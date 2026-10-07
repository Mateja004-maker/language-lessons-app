"""
Mehanička provera (PASS/FAIL) JSON odgovora modela za generisanje sličnog
pitanja. Bez Flask-a i baze - koristi je app.py (generisanje i izmena
predloga pri pregledu), testovi i komandna linija:

    python -m question_validation odgovor.json [--type mc|open] [--answers N] [--version mc-v2]

Provera staje na PRVOJ grešci (isti redosled i iste poruke kao ranija
validate_similar_question_payload u app.py), pa je validation_errors u bazi
isti kao pre izdvajanja.

Verzije prompta:
- do v2 (mc-v1, mc-v2, open-v1, open-v2, i nepoznata/bez verzije): polja
  koja nisu deo formata se ignorišu - ponašanje kao do sada;
- od v3: nepoznata polja (na vrhu i u ponuđenim odgovorima) su greška.
  Nijedan v3 prompt još ne postoji, pa ovo pravilo za sada nije aktivno.
"""

import json
import re
import sys
from dataclasses import dataclass, field

QUESTION_TYPES = ("mc", "open")

# Od koje verzije prompta se nepoznata polja odbijaju
STRICT_FIELDS_FROM_VERSION = 3

# Dozvoljena polja u strogom režimu (v3+). Tačka A (težina/Blumov nivo)
# ovde dodaje svoja polja kada uvede v3 prompt.
ALLOWED_TOP_LEVEL_FIELDS = {
    "mc": {"question_text", "answers"},
    "open": {"question_text"},
}
ALLOWED_ANSWER_FIELDS = {"answer_text", "is_correct"}

_VERSION_NUMBER_RE = re.compile(r"-v(\d+)$")


@dataclass
class ValidationResult:
    passed: bool
    errors: list = field(default_factory=list)


def prompt_version_number(prompt_version):
    """'mc-v2' -> 2; None ili nepoznat oblik -> None."""
    if not isinstance(prompt_version, str):
        return None
    match = _VERSION_NUMBER_RE.search(prompt_version.strip())
    return int(match.group(1)) if match else None


def strict_fields_enabled(prompt_version) -> bool:
    number = prompt_version_number(prompt_version)
    return number is not None and number >= STRICT_FIELDS_FROM_VERSION


def _fail(message):
    return ValidationResult(passed=False, errors=[message])


def validate(parsed, question_type, expected_answer_count, prompt_version=None) -> ValidationResult:
    """Proverava isparsiran JSON odgovora modela za dati tip pitanja."""
    if not isinstance(parsed, dict):
        return _fail("Odgovor modela mora biti JSON objekat")

    strict = strict_fields_enabled(prompt_version)
    if strict:
        allowed = ALLOWED_TOP_LEVEL_FIELDS.get(question_type, ALLOWED_TOP_LEVEL_FIELDS["open"])
        unknown = sorted(set(parsed) - allowed)
        if unknown:
            return _fail(f"Nepoznata polja u odgovoru: {', '.join(unknown)}")

    question_text = parsed.get("question_text")
    if not isinstance(question_text, str) or not question_text.strip():
        return _fail("Nedostaje ili je prazan question_text")

    if question_type == "mc":
        answers = parsed.get("answers")
        if not isinstance(answers, list) or len(answers) != expected_answer_count:
            return _fail(f"Očekivano je tačno {expected_answer_count} ponuđenih odgovora")

        correct_count = 0
        for a in answers:
            if not isinstance(a, dict):
                return _fail("Svaki ponuđeni odgovor mora biti JSON objekat")
            if strict:
                unknown = sorted(set(a) - ALLOWED_ANSWER_FIELDS)
                if unknown:
                    return _fail(f"Nepoznata polja u ponuđenom odgovoru: {', '.join(unknown)}")
            if not isinstance(a.get("answer_text"), str) or not a["answer_text"].strip():
                return _fail("Ponuđeni odgovor bez teksta")
            if not isinstance(a.get("is_correct"), bool):
                return _fail("is_correct mora biti true/false")
            if a["is_correct"]:
                correct_count += 1

        if correct_count != 1:
            return _fail(f"Očekivan je tačno jedan tačan odgovor, pronađeno {correct_count}")

    else:  # "open"
        if "answers" in parsed:
            return _fail("Otvoreno pitanje ne sme imati ponuđene odgovore")

    return ValidationResult(passed=True)


# --- Komandna linija ---

def _parse_args(argv):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m question_validation",
        description="Mehanička provera JSON odgovora modela za slično pitanje (PASS/FAIL).",
    )
    parser.add_argument("file", help="fajl sa sirovim odgovorom modela (JSON)")
    parser.add_argument("--type", choices=QUESTION_TYPES,
                        help="tip pitanja; podrazumevano mc ako odgovor ima 'answers', inače open")
    parser.add_argument("--answers", type=int,
                        help="očekivan broj ponuđenih odgovora (mc); podrazumevano broj u samom fajlu")
    parser.add_argument("--version", default=None,
                        help="verzija prompta, npr. mc-v2 ili mc-v3 (od v3 se odbijaju nepoznata polja)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Ispisuje PASS ili FAIL sa razlozima. Izlazni kod: 0 PASS, 1 FAIL."""
    args = _parse_args(argv)
    # Windows konzola (cp1252) inače pada na č/ć/š u porukama
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(args.file, encoding="utf-8") as f:
        raw = f.read()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        print("FAIL")
        print("- Odgovor modela nije validan JSON")
        return 1

    question_type = args.type or ("mc" if isinstance(parsed, dict) and "answers" in parsed else "open")
    expected = args.answers
    if expected is None:
        answers = parsed.get("answers") if isinstance(parsed, dict) else None
        expected = len(answers) if isinstance(answers, list) else 0

    result = validate(parsed, question_type, expected, args.version)
    print("PASS" if result.passed else "FAIL")
    for error in result.errors:
        print(f"- {error}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
