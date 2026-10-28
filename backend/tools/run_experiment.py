"""Pokretač eksperimenta generisanja sličnih pitanja (tačka D).

    python tools/run_experiment.py --batch ID --models groq,gemini,openrouter --per-question N
        [--mode single|set] [--group-size G --k K] [--reference-set ID] [--max-calls K] [--dry-run]

Režimi (tačka J): single (podrazumevano) - svako pitanje skupa je poseban ulaz;
set - pitanja referentnog skupa se dele redom u grupe od G pitanja, a jedan
poziv daje do K novih pitanja (generate_similar_set). Jedna serija ne sme da
meša režime, a u režimu set ni veličinu grupe ni K.

(iz foldera backend/). Za svako pitanje referentnog skupa serije, za svaki
model i za svaki od N pokušaja poziva istu logiku kao ruta
POST /api/questions/<id>/generate-similar (generate_similar_for_question):
ista validacija, isto beleženje, isto slepo ocenjivanje i isti ponovni
pokušaji provajdera; svaki run dobija evaluation_batch_id serije.

Posle lošeg formata ruta (i pokretač) pita model još jednom; izveštaj
razdvaja: ok iz prve, ok posle ponavljanja, loš format, prazan odgovor i
bez odgovora po vrsti (network / http_4xx / rate_limit / http_5xx).

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

--task explanation --explain-mode mode_a|mode_b: isti pokretač za objašnjenja
(Andrejev modul, generate_explanation_for_question). Jedna serija = jedan režim
objašnjenja; serija ne sme da ima run-ove pitanja ni drugog režima. U režimu A
pitanja bez poznatog rešenja (resolve_explanation_source) se izbacuju iz plana i
ispisuju kao preskočena; u režimu B izveštaj broji i ishod mehaničke provere.
--mode set, --group-size i --k ne važe za objašnjenja.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# app MORA da se učita pre ai_provider-a: app.py učitava backend/.env, a
# ai_provider čita API ključeve iz okruženja u trenutku učitavanja (inače 401).
from app import (  # noqa: E402
    EXPLANATION_DEFAULT_MODELS,
    FAILURE_COLUMNS,
    SET_MAX_K,
    generate_explanation_for_question,
    generate_similar_for_question,
    generate_similar_set,
    get_db_connection,
    input_question_ids_of_run,
    reference_sets_enabled,
    resolve_explanation_source,
    table_columns_exist,
)
import ai_provider  # noqa: E402
import explanation_prompts  # noqa: E402
import generation_failures  # noqa: E402
import prompt_templates  # noqa: E402

API_KEY_NAMES = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
                 "openrouter": "OPENROUTER_API_KEY", "mistral": "MISTRAL_API_KEY"}

INFRA_STOP_AFTER = 3  # uzastopnih infrastrukturnih padova istog modela -> stani sa tim modelom


class ExperimentError(Exception):
    """Greška u podešavanju ili protokolu - ništa se ne poziva."""


# ---------- plan ----------

MODES = ("single", "set")
TASKS = ("question", "explanation")
EXPLAIN_MODES = ("mode_a", "mode_b")


def build_plan(units, providers, per_question):
    """Pun plan eksperimenta, istim redosledom za sve modele (naizmenično).
    unit je id pitanja (single) ili grupa id-jeva kao tuple (set)."""
    return [
        (attempt, unit, provider)
        for attempt in range(1, per_question + 1)
        for unit in units
        for provider in providers
    ]


def make_groups(question_ids, group_size):
    """Pitanja skupa redom u grupe od group_size (poslednja može biti manja)."""
    return [tuple(question_ids[i:i + group_size]) for i in range(0, len(question_ids), group_size)]


def _purpose(mode, task="question"):
    if task == "explanation":
        return explanation_prompts.PURPOSE_EXPLANATION
    return prompt_templates.PURPOSE_SIMILAR_QUESTION_SET if mode == "set" else prompt_templates.PURPOSE_SIMILAR_QUESTION


def _unit_label(unit):
    return f"grupa {list(unit)}" if isinstance(unit, tuple) else f"pitanje {unit}"


def _query(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def _failure_columns_exist():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        return table_columns_exist(cursor, "ai_generation_runs", FAILURE_COLUMNS)
    finally:
        cursor.close()
        conn.close()


def answered_counts(batch_id, mode="single", explain_mode=None):
    """{(unit, provider): broj run-ova serije u kojima je model odgovorio}.
    unit = id pitanja (single) ili grupa id-jeva (set, iz params_used.input_question_ids).
    Odgovorio = stiglo je telo odgovora, ili je (posle migracije tačke I) vrsta
    pada 'empty' / 'invalid_json' / 'schema'. explain_mode (objašnjenja): broje
    se samo run-ovi objašnjenja tog režima, unit je id pitanja."""
    model_failure = ""
    mode_filter = ""
    if explain_mode is not None:
        params = [batch_id, _purpose(mode, "explanation"), explain_mode]
        mode_filter = "AND r.mode = %s"
    else:
        params = [batch_id, _purpose(mode)]
    if _failure_columns_exist():
        model_failure = f"OR r.failure_type IN ({', '.join(['%s'] * len(generation_failures.MODEL_FAILURES))})"
        params += list(generation_failures.MODEL_FAILURES)
    rows = _query(f"""
        SELECT r.source_question_id AS question_id, r.params_used, m.provider
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s
          AND r.purpose = %s
          {mode_filter}
          AND (r.raw_response IS NOT NULL
               OR JSON_VALUE(r.params_used, '$.finish_reason') IS NOT NULL
               {model_failure})
    """, tuple(params))
    counts = Counter()
    for row in rows:
        unit = tuple(input_question_ids_of_run(row["params_used"])) if mode == "set" else row["question_id"]
        counts[(unit, row["provider"])] += 1
    return dict(counts)


def check_protocol(batch_id, providers, mode="single", groups=None, k=None):
    """Serija ne sme da meša modele, verzije prompta ni režime (single / set);
    u režimu set ni grupe ni K."""
    problems = []
    other_purpose = _purpose("set" if mode == "single" else "single")
    if _query("SELECT 1 FROM ai_generation_runs WHERE evaluation_batch_id = %s AND purpose = %s LIMIT 1",
              (batch_id, other_purpose)):
        problems.append(f"serija već ima run-ove drugog režima ({other_purpose}) - serija ne sme da meša režime")
    if mode == "set":
        active_versions = {prompt_templates.template_version(prompt_templates.SET_TEMPLATE_FILE.read_text(encoding="utf-8"))}
        planned = set(groups or [])
        for row in _query("SELECT params_used FROM ai_generation_runs WHERE evaluation_batch_id = %s AND purpose = %s",
                          (batch_id, _purpose("set"))):
            group = tuple(input_question_ids_of_run(row["params_used"]))
            if group not in planned:
                problems.append(f"serija ima grupu {list(group)} koja nije u planu (druga veličina grupe ili drugi skup)")
            run_k = (json.loads(row["params_used"]) or {}).get("k") if row["params_used"] else None
            if run_k != k:
                problems.append(f"serija ima K={run_k}, traženo je K={k}")
    else:
        active_versions = {prompt_templates._read_template_file(t)[0] for t in ("mc", "open")}
    rows = _query("""
        SELECT DISTINCT m.provider, m.model_name, p.version
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        JOIN ai_prompts p ON p.id = r.prompt_id
        WHERE r.evaluation_batch_id = %s AND r.purpose = %s
    """, (batch_id, _purpose(mode)))
    for row in rows:
        expected_model = ai_provider.DEFAULT_MODELS.get(row["provider"])
        if row["provider"] in providers and row["model_name"] != expected_model:
            problems.append(f"{row['provider']}: serija ima model {row['model_name']}, sada je {expected_model}")
        if row["version"] not in active_versions:
            problems.append(f"serija ima prompt {row['version']}, aktivni su {sorted(active_versions)}")
    if problems:
        raise ExperimentError("Protokol bi bio narušen:\n  - " + "\n  - ".join(sorted(set(problems))))


def explanation_sources(question_ids, explain_mode):
    """{id pitanja: resolve_explanation_source(...)} - samo čita. U režimu A
    pitanje bez poznatog rešenja ima ključ 'error'; inače izvor nosi
    question_type (i has_test_cases u režimu B) za izbor šablona."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sources = {}
        for question_id in question_ids:
            cursor.execute("SELECT * FROM exam_questions WHERE id = %s", (question_id,))
            question = cursor.fetchone()
            sources[question_id] = (resolve_explanation_source(cursor, question, explain_mode) if question
                                    else {"error": "pitanje ne postoji"})
        return sources
    finally:
        cursor.close()
        conn.close()


