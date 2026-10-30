"""Provera alata tools/import_question_set.py: probni rad, upis, idempotentnost,
prekid kad reference_solution ne prolazi test primere i greške u fajlu.

Pokretanje (iz foldera backend/), samo nad probnom bazom:
    python tools/test_clean_db.py --only verify_import_question_set

Test upisuje pomoću --apply, pa radi SAMO nad bazom čije ime završava na
"_test"; nad bazom iz .env se preskače. Pravi privremen predmet (oznaka
tmp-imp-*), sve briše na kraju i poredi broj redova pre i posle. Alat se
zove u istom procesu (main), bez novog Python procesa.
"""
import copy
import json
import os
import sys
import tempfile
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

from app import get_db_connection  # noqa: E402
import import_question_set  # noqa: E402

TAG = uuid.uuid4().hex[:5]
NAME = f"tmp-imp-{TAG}"
CODE = f"i{TAG}"
COUNTED = ("subjects", "areas", "exam_questions", "exam_answers", "exam_question_test_cases",
           "reference_sets", "reference_set_questions")
EXAMPLE = os.path.join(BACKEND, "tools", "question_set_example.json")
results = []
tmpdir = tempfile.mkdtemp(prefix="uvoz-")


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
    finally:
        cur.close()
        conn.close()


