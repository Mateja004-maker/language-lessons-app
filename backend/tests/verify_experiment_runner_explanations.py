"""Provera pokretača eksperimenta za objašnjenja (--task explanation).

Pokretanje (iz foldera backend/):
    python tests/verify_experiment_runner_explanations.py

LAŽNI provajder (requests.post je zamenjen) - nijedan pravi AI servis se ne
poziva. Pokretač ide kroz svoj podrazumevani generator
(generate_explanation_for_question), pa se proveravaju i run-ovi u bazi.
Modeli su groq i gemini (ključevi iz backend/.env; poziv ide lažnom provajderu).

Provera pravi privremena pitanja (MC, programsko sa test primerima i
referentnim rešenjem, otvoreno bez rešenja) i privremene serije; sve se briše
po id-jevima, a na kraju se porede brojevi redova.
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import requests  # noqa: E402

# app pre ai_provider-a: app.py ucitava backend/.env, a ai_provider cita kljuceve pri ucitavanju
from app import get_db_connection  # noqa: E402
import ai_provider  # noqa: E402
import run_experiment as rx  # noqa: E402

PROVIDERS = ["groq", "gemini"]
COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_prompts", "ai_models", "evaluation_batches",
                "exam_questions", "exam_answers", "exam_question_test_cases")
TAG = uuid.uuid4().hex[:6]

results = []
created = {"batches": [], "questions": [], "prompts_before": set(), "models_before": set()}


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


def new_batch(label):
    batch_id = db_exec("INSERT INTO evaluation_batches (name, description) VALUES (%s, 'tmp verify')",
                       (f"tmp-verify-expl-{TAG}-{label}",))
    created["batches"].append(batch_id)
    return batch_id


def _delete_ids(table, ids, column="id"):
    if ids:
        ph = ",".join(["%s"] * len(ids))
        db_exec(f"DELETE FROM {table} WHERE {column} IN ({ph})", ids)


def cleanup():
    batches = created["batches"]
    if batches:
        ph = ",".join(["%s"] * len(batches))
        runs = [r["id"] for r in db_all(f"SELECT id FROM ai_generation_runs WHERE evaluation_batch_id IN ({ph})", batches)]
        _delete_ids("ai_generated_artifacts", runs, "generation_run_id")
        _delete_ids("ai_generation_runs", runs)
        _delete_ids("evaluation_batches", batches)
    for table, before, column in (("ai_prompts", "prompts_before", "prompt_id"), ("ai_models", "models_before", "model_id")):
        for row in db_all(f"SELECT id FROM {table}"):
            if row["id"] not in created[before] and not db_all(
                    f"SELECT 1 FROM ai_generation_runs WHERE {column} = %s LIMIT 1", (row["id"],)):
                db_exec(f"DELETE FROM {table} WHERE id = %s", (row["id"],))
    _delete_ids("exam_question_test_cases", created["questions"], "question_id")
    _delete_ids("exam_answers", created["questions"], "question_id")
    _delete_ids("exam_questions", created["questions"])


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
    """Odgovara ispravnim objašnjenjem za zadati režim (self.mode). U režimu B
    odgovor nosi i rešenje (kod) i selected_option, pa važi za programsko, MC i
    otvoreno pitanje. Ponašanje po modelu: 'bad_json', 'http429' ili 'wrong'
    (pogrešno rešenje i pogrešna opcija)."""

    def __init__(self):
        self.mode = "mode_a"
        self.behavior = {}
        self.calls = []

    def __call__(self, url, **kwargs):
        provider = "gemini" if "googleapis" in url else "groq"
        self.calls.append(provider)
        behavior = self.behavior.get(provider)
        if behavior == "http429":
            return FakeResponse(429, "rate limit")
        if self.mode == "mode_a":
            payload = {"explanation": f"Lazno objasnjenje ({provider})"}
        elif behavior == "wrong":
            payload = {"solution": "print(int(input()) + 1)", "selected_option": 1, "explanation": "Pogresno."}
        else:
            payload = {"solution": "print(int(input()) * 2)", "selected_option": 2, "explanation": "Tacno."}
        text = "ovo nije json" if behavior == "bad_json" else json.dumps(payload)
        if provider == "gemini":
            return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})
        return FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                  "usage": {"total_tokens": 1}})


def make_questions():
    subject = db_all("SELECT MIN(id) AS id FROM subjects")[0]["id"]

    def question(text, reference_solution=None):
        qid = db_exec("INSERT INTO exam_questions (subject_id, question_text, reference_solution) VALUES (%s, %s, %s)",
                      (subject, f"{text} [{TAG}]", reference_solution))
        created["questions"].append(qid)
        return qid

    mc = question("Pokretac objasnjenja: koliko je 2 + 2?")
    for text, correct in (("3", 0), ("4", 1), ("5", 0)):
        db_exec("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)", (mc, text, correct))
    prog = question("Pokretac objasnjenja: ispisi udvostruceni ulaz.", "print(int(input()) * 2)")
    for order_no, (given, expected) in enumerate((("3", "6"), ("5", "10")), start=1):
        db_exec("INSERT INTO exam_question_test_cases (question_id, input_data, expected_output, order_no) "
                "VALUES (%s, %s, %s, %s)", (prog, given, expected, order_no))
    open_q = question("Pokretac objasnjenja: objasni pojam promenljive.")
    return mc, prog, open_q


def batch_runs(batch_id):
    return db_all("""
        SELECT r.id, r.source_question_id, r.purpose, r.mode, r.prompt_id, m.provider
        FROM ai_generation_runs r JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s ORDER BY r.id
    """, (batch_id,))


def quiet(*_args, **_kwargs):
    pass


def expect_error(fn):
    try:
        fn()
        return "bez greske"
    except rx.ExperimentError as e:
        return str(e)


# ---------- provere ----------

def run(fake):
    mc, prog, open_q = make_questions()
    questions = [mc, prog, open_q]

    # --- validacija parametara ---
    batch = new_batch("a")
    got = [
        expect_error(lambda: rx.run_experiment(batch, questions, PROVIDERS, 1, dry_run=True, out=quiet, task="explanation")),
        expect_error(lambda: rx.run_experiment(batch, questions, PROVIDERS, 1, dry_run=True, out=quiet, task="explanation",
                                               explain_mode="mode_a", mode="set", group_size=2, k=2)),
        expect_error(lambda: rx.run_experiment(batch, questions, PROVIDERS, 1, dry_run=True, out=quiet, explain_mode="mode_a")),
        expect_error(lambda: rx.run_experiment(batch, [open_q], PROVIDERS, 1, dry_run=True, out=quiet, task="explanation",
                                               explain_mode="mode_a")),
    ]
    record("neispravni parametri", "4 x ExperimentError (bez rezima, set, rezim uz pitanja, A bez resenja)",
           " | ".join(g[:30] for g in got),
           got[0].startswith("--explain-mode je obavezan") and got[1].startswith("--mode set")
           and got[2].startswith("--explain-mode važi samo") and got[3].startswith("Nijedno pitanje"))

    # --- rezim A: dry-run i preskocena pitanja ---
    fake.mode = "mode_a"
    lines = []
    rx.run_experiment(batch, questions, PROVIDERS, 2, dry_run=True, out=lines.append, task="explanation", explain_mode="mode_a")
    waiting = [line for line in lines if line.strip().startswith("čeka")]
    skipped_lines = [line for line in lines if "preskočeno" in line]
    record("A: --dry-run sa preskocenim pitanjem", f"zaglavlje [explanation mode_a] 2 pitanja = 8 mesta, 8 'čeka', "
           f"pitanje {open_q} preskočeno, 0 poziva",
           f"{lines[0][:60]}... čeka={len(waiting)}, preskočeno={skipped_lines}, poziva={len(fake.calls)}, run-ova={len(batch_runs(batch))}",
           "[explanation mode_a]: 2 pitanja x 2 modela x 2 = 8 mesta" in lines[0] and len(waiting) == 8
           and len(skipped_lines) == 1 and f"pitanje {open_q}: nema poznatog rešenja" in skipped_lines[0]
           and not fake.calls and not batch_runs(batch))

    # --- rezim A: prekid, nastavak, zavrsena serija ---
    rep = rx.run_experiment(batch, questions, PROVIDERS, 2, max_calls=3, out=quiet, task="explanation", explain_mode="mode_a")
    first = [(r["source_question_id"], r["provider"]) for r in batch_runs(batch)]
    record("A: prekid posle 3 poziva", f"3 run-a redom: {[(mc, 'groq'), (mc, 'gemini'), (prog, 'groq')]}",
           f"{first}, ok_first={dict(rep['ok_first'])}",
           first == [(mc, "groq"), (mc, "gemini"), (prog, "groq")] and sum(rep["ok_first"].values()) == 3)
    rep = rx.run_experiment(batch, questions, PROVIDERS, 2, out=quiet, task="explanation", explain_mode="mode_a")
    runs = batch_runs(batch)
    per_slot = {(r["source_question_id"], r["provider"]) for r in runs}
    counts = {slot: sum(1 for r in runs if (r["source_question_id"], r["provider"]) == slot) for slot in per_slot}
    record("A: nastavak bez dupliranja", "jos 5 poziva, 8 run-ova, svako (pitanje, model) tacno 2, otvoreno nijednom",
           f"poziva={rep['calls']}, run-ova={len(runs)}, po mestu={sorted(set(counts.values()))}, "
           f"svi explanation/mode_a={all((r['purpose'], r['mode']) == ('explanation', 'mode_a') for r in runs)}",
           rep["calls"] == 5 and len(runs) == 8 and set(counts.values()) == {2}
           and open_q not in {r["source_question_id"] for r in runs}
           and all((r["purpose"], r["mode"]) == ("explanation", "mode_a") for r in runs))
    rep = rx.run_experiment(batch, questions, PROVIDERS, 2, out=quiet, task="explanation", explain_mode="mode_a")
    record("A: zavrsena serija", "0 poziva, 0 preostalo", f"poziva={rep['calls']}, preostalo={rep['pending']}",
           rep["calls"] == 0 and rep["pending"] == 0)
    record("brojanje po rezimu", "serija A nema odgovorenih mesta za mode_b",
           f"mode_b={rx.answered_counts(batch, explain_mode='mode_b')}",
           rx.answered_counts(batch, explain_mode="mode_b") == {})

    # --- rezim B: mehanicka provera u izvestaju ---
    fake.mode = "mode_b"
    fake.behavior = {"gemini": "wrong"}
    batch_b = new_batch("b")
    rep = rx.run_experiment(batch_b, questions, PROVIDERS, 1, out=quiet, task="explanation", explain_mode="mode_b")
    report_lines = []
    rx.print_report(rep, PROVIDERS, out=report_lines.append)
    acc_lines = [line.strip() for line in report_lines if "mehanička provera" in line]
    record("B: sva 3 pitanja, provera po modelu", "6 poziva; groq prosla 2 / nije izvrsena 1, gemini nije prosla 2 / nije izvrsena 1",
           f"poziva={rep['calls']}, {acc_lines}",
           rep["calls"] == 6 and acc_lines == [
               "groq: mehanička provera - prošla 2, nije prošla 0, nije izvršena 1",
               "gemini: mehanička provera - prošla 0, nije prošla 2, nije izvršena 1"])

    # --- 422 se razvrstava po failure_type, ne kao greska ---
    fake.mode = "mode_a"
    fake.behavior = {"groq": "bad_json", "gemini": "http429"}
    batch_f = new_batch("format")
    rep = rx.run_experiment(batch_f, questions, PROVIDERS, 1, out=quiet, task="explanation", explain_mode="mode_a")
    record("422: los format i 429", "groq format=2 (nije zaustavljen), gemini infra rate_limit i zaustavljen, greska=0",
           f"groq format={rep['format']['groq']}, gemini infra={dict(rep['infra_types']['gemini'])}, "
           f"zaustavljeni={sorted(rep['stopped'])}, greska={sum(rep['error'].values())}",
           rep["format"]["groq"] == 2 and "groq" not in rep["stopped"]
           and rep["infra_types"]["gemini"] == {"rate_limit": 1} and "gemini" in rep["stopped"]
           and sum(rep["error"].values()) == 0)
    fake.behavior = {}

    # --- zastita protokola ---
    got = [expect_error(lambda: rx.run_experiment(batch, questions, PROVIDERS, 2, dry_run=True, out=quiet,
                                                  task="explanation", explain_mode="mode_b"))]
    batch_mix = new_batch("mix")
    db_exec("""INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, source_question_id, evaluation_batch_id, validation_passed)
               SELECT model_id, prompt_id, 'similar_question', source_question_id, %s, 0
               FROM ai_generation_runs WHERE id = %s""", (batch_mix, runs[0]["id"]))
    got.append(expect_error(lambda: rx.run_experiment(batch_mix, questions, PROVIDERS, 1, dry_run=True, out=quiet,
                                                      task="explanation", explain_mode="mode_a")))
    mode_b_prompt = batch_runs(batch_b)[0]["prompt_id"]
    db_exec("UPDATE ai_generation_runs SET prompt_id = %s WHERE id = %s", (mode_b_prompt, runs[0]["id"]))
    got.append(expect_error(lambda: rx.run_experiment(batch, questions, PROVIDERS, 2, dry_run=True, out=quiet,
                                                      task="explanation", explain_mode="mode_a")))
    record("serija ne mesa rezime, zadatke ni verzije prompta", "3 x ExperimentError",
           " | ".join(g.replace("Protokol bi bio narušen:\n  - ", "")[:45] for g in got),
           "u režimu mode_a - serija ne sme da meša režime" in got[0]
           and "drugog zadatka (similar_question)" in got[1]
           and "aktivan je mode_a-v1" in got[2])


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e if len(e) <= 70 else e[:67] + "...", g if len(g) <= 110 else g[:107] + "...", s) for c, e, g, s in results]
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
    created["models_before"] = {r["id"] for r in db_all("SELECT id FROM ai_models")}
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
