"""Probni krug v3 prompta na PRAVIM modelima (pre zamrzavanja prompta i eksperimenta).

    python tools/probe_v3.py                 # samo plan, bez poziva modela
    python tools/probe_v3.py --confirm       # stvarni pozivi (troši besplatne limite)
    [--models groq,gemini,openrouter] [--mc-question ID] [--open-question ID] [--ids-file PUTANJA]

(iz foldera backend/). Za po jedno MC i jedno otvoreno pitanje iz predmeta
"Osnove programiranja" poziva svaki model kroz generate_similar_for_question -
istu logiku kao ruta (validacija, ponovni zahtev posle lošeg formata,
beleženje) - BEZ serije (evaluation_batch_id NULL), pa probni run-ovi ne ulaze
u eksperiment.

Za svaki poziv ispisuje: da li je prošao validaciju, failure_type, ponovni
zahtev, vreme odziva, i iz SIROVOG odgovora modela: difficulty i bloom_level
(dozvoljena vrednost? dijakritici?) i višak polja. Ako je bilo ponovnog
zahteva, analizira i prvi odgovor.

Napravljeni predlozi su pravi predlozi u statusu 'predlog' (vide se na
/ai/predlozi). ID-jevi svih run-ova i predloga se upisuju u --ids-file
(podrazumevano backend/probe_v3_ids.json, nije u git-u) posle SVAKOG poziva,
da bi mogli da se obrišu tačno po ID-jevima.
"""
import argparse
import json
import os
import sys
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# app MORA da se učita pre ai_provider-a: app.py učitava backend/.env, a
# ai_provider čita API ključeve iz okruženja u trenutku učitavanja (inače 401).
from app import generate_similar_for_question, get_db_connection  # noqa: E402
import ai_provider  # noqa: E402
import prompt_templates  # noqa: E402
import question_validation  # noqa: E402

SUBJECT_NAME = "Osnove programiranja"
DEFAULT_IDS_FILE = os.path.join(BACKEND_DIR, "probe_v3_ids.json")
KEY_NAMES = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
             "openrouter": "OPENROUTER_API_KEY", "mistral": "MISTRAL_API_KEY"}


def _query(sql, params=()):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def pick_questions(mc_id=None, open_id=None):
    """(MC pitanje, otvoreno pitanje) iz predmeta SUBJECT_NAME."""
    subject = _query("SELECT id FROM subjects WHERE name = %s", (SUBJECT_NAME,))
    if not subject:
        raise SystemExit(f"Predmet '{SUBJECT_NAME}' ne postoji")
    rows = _query("""
        SELECT q.id, q.question_text,
               (SELECT COUNT(*) FROM exam_answers a WHERE a.question_id = q.id) AS answers,
               (SELECT COALESCE(SUM(a.is_correct), 0) FROM exam_answers a WHERE a.question_id = q.id) AS correct
        FROM exam_questions q WHERE q.subject_id = %s ORDER BY q.id
    """, (subject[0]["id"],))
    by_id = {row["id"]: row for row in rows}
    mc = by_id.get(mc_id) if mc_id else next((r for r in rows if r["answers"] >= 2 and r["correct"] == 1), None)
    open_q = by_id.get(open_id) if open_id else next((r for r in rows if r["answers"] == 0), None)
    if not mc or mc["answers"] < 2 or mc["correct"] != 1:
        raise SystemExit("Nema odgovarajućeg MC pitanja (bar 2 odgovora, tačno 1 tačan) u predmetu")
    if not open_q or open_q["answers"] != 0:
        raise SystemExit("Nema otvorenog pitanja (bez ponuđenih odgovora) u predmetu")
    return mc, open_q


def inspect_raw(raw_text, question_type):
    """Analiza sirovog teksta modela (bez obzira na validaciju)."""
    info = {"json": False, "difficulty": None, "bloom_level": None, "labels_ok": False,
            "diacritics": False, "extra_fields": []}
    try:
        data = json.loads(raw_text) if raw_text is not None else None
    except (ValueError, TypeError):
        return info
    if not isinstance(data, dict):
        return info
    info["json"] = True
    info["difficulty"] = data.get("difficulty")
    info["bloom_level"] = data.get("bloom_level")
    info["labels_ok"] = (info["difficulty"] in question_validation.DIFFICULTY_VALUES
                         and info["bloom_level"] in question_validation.BLOOM_LEVELS)
    info["diacritics"] = any(isinstance(v, str) and not v.isascii() for v in (info["difficulty"], info["bloom_level"]))
    allowed = question_validation.ALLOWED_TOP_LEVEL_FIELDS.get(question_type, set())
    extra = sorted(set(data) - allowed)
    for answer in data.get("answers") or []:
        if isinstance(answer, dict):
            extra += [f"answers.{k}" for k in sorted(set(answer) - question_validation.ALLOWED_ANSWER_FIELDS)]
    info["extra_fields"] = sorted(set(extra))
    return info


