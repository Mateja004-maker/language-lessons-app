"""
Privremena smoke-test skripta - proverava code_executor.py protiv PRAVIH
podataka iz baze (probni zadatak #60), ne samo hardkodovanih primera.
Samo čitanje iz baze. Za jednokratno ručno pokretanje, nije deo aplikacije.
"""

import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
import os

import code_executor

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

QUESTION_TEXT_PREFIX = "Napiši Python program koji sa standardnog ulaza učitava dva cela broja"


def main():
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE"),
    )
    cur = conn.cursor(dictionary=True)

    cur.execute(
        "SELECT id, question_text, reference_solution FROM exam_questions "
        "WHERE question_text LIKE %s LIMIT 1",
        (QUESTION_TEXT_PREFIX + "%",),
    )
    question = cur.fetchone()

    if question is None:
        print(f"FAIL - nije nadjeno pitanje cije question_text pocinje sa: {QUESTION_TEXT_PREFIX!r}")
        cur.close()
        conn.close()
        return

    question_id = question["id"]
    reference_solution = question["reference_solution"]

    if not reference_solution:
        print(f"FAIL - pitanje id={question_id} nema popunjen reference_solution")
        cur.close()
        conn.close()
        return

    cur.execute(
        "SELECT order_no, input_data, expected_output FROM exam_question_test_cases "
        "WHERE question_id = %s ORDER BY order_no",
        (question_id,),
    )
    test_cases = cur.fetchall()

    cur.close()
    conn.close()

    if not test_cases:
        print(f"FAIL - pitanje id={question_id} nema nijedan red u exam_question_test_cases")
        return

    print(f"Pitanje id={question_id}, {len(test_cases)} test primer(a) ucitano iz baze.")

    outcome = code_executor.run_against_test_cases(reference_solution, test_cases)

    if outcome["all_passed"]:
        print("PASS - referentno resenje prolazi sve test primere")
    else:
        print("FAIL - referentno resenje NE prolazi sve test primere:")
        for r in outcome["results"]:
            if not r["passed"]:
                print(f"  - order_no={r['order_no']} input={r['input_data']!r} "
                      f"expected={r['expected_output']!r} actual={r['actual_output']!r} "
                      f"error={r['error']!r} timed_out={r['timed_out']}")


if __name__ == "__main__":
    main()
