"""
Učitavanje i popunjavanje prompt template-a za AI generisanje pitanja.

Fajlovi u backend/prompts/*.txt su izvor istine za sadržaj (git-praćeni,
human-editable). Svaki fajl na vrhu ima Jinja komentar sa verzijom, npr.
{# version: mc-v1 #}. ensure_prompt_synced() osigurava da za tu (purpose,
version) kombinaciju postoji odgovarajući red u ai_prompts tabeli - ne
prepisuje postojeći red, jer bi to pokvarilo reproducibilnost prošlih
ai_generation_runs zapisa. Ako se sadržaj fajla promeni, version komentar
u fajlu mora da se promeni da bi se napravio nov red.

Ovaj fajl ne poziva ai_provider.generate() niti zna za HTTP/DB detalje
poziva modela - to ostaje na pozivaocu (ruti). ai_provider.py ostaje čist
transportni sloj i ne zna ništa o template-ima.
"""

import re
from pathlib import Path

from jinja2 import Template

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

PURPOSE_SIMILAR_QUESTION = "similar_question"
# Generisanje iz SKUPA pitanja testa (tačka J): jedan poziv -> do K novih pitanja
PURPOSE_SIMILAR_QUESTION_SET = "similar_question_set"
SET_TEMPLATE_FILE = PROMPTS_DIR / "similar_question_set.txt"

# AKTIVNI šabloni (učitavaju se pri generisanju): mc-v3 i open-v3 - model
# vraća i difficulty/bloom_level. Prethodne verzije su sačuvane kao
# similar_question_mc_v2.txt / similar_question_open_v2.txt samo radi istorije
# (ne učitavaju se; njihov tekst je i u ai_prompts, uz stare run-ove).
QUESTION_TYPE_FILES = {
    "mc": PROMPTS_DIR / "similar_question_mc.txt",
    "open": PROMPTS_DIR / "similar_question_open.txt",
}

_VERSION_COMMENT_RE = re.compile(r"{#\s*version:\s*(\S+?)\s*#}")


def detect_question_type(original_answers: list) -> str:
    """MC ako original ima ponuđene odgovore, inače otvoreno pitanje."""
    return "mc" if original_answers else "open"


def _read_template_file(question_type: str) -> tuple[str, str]:
    """Vraća (version, sadržaj_fajla) za dati tip pitanja."""
    path = QUESTION_TYPE_FILES.get(question_type)
    if path is None:
        raise ValueError(f"Nepoznat question_type: {question_type}")

    content = path.read_text(encoding="utf-8")
    match = _VERSION_COMMENT_RE.search(content)
    if not match:
        raise ValueError(
            f"Fajl {path.name} nema '{{# version: ... #}}' komentar na vrhu"
        )

    return match.group(1), content


def template_version(template_text: str):
    """Verzija iz '{# version: ... #}' komentara u šablonu, ili None."""
    match = _VERSION_COMMENT_RE.search(template_text or "")
    return match.group(1) if match else None


def ensure_prompt_synced(conn, question_type: str) -> tuple[int, str]:
    """
    Učitava .txt fajl za dati question_type i osigurava da postoji
    odgovarajući red u ai_prompts (purpose=similar_question, version iz
    fajla). Vraća (prompt_id, template_text).
    """
    version, template_text = _read_template_file(question_type)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM ai_prompts WHERE purpose = %s AND version = %s",
        (PURPOSE_SIMILAR_QUESTION, version),
    )
    row = cursor.fetchone()
    if row:
        cursor.close()
        return row[0], template_text

    cursor.execute(
        """
        INSERT INTO ai_prompts (purpose, version, template)
        VALUES (%s, %s, %s)
        """,
        (PURPOSE_SIMILAR_QUESTION, version, template_text),
    )
    conn.commit()
    prompt_id = cursor.lastrowid
    cursor.close()

    return prompt_id, template_text


def ensure_set_prompt_synced(conn) -> tuple[int, str, str]:
    """Kao ensure_prompt_synced, za šablon generisanja iz skupa.
    Vraća (prompt_id, template_text, version)."""
    content = SET_TEMPLATE_FILE.read_text(encoding="utf-8")
    version = template_version(content)
    if not version:
        raise ValueError(f"Fajl {SET_TEMPLATE_FILE.name} nema '{{# version: ... #}}' komentar na vrhu")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM ai_prompts WHERE purpose = %s AND version = %s",
                       (PURPOSE_SIMILAR_QUESTION_SET, version))
        row = cursor.fetchone()
        if row:
            return row[0], content, version
        cursor.execute("INSERT INTO ai_prompts (purpose, version, template) VALUES (%s, %s, %s)",
                       (PURPOSE_SIMILAR_QUESTION_SET, version, content))
        conn.commit()
        return cursor.lastrowid, content, version
    finally:
        cursor.close()


def build_set_prompt(template_text: str, questions: list, k: int, subject_name: str) -> str:
    """questions: [{'question_text', 'answers': [{'answer_text', 'is_correct'}]}] - ulazni skup."""
    return Template(template_text).render(
        subject_name=subject_name,
        questions=questions,
        input_count=len(questions),
        k=k,
    )


def build_similar_question_prompt(
    template_text: str,
    original_question_text: str,
    original_answers: list,
    subject_name: str,
    area_name: str | None = None,
) -> str:
    """Popunjava Jinja2 template konkretnim podacima. Vraća gotov prompt string."""
    tpl = Template(template_text)
    return tpl.render(
        subject_name=subject_name,
        area_name=area_name,
        original_question_text=original_question_text,
        original_answers=original_answers,
        answer_count=len(original_answers),
    )
