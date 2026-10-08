"""Provera tačke G: CSV izvoz serije, agregatni SQL upiti i analiza nad izvozom.

Pokretanje (iz foldera backend/):
    python tests/verify_experiment_export.py

Bez AI poziva: izmišljeni run-ovi i predlozi se upisuju direktno u bazu, u
privremenu seriju (plus jedan probni run BEZ serije, koji ne sme da uđe ni u
izvoz ni u upite). Sve se briše po zabeleženim id-jevima i porede se brojevi
redova pre i posle.
"""
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from contextlib import redirect_stdout

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

from app import app, get_db_connection, anonymize_user  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import analyze_experiment as ax  # noqa: E402

SQL_FILE = os.path.join(ROOT, "db", "queries", "eksperiment_po_modelu.sql")
COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_label_evaluations",
                "evaluation_batches", "users")
TAG = uuid.uuid4().hex[:6]

results = []
created = {"users": [], "batches": [], "runs": [], "artifacts": []}
client = app.test_client()


def db_all(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def db_exec(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def row_counts():
    return {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in COUNT_TABLES}


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def headers(user_id, role):
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": f"verify-{user_id}"})
    return {"Authorization": f"Bearer {token}"}


def lookup_id(sql, params):
    rows = db_all(sql, params)
    if not rows:
        raise SystemExit(f"Nedostaje u bazi: {sql % params}")
    return rows[0]["id"]


# ---------- izmisljeni podaci ----------

def make_user(name):
    uid = db_exec("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', 2, %s, 1)",
                  (f"tmp-exp-{name}-{TAG}@example.invalid", f"TmpIme{name}{TAG}"))
    created["users"].append(uid)
    return uid


def make_run(model_id, prompt_id, purpose, batch_id, passed, failure=None, first=None, retries=0, ms=None, params=None):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, params_used, validation_passed, failure_type,
               first_attempt_passed, format_retries, response_time_ms, tokens_used, evaluation_batch_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 100, %s)
    """, (model_id, prompt_id, purpose, json.dumps(params or {"attempts": 1}), passed, failure, first, retries, ms, batch_id))
    created["runs"].append(rid)
    return rid


def make_artifact(run_id, status, reviewer, md, mb, rd=None, rb=None, ed=None, edn=None, sim=None, dup=None, mc=True):
    body = {"question_text": f"Izmisljeno {TAG}", "difficulty": md, "bloom_level": mb}
    if mc:
        body["answers"] = [{"answer_text": "a", "is_correct": True}, {"answer_text": "b", "is_correct": False}]
    aid = db_exec("""
        INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text, reviewed_by,
               model_difficulty, model_bloom_level, reviewed_difficulty, reviewed_bloom_level, edit_distance,
               edit_distance_norm, max_similarity, similar_source, reviewed_duplicate)
        VALUES (%s, 'question', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (run_id, status, json.dumps(body), reviewer, md, mb, rd, rb, ed, edn, sim, "bank" if sim else None, dup))
    created["artifacts"].append(aid)
    return aid


def score(artifact_id, rubric, evaluator, rnd, value):
    db_exec("INSERT INTO ai_evaluations (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, evaluation_round) "
            "VALUES (%s, %s, %s, 'TEACHER', %s, %s)", (artifact_id, rubric, evaluator, value, rnd))


def cleanup():
    def ph(ids):
        return ",".join(["%s"] * len(ids))
    arts, runs = created["artifacts"], created["runs"]
    if arts:
        db_exec(f"DELETE FROM ai_label_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    if created["batches"]:
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph(created['batches'])})", created["batches"])
    if created["users"]:
        db_exec(f"DELETE FROM users WHERE id IN ({ph(created['users'])})", created["users"])


