"""Provera alata tools/validate_batch.py na izmišljenim podacima.

Pokretanje (iz foldera backend/):
    python tests/verify_validate_batch.py

Bez AI poziva: privremena pitanja, run-ovi i predlozi se upisuju direktno u bazu
(tri privremene serije: ispravna, sa greškama, prazna). Sve se briše po
zabeleženim id-jevima i porede se brojevi redova pre i posle.
"""
import io
import json
import os
import sys
import uuid
from contextlib import redirect_stdout

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

from app import get_db_connection  # noqa: E402
import validate_batch as vb  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "evaluation_batches", "exam_questions", "exam_answers")
TAG = uuid.uuid4().hex[:6]
LABELS = {"difficulty": "srednje", "bloom_level": "primena"}

results = []
created = {"batches": [], "runs": [], "artifacts": [], "questions": []}


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


def lookup(sql, params=()):
    rows = db_all(sql, params)
    if not rows:
        raise SystemExit(f"Nedostaje u bazi: {sql % params if params else sql}")
    return rows[0]["id"]


def mc(n=4, correct=1, labels=True, text="Izmisljeno MC"):
    body = {"question_text": f"{text} {TAG}", "answers": [{"answer_text": f"o{i}", "is_correct": i < correct} for i in range(n)]}
    return {**body, **(LABELS if labels else {})}


def open_q(labels=True, **extra):
    return {"question_text": f"Izmisljeno otvoreno {TAG}", **(LABELS if labels else {}), **extra}


def make_question(answers):
    qid = db_exec("INSERT INTO exam_questions (question_text) VALUES (%s)", (f"tmp-validate {TAG}",))
    created["questions"].append(qid)
    for i in range(answers):
        db_exec("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)", (qid, f"a{i}", i == 0))
    return qid


def make_batch(name):
    bid = db_exec("INSERT INTO evaluation_batches (name) VALUES (%s)", (f"tmp-validate-{name}-{TAG}",))
    created["batches"].append(bid)
    return bid


def make_run(batch, model, prompt, purpose, source=None, passed=1, parsed=None, params=None):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, source_question_id, params_used, parsed_result,
               validation_passed, evaluation_batch_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (model, prompt, purpose, source, json.dumps(params or {"temperature": 0.7}),
          json.dumps(parsed) if parsed is not None else None, passed, batch))
    created["runs"].append(rid)
    return rid


def make_artifact(run, body, artifact_type="question"):
    aid = db_exec("INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text) "
                  "VALUES (%s, %s, 'predlog', %s)", (run, artifact_type, json.dumps(body) if isinstance(body, dict) else body))
    created["artifacts"].append(aid)
    return aid


def cleanup():
    def ph(ids):
        return ",".join(["%s"] * len(ids))
    for table, key in (("ai_generated_artifacts", "artifacts"), ("ai_generation_runs", "runs"),
                       ("evaluation_batches", "batches")):
        if created[key]:
            db_exec(f"DELETE FROM {table} WHERE id IN ({ph(created[key])})", created[key])
    if created["questions"]:
        db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(created['questions'])})", created["questions"])
        db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(created['questions'])})", created["questions"])


def run_tool(batch_id):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = vb.validate_batch(batch_id)
    return code, buf.getvalue()


