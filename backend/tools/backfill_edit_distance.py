"""Jednokratna dopuna razdaljine izmene za već izmenjene predloge (tačka B).

    python tools/backfill_edit_distance.py [--dry-run]

(iz foldera backend/). Za svaki AI predlog pitanja sa odlukom
'prihvaceno_izmena' računa edit_distance / edit_distance_norm iz original_text
i edited_text (backend/edit_distance.py) i upisuje ih SAMO tamo gde su NULL;
ništa drugo se ne menja. --dry-run samo ispisuje vrednosti (radi i pre
migracije db/migration_edit_distance.sql).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit_distance  # noqa: E402
from app import EDIT_DISTANCE_COLUMNS, get_db_connection, table_columns_exist  # noqa: E402


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/backfill_edit_distance.py")
    parser.add_argument("--dry-run", action="store_true", help="samo ispiši, bez upisa")
    args = parser.parse_args(argv)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        enabled = table_columns_exist(cursor, "ai_generated_artifacts", EDIT_DISTANCE_COLUMNS)
        if not enabled and not args.dry_run:
            print("GREŠKA: kolone ne postoje - pokrenite db/migration_edit_distance.sql (ili koristite --dry-run)")
            return 2

        current = "edit_distance, edit_distance_norm" if enabled else "NULL AS edit_distance, NULL AS edit_distance_norm"
        cursor.execute(f"""
            SELECT id, original_text, edited_text, {current}
            FROM ai_generated_artifacts
            WHERE artifact_type = 'question' AND status = 'prihvaceno_izmena' AND edited_text IS NOT NULL
            ORDER BY id
        """)
        rows = cursor.fetchall()
        updated = 0
        for row in rows:
            distance = edit_distance.edit_distance(json.loads(row["original_text"]), json.loads(row["edited_text"]))
            already = row["edit_distance"] is not None
            print(f"predlog #{row['id']}: pitanje {distance['question']}, odgovori {distance['answers']}, "
                  f"ukupno {distance['total']}, normalizovano {distance['normalized']}"
                  + ("  (već upisano, ne menja se)" if already else ""))
            if enabled and not already and not args.dry_run:
                cursor.execute("""
                    UPDATE ai_generated_artifacts SET edit_distance = %s, edit_distance_norm = %s
                    WHERE id = %s AND edit_distance IS NULL
                """, (distance["total"], distance["normalized"], row["id"]))
                updated += cursor.rowcount
        if not args.dry_run:
            conn.commit()
        print(f"Izmenjenih predloga: {len(rows)}; upisano: {updated}" + (" (--dry-run, bez upisa)" if args.dry_run else ""))
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
