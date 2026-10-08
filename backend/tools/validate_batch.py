"""Ponovna mehanička validacija (PASS/FAIL) svih sačuvanih predloga jedne serije.

    python tools/validate_batch.py --batch ID

(iz foldera backend/). Samo čita bazu (sesija je READ ONLY). Ne poziva modele.

Za svaki predlog pitanja (ai_generated_artifacts, artifact_type='question') iz
run-ova serije ponovo pušta isti validator kao pri generisanju, prema verziji
prompta run-a:
  - jedno pitanje (similar_question): question_validation.validate; tip iz
    verzije prompta (mc-* / open-*), očekivan broj odgovora = broj odgovora
    izvornog pitanja;
  - skup (similar_question_set): question_validation.validate_set_item za svaki
    predlog, a za run i validate_set nad celim odgovorom (broj prihvaćenih
    stavki mora biti jednak broju sačuvanih predloga).
Proverava se i doslednost: run sa predlogom mora imati validation_passed = 1.
Predlozi koji nisu pitanja (npr. objašnjenja) se preskaču i navode u rezimeu.
Model se ne ispisuje (alat ne sme da otkrije model tokom slepog ocenjivanja).

Izlazni kod: 0 = sve PASS, 1 = bar jedan FAIL, 2 = serija ne postoji,
3 = serija nema nijedan predlog pitanja.
"""
import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# app pre ostalih modula: app.py ucitava backend/.env
from app import get_db_connection  # noqa: E402
import prompt_templates  # noqa: E402
import question_validation  # noqa: E402

PURPOSE_SINGLE = prompt_templates.PURPOSE_SIMILAR_QUESTION
PURPOSE_SET = prompt_templates.PURPOSE_SIMILAR_QUESTION_SET


def _json(text):
    try:
        return json.loads(text) if text is not None else None
    except (ValueError, TypeError):
        return None


def question_type_for(prompt_version, source_answer_count):
    """Tip pitanja kao pri generisanju: iz verzije prompta, a za nepoznatu verziju iz izvora."""
    version = prompt_version or ""
    if version.startswith("mc-"):
        return "mc"
    if version.startswith("open-"):
        return "open"
    return "mc" if source_answer_count else "open"


def validate_artifact(row):
    """Jedan predlog -> (ishod 'PASS' | 'FAIL' | 'SKIP', [razlozi])."""
    if row["artifact_type"] != "question":
        return "SKIP", [f"tip predloga '{row['artifact_type']}' - nije pitanje"]
    parsed = _json(row["original_text"])
    if parsed is None:
        return "FAIL", ["original_text nije validan JSON"]
    version = row["prompt_version"]
    if row["purpose"] == PURPOSE_SINGLE:
        if row["source_answer_count"] is None:
            return "FAIL", ["izvorno pitanje više ne postoji - očekivan broj odgovora se ne može proveriti"]
        qtype = question_type_for(version, row["source_answer_count"])
        result = question_validation.validate(parsed, qtype, row["source_answer_count"], version)
        return ("PASS", []) if result.passed else ("FAIL", result.errors)
    if row["purpose"] == PURPOSE_SET:
        result = question_validation.validate_set_item(parsed, version)
        return ("PASS", []) if result.passed else ("FAIL", result.errors)
    return "SKIP", [f"namena run-a '{row['purpose']}' - nije generisanje pitanja"]


def validate_run(run, artifact_count):
    """Doslednost run-a sa sačuvanim predlozima -> lista grešaka (prazna = u redu)."""
    errors = []
    if artifact_count and run["validation_passed"] != 1:
        errors.append(f"run ima {artifact_count} predlog(a), a validation_passed = {run['validation_passed']}")
    if run["purpose"] == PURPOSE_SINGLE and artifact_count > 1:
        errors.append(f"run za jedno pitanje ima {artifact_count} predloga")
    if run["purpose"] == PURPOSE_SET and artifact_count:
        params = _json(run["params_used"]) or {}
        k = params.get("k")
        parsed = _json(run["parsed_result"])
        if not isinstance(k, int):
            errors.append("params_used nema K")
        elif parsed is None:
            errors.append("parsed_result nije sačuvan ili nije JSON")
        else:
            result = question_validation.validate_set(parsed, k, run["prompt_version"])
            if not result.passed:
                errors.append("ceo odgovor ne prolazi validate_set: " + "; ".join(result.errors))
            elif len(result.accepted) != artifact_count:
                errors.append(f"validate_set prihvata {len(result.accepted)} stavki, a sačuvano je {artifact_count} predloga")
    return errors


