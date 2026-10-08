"""Testovi mehaničke provere (PASS/FAIL) odgovora modela za slično pitanje.

Pokretanje (iz foldera backend/):
    python tests/test_question_validation.py

Samo stdlib unittest; bez baze, mreže i Flask-a.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from question_validation import (  # noqa: E402
    BLOOM_LEVELS,
    DIFFICULTY_VALUES,
    prompt_version_number,
    strict_fields_enabled,
    validate,
    validate_set,
)

LABELS = {"difficulty": "srednje", "bloom_level": "primena"}


def mc(question_text="Koliko je 2 + 2?", answers=None, **extra):
    if answers is None:
        answers = [
            {"answer_text": "3", "is_correct": False},
            {"answer_text": "4", "is_correct": True},
            {"answer_text": "5", "is_correct": False},
        ]
    return {"question_text": question_text, "answers": answers, **extra}


class PassCases(unittest.TestCase):
    def test_mc_valid(self):
        r = validate(mc(), "mc", 3, "mc-v2")
        self.assertTrue(r.passed)
        self.assertEqual(r.errors, [])

    def test_open_valid(self):
        self.assertTrue(validate({"question_text": "Objasni rekurziju."}, "open", 0, "open-v2").passed)

    def test_v2_ignores_extra_top_level_field(self):
        self.assertTrue(validate(mc(explanation="x"), "mc", 3, "mc-v2").passed)

    def test_v2_ignores_extra_answer_field(self):
        answers = [{"answer_text": "a", "is_correct": True, "why": "x"}, {"answer_text": "b", "is_correct": False}]
        self.assertTrue(validate(mc(answers=answers), "mc", 2, "mc-v2").passed)

    def test_no_version_behaves_like_v2(self):
        self.assertTrue(validate(mc(extra=1), "mc", 3, None).passed)

    def test_v3_valid_with_labels(self):
        self.assertTrue(validate(mc(**LABELS), "mc", 3, "mc-v3").passed)

    def test_v3_open_valid_with_labels(self):
        self.assertTrue(validate({"question_text": "Objasni.", **LABELS}, "open", 0, "open-v3").passed)

    def test_v3_every_allowed_label_value(self):
        for difficulty in DIFFICULTY_VALUES:
            for bloom in BLOOM_LEVELS:
                result = validate(mc(difficulty=difficulty, bloom_level=bloom), "mc", 3, "mc-v3")
                self.assertTrue(result.passed, (difficulty, bloom, result.errors))

    def test_v2_ignores_labels_even_invalid(self):
        self.assertTrue(validate(mc(difficulty="hard", bloom_level=1), "mc", 3, "mc-v2").passed)

    def test_v3_edited_text_without_labels(self):
        # nastavnikova izmena: oznake nisu obavezne (bira ih posebno)
        self.assertTrue(validate(mc(), "mc", 3, "mc-v3", require_labels=False).passed)


class FailCases(unittest.TestCase):
    def assertFail(self, result, message):
        self.assertFalse(result.passed)
        self.assertEqual(result.errors, [message])

    def test_not_object(self):
        self.assertFail(validate([1, 2], "mc", 3), "Odgovor modela mora biti JSON objekat")

    def test_missing_question_text(self):
        self.assertFail(validate({"answers": []}, "mc", 0), "Nedostaje ili je prazan question_text")

    def test_blank_question_text(self):
        self.assertFail(validate(mc(question_text="   "), "mc", 3), "Nedostaje ili je prazan question_text")

    def test_question_text_not_string(self):
        self.assertFail(validate(mc(question_text=5), "mc", 3), "Nedostaje ili je prazan question_text")

    def test_wrong_answer_count(self):
        self.assertFail(validate(mc(), "mc", 4), "Očekivano je tačno 4 ponuđenih odgovora")

    def test_answers_not_list(self):
        self.assertFail(validate(mc(answers="a,b,c"), "mc", 3), "Očekivano je tačno 3 ponuđenih odgovora")

    def test_answer_not_object(self):
        self.assertFail(validate(mc(answers=["a", "b"]), "mc", 2), "Svaki ponuđeni odgovor mora biti JSON objekat")

    def test_empty_answer_text(self):
        answers = [{"answer_text": " ", "is_correct": True}, {"answer_text": "b", "is_correct": False}]
        self.assertFail(validate(mc(answers=answers), "mc", 2), "Ponuđeni odgovor bez teksta")

    def test_is_correct_not_bool(self):
        answers = [{"answer_text": "a", "is_correct": 1}, {"answer_text": "b", "is_correct": False}]
        self.assertFail(validate(mc(answers=answers), "mc", 2), "is_correct mora biti true/false")

    def test_no_correct_answer(self):
        answers = [{"answer_text": "a", "is_correct": False}, {"answer_text": "b", "is_correct": False}]
        self.assertFail(validate(mc(answers=answers), "mc", 2), "Očekivan je tačno jedan tačan odgovor, pronađeno 0")

    def test_two_correct_answers(self):
        answers = [{"answer_text": "a", "is_correct": True}, {"answer_text": "b", "is_correct": True}]
        self.assertFail(validate(mc(answers=answers), "mc", 2), "Očekivan je tačno jedan tačan odgovor, pronađeno 2")

    def test_open_with_answers(self):
        self.assertFail(validate({"question_text": "x", "answers": []}, "open", 0),
                        "Otvoreno pitanje ne sme imati ponuđene odgovore")

    def test_first_error_wins(self):
        # i question_text i odgovori su losi - prijavljuje se prva greska, kao ranije
        self.assertFail(validate(mc(question_text="", answers="x"), "mc", 3), "Nedostaje ili je prazan question_text")

    def test_v3_rejects_extra_top_level_field(self):
        self.assertFail(validate(mc(explanation="x"), "mc", 3, "mc-v3"), "Nepoznata polja u odgovoru: explanation")

    def test_v3_rejects_extra_answer_field(self):
        answers = [{"answer_text": "a", "is_correct": True, "why": "x"}, {"answer_text": "b", "is_correct": False}]
        self.assertFail(validate(mc(answers=answers), "mc", 2, "mc-v3"),
                        "Nepoznata polja u ponuđenom odgovoru: why")

    def test_v3_open_rejects_extra_field(self):
        self.assertFail(validate({"question_text": "x", "note": 1}, "open", 0, "open-v3"),
                        "Nepoznata polja u odgovoru: note")


class V3LabelCases(unittest.TestCase):
    DIFFICULTY_ERROR = "Nedostaje ili je nevažeće difficulty (dozvoljeno: lako, srednje, tesko)"
    BLOOM_ERROR = ("Nedostaje ili je nevažeće bloom_level (dozvoljeno: pamcenje, razumevanje, "
                   "primena, analiza, vrednovanje, stvaranje)")

    def assertFail(self, result, message):
        self.assertFalse(result.passed)
        self.assertEqual(result.errors, [message])

    def test_missing_difficulty(self):
        self.assertFail(validate(mc(bloom_level="primena"), "mc", 3, "mc-v3"), self.DIFFICULTY_ERROR)

    def test_missing_bloom_level(self):
        self.assertFail(validate(mc(difficulty="lako"), "mc", 3, "mc-v3"), self.BLOOM_ERROR)

    def test_missing_both_reports_difficulty_first(self):
        self.assertFail(validate(mc(), "mc", 3, "mc-v3"), self.DIFFICULTY_ERROR)

    def test_invalid_difficulty_values(self):
        for bad in ("teško", "Lako", "hard", "", " lako", None, 1, ["lako"]):
            with self.subTest(bad=bad):
                self.assertFail(validate(mc(difficulty=bad, bloom_level="primena"), "mc", 3, "mc-v3"),
                                self.DIFFICULTY_ERROR)

    def test_invalid_bloom_values(self):
        for bad in ("pamćenje", "Primena", "kreiranje", "remember", "", None, 3):
            with self.subTest(bad=bad):
                self.assertFail(validate(mc(difficulty="lako", bloom_level=bad), "mc", 3, "mc-v3"),
                                self.BLOOM_ERROR)

    def test_open_missing_labels(self):
        self.assertFail(validate({"question_text": "x"}, "open", 0, "open-v3"), self.DIFFICULTY_ERROR)

    def test_edited_text_invalid_label_still_fails(self):
        self.assertFail(validate(mc(difficulty="hard"), "mc", 3, "mc-v3", require_labels=False),
                        self.DIFFICULTY_ERROR)

    def test_format_error_comes_before_label_error(self):
        self.assertFail(validate(mc(question_text=""), "mc", 3, "mc-v3"), "Nedostaje ili je prazan question_text")


def set_mc(n=4, **extra):
    return {"question_text": "Novo MC pitanje", **LABELS,
            "answers": [{"answer_text": f"o{i}", "is_correct": i == 0} for i in range(n)], **extra}


def set_open(**extra):
    return {"question_text": "Novo otvoreno pitanje", **LABELS, **extra}


class SetValidation(unittest.TestCase):
    def test_all_valid(self):
        r = validate_set({"questions": [set_mc(3), set_open(), set_mc(5)]}, 3, "set-v1")
        self.assertTrue(r.passed)
        self.assertEqual(len(r.accepted), 3)
        self.assertEqual([i.question_type for i in r.items], ["mc", "open", "mc"])

    def test_partial_accepts_only_valid_items(self):
        r = validate_set({"questions": [set_mc(4), set_mc(2), set_open(note="x")]}, 3, "set-v1")
        self.assertTrue(r.passed)
        self.assertEqual([i.index for i in r.accepted], [0])
        self.assertEqual([i.index for i in r.rejected], [1, 2])
        self.assertEqual(r.items[1].errors, ["Očekivano je 3-5 ponuđenih odgovora"])
        self.assertEqual(r.items[2].errors, ["Nepoznata polja u odgovoru: note"])

    def test_fewer_than_k_is_allowed(self):
        self.assertTrue(validate_set({"questions": [set_open()]}, 3, "set-v1").passed)

    def test_empty_array(self):
        r = validate_set({"questions": []}, 3, "set-v1")
        self.assertEqual((r.passed, r.errors), (False, ["Prazan niz questions"]))

    def test_more_than_k(self):
        r = validate_set({"questions": [set_open()] * 4}, 3, "set-v1")
        self.assertEqual((r.passed, r.errors), (False, ["Vraćeno 4 pitanja, a traženo najviše 3"]))

    def test_no_valid_item(self):
        r = validate_set({"questions": [set_mc(2), set_mc(6)]}, 3, "set-v1")
        self.assertFalse(r.passed)
        self.assertTrue(r.errors[0].startswith("Nijedno pitanje nije ispravno"))
        self.assertEqual(len(r.rejected), 2)

    def test_structure_errors(self):
        self.assertEqual(validate_set([1], 3, "set-v1").errors, ["Odgovor modela mora biti JSON objekat"])
        self.assertEqual(validate_set({"items": []}, 3, "set-v1").errors, ["Nepoznata polja u odgovoru: items"])
        self.assertEqual(validate_set({}, 3, "set-v1").errors, ["Nedostaje niz questions"])

    def test_item_labels_required_and_mc_rules(self):
        no_labels = {"question_text": "x", "answers": [{"answer_text": f"{i}", "is_correct": i == 0} for i in range(3)]}
        two_correct = set_mc(3)
        two_correct["answers"][1]["is_correct"] = True
        r = validate_set({"questions": [no_labels, two_correct]}, 2, "set-v1")
        self.assertFalse(r.passed)
        self.assertIn("difficulty", r.items[0].errors[0])
        self.assertIn("tačno jedan tačan", r.items[1].errors[0])

    def test_set_versions_are_strict(self):
        self.assertTrue(strict_fields_enabled("set-v1"))
        self.assertTrue(strict_fields_enabled("set-v2"))


class Versions(unittest.TestCase):
    def test_version_numbers(self):
        self.assertEqual(prompt_version_number("mc-v2"), 2)
        self.assertEqual(prompt_version_number("open-v10"), 10)
        self.assertIsNone(prompt_version_number(None))
        self.assertIsNone(prompt_version_number("mc"))

    def test_strict_only_from_v3(self):
        self.assertFalse(strict_fields_enabled("mc-v1"))
        self.assertFalse(strict_fields_enabled("mc-v2"))
        self.assertFalse(strict_fields_enabled(None))
        self.assertTrue(strict_fields_enabled("mc-v3"))

    def test_active_prompt_files_are_v3(self):
        # Aktivni šabloni su v3: strogo pravilo i obavezne oznake važe za nova generisanja
        import prompt_templates
        for question_type, expected in (("mc", "mc-v3"), ("open", "open-v3")):
            version, template = prompt_templates._read_template_file(question_type)
            self.assertEqual(version, expected)
            self.assertTrue(strict_fields_enabled(version))
            self.assertIn('"difficulty"', template)
            self.assertIn('"bloom_level"', template)

    def test_archived_v2_prompts_kept(self):
        import prompt_templates
        for name, expected in (("similar_question_mc_v2.txt", "mc-v2"), ("similar_question_open_v2.txt", "open-v2")):
            text = (prompt_templates.PROMPTS_DIR / name).read_text(encoding="utf-8")
            self.assertEqual(prompt_templates.template_version(text), expected)


class CommandLine(unittest.TestCase):
    def run_cli(self, content, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "question_validation", path, *args],
                cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8",
            )
        finally:
            os.unlink(path)
        return proc.returncode, proc.stdout

    def test_cli_pass(self):
        code, out = self.run_cli(json.dumps(mc()))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "PASS")

    def test_cli_fail_with_reason(self):
        code, out = self.run_cli(json.dumps(mc()), "--answers", "4")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["FAIL", "- Očekivano je tačno 4 ponuđenih odgovora"])

    def test_cli_invalid_json(self):
        code, out = self.run_cli("```json\n{\"question_text\": \"x\"}\n```")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["FAIL", "- Odgovor modela nije validan JSON"])

    def test_cli_v3_extra_field(self):
        code, out = self.run_cli(json.dumps(mc(extra=1)), "--version", "mc-v3")
        self.assertEqual(code, 1)
        self.assertIn("Nepoznata polja u odgovoru: extra", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
