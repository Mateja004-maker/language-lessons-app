"""Provera tačke I: vrsta pada, ponovni zahtev posle lošeg formata i poruke korisniku.

Pokretanje (iz foldera backend/):
    python tests/verify_generation_failures.py

Kroz pravu rutu POST /api/questions/<id>/generate-similar, sa LAŽNIM
provajderom (requests.post vraća unapred zadat niz odgovora, time.sleep samo
beleži pauze) - nijedan pravi AI servis se ne poziva. Run-ovi i predlozi
koje provera napravi brišu se po id-jevima; na kraju se porede brojevi redova.

Kolone failure_type / first_attempt_passed / format_retries se proveravaju ako
je db/migration_failure_type_retry.sql pokrenuta; inače je taj slučaj PRESKOCENO
(isto se proverava kroz odgovor rute i params_used).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
from app import FAILURE_COLUMNS, app, get_db_connection, table_columns_exist  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_prompts", "exam_questions")
NETWORK = "NETWORK"
results = []
created = {"runs": [], "artifacts": [], "prompts_before": set()}
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
    finally:
        cur.close()
        conn.close()


def columns_enabled():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return table_columns_exist(cur, "ai_generation_runs", FAILURE_COLUMNS)
    finally:
        cur.close()
        conn.close()


def row_counts():
    return {t: db_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in COUNT_TABLES}


def cleanup():
    if created["artifacts"]:
        ph = ",".join(["%s"] * len(created["artifacts"]))
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph})", created["artifacts"])
    if created["runs"]:
        ph = ",".join(["%s"] * len(created["runs"]))
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph})", created["runs"])
    for row in db_all("SELECT id FROM ai_prompts"):
        if row["id"] not in created["prompts_before"] and not db_all(
                "SELECT 1 FROM ai_generation_runs WHERE prompt_id = %s LIMIT 1", (row["id"],)):
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (row["id"],))


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self.headers, self._body = status, headers or {}, body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError
        return self._body


def model_text(text, tokens=5, finish="stop"):
    return FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": finish}],
                              "usage": {"total_tokens": tokens}})


def run_case(source_id, sequence, h):
    calls, pauses = [], []

    def fake_post(*args, **kwargs):
        if len(calls) >= len(sequence):
            raise AssertionError("ruta je pozvala provajdera vise puta nego sto je zadato")
        item = sequence[len(calls)]
        calls.append(1)
        if item == NETWORK:
            raise requests.ConnectionError("lazna mrezna greska")
        return item

    requests.post = fake_post
    ai_provider.time.sleep = pauses.append
    r = client.post(f"/api/questions/{source_id}/generate-similar?provider=groq", headers=h)
    body = r.get_json() or {}
    if body.get("generation_run_id"):
        created["runs"].append(body["generation_run_id"])
    if body.get("artifact_id"):
        created["artifacts"].append(body["artifact_id"])
    return r.status_code, body, len(calls), pauses


def run():
    enabled = columns_enabled()
    print(f"Migracija db/migration_failure_type_retry.sql: {'POKRENUTA' if enabled else 'NIJE pokrenuta'}")
    with app.app_context():
        admin = {"Authorization": "Bearer " + create_access_token(identity="1", additional_claims={"role": "ADMIN", "email": "x"})}

    src = db_one("""SELECT q.id FROM exam_questions q JOIN exam_answers a ON a.question_id = q.id
                    WHERE q.subject_id IS NOT NULL GROUP BY q.id
                    HAVING SUM(a.is_correct) = 1 AND COUNT(*) >= 3 ORDER BY q.id DESC LIMIT 1""")
    n = db_one("SELECT COUNT(*) AS n FROM exam_answers WHERE question_id = %s", (src["id"],))["n"]
    labels = {"difficulty": "srednje", "bloom_level": "primena"}

    def mc(count=n, correct=(0,)):
        return json.dumps({"question_text": "Probno pitanje", **labels,
                           "answers": [{"answer_text": f"o{i}", "is_correct": i in correct} for i in range(count)]})

    good, bad_json = mc(), "ovo nije json"
    fenced = "```json\n" + good + "\n```"
    r503 = FakeResponse(503, "service unavailable")
    r429 = FakeResponse(429, "rate limit exceeded", {"Retry-After": "10"})

    cases = [
        # (naziv, niz odgovora, status, failure_type, first_attempt_passed, format_retries, HTTP poziva, rec u poruci)
        ("uspeh iz prve", [model_text(good)], 201, None, True, 0, 1, None),
        ("nevalidan JSON (oba puta)", [model_text(bad_json), model_text(bad_json)], 422, "invalid_json", False, 1, 2, "format"),
        ("markdown ograde (oba puta)", [model_text(fenced), model_text(fenced)], 422, "invalid_json", False, 1, 2, "format"),
        ("pogrešan broj odgovora", [model_text(mc(n - 1)), model_text(mc(n - 1))], 422, "schema", False, 1, 2, "pravila"),
        ("dva tačna odgovora", [model_text(mc(correct=(0, 1))), model_text(mc(correct=(0, 1)))], 422, "schema", False, 1, 2, "pravila"),
        ("prvi loš pa dobar (ponovni zahtev)", [model_text(bad_json, tokens=5), model_text(good, tokens=7)], 201, None, False, 1, 2, None),
        ("oba loša (JSON pa šema)", [model_text(bad_json), model_text(mc(n - 1))], 422, "schema", False, 1, 2, "pravila"),
        ("prazan odgovor (ne ponavlja se)", [model_text("", finish="length")], 422, "empty", False, 0, 1, "nije vratio"),
        ("trajni 503", [r503, r503, r503], 422, "http_5xx", False, 0, 3, "nedostupan"),
        ("mrežna greška", [NETWORK, NETWORK, NETWORK], 422, "network", False, 0, 3, "povezati"),
        ("trajni 429 sa Retry-After", [r429, r429, r429], 422, "rate_limit", False, 0, 3, "limit"),
        ("401", [FakeResponse(401, "invalid api key")], 422, "http_4xx", False, 0, 1, "ključ"),
        ("loš format pa 429 pri ponavljanju", [model_text(bad_json), r429, r429, r429], 422, "rate_limit", False, 1, 4, "limit"),
    ]

    column_mismatches = []
    for name, sequence, exp_status, exp_type, exp_first, exp_retries, exp_calls, word in cases:
        status, body, calls, pauses = run_case(src["id"], sequence, admin)
        run = db_one("""SELECT validation_passed, raw_response, validation_errors, params_used, tokens_used
                        FROM ai_generation_runs WHERE id = %s""", (body.get("generation_run_id"),)) or {}
        params = json.loads(run.get("params_used") or "{}")
        has_artifact = bool(body.get("artifact_id"))
        details = body.get("details") or ""
        checks = [
            status == exp_status,
            body.get("failure_type") == exp_type,
            body.get("first_attempt_passed") is exp_first,
            body.get("format_retries") == exp_retries,
            calls == exp_calls,
            has_artifact == (exp_status == 201),
            status != 500,
            "API greška" not in details and "mrežna greška" not in details,
            word is None or word in details,
            run.get("validation_passed") == (1 if exp_status == 201 else 0),
        ]
        extra = ""
        if exp_retries:  # prvi pokusaj sacuvan u params_used
            first = params.get("first_attempt") or {}
            checks.append(first.get("raw_response") is not None)
            extra = f", prvi u params_used={'da' if first else 'ne'}"
        if name.startswith("prvi loš pa dobar"):
            checks.append(run.get("tokens_used") == 12)
            extra += f", tokeni={run.get('tokens_used')}"
        if name == "trajni 429 sa Retry-After":
            checks.append(pauses == [10.0, 15])
            extra += f", pauze={pauses}"
        if name == "loš format pa 429 pri ponavljanju":
            checks.append(run.get("raw_response") is None)
        if enabled:
            row = db_one("SELECT failure_type, first_attempt_passed, format_retries FROM ai_generation_runs WHERE id = %s",
                         (body.get("generation_run_id"),))
            if (row["failure_type"], row["first_attempt_passed"], row["format_retries"]) != (exp_type, int(exp_first), exp_retries):
                column_mismatches.append(name)
        record(name, f"{exp_status} {exp_type or 'ok'} prvi={exp_first} pon={exp_retries} poziva={exp_calls}",
               f"{status} {body.get('failure_type') or 'ok'} prvi={body.get('first_attempt_passed')} pon={body.get('format_retries')} "
               f"poziva={calls}, predlog={'da' if has_artifact else 'ne'}{extra} | {details[:40]}",
               all(checks))

        if name.startswith("prvi loš pa dobar"):
            d = client.get(f"/api/ai/artifacts/{body['artifact_id']}", headers=admin).get_json()
            leaked = [k for k in ("provider", "model_name", "created_at", "generation_run_id", "params_used",
                                  "failure_type", "format_retries", "first_attempt_passed", "first_attempt") if k in d]
            record("slepo: detalj predloga posle ponavljanja", "bez modela i podataka o run-u", f"procurelo: {leaked or 'nista'}", not leaked)

    if enabled:
        record("kolone run-a (failure_type, first_attempt_passed, format_retries)", f"tačne za svih {len(cases)}",
               f"neslaganja: {column_mismatches or 'nema'}", not column_mismatches)
    else:
        skip("kolone run-a (failure_type, first_attempt_passed, format_retries)", "migracija nije pokrenuta")


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 55 else e[:52] + "...", g if len(g) <= 110 else g[:107] + "...", s) for c, e, g, s in results]
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
