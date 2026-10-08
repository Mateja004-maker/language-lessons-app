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
- od v3: nepoznata polja (na vrhu i u ponuđenim odgovorima) su greška, a
  "difficulty" i "bloom_level" su obavezni, sa dozvoljenim vrednostima
  (ključevi i vrednosti bez dijakritika).
"""

import json
import re
import sys
from dataclasses import dataclass, field

QUESTION_TYPES = ("mc", "open")

# Od koje verzije prompta se nepoznata polja odbijaju i traže oznake
STRICT_FIELDS_FROM_VERSION = 3

# Težina i nivo Blumove taksonomije (v3+): model ih predlaže, nastavnik ih
# pri pregledu bira nezavisno. Vrednosti bez dijakritika.
DIFFICULTY_VALUES = ("lako", "srednje", "tesko")
BLOOM_LEVELS = ("pamcenje", "razumevanje", "primena", "analiza", "vrednovanje", "stvaranje")
LABEL_FIELDS = {"difficulty": DIFFICULTY_VALUES, "bloom_level": BLOOM_LEVELS}

# Dozvoljena polja u strogom režimu (v3+)
ALLOWED_TOP_LEVEL_FIELDS = {
    "mc": {"question_text", "answers", "difficulty", "bloom_level"},
    "open": {"question_text", "difficulty", "bloom_level"},
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
    """Strogo pravilo (nepoznata polja = greška, oznake obavezne): mc/open od v3
    i svaka verzija generisanja iz skupa (set-v1 ...), koje je nastalo posle v3."""
    if isinstance(prompt_version, str) and prompt_version.strip().startswith("set-"):
        return True
    number = prompt_version_number(prompt_version)
    return number is not None and number >= STRICT_FIELDS_FROM_VERSION


def _fail(message):
    return ValidationResult(passed=False, errors=[message])


def label_error(field_name, value):
    """Poruka greške za vrednost oznake (difficulty / bloom_level), ili None ako je ispravna."""
    allowed = LABEL_FIELDS[field_name]
    if not isinstance(value, str) or value not in allowed:
        return f"Nedostaje ili je nevažeće {field_name} (dozvoljeno: {', '.join(allowed)})"
    return None


def validate(parsed, question_type, expected_answer_count, prompt_version=None,
             require_labels=True) -> ValidationResult:
    """Proverava isparsiran JSON odgovora modela za dati tip pitanja.
    require_labels=False se koristi za nastavnikovu izmenu (edited_text):
    oznake tada nisu obavezne jer nastavnik svoje bira posebno, ali ako
    su prisutne moraju imati dozvoljenu vrednost."""
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

    if strict:
        for field_name in LABEL_FIELDS:
            if field_name not in parsed and not require_labels:
                continue
            error = label_error(field_name, parsed.get(field_name))
            if error:
                return _fail(error)

    return ValidationResult(passed=True)


# --- Generisanje iz skupa pitanja (tačka J) ---
# Odgovor modela: {"questions": [stavka, ...]}; svaka stavka je MC (3-5 odgovora)
# ili otvoreno pitanje, sa istim pravilima kao v3 pitanje. Prazan niz ili više
# od K stavki je greška celog odgovora. Delimično ispravan niz: prihvataju se
# samo ispravne stavke (odbijene se beleže); ceo odgovor je neuspeh tek kad
# nijedna stavka nije ispravna.

SET_MIN_ANSWERS = 3
SET_MAX_ANSWERS = 5
ALLOWED_SET_FIELDS = {"questions"}


@dataclass
class SetItemResult:
    index: int
    question_type: str
    passed: bool
    errors: list
    item: object


@dataclass
class SetValidationResult:
    passed: bool
    errors: list = field(default_factory=list)
    items: list = field(default_factory=list)

    @property
    def accepted(self):
        return [r for r in self.items if r.passed]

    @property
    def rejected(self):
        return [r for r in self.items if not r.passed]


def validate_set_item(item, prompt_version) -> SetItemResult:
    """Jedna stavka niza: MC ako ima "answers", inače otvoreno pitanje."""
    question_type = "mc" if isinstance(item, dict) and "answers" in item else "open"
    if question_type == "mc":
        answers = item.get("answers")
        if not isinstance(answers, list) or not SET_MIN_ANSWERS <= len(answers) <= SET_MAX_ANSWERS:
            return SetItemResult(0, question_type, False,
                                 [f"Očekivano je {SET_MIN_ANSWERS}-{SET_MAX_ANSWERS} ponuđenih odgovora"], item)
        expected = len(answers)
    else:
        expected = 0
    result = validate(item, question_type, expected, prompt_version)
    return SetItemResult(0, question_type, result.passed, result.errors, item)


def validate_set(parsed, k, prompt_version) -> SetValidationResult:
    """Ceo odgovor za skup; passed = bar jedna ispravna stavka."""
    if not isinstance(parsed, dict):
        return SetValidationResult(False, ["Odgovor modela mora biti JSON objekat"])
    if strict_fields_enabled(prompt_version):
        unknown = sorted(set(parsed) - ALLOWED_SET_FIELDS)
        if unknown:
            return SetValidationResult(False, [f"Nepoznata polja u odgovoru: {', '.join(unknown)}"])
    questions = parsed.get("questions")
    if not isinstance(questions, list):
        return SetValidationResult(False, ["Nedostaje niz questions"])
    if not questions:
        return SetValidationResult(False, ["Prazan niz questions"])
    if len(questions) > k:
        return SetValidationResult(False, [f"Vraćeno {len(questions)} pitanja, a traženo najviše {k}"])

    items = []
    for index, item in enumerate(questions):
        result = validate_set_item(item, prompt_version)
        result.index = index
        items.append(result)
    if not any(r.passed for r in items):
        return SetValidationResult(False, [f"Nijedno pitanje nije ispravno (prvo: {items[0].errors[0]})"], items)
    return SetValidationResult(True, [], items)


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