def load(batch_id):
    """-> (serija postoji, run-ovi, predlozi). Samo SELECT, u READ ONLY sesiji."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.execute("SELECT id FROM evaluation_batches WHERE id = %s", (batch_id,))
        if not cursor.fetchone():
            return False, [], []
        cursor.execute("""
            SELECT r.id, r.purpose, r.params_used, r.parsed_result, r.validation_passed, r.source_question_id,
                   p.version AS prompt_version
            FROM ai_generation_runs r LEFT JOIN ai_prompts p ON p.id = r.prompt_id
            WHERE r.evaluation_batch_id = %s ORDER BY r.id
        """, (batch_id,))
        runs = cursor.fetchall()
        cursor.execute("""
            SELECT a.id, a.artifact_type, a.status, a.original_text, r.id AS run_id, r.purpose,
                   p.version AS prompt_version, r.source_question_id,
                   (SELECT COUNT(*) FROM exam_answers ea WHERE ea.question_id = r.source_question_id) AS answers,
                   EXISTS (SELECT 1 FROM exam_questions q WHERE q.id = r.source_question_id) AS source_exists
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            LEFT JOIN ai_prompts p ON p.id = r.prompt_id
            WHERE r.evaluation_batch_id = %s ORDER BY a.id
        """, (batch_id,))
        artifacts = cursor.fetchall()
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    for a in artifacts:
        a["source_answer_count"] = int(a["answers"]) if a["source_exists"] else None
    return True, runs, artifacts


def validate_batch(batch_id, out=print):
    exists, runs, artifacts = load(batch_id)
    if not exists:
        out(f"Serija {batch_id} ne postoji.")
        return 2

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    per_run = {}
    out(f"Serija {batch_id}: {len(runs)} run-ova, {len(artifacts)} predloga\n")
    for a in artifacts:
        outcome, errors = validate_artifact(a)
        counts[outcome] += 1
        if a["artifact_type"] == "question":
            per_run[a["run_id"]] = per_run.get(a["run_id"], 0) + 1
        mode = {PURPOSE_SINGLE: "single", PURPOSE_SET: "set"}.get(a["purpose"], a["purpose"])
        line = f"{outcome:4}  predlog #{a['id']:<6} run #{a['run_id']:<6} {mode:<7} {a['prompt_version'] or '?':<8} {a['status']}"
        out(line + ("" if not errors else "  - " + "; ".join(errors)))

    run_failures = 0
    for run in runs:
        errors = validate_run(run, per_run.get(run["id"], 0))
        if errors:
            run_failures += 1
            out(f"FAIL  run #{run['id']:<6} (doslednost)  - " + "; ".join(errors))

    without_artifacts = sum(1 for run in runs if not per_run.get(run["id"]))
    questions = counts["PASS"] + counts["FAIL"]
    out("\nRezime:")
    out(f"  predlozi pitanja: {questions}  PASS: {counts['PASS']}  FAIL: {counts['FAIL']}")
    out(f"  run-ovi sa nedoslednošću: {run_failures}")
    if counts["SKIP"]:
        out(f"  preskočeno (nisu predlozi pitanja): {counts['SKIP']}")
    if without_artifacts:
        out(f"  run-ova bez predloga pitanja (pad ili objašnjenje): {without_artifacts} - nisu predlozi, ne validiraju se")
    if not questions:
        out("  Serija nema nijedan predlog pitanja - nema šta da se validira.")
        return 3
    ok = counts["FAIL"] == 0 and run_failures == 0
    out("  UKUPNO: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/validate_batch.py")
    parser.add_argument("--batch", type=int, required=True, help="id evaluacione serije")
    args = parser.parse_args(argv)
    return validate_batch(args.batch)


if __name__ == "__main__":
    sys.exit(main())
