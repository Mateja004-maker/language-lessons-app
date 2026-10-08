"""Provera tačke J: generisanje iz skupa pitanja testa (ruta, pokretač, slepo ocenjivanje).

Pokretanje (iz foldera backend/):
    python tests/verify_set_generation.py

LAŽNI provajder (requests.post je zamenjen) - nijedan pravi AI servis se ne
poziva. Pravi privremene testove (od postojećih pitanja, koja se ne menjaju),
nastavnika, serije i predloge; sve briše po zabeleženim id-jevima i poredi
brojeve redova pre i posle.
"""
import json
import os
import re
import sys
import uuid
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

# app pre ai_provider-a: app.py ucitava backend/.env, a ai_provider cita kljuceve pri ucitavanju
from app import app, get_db_connection  # noqa: E402
import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
import run_experiment as rx  # noqa: E402

PROVIDERS = ["groq", "gemini", "openrouter"]
MODEL_FIELDS = ("provider", "model_name", "created_at", "generation_run_id", "model_difficulty", "model_bloom_level")
COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_label_evaluations", "ai_prompts",
                "exam_questions", "exam_answers", "exams", "exam_test_questions", "evaluation_batches", "users")
TAG = uuid.uuid4().hex[:6]
LABELS = {"difficulty": "srednje", "bloom_level": "primena"}

results = []
created = {"exams": [], "batches": [], "users": [], "prompts_before": set()}
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


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def headers(user_id, role):
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": f"verify-{user_id}"})
    return {"Authorization": f"Bearer {token}"}


# ---------- lazni provajder ----------

class FakeResponse:
    def __init__(self, body):
        self.status_code, self.headers, self._body, self.text = 200, {}, body, json.dumps(body)

    def json(self):
        return self._body


def mc(n=4, text="Novo MC pitanje", **extra):
    return {"question_text": text, **LABELS, "answers": [{"answer_text": f"o{i}", "is_correct": i == 0} for i in range(n)], **extra}


def open_q(text="Novo otvoreno pitanje", **extra):
    return {"question_text": text, **LABELS, **extra}


