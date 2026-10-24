"""
Učitavanje i popunjavanje prompt template-a za generisanje rešenja i
objašnjenja (Andrejev modul). Isti obrazac kao Anđino prompt_templates.py
(zajednička ai_prompts tabela), ali u sopstvenom fajlu/imenskom prostoru -
"Razdvojene odgovornosti u kodu" (Plan integracije, odeljak 3, tačka 4).

purpose je uvek 'explanation' (isto za oba režima) - mode ('mode_a' | 'mode_b')
je taj koji razlikuje, i upisuje se odvojeno u ai_generation_runs.mode.
version u ai_prompts razlikuje šablone (mode_a-v1, mode_b-v1), pod istim
purpose - identičan obrazac kao njeno purpose='similar_question' sa
version='mc-v1'/'open-v1'.
"""

import re
from pathlib import Path

from jinja2 import Template

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

PURPOSE_EXPLANATION = "explanation"

MODE_FILES = {
    "mode_a": PROMPTS_DIR / "explanation_mode_a_v1.txt",
    "mode_b": PROMPTS_DIR / "explanation_mode_b_v1.txt",
}

# mode_b za MC pitanja koristi poseban template (model bira broj ponudjenog
# odgovora umesto da pise Python kod) - explanation_mode_b_v1.txt i dalje
# vazi nepromenjeno za programske/otvorene zadatke.
MODE_B_MC_FILE = PROMPTS_DIR / "explanation_mode_b_mc_v1.txt"

# mode_b za otvoreno pitanje bez test primera (npr. pitanje iz istorije ili
# jezika): generican template bez Python koda. Programski zadatak (ima test
# primere) i dalje dobija explanation_mode_b_v1.txt.
MODE_B_OPEN_FILE = PROMPTS_DIR / "explanation_mode_b_open_v1.txt"

_VERSION_COMMENT_RE = re.compile(r"{#\s*version:\s*(\S+?)\s*#}")


def _template_path(mode: str, question_type: str | None, has_test_cases: bool | None = None) -> Path:
    """Bira .txt fajl za dati mode. mode_b + MC ima poseban template;
    mode_b + otvoreno pitanje bez test primera (has_test_cases nije tacno)
    dobija generican template; mode_a i mode_b za programske zadatke (sa
    test primerima) kao do sad."""
    if mode == "mode_b" and question_type == "mc":
        return MODE_B_MC_FILE
    if mode == "mode_b" and not has_test_cases:
        return MODE_B_OPEN_FILE
    path = MODE_FILES.get(mode)
    if path is None:
        raise ValueError(f"Nepoznat mode: {mode}")
    return path


def _read_template_file(mode: str, question_type: str | None = None,
                        has_test_cases: bool | None = None) -> tuple[str, str]:
    """Vraća (version, sadržaj_fajla) za dati režim ('mode_a' | 'mode_b';
    question_type='mc' bira mode_b MC template, has_test_cases bira izmedju
    programskog i genericnog mode_b template-a)."""
    path = _template_path(mode, question_type, has_test_cases)

    content = path.read_text(encoding="utf-8")
    match = _VERSION_COMMENT_RE.search(content)
    if not match:
        raise ValueError(
            f"Fajl {path.name} nema '{{# version: ... #}}' komentar na vrhu"
        )

    return match.group(1), content


def ensure_prompt_synced(conn, mode: str, question_type: str | None = None,
                         has_test_cases: bool | None = None) -> tuple[int, str]:
    """
    Učitava .txt fajl za dati mode (question_type i has_test_cases su
    relevantni samo za mode_b) i osigurava da postoji odgovarajući red u
    ai_prompts (purpose='explanation', version iz fajla). Vraća (prompt_id, template_text).
    """
    version, template_text = _read_template_file(mode, question_type, has_test_cases)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM ai_prompts WHERE purpose = %s AND version = %s",
        (PURPOSE_EXPLANATION, version),
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
        (PURPOSE_EXPLANATION, version, template_text),
    )
    conn.commit()
    prompt_id = cursor.lastrowid
    cursor.close()

    return prompt_id, template_text


def build_explanation_prompt(
    template_text: str,
    question_text: str,
    subject_name: str | None = None,
    area_name: str | None = None,
    correct_solution: str | None = None,
) -> str:
    """Popunjava Jinja2 template konkretnim podacima. Vraća gotov prompt string.
    correct_solution se koristi samo za mode_a - mode_b template ga ne
    referiše, pa je bezbedno prosledjivati None za mode_b."""
    tpl = Template(template_text)
    return tpl.render(
        question_text=question_text,
        subject_name=subject_name,
        area_name=area_name,
        correct_solution=correct_solution,
    )
