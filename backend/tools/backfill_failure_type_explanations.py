"""Jednokratna dopuna vrste pada za stare run-ove OBJASNJENJA (Andrejev modul).

    python tools/backfill_failure_type_explanations.py [--dry-run]

(iz foldera backend/). Za run-ove objasnjenja (purpose='explanation') kojima
first_attempt_passed jos nije upisan izvodi failure_type istom logikom kao
generate_explanation u app.py:
  uspeh (validation_passed = 1)        -> NULL
  model nije odgovorio (raw_response NULL) -> generation_failures.classify_provider_error
  odgovor nije JSON (parsed_result NULL)   -> invalid_json
  JSON ne prolazi validaciju               -> schema
first_attempt_passed = 1 samo za uspeh; format_retries = 0 (objasnjenja nemaju
ponovni zahtev posle loseg formata). Upisuje SAMO ta tri polja. Run-ovi pitanja
se ne diraju (za njih je tools/backfill_failure_type.py). --dry-run samo ispisuje.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import explanation_prompts  # noqa: E402
import generation_failures  # noqa: E402
from app import FAILURE_COLUMNS, get_db_connection, table_columns_exist  # noqa: E402


def derive(row):
    if row["validation_passed"]:
        failure_type = None
    elif row["raw_response"] is None:
        failure_type = generation_failures.classify_provider_error(row["validation_errors"])
    elif row["parsed_result"] is None:
        failure_type = "invalid_json"
    else:
        failure_type = "schema"
    return {
        "failure_type": failure_type,
        "first_attempt_passed": 1 if failure_type is None else 0,
        "format_retries": 0,
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/backfill_failure_type_explanations.py")
    parser.add_argument("--dry-run", action="store_true", help="samo ispiši, bez upisa")
    args = parser.parse_args(argv)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not table_columns_exist(cursor, "ai_generation_runs", FAILURE_COLUMNS):
            print("GREŠKA: kolone ne postoje - pokrenite db/migration_failure_type_retry.sql")
            return 2

        cursor.execute("""
            SELECT id, mode, validation_passed, raw_response, parsed_result, validation_errors
            FROM ai_generation_runs
            WHERE purpose = %s AND first_attempt_passed IS NULL
            ORDER BY id
        """, (explanation_prompts.PURPOSE_EXPLANATION,))
        rows = cursor.fetchall()

        kinds = Counter()
        updated = 0
        for row in rows:
            values = derive(row)
            kinds[values["failure_type"] or "uspeh"] += 1
            reason = " ".join((row["validation_errors"] or "").split())[:60]
            print(f"run #{row['id']} {row['mode']}: {values['failure_type'] or 'uspeh':12} "
                  f"prvi prošao={values['first_attempt_passed']} ponavljanja={values['format_retries']}"
                  + (f"  ({reason})" if reason else ""))
            if not args.dry_run:
                cursor.execute("""
                    UPDATE ai_generation_runs
                    SET failure_type = %s, first_attempt_passed = %s, format_retries = %s
                    WHERE id = %s AND purpose = %s AND first_attempt_passed IS NULL
                """, (values["failure_type"], values["first_attempt_passed"], values["format_retries"],
                      row["id"], explanation_prompts.PURPOSE_EXPLANATION))
                updated += cursor.rowcount
        if not args.dry_run:
            conn.commit()

        print(f"\nRun-ova: {len(rows)}; po vrsti: {dict(kinds.most_common())}")
        print(f"Upisano: {updated}" + (" (--dry-run, bez upisa)" if args.dry_run else ""))
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