def _explanation_prompt_version(explain_mode, source):
    """Aktivna verzija šablona za pitanje (isti izbor kao ensure_prompt_synced)."""
    return explanation_prompts._read_template_file(
        explain_mode, source.get("question_type"), source.get("has_test_cases"))[0]


def check_explanation_protocol(batch_id, providers, explain_mode, sources):
    """Serija objašnjenja ne sme da meša zadatke (pitanja / objašnjenja), režime
    objašnjenja, modele ni verzije šablona (aktivna verzija zavisi od tipa pitanja)."""
    problems = []
    for row in _query("""SELECT DISTINCT r.purpose, r.mode FROM ai_generation_runs r
                         WHERE r.evaluation_batch_id = %s""", (batch_id,)):
        if row["purpose"] != explanation_prompts.PURPOSE_EXPLANATION:
            problems.append(f"serija već ima run-ove drugog zadatka ({row['purpose']}) - serija ne sme da meša pitanja i objašnjenja")
        elif row["mode"] != explain_mode:
            problems.append(f"serija već ima run-ove objašnjenja u režimu {row['mode']} - serija ne sme da meša režime")
    rows = _query("""
        SELECT DISTINCT r.source_question_id, m.provider, m.model_name, p.version
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        JOIN ai_prompts p ON p.id = r.prompt_id
        WHERE r.evaluation_batch_id = %s AND r.purpose = %s AND r.mode = %s
    """, (batch_id, explanation_prompts.PURPOSE_EXPLANATION, explain_mode))
    for row in rows:
        expected_model = EXPLANATION_DEFAULT_MODELS.get(row["provider"])
        if row["provider"] in providers and row["model_name"] != expected_model:
            problems.append(f"{row['provider']}: serija ima model {row['model_name']}, sada je {expected_model}")
        source = sources.get(row["source_question_id"])
        if source is None or "error" in source:
            problems.append(f"serija ima run za pitanje {row['source_question_id']} koje nije u planu")
            continue
        expected_version = _explanation_prompt_version(explain_mode, source)
        if row["version"] != expected_version:
            problems.append(f"pitanje {row['source_question_id']}: serija ima prompt {row['version']}, aktivan je {expected_version}")
    if problems:
        raise ExperimentError("Protokol bi bio narušen:\n  - " + "\n  - ".join(sorted(set(problems))))


