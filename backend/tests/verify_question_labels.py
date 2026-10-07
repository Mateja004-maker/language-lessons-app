"""Provera tačke A: težina i Blumov nivo za AI predloge pitanja (v3 prompt).

Pokretanje (iz foldera backend/):
    python tests/verify_question_labels.py

Kroz stvarne rute (app.test_client()) nad bazom iz backend/.env, sa LAŽNIM
provajderom (requests.post je zamenjen) - nijedan pravi AI servis se ne
poziva. Privremeni run-ovi, predlozi, ocene i nova pitanja se brišu po
zabeleženim id-jevima (i kad provera padne); na kraju se porede brojevi redova.

Ako db/migration_question_labels.sql još nije pokrenuta, slučajevi koji
pišu u nove kolone se označavaju kao PRESKOCENO, a proverava se da v3
prihvatanje vraća 409 bez upisa. Posle migracije skript proverava i upis.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
from app import app, get_db_connection, question_labels_enabled  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_prompts",
                "ai_models", "exam_questions", "exam_answers")
LABEL_KEYS = ("model_difficulty", "model_bloom_level")

results = []
created = {"runs": [], "artifacts": [], "prompts": []}
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
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def row_counts():
    return {t: db_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in COUNT_TABLES}


def labels_enabled():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return question_labels_enabled(cur)
    finally:
        cur.close()
        conn.close()


def cleanup():
    arts = created["artifacts"]
    runs = created["runs"]

    def ph(ids):
        return ",".join(["%s"] * len(ids))

    if arts:
        new_questions = [r["created_question_id"] for r in db_all(
            f"SELECT created_question_id FROM ai_generated_artifacts WHERE id IN ({ph(arts)}) AND created_question_id IS NOT NULL", arts)]
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
        if new_questions:
            db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(new_questions)})", new_questions)
            db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(new_questions)})", new_questions)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    for prompt_id in created["prompts"]:
        # samo ako ga ne koristi nijedan run van ove provere
        if db_one("SELECT COUNT(*) AS n FROM ai_generation_runs WHERE prompt_id = %s", (prompt_id,))["n"] == 0:
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (prompt_id,))


# ---------- lazni provajder ----------

class FakeResponse:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {}
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def model_returns(payload):
    body = {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 1}}
    requests.post = lambda *a, **k: FakeResponse(body)


def headers(user_id, role):
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": f"verify-{user_id}"})
    return {"Authorization": f"Bearer {token}"}


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


# ---------- pomocno ----------

def generate(source_id, payload, h):
    model_returns(payload)
    r = client.post(f"/api/questions/{source_id}/generate-similar?provider=groq", headers=h)
    body = r.get_json() or {}
    if body.get("generation_run_id"):
        created["runs"].append(body["generation_run_id"])
    if body.get("artifact_id"):
        created["artifacts"].append(body["artifact_id"])
    return r.status_code, body


def make_v2_artifact(source_id, n_answers):
    """v2 predlog direktno u bazi (aktivni prompt je v3, pa ruta pravi samo v3)."""
    prompt = db_one("SELECT id FROM ai_prompts WHERE purpose = 'similar_question' AND version = 'mc-v2'")
    model = db_one("SELECT id FROM ai_models ORDER BY id LIMIT 1")
    payload = {"question_text": "Probno v2 pitanje",
               "answers": [{"answer_text": f"v2-{i}", "is_correct": i == 0} for i in range(n_answers)]}
    run_id = db_exec("""INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, source_question_id, params_used,
                        raw_response, parsed_result, validation_passed, retry_count)
                        VALUES (%s, %s, 'similar_question', %s, '{}', %s, %s, 1, 0)""",
                     (model["id"], prompt["id"], source_id, json.dumps(payload), json.dumps(payload)))
    created["runs"].append(run_id)
    art_id = db_exec("""INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text)
                        VALUES (%s, 'question', 'predlog', %s)""", (run_id, json.dumps(payload)))
    created["artifacts"].append(art_id)
    return art_id


def review(art_id, h, decision, **extra):
    detail = client.get(f"/api/ai/artifacts/{art_id}", headers=h).get_json()
    scores = [{"rubric_definition_id": c["id"], "score": 3} for c in detail["rubric_criteria"]]
    body = {"decision": decision, "scores": scores, **extra}
    if decision == "odbaceno":
        body.setdefault("rejection_reason", "probno odbijanje")
    r = client.post(f"/api/ai/artifacts/{art_id}/review", headers=h, json=body)
    return r.status_code, r.get_json() or {}


def status_of(art_id):
    return db_one("SELECT status FROM ai_generated_artifacts WHERE id = %s", (art_id,))["status"]


def evaluations_of(art_id):
    return db_one("SELECT COUNT(*) AS n FROM ai_evaluations WHERE artifact_id = %s", (art_id,))["n"]


# ---------- provere ----------

def run():
    enabled = labels_enabled()
    print(f"Migracija db/migration_question_labels.sql: {'POKRENUTA' if enabled else 'NIJE pokrenuta'}")

    prompts_before = {r["version"] for r in db_all("SELECT version FROM ai_prompts WHERE purpose = 'similar_question'")}
    admin_id = db_one("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'ADMIN' ORDER BY u.id LIMIT 1")["id"]
    admin = headers(admin_id, "ADMIN")

    # izvorno MC pitanje sa tacno jednim tacnim odgovorom
    src = db_one("""SELECT q.id, q.subject_id, COUNT(a.id) AS n, SUM(a.is_correct) AS correct
                    FROM exam_questions q JOIN exam_answers a ON a.question_id = q.id
                    GROUP BY q.id, q.subject_id HAVING n >= 2 AND correct = 1 ORDER BY q.id LIMIT 1""")
    source_id, n = src["id"], int(src["n"])
    teacher_row = db_one("""SELECT ts.teacher_id FROM teacher_subjects ts JOIN users u ON u.id = ts.teacher_id
                            JOIN roles r ON r.id = u.role_id AND r.name = 'TEACHER' WHERE ts.subject_id = %s LIMIT 1""",
                         (src["subject_id"],))
    viewer = headers(teacher_row["teacher_id"], "TEACHER") if teacher_row else admin
    viewer_label = "TEACHER" if teacher_row else "ADMIN"

    def mc_payload(**labels):
        return {"question_text": "Probno v3 pitanje",
                "answers": [{"answer_text": f"o{i}", "is_correct": i == 0} for i in range(n)], **labels}

    good = mc_payload(difficulty="tesko", bloom_level="analiza")

    # --- generisanje v3 ---
    code, body = generate(source_id, good, admin)
    v3_id = body.get("artifact_id")
    run = db_one("""SELECT r.validation_passed, p.version, a.original_text FROM ai_generation_runs r
                    JOIN ai_prompts p ON p.id = r.prompt_id
                    LEFT JOIN ai_generated_artifacts a ON a.generation_run_id = r.id WHERE r.id = %s""",
                 (body.get("generation_run_id"),)) or {}
    stored = json.loads(run.get("original_text") or "{}")
    record("generisanje v3 sa oznakama", "201, mc-v3, oznake u original_text, ne u odgovoru rute",
           f"{code}, {run.get('version')}, u bazi={stored.get('difficulty')}/{stored.get('bloom_level')}, "
           f"u odgovoru={sorted(set(body.get('proposed_question', {})) & {'difficulty', 'bloom_level'}) or 'nema'}",
           code == 201 and run.get("version") == "mc-v3" and stored.get("difficulty") == "tesko"
           and "difficulty" not in body.get("proposed_question", {}))
    if "mc-v3" not in prompts_before:
        row = db_one("SELECT id FROM ai_prompts WHERE purpose = 'similar_question' AND version = 'mc-v3'")
        if row:
            created["prompts"].append(row["id"])

    for case, payload, expected_msg in (
        ("generisanje v3 bez oznaka", mc_payload(), "difficulty"),
        ("generisanje v3, nevazeca tezina 'teško'", mc_payload(difficulty="teško", bloom_level="analiza"), "difficulty"),
        ("generisanje v3, nevazeci Blum 'pamćenje'", mc_payload(difficulty="lako", bloom_level="pamćenje"), "bloom_level"),
        ("generisanje v3, visak polja", mc_payload(difficulty="lako", bloom_level="primena", note="x"), "Nepoznata polja"),
    ):
        code, b = generate(source_id, payload, admin)
        record(case, f"422, poruka sadrzi '{expected_msg}'", f"{code}, {b.get('details')}",
               code == 422 and expected_msg in (b.get("details") or "") and not b.get("artifact_id"))

    # --- slepo: modelove oznake se ne vracaju dok je 'predlog' ---
    d = client.get(f"/api/ai/artifacts/{v3_id}", headers=viewer).get_json()
    leaked = [k for k in LABEL_KEYS if k in d] + [k for k in ("difficulty", "bloom_level") if k in (d.get("original_text") or {})]
    record(f"{viewer_label} detalj v3 'predlog'", "bez modelovih oznaka, labels_required=true",
           f"procurelo: {leaked or 'nista'}, labels_required={d.get('labels_required')}",
           not leaked and d.get("labels_required") is True)

    lst = client.get("/api/ai/artifacts?status=predlog", headers=viewer).get_json()
    row = next((r for r in lst if r["id"] == v3_id), None)
    leaked = ([k for k in LABEL_KEYS if k in row] + [k for k in ("difficulty", "bloom_level") if k in (row.get("original_text") or {})]) if row else ["red nije u listi"]
    record(f"{viewer_label} lista 'predlog' (v3 red)", "bez modelovih oznaka", f"procurelo: {leaked or 'nista'}", not leaked)

    d = client.get(f"/api/ai/artifacts/{v3_id}?reveal=1", headers=admin).get_json()
    record("ADMIN detalj v3 sa ?reveal=1", "tesko / analiza", f"{d.get('model_difficulty')} / {d.get('model_bloom_level')}",
           d.get("model_difficulty") == "tesko" and d.get("model_bloom_level") == "analiza")

    d = client.get(f"/api/ai/artifacts/{v3_id}", headers=admin).get_json()
    record("ADMIN detalj v3 bez ?reveal=1", "bez modelovih oznaka", f"procurelo: {[k for k in LABEL_KEYS if k in d] or 'nista'}",
           not any(k in d for k in LABEL_KEYS))

    # --- pregled v3 ---
    code, b = review(v3_id, admin, "prihvaceno")
    record("pregled v3 prihvatanje bez oznaka", "400", f"{code} {b.get('error')}",
           code == 400 and status_of(v3_id) == "predlog" and evaluations_of(v3_id) == 0)

    code, b = review(v3_id, admin, "prihvaceno", reviewed_difficulty="Tesko", reviewed_bloom_level="analiza")
    record("pregled v3 nevazeca oznaka 'Tesko'", "400", f"{code} {b.get('error')}", code == 400 and status_of(v3_id) == "predlog")

    code, b = review(v3_id, admin, "prihvaceno", reviewed_difficulty="srednje")
    record("pregled v3 samo jedna oznaka", "400", f"{code} {b.get('error')}", code == 400 and status_of(v3_id) == "predlog")

    if not enabled:
        code, b = review(v3_id, admin, "prihvaceno", reviewed_difficulty="srednje", reviewed_bloom_level="primena")
        record("pregled v3 sa oznakama PRE migracije", "409, bez upisa",
               f"{code} {b.get('error')}, status={status_of(v3_id)}, ocena={evaluations_of(v3_id)}",
               code == 409 and status_of(v3_id) == "predlog" and evaluations_of(v3_id) == 0)
        why = "migracija nije pokrenuta"
        skip("generisanje upisuje model_* kolone", why)
        skip("prihvatanje v3: reviewed_* i oznake novog pitanja", why)
        skip("posle odluke: modelove i nastavnikove oznake", why)
        skip("izmena v3 sa oznakama", why)
    else:
        cols = db_one("SELECT model_difficulty, model_bloom_level FROM ai_generated_artifacts WHERE id = %s", (v3_id,))
        record("generisanje upisuje model_* kolone", "tesko / analiza", f"{cols['model_difficulty']} / {cols['model_bloom_level']}",
               cols["model_difficulty"] == "tesko" and cols["model_bloom_level"] == "analiza")

        code, b = review(v3_id, admin, "prihvaceno", reviewed_difficulty="srednje", reviewed_bloom_level="primena")
        a = db_one("SELECT status, reviewed_difficulty, reviewed_bloom_level, created_question_id FROM ai_generated_artifacts WHERE id = %s", (v3_id,))
        q = db_one("SELECT difficulty, bloom_level FROM exam_questions WHERE id = %s", (a["created_question_id"],)) or {}
        record("prihvatanje v3: reviewed_* i oznake novog pitanja", "200, srednje/primena u predlogu i u pitanju",
               f"{code}, predlog={a['reviewed_difficulty']}/{a['reviewed_bloom_level']}, pitanje={q.get('difficulty')}/{q.get('bloom_level')}",
               code == 200 and a["status"] == "prihvaceno" and a["reviewed_difficulty"] == "srednje"
               and q.get("difficulty") == "srednje" and q.get("bloom_level") == "primena")

        d = client.get(f"/api/ai/artifacts/{v3_id}", headers=viewer).get_json()
        record("posle odluke: modelove i nastavnikove oznake", "model tesko/analiza, nastavnik srednje/primena",
               f"model {d.get('model_difficulty')}/{d.get('model_bloom_level')}, nastavnik {d.get('reviewed_difficulty')}/{d.get('reviewed_bloom_level')}",
               d.get("model_difficulty") == "tesko" and d.get("reviewed_bloom_level") == "primena")

        _, b2 = generate(source_id, mc_payload(difficulty="lako", bloom_level="pamcenje"), admin)
        edited = {"question_text": "Izmenjeno v3", "answers": [{"answer_text": f"e{i}", "is_correct": i == 1} for i in range(n)]}
        code, b = review(b2["artifact_id"], admin, "prihvaceno_izmena", edited_text=edited,
                         reviewed_difficulty="lako", reviewed_bloom_level="razumevanje")
        a = db_one("SELECT status, edited_text, reviewed_bloom_level FROM ai_generated_artifacts WHERE id = %s", (b2["artifact_id"],))
        record("izmena v3 sa oznakama", "200, edited_text bez oznaka", f"{code} {a['status']}, reviewed={a['reviewed_bloom_level']}",
               code == 200 and a["status"] == "prihvaceno_izmena" and "difficulty" not in json.loads(a["edited_text"]))

    _, b3 = generate(source_id, mc_payload(difficulty="srednje", bloom_level="primena"), admin)
    code, b = review(b3["artifact_id"], admin, "odbaceno")
    record("odbacivanje v3 bez oznaka", "200 (oznake opcione)", f"{code} {b.get('status') or b.get('error')}",
           code == 200 and status_of(b3["artifact_id"]) == "odbaceno")

    # --- v2 predlog se i dalje pregleda bez oznaka ---
    v2_id = make_v2_artifact(source_id, n)
    d = client.get(f"/api/ai/artifacts/{v2_id}", headers=admin).get_json()
    record("v2 detalj", "bez labels_required i modelovih oznaka",
           f"labels_required={d.get('labels_required')}, {[k for k in LABEL_KEYS if k in d] or 'nista'}",
           "labels_required" not in d and not any(k in d for k in LABEL_KEYS))
    code, b = review(v2_id, admin, "prihvaceno")
    record("v2 prihvatanje bez oznaka", "200, novo pitanje", f"{code}, created_question_id={b.get('created_question_id')}",
           code == 200 and b.get("created_question_id"))


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e, g if len(g) <= 90 else g[:87] + "...", s) for c, e, g, s in results]
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
    real_post, real_sleep = requests.post, ai_provider.time.sleep
    ai_provider.time.sleep = lambda s: None
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
