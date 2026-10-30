"""Uvoz skupa pitanja iz JSON fajla u banku pitanja (exam_id NULL).

    python tools/import_question_set.py <fajl.json> [--apply]

(iz foldera backend/). Podrazumevano je PROBNI rad: proverava fajl, izvršava
reference_solution programskih pitanja nad njihovim test primerima i ispisuje
šta bi se napravilo, bez ikakvog upisa. Upis tek uz --apply, u jednoj
transakciji (sve ili ništa).

Oblik fajla (primer: tools/question_set_example.json):
  {
    "subject": {"name": "...", "code": "..."},
    "areas": ["Oblast 1", ...],
    "questions": [
      {"key": "q1", "area": "Oblast 1", "question_text": "...",
       "difficulty": "lako|srednje|tesko", "bloom_level": "...", "points": 1,
       # tačno jedno od sledećeg (ili nijedno = otvoreno pitanje bez koda):
       "answers": [{"answer_text": "...", "is_correct": true}, ...],
       "reference_solution": "...", "test_cases": [{"input_data": "...", "expected_output": "..."}]}
    ],
    "reference_set": {"name": "...", "questions": ["q1", ...]}   # opciono, po "key"
  }

Pravila:
  - predmet se traži po kodu; ako ne postoji, pravi se (kod i naziv ne smeju
    da pripadaju različitim postojećim predmetima);
  - oblasti se traže po imenu u predmetu i prave ako ne postoje;
  - pitanje sa istim tekstom u istom predmetu se preskače (idempotentno);
    u referentnom skupu se tada koristi postojeće pitanje;
  - referentni skup sa istim imenom se preskače;
  - programsko pitanje: reference_solution se pokreće nad svim test primerima
    (code_executor.run_against_test_cases, isto kao mehanička provera
    objašnjenja); ako bilo koji primer padne, uvoz se prekida.
Izlazni kod: 0 = u redu, 1 = greška u fajlu / provera rešenja pala / greška pri upisu.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import code_executor  # noqa: E402
import question_validation  # noqa: E402
from app import get_db_connection  # noqa: E402

SUBJECT_CODE_MAX = 10
SUBJECT_NAME_MAX = 80
AREA_NAME_MAX = 150
SET_NAME_MAX = 150


class UvozGreska(Exception):
    """Greška zbog koje se uvoz prekida (poruke su u .errors)."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _text(value):
    return value.strip() if isinstance(value, str) else None


def question_kind(question):
    if question.get("answers") is not None:
        return "mc"
    if question.get("reference_solution") is not None or question.get("test_cases") is not None:
        return "programsko"
    return "otvoreno"


