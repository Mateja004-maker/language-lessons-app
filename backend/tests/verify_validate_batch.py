"""Provera alata tools/validate_batch.py na izmišljenim podacima.

Pokretanje (iz foldera backend/):
    python tests/verify_validate_batch.py

Bez AI poziva: privremena pitanja, run-ovi i predlozi se upisuju direktno u bazu
(privremene serije: ispravna, sa greškama, prazna, i po jedna ispravna i sa
greškama za objašnjenja, uz privremene šablone objašnjenja). Sve se briše po
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

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "evaluation_batches", "exam_questions", "exam_answers",
                "ai_prompts")
TAG = uuid.uuid4().hex[:6]
LABELS = {"difficulty": "srednje", "bloom_level": "primena"}

results = []
created = {"batches": [], "runs": [], "artifacts": [], "questions": [], "prompts": []}


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


def make_prompt(version_prefix):
    """Privremeni šablon objašnjenja; verzija ima pravi prefiks (mode_b_mc- ...) i oznaku testa."""
    pid = db_exec("INSERT INTO ai_prompts (purpose, version, template) VALUES ('explanation', %s, 'tmp')",
                  (f"{version_prefix}-t{TAG}",))
    created["prompts"].append(pid)
    return pid


def make_run(batch, model, prompt, purpose, source=None, passed=1, parsed=None, params=None, mode=None):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, mode, source_question_id, params_used, parsed_result,
               validation_passed, evaluation_batch_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (model, prompt, purpose, mode, source, json.dumps(params or {"temperature": 0.7}),
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
    if created["prompts"]:
        db_exec(f"DELETE FROM ai_prompts WHERE id IN ({ph(created['prompts'])})", created["prompts"])


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
        b10 = make_artifact(make_run(bad, model, p["mc-v3"], "explanation", src4), {"explanation": "x"}, "explanation")  # bez režima
        b11 = make_artifact(make_run(bad, model, p["mc-v3"], "explanation", src4, mode="mode_a"), mc(4))  # pitanje iz run-a objašnjenja
        code, out = run_tool(bad)
        record("serija sa greskama: izlazni kod", 1, code, code == 1)
        expect = {b1: "FAIL", b2: "FAIL", b3: "FAIL", b4: "FAIL", b5: "PASS", b6: "FAIL", b7: "PASS", b8: "FAIL", b9: "PASS",
                  b10: "FAIL", b11: "SKIP"}
        got = {a: line_for(out, a)[:4].strip() for a in expect}
        record("ishod po predlogu", list(expect.values()), list(got.values()), got == expect)
        record("razlog: broj odgovora", "Očekivano je tačno 4", line_for(out, b1)[-45:], "tačno 4 ponuđenih" in line_for(out, b1))
        record("razlog: neispravan JSON", "nije validan JSON", line_for(out, b6)[-35:], "nije validan JSON" in line_for(out, b6))
        record("doslednost: set run (1 od 2 stavke ispravna)", f"FAIL run #{r_set}",
               "da" if f"run #{r_set}" in out else "ne",
               any(l.startswith(f"FAIL  run #{r_set}") and "prihvata 1" in l for l in out.splitlines()))
        record("doslednost: predlog uz validation_passed = 0", f"FAIL run #{r_incons}", "da" if f"run #{r_incons} " in out else "ne",
               any(l.startswith(f"FAIL  run #{r_incons}") for l in out.splitlines()))
        record("razlog: objasnjenje bez rezima", "nepoznat režim", line_for(out, b10)[-30:], "nepoznat režim" in line_for(out, b10))
        record("pitanje iz run-a objasnjenja preskoceno i navedeno", "preskočeno: 1",
               "da" if "preskočeno (nisu predlozi pitanja ni objašnjenja): 1" in out else "ne",
               "preskočeno (nisu predlozi pitanja ni objašnjenja): 1" in out)
        record("model se ne ispisuje", [], [m for m in model_names if m in out], not [m for m in model_names if m in out])

        # --- objasnjenja (Andrejev modul): format i doslednost ---
        pa, pb, pb_mc = make_prompt("mode_a"), make_prompt("mode_b"), make_prompt("mode_b_mc")
        expl = {"explanation": "Izmisljeno objasnjenje."}
        expl_ok = make_batch("expl-ok")
        e1 = make_artifact(make_run(expl_ok, model, pa, "explanation", src4, mode="mode_a"), expl, "explanation")
        e2 = make_artifact(make_run(expl_ok, model, pb_mc, "explanation", src4, mode="mode_b"),
                           {"selected_option": 1, **expl}, "explanation")
        e3 = make_artifact(make_run(expl_ok, model, pb, "explanation", src_open, mode="mode_b"),
                           {"solution": "print(1)", **expl}, "explanation")
        make_run(expl_ok, model, pa, "explanation", src4, passed=0, mode="mode_a")   # pad bez predloga
        code, out = run_tool(expl_ok)
        passes = [line_for(out, a).startswith("PASS") for a in (e1, e2, e3)]
        record("objasnjenja: ispravna serija -> 0, 3 x PASS (A, B MC, B kod)", (0, [True] * 3), (code, passes),
               code == 0 and all(passes) and "predlozi objašnjenja: 3  PASS: 3  FAIL: 0" in out)
        record("objasnjenja: run bez predloga nije FAIL", "pomenut u rezimeu, bez FAIL run",
               "da" if "run-ova bez predloga" in out else "ne", "run-ova bez predloga" in out and "FAIL  run" not in out)

        expl_bad = make_batch("expl-bad")
        f1 = make_artifact(make_run(expl_bad, model, pa, "explanation", src4, mode="mode_a"),
                           {"solution": "x", **expl}, "explanation")                       # A ne sme da vrati solution
        f2 = make_artifact(make_run(expl_bad, model, pb_mc, "explanation", src4, mode="mode_b"), expl, "explanation")
        f3 = make_artifact(make_run(expl_bad, model, pb, "explanation", src_open, mode="mode_b"), "nije json", "explanation")
        r_expl_incons = make_run(expl_bad, model, pa, "explanation", src4, passed=0, mode="mode_a")
        f4 = make_artifact(r_expl_incons, expl, "explanation")                              # predlog uz neuspeo run
        r_expl_two = make_run(expl_bad, model, pa, "explanation", src4, mode="mode_a")
        f5, f6 = make_artifact(r_expl_two, expl, "explanation"), make_artifact(r_expl_two, expl, "explanation")
        code, out = run_tool(expl_bad)
        expect = {f1: "FAIL", f2: "FAIL", f3: "FAIL", f4: "PASS", f5: "PASS", f6: "PASS"}
        got = {a: line_for(out, a)[:4].strip() for a in expect}
        record("objasnjenja: serija sa greskama -> 1, ishod po predlogu", (1, list(expect.values())),
               (code, list(got.values())), code == 1 and got == expect)
        record("objasnjenja: razlozi (sema A, B MC, JSON)", "solution / selected_option / nije validan JSON",
               [line_for(out, a)[-40:] for a in (f1, f2, f3)],
               "ne sme da vraca solution" in line_for(out, f1) and "selected_option" in line_for(out, f2)
               and "nije validan JSON" in line_for(out, f3))
        record("objasnjenja: doslednost - predlog uz validation_passed = 0", f"FAIL run #{r_expl_incons}",
               "da" if f"run #{r_expl_incons} " in out else "ne",
               any(l.startswith(f"FAIL  run #{r_expl_incons}") and "validation_passed = 0" in l for l in out.splitlines()))
        record("objasnjenja: doslednost - run sa 2 predloga", f"FAIL run #{r_expl_two}",
               "da" if f"run #{r_expl_two} " in out else "ne",
               any(l.startswith(f"FAIL  run #{r_expl_two}") and "ima 2 predloga" in l for l in out.splitlines()))
        record("objasnjenja: rezime i rezim u redu predloga", "predlozi objašnjenja: 6  PASS: 3  FAIL: 3, mode_a",
               "da" if "predlozi objašnjenja: 6  PASS: 3  FAIL: 3" in out else "ne",
               "predlozi objašnjenja: 6  PASS: 3  FAIL: 3" in out and "mode_a" in line_for(out, f1))

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
