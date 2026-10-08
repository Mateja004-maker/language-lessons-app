"""Testovi saglasnosti ocenjivača (python tests/test_agreement.py iz backend/). Samo stdlib.

Kripendorfova alfa se proverava na objavljenom primeru: K. Krippendorff,
"Computing Krippendorff's Alpha-Reliability" (2011), 4 posmatrača x 12 jedinica
sa nedostajućim vrednostima: nominalna 0.743, ordinalna 0.815, intervalna 0.849.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agreement import cohen_kappa, krippendorff_alpha  # noqa: E402

_ = None
KRIPPENDORFF_2011 = [  # redovi = posmatrači, kolone = jedinice
    [1, 2, 3, 3, 2, 1, 4, 1, 2, _, _, _],
    [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, _, 3],
    [_, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, _],
    [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, _],
]
UNITS_2011 = [list(col) for col in zip(*KRIPPENDORFF_2011)]


class Kappa(unittest.TestCase):
    def test_hand_computed_nominal(self):
        # po = 0.75, pe = 0.5*0.25 + 0.5*0.75 = 0.5 -> (0.75 - 0.5) / 0.5 = 0.5
        self.assertAlmostEqual(cohen_kappa([1, 1, 2, 2], [1, 2, 2, 2]), 0.5)

    def test_perfect_and_reversed_quadratic(self):
        self.assertAlmostEqual(cohen_kappa([1, 2, 3, 4], [1, 2, 3, 4], weights="quadratic"), 1.0)
        # obrnut redosled na 3 kategorije: posmatrano 2/3, ocekivano 1/3 -> 1 - 2 = -1
        self.assertAlmostEqual(cohen_kappa([1, 2, 3], [3, 2, 1], weights="quadratic"), -1.0)

    def test_quadratic_penalizes_far_disagreement_more(self):
        near = cohen_kappa([1, 2, 3, 4, 5], [2, 2, 3, 4, 5], weights="quadratic", categories=range(1, 6))
        far = cohen_kappa([1, 2, 3, 4, 5], [5, 2, 3, 4, 5], weights="quadratic", categories=range(1, 6))
        self.assertGreater(near, far)

    def test_categories_and_missing(self):
        a = ["lako", "srednje", None, "tesko"]
        b = ["lako", "srednje", "lako", "srednje"]
        self.assertAlmostEqual(cohen_kappa(a, b), cohen_kappa(["lako", "srednje", "tesko"], ["lako", "srednje", "srednje"]))

    def test_not_computable_returns_none(self):
        self.assertIsNone(cohen_kappa([], []))
        self.assertIsNone(cohen_kappa([3, 3], [3, 3]))          # jedna kategorija
        self.assertIsNone(cohen_kappa([None, 1], [2, None]))     # nema parova


class Alpha(unittest.TestCase):
    def test_krippendorff_2011_published_values(self):
        self.assertAlmostEqual(krippendorff_alpha(UNITS_2011, "nominal"), 0.743, places=3)
        self.assertAlmostEqual(krippendorff_alpha(UNITS_2011, "ordinal"), 0.815, places=3)
        self.assertAlmostEqual(krippendorff_alpha(UNITS_2011, "interval"), 0.849, places=3)

    def test_hand_computed_two_raters(self):
        # parovi (1,1),(1,2),(2,2),(2,2): Do = 2/8, De = 30/56 -> 1 - 0.25 / 0.5357 = 0.5333
        self.assertAlmostEqual(krippendorff_alpha([[1, 1], [1, 2], [2, 2], [2, 2]]), 1 - 0.25 / (30 / 56), places=4)

    def test_strings_nominal(self):
        units = [["lako", "lako"], ["tesko", "tesko"], ["srednje", "lako"]]
        self.assertIsNotNone(krippendorff_alpha(units, "nominal"))

    def test_not_computable_returns_none(self):
        self.assertIsNone(krippendorff_alpha([[1], [2]]))              # nijedna jedinica sa 2 ocene
        self.assertIsNone(krippendorff_alpha([[3, 3], [3, 3]]))        # bez varijacije
        self.assertIsNone(krippendorff_alpha([]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
