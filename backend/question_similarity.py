"""
Provera mogućih duplikata AI predloga pitanja (tačka C). Bez Flask-a i baze.

Normalizacija: mala slova, bez dijakritika (đ -> dj), bez interpunkcije,
sažeti razmaci. Sličnost je difflib.SequenceMatcher ratio (0..1):
  - question: samo tekst pitanja;
  - combined: za MC tekst pitanja zajedno sa ponuđenim odgovorima (odgovori
    sortirani, da redosled ne utiče).
Ocena para (score) je opisana u pair_score(). Predlog je "mogući duplikat"
kada je najveća ocena >= DUPLICATE_THRESHOLD.
"""

import re
import unicodedata
from difflib import SequenceMatcher

DUPLICATE_THRESHOLD = 0.85

# Redosled važi i kao prednost pri jednakoj oceni
SOURCE_ORDER = ("source", "bank", "artifact")

_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_SPECIAL = str.maketrans({"đ": "dj", "Đ": "dj", "ß": "ss", "æ": "ae", "ø": "o"})


def normalize(text) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text.translate(_SPECIAL))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return _NON_ALNUM_RE.sub(" ", text).strip()


def _answers(payload):
    answers = (payload or {}).get("answers") or []
    return sorted(normalize(a.get("answer_text")) for a in answers if isinstance(a, dict))


def ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def pair_scores(candidate, other) -> dict:
    """{'question': ratio teksta pitanja, 'combined': ratio pitanja + odgovora ili None}."""
    q_candidate = normalize((candidate or {}).get("question_text"))
    q_other = normalize((other or {}).get("question_text"))
    result = {"question": ratio(q_candidate, q_other), "combined": None}
    a_candidate, a_other = _answers(candidate), _answers(other)
    if a_candidate and a_other:
        result["combined"] = ratio(" ".join([q_candidate, *a_candidate]), " ".join([q_other, *a_other]))
    return result


def pair_score(candidate, other) -> float:
    """Ocena para: za dva MC pitanja combined (pitanje + odgovori), inače tekst pitanja."""
    scores = pair_scores(candidate, other)
    return scores["combined"] if scores["combined"] is not None else scores["question"]


def find_most_similar(candidate, pool):
    """pool: iterable (source, id, payload); source iz SOURCE_ORDER.
    Vraća {'score', 'source', 'id'} najsličnijeg ili None za prazan pool."""
    best = None
    for source, item_id, payload in sorted(pool, key=lambda item: (SOURCE_ORDER.index(item[0]), item[1])):
        score = round(pair_score(candidate, payload), 3)
        if best is None or score > best["score"]:
            best = {"score": score, "source": source, "id": item_id}
    return best


def is_possible_duplicate(score) -> bool:
    return score is not None and float(score) >= DUPLICATE_THRESHOLD