def validate(data):
    """Lista grešaka u strukturi fajla (prazna = u redu). Bez baze."""
    errors = []
    if not isinstance(data, dict):
        return ["Fajl mora biti JSON objekat"]

    subject = data.get("subject")
    if not isinstance(subject, dict):
        errors.append("subject je obavezan objekat sa name i code")
    else:
        name, code = _text(subject.get("name")), _text(subject.get("code"))
        if not name or len(name) > SUBJECT_NAME_MAX:
            errors.append(f"subject.name je obavezan (najviše {SUBJECT_NAME_MAX} znakova)")
        if not code or len(code) > SUBJECT_CODE_MAX:
            errors.append(f"subject.code je obavezan (najviše {SUBJECT_CODE_MAX} znakova)")

    areas = data.get("areas")
    if (not isinstance(areas, list) or not areas
            or any(not _text(a) or len(_text(a)) > AREA_NAME_MAX for a in areas)):
        errors.append(f"areas mora biti neprazan niz imena (najviše {AREA_NAME_MAX} znakova)")
        area_names = set()
    else:
        area_names = {_text(a) for a in areas}
        if len(area_names) != len(areas):
            errors.append("areas: imena oblasti se ponavljaju")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("questions mora biti neprazan niz")
        questions = []

    keys, texts = set(), set()
    for i, q in enumerate(questions, start=1):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            errors.append(f"{where}: mora biti objekat")
            continue
        key = q.get("key")
        if key is not None:
            if not _text(key):
                errors.append(f"{where}: key mora biti neprazan string")
            elif key in keys:
                errors.append(f"{where}: key '{key}' se ponavlja")
            else:
                keys.add(key)
        text = _text(q.get("question_text"))
        if not text:
            errors.append(f"{where}: question_text je obavezan")
        elif text in texts:
            errors.append(f"{where}: isti question_text se ponavlja u fajlu")
        else:
            texts.add(text)
        if _text(q.get("area")) not in area_names:
            errors.append(f"{where}: area mora biti jedna od oblasti iz areas")
        error = question_validation.label_error("difficulty", q.get("difficulty"))
        if error:
            errors.append(f"{where}: {error}")
        if q.get("bloom_level") is not None:
            error = question_validation.label_error("bloom_level", q.get("bloom_level"))
            if error:
                errors.append(f"{where}: {error}")
        points = q.get("points", 1)
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            errors.append(f"{where}: points mora biti pozitivan ceo broj")

        has_answers = q.get("answers") is not None
        has_code = q.get("reference_solution") is not None or q.get("test_cases") is not None
        if has_answers and has_code:
            errors.append(f"{where}: pitanje ima ili answers (MC) ili reference_solution + test_cases, ne oba")
        elif has_answers:
            answers = q["answers"]
            if (not isinstance(answers, list) or len(answers) < 2
                    or any(not isinstance(a, dict) or not _text(a.get("answer_text"))
                           or not isinstance(a.get("is_correct"), bool) for a in answers)):
                errors.append(f"{where}: answers mora imati bar 2 odgovora sa answer_text i is_correct (true/false)")
            elif not any(a["is_correct"] for a in answers):
                errors.append(f"{where}: bar jedan odgovor mora biti tačan")
        elif has_code:
            if not _text(q.get("reference_solution")):
                errors.append(f"{where}: reference_solution je obavezan uz test_cases")
            cases = q.get("test_cases")
            if (not isinstance(cases, list) or not cases
                    or any(not isinstance(c, dict) or not isinstance(c.get("expected_output"), str)
                           or not isinstance(c.get("input_data", ""), str) for c in cases)):
                errors.append(f"{where}: test_cases mora biti neprazan niz sa input_data i expected_output (stringovi)")

    ref = data.get("reference_set")
    if ref is not None:
        if not isinstance(ref, dict) or not _text(ref.get("name")) or len(_text(ref["name"])) > SET_NAME_MAX:
            errors.append(f"reference_set.name je obavezan (najviše {SET_NAME_MAX} znakova)")
        else:
            ref_keys = ref.get("questions")
            if not isinstance(ref_keys, list) or not ref_keys:
                errors.append("reference_set.questions mora biti neprazan niz key vrednosti pitanja")
            else:
                unknown = [k for k in ref_keys if k not in keys]
                if unknown:
                    errors.append(f"reference_set.questions: nepoznati key: {unknown}")
                if len(set(map(str, ref_keys))) != len(ref_keys):
                    errors.append("reference_set.questions: pitanja se ponavljaju")
    return errors


def check_solutions(data):
    """Pokreće reference_solution nad test primerima svakog programskog pitanja.
    Vraća (izveštaj_redovi, greške)."""
    report, errors = [], []
    for i, q in enumerate(data["questions"], start=1):
        if question_kind(q) != "programsko":
            continue
        cases = [{"order_no": n, "input_data": c.get("input_data", ""), "expected_output": c["expected_output"]}
                 for n, c in enumerate(q["test_cases"])]
        check = code_executor.run_against_test_cases(q["reference_solution"], cases)
        passed = sum(r["passed"] for r in check["results"])
        report.append(f"questions[{i}]: reference_solution {passed}/{len(cases)} test primera")
        if not check["all_passed"]:
            for r in check["results"]:
                if not r["passed"]:
                    errors.append(
                        f"questions[{i}], test primer {r['order_no']}: očekivano {r['expected_output']!r}, "
                        f"dobijeno {r['actual_output']!r}" + (f" ({r['error']})" if r.get("error") else ""))
    return report, errors