def pending_slots(plan, counts):
    """Mesta iz plana koja još nisu urađena, istim redosledom."""
    return [(a, q, p) for a, q, p in plan if counts.get((q, p), 0) < a]


# ---------- izvrsavanje ----------

REPORT_KINDS = ("ok_first", "ok_retry", "format", "empty", "infra", "error")


def _classify(status, body):
    """Vrsta ishoda za izveštaj:
    ok_first (prošlo iz prve) | ok_retry (prošlo posle ponovnog zahteva) |
    format (loš format i posle ponavljanja) | empty (prazan odgovor) |
    infra (model nije odgovorio; vrsta u failure_type) | error (neočekivano)."""
    if status == 201:
        return "ok_first" if body.get("format_retries", 0) == 0 else "ok_retry"
    failure_type = body.get("failure_type")
    if status == 422 and failure_type in generation_failures.FORMAT_FAILURES:
        return "format"
    if status == 422 and failure_type == "empty":
        return "empty"
    if status == 422 and failure_type in generation_failures.INFRA_FAILURES:
        return "infra"
    return "error"


def _raw_reason(run_id):
    """Sirov razlog iz run-a (ruta vraća razumljivu poruku, ne sirov tekst)."""
    row = _query("SELECT validation_errors FROM ai_generation_runs WHERE id = %s", (run_id,)) if run_id else []
    return " ".join(((row[0]["validation_errors"] if row else None) or "").split())[:90]


