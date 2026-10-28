"""Provera rute POST /api/questions/<id>/generate-explanation (režim A/B).

Pokretanje (iz foldera backend/):
    python tests/verify_generate_explanation.py

Kroz pravu rutu, sa LAŽNIM provajderom (requests.post vraća unapred zadat
odgovor, time.sleep samo beleži pauze) - nijedan pravi AI servis se ne poziva.
Za svaki slučaj proverava status, tačan skup polja u telu odgovora i upis u
ai_generation_runs / ai_generated_artifacts (ili da upisa nema, za 400/404).
Neuspeh (422) vraća i failure_type, istu vrednost koja se upisuje u run.

Provera pravi privremena pitanja (MC, programsko sa test primerima, otvoreno)
i privremenu seriju; sve se briše po id-jevima, a na kraju se porede brojevi
redova. Režim B za programsko pitanje pokreće lažno rešenje kroz code_executor.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
from app import FAILURE_COLUMNS, app, get_db_connection, table_columns_exist  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_prompts", "ai_models", "exam_questions",
                "exam_answers", "exam_question_test_cases", "evaluation_batches")
BODY_201 = {"message", "generation_run_id", "artifact_id", "mode", "accuracy_check_passed", "proposed_result"}
BODY_422 = {"error", "details", "generation_run_id", "failure_type"}
BODY_ERROR = {"error"}
results = []
created = {"runs": [], "artifacts": [], "questions": [], "batches": [], "prompts_before": set(), "models_before": set()}
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


def _delete_ids(table, ids, column="id"):
    if ids:
        ph = ",".join(["%s"] * len(ids))
        db_exec(f"DELETE FROM {table} WHERE {column} IN ({ph})", ids)


def cleanup():
    _delete_ids("ai_generated_artifacts", created["artifacts"])
    _delete_ids("ai_generation_runs", created["runs"])
    for table, before in (("ai_prompts", "prompts_before"), ("ai_models", "models_before")):
        column = "prompt_id" if table == "ai_prompts" else "model_id"
        for row in db_all(f"SELECT id FROM {table}"):
            if row["id"] not in created[before] and not db_all(
                    f"SELECT 1 FROM ai_generation_runs WHERE {column} = %s LIMIT 1", (row["id"],)):
                db_exec(f"DELETE FROM {table} WHERE id = %s", (row["id"],))
    _delete_ids("exam_question_test_cases", created["questions"], "question_id")
    _delete_ids("exam_answers", created["questions"], "question_id")
    _delete_ids("exam_questions", created["questions"])
    _delete_ids("evaluation_batches", created["batches"])


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.headers, self._body = status, {}, body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError
        return self._body


def model_text(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                              "usage": {"total_tokens": 5}})


def make_questions():
    subject = db_one("SELECT MIN(id) AS id FROM subjects")["id"]

    def question(text, reference_solution=None):
        qid = db_exec("INSERT INTO exam_questions (subject_id, question_text, reference_solution) VALUES (%s, %s, %s)",
                      (subject, text, reference_solution))
        created["questions"].append(qid)
        return qid

    mc = question("Provera objasnjenja: koliko je 2 + 2?")
    for text, correct in (("3", 0), ("4", 1), ("5", 0)):
        db_exec("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)", (mc, text, correct))
    prog = question("Provera objasnjenja: ucitaj ceo broj i ispisi ga udvostrucenog.", "print(int(input()) * 2)")
    for order_no, (given, expected) in enumerate((("3", "6"), ("5", "10")), start=1):
        db_exec("INSERT INTO exam_question_test_cases (question_id, input_data, expected_output, order_no) "
                "VALUES (%s, %s, %s, %s)", (prog, given, expected, order_no))
    open_q = question("Provera objasnjenja: objasni pojam promenljive.")
    batch = db_exec("INSERT INTO evaluation_batches (name) VALUES (%s)", ("verify-generate-explanation",))
    created["batches"].append(batch)
    missing = db_one("SELECT COALESCE(MAX(id), 0) + 1000 AS id FROM exam_questions")["id"]
    return {"mc": mc, "prog": prog, "open": open_q, "batch": batch, "missing": missing}


def call(question_id, query, response, headers):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        if response is None:
            raise AssertionError("ruta je pozvala provajdera, a nije smela")
        return response

    requests.post = fake_post
    runs_before = db_one("SELECT COUNT(*) AS n FROM ai_generation_runs")["n"]
    r = client.post(f"/api/questions/{question_id}/generate-explanation?{query}", headers=headers)
    body = r.get_json() or {}
    if body.get("generation_run_id"):
        created["runs"].append(body["generation_run_id"])
    if body.get("artifact_id"):
        created["artifacts"].append(body["artifact_id"])
    new_runs = db_one("SELECT COUNT(*) AS n FROM ai_generation_runs")["n"] - runs_before
    return r.status_code, body, len(calls), new_runs


def run():
    columns = False
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        columns = table_columns_exist(cur, "ai_generation_runs", FAILURE_COLUMNS)
    finally:
        cur.close()
        conn.close()
    with app.app_context():
        admin = {"Authorization": "Bearer " + create_access_token(identity="1", additional_claims={"role": "ADMIN", "email": "x"})}
    q = make_questions()
    ai_provider.time.sleep = lambda seconds: None

    explanation = {"explanation": "Zato sto je 2 + 2 = 4."}
    # (naziv, pitanje, upit, odgovor provajdera, status, polja tela, run: (mode, validation_passed,
    #  accuracy_check_passed, failure_type, batch) ili None ako run ne sme da nastane)
    cases = [
        ("A: MC sa tacnim odgovorom", q["mc"], "mode=mode_a&provider=groq", model_text(explanation),
         201, BODY_201, ("mode_a", 1, None, None, None)),
        ("A: programsko sa reference_solution, u seriji", q["prog"],
         f"mode=mode_a&provider=groq&evaluation_batch_id={q['batch']}", model_text(explanation),
         201, BODY_201, ("mode_a", 1, None, None, q["batch"])),
        ("B: programsko, resenje prolazi testove", q["prog"], "mode=mode_b&provider=groq",
         model_text({"solution": "print(int(input()) * 2)", "explanation": "Udvostruci ulaz."}),
         201, BODY_201, ("mode_b", 1, 1, None, None)),
        ("B: programsko, resenje ne prolazi", q["prog"], "mode=mode_b&provider=groq",
         model_text({"solution": "print(int(input()) + 1)", "explanation": "Pogresno."}),
         201, BODY_201, ("mode_b", 1, 0, None, None)),
        ("B: MC, izabran tacan odgovor", q["mc"], "mode=mode_b&provider=groq",
         model_text({"selected_option": 2, "explanation": "4 je tacno."}),
         201, BODY_201, ("mode_b", 1, 1, None, None)),
        ("B: otvoreno bez test primera", q["open"], "mode=mode_b&provider=groq",
         model_text({"solution": "Promenljiva je imenovana vrednost.", "explanation": "Opis."}),
         201, BODY_201, ("mode_b", 1, None, None, None)),
        ("422: odgovor nije JSON", q["mc"], "mode=mode_a&provider=groq", model_text("ovo nije json"),
         422, BODY_422, ("mode_a", 0, None, "invalid_json", None)),
        ("422: A vraca solution (sema)", q["mc"], "mode=mode_a&provider=groq",
         model_text({"solution": "x", "explanation": "y"}),
         422, BODY_422, ("mode_a", 0, None, "schema", None)),
        ("422: B MC bez selected_option (sema)", q["mc"], "mode=mode_b&provider=groq", model_text(explanation),
         422, BODY_422, ("mode_b", 0, None, "schema", None)),
        ("422: provajder 401", q["mc"], "mode=mode_a&provider=groq", FakeResponse(401, "invalid api key"),
         422, BODY_422, ("mode_a", 0, None, "http_4xx", None)),
        ("400: nepoznat mode", q["mc"], "mode=mode_c&provider=groq", None, 400, BODY_ERROR, None),
        ("400: nepoznat provider", q["mc"], "mode=mode_a&provider=nepoznat", None, 400, BODY_ERROR, None),
        ("400: nepostojeca serija", q["mc"], "mode=mode_a&provider=groq&evaluation_batch_id=999999", None,
         400, BODY_ERROR, None),
        ("400: A bez poznatog resenja", q["open"], "mode=mode_a&provider=groq", None, 400, BODY_ERROR, None),
        ("404: nepostojece pitanje", q["missing"], "mode=mode_a&provider=groq", None, 404, BODY_ERROR, None),
    ]

    for name, question_id, query, response, exp_status, exp_keys, exp_run in cases:
        status, body, calls, new_runs = call(question_id, query, response, admin)
        failed = []
        if status != exp_status:
            failed.append(f"status {status}")
        if set(body) != exp_keys:
            failed.append(f"polja {sorted(set(body) ^ exp_keys)}")
        if exp_run is None:
            if new_runs or calls:
                failed.append(f"upis/poziv (run-ova {new_runs}, poziva {calls})")
        else:
            mode, passed, accuracy, failure_type, batch = exp_run
            run_row = db_one("""SELECT purpose, mode, source_question_id, validation_passed, accuracy_check_passed,
                                       evaluation_batch_id FROM ai_generation_runs WHERE id = %s""",
                             (body.get("generation_run_id"),)) or {}
            expected_row = {"purpose": "explanation", "mode": mode, "source_question_id": question_id,
                            "validation_passed": passed, "accuracy_check_passed": accuracy, "evaluation_batch_id": batch}
            diff = [k for k, v in expected_row.items() if run_row.get(k) != v]
            if diff or new_runs != 1:
                failed.append(f"run {diff or ''} (novih {new_runs})")
            if exp_status == 422 and body.get("failure_type") != failure_type:
                failed.append(f"failure_type u telu {body.get('failure_type')!r}")
            if columns:
                stored = db_one("SELECT failure_type FROM ai_generation_runs WHERE id = %s",
                                (body.get("generation_run_id"),)) or {}
                if stored.get("failure_type") != failure_type:
                    failed.append(f"failure_type u run-u {stored.get('failure_type')!r}")
            if exp_status == 201:
                artifact = db_one("SELECT artifact_type, status, original_text FROM ai_generated_artifacts WHERE id = %s",
                                  (body.get("artifact_id"),)) or {}
                if (artifact.get("artifact_type"), artifact.get("status")) != ("explanation", "predlog") \
                        or json.loads(artifact.get("original_text") or "null") != body.get("proposed_result") \
                        or body.get("mode") != mode or body.get("accuracy_check_passed") != accuracy:
                    failed.append("predlog/telo 201")
            elif body.get("artifact_id") or db_one("SELECT 1 AS x FROM ai_generated_artifacts WHERE generation_run_id = %s",
                                                   (body.get("generation_run_id"),)):
                failed.append("predlog napravljen uz 422")
        got = f"{status} polja={sorted(body)}" + (f" failure_type={body.get('failure_type')}" if status == 422 else "")
        record(name, f"{exp_status} {sorted(exp_keys)}", got + (f" | PALO: {'; '.join(failed)}" if failed else ""), not failed)


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 60 else e[:57] + "...", g if len(g) <= 130 else g[:127] + "...", s) for c, e, g, s in results]
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
    created["prompts_before"] = {r["id"] for r in db_all("SELECT id FROM ai_prompts")}
    created["models_before"] = {r["id"] for r in db_all("SELECT id FROM ai_models")}
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