def _save_ids(path, record):
    data = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    if data and data[-1].get("started_at") == record["started_at"]:
        data[-1] = record
    else:
        data.append(record)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/probe_v3.py")
    parser.add_argument("--confirm", action="store_true", help="stvarno pozovi modele (bez ovoga samo plan)")
    parser.add_argument("--models", default="groq,gemini,openrouter")
    parser.add_argument("--mc-question", type=int)
    parser.add_argument("--open-question", type=int)
    parser.add_argument("--ids-file", default=DEFAULT_IDS_FILE)
    args = parser.parse_args(argv)

    providers = [p.strip() for p in args.models.split(",") if p.strip()]
    unknown = [p for p in providers if p not in ai_provider.DEFAULT_MODELS]
    if unknown:
        print(f"GREŠKA: nepoznati modeli {unknown}")
        return 2
    mc, open_q = pick_questions(args.mc_question, args.open_question)
    versions = {t: prompt_templates._read_template_file(t)[0] for t in ("mc", "open")}

    plan = [(q, qtype, p) for q, qtype in ((mc, "mc"), (open_q, "open")) for p in providers]
    print(f"Probni krug v3 (bez serije), prompt {versions['mc']} / {versions['open']}")
    print(f"  MC pitanje #{mc['id']}: {mc['question_text'][:70]}")
    print(f"  otvoreno pitanje #{open_q['id']}: {open_q['question_text'][:70]}")
    for p in providers:
        key_ok = bool(getattr(ai_provider, KEY_NAMES[p], ""))
        print(f"  {p:11} {ai_provider.DEFAULT_MODELS[p]:42} ključ: {'podešen' if key_ok else 'NEDOSTAJE'}")
    print(f"Plan: {len(plan)} generisanja ({len(providers)} modela x 2 pitanja); najviše {2 * len(plan)} odgovora "
          f"modela (jedan ponovni zahtev posle lošeg formata) i do 3 HTTP pokušaja po zahtevu (pauze 5s/15s).")
    print(f"Run-ovi i predlozi se beleže u {args.ids_file}.")
    missing = [p for p in providers if not getattr(ai_provider, KEY_NAMES[p], "")]
    if missing:
        print(f"\nGREŠKA: nedostaje API ključ za {missing} - proveri backend/.env. Proba se ne pokreće.")
        return 2
    if not args.confirm:
        print("\nOvo je samo plan - nijedan model nije pozvan. Za stvarno pokretanje dodaj --confirm.")
        return 0

    record = {"started_at": datetime.now().isoformat(timespec="seconds"), "runs": [], "artifacts": []}
    _save_ids(args.ids_file, record)
    rows = []
    for question, qtype, provider in plan:
        body, status = generate_similar_for_question(question["id"], provider, None)
        run_id, artifact_id = body.get("generation_run_id"), body.get("artifact_id")
        if run_id:
            record["runs"].append(run_id)
        if artifact_id:
            record["artifacts"].append(artifact_id)
        _save_ids(args.ids_file, record)  # posle svakog poziva - ostaje i ako se proba prekine

        run = (_query("SELECT raw_response, validation_errors, response_time_ms, params_used FROM ai_generation_runs WHERE id = %s",
                      (run_id,)) or [{}])[0] if run_id else {}
        params = json.loads(run.get("params_used") or "{}")
        final = inspect_raw(run.get("raw_response"), qtype)
        first = (inspect_raw((params.get("first_attempt") or {}).get("raw_response"), qtype)
                 if params.get("first_attempt") else None)
        rows.append((question, qtype, provider, status, body, run, final, first))
        print(f"  ... #{question['id']} {provider}: {status} {body.get('failure_type') or 'ok'}")

    print(f"\n{'pitanje':9} {'model':11} {'status':6} {'prošlo':6} {'failure':12} {'pon.':4} {'ms':>6}  "
          f"{'difficulty':10} {'bloom':12} {'oznake ok':9} {'dijakr.':7} višak polja")
    for question, qtype, provider, status, body, run, final, first in rows:
        passed = status == 201
        print(f"#{question['id']:<4} {qtype:3} {provider:11} {status:<6} {'DA' if passed else 'NE':6} "
              f"{body.get('failure_type') or '-':12} {body.get('format_retries', '-')!s:4} {run.get('response_time_ms') if run.get('response_time_ms') is not None else '-':>6}  "
              f"{str(final['difficulty']):10} {str(final['bloom_level']):12} {'DA' if final['labels_ok'] else 'NE':9} "
              f"{'DA' if final['diacritics'] else 'ne':7} {', '.join(final['extra_fields']) or '-'}")
        if first:
            print(f"      prvi odgovor: JSON={'da' if first['json'] else 'NE'}, oznake ok={'da' if first['labels_ok'] else 'ne'}, "
                  f"dijakritici={'DA' if first['diacritics'] else 'ne'}, višak={', '.join(first['extra_fields']) or '-'}, "
                  f"razlog={(json.loads(run.get('params_used') or '{}').get('first_attempt') or {}).get('validation_errors')}")
        if not passed:
            print(f"      razlog (run): {' '.join((run.get('validation_errors') or '').split())[:120]}")

    print("\nPo modelu:")
    for p in providers:
        mine = [r for r in rows if r[2] == p]
        ok = sum(r[3] == 201 for r in mine)
        first_ok = sum(r[3] == 201 and r[4].get("format_retries") == 0 for r in mine)
        print(f"  {p:11} prošlo {ok}/{len(mine)} (iz prve {first_ok}), oznake bez dijakritika u svim odgovorima: "
              f"{'DA' if all(r[6]['labels_ok'] and not r[6]['diacritics'] for r in mine) else 'NE'}, "
              f"višak polja: {'NE' if not any(r[6]['extra_fields'] for r in mine) else 'DA'}")
    print(f"\nNapravljeno: run-ova {len(record['runs'])}, predloga {len(record['artifacts'])} -> {args.ids_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