def run_experiment(batch_id, question_ids, providers, per_question, dry_run=False,
                   max_calls=None, generate=None, out=print, mode="single", group_size=None, k=None,
                   task="question", explain_mode=None):
    """Izvršava (ili samo prikazuje) plan; vraća izveštaj kao dict."""
    if mode not in MODES:
        raise ExperimentError(f"--mode mora biti jedno od: {', '.join(MODES)}")
    if task not in TASKS:
        raise ExperimentError(f"--task mora biti jedno od: {', '.join(TASKS)}")
    if task == "explanation":
        if explain_mode not in EXPLAIN_MODES:
            raise ExperimentError(f"--explain-mode je obavezan uz --task explanation: {', '.join(EXPLAIN_MODES)}")
        if mode != "single" or group_size is not None or k is not None:
            raise ExperimentError("--mode set, --group-size i --k ne važe uz --task explanation")
    elif explain_mode is not None:
        raise ExperimentError("--explain-mode važi samo uz --task explanation")
    known_models = EXPLANATION_DEFAULT_MODELS if task == "explanation" else ai_provider.DEFAULT_MODELS
    unknown = [p for p in providers if p not in known_models]
    if unknown:
        raise ExperimentError(f"Nepoznati modeli: {unknown} (dozvoljeno: {sorted(known_models)})")
    missing_keys = [p for p in providers if not getattr(ai_provider, API_KEY_NAMES.get(p, ""), "")]
    if missing_keys and not dry_run and generate is None:
        raise ExperimentError(f"Nedostaje API ključ za: {missing_keys} (proveri backend/.env)")
    if per_question < 1:
        raise ExperimentError("--per-question mora biti bar 1")
    if not question_ids:
        raise ExperimentError("Referentni skup nema pitanja")
    if not _query("SELECT id FROM evaluation_batches WHERE id = %s", (batch_id,)):
        raise ExperimentError(f"Serija {batch_id} ne postoji")

    skipped = {}
    if task == "explanation":
        # režim A traži poznato rešenje: pitanja bez njega se izbacuju pre plana
        sources = explanation_sources(question_ids, explain_mode)
        skipped = {q: s["error"] for q, s in sources.items() if "error" in s}
        units = [q for q in question_ids if q not in skipped]
        if not units:
            raise ExperimentError(f"Nijedno pitanje skupa ne može u režim {explain_mode} (nema poznatog rešenja)")
        if generate is None:
            def generate(unit, provider, batch):  # noqa: E306
                return generate_explanation_for_question(unit, explain_mode, provider, batch)
    elif mode == "set":
        if not isinstance(group_size, int) or group_size < 1:
            raise ExperimentError("--group-size mora biti bar 1 u režimu set")
        if not isinstance(k, int) or not 1 <= k <= SET_MAX_K:
            raise ExperimentError(f"--k mora biti od 1 do {SET_MAX_K} u režimu set")
        units = make_groups(question_ids, group_size)
        if generate is None:
            def generate(unit, provider, batch):  # noqa: E306
                return generate_similar_set(list(unit), provider, k, batch,
                                            input_source={"type": "experiment", "batch": batch})
    else:
        units = list(question_ids)
        if generate is None:
            generate = generate_similar_for_question

    if task == "explanation":
        check_explanation_protocol(batch_id, providers, explain_mode, sources)
    else:
        check_protocol(batch_id, providers, mode=mode, groups=units, k=k)
    plan = build_plan(units, providers, per_question)
    counts = answered_counts(batch_id, mode, explain_mode)
    pending = pending_slots(plan, counts)

    report = {
        "planned": Counter(p for _, _, p in plan),
        "done_before": Counter(p for _, _, p in plan) - Counter(p for _, _, p in pending),
        **{kind: Counter() for kind in REPORT_KINDS},
        "infra_types": defaultdict(Counter),
        "stopped": {}, "reasons": defaultdict(Counter), "calls": 0,
        "run_ids": [], "artifact_ids": [], "pending": len(pending),
        "mode": mode, "items_accepted": Counter(), "items_rejected": Counter(),
        "task": task, "explain_mode": explain_mode, "skipped": skipped, "accuracy": defaultdict(Counter),
    }

    unit_text = (f"{len(units)} grupa (do {group_size} pitanja, K={k})" if mode == "set"
                 else f"{len(units)} pitanja")
    label = f"explanation {explain_mode}" if task == "explanation" else mode
    out(f"Serija {batch_id} [{label}]: {unit_text} x {len(providers)} modela x {per_question} "
        f"= {len(plan)} mesta; urađeno {len(plan) - len(pending)}, čeka {len(pending)}")
    for question_id, reason in skipped.items():
        out(f"  preskočeno  pitanje {question_id}: nema poznatog rešenja ({reason})")

    if dry_run:
        done = set(plan) - set(pending)
        for slot in plan:
            attempt, unit, provider = slot
            out(f"  {'urađeno' if slot in done else 'čeka  '}  pokušaj {attempt}  {_unit_label(unit)}  {provider}")
        return report

    infra_streak = Counter()
    for attempt, unit, provider in pending:
        if provider in report["stopped"]:
            continue
        if max_calls is not None and report["calls"] >= max_calls:
            out(f"Zaustavljeno posle {max_calls} poziva (--max-calls); ponovo pokreni za nastavak.")
            break

        report["calls"] += 1
        try:
            body, status = generate(unit, provider, batch_id)
        except Exception as e:  # npr. baza - nema smisla nastaviti
            report["error"][provider] += 1
            report["reasons"][provider][f"izuzetak: {e}"] += 1
            out(f"  GREŠKA pokušaj {attempt} {_unit_label(unit)} {provider}: {e} - prekidam")
            break

        if body.get("generation_run_id"):
            report["run_ids"].append(body["generation_run_id"])
        if body.get("artifact_id"):
            report["artifact_ids"].append(body["artifact_id"])
        report["artifact_ids"].extend(body.get("artifact_ids") or [])
        report["items_accepted"][provider] += body.get("accepted", 0) or 0
        report["items_rejected"][provider] += body.get("rejected", 0) or 0

        kind = _classify(status, body)
        failure_type = body.get("failure_type")
        report[kind][provider] += 1
        if explain_mode == "mode_b" and status == 201:
            accuracy = body.get("accuracy_check_passed")
            report["accuracy"][provider]["prošla" if accuracy == 1 else "nije prošla" if accuracy == 0
                                         else "nije izvršena"] += 1
        reason = None
        if kind not in ("ok_first", "ok_retry"):
            reason = f"{failure_type or status}: {_raw_reason(body.get('generation_run_id')) or body.get('error')}"
            report["reasons"][provider][reason] += 1
        if kind == "infra":
            report["infra_types"][provider][failure_type] += 1
        out(f"  pokušaj {attempt}  {_unit_label(unit)}  {provider:10}  {kind}" + (f"  ({reason})" if reason else ""))

        if kind == "infra":
            infra_streak[provider] += 1
            if failure_type == "rate_limit":
                report["stopped"][provider] = "rate_limit (429) - verovatno dnevni limit"
            elif infra_streak[provider] >= INFRA_STOP_AFTER:
                report["stopped"][provider] = f"{INFRA_STOP_AFTER} uzastopna pada bez odgovora modela"
            if provider in report["stopped"]:
                out(f"  -> {provider} zaustavljen: {report['stopped'][provider]}")
        else:
            infra_streak[provider] = 0
        if kind == "error":
            report["stopped"][provider] = f"greška {status}: {reason}"

    remaining = pending_slots(plan, answered_counts(batch_id, mode, explain_mode))
    report["pending"] = len(remaining)
    return report