def line_for(output, artifact_id):
    return next((l for l in output.splitlines() if f"predlog #{artifact_id} " in l), "")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    model = lookup("SELECT id FROM ai_models ORDER BY id LIMIT 1")
    p = {v: lookup("SELECT id FROM ai_prompts WHERE version = %s", (v,)) for v in ("mc-v3", "open-v3", "set-v1", "mc-v2")}
    model_names = [r["model_name"] for r in db_all("SELECT model_name FROM ai_models")]

    before = row_counts()
    try:
        src4, src_open = make_question(4), make_question(0)

        # --- serija bez gresaka ---
        good = make_batch("ok")
        r1 = make_run(good, model, p["mc-v3"], "similar_question", src4)
        g1 = make_artifact(r1, mc(4))
        r2 = make_run(good, model, p["open-v3"], "similar_question", src_open)
        g2 = make_artifact(r2, open_q())
        items = [mc(3), open_q()]
        r3 = make_run(good, model, p["set-v1"], "similar_question_set", parsed={"questions": items}, params={"k": 3})
        g3, g4 = make_artifact(r3, items[0]), make_artifact(r3, items[1])
        make_run(good, model, p["mc-v3"], "similar_question", src4, passed=0)   # pad bez predloga
        code, out = run_tool(good)
        record("ispravna serija: izlazni kod", 0, code, code == 0)
        passes = [line_for(out, a).startswith("PASS") for a in (g1, g2, g3, g4)]
        record("ispravna serija: 4 x PASS", [True] * 4, passes, all(passes))
        record("ispravna serija: run bez predloga nije FAIL", "pomenut u rezimeu",
               "da" if "run-ova bez predloga pitanja" in out else "ne", "run-ova bez predloga pitanja" in out and "FAIL  run" not in out)

        # --- serija sa greskama ---
        bad = make_batch("bad")
        b1 = make_artifact(make_run(bad, model, p["mc-v3"], "similar_question", src4), mc(3))          # 3 umesto 4
        b2 = make_artifact(make_run(bad, model, p["mc-v3"], "similar_question", src4), mc(4, correct=2))
        b3 = make_artifact(make_run(bad, model, p["open-v3"], "similar_question", src_open), open_q(answers=[]))
        b4 = make_artifact(make_run(bad, model, p["mc-v3"], "similar_question", src4), mc(4, labels=False))
        b5 = make_artifact(make_run(bad, model, p["mc-v2"], "similar_question", src4), mc(4, labels=False))  # v2: oznake nisu obavezne
        b6 = make_artifact(make_run(bad, model, p["mc-v3"], "similar_question", src4), "nije json")
        set_items = [mc(4), open_q(labels=False)]
        r_set = make_run(bad, model, p["set-v1"], "similar_question_set", parsed={"questions": set_items}, params={"k": 2})
        b7, b8 = make_artifact(r_set, set_items[0]), make_artifact(r_set, set_items[1])   # druga stavka bez oznaka
        r_incons = make_run(bad, model, p["mc-v3"], "similar_question", src4, passed=0)
        b9 = make_artifact(r_incons, mc(4))                                                # predlog uz neuspeo run
        b10 = make_artifact(make_run(bad, model, p["mc-v3"], "explanation", src4), {"explanation": "x"}, "explanation")
        code, out = run_tool(bad)
        record("serija sa greskama: izlazni kod", 1, code, code == 1)
        expect = {b1: "FAIL", b2: "FAIL", b3: "FAIL", b4: "FAIL", b5: "PASS", b6: "FAIL", b7: "PASS", b8: "FAIL", b9: "PASS", b10: "SKIP"}
        got = {a: line_for(out, a)[:4].strip() for a in expect}
        record("ishod po predlogu", list(expect.values()), list(got.values()), got == expect)
        record("razlog: broj odgovora", "Očekivano je tačno 4", line_for(out, b1)[-45:], "tačno 4 ponuđenih" in line_for(out, b1))
        record("razlog: neispravan JSON", "nije validan JSON", line_for(out, b6)[-35:], "nije validan JSON" in line_for(out, b6))
        record("doslednost: set run (1 od 2 stavke ispravna)", f"FAIL run #{r_set}",
               "da" if f"run #{r_set}" in out else "ne",
               any(l.startswith(f"FAIL  run #{r_set}") and "prihvata 1" in l for l in out.splitlines()))
        record("doslednost: predlog uz validation_passed = 0", f"FAIL run #{r_incons}", "da" if f"run #{r_incons} " in out else "ne",
               any(l.startswith(f"FAIL  run #{r_incons}") for l in out.splitlines()))
        record("objasnjenje preskoceno i navedeno", "preskočeno: 1", "da" if "preskočeno (nisu predlozi pitanja): 1" in out else "ne",
               "preskočeno (nisu predlozi pitanja): 1" in out)
        record("model se ne ispisuje", [], [m for m in model_names if m in out], not [m for m in model_names if m in out])

        # --- obrisan izvor ---
        orphan_src = make_question(4)
        orphan_batch = make_batch("orphan")
        o1 = make_artifact(make_run(orphan_batch, model, p["mc-v3"], "similar_question", orphan_src), mc(4))
        db_exec("DELETE FROM exam_answers WHERE question_id = %s", (orphan_src,))
        db_exec("DELETE FROM exam_questions WHERE id = %s", (orphan_src,))
        created["questions"].remove(orphan_src)
        code, out = run_tool(orphan_batch)
        record("obrisano izvorno pitanje -> FAIL sa razlogom", "1 / izvorno pitanje", f"{code} / {line_for(out, o1)[:4]}",
               code == 1 and "izvorno pitanje više ne postoji" in line_for(out, o1))

        # --- prazna i nepostojeca serija, komandna linija ---
        empty = make_batch("empty")
        code, out = run_tool(empty)
        record("prazna serija", 3, code, code == 3 and "nema nijedan predlog" in out)
        missing = db_all("SELECT COALESCE(MAX(id), 0) + 1000 AS id FROM evaluation_batches")[0]["id"]
        code, _ = run_tool(missing)
        record("nepostojeca serija", 2, code, code == 2)
        # komandna linija u istom procesu (novi proces bi ponovo učitao .env - vidi tools/test_clean_db.py)
        cli = []
        for b in (good, bad):
            with redirect_stdout(io.StringIO()):
                cli.append(vb.main(["--batch", str(b)]))
        record("komandna linija: izlazni kodovi", [0, 1], cli, cli == [0, 1])

        # --- samo citanje ---
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            try:
                cur.execute("UPDATE evaluation_batches SET name = name WHERE id = %s", (good,))
                blocked = False
            except Exception as e:  # 1792: Cannot execute statement in a READ ONLY transaction
                blocked = "READ ONLY" in str(e)
            conn.rollback()
        finally:
            cur.close()
            conn.close()
        record("READ ONLY sesija odbija upis", "odbijeno", "odbijeno" if blocked else "dozvoljeno", blocked)
    finally:
        cleanup()
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
