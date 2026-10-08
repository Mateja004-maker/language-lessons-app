"""Testovi skripte tools/analyze_experiment.py na izmišljenim CSV fajlovima
(python tests/test_analyze_experiment.py iz backend/). Bez baze i bez AI poziva.
"""
import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import analyze_experiment as ax  # noqa: E402
from agreement import cohen_kappa  # noqa: E402

ART_COLUMNS = ["batch_id", "artifact_id", "mode", "provider", "model_name", "status", "decider",
               "model_difficulty", "model_bloom_level", "reviewed_difficulty", "reviewed_bloom_level",
               "second_rater", "second_difficulty", "second_bloom_level", "edit_distance_norm",
               "possible_duplicate", "reviewed_duplicate", "r1_strucna_tacnost", "r1_relevantnost",
               "r2_strucna_tacnost", "r2_relevantnost"]


def art(i, provider="groq", status="prihvaceno", md="lako", mb="primena", rd="lako", rb="primena",
        second=True, sd=None, sb=None, r1=(5, 4), r2=None, edit="", dup="0"):
    return {"batch_id": 9, "artifact_id": i, "mode": "single", "provider": provider, "model_name": f"{provider}-m",
            "status": status, "decider": "u_aaa", "model_difficulty": md, "model_bloom_level": mb,
            "reviewed_difficulty": rd, "reviewed_bloom_level": rb, "second_rater": "u_bbb" if second else "",
            "second_difficulty": (sd or rd) if second else "", "second_bloom_level": (sb or rb) if second else "",
            "edit_distance_norm": edit, "possible_duplicate": dup, "reviewed_duplicate": "",
            "r1_strucna_tacnost": r1[0], "r1_relevantnost": r1[1],
            "r2_strucna_tacnost": (r2 or r1)[0] if second else "", "r2_relevantnost": (r2 or r1)[1] if second else ""}


