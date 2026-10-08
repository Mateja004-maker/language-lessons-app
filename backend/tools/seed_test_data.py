"""Minimalni izmišljeni podaci za testove na PRAZNOJ probnoj bazi.

Koristi ga tools/test_clean_db.py posle db/schema.sql + db/reference_data.sql.
Ne pokreće se nad pravom bazom: seed() odbija rad ako ime baze ne završava
na "_test" ili ako baza već ima korisnike.

Šta pravi (sve izmišljeno, nalozi bez lozinke - password_hash '!' ne može da se prijavi):
  - korisnike ADMIN, TEACHER, STUDENT (@example.invalid);
  - predmete "Osnove programiranja" i "Matematika"; nastavnik i student
    dobijaju "Osnove programiranja";
  - banku pitanja: 5 MC pitanja (4 odgovora, tačno jedan tačan) i 1 otvoreno
    u "Osnove programiranja", 1 MC pitanje (3 odgovora) u "Matematika";
  - ai_models za sve provajdere iz ai_provider.DEFAULT_MODELS;
  - ai_prompts iz fajlova backend/prompts/ (aktivni i arhivirani v2, set,
    objašnjenja), sa verzijom iz zaglavlja fajla;
  - nekoliko AI predloga BEZ serije (kao razvojne probe; ne ulaze u izvoz ni u
    upite eksperimenta): pitanja u statusima predlog / prihvaceno / odbaceno i
    objašnjenja predlog / prihvaceno - za proveru slepog pregleda postojećih predloga.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

PROMPT_FILES = {  # fajl -> purpose
    "similar_question_mc.txt": "similar_question",
    "similar_question_open.txt": "similar_question",
    "similar_question_mc_v2.txt": "similar_question",
    "similar_question_open_v2.txt": "similar_question",
    "similar_question_set.txt": "similar_question_set",
    "explanation_mode_a_v1.txt": "explanation",
    "explanation_mode_b_v1.txt": "explanation",
}

QUESTIONS = [  # (predmet, tekst, odgovori; prvi je tačan)
    ("OP", "Koji tip podatka u Pythonu čuva ceo broj?", ["int", "str", "list", "dict"]),
    ("OP", "Šta ispisuje print(2 ** 3)?", ["8", "6", "9", "5"]),
    ("OP", "Kojom ključnom reči se definiše funkcija u Pythonu?", ["def", "func", "lambda", "fn"]),
    ("OP", "Koliko puta se izvršava telo petlje for i in range(3)?", ["3", "2", "4", "0"]),
    ("OP", "Koji operator proverava jednakost dve vrednosti?", ["==", "=", "!=", ":="]),
    ("OP", "Objasnite razliku između liste i torke u Pythonu.", []),
    ("MAT", "Koliko je 7 · 8?", ["56", "54", "64"]),
]


class SeedError(Exception):
    pass


def _lookup(cur, sql, params):
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        raise SeedError(f"Seed: nedostaje {params}")
    return row[0]


def seed_proposals(cur, ids):
    """AI predlozi bez serije: 4 pitanja i 2 objašnjenja za prvo pitanje predmeta OP."""
    import json

    source = ids["questions"][0]
    model = _lookup(cur, "SELECT id FROM ai_models WHERE provider = %s", ("groq",))
    created = 0
    for purpose, mode, version, items in (
        ("similar_question", None, "mc-v3", [
            ("predlog", None), ("predlog", None), ("prihvaceno", None), ("odbaceno", "Izmišljen razlog odbacivanja")]),
        ("explanation", "mode_a", "mode_a-v1", [("predlog", None), ("prihvaceno", None)]),
    ):
        prompt = _lookup(cur, "SELECT id FROM ai_prompts WHERE version = %s", (version,))
        for i, (status, reason) in enumerate(items):
            if purpose == "similar_question":
                body = {"question_text": f"Izmišljeni predlog pitanja {i + 1}", "difficulty": "lako", "bloom_level": "pamcenje",
                        "answers": [{"answer_text": f"o{j}", "is_correct": j == 0} for j in range(4)]}
            else:
                body = {"explanation": f"Izmišljeno objašnjenje {i + 1}."}
            cur.execute("""
                INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, mode, source_question_id, params_used,
                       raw_response, parsed_result, validation_passed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
            """, (model, prompt, purpose, mode, source, json.dumps({"temperature": 0.7}), json.dumps(body), json.dumps(body)))
            run = cur.lastrowid
            decided = status != "predlog"
            cur.execute("""
                INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text, rejection_reason,
                       reviewed_by, reviewed_at, model_difficulty, model_bloom_level, reviewed_difficulty, reviewed_bloom_level)
                VALUES (%s, %s, %s, %s, %s, %s, IF(%s, NOW(), NULL), %s, %s, %s, %s)
            """, (run, "question" if purpose == "similar_question" else "explanation", status, json.dumps(body), reason,
                  ids["teacher"] if decided else None, decided,
                  *(("lako", "pamcenje") if purpose == "similar_question" else (None, None)),
                  *(("lako", "pamcenje") if purpose == "similar_question" and decided else (None, None))))
            created += 1
    return created


def seed(conn, out=print):
    """Upisuje podatke u bazu na koju je conn povezan. Vraća rečnik sa id-jevima."""
    import ai_provider
    import prompt_templates

    cur = conn.cursor()
    cur.execute("SELECT DATABASE()")
    database = cur.fetchone()[0] or ""
    if not database.endswith("_test"):
        raise SeedError(f"Odbijeno: baza '{database}' ne završava na _test")
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0]:
        raise SeedError(f"Odbijeno: baza '{database}' već ima korisnike")

    ids = {}
    for role_id, role in ((1, "admin"), (2, "teacher"), (3, "student")):
        cur.execute("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', %s, %s, 1)",
                    (f"seed-{role}@example.invalid", role_id, f"Seed {role}"))
        ids[role] = cur.lastrowid
    for code, name in (("OP", "Osnove programiranja"), ("MAT", "Matematika")):
        cur.execute("INSERT INTO subjects (code, name) VALUES (%s, %s)", (code, name))
        ids[code] = cur.lastrowid
    cur.execute("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (ids["teacher"], ids["OP"]))
    cur.execute("INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)", (ids["student"], ids["OP"]))

    ids["questions"] = []
    for code, text, answers in QUESTIONS:
        cur.execute("INSERT INTO exam_questions (subject_id, question_text) VALUES (%s, %s)", (ids[code], text))
        qid = cur.lastrowid
        ids["questions"].append(qid)
        for i, answer in enumerate(answers):
            cur.execute("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)",
                        (qid, answer, 1 if i == 0 else 0))

    for provider, model_name in ai_provider.DEFAULT_MODELS.items():
        cur.execute("INSERT INTO ai_models (provider, model_name) VALUES (%s, %s)", (provider, model_name))

    for file_name, purpose in PROMPT_FILES.items():
        text = (prompt_templates.PROMPTS_DIR / file_name).read_text(encoding="utf-8")
        version = prompt_templates.template_version(text)
        if not version:
            raise SeedError(f"{file_name} nema '{{# version: ... #}}' zaglavlje")
        cur.execute("INSERT INTO ai_prompts (purpose, version, template) VALUES (%s, %s, %s)", (purpose, version, text))

    artifacts = seed_proposals(cur, ids)

    conn.commit()
    cur.close()
    out(f"Seed u '{database}': 3 korisnika, 2 predmeta, {len(QUESTIONS)} pitanja, "
        f"{len(ai_provider.DEFAULT_MODELS)} modela, {len(PROMPT_FILES)} promptova, {artifacts} AI predloga.")
    return ids


if __name__ == "__main__":
    print("Pokreće se preko tools/test_clean_db.py (pravi probnu bazu i poziva seed).")
    sys.exit(2)