def build_plan(cursor, data):
    """Šta postoji, a šta bi se napravilo. Samo čita bazu."""
    errors = []
    name, code = data["subject"]["name"].strip(), data["subject"]["code"].strip()
    cursor.execute("SELECT id, code, name FROM subjects WHERE code = %s OR name = %s", (code, name))
    rows = cursor.fetchall()
    subject_id = None
    for row in rows:
        if row["code"] == code and row["name"] != name:
            errors.append(f"Kod '{code}' već ima predmet '{row['name']}' (id {row['id']}), a ne '{name}'")
        elif row["name"] == name and row["code"] != code:
            errors.append(f"Predmet '{name}' već postoji sa kodom '{row['code']}' (id {row['id']}), a ne '{code}'")
        else:
            subject_id = row["id"]
    if errors:
        raise UvozGreska(errors)

    existing_areas, existing_questions = {}, {}
    if subject_id is not None:
        cursor.execute("SELECT id, name FROM areas WHERE subject_id = %s", (subject_id,))
        existing_areas = {row["name"]: row["id"] for row in cursor.fetchall()}
        cursor.execute("SELECT id, question_text FROM exam_questions WHERE subject_id = %s", (subject_id,))
        for row in cursor.fetchall():
            existing_questions.setdefault(row["question_text"].strip(), row["id"])

    areas = [{"name": a.strip(), "id": existing_areas.get(a.strip())} for a in data["areas"]]
    questions = []
    for i, q in enumerate(data["questions"], start=1):
        text = q["question_text"].strip()
        questions.append({"index": i, "data": q, "text": text, "kind": question_kind(q),
                          "existing_id": existing_questions.get(text)})

    ref_plan = None
    ref = data.get("reference_set")
    if ref is not None:
        cursor.execute("SELECT id, subject_id FROM reference_sets WHERE name = %s", (ref["name"].strip(),))
        row = cursor.fetchone()
        if row and row["subject_id"] != subject_id:
            raise UvozGreska([f"Referentni skup '{ref['name'].strip()}' već postoji u drugom predmetu (id {row['id']})"])
        ref_plan = {"name": ref["name"].strip(), "keys": ref["questions"], "existing_id": row["id"] if row else None}

    return {"subject": {"name": name, "code": code, "id": subject_id},
            "areas": areas, "questions": questions, "reference_set": ref_plan}


def print_plan(plan, out=print):
    s = plan["subject"]
    out(f"Predmet: {s['name']} ({s['code']}) - " + (f"postoji (id {s['id']})" if s["id"] else "NOV"))
    for a in plan["areas"]:
        out(f"  Oblast: {a['name']} - " + (f"postoji (id {a['id']})" if a["id"] else "NOVA"))
    for q in plan["questions"]:
        status = f"PRESKAČE SE, već postoji (id {q['existing_id']})" if q["existing_id"] else "NOVO"
        out(f"  Pitanje {q['index']} [{q['kind']}, {q['data']['area'].strip()}]: {q['text'][:70]} - {status}")
    r = plan["reference_set"]
    if r:
        out(f"Referentni skup: {r['name']} ({len(r['keys'])} pitanja) - "
            + (f"PRESKAČE SE, već postoji (id {r['existing_id']})" if r["existing_id"] else "NOV"))
    new_questions = sum(1 for q in plan["questions"] if not q["existing_id"])
    out(f"Ukupno novih pitanja: {new_questions}, preskočenih: {len(plan['questions']) - new_questions}")


