"""Ponovni izračun mogućih duplikata za AI predloge pitanja (tačka C).

    python tools/recompute_similarity.py [--dry-run] [--artifact ID]

(iz foldera backend/). Za svaki AI predlog pitanja (ili samo --artifact ID)
računa najsličnije pitanje/predlog istom logikom kao pri generisanju
(app.compute_artifact_similarity) i upisuje SAMO max_similarity,
similar_source, similar_question_id i similar_artifact_id; nastavnikova
potvrda (reviewed_duplicate) i sve ostalo ostaju netaknuti.
--dry-run samo ispisuje rezultat i raspodelu (radi i pre migracije
db/migration_duplicate_check.sql).
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import question_similarity  # noqa: E402
from app import (  # noqa: E402
    compute_artifact_similarity,
    duplicate_check_enabled,
    get_db_connection,
    store_artifact_similarity,
)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/recompute_similarity.py")
    parser.add_argument("--dry-run", action="store_true", help="samo ispiši, bez upisa")
    parser.add_argument("--artifact", type=int, help="samo ovaj predlog")
    args = parser.parse_args(argv)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not args.dry_run and not duplicate_check_enabled(cursor):
            print("GREŠKA: kolone ne postoje - pokrenite db/migration_duplicate_check.sql (ili koristite --dry-run)")
            return 2

        if args.artifact is not None:
            cursor.execute("SELECT id FROM ai_generated_artifacts WHERE id = %s AND artifact_type = 'question'", (args.artifact,))
        else:
            cursor.execute("SELECT id FROM ai_generated_artifacts WHERE artifact_type = 'question' ORDER BY id")
        ids = [row["id"] for row in cursor.fetchall()]
        if not ids:
            print("Nema AI predloga pitanja za obradu.")
            return 1

        scores = []
        for artifact_id in ids:
            best = (compute_artifact_similarity(cursor, artifact_id) if args.dry_run
                    else store_artifact_similarity(cursor, artifact_id))
            if best is None:
                print(f"predlog #{artifact_id}: nema sa čim da se poredi")
                continue
            scores.append(best["score"])
            flag = "  <- mogući duplikat" if question_similarity.is_possible_duplicate(best["score"]) else ""
            print(f"predlog #{artifact_id}: {best['score']:.3f} sa {best['source']} #{best['id']}{flag}")
        if not args.dry_run:
            conn.commit()

        print(f"\nObrađeno: {len(ids)}" + (" (--dry-run, bez upisa)" if args.dry_run else "; upisano"))
        buckets = Counter(min(int(s * 10) / 10, 0.9) for s in scores)
        for bucket in sorted(buckets):
            print(f"  {bucket:.1f}-{bucket + 0.1:.1f}: {'#' * buckets[bucket]} {buckets[bucket]}")
        threshold = question_similarity.DUPLICATE_THRESHOLD
        print(f"Prag {threshold}: mogućih duplikata {sum(question_similarity.is_possible_duplicate(s) for s in scores)} od {len(scores)}")
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
