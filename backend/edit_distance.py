"""
Razdaljina izmene (Levenshtein) između predloga modela i nastavnikove izmene
- mera obima nastavničke intervencije za "prihvaceno_izmena" (tačka B).
Bez Flask-a, baze i spoljnih zavisnosti.

Normalizacija je namerno blaga (Unicode NFC, sažeti razmaci, bez razmaka na
krajevima): velika/mala slova, dijakritici i interpunkcija se NE uklanjaju,
jer je i njihova ispravka stvarna intervencija nastavnika (jezička ispravnost).

Pitanje i odgovori se mere odvojeno. Odgovori se spajaju redom, svaki u svom
redu sa oznakom tačnosti ("+ " tačan, "- " netačan), pa se računa i promena
tačnog odgovora. Ukupno = pitanje + odgovori; normalizovano = ukupno podeljeno
zbirom dužina dužeg teksta u svakom delu (uvek između 0 i 1).
"""

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text) -> str:
    if not isinstance(text, str):
        return ""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def levenshtein(a: str, b: str) -> int:
    """Broj umetanja, brisanja i zamena znakova da se a pretvori u b."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,                        # brisanje
                current[j - 1] + 1,                     # umetanje
                previous[j - 1] + (char_a != char_b),   # zamena
            ))
        previous = current
    return previous[-1]


def answers_text(payload) -> str:
    answers = (payload or {}).get("answers") or []
    return "\n".join(
        f"{'+' if a.get('is_correct') else '-'} {normalize(a.get('answer_text'))}"
        for a in answers if isinstance(a, dict)
    )


def edit_distance(original, edited) -> dict:
    """Razdaljina između original_text i edited_text predloga (dict-ovi)."""
    q_orig = normalize((original or {}).get("question_text"))
    q_edit = normalize((edited or {}).get("question_text"))
    a_orig = answers_text(original)
    a_edit = answers_text(edited)

    question = levenshtein(q_orig, q_edit)
    answers = levenshtein(a_orig, a_edit)
    total = question + answers
    length = max(len(q_orig), len(q_edit)) + max(len(a_orig), len(a_edit))
    return {
        "question": question,
        "answers": answers,
        "total": total,
        "normalized": round(total / length, 4) if length else 0.0,
    }