class FakeProvider:
    """Vraća odgovore iz reda `queue` (tekst ili dict); kad je red prazan - K ispravnih pitanja
    (K iz prompta), različitih po tekstu."""

    def __init__(self):
        self.queue = []
        self.calls = []
        self.counter = 0

    def __call__(self, url, **kwargs):
        provider = "gemini" if "googleapis" in url else "openrouter" if "openrouter" in url else "groq"
        body = kwargs.get("json") or {}
        prompt = body["contents"][0]["parts"][0]["text"] if provider == "gemini" else body["messages"][0]["content"]
        self.calls.append(provider)
        if self.queue:
            item = self.queue.pop(0)
            text = item if isinstance(item, str) else json.dumps(item)
        else:
            k = int(re.search(r"generiši TAČNO (\d+) novih", prompt).group(1))
            self.counter += 1
            text = json.dumps({"questions": [mc(4, f"Lažno pitanje {self.counter}-{i} {provider} {TAG}") for i in range(k)]})
        if provider == "gemini":
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})
        return FakeResponse({"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"total_tokens": 2}})


# ---------- priprema i ciscenje ----------

def make_exam(subject_id, question_ids):
    exam_id = db_exec("""INSERT INTO exams (title, subject_id, level, duration_minutes, is_published)
                         VALUES (%s, %s, 'A1', 30, 0)""", (f"tmp-set-{TAG}", subject_id))
    created["exams"].append(exam_id)
    for order_no, qid in enumerate(question_ids, start=1):
        db_exec("INSERT INTO exam_test_questions (exam_id, question_id, order_no) VALUES (%s, %s, %s)", (exam_id, qid, order_no))
    return exam_id


def make_batch(label):
    batch_id = db_exec("INSERT INTO evaluation_batches (name, description) VALUES (%s, 'tmp verify')", (f"tmp-set-{TAG}-{label}",))
    created["batches"].append(batch_id)
    return batch_id


def cleanup():
    def ph(ids):
        return ",".join(["%s"] * len(ids))

    runs = [r["id"] for r in db_all("SELECT id FROM ai_generation_runs WHERE params_used LIKE %s", (f'%"tmp-set-{TAG}%',))]
    runs += [r["id"] for b in created["batches"] for r in db_all("SELECT id FROM ai_generation_runs WHERE evaluation_batch_id = %s", (b,))]
    runs += [r["id"] for e in created["exams"] for r in db_all(
        "SELECT id FROM ai_generation_runs WHERE JSON_VALUE(params_used, '$.input.type') = 'exam' AND JSON_VALUE(params_used, '$.input.id') = %s", (e,))]
    runs = sorted(set(runs))
    if runs:
        arts = [r["id"] for r in db_all(f"SELECT id FROM ai_generated_artifacts WHERE generation_run_id IN ({ph(runs)})", runs)]
        if arts:
            questions = [r["created_question_id"] for r in db_all(
                f"SELECT created_question_id FROM ai_generated_artifacts WHERE id IN ({ph(arts)}) AND created_question_id IS NOT NULL", arts)]
            db_exec(f"DELETE FROM ai_label_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
            db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
            db_exec(f"UPDATE ai_generated_artifacts SET similar_artifact_id = NULL WHERE id IN ({ph(arts)})", arts)
            db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
            if questions:
                db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(questions)})", questions)
                db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(questions)})", questions)
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    if created["exams"]:
        db_exec(f"DELETE FROM exam_test_questions WHERE exam_id IN ({ph(created['exams'])})", created["exams"])
        db_exec(f"DELETE FROM exams WHERE id IN ({ph(created['exams'])})", created["exams"])
    if created["batches"]:
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph(created['batches'])})", created["batches"])
    if created["users"]:
        db_exec(f"DELETE FROM teacher_subjects WHERE teacher_id IN ({ph(created['users'])})", created["users"])
        db_exec(f"DELETE FROM users WHERE id IN ({ph(created['users'])})", created["users"])
    for row in db_all("SELECT id FROM ai_prompts"):
        if row["id"] not in created["prompts_before"] and not db_all(
                "SELECT 1 FROM ai_generation_runs WHERE prompt_id = %s LIMIT 1", (row["id"],)):
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (row["id"],))


# ---------- provere ----------

