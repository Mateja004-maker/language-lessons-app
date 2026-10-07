"""Testovi razdaljine izmene (python tests/test_edit_distance.py iz backend/). Samo stdlib."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edit_distance import edit_distance, levenshtein, normalize  # noqa: E402


def mc(question, answers):
    return {"question_text": question,
            "answers": [{"answer_text": t, "is_correct": c} for t, c in answers]}


class Levenshtein(unittest.TestCase):
    def test_known_pairs(self):
        for a, b, expected in (("kitten", "sitting", 3), ("flaw", "lawn", 2), ("saturday", "sunday", 3),
                               ("abc", "abc", 0), ("abc", "", 3), ("", "abc", 3), ("", "", 0), ("a", "b", 1)):
            with self.subTest(a=a, b=b):
                self.assertEqual(levenshtein(a, b), expected)
                self.assertEqual(levenshtein(b, a), expected)

    def test_diacritics_and_case_count(self):
        self.assertEqual(levenshtein("cas", "čas"), 1)
        self.assertEqual(levenshtein("Python", "python"), 1)


class Normalize(unittest.TestCase):
    def test_whitespace_and_nfc(self):
        self.assertEqual(normalize("  Koliko   je\n2 + 2?  "), "Koliko je 2 + 2?")
        self.assertEqual(normalize("čas"), "čas")  # razlozeno c + kvacica -> jedan znak
        self.assertEqual(normalize(None), "")


class EditDistance(unittest.TestCase):
    def test_identical_is_zero(self):
        p = mc("Koliko je 2 + 2?", [("3", False), ("4", True)])
        self.assertEqual(edit_distance(p, p), {"question": 0, "answers": 0, "total": 0, "normalized": 0.0})

    def test_only_whitespace_change_is_zero(self):
        a = mc("Koliko je 2 + 2?", [("3", False), ("4", True)])
        b = mc("Koliko  je 2 + 2? ", [(" 3", False), ("4 ", True)])
        self.assertEqual(edit_distance(a, b)["total"], 0)

    def test_question_change(self):
        a = mc("kitten", [("x", True)])
        b = mc("sitting", [("x", True)])
        self.assertEqual(edit_distance(a, b)["question"], 3)
        self.assertEqual(edit_distance(a, b)["answers"], 0)

    def test_changed_correct_answer_counts(self):
        a = mc("P?", [("a", True), ("b", False)])
        b = mc("P?", [("a", False), ("b", True)])
        self.assertEqual(edit_distance(a, b)["answers"], 2)

    def test_empty_edit(self):
        a = mc("abc", [])
        result = edit_distance(a, {"question_text": ""})
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["normalized"], 1.0)

    def test_both_empty(self):
        self.assertEqual(edit_distance({}, {})["normalized"], 0.0)

    def test_open_question(self):
        result = edit_distance({"question_text": "Objasni for petlju."}, {"question_text": "Objasni while petlju."})
        self.assertEqual(result["answers"], 0)
        self.assertGreater(result["question"], 0)

    def test_normalized_bounded(self):
        a = mc("dugacko pitanje koje se skrati", [("x", True)])
        b = mc("k", [("potpuno drugaciji i mnogo duzi odgovor", True)])
        self.assertLessEqual(edit_distance(a, b)["normalized"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
