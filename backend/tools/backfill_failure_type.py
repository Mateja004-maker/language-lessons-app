"""Jednokratna dopuna vrste pada za stare run-ove generisanja pitanja (tačka I).

    python tools/backfill_failure_type.py [--dry-run]

(iz foldera backend/). Za run-ove generisanja sličnih pitanja kojima
first_attempt_passed još nije upisan izvodi iz sačuvanih podataka:
  failure_type          iz validation_passed, raw_response i validation_errors
                        (generation_failures.classify_stored_run)
  format_retries        1 ako params_used ima first_attempt, inače 0
  first_attempt_passed  0 ako je bilo ponavljanja, inače validation_passed
i upisuje SAMO ta tri polja (samo gde je first_attempt_passed NULL). Run-ovi
objašnjenja se ne diraju. --dry-run samo ispisuje (radi i pre migracije
db/migration_failure_type_retry.sql).
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generation_failures  # noqa: E402
import prompt_templates  # noqa: E402
from app import FAILURE_COLUMNS, get_db_connection, table_columns_exist  # noqa: E402


def derive(row):
    try:
        params = json.loads(row["params_used"]) if row["params_used"] else {}
    except ValueError:
        params = {}
    retried = isinstance(params, dict) and bool(params.get("first_attempt"))
    return {
        "failure_type": generation_failures.classify_stored_run(
            row["validation_passed"], row["raw_response"], row["validation_errors"]),
        "format_retries": 1 if retried else 0,
        "first_attempt_passed": 0 if retried else (1 if row["validation_passed"] else 0),
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/backfill_failure_type.py")
    parser.add_argument("--dry-run", action="store_true", help="samo ispiši, bez upisa")
    args = parser.parse_args(argv)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        enabled = table_columns_exist(cursor, "ai_generation_runs", FAILURE_COLUMNS)
        if not enabled and not args.dry_run:
            print("GREŠKA: kolone ne postoje - pokrenite db/migration_failure_type_retry.sql (ili koristite --dry-run)")
            return 2

        pending = "AND first_attempt_passed IS NULL" if enabled else ""
        cursor.execute(f"""
            SELECT id, validation_passed, raw_response, validation_errors, params_used
            FROM ai_generation_runs
            WHERE purpose = %s {pending}
            ORDER BY id
        """, (prompt_templates.PURPOSE_SIMILAR_QUESTION,))
        rows = cursor.fetchall()

        kinds = Counter()
        updated = 0
        for row in rows:
            values = derive(row)
            kinds[values["failure_type"] or "uspeh"] += 1
            reason = " ".join((row["validation_errors"] or "").split())[:70]
            print(f"run #{row['id']}: {values['failure_type'] or 'uspeh':12} prvi prošao={values['first_attempt_passed']} "
                  f"ponavljanja={values['format_retries']}" + (f"  ({reason})" if reason else ""))
            if enabled and not args.dry_run:
                cursor.execute("""
                    UPDATE ai_generation_runs
                    SET failure_type = %s, first_attempt_passed = %s, format_retries = %s
                    WHERE id = %s AND first_attempt_passed IS NULL
                """, (values["failure_type"], values["first_attempt_passed"], values["format_retries"], row["id"]))
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