def write(path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


class AnalyzeExperiment(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "izlaz")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_analyze(self, artifacts, runs=None, evaluations=None):
        a_path = os.path.join(self.dir, "a.csv")
        write(a_path, ART_COLUMNS, artifacts)
        r_path = e_path = None
        if runs is not None:
            r_path = os.path.join(self.dir, "r.csv")
            write(r_path, ["run_id", "purpose", "provider", "model_name", "validation_passed", "failure_type",
                           "first_attempt_passed", "format_retries", "response_time_ms"], runs)
        if evaluations is not None:
            e_path = os.path.join(self.dir, "e.csv")
            write(e_path, ["artifact_id", "evaluator", "evaluation_round", "dimension_key", "level", "value"], evaluations)
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = ax.analyze(a_path, r_path, e_path, self.out)
        return result, buf.getvalue()

    def agreement(self, result, comparison, item):
        return next(r for r in result["agreement"] if r["poredjenje"] == comparison and r["stavka"] == item)

    def test_weighted_and_nominal_kappa_match_agreement_module(self):
        rows = [art(1, r1=(5, 4), r2=(4, 4), rd="lako", sd="lako"),
                art(2, r1=(3, 2), r2=(3, 3), rd="srednje", sd="tesko"),
                art(3, r1=(1, 5), r2=(2, 5), rd="tesko", sd="tesko"),
                art(4, r1=(4, 3), r2=(5, 3), rd="srednje", sd="srednje")]
        result, output = self.run_analyze(rows)
        self.assertIsNone(result["message"])
        k = self.agreement(result, "nastavnik vs. druga ocena", "strucna_tacnost")
        self.assertEqual(k["parova"], 4)
        self.assertAlmostEqual(k["kapa"], cohen_kappa([5, 3, 1, 4], [4, 3, 2, 5], weights="quadratic", categories=range(1, 6)))
        self.assertEqual(k["vrsta_kape"], "težinska (kvadratna)")
        self.assertIsNotNone(k["alfa"])
        d = self.agreement(result, "nastavnik vs. druga ocena", "difficulty")
        self.assertAlmostEqual(d["kapa"], cohen_kappa(["lako", "srednje", "tesko", "srednje"],
                                                      ["lako", "tesko", "tesko", "srednje"]))
        self.assertEqual(d["vrsta_kape"], "nominalna")
        self.assertIn("izvestaj.md", output)

    def test_no_second_rating_is_reported_not_crashing(self):
        rows = [art(1, second=False), art(2, second=False, rd="srednje", md="tesko")]
        result, output = self.run_analyze(rows)
        self.assertEqual(result["message"], ax.NO_SECOND_RATING)
        self.assertIn("Nema druge ocene", output)
        self.assertFalse(any(r["poredjenje"] == "nastavnik vs. druga ocena" for r in result["agreement"]))
        # model vs. nastavnik se i dalje računa
        self.assertTrue(any(r["poredjenje"] == "model vs. nastavnik" for r in result["agreement"]))
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            self.assertIn("Nema druge ocene", f.read())

    def test_empty_artifacts_file(self):
        result, output = self.run_analyze([])
        self.assertIn("nema redova", output)
        self.assertTrue(os.path.exists(os.path.join(self.out, "izvestaj.md")))

    def test_decisions_and_duplicates_per_model(self):
        rows = [art(1, status="prihvaceno"), art(2, status="prihvaceno_izmena", edit="0.2"),
                art(3, status="prihvaceno_izmena", edit="0.4"), art(4, status="odbaceno", dup="1"),
                art(5, provider="gemini", status="predlog")]
        self.run_analyze(rows)
        table = {r["model"]: r for r in ax.read_csv(os.path.join(self.out, "tabela_predlozi.csv"))}
        groq = table["groq/groq-m [single]"]
        self.assertEqual((groq["prihvaceno"], groq["prihvaceno_izmena"], groq["odbaceno"]), ("1", "2", "1"))
        self.assertEqual(groq["prihvaceno_pct"], "25.0")
        self.assertEqual(float(groq["prosek_razdaljine_norm"]), 0.3)
        self.assertEqual(groq["mogucih_duplikata"], "1")
        self.assertIsNone(table["gemini/gemini-m [single]"]["prihvaceno_pct"])  # nijedna odluka

    def test_score_distribution_per_model_and_dimension(self):
        rows = [art(1, r1=(5, 4)), art(2, r1=(5, 2)), art(3, r1=(3, 4)), art(4, r1=(1, "")),
                art(5, provider="gemini", r1=(2, 2))]
        self.run_analyze(rows)
        table = {(r["model"], r["kriterijum"]): r for r in ax.read_csv(os.path.join(self.out, "tabela_raspodela_ocena.csv"))}
        t = table[("groq/groq-m [single]", "strucna_tacnost")]
        self.assertEqual([t[f"ocena_{v}"] for v in range(1, 6)], ["1", "0", "1", "0", "2"])
        self.assertEqual((t["broj_ocena"], t["prosek"]), ("4", "3.5"))
        r = table[("groq/groq-m [single]", "relevantnost")]      # prazna ocena se ne broji
        self.assertEqual([r[f"ocena_{v}"] for v in range(1, 6)], ["0", "1", "0", "2", "0"])
        self.assertEqual(r["broj_ocena"], "3")
        g = table[("gemini/gemini-m [single]", "strucna_tacnost")]
        self.assertEqual((g["ocena_2"], g["broj_ocena"]), ("1", "1"))
        self.assertEqual(len(table), 4)                         # 2 modela x 2 kriterijuma
        self.assertTrue(os.path.exists(os.path.join(self.out, "grafikon_raspodela_ocena.svg")))
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            self.assertIn("Raspodela ocena po kriterijumu", f.read())

    def test_runs_table_failures_and_median(self):
        runs = [{"run_id": 1, "purpose": "similar_question", "provider": "groq", "model_name": "g",
                 "validation_passed": 1, "failure_type": "", "first_attempt_passed": 1, "format_retries": 0, "response_time_ms": 100},
                {"run_id": 2, "purpose": "similar_question", "provider": "groq", "model_name": "g",
                 "validation_passed": 1, "failure_type": "", "first_attempt_passed": 0, "format_retries": 1, "response_time_ms": 300},
                {"run_id": 3, "purpose": "similar_question", "provider": "groq", "model_name": "g",
                 "validation_passed": 0, "failure_type": "rate_limit", "first_attempt_passed": "", "format_retries": 0, "response_time_ms": 1000},
                {"run_id": 4, "purpose": "similar_question", "provider": "groq", "model_name": "g",
                 "validation_passed": 0, "failure_type": "schema", "first_attempt_passed": 0, "format_retries": 1, "response_time_ms": 200}]
        self.run_analyze([art(1)], runs=runs)
        row = ax.read_csv(os.path.join(self.out, "tabela_pozivi.csv"))[0]
        self.assertEqual(row["model"], "groq/g [single]")
        self.assertEqual((row["pokusaja"], row["uspesnih"], row["ponovni_zahtev"]), ("4", "2", "2"))
        self.assertEqual((row["pad_rate_limit"], row["pad_schema"], row["pad_network"]), ("1", "1", "0"))
        self.assertEqual(row["formalno_iz_prve_pct"], "33.3")   # 1 od 3 poziva na koje je model odgovorio
        self.assertEqual((row["prosek_ms"], row["medijana_ms"]), ("400", "250"))
        self.assertTrue(os.path.exists(os.path.join(self.out, "grafikon_padovi.svg")))

    def test_alpha_uses_all_raters_from_evaluations_file(self):
        rows = [art(1, r1=(5, 4), r2=(5, 4)), art(2, r1=(2, 4), r2=(2, 4))]
        evaluations = [  # treći ocenjivač se ne slaže na predlogu 2
            {"artifact_id": a, "evaluator": who, "evaluation_round": rnd, "dimension_key": "strucna_tacnost",
             "level": "ordinal", "value": v}
            for a, who, rnd, v in [(1, "u_a", 1, 5), (1, "u_b", 2, 5), (1, "u_c", 2, 5),
                                   (2, "u_a", 1, 2), (2, "u_b", 2, 2), (2, "u_c", 2, 5)]]
        result, _ = self.run_analyze(rows, evaluations=evaluations)
        k = self.agreement(result, "nastavnik vs. druga ocena", "strucna_tacnost")
        self.assertAlmostEqual(k["kapa"], 1.0)      # par nastavnik / prvi drugi ocenjivač se slaže
        self.assertLess(k["alfa"], 1.0)             # alfa vidi i trećeg ocenjivača

    def test_outputs_and_cli(self):
        a_path = os.path.join(self.dir, "a.csv")
        write(a_path, ART_COLUMNS, [art(1), art(2, provider="gemini", rd="tesko", sd="srednje")])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ax.main(["--artifacts", a_path, "--out", self.out]), 0)
        for name in ("izvestaj.md", "tabela_predlozi.csv", "tabela_ocene.csv", "tabela_saglasnost.csv",
                     "grafikon_odluke.svg", "grafikon_ocene.svg"):
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        with open(os.path.join(self.out, "grafikon_odluke.svg"), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("<svg"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
