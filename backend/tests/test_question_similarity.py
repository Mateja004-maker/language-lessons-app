"""Testovi provere mogućih duplikata (python tests/test_question_similarity.py iz backend/). Samo stdlib."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from question_similarity import (  # noqa: E402
    DUPLICATE_THRESHOLD,
    find_most_similar,
    is_possible_duplicate,
    normalize,
    pair_score,
    pair_scores,
)


def mc(question, *answers, correct=0):
    return {"question_text": question,
            "answers": [{"answer_text": t, "is_correct": i == correct} for i, t in enumerate(answers)]}


def open_q(question):
    return {"question_text": question}


class Normalization(unittest.TestCase):
    def test_lowercase_diacritics_punctuation_spaces(self):
        self.assertEqual(normalize("  Šta je ĐAK,   čovek?! "), "sta je djak covek")
        self.assertEqual(normalize("Koji <div> i <span>?"), "koji div i span")
        self.assertEqual(normalize("ćao—žabe"), "cao zabe")
        self.assertEqual(normalize(None), "")


class Scores(unittest.TestCase):
    def test_identical(self):
        q = mc("Koja petlja se koristi za poznat broj ponavljanja?", "for", "while", "do")
        self.assertEqual(pair_score(q, q), 1.0)
        self.assertTrue(is_possible_duplicate(pair_score(q, q)))

    def test_near_copy_case_punctuation_diacritics(self):
        a = open_q("Objasni razliku između for i while petlje.")
        b = open_q("objasni RAZLIKU izmedju for i while petlje")
        self.assertEqual(pair_score(a, b), 1.0)

    def test_light_rewording_is_flagged(self):
        a = mc("Koja ključna reč se koristi u Python-u za definisanje funkcije?", "def", "func", "function")
        b = mc("Koja ključna reč se u Python-u koristi za definisanje funkcije?", "def", "func", "function")
        self.assertTrue(is_possible_duplicate(pair_score(a, b)), pair_score(a, b))

    def test_different_question_not_flagged(self):
        a = mc("Koja ključna reč se koristi u Python-u za definisanje funkcije?", "def", "func", "function")
        b = mc("Kog tipa će biti promenljiva x nakon x = 3.14?", "int", "float", "str")
        self.assertLess(pair_score(a, b), 0.5)
        self.assertFalse(is_possible_duplicate(pair_score(a, b)))

    def test_mc_answers_lower_score_for_template_variation(self):
        # isti sablon, druga rec i drugi tacan odgovor: tekst pitanja vrlo slican, sa odgovorima manje
        a = mc("Koji HTML tag se koristi za najveći naslov?", "<h1>", "<h6>", "<p>")
        b = mc("Koji HTML tag se koristi za najmanji naslov?", "<h6>", "<h3>", "<header>")
        scores = pair_scores(a, b)
        self.assertGreater(scores["question"], scores["combined"])
        self.assertEqual(pair_score(a, b), scores["combined"])

    def test_answer_order_does_not_matter(self):
        a = mc("P?", "jedan", "dva", "tri")
        b = mc("P?", "tri", "jedan", "dva", correct=1)
        self.assertEqual(pair_scores(a, b)["combined"], 1.0)

    def test_open_vs_mc_uses_question_text(self):
        a = open_q("Objasni for petlju")
        b = mc("Objasni for petlju", "x", "y")
        self.assertIsNone(pair_scores(a, b)["combined"])
        self.assertEqual(pair_score(a, b), 1.0)


class MostSimilar(unittest.TestCase):
    def test_empty_pool(self):
        self.assertIsNone(find_most_similar(open_q("x"), []))

    def test_picks_highest(self):
        cand = open_q("Objasni razliku između for i while petlje")
        pool = [("bank", 5, open_q("Šta je promenljiva?")),
                ("artifact", 9, open_q("Objasni razliku između for i while petlje!")),
                ("source", 3, open_q("Objasni funkcije"))]
        self.assertEqual(find_most_similar(cand, pool), {"score": 1.0, "source": "artifact", "id": 9})

    def test_tie_prefers_source_then_bank(self):
        cand = open_q("isto pitanje")
        pool = [("artifact", 1, open_q("isto pitanje")), ("bank", 2, open_q("isto pitanje")),
                ("source", 3, open_q("isto pitanje"))]
        self.assertEqual(find_most_similar(cand, pool)["source"], "source")

    def test_threshold_boundary(self):
        self.assertTrue(is_possible_duplicate(DUPLICATE_THRESHOLD))
        self.assertFalse(is_possible_duplicate(DUPLICATE_THRESHOLD - 0.001))
        self.assertFalse(is_possible_duplicate(None))


if __name__ == "__main__":
    unittest.main(verbosity=1)
