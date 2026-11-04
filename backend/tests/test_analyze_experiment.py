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
from agreement import cohen_kappa, krippendorff_alpha  # noqa: E402

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

    def run_analyze(self, artifacts, runs=None, evaluations=None, columns=ART_COLUMNS):
        a_path = os.path.join(self.dir, "a.csv")
        write(a_path, columns, artifacts)
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

    def test_accuracy_table_mode_b_only(self):
        a_path = os.path.join(self.dir, "a.csv")
        columns = ["artifact_id", "mode", "provider", "model_name", "status", "accuracy_check_passed"]
        write(a_path, columns, [
            {"artifact_id": i, "mode": mode, "provider": p, "model_name": f"{p}-m", "status": "predlog",
             "accuracy_check_passed": acc}
            for i, (mode, p, acc) in enumerate([("mode_b", "groq", 1), ("mode_b", "groq", 1), ("mode_b", "groq", 0),
                                                ("mode_b", "groq", ""), ("mode_b", "gemini", ""),
                                                ("mode_a", "groq", "")], start=1)])
        with redirect_stdout(io.StringIO()):
            ax.analyze(a_path, out_dir=self.out)
        table = {r["model"]: r for r in ax.read_csv(os.path.join(self.out, "tabela_tacnost.csv"))}
        self.assertEqual(set(table), {"groq/groq-m [mode_b]", "gemini/gemini-m [mode_b]"})  # mode_a se ne broji
        groq = table["groq/groq-m [mode_b]"]
        self.assertEqual((groq["predloga"], groq["prosla"], groq["nije_prosla"], groq["nije_izvrsena"]), ("4", "2", "1", "1"))
        self.assertEqual(groq["stopa_tacnosti"], "0.667")   # 2 / (2 + 1), neizvršena nije u imeniocu
        self.assertIsNone(table["gemini/gemini-m [mode_b]"]["stopa_tacnosti"])  # nijedna izvršena provera
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            self.assertIn("Mehanička provera tačnosti", f.read())

    def write_mode_b(self, a_rows, r_rows):
        a_path, r_path = os.path.join(self.dir, "a.csv"), os.path.join(self.dir, "r.csv")
        write(a_path, ["artifact_id", "mode", "provider", "model_name", "status", "accuracy_check_passed"], [
            {"artifact_id": i, "mode": mode, "provider": p, "model_name": f"{p}-m", "status": "predlog",
             "accuracy_check_passed": acc} for i, (mode, p, acc) in enumerate(a_rows, start=1)])
        write(r_path, ["run_id", "mode", "provider", "model_name", "failure_type", "artifacts"], [
            {"run_id": i, "mode": mode, "provider": p, "model_name": f"{p}-m", "failure_type": failure, "artifacts": n}
            for i, (mode, p, failure, n) in enumerate(r_rows, start=1)])
        with redirect_stdout(io.StringIO()):
            ax.analyze(a_path, r_path, out_dir=self.out)
        return {r["model"]: r for r in ax.read_csv(os.path.join(self.out, "tabela_tacnost.csv"))}

    def test_accuracy_counts_runs_without_proposal(self):
        table = self.write_mode_b(
            [("mode_b", "groq", 1), ("mode_b", "groq", 0), ("mode_b", "groq", ""), ("mode_a", "groq", "")],
            [("mode_b", "groq", "", 1), ("mode_b", "groq", "", 1), ("mode_b", "groq", "", 1),
             ("mode_b", "groq", "invalid_json", 0), ("mode_b", "groq", "schema", 0), ("mode_b", "groq", "empty", 0),
             ("mode_b", "groq", "rate_limit", 0), ("mode_b", "groq", "network", 0),  # padovi servisa se ne broje
             ("mode_a", "groq", "schema", 0)])                                       # drugi režim se ne broji
        groq = table["groq/groq-m [mode_b]"]
        self.assertEqual((groq["bez_predloga"], groq["svih_pokusaja"], groq["stopa_od_svih"]), ("3", "6", "0.167"))
        self.assertEqual(groq["stopa_tacnosti"], "0.5")  # postojeća stopa se ne menja

    def test_accuracy_model_with_only_bad_format_is_listed(self):
        table = self.write_mode_b([("mode_b", "groq", 1)],
                                  [("mode_b", "groq", "", 1), ("mode_b", "gemini", "invalid_json", 0)])
        gemini = table["gemini/gemini-m [mode_b]"]
        self.assertEqual((gemini["predloga"], gemini["bez_predloga"], gemini["svih_pokusaja"]), ("0", "1", "1"))
        self.assertEqual(gemini["stopa_od_svih"], "0.0")
        self.assertIsNone(gemini["stopa_tacnosti"])

    def test_accuracy_columns_keep_names_and_order_without_runs(self):
        a_path = os.path.join(self.dir, "a.csv")
        write(a_path, ["artifact_id", "mode", "provider", "model_name", "status", "accuracy_check_passed"],
              [{"artifact_id": 1, "mode": "mode_b", "provider": "groq", "model_name": "groq-m", "status": "predlog",
                "accuracy_check_passed": 1}])
        with redirect_stdout(io.StringIO()):
            ax.analyze(a_path, out_dir=self.out)
        row = ax.read_csv(os.path.join(self.out, "tabela_tacnost.csv"))[0]
        self.assertEqual(list(row)[:6], ["model", "predloga", "prosla", "nije_prosla", "nije_izvrsena", "stopa_tacnosti"])
        self.assertEqual(list(row)[6:], ["bez_predloga", "svih_pokusaja", "stopa_od_svih"])
        self.assertIsNone(row["bez_predloga"])  # bez --runs se ne zna
        self.assertIsNone(row["stopa_od_svih"])

    def test_no_accuracy_table_for_question_batch(self):
        self.run_analyze([art(1), art(2)])
        self.assertFalse(os.path.exists(os.path.join(self.out, "tabela_tacnost.csv")))
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            self.assertNotIn("Mehanička provera", f.read())

    def test_manual_accuracy_table_mode_b_without_check(self):
        columns = ["artifact_id", "mode", "provider", "model_name", "status", "accuracy_check_passed", "r1_tacnost_resenja"]
        rows = [{"artifact_id": i, "mode": mode, "provider": p, "model_name": f"{p}-m", "status": "prihvaceno",
                 "accuracy_check_passed": acc, "r1_tacnost_resenja": manual}
                for i, (mode, p, acc, manual) in enumerate([
                    ("mode_b", "groq", "", 1), ("mode_b", "groq", "", 1), ("mode_b", "groq", "", 0),
                    ("mode_b", "groq", "", ""),      # još neocenjen
                    ("mode_b", "groq", 1, ""),       # mehanička provera -> nije u ručnoj tabeli
                    ("mode_b", "gemini", "", ""),    # nijedna ručna ocena
                    ("mode_a", "groq", "", "")], start=1)]
        self.run_analyze(rows, columns=columns)
        table = {r["model"]: r for r in ax.read_csv(os.path.join(self.out, "tabela_tacnost_rucna.csv"))}
        self.assertEqual(set(table), {"groq/groq-m [mode_b]", "gemini/gemini-m [mode_b]"})  # mode_a se ne broji
        groq = table["groq/groq-m [mode_b]"]
        self.assertEqual((groq["predloga"], groq["ocenjeno"], groq["tacno"], groq["netacno"]), ("4", "3", "2", "1"))
        self.assertEqual(groq["stopa_tacnosti"], "0.667")   # 2 / 3, neocenjen nije u imeniocu
        self.assertIsNone(table["gemini/gemini-m [mode_b]"]["stopa_tacnosti"])
        mechanical = {r["model"]: r for r in ax.read_csv(os.path.join(self.out, "tabela_tacnost.csv"))}
        self.assertEqual(float(mechanical["groq/groq-m [mode_b]"]["stopa_tacnosti"]), 1.0)   # ručno ocenjeni nisu u imeniocu
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            report = f.read()
        self.assertLess(report.index("Mehanička provera tačnosti"), report.index("Ručna ocena tačnosti"))
        self.assertLess(report.index("Ručna ocena tačnosti"), report.index("Prosečne ocene po kriterijumu"))

    def test_no_manual_accuracy_table_for_question_batch(self):
        self.run_analyze([art(1), art(2)])
        for name in ("tabela_tacnost_rucna.csv", "tabela_saglasnost_rucna.csv"):
            self.assertFalse(os.path.exists(os.path.join(self.out, name)), name)

    def test_manual_accuracy_not_in_scale_tables(self):
        # ocena 0 za tacnost_resenja ranije je rušila kvadratnu kapu (kategorije 1-5)
        columns = ART_COLUMNS + ["accuracy_check_passed", "r1_tacnost_resenja", "r2_tacnost_resenja"]
        rows = [{**art(i, r1=r1, r2=r1), "mode": "mode_b", "accuracy_check_passed": "",
                 "r1_tacnost_resenja": m1, "r2_tacnost_resenja": m2}
                for i, (r1, m1, m2) in enumerate([((5, 4), 0, 0), ((3, 2), 1, 0), ((4, 4), 0, 1)], start=1)]
        result, _ = self.run_analyze(rows, columns=columns)
        ocene = ax.read_csv(os.path.join(self.out, "tabela_ocene.csv"))
        self.assertNotIn("tacnost_resenja", ocene[0])
        self.assertEqual(float(ocene[0]["strucna_tacnost"]), 4.0)
        raspodela = ax.read_csv(os.path.join(self.out, "tabela_raspodela_ocena.csv"))
        self.assertEqual({r["kriterijum"] for r in raspodela}, {"strucna_tacnost", "relevantnost"})
        self.assertFalse(any(r["stavka"] == "tacnost_resenja" for r in result["agreement"]))
        self.assertEqual(self.agreement(result, "nastavnik vs. druga ocena", "strucna_tacnost")["vrsta_kape"],
                         "težinska (kvadratna)")

    def test_manual_accuracy_agreement_percent_and_nominal_kappa(self):
        columns = ART_COLUMNS + ["accuracy_check_passed", "r1_tacnost_resenja", "r2_tacnost_resenja"]
        first, second = [1, 1, 0, 0, 1], [1, 0, 0, 0, 1]
        rows = [{**art(i), "mode": "mode_b", "accuracy_check_passed": "", "r1_tacnost_resenja": m1, "r2_tacnost_resenja": m2}
                for i, (m1, m2) in enumerate(zip(first, second), start=1)]
        rows.append({**art(6), "mode": "mode_b", "accuracy_check_passed": "", "r1_tacnost_resenja": 1,
                     "r2_tacnost_resenja": ""})   # bez druge ocene -> nije par
        result, _ = self.run_analyze(rows, columns=columns)
        k = result["manual_agreement"][0]
        self.assertEqual((k["stavka"], k["parova"], k["slaganje_pct"]), ("tacnost_resenja", 5, 80.0))
        # po = 0.8, pe = 0.6*0.4 + 0.4*0.6 = 0.48 -> (0.8 - 0.48) / 0.52
        self.assertAlmostEqual(k["kapa"], 0.32 / 0.52)
        self.assertAlmostEqual(k["kapa"], cohen_kappa(first, second, categories=(0, 1)))
        self.assertEqual((k["vrsta_kape"], k["vrsta_alfe"]), ("nominalna", "nominalna"))
        self.assertIsNotNone(k["alfa"])
        saved = ax.read_csv(os.path.join(self.out, "tabela_saglasnost_rucna.csv"))[0]
        self.assertEqual(saved["slaganje_pct"], "80.0")
        with open(os.path.join(self.out, "izvestaj.md"), encoding="utf-8") as f:
            self.assertIn("Saglasnost: ručna ocena tačnosti", f.read())

    def test_manual_accuracy_alpha_uses_all_raters_from_evaluations_file(self):
        columns = ART_COLUMNS + ["accuracy_check_passed", "r1_tacnost_resenja", "r2_tacnost_resenja"]
        rows = [{**art(i), "mode": "mode_b", "accuracy_check_passed": "", "r1_tacnost_resenja": v, "r2_tacnost_resenja": v}
                for i, v in [(1, 1), (2, 0)]]
        evaluations = [  # treći ocenjivač se ne slaže na predlogu 2
            {"artifact_id": a, "evaluator": who, "evaluation_round": rnd, "dimension_key": "tacnost_resenja",
             "level": "ordinal", "value": v}
            for a, who, rnd, v in [(1, "u_a", 1, 1), (1, "u_b", 2, 1), (1, "u_c", 2, 1),
                                   (2, "u_a", 1, 0), (2, "u_b", 2, 0), (2, "u_c", 2, 1)]]
        result, _ = self.run_analyze(rows, evaluations=evaluations, columns=columns)
        k = result["manual_agreement"][0]
        self.assertEqual(k["slaganje_pct"], 100.0)   # par nastavnik / prvi drugi ocenjivač se slaže
        self.assertAlmostEqual(k["alfa"], krippendorff_alpha([[1.0, 1.0, 1.0], [0.0, 0.0, 1.0]], "nominal"))
        self.assertLess(k["alfa"], 1.0)              # alfa vidi i trećeg ocenjivača

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
