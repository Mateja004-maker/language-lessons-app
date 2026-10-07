"""Provera tačke D: pokretač eksperimenta i referentni skup.

Pokretanje (iz foldera backend/):
    python tests/verify_experiment_runner.py

LAŽNI provajder (requests.post je zamenjen) - nijedan pravi AI servis se ne
poziva. Pravi privremene evaluacione serije i run-ove kroz stvarnu logiku
generisanja (generate_similar_for_question) nad bazom iz backend/.env i sve
briše po zabeleženim id-jevima; na kraju poredi brojeve redova.

Slučajevi koji traže tabele iz db/migration_reference_sets.sql se, ako
migracija nije pokrenuta, označavaju kao PRESKOCENO.
"""
import json
import os
import re
import sys
import uuid
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
import run_experiment as rx  # noqa: E402
from app import app, get_db_connection, reference_sets_enabled  # noqa: E402

PROVIDERS = ["groq", "gemini", "openrouter"]
COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_prompts",
                "ai_models", "evaluation_batches", "exam_questions")
TAG = uuid.uuid4().hex[:6]

results = []
created = {"batches": [], "prompts_before": set(), "sets": []}
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


def migration_enabled():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return reference_sets_enabled(cur)
    finally:
        cur.close()
        conn.close()


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


def new_batch(label):
    batch_id = db_exec("INSERT INTO evaluation_batches (name, description) VALUES (%s, 'tmp verify')",
                       (f"tmp-verify-{TAG}-{label}",))
    created["batches"].append(batch_id)
    return batch_id


def cleanup():
    batches = created["batches"]
    if batches:
        ph = ",".join(["%s"] * len(batches))
        runs = [r["id"] for r in db_all(f"SELECT id FROM ai_generation_runs WHERE evaluation_batch_id IN ({ph})", batches)]
        if runs:
            rph = ",".join(["%s"] * len(runs))
            db_exec(f"DELETE FROM ai_generated_artifacts WHERE generation_run_id IN ({rph})", runs)
            db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({rph})", runs)
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph})", batches)
    for set_id in created["sets"]:
        db_exec("DELETE FROM reference_sets WHERE id = %s", (set_id,))
    for row in db_all("SELECT id FROM ai_prompts"):
        if row["id"] not in created["prompts_before"] and not db_all(
                "SELECT 1 FROM ai_generation_runs WHERE prompt_id = %s LIMIT 1", (row["id"],)):
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (row["id"],))


# ---------- lazni provajder ----------

class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self.headers = {}
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError
        return self._body


class FakeProvider:
    """Odgovara ispravnim v3 pitanjem (MC ili otvoreno, prema promptu), osim
    za modele kojima je zadato drugačije ponašanje: 'http429' ili 'bad_format'."""

    def __init__(self):
        self.behavior = {}
        self.calls = []
        self._toggle = {}

    def __call__(self, url, **kwargs):
        provider = ("gemini" if "googleapis" in url else "openrouter" if "openrouter" in url else
                    "groq" if "groq" in url else "mistral")
        body = kwargs.get("json") or {}
        prompt = (body["contents"][0]["parts"][0]["text"] if provider == "gemini"
                  else body["messages"][0]["content"])
        self.calls.append(provider)

        mode = self.behavior.get(provider)
        if mode == "bad_then_good":  # naizmenicno: los format, pa ispravan odgovor
            self._toggle[provider] = not self._toggle.get(provider, False)
            mode = "bad_format" if self._toggle[provider] else None
        if mode == "http429":
            return FakeResponse(429, "rate limit")
        match = re.search(r"Generiši tačno (\d+) ponuđenih", prompt)
        payload = {"question_text": f"Lazno pitanje ({provider})", "difficulty": "srednje", "bloom_level": "primena"}
        if match:
            payload["answers"] = [{"answer_text": f"o{i}", "is_correct": i == 0} for i in range(int(match.group(1)))]
        if mode == "bad_format":
            payload = {"question_text": "bez oznaka"}
        text = json.dumps(payload)
        if provider == "gemini":
            return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})
        return FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                  "usage": {"total_tokens": 1}})


