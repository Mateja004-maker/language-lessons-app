"""Pokretač eksperimenta generisanja sličnih pitanja (tačka D).

    python tools/run_experiment.py --batch ID --models groq,gemini,openrouter --per-question N
        [--reference-set ID] [--max-calls K] [--dry-run]

(iz foldera backend/). Za svako pitanje referentnog skupa serije, za svaki
model i za svaki od N pokušaja poziva istu logiku kao ruta
POST /api/questions/<id>/generate-similar (generate_similar_for_question):
ista validacija, isto beleženje, isto slepo ocenjivanje i isti ponovni
pokušaji provajdera; svaki run dobija evaluation_batch_id serije.

Redosled je uvek isti i naizmeničan po modelima:
    pokušaj 1: pitanje 1 -> model A, B, C; pitanje 2 -> A, B, C; ...
    pokušaj 2: ...

Nastavak bez dupliranja: stanje se ne čuva posebno, već se računa iz
ai_generation_runs serije. Mesto (pitanje, model, pokušaj k) je urađeno kada
serija za to pitanje i model ima bar k run-ova u kojima je model ODGOVORIO
(stiglo je telo odgovora: raw_response ili finish_reason). I odgovor u
neispravnom formatu je rezultat eksperimenta i ne ponavlja se. Infrastrukturni
padovi (mreža, HTTP greška, 429) ostaju zabeleženi kao run-ovi, ali se mesto
ponavlja pri sledećem pokretanju. 429 posle svih ponovnih pokušaja provajdera
(dnevni limit) zaustavlja taj model do sledećeg pokretanja; ostali nastavljaju.

Zaštita protokola: ako serija već ima run-ove sa drugim modelom za istog
provajdera ili sa drugom verzijom prompta od trenutno aktivne, pokretač
odbija da nastavi (mešanje bi pokvarilo poređenje).

--dry-run ispisuje plan (urađeno / čeka) bez poziva modela i bez upisa.
--max-calls K zaustavlja posle K poziva modela (kontrolisana potrošnja limita).
--reference-set ID vezuje skup za seriju koja još nema skup ni run-ove.
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import ai_provider  # noqa: E402
import prompt_templates  # noqa: E402
from app import (  # noqa: E402
    generate_similar_for_question,
    get_db_connection,
    reference_sets_enabled,
)

INFRA_STOP_AFTER = 3  # uzastopnih infrastrukturnih padova istog modela -> stani sa tim modelom


class ExperimentError(Exception):
    """Greška u podešavanju ili protokolu - ništa se ne poziva."""


# ---------- plan ----------

def build_plan(question_ids, providers, per_question):
    """Pun plan eksperimenta, istim redosledom za sve modele (naizmenično)."""
    return [
        (attempt, question_id, provider)
        for attempt in range(1, per_question + 1)
        for question_id in question_ids
        for provider in providers
    ]


def _query(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def answered_counts(batch_id):
    """{(question_id, provider): broj run-ova serije u kojima je model odgovorio}."""
    rows = _query("""
        SELECT r.source_question_id AS question_id, m.provider, COUNT(*) AS n
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s
          AND r.purpose = %s
          AND (r.raw_response IS NOT NULL
               OR JSON_VALUE(r.params_used, '$.finish_reason') IS NOT NULL)
        GROUP BY r.source_question_id, m.provider
    """, (batch_id, prompt_templates.PURPOSE_SIMILAR_QUESTION))
    return {(row["question_id"], row["provider"]): row["n"] for row in rows}


def check_protocol(batch_id, providers):
    """Serija ne sme da meša modele ni verzije prompta."""
    active_versions = {prompt_templates._read_template_file(t)[0] for t in ("mc", "open")}
    rows = _query("""
        SELECT DISTINCT m.provider, m.model_name, p.version
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        JOIN ai_prompts p ON p.id = r.prompt_id
        WHERE r.evaluation_batch_id = %s AND r.purpose = %s
    """, (batch_id, prompt_templates.PURPOSE_SIMILAR_QUESTION))
    problems = []
    for row in rows:
        expected_model = ai_provider.DEFAULT_MODELS.get(row["provider"])
        if row["provider"] in providers and row["model_name"] != expected_model:
            problems.append(f"{row['provider']}: serija ima model {row['model_name']}, sada je {expected_model}")
        if row["version"] not in active_versions:
            problems.append(f"serija ima prompt {row['version']}, aktivni su {sorted(active_versions)}")
    if problems:
        raise ExperimentError("Protokol bi bio narušen:\n  - " + "\n  - ".join(sorted(set(problems))))


def pending_slots(plan, counts):
    """Mesta iz plana koja još nisu urađena, istim redosledom."""
    return [(a, q, p) for a, q, p in plan if counts.get((q, p), 0) < a]


# ---------- izvrsavanje ----------

def _classify(status, body):
    """'ok' | 'format' (model odgovorio, nevalidno) | 'infra' (bez odgovora modela) | 'error'."""
    if status == 201:
        return "ok"
    if status == 422:
        run_id = body.get("generation_run_id")
        row = _query("""
            SELECT (raw_response IS NOT NULL
                    OR JSON_VALUE(params_used, '$.finish_reason') IS NOT NULL) AS answered
            FROM ai_generation_runs WHERE id = %s
        """, (run_id,)) if run_id else []
        return "format" if row and row[0]["answered"] else "infra"
    return "error"


def run_experiment(batch_id, question_ids, providers, per_question, dry_run=False,
                   max_calls=None, generate=generate_similar_for_question, out=print):
    """Izvršava (ili samo prikazuje) plan; vraća izveštaj kao dict."""
    unknown = [p for p in providers if p not in ai_provider.DEFAULT_MODELS]
    if unknown:
        raise ExperimentError(f"Nepoznati modeli: {unknown} (dozvoljeno: {sorted(ai_provider.DEFAULT_MODELS)})")
    if per_question < 1:
        raise ExperimentError("--per-question mora biti bar 1")
    if not question_ids:
        raise ExperimentError("Referentni skup nema pitanja")
    if not _query("SELECT id FROM evaluation_batches WHERE id = %s", (batch_id,)):
        raise ExperimentError(f"Serija {batch_id} ne postoji")

    check_protocol(batch_id, providers)
    plan = build_plan(question_ids, providers, per_question)
    counts = answered_counts(batch_id)
    pending = pending_slots(plan, counts)

    report = {
        "planned": Counter(p for _, _, p in plan),
        "done_before": Counter(p for _, _, p in plan) - Counter(p for _, _, p in pending),
        "ok": Counter(), "format": Counter(), "infra": Counter(), "error": Counter(),
        "stopped": {}, "reasons": defaultdict(Counter), "calls": 0,
        "run_ids": [], "artifact_ids": [], "pending": len(pending),
    }

    out(f"Serija {batch_id}: {len(question_ids)} pitanja x {len(providers)} modela x {per_question} "
        f"= {len(plan)} mesta; urađeno {len(plan) - len(pending)}, čeka {len(pending)}")

    if dry_run:
        done = set(plan) - set(pending)
        for slot in plan:
            attempt, question_id, provider = slot
            out(f"  {'urađeno' if slot in done else 'čeka  '}  pokušaj {attempt}  pitanje {question_id}  {provider}")
        return report

    infra_streak = Counter()
    for attempt, question_id, provider in pending:
        if provider in report["stopped"]:
            continue
        if max_calls is not None and report["calls"] >= max_calls:
            out(f"Zaustavljeno posle {max_calls} poziva (--max-calls); ponovo pokreni za nastavak.")
            break

        report["calls"] += 1
        try:
            body, status = generate(question_id, provider, batch_id)
        except Exception as e:  # npr. baza - nema smisla nastaviti
            report["error"][provider] += 1
            report["reasons"][provider][f"izuzetak: {e}"] += 1
            out(f"  GREŠKA pokušaj {attempt} pitanje {question_id} {provider}: {e} - prekidam")
            break

        if body.get("generation_run_id"):
            report["run_ids"].append(body["generation_run_id"])
        if body.get("artifact_id"):
            report["artifact_ids"].append(body["artifact_id"])

        kind = _classify(status, body)
        report[kind][provider] += 1
        reason = body.get("details") or body.get("error")
        if kind != "ok":
            report["reasons"][provider][reason] += 1
        out(f"  pokušaj {attempt}  pitanje {question_id}  {provider:10}  {kind}"
            + (f"  ({reason})" if kind != "ok" else ""))

        if kind == "infra":
            infra_streak[provider] += 1
            if " 429 " in f" {reason} ":
                report["stopped"][provider] = "429 - verovatno dnevni limit"
            elif infra_streak[provider] >= INFRA_STOP_AFTER:
                report["stopped"][provider] = f"{INFRA_STOP_AFTER} uzastopna pada bez odgovora modela"
            if provider in report["stopped"]:
                out(f"  -> {provider} zaustavljen: {report['stopped'][provider]}")
        else:
            infra_streak[provider] = 0
        if kind == "error":
            report["stopped"][provider] = f"greška {status}: {reason}"

    remaining = pending_slots(plan, answered_counts(batch_id))
    report["pending"] = len(remaining)
    return report


def print_report(report, providers, out=print):
    out("\nIzveštaj (ovo pokretanje):")
    out(f"  {'model':12} {'plan':>5} {'ranije':>7} {'ok':>4} {'format':>7} {'bez odg.':>9} {'greška':>7}")
    for p in providers:
        out(f"  {p:12} {report['planned'][p]:>5} {report['done_before'][p]:>7} {report['ok'][p]:>4} "
            f"{report['format'][p]:>7} {report['infra'][p]:>9} {report['error'][p]:>7}")
    for p in providers:
        for reason, n in report["reasons"][p].most_common():
            out(f"  {p}: {n} x {reason}")
        if p in report["stopped"]:
            out(f"  {p}: ZAUSTAVLJEN - {report['stopped'][p]}")
    out(f"Poziva modela: {report['calls']}; preostalo mesta: {report['pending']}")


# ---------- referentni skup ----------

def resolve_question_ids(batch_id, reference_set_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not reference_sets_enabled(cursor):
            raise ExperimentError("Tabele za referentni skup ne postoje - pokrenite db/migration_reference_sets.sql")
        cursor.execute("SELECT id, reference_set_id FROM evaluation_batches WHERE id = %s", (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            raise ExperimentError(f"Serija {batch_id} ne postoji")

        if reference_set_id is not None and batch["reference_set_id"] != reference_set_id:
            if batch["reference_set_id"] is not None:
                raise ExperimentError(f"Serija {batch_id} je već vezana za skup {batch['reference_set_id']}")
            cursor.execute("SELECT COUNT(*) AS n FROM ai_generation_runs WHERE evaluation_batch_id = %s", (batch_id,))
            if cursor.fetchone()["n"]:
                raise ExperimentError(f"Serija {batch_id} već ima run-ove - skup se ne može naknadno vezati")
            cursor.execute("SELECT id FROM reference_sets WHERE id = %s", (reference_set_id,))
            if not cursor.fetchone():
                raise ExperimentError(f"Referentni skup {reference_set_id} ne postoji")
            cursor.execute("UPDATE evaluation_batches SET reference_set_id = %s WHERE id = %s",
                           (reference_set_id, batch_id))
            conn.commit()
            batch["reference_set_id"] = reference_set_id
            print(f"Serija {batch_id} vezana za referentni skup {reference_set_id}.")

        if batch["reference_set_id"] is None:
            raise ExperimentError(f"Serija {batch_id} nema referentni skup (dodaj --reference-set ID)")

        cursor.execute("""
            SELECT question_id FROM reference_set_questions
            WHERE reference_set_id = %s ORDER BY order_no ASC, question_id ASC
        """, (batch["reference_set_id"],))
        return [row["question_id"] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/run_experiment.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--batch", type=int, required=True, help="id evaluacione serije")
    parser.add_argument("--models", required=True, help="npr. groq,gemini,openrouter")
    parser.add_argument("--per-question", type=int, required=True, help="broj pokušaja po pitanju i modelu")
    parser.add_argument("--reference-set", type=int, help="veži skup za seriju bez skupa i bez run-ova")
    parser.add_argument("--max-calls", type=int, help="najviše ovoliko poziva modela u ovom pokretanju")
    parser.add_argument("--dry-run", action="store_true", help="samo ispiši plan, bez poziva modela")
    args = parser.parse_args(argv)

    providers = [p.strip() for p in args.models.split(",") if p.strip()]
    try:
        if args.dry_run and args.reference_set is not None:
            raise ExperimentError("--dry-run ne vezuje skup; prvo pokreni bez --dry-run ili veži skup ranije")
        question_ids = resolve_question_ids(args.batch, args.reference_set)
        report = run_experiment(args.batch, question_ids, providers, args.per_question,
                                dry_run=args.dry_run, max_calls=args.max_calls)
    except ExperimentError as e:
        print(f"GREŠKA: {e}")
        return 2
    if not args.dry_run:
        print_report(report, providers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