def run(fake):
    admin_id = db_one("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'ADMIN' ORDER BY u.id LIMIT 1")["id"]
    admin = headers(admin_id, "ADMIN")
    subject = db_one("SELECT id FROM subjects WHERE name = 'Osnove programiranja'")["id"]
    input_ids = [r["id"] for r in db_all("SELECT id FROM exam_questions WHERE subject_id = %s ORDER BY id LIMIT 4", (subject,))]
    exam = make_exam(subject, input_ids[:3])
    input_text = db_one("SELECT question_text FROM exam_questions WHERE id = %s", (input_ids[0],))["question_text"]

    def gen(exam_id, k=3, h=admin, provider="groq", batch=None):
        url = f"/api/exams/{exam_id}/generate-similar?provider={provider}&k={k}" + (f"&evaluation_batch_id={batch}" if batch else "")
        r = client.post(url, headers=h)
        return r.status_code, r.get_json() or {}

    def run_row(run_id):
        return db_one("""SELECT purpose, source_question_id, validation_passed, failure_type, first_attempt_passed,
                         format_retries, params_used FROM ai_generation_runs WHERE id = %s""", (run_id,))

    # 1. ceo ispravan niz
    status, body = gen(exam)
    arts = db_all("SELECT id, generation_run_id FROM ai_generated_artifacts WHERE generation_run_id = %s", (body.get("generation_run_id"),))
    run = run_row(body.get("generation_run_id")) or {}
    params = json.loads(run.get("params_used") or "{}")
    record("jedan run daje K predloga", "201, 3 predloga istog run-a, purpose set, ulaz = pitanja testa",
           f"{status}, predloga={len(arts)}, purpose={run.get('purpose')}, ulaz={params.get('input_question_ids')}",
           status == 201 and len(arts) == 3 and body.get("accepted") == 3 and run.get("purpose") == "similar_question_set"
           and params.get("input_question_ids") == input_ids[:3] and run.get("source_question_id") == input_ids[0])
    full_artifacts = [a["id"] for a in arts]

    # 2. delimicno ispravan niz
    fake.queue = [{"questions": [mc(4, f"Ispravno {TAG}"), mc(2, f"Dva odgovora {TAG}"), open_q(f"Visak {TAG}", note="x")]}]
    status, body = gen(exam)
    run = run_row(body.get("generation_run_id")) or {}
    items = (json.loads(run.get("params_used") or "{}")).get("set_items") or {}
    record("delimično ispravan niz", "201, prihvaćeno 1, odbijeno 2 (schema, sa razlozima), run uspešan",
           f"{status}, prihvaćeno={body.get('accepted')}, odbijeno={body.get('rejected')}, "
           f"razlozi={[r['errors'][0][:30] for r in items.get('rejected', [])]}, validation_passed={run.get('validation_passed')}, failure={run.get('failure_type')}",
           status == 201 and body.get("accepted") == 1 and body.get("rejected") == 2
           and [r["failure_type"] for r in items.get("rejected", [])] == ["schema", "schema"]
           and run.get("validation_passed") == 1 and run.get("failure_type") is None)

    # 3. prazan niz (oba pokusaja)
    fake.queue = [{"questions": []}, {"questions": []}]
    status, body = gen(exam)
    record("prazan niz", "422 schema, ponovni zahtev 1, bez predloga",
           f"{status} {body.get('failure_type')}, pon={body.get('format_retries')}, predloga={len(body.get('artifact_ids') or [])}",
           status == 422 and body.get("failure_type") == "schema" and body.get("format_retries") == 1 and not body.get("artifact_ids"))

    # 4. vise od K stavki
    fake.queue = [{"questions": [open_q(f"x{i}") for i in range(4)]}] * 2
    status, body = gen(exam)
    raw_reason = (db_one("SELECT validation_errors FROM ai_generation_runs WHERE id = %s", (body.get("generation_run_id"),)) or {}).get("validation_errors")
    record("više od K stavki", "422 schema, razlog u run-u", f"{status} {body.get('failure_type')}, {raw_reason}",
           status == 422 and body.get("failure_type") == "schema" and "najviše 3" in (raw_reason or ""))

    # 5. los JSON pa ispravno
    fake.queue = ["ovo nije json"]
    status, body = gen(exam)
    run = run_row(body.get("generation_run_id")) or {}
    record("loš JSON pa ispravan niz", "201, ponovni zahtev 1, prvi nije prošao",
           f"{status}, pon={body.get('format_retries')}, prvi={body.get('first_attempt_passed')}, kolone={run.get('first_attempt_passed')}/{run.get('format_retries')}",
           status == 201 and body.get("format_retries") == 1 and body.get("first_attempt_passed") is False
           and run.get("first_attempt_passed") == 0 and run.get("format_retries") == 1)

    # 6. duplikati unutar run-a i prema ulaznom skupu
    copy_of_input = {"question_text": input_text, **LABELS}
    fake.queue = [{"questions": [mc(4, f"Isto pitanje {TAG}"), mc(4, f"Isto pitanje {TAG}"), copy_of_input]}]
    status, body = gen(exam)
    rows = db_all("""SELECT id, max_similarity, similar_source, similar_question_id, similar_artifact_id
                     FROM ai_generated_artifacts WHERE generation_run_id = %s ORDER BY id""", (body.get("generation_run_id"),))
    first, second, third = rows if len(rows) == 3 else ({}, {}, {})
    record("duplikati unutar run-a i prema ulaznom skupu",
           "1. i 2. isti -> 1.000 'artifact' jedan prema drugom; 3. = ulazno pitanje -> 'source'",
           f"{[(r['id'], float(r['max_similarity']), r['similar_source'], r['similar_question_id'] or r['similar_artifact_id']) for r in rows]}",
           len(rows) == 3 and float(first["max_similarity"]) == 1.0 and first["similar_source"] == "artifact"
           and first["similar_artifact_id"] == second["id"] and second["similar_artifact_id"] == first["id"]
           and third["similar_source"] == "source" and third["similar_question_id"] == input_ids[0])

    # 7. dozvole i ulaz
    teacher = db_exec("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', 2, 'tmp', 1)",
                      (f"tmp-set-{TAG}@example.invalid",))
    created["users"].append(teacher)
    empty_exam = make_exam(subject, [])
    statuses = [gen(exam, h=headers(teacher, "TEACHER"))[0], gen(99999999)[0], gen(exam, k=0)[0], gen(exam, k=11)[0], gen(empty_exam)[0]]
    record("dozvole i ulaz", "403 (nastavnik bez predmeta), 404, 400 (k=0), 400 (k=11), 400 (test bez pitanja)",
           f"{statuses}", statuses == [403, 404, 400, 400, 400])

    # 8. slepo ocenjivanje za K predloga + ulazna pitanja
    listed = {r["id"]: r for r in client.get("/api/ai/artifacts?status=predlog", headers=admin).get_json()}
    leaked = sorted({f for a in full_artifacts for f in MODEL_FIELDS if f in listed.get(a, {})})
    detail = client.get(f"/api/ai/artifacts/{full_artifacts[0]}", headers=admin).get_json() or {}
    record("slepo ocenjivanje za K predloga", "svi u listi, bez modela/vremena/run-a/oznaka; detalj sa 3 ulazna pitanja",
           f"u listi={sum(a in listed for a in full_artifacts)}/3, procurelo={leaked or 'nista'}, "
           f"detalj procurelo={[f for f in MODEL_FIELDS if f in detail] or 'nista'}, ulaznih={len(detail.get('input_questions') or [])}",
           all(a in listed for a in full_artifacts) and not leaked and not any(f in detail for f in MODEL_FIELDS)
           and [q["id"] for q in detail.get("input_questions") or []] == input_ids[:3])

    # 9. pregled i razdaljina izmene rade za predlog iz skupa
    rubric = detail["rubric_criteria"]
    edited = {"question_text": "Izmenjeno pitanje iz skupa",
              "answers": [{"answer_text": f"o{i}", "is_correct": i == 1} for i in range(4)]}
    r = client.post(f"/api/ai/artifacts/{full_artifacts[0]}/review", headers=admin, json={
        "decision": "prihvaceno_izmena", "scores": [{"rubric_definition_id": c["id"], "score": 4} for c in rubric],
        "edited_text": edited, "reviewed_difficulty": "lako", "reviewed_bloom_level": "razumevanje"})
    art = db_one("SELECT status, edit_distance, created_question_id FROM ai_generated_artifacts WHERE id = %s", (full_artifacts[0],))
    question = db_one("SELECT subject_id, difficulty FROM exam_questions WHERE id = %s", (art["created_question_id"],)) or {}
    record("pregled predloga iz skupa (izmena)", "200, novo pitanje u predmetu, razdaljina upisana",
           f"{r.status_code} {art['status']}, razdaljina={art['edit_distance']}, pitanje predmet={question.get('subject_id')} težina={question.get('difficulty')}",
           r.status_code == 200 and art["status"] == "prihvaceno_izmena" and art["edit_distance"]
           and question.get("subject_id") == subject and question.get("difficulty") == "lako")

    # ---------- pokretac: --mode set ----------
    batch = make_batch("set")
    calls_before = len(fake.calls)
    rep = rx.run_experiment(batch, input_ids, PROVIDERS, 1, mode="set", group_size=2, k=2, max_calls=2, out=lambda *a: None)
    order = fake.calls[calls_before:]
    runs = db_all("""SELECT r.params_used, m.provider FROM ai_generation_runs r JOIN ai_models m ON m.id = r.model_id
                     WHERE r.evaluation_batch_id = %s ORDER BY r.id""", (batch,))
    first_units = [(tuple(json.loads(r["params_used"])["input_question_ids"]), r["provider"]) for r in runs]
    record("režim set: grupe naizmenično po modelima, prekid", "2 poziva: grupa 1 -> groq, gemini",
           f"{first_units}", first_units == [(tuple(input_ids[:2]), "groq"), (tuple(input_ids[:2]), "gemini")])
    rep = rx.run_experiment(batch, input_ids, PROVIDERS, 1, mode="set", group_size=2, k=2, out=lambda *a: None)
    runs = db_all("""SELECT r.params_used, m.provider FROM ai_generation_runs r JOIN ai_models m ON m.id = r.model_id
                     WHERE r.evaluation_batch_id = %s""", (batch,))
    per_slot = Counter((tuple(json.loads(r["params_used"])["input_question_ids"]), r["provider"]) for r in runs)
    record("režim set: nastavak bez dupliranja", "još 4 poziva, ukupno 6 (2 grupe x 3 modela), svako mesto tačno 1",
           f"poziva={rep['calls']}, run-ova={len(runs)}, po mestu={sorted(set(per_slot.values()))}, prihvaćeno={sum(rep['items_accepted'].values())}",
           rep["calls"] == 4 and len(runs) == 6 and set(per_slot.values()) == {1} and len(per_slot) == 6
           and sum(rep["items_accepted"].values()) == 8)
    rep = rx.run_experiment(batch, input_ids, PROVIDERS, 1, mode="set", group_size=2, k=2, out=lambda *a: None)
    record("režim set: završena serija", "0 poziva", f"poziva={rep['calls']}, preostalo={rep['pending']}", rep["calls"] == 0 and rep["pending"] == 0)

    errors = []
    for kwargs in ({"mode": "single"}, {"mode": "set", "group_size": 3, "k": 2}, {"mode": "set", "group_size": 2, "k": 3}):
        try:
            rx.run_experiment(batch, input_ids, PROVIDERS, 1, out=lambda *a: None, **kwargs)
            errors.append("nije odbijeno")
        except rx.ExperimentError as e:
            errors.append(str(e).splitlines()[1].strip()[:50] if "\n" in str(e) else str(e)[:50])
    record("serija ne meša režime, grupe ni K", "3 x ExperimentError", f"{errors}", "nije odbijeno" not in errors)


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 70 else e[:67] + "...", g if len(g) <= 100 else g[:97] + "...", s) for c, e, g, s in results]
    widths = [max(len(str(r[i])) for r in rows + [head]) for i in range(4)]
    line = " | ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    failed = sum(1 for r in results if r[3] == "PALO")
    print(f"\nUkupno: {len(results)}, palo: {failed}")
    return failed


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    real_post, real_sleep = requests.post, ai_provider.time.sleep
    fake = FakeProvider()
    requests.post = fake
    ai_provider.time.sleep = lambda s: None
    created["prompts_before"] = {r["id"] for r in db_all("SELECT id FROM ai_prompts")}
    before = row_counts()
    try:
        run(fake)
    finally:
        requests.post, ai_provider.time.sleep = real_post, real_sleep
        cleanup()
        after = row_counts()
        changed = {t: (before[t], after[t]) for t in COUNT_TABLES if before[t] != after[t]}
        record("brojevi redova u bazi pre/posle", "isti", "isti" if not changed else str(changed), not changed)
    sys.exit(1 if print_table() else 0)
