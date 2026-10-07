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

from question_validation import validate, prompt_version_number, strict_fields_enabled  # noqa: E402


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

    def test_v3_valid_without_extra_fields(self):
        self.assertTrue(validate(mc(), "mc", 3, "mc-v3").passed)


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

    def test_current_prompt_files_are_not_strict(self):
        # Strogo pravilo ne sme biti aktivno dok v3 prompt ne postoji
        import prompt_templates
        for question_type in ("mc", "open"):
            version, _ = prompt_templates._read_template_file(question_type)
            self.assertFalse(strict_fields_enabled(version), version)


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
