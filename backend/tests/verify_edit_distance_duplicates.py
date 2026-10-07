"""Provera tačaka B (razdaljina izmene) i C (mogući duplikati) kroz rute.

Pokretanje (iz foldera backend/):
    python tests/verify_edit_distance_duplicates.py

LAŽNI provajder (requests.post je zamenjen) - nijedan pravi AI servis se ne
poziva. Privremeni run-ovi, predlozi, ocene i nova pitanja se brišu po
zabeleženim id-jevima; na kraju se porede brojevi redova.

Svaka migracija (db/migration_edit_distance.sql, db/migration_duplicate_check.sql)
se proverava nezavisno: pre nje - da sve radi kao ranije (i jasan 409 gde
treba), posle nje - da se vrednosti upisuju; slučajevi koji traže migraciju
koja nije pokrenuta se označavaju PRESKOCENO.
"""
import contextlib
import io
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
import backfill_edit_distance  # noqa: E402
import edit_distance as ed  # noqa: E402
import recompute_similarity  # noqa: E402
from app import (  # noqa: E402
    DUPLICATE_COLUMNS,
    EDIT_DISTANCE_COLUMNS,
    app,
    get_db_connection,
    question_labels_enabled,
    table_columns_exist,
)

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_prompts",
                "exam_questions", "exam_answers")
MODEL_FIELDS = ("provider", "model_name", "created_at", "generation_run_id", "model_difficulty", "model_bloom_level")
DUP_FIELDS = ("max_similarity", "possible_duplicate", "similar_source", "similar_question_id",
              "similar_question_text", "reviewed_duplicate")

results = []
created = {"runs": [], "artifacts": [], "prompts_before": set()}
client = app.test_client()


# ---------- baza ----------

def db_all(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def db_one(sql, params=()):
    rows = db_all(sql, params)
    return rows[0] if rows else None


def db_exec(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def enabled(columns):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return table_columns_exist(cur, "ai_generated_artifacts", columns)
    finally:
        cur.close()
        conn.close()


def labels_on():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return question_labels_enabled(cur)
    finally:
        cur.close()
        conn.close()


def row_counts():
    return {t: db_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in COUNT_TABLES}


def artifacts_snapshot(exclude=()):
    rows = db_all("SELECT * FROM ai_generated_artifacts ORDER BY id")
    return [{k: v for k, v in row.items() if k not in exclude} for row in rows]


def cleanup():
    arts, runs = created["artifacts"], created["runs"]

    def ph(ids):
        return ",".join(["%s"] * len(ids))

    if arts:
        questions = [r["created_question_id"] for r in db_all(
            f"SELECT created_question_id FROM ai_generated_artifacts WHERE id IN ({ph(arts)}) AND created_question_id IS NOT NULL", arts)]
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
        if questions:
            db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(questions)})", questions)
            db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(questions)})", questions)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    for row in db_all("SELECT id FROM ai_prompts"):
        if row["id"] not in created["prompts_before"] and not db_all(
                "SELECT 1 FROM ai_generation_runs WHERE prompt_id = %s LIMIT 1", (row["id"],)):
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (row["id"],))


# ---------- lazni provajder i pomocne ----------

class FakeResponse:
    def __init__(self, body):
        self.status_code, self.headers, self._body, self.text = 200, {}, body, json.dumps(body)

    def json(self):
        return self._body


def model_returns(payload):
    body = {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 1}}
    requests.post = lambda *a, **k: FakeResponse(body)


def generate(source_id, payload, h):
    model_returns(payload)
    r = client.post(f"/api/questions/{source_id}/generate-similar?provider=groq", headers=h)
    body = r.get_json() or {}
    if body.get("generation_run_id"):
        created["runs"].append(body["generation_run_id"])
    if body.get("artifact_id"):
        created["artifacts"].append(body["artifact_id"])
    return r.status_code, body