def counts():
    return {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in COUNTED}


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def run(data, *flags):
    path = os.path.join(tmpdir, f"{uuid.uuid4().hex[:6]}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    lines = []
    rc = import_question_set.main([path, *flags], out=lines.append)
    return rc, "\n".join(lines)


def base_data():
    with open(EXAMPLE, encoding="utf-8") as f:
        data = json.load(f)
    data["subject"] = {"name": NAME, "code": CODE}
    data["reference_set"]["name"] = f"{NAME} skup"
    for q in data["questions"]:
        q["question_text"] = f"[{TAG}] {q['question_text']}"
    return data


def subject_id():
    rows = db_all("SELECT id FROM subjects WHERE code = %s", (CODE,))
    return rows[0]["id"] if rows else None


def cleanup():
    sid = subject_id()
    other = db_all("SELECT id FROM subjects WHERE code = %s", (f"j{TAG}",))
    for s in ([sid] if sid else []) + [r["id"] for r in other]:
        db_exec("DELETE FROM reference_sets WHERE subject_id = %s", (s,))
        db_exec("""DELETE t FROM exam_question_test_cases t JOIN exam_questions q ON q.id = t.question_id
                   WHERE q.subject_id = %s""", (s,))
        db_exec("DELETE FROM exam_questions WHERE subject_id = %s", (s,))
        db_exec("DELETE FROM areas WHERE subject_id = %s", (s,))
        db_exec("DELETE FROM subjects WHERE id = %s", (s,))


def main():
    database = db_all("SELECT DATABASE() AS db")[0]["db"]
    if not database.endswith("_test"):
        print(f"PRESKOCENO: test upisuje kroz --apply i radi samo nad probnom bazom (*_test), a ne nad {database!r}.")
        print("Pokrenite: python tools/test_clean_db.py --only verify_import_question_set")
        return 0

    before = counts()
    try:
        data = base_data()

        rc, out = run(data)
        record("probni rad: rc 0, ništa upisano", "0, isti brojevi", rc,
               rc == 0 and counts() == before and "PROBNI RAD" in out and subject_id() is None)

        rc, out = run(data, "--apply")
        sid = subject_id()
        record("--apply: rc 0, napravljen predmet", "0, predmet postoji", (rc, sid), rc == 0 and sid is not None)
        after = counts()
        delta = {t: after[t] - before[t] for t in COUNTED}
        expected = {"subjects": 1, "areas": 2, "exam_questions": 3, "exam_answers": 4,
                    "exam_question_test_cases": 3, "reference_sets": 1, "reference_set_questions": 3}
        record("--apply: broj novih redova po tabeli", expected, delta, delta == expected)

        rows = db_all("""SELECT q.id, q.exam_id, q.difficulty, q.bloom_level, q.reference_solution, a.name AS area
                         FROM exam_questions q JOIN areas a ON a.id = q.area_id
                         WHERE q.subject_id = %s ORDER BY q.id""", (sid,))
        record("pitanja u banci (exam_id NULL), oznake i oblasti kao u fajlu",
               "3 reda, exam_id NULL",
               [(r["exam_id"], r["difficulty"], r["bloom_level"], r["area"]) for r in rows],
               len(rows) == 3 and all(r["exam_id"] is None for r in rows)
               and [r["difficulty"] for r in rows] == [q["difficulty"] for q in data["questions"]]
               and [r["area"] for r in rows] == [q["area"] for q in data["questions"]])
        prog = rows[2]["id"]
        cases = db_all("""SELECT order_no, input_data, expected_output FROM exam_question_test_cases
                          WHERE question_id = %s ORDER BY order_no""", (prog,))
        record("programsko pitanje: reference_solution i test primeri redom",
               "3 primera, 0..2", [(c["order_no"], c["expected_output"]) for c in cases],
               rows[2]["reference_solution"] == data["questions"][2]["reference_solution"]
               and [(c["order_no"], c["input_data"], c["expected_output"]) for c in cases]
               == [(i, c["input_data"], c["expected_output"]) for i, c in enumerate(data["questions"][2]["test_cases"])])
        correct = db_all("SELECT answer_text FROM exam_answers WHERE question_id = %s AND is_correct = 1", (rows[0]["id"],))
        record("MC: tačan odgovor", "<h1>", [r["answer_text"] for r in correct],
               [r["answer_text"] for r in correct] == ["<h1>"])
        ref = db_all("""SELECT rsq.question_id FROM reference_sets s
                        JOIN reference_set_questions rsq ON rsq.reference_set_id = s.id
                        WHERE s.name = %s ORDER BY rsq.order_no""", (f"{NAME} skup",))
        record("referentni skup: pitanja redom", [r["id"] for r in rows], [r["question_id"] for r in ref],
               [r["question_id"] for r in ref] == [r["id"] for r in rows])

        snapshot = counts()
        rc, out = run(data, "--apply")
        record("ponovni --apply: sve preskočeno, ništa novo", "0, isti brojevi", (rc, out.count("PRESKAČE SE")),
               rc == 0 and counts() == snapshot and out.count("PRESKAČE SE") == 4)

        extra = copy.deepcopy(data)
        extra["questions"].append({"key": "novo", "area": "HTML i CSS", "question_text": f"[{TAG}] Novo pitanje?",
                                   "difficulty": "tesko"})
        extra["reference_set"]["name"] = f"{NAME} skup 2"
        extra["reference_set"]["questions"] = ["html-naslov", "novo"]
        rc, out = run(extra, "--apply")
        ref2 = db_all("""SELECT rsq.question_id FROM reference_sets s
                         JOIN reference_set_questions rsq ON rsq.reference_set_id = s.id
                         WHERE s.name = %s ORDER BY rsq.order_no""", (f"{NAME} skup 2",))
        new_id = db_all("SELECT id FROM exam_questions WHERE question_text = %s", (f"[{TAG}] Novo pitanje?",))
        record("delimično novo: samo novo pitanje, skup koristi i postojeće",
               "1 novo, skup [MC, novo]", (rc, [r["question_id"] for r in ref2]),
               rc == 0 and counts()["exam_questions"] == snapshot["exam_questions"] + 1 and new_id
               and [r["question_id"] for r in ref2] == [rows[0]["id"], new_id[0]["id"]])

        snapshot = counts()
        bad = base_data()
        bad["subject"] = {"name": f"{NAME}-2", "code": f"j{TAG}"}
        bad["questions"][2]["test_cases"][1]["expected_output"] = "99"
        rc, out = run(bad, "--apply")
        record("rešenje ne prolazi test primer: prekid, ništa upisano", "1, isti brojevi",
               (rc, "uvoz je prekinut" in out), rc == 1 and counts() == snapshot and "test primer 1" in out)

        bad = base_data()
        bad["questions"][0]["difficulty"] = "veoma tesko"
        bad["questions"][1]["area"] = "Nepostojeca oblast"
        bad["questions"][0]["answers"] = [{"answer_text": "a", "is_correct": False},
                                          {"answer_text": "b", "is_correct": False}]
        rc, out = run(bad, "--apply")
        record("greške u fajlu: sve prijavljene, ništa upisano", "1, 3 greške", (rc, out.count("  - ")),
               rc == 1 and counts() == snapshot and out.count("  - ") == 3)

        conflict = base_data()
        conflict["subject"]["name"] = f"{NAME}-drugo-ime"
        rc, out = run(conflict, "--apply")
        record("kod predmeta zauzet drugim imenom: odbijeno", "1", (rc, "već ima predmet" in out),
               rc == 1 and counts() == snapshot and "već ima predmet" in out)
    finally:
        cleanup()
    after = counts()
    record("brojevi redova pre = posle", before, after, before == after)

    width = max(len(r[0]) for r in results)
    for case, expected, got, status in results:
        print(f"{status:4}  {case:<{width}}  ocekivano: {expected}  dobijeno: {got}")
    failed = sum(r[3] == "PALO" for r in results)
    print(f"\n{len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