def apply_plan(conn, plan):
    """Upisuje sve u jednoj transakciji. Vraća {"subject_id", "question_ids", "reference_set_id"}."""
    cursor = conn.cursor()
    try:
        s = plan["subject"]
        subject_id = s["id"]
        if subject_id is None:
            cursor.execute("INSERT INTO subjects (code, name) VALUES (%s, %s)", (s["code"], s["name"]))
            subject_id = cursor.lastrowid
        area_ids = {}
        for a in plan["areas"]:
            if a["id"] is None:
                cursor.execute("INSERT INTO areas (subject_id, name) VALUES (%s, %s)", (subject_id, a["name"]))
                area_ids[a["name"]] = cursor.lastrowid
            else:
                area_ids[a["name"]] = a["id"]

        ids_by_key, created = {}, []
        for q in plan["questions"]:
            d = q["data"]
            question_id = q["existing_id"]
            if question_id is None:
                cursor.execute("""
                    INSERT INTO exam_questions
                    (exam_id, subject_id, area_id, question_text, reference_solution, points, order_no,
                     difficulty, bloom_level)
                    VALUES (NULL, %s, %s, %s, %s, %s, 0, %s, %s)
                """, (subject_id, area_ids[d["area"].strip()], q["text"], d.get("reference_solution"),
                      d.get("points", 1), d["difficulty"], d.get("bloom_level")))
                question_id = cursor.lastrowid
                created.append(question_id)
                for a in d.get("answers") or []:
                    cursor.execute(
                        "INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)",
                        (question_id, a["answer_text"].strip(), 1 if a["is_correct"] else 0))
                for order_no, c in enumerate(d.get("test_cases") or []):
                    cursor.execute("""
                        INSERT INTO exam_question_test_cases (question_id, input_data, expected_output, order_no)
                        VALUES (%s, %s, %s, %s)
                    """, (question_id, c.get("input_data", ""), c["expected_output"], order_no))
            if d.get("key") is not None:
                ids_by_key[d["key"]] = question_id

        set_id = None
        r = plan["reference_set"]
        if r and r["existing_id"] is None:
            cursor.execute("INSERT INTO reference_sets (name, subject_id) VALUES (%s, %s)", (r["name"], subject_id))
            set_id = cursor.lastrowid
            for order_no, key in enumerate(r["keys"], start=1):
                cursor.execute("""
                    INSERT INTO reference_set_questions (reference_set_id, question_id, order_no)
                    VALUES (%s, %s, %s)
                """, (set_id, ids_by_key[key], order_no))
        conn.commit()
        return {"subject_id": subject_id, "question_ids": created, "reference_set_id": set_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def main(argv=None, out=print):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/import_question_set.py")
    parser.add_argument("file", help="JSON fajl sa skupom pitanja")
    parser.add_argument("--apply", action="store_true", help="stvarno upiši (bez ovoga samo probni rad)")
    args = parser.parse_args(argv)

    try:
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        out(f"GREŠKA: fajl se ne može pročitati kao JSON: {e}")
        return 1

    errors = validate(data)
    if errors:
        out("GREŠKA u fajlu, ništa nije upisano:")
        for e in errors:
            out(f"  - {e}")
        return 1

    report, errors = check_solutions(data)
    for line in report:
        out(line)
    if errors:
        out("GREŠKA: reference_solution ne prolazi test primere, uvoz je prekinut:")
        for e in errors:
            out(f"  - {e}")
        return 1

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        try:
            plan = build_plan(cursor, data)
        finally:
            cursor.close()
        out(f"Baza: {conn.database}")
        print_plan(plan, out)

        if not args.apply:
            out("\nPROBNI RAD: ništa nije upisano. Za upis dodajte --apply.")
            return 0

        out("\nPODSETNIK: pre upisa napravite backup baze van repozitorijuma, npr.")
        out(f"  mysqldump -uroot --routines --triggers {conn.database} > ../backup_pre_uvoz_pitanja.sql")
        result = apply_plan(conn, plan)
        out(f"UPISANO: predmet id {result['subject_id']}, novih pitanja {len(result['question_ids'])} "
            f"{result['question_ids']}" + (f", referentni skup id {result['reference_set_id']}"
                                            if result["reference_set_id"] else ""))
        return 0
    except UvozGreska as e:
        out("GREŠKA, ništa nije upisano:")
        for msg in e.errors:
            out(f"  - {msg}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