def review(art_id, h, decision, **extra):
    detail = client.get(f"/api/ai/artifacts/{art_id}", headers=h).get_json()
    body = {"decision": decision, "scores": [{"rubric_definition_id": c["id"], "score": 3} for c in detail["rubric_criteria"]],
            **extra}
    if decision == "odbaceno":
        body.setdefault("rejection_reason", "probno")
    if detail.get("labels_required") and decision != "odbaceno":
        body.setdefault("reviewed_difficulty", "srednje")
        body.setdefault("reviewed_bloom_level", "primena")
    r = client.post(f"/api/ai/artifacts/{art_id}/review", headers=h, json=body)
    return r.status_code, r.get_json() or {}


def run_tool(module, args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main(args)
    return code, out.getvalue()


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


# ---------- provere ----------

def run():
    b_on, c_on = enabled(EDIT_DISTANCE_COLUMNS), enabled(DUPLICATE_COLUMNS)
    print(f"Migracija razdaljine izmene: {'POKRENUTA' if b_on else 'NIJE pokrenuta'}; "
          f"provere duplikata: {'POKRENUTA' if c_on else 'NIJE pokrenuta'}")

    with app.app_context():
        admin = {"Authorization": "Bearer " + create_access_token(identity="1", additional_claims={"role": "ADMIN", "email": "x"})}

    src = db_one("""SELECT q.id, q.question_text FROM exam_questions q JOIN exam_answers a ON a.question_id = q.id
                    WHERE q.subject_id IS NOT NULL GROUP BY q.id, q.question_text
                    HAVING SUM(a.is_correct) = 1 AND COUNT(*) >= 2 ORDER BY q.id DESC LIMIT 1""")
    source_answers = db_all("SELECT answer_text, is_correct FROM exam_answers WHERE question_id = %s ORDER BY id", (src["id"],))
    n = len(source_answers)
    labels = {"difficulty": "lako", "bloom_level": "pamcenje"}
    copy_of_source = {"question_text": src["question_text"],
                      "answers": [{"answer_text": a["answer_text"], "is_correct": bool(a["is_correct"])} for a in source_answers],
                      **labels}
    different = {"question_text": "Koliko nogu ima pauk prema ovom potpuno drugačijem probnom pitanju?",
                 "answers": [{"answer_text": f"{i + 6}", "is_correct": i == 2} for i in range(n)], **labels}

    # --- generisanje (kopija izvora i razlicito pitanje) ---
    code_copy, body_copy = generate(src["id"], copy_of_source, admin)
    code_diff, body_diff = generate(src["id"], different, admin)
    record("generisanje radi (pre i posle migracije)", "201, 201", f"{code_copy}, {code_diff}", code_copy == 201 and code_diff == 201)
    copy_id, diff_id = body_copy.get("artifact_id"), body_diff.get("artifact_id")

    detail_copy = client.get(f"/api/ai/artifacts/{copy_id}", headers=admin).get_json()
    listed = {r["id"]: r for r in client.get("/api/ai/artifacts?status=predlog", headers=admin).get_json()}
    leaked = [k for k in MODEL_FIELDS if k in detail_copy] + [k for k in MODEL_FIELDS if k in listed.get(copy_id, {})]
    record("slepo: detalj i lista bez modela (sa poljima duplikata)", "bez provider/model/vremena/oznaka modela",
           f"procurelo: {leaked or 'nista'}", not leaked)

    # --- C: duplikati ---
    if not c_on:
        record("C pre migracije: bez polja duplikata u odgovoru", "nema polja",
               f"{[k for k in DUP_FIELDS if k in detail_copy] or 'nema'}", not any(k in detail_copy for k in DUP_FIELDS))
        code, body = review(diff_id, admin, "odbaceno", reviewed_duplicate=True)
        record("C pre migracije: reviewed_duplicate -> 409", "409, bez upisa",
               f"{code} {body.get('error')}, status={db_one('SELECT status FROM ai_generated_artifacts WHERE id=%s', (diff_id,))['status']}",
               code == 409 and db_one("SELECT status FROM ai_generated_artifacts WHERE id = %s", (diff_id,))["status"] == "predlog")
        before = artifacts_snapshot()
        code, out = run_tool(recompute_similarity, ["--dry-run"])
        record("C recompute --dry-run pre migracije", "exit 0, baza nepromenjena",
               f"exit {code}, nepromenjeno={artifacts_snapshot() == before}", code == 0 and artifacts_snapshot() == before)
        code, out = run_tool(recompute_similarity, [])
        record("C recompute bez migracije", "exit 2 sa porukom", f"exit {code}: {out.strip()[:60]}", code == 2)
        for case in ("C generisanje upisuje sličnost", "C kopija izvora = mogući duplikat", "C različito pitanje nije duplikat",
                     "C potvrda nastavnika upisana", "C ponovni izračun menja samo kolone sličnosti"):
            skip(case, "migracija duplikata nije pokrenuta")
    else:
        row = db_one("SELECT max_similarity, similar_source, similar_question_id FROM ai_generated_artifacts WHERE id = %s", (copy_id,))
        record("C generisanje upisuje sličnost", "1.000 / source / izvorno pitanje",
               f"{row['max_similarity']} / {row['similar_source']} / #{row['similar_question_id']}",
               float(row["max_similarity"]) == 1.0 and row["similar_source"] == "source" and row["similar_question_id"] == src["id"])
        record("C kopija izvora = mogući duplikat", "possible_duplicate=true, tekst sličnog pitanja",
               f"{detail_copy.get('possible_duplicate')}, tekst={'da' if detail_copy.get('similar_question_text') else 'ne'}, u listi={listed.get(copy_id, {}).get('possible_duplicate')}",
               detail_copy.get("possible_duplicate") is True and detail_copy.get("similar_question_text") == src["question_text"]
               and listed.get(copy_id, {}).get("possible_duplicate") is True)
        detail_diff = client.get(f"/api/ai/artifacts/{diff_id}", headers=admin).get_json()
        record("C različito pitanje nije duplikat", "possible_duplicate=false",
               f"{detail_diff.get('possible_duplicate')} ({detail_diff.get('max_similarity')})", detail_diff.get("possible_duplicate") is False)

        code, body = review(copy_id, admin, "odbaceno", reviewed_duplicate=True)
        stored = db_one("SELECT reviewed_duplicate FROM ai_generated_artifacts WHERE id = %s", (copy_id,))["reviewed_duplicate"]
        record("C potvrda nastavnika upisana", "200, reviewed_duplicate=1", f"{code}, {stored}", code == 200 and stored == 1)

        sim_cols = ("max_similarity", "similar_source", "similar_question_id", "similar_artifact_id")
        before_other = artifacts_snapshot(exclude=sim_cols)
        before_sim = db_all(f"SELECT id, {', '.join(sim_cols)} FROM ai_generated_artifacts WHERE id IN (%s, %s) ORDER BY id", (copy_id, diff_id))
        run_tool(recompute_similarity, ["--artifact", str(copy_id)])
        run_tool(recompute_similarity, ["--artifact", str(diff_id)])
        after_sim = db_all(f"SELECT id, {', '.join(sim_cols)} FROM ai_generated_artifacts WHERE id IN (%s, %s) ORDER BY id", (copy_id, diff_id))
        record("C ponovni izračun menja samo kolone sličnosti", "ostale kolone iste; sličnost ista kao pri generisanju",
               f"ostalo isto={artifacts_snapshot(exclude=sim_cols) == before_other}, sličnost ista={after_sim == before_sim}",
               artifacts_snapshot(exclude=sim_cols) == before_other and after_sim == before_sim)

    code, body = review(diff_id, admin, "odbaceno", reviewed_duplicate="da") if db_one(
        "SELECT status FROM ai_generated_artifacts WHERE id = %s", (diff_id,))["status"] == "predlog" else (None, {})
    if code is not None:
        record("reviewed_duplicate pogrešnog tipa", "400", f"{code} {body.get('error')}", code == 400)

    # --- B: razdaljina izmene ---
    if not labels_on():
        skip("B izmena kroz rutu", "potrebna je i migracija oznaka (v3 prihvatanje)")
        return
    _, body_edit = generate(src["id"], different, admin)
    edit_id = body_edit.get("artifact_id")
    edited = {"question_text": different["question_text"].replace("pauk", "mrav"),
              "answers": [{"answer_text": f"{i + 6}", "is_correct": i == 0} for i in range(n)]}
    code, body = review(edit_id, admin, "prihvaceno_izmena", edited_text=edited)
    expected = ed.edit_distance(different, edited)
    _, body_plain = generate(src["id"], different, admin)
    code_plain, _ = review(body_plain["artifact_id"], admin, "prihvaceno")
    if not b_on:
        record("B izmena pre migracije", "200 (bez upisa razdaljine)", f"{code} {body.get('status') or body.get('error')}", code == 200)
        before = artifacts_snapshot()
        code, out = run_tool(backfill_edit_distance, ["--dry-run"])
        record("B backfill --dry-run pre migracije", "exit 0, baza nepromenjena",
               f"exit {code}, nepromenjeno={artifacts_snapshot() == before}", code == 0 and artifacts_snapshot() == before)
        code, out = run_tool(backfill_edit_distance, [])
        record("B backfill bez migracije", "exit 2 sa porukom", f"exit {code}: {out.strip()[:60]}", code == 2)
        for case in ("B ruta upisuje razdaljinu za izmenu", "B bez izmene ostaje NULL", "B backfill dopunjuje samo NULL"):
            skip(case, "migracija razdaljine nije pokrenuta")
    else:
        row = db_one("SELECT edit_distance, edit_distance_norm FROM ai_generated_artifacts WHERE id = %s", (edit_id,))
        record("B ruta upisuje razdaljinu za izmenu", f"{expected['total']} / {expected['normalized']}",
               f"{code}, {row['edit_distance']} / {row['edit_distance_norm']}",
               code == 200 and row["edit_distance"] == expected["total"] and float(row["edit_distance_norm"]) == expected["normalized"])
        row = db_one("SELECT edit_distance FROM ai_generated_artifacts WHERE id = %s", (body_plain["artifact_id"],))
        record("B bez izmene ostaje NULL", "200, NULL", f"{code_plain}, {row['edit_distance']}", code_plain == 200 and row["edit_distance"] is None)
        db_exec("UPDATE ai_generated_artifacts SET edit_distance = NULL, edit_distance_norm = NULL WHERE id = %s", (edit_id,))
        before_other = artifacts_snapshot(exclude=EDIT_DISTANCE_COLUMNS)
        before_values = db_all("SELECT id, edit_distance FROM ai_generated_artifacts WHERE edit_distance IS NOT NULL ORDER BY id")
        run_tool(backfill_edit_distance, [])
        row = db_one("SELECT edit_distance FROM ai_generated_artifacts WHERE id = %s", (edit_id,))
        unchanged = [r for r in db_all("SELECT id, edit_distance FROM ai_generated_artifacts WHERE edit_distance IS NOT NULL ORDER BY id")
                     if r["id"] != edit_id]
        record("B backfill dopunjuje samo NULL", f"#{edit_id} dobija {expected['total']}, ostalo isto",
               f"{row['edit_distance']}, ranije upisane iste={unchanged == [r for r in before_values if r['id'] != edit_id]}, ostale kolone iste={artifacts_snapshot(exclude=EDIT_DISTANCE_COLUMNS) == before_other}",
               row["edit_distance"] == expected["total"] and artifacts_snapshot(exclude=EDIT_DISTANCE_COLUMNS) == before_other)


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 60 else e[:57] + "...", g if len(g) <= 85 else g[:82] + "...", s) for c, e, g, s in results]
    widths = [max(len(str(r[i])) for r in rows + [head]) for i in range(4)]
    line = " | ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    failed = sum(1 for r in results if r[3] == "PALO")
    skipped = sum(1 for r in results if r[3] == "PRESKOCENO")
    print(f"\nUkupno: {len(results)}, palo: {failed}, preskoceno: {skipped}")
    return failed


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    real_post, real_sleep = requests.post, ai_provider.time.sleep
    ai_provider.time.sleep = lambda s: None
    created["prompts_before"] = {r["id"] for r in db_all("SELECT id FROM ai_prompts")}
    before = row_counts()
    try:
        run()
    finally:
        requests.post, ai_provider.time.sleep = real_post, real_sleep
        cleanup()
        after = row_counts()
        changed = {t: (before[t], after[t]) for t in COUNT_TABLES if before[t] != after[t]}
        record("brojevi redova u bazi pre/posle", "isti", "isti" if not changed else str(changed), not changed)
    sys.exit(1 if print_table() else 0)
