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


def build_similar_question_prompt(
    template_text: str,
    original_question_text: str,
    original_answers: list,
    subject_name: str,
) -> str:
    """Popunjava Jinja2 template konkretnim podacima. Vraća gotov prompt string."""
    tpl = Template(template_text)
    return tpl.render(
        subject_name=subject_name,
        original_question_text=original_question_text,
        original_answers=original_answers,
        answer_count=len(original_answers),
    )