def batch_runs(batch_id):
    return db_all("""
        SELECT r.id, r.source_question_id, r.prompt_id, r.evaluation_batch_id, m.provider,
               (r.raw_response IS NOT NULL OR JSON_VALUE(r.params_used, '$.finish_reason') IS NOT NULL) AS answered
        FROM ai_generation_runs r JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s ORDER BY r.id
    """, (batch_id,))


def quiet(*_args, **_kwargs):
    pass


# ---------- provere ----------

def run(fake):
    # izvorna pitanja: 2 MC i (ako postoji) 1 otvoreno iz istog predmeta
    mc = db_all("""SELECT q.id, q.subject_id FROM exam_questions q JOIN exam_answers a ON a.question_id = q.id
                   WHERE q.subject_id IS NOT NULL GROUP BY q.id, q.subject_id
                   HAVING SUM(a.is_correct) = 1 AND COUNT(*) >= 2 ORDER BY q.id""")
    subject = mc[0]["subject_id"]
    same = [r["id"] for r in mc if r["subject_id"] == subject][:2]
    open_q = db_all("""SELECT q.id FROM exam_questions q WHERE q.subject_id = %s
                       AND NOT EXISTS (SELECT 1 FROM exam_answers a WHERE a.question_id = q.id) ORDER BY q.id LIMIT 1""",
                    (subject,))
    questions = same + [r["id"] for r in open_q]
    n_per = 2
    total = len(questions) * len(PROVIDERS) * n_per
    plan = rx.build_plan(questions, PROVIDERS, n_per)

    # --- plan i dry-run ---
    expected_head = [(1, questions[0], "groq"), (1, questions[0], "gemini"), (1, questions[0], "openrouter"),
                     (1, questions[1], "groq")]
    record("plan: naizmenicno po modelima", f"{expected_head}", f"{plan[:4]}", plan[:4] == expected_head and len(plan) == total)

    batch = new_batch("main")
    lines = []
    rep = rx.run_experiment(batch, questions, PROVIDERS, n_per, dry_run=True, out=lines.append)
    waiting = sum(1 for line in lines if line.strip().startswith("čeka"))  # redovi plana, bez zaglavlja
    record("--dry-run", f"{total} mesta ispisano, 0 poziva, 0 run-ova",
           f"{waiting} 'čeka', poziva={len(fake.calls)}, run-ova={len(batch_runs(batch))}",
           waiting == total and not fake.calls and not batch_runs(batch) and rep["calls"] == 0)

    # --- prekid posle 4 poziva ---
    rep = rx.run_experiment(batch, questions, PROVIDERS, n_per, max_calls=4, out=quiet)
    runs = batch_runs(batch)
    order = [(r["source_question_id"], r["provider"]) for r in runs]
    record("prekid posle 4 poziva (--max-calls)", "4 run-a, redom iz plana",
           f"{len(runs)} run-a: {order}", len(runs) == 4 and order == [(q, p) for _, q, p in plan[:4]])

    # --- nastavak ne duplira ---
    rep = rx.run_experiment(batch, questions, PROVIDERS, n_per, out=quiet)
    runs = batch_runs(batch)
    per_slot = Counter((r["source_question_id"], r["provider"]) for r in runs)
    record("nastavak posle prekida", f"jos {total - 4} poziva, ukupno {total}, svako (pitanje, model) tacno {n_per}",
           f"poziva={rep['calls']}, run-ova={len(runs)}, broj po mestu={sorted(set(per_slot.values()))}",
           rep["calls"] == total - 4 and len(runs) == total and set(per_slot.values()) == {n_per}
           and len(per_slot) == len(questions) * len(PROVIDERS))

    rep = rx.run_experiment(batch, questions, PROVIDERS, n_per, out=quiet)
    record("ponovno pokretanje zavrsene serije", "0 poziva", f"poziva={rep['calls']}, preostalo={rep['pending']}",
           rep["calls"] == 0 and rep["pending"] == 0)

    prompts_per_q = {q: {r["prompt_id"] for r in runs if r["source_question_id"] == q} for q in questions}
    providers_per_q = {q: {r["provider"] for r in runs if r["source_question_id"] == q} for q in questions}
    record("isti source_question_id x prompt_id za svaki model", "1 prompt po pitanju, svi modeli",
           f"promptova po pitanju={[len(v) for v in prompts_per_q.values()]}, modela={[len(v) for v in providers_per_q.values()]}",
           all(len(v) == 1 for v in prompts_per_q.values()) and all(v == set(PROVIDERS) for v in providers_per_q.values()))
    record("svi run-ovi imaju evaluation_batch_id", f"{total} x {batch}",
           f"{Counter(r['evaluation_batch_id'] for r in runs)}", all(r["evaluation_batch_id"] == batch for r in runs))

    # --- 429 (dnevni limit) i los format ---
    batch2 = new_batch("limit")
    fake.behavior = {"gemini": "http429", "openrouter": "bad_format"}
    calls_before = len(fake.calls)
    rep = rx.run_experiment(batch2, questions, PROVIDERS, 1, out=quiet)
    gemini_http = fake.calls[calls_before:].count("gemini")
    record("429 zaustavlja samo taj model", "gemini zaustavljen posle 1 mesta (3 HTTP pokusaja), ostali nastavljaju",
           f"gemini stopped={'gemini' in rep['stopped']}, gemini HTTP poziva={gemini_http}, groq ok={rep['ok_first']['groq']}, "
           f"vrste={dict(rep['infra_types']['gemini'])}",
           "gemini" in rep["stopped"] and gemini_http == 3 and rep["ok_first"]["groq"] == len(questions)
           and rep["infra_types"]["gemini"] == {"rate_limit": 1})
    record("los format se racuna kao odgovor", f"openrouter format={len(questions)}",
           f"format={rep['format']['openrouter']}, razlozi={dict(rep['reasons']['openrouter'])}",
           rep["format"]["openrouter"] == len(questions))

    fake.behavior = {}
    rep = rx.run_experiment(batch2, questions, PROVIDERS, 1, out=quiet)
    runs2 = batch_runs(batch2)
    answered = Counter(r["provider"] for r in runs2 if r["answered"])
    record("nastavak posle limita", f"pozivi samo za gemini ({len(questions)}), openrouter se ne ponavlja",
           f"poziva={rep['calls']}, odgovorenih po modelu={dict(answered)}, infra run-ova sacuvano={sum(1 for r in runs2 if not r['answered'])}",
           rep["calls"] == len(questions) and answered == Counter({p: len(questions) for p in PROVIDERS}))

    # --- ponovni zahtev posle loseg formata ---
    batch5 = new_batch("retry")
    fake.behavior = {"groq": "bad_then_good"}
    calls_before = len(fake.calls)
    rep = rx.run_experiment(batch5, questions, PROVIDERS, 1, out=quiet)
    groq_http = fake.calls[calls_before:].count("groq")
    record("los pa dobar odgovor = ok posle ponavljanja", f"groq ok_retry={len(questions)}, 2 HTTP poziva po mestu, ostali ok iz prve",
           f"ok_retry={rep['ok_retry']['groq']}, groq HTTP={groq_http}, ok_first gemini/openrouter={rep['ok_first']['gemini']}/{rep['ok_first']['openrouter']}",
           rep["ok_retry"]["groq"] == len(questions) and groq_http == 2 * len(questions)
           and rep["ok_first"]["gemini"] == len(questions) and rep["ok_first"]["openrouter"] == len(questions))
    fake.behavior = {}

    # --- zastita protokola i ulaz ---
    batch3 = new_batch("protokol")
    old_prompt = db_all("SELECT id FROM ai_prompts WHERE purpose = 'similar_question' AND version = 'mc-v2'")[0]["id"]
    model_id = db_all("SELECT id FROM ai_models WHERE provider = 'groq' AND model_name = %s",
                      (ai_provider.DEFAULT_MODELS["groq"],))[0]["id"]
    db_exec("""INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, source_question_id, params_used,
               validation_passed, retry_count, evaluation_batch_id) VALUES (%s, %s, 'similar_question', %s, '{}', 0, 0, %s)""",
            (model_id, old_prompt, questions[0], batch3))
    try:
        rx.run_experiment(batch3, questions, PROVIDERS, 1, out=quiet)
        got = "nije odbijeno"
    except rx.ExperimentError as e:
        got = str(e).splitlines()[0]
    record("serija sa starim promptom (mc-v2)", "ExperimentError, bez poziva", got, got.startswith("Protokol"))

    try:
        rx.run_experiment(batch, questions, ["groq", "chatgpt"], 1, out=quiet)
        got = "nije odbijeno"
    except rx.ExperimentError as e:
        got = str(e)
    record("nepoznat model", "ExperimentError", got, got.startswith("Nepoznati modeli"))

    # --- referentni skup (rute) ---
    with app.app_context():
        admin = {"Authorization": "Bearer " + create_access_token(identity="1", additional_claims={"role": "ADMIN", "email": "x"})}
    other = db_all("SELECT id FROM exam_questions WHERE subject_id IS NOT NULL AND subject_id <> %s LIMIT 1", (subject,))[0]["id"]
    r = client.post("/api/reference-sets", headers=admin,
                    json={"name": f"tmp-{TAG}", "subject_id": subject, "question_ids": [questions[0], other]})
    record("skup: pitanje van predmeta", "400 sa tim id-jem", f"{r.status_code} {r.get_json()}",
           r.status_code == 400 and r.get_json().get("question_ids") == [other])

    # --- ruta generisanja i dalje radi (sa serijom) ---
    r = client.post(f"/api/questions/{questions[0]}/generate-similar?provider=groq&evaluation_batch_id={batch3}", headers=admin)
    body = r.get_json() or {}
    run_row = db_all("SELECT evaluation_batch_id FROM ai_generation_runs WHERE id = %s", (body.get("generation_run_id"),))
    record("ruta generisanja sa serijom", "201, run u seriji", f"{r.status_code}, serija={run_row[0]['evaluation_batch_id'] if run_row else None}",
           r.status_code == 201 and run_row and run_row[0]["evaluation_batch_id"] == batch3)

    if not migration_enabled():
        r = client.post("/api/reference-sets", headers=admin,
                        json={"name": f"tmp-{TAG}", "subject_id": subject, "question_ids": questions})
        record("skup: ispravan zahtev PRE migracije", "409, poruka o migraciji", f"{r.status_code} {r.get_json()}", r.status_code == 409)
        for case in ("skup: pravljenje i detalj", "pokretac cita pitanja iz skupa serije"):
            skip(case, "migracija nije pokrenuta")
        return

    r = client.post("/api/reference-sets", headers=admin,
                    json={"name": f"tmp-{TAG}", "subject_id": subject, "question_ids": list(reversed(questions))})
    set_id = (r.get_json() or {}).get("id")
    if set_id:
        created["sets"].append(set_id)
    d = client.get(f"/api/reference-sets/{set_id}", headers=admin).get_json() or {}
    record("skup: pravljenje i detalj", f"201, pitanja redom {list(reversed(questions))}",
           f"{r.status_code}, {[q['question_id'] for q in d.get('questions', [])]}",
           r.status_code == 201 and [q["question_id"] for q in d.get("questions", [])] == list(reversed(questions)))

    batch4 = new_batch("skup")
    ids = rx.resolve_question_ids(batch4, set_id)
    linked = db_all("SELECT reference_set_id FROM evaluation_batches WHERE id = %s", (batch4,))[0]["reference_set_id"]
    record("pokretac cita pitanja iz skupa serije", f"{list(reversed(questions))}, serija vezana za skup",
           f"{ids}, reference_set_id={linked}", ids == list(reversed(questions)) and linked == set_id)
    db_exec("UPDATE evaluation_batches SET reference_set_id = NULL WHERE id = %s", (batch4,))


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 70 else e[:67] + "...", g if len(g) <= 90 else g[:87] + "...", s) for c, e, g, s in results]
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
    print(f"Migracija db/migration_reference_sets.sql: {'POKRENUTA' if migration_enabled() else 'NIJE pokrenuta'}")
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