def print_report(report, providers, out=print):
    out("\nIzveštaj (ovo pokretanje):")
    out(f"  {'model':12} {'plan':>5} {'ranije':>7} {'ok iz prve':>11} {'ok posle pon.':>14} "
        f"{'loš format':>11} {'prazan':>7} {'bez odg.':>9} {'greška':>7}")
    for p in providers:
        out(f"  {p:12} {report['planned'][p]:>5} {report['done_before'][p]:>7} {report['ok_first'][p]:>11} "
            f"{report['ok_retry'][p]:>14} {report['format'][p]:>11} {report['empty'][p]:>7} "
            f"{report['infra'][p]:>9} {report['error'][p]:>7}")
    if report.get("mode") == "set":
        for p in providers:
            out(f"  {p}: pitanja prihvaćeno {report['items_accepted'][p]}, odbijeno (stavke) {report['items_rejected'][p]}")
    if report.get("explain_mode") == "mode_b":
        for p in providers:
            acc = report["accuracy"][p]
            out(f"  {p}: mehanička provera - prošla {acc['prošla']}, nije prošla {acc['nije prošla']}, "
                f"nije izvršena {acc['nije izvršena']}")
    if report.get("skipped"):
        out(f"  preskočeno (nema poznatog rešenja): {sorted(report['skipped'])}")
    for p in providers:
        if report["infra_types"][p]:
            out(f"  {p}: bez odgovora po vrsti: {dict(report['infra_types'][p])}")
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
    parser.add_argument("--mode", choices=MODES, default="single", help="single (pitanje po pitanje) ili set (grupe pitanja)")
    parser.add_argument("--group-size", type=int, help="režim set: broj pitanja skupa po grupi")
    parser.add_argument("--k", type=int, help="režim set: broj novih pitanja po pozivu")
    parser.add_argument("--task", choices=TASKS, default="question", help="question (slična pitanja) ili explanation (objašnjenja)")
    parser.add_argument("--explain-mode", choices=EXPLAIN_MODES, help="obavezno uz --task explanation: mode_a ili mode_b")
    args = parser.parse_args(argv)

    providers = [p.strip() for p in args.models.split(",") if p.strip()]
    try:
        if args.dry_run and args.reference_set is not None:
            raise ExperimentError("--dry-run ne vezuje skup; prvo pokreni bez --dry-run ili veži skup ranije")
        question_ids = resolve_question_ids(args.batch, args.reference_set)
        report = run_experiment(args.batch, question_ids, providers, args.per_question,
                                dry_run=args.dry_run, max_calls=args.max_calls,
                                mode=args.mode, group_size=args.group_size, k=args.k,
                                task=args.task, explain_mode=args.explain_mode)
    except ExperimentError as e:
        print(f"GREŠKA: {e}")
        return 2
    if not args.dry_run:
        print_report(report, providers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