def sql_queries(batch_id):
    """Upiti iz db/queries/eksperiment_po_modelu.sql, ograničeni na jednu seriju (kao što piše u fajlu)."""
    with open(SQL_FILE, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("r.evaluation_batch_id IS NOT NULL  -- FILTER_SERIJA", f"r.evaluation_batch_id = {int(batch_id)}")
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    return [q.strip() for q in text.split(";") if q.strip()]


def get_csv(batch_id, kind, role="ADMIN", user_id=1):
    resp = client.get(f"/api/evaluation-batches/{batch_id}/export.csv?kind={kind}", headers=headers(user_id, role))
    text = resp.get_data(as_text=True)
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿")))) if resp.status_code == 200 else []
    return resp, text, rows


# ---------- provere ----------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    groq = lookup_id("SELECT id FROM ai_models WHERE provider = %s AND model_name = %s", ("groq", "openai/gpt-oss-20b"))
    gemini = lookup_id("SELECT id FROM ai_models WHERE provider = %s AND model_name = %s", ("gemini", "gemini-3.6-flash"))
    p_mc = lookup_id("SELECT id FROM ai_prompts WHERE purpose = %s AND version = %s", ("similar_question", "mc-v3"))
    p_set = lookup_id("SELECT id FROM ai_prompts WHERE purpose = %s AND version = %s", ("similar_question_set", "set-v1"))
    r_tacnost = lookup_id("SELECT id FROM ai_rubric_definitions WHERE dimension_key = %s AND applies_to = 'question'", ("strucna_tacnost",))
    r_relev = lookup_id("SELECT id FROM ai_rubric_definitions WHERE dimension_key = %s AND applies_to = 'question'", ("relevantnost",))
    admin = db_all("SELECT id FROM users WHERE role_id = 1 ORDER BY id LIMIT 1")[0]["id"]

    before = row_counts()
    tmp_dir = tempfile.mkdtemp()
    try:
        teacher, second, third = make_user("A"), make_user("B"), make_user("C")
        batch = db_exec("INSERT INTO evaluation_batches (name) VALUES (%s)", (f"tmp-export-{TAG}",))
        created["batches"].append(batch)

        # groq, jedno pitanje: 2 uspešna (od toga 1 posle ponovnog zahteva), 1 http_5xx, 1 invalid_json
        g1 = make_run(groq, p_mc, "similar_question", batch, 1, first=1, ms=100, params={"attempts": 1, "input_question_ids": [11]})
        g2 = make_run(groq, p_mc, "similar_question", batch, 1, first=0, retries=1, ms=300)
        make_run(groq, p_mc, "similar_question", batch, 0, failure="http_5xx", ms=900)
        make_run(groq, p_mc, "similar_question", batch, 0, failure="invalid_json", first=0, retries=1, ms=500)
        # gemini, skup: 1 uspešan run sa 2 predloga
        s1 = make_run(gemini, p_set, "similar_question_set", batch, 1, first=1, ms=2000,
                      params={"attempts": 1, "input_question_ids": [11, 12, 13], "set_items": {"accepted": 2, "rejected": []}})
        # probni run BEZ serije - ne sme da uđe nigde
        probe = make_run(groq, p_mc, "similar_question", None, 1, first=1, ms=50)
        make_artifact(probe, "prihvaceno", teacher, "lako", "pamcenje", "lako", "pamcenje")

        a1 = make_artifact(g1, "prihvaceno", teacher, "lako", "primena", "lako", "primena", sim=0.95, dup=1)
        a2 = make_artifact(g2, "prihvaceno_izmena", teacher, "srednje", "analiza", "tesko", "analiza", ed=40, edn=0.2)
        a3 = make_artifact(s1, "odbaceno", teacher, "tesko", "primena", "tesko", "razumevanje", sim=0.5, mc=False)
        a4 = make_artifact(s1, "predlog", None, "lako", "pamcenje")
        for aid, (t, r) in {a1: (5, 4), a2: (3, 4), a3: (2, 3)}.items():
            score(aid, r_tacnost, teacher, 1, t)
            score(aid, r_relev, teacher, 1, r)
        for aid, (t, r) in {a1: (4, 4), a2: (3, 5)}.items():
            score(aid, r_tacnost, second, 2, t)
            score(aid, r_relev, second, 2, r)
        score(a1, r_tacnost, third, 2, 1)
        db_exec("INSERT INTO ai_label_evaluations (artifact_id, evaluator_id, evaluator_role, difficulty, bloom_level) "
                "VALUES (%s, %s, 'TEACHER', 'lako', 'primena'), (%s, %s, 'TEACHER', 'srednje', 'analiza')",
                (a1, second, a2, second))
        db_exec("INSERT INTO ai_label_evaluations (artifact_id, evaluator_id, evaluator_role, difficulty, bloom_level) "
                "VALUES (%s, %s, 'TEACHER', 'tesko', 'primena')", (a1, third))

        # --- pristup ruti ---
        resp, _, _ = get_csv(batch, "artifacts", role="TEACHER", user_id=teacher)
        record("TEACHER -> izvoz", 403, resp.status_code, resp.status_code == 403)
        resp, _, _ = get_csv(batch, "artifacts", role="STUDENT", user_id=teacher)
        record("STUDENT -> izvoz", 403, resp.status_code, resp.status_code == 403)
        resp = client.get(f"/api/evaluation-batches/{batch}/export.csv")
        record("bez tokena -> izvoz", 401, resp.status_code, resp.status_code == 401)
        missing = db_all("SELECT COALESCE(MAX(id), 0) + 1000 AS id FROM evaluation_batches")[0]["id"]
        resp, _, _ = get_csv(missing, "artifacts", user_id=admin)
        record("nepostojeca serija", 404, resp.status_code, resp.status_code == 404)
        resp, _, _ = get_csv(batch, "nesto", user_id=admin)
        record("nepoznat kind", 400, resp.status_code, resp.status_code == 400)

        # --- kind=artifacts ---
        resp, text_a, arts = get_csv(batch, "artifacts", user_id=admin)
        record("artifacts: status i tip", "200 text/csv attachment",
               f"{resp.status_code} {resp.mimetype} {resp.headers.get('Content-Disposition', '')[:10]}",
               resp.status_code == 200 and resp.mimetype == "text/csv"
               and resp.headers.get("Content-Disposition", "").startswith("attachment"))
        ids = [int(r["artifact_id"]) for r in arts]
        record("artifacts: red po predlogu, bez probe", [a1, a2, a3, a4], ids, ids == [a1, a2, a3, a4])
        by_id = {int(r["artifact_id"]): r for r in arts}
        r1 = by_id[a1]
        record("model / verzija prompta / rezim", "groq openai/gpt-oss-20b mc-v3 single",
               f"{r1['provider']} {r1['model_name']} {r1['prompt_version']} {r1['mode']}",
               (r1["provider"], r1["model_name"], r1["prompt_version"], r1["mode"]) == ("groq", "openai/gpt-oss-20b", "mc-v3", "single"))
        record("skup: rezim i ulazna pitanja", "set 11;12;13", f"{by_id[a3]['mode']} {by_id[a3]['input_question_ids']}",
               by_id[a3]["mode"] == "set" and by_id[a3]["input_question_ids"] == "11;12;13")
        record("odlucuje = hes nastavnika", anonymize_user(teacher), r1["decider"], r1["decider"] == anonymize_user(teacher))
        record("druga ocena = hes prvog drugog ocenjivaca, broj 2",
               f"{anonymize_user(second)} 2", f"{r1['second_rater']} {r1['second_raters_count']}",
               r1["second_rater"] == anonymize_user(second) and r1["second_raters_count"] == "2")
        record("oznake model / nastavnik / druga", "lako primena lako primena lako primena",
               " ".join(r1[k] for k in ("model_difficulty", "model_bloom_level", "reviewed_difficulty", "reviewed_bloom_level",
                                        "second_difficulty", "second_bloom_level")),
               (r1["model_difficulty"], r1["reviewed_difficulty"], r1["second_difficulty"], r1["second_bloom_level"])
               == ("lako", "lako", "lako", "primena"))
        record("ocene r1/r2", "r1 5/4, r2 4/4", f"r1 {r1['r1_strucna_tacnost']}/{r1['r1_relevantnost']}, "
                                                 f"r2 {r1['r2_strucna_tacnost']}/{r1['r2_relevantnost']}",
               (r1["r1_strucna_tacnost"], r1["r1_relevantnost"], r1["r2_strucna_tacnost"], r1["r2_relevantnost"]) == ("5", "4", "4", "4"))
        r2 = by_id[a2]
        record("odluka i razdaljina izmene", "prihvaceno_izmena 40 0.2000",
               f"{r2['status']} {r2['edit_distance']} {r2['edit_distance_norm']}",
               (r2["status"], r2["edit_distance"], r2["edit_distance_norm"]) == ("prihvaceno_izmena", "40", "0.2000"))
        record("duplikat-oznaka", "a1: 1/1, a3: 0", f"a1: {r1['possible_duplicate']}/{r1['reviewed_duplicate']}, a3: {by_id[a3]['possible_duplicate']}",
               r1["possible_duplicate"] == "1" and r1["reviewed_duplicate"] == "1" and by_id[a3]["possible_duplicate"] == "0")
        record("predlog na cekanju: bez odluke i ocena", "prazno", f"{by_id[a4]['decider']!r} {by_id[a4]['r1_strucna_tacnost']!r}",
               by_id[a4]["status"] == "predlog" and by_id[a4]["decider"] == "" and by_id[a4]["r1_strucna_tacnost"] == "")

        # --- kind=runs i kind=evaluations ---
        _, text_r, runs = get_csv(batch, "runs", user_id=admin)
        run_ids = sorted(int(r["run_id"]) for r in runs)
        record("runs: samo serija (bez probe)", 5, len(runs), len(runs) == 5 and probe not in run_ids)
        failures = sorted(r["failure_type"] for r in runs if r["failure_type"])
        record("runs: vrste pada", ["http_5xx", "invalid_json"], failures, failures == ["http_5xx", "invalid_json"])
        _, text_e, evals = get_csv(batch, "evaluations", user_id=admin)
        ordinal = [r for r in evals if r["level"] == "ordinal"]
        nominal = [r for r in evals if r["level"] == "nominal"]
        # ocene: 3x2 runda 1 + 2x2 + 1 runda 2 = 11; oznake: (3 nastavnik + 3 drugi) x 2 = 12
        record("evaluations: broj redova", "11 ordinal + 12 nominal", f"{len(ordinal)} + {len(nominal)}",
               len(ordinal) == 11 and len(nominal) == 12)

        # --- anonimnost ---
        leaked = [s for s in ("example.invalid", "tmp-exp-", f"TmpIme", "@") if s in text_a + text_r + text_e]
        record("bez emailova i imena u izvozu", [], leaked, not leaked)
        hashes = {r["evaluator"] for r in evals}
        expected_hashes = {anonymize_user(teacher), anonymize_user(second), anonymize_user(third)}
        record("hesevi ocenjivaca dosledni u izvozima", "3 hesa", len(hashes), hashes == expected_hashes)
        record("hes nije id", "u_ + 12 hex, razlicit od id-ja", r1["decider"],
               re.fullmatch(r"u_[0-9a-f]{12}", r1["decider"]) is not None and r1["decider"] != f"u_{teacher}")

        # --- SQL upiti iz db/queries ---
        q_runs, q_arts, q_scores = [db_all(q) for q in sql_queries(batch)]
        g = next(r for r in q_runs if r["provider"] == "groq")
        record("SQL A groq: pokusaja/uspesnih/iz prve/ponovni", "4/2/1/2",
               f"{g['pokusaja']}/{g['uspesnih']}/{g['prosao_iz_prve']}/{g['sa_ponovnim_zahtevom']}",
               (int(g["pokusaja"]), int(g["uspesnih"]), int(g["prosao_iz_prve"]), int(g["sa_ponovnim_zahtevom"])) == (4, 2, 1, 2))
        record("SQL A groq: padovi http_5xx/invalid_json/network", "1/1/0",
               f"{g['pad_http_5xx']}/{g['pad_invalid_json']}/{g['pad_network']}",
               (int(g["pad_http_5xx"]), int(g["pad_invalid_json"]), int(g["pad_network"])) == (1, 1, 0))
        record("SQL A groq: stope", "uspeh 50.0, formalno iz prve 33.3, bez odgovora 25.0",
               f"{g['stopa_uspeha_pct']}, {g['formalna_ispravnost_iz_prve_pct']}, {g['bez_odgovora_pct']}",
               (float(g["stopa_uspeha_pct"]), float(g["formalna_ispravnost_iz_prve_pct"]), float(g["bez_odgovora_pct"])) == (50.0, 33.3, 25.0))
        record("SQL A groq: prosek i medijana ms", "450 / 400", f"{g['prosek_ms']} / {g['medijana_ms']}",
               int(g["prosek_ms"]) == 450 and float(g["medijana_ms"]) == 400)
        record("SQL A: rezimi odvojeni, proba iskljucena", 2, len(q_runs), len(q_runs) == 2)
        ga = next(r for r in q_arts if r["provider"] == "groq")
        sa = next(r for r in q_arts if r["provider"] == "gemini")
        record("SQL B groq: predloga/prihv/izmena/razdaljina", "2/1/1/40.0",
               f"{ga['predloga']}/{ga['prihvaceno']}/{ga['prihvaceno_izmena']}/{ga['prosek_razdaljine']}",
               (int(ga["predloga"]), int(ga["prihvaceno"]), int(ga["prihvaceno_izmena"]), float(ga["prosek_razdaljine"])) == (2, 1, 1, 40.0))
        record("SQL B gemini skup: odbaceno/na cekanju/odbaceno_pct", "1/1/100.0",
               f"{sa['odbaceno']}/{sa['na_cekanju']}/{sa['odbaceno_pct']}",
               (int(sa["odbaceno"]), int(sa["na_cekanju"]), float(sa["odbaceno_pct"])) == (1, 1, 100.0))
        record("SQL B: duplikati i raspodela oznaka", "dup 1/1, model_lako 1, nast_tesko 1",
               f"dup {ga['mogucih_duplikata']}/{ga['potvrdjenih_duplikata']}, model_lako {ga['model_lako']}, nast_tesko {ga['nast_tesko']}",
               (int(ga["mogucih_duplikata"]), int(ga["potvrdjenih_duplikata"]), int(ga["model_lako"]), int(ga["nast_tesko"])) == (1, 1, 1, 1))
        csv_status = sorted(r["status"] for r in arts)
        sql_total = sum(int(r["predloga"]) for r in q_arts)
        record("SQL B i CSV izvoz: isti broj predloga", len(csv_status), sql_total, sql_total == len(csv_status))
        sc = {(r["provider"], r["kriterijum"]): r for r in q_scores}
        gt = sc.get(("groq", "strucna_tacnost"), {})
        dist = [int(gt.get(f"ocena_{v}", -1)) for v in range(1, 6)]
        record("SQL C groq strucna_tacnost: raspodela 1-5, broj, prosek", "[0, 0, 1, 0, 1] 2 4.0",
               f"{dist} {gt.get('broj_ocena')} {gt.get('prosek')}",
               dist == [0, 0, 1, 0, 1] and int(gt.get("broj_ocena", 0)) == 2 and float(gt.get("prosek", 0)) == 4.0)
        record("SQL C: samo runda 1 nastavnika koji odlucuje", "4 reda (2 modela x 2 kriterijuma), gemini 1 ocena",
               f"{len(q_scores)} redova, gemini {sc.get(('gemini', 'strucna_tacnost'), {}).get('broj_ocena')}",
               len(q_scores) == 4 and int(sc[("gemini", "strucna_tacnost")]["broj_ocena"]) == 1)

        # --- analiza nad pravim izvozom ---
        paths = {}
        for kind, text in (("artifacts", text_a), ("runs", text_r), ("evaluations", text_e)):
            paths[kind] = os.path.join(tmp_dir, f"serija_{kind}.csv")
            with open(paths[kind], "w", encoding="utf-8", newline="") as f:
                f.write(text)
        with redirect_stdout(io.StringIO()):
            result = ax.analyze(paths["artifacts"], paths["runs"], paths["evaluations"], os.path.join(tmp_dir, "izlaz"))
        kappa = next(r for r in result["agreement"] if r["stavka"] == "strucna_tacnost")
        record("analiza izvoza: kapa nad 2 para", 2, kappa["parova"], kappa["parova"] == 2 and kappa["kapa"] is not None)
        record("analiza izvoza: alfa i sa trecim ocenjivacem", "broj", kappa["alfa"], kappa["alfa"] is not None)
        dist_rows = ax.read_csv(os.path.join(tmp_dir, "izlaz", "tabela_raspodela_ocena.csv"))
        same = all(
            [int(r[f"ocena_{v}"]) for v in range(1, 6)]
            == [int(sc[(r["model"].split("/")[0], r["kriterijum"])][f"ocena_{v}"]) for v in range(1, 6)]
            for r in dist_rows)
        record("analiza i SQL C: ista raspodela ocena", "jednako", "jednako" if same and len(dist_rows) == 4 else "razlicito",
               same and len(dist_rows) == 4)
        record("analiza izvoza: izvestaj", "postoji", "postoji" if os.path.exists(os.path.join(tmp_dir, "izlaz", "izvestaj.md")) else "nema",
               os.path.exists(os.path.join(tmp_dir, "izlaz", "izvestaj.md")))
    finally:
        cleanup()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    after = row_counts()
    record("brojevi redova pre = posle", before, after, before == after)

    width = max(len(r[0]) for r in results)
    for case, expected, got, status in results:
        print(f"{status:4}  {case:<{width}}  ocekivano: {expected}  dobijeno: {got}")
    failed = sum(r[3] == "PALO" for r in results)
    print(f"\n{len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
