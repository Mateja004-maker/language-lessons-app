"""Analiza eksperimenta iz CSV izvoza (tačka G): tabele, grafikoni i saglasnost ocenjivača.

    python tools/analyze_experiment.py --artifacts serija_1_artifacts.csv
        [--runs serija_1_runs.csv] [--evaluations serija_1_evaluations.csv] [--out analiza_serija_1]

(iz foldera backend/). Ulaz su CSV fajlovi iz GET /api/evaluation-batches/<id>/export.csv
(kind=artifacts, runs, evaluations). Skripta NE čita bazu - brojevi u radu se uvek
dobijaju iz istih izvornih fajlova. Bez spoljnih biblioteka (grafikoni su SVG).

Izlaz u --out: izvestaj.md (sve tabele), tabela_*.csv i grafikon_*.svg.
Po modelu (provajder/model [režim]):
  - pozivi (ako je dat --runs): uspeh, prolaz iz prve, ponovni zahtev, vrste pada,
    prosečno i medijansko vreme;
  - predlozi: odluke u %, razdaljina izmene, duplikati, raspodela težine i Bluma
    (model i nastavnik);
  - prosečne ocene po kriterijumu (nastavnik koji odlučuje, runda 1) i raspodela
    ocena po kriterijumu (koliko ocena 1, 2, 3, 4, 5);
  - saglasnost: težinska (kvadratna) Koenova kapa nastavnik vs. druga ocena po
    kriterijumu, nominalna kapa za težinu i Blumov nivo, Kripendorfova alfa
    (ordinalna za ocene, nominalna za kategorije; iz --evaluations ako je dat, uz sve
    ocenjivače), i saglasnost modela sa nastavnikom za kategorije.
Ako druge ocene nema, to se jasno ispiše, a ostatak analize se uradi.
"""
import argparse
import csv
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agreement import cohen_kappa, krippendorff_alpha  # noqa: E402

DECISIONS = ("prihvaceno", "prihvaceno_izmena", "odbaceno", "predlog")
DIFFICULTY = ("lako", "srednje", "tesko")
BLOOM = ("pamcenje", "razumevanje", "primena", "analiza", "vrednovanje", "stvaranje")
FAILURES = ("network", "http_4xx", "rate_limit", "http_5xx", "empty", "invalid_json", "schema")
COLORS = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#999999")
NO_SECOND_RATING = "Nema druge ocene u ovim podacima - saglasnost ocenjivača (kapa, alfa) se ne računa."


# ---------- citanje ----------

def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]


def num(value):
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def group_key(row):
    mode = row.get("mode") or {"similar_question": "single", "similar_question_set": "set"}.get(row.get("purpose"), row.get("purpose"))
    return f"{row.get('provider')}/{row.get('model_name')} [{mode}]"


def pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def fmt(value, digits=3):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else str(round(value))
    return str(value)


# ---------- tabele ----------

def runs_table(runs):
    groups = defaultdict(list)
    for r in runs:
        groups[group_key(r)].append(r)
    columns = ["model", "pokusaja", "uspesnih", "uspeh_pct", "iz_prve_pct", "ponovni_zahtev", "formalno_iz_prve_pct",
               *[f"pad_{f}" for f in FAILURES], "prosek_ms", "medijana_ms"]
    rows = []
    for key, items in sorted(groups.items()):
        answered = [r for r in items if r.get("failure_type") in (None, "empty", "invalid_json", "schema")]
        times = [num(r.get("response_time_ms")) for r in items if num(r.get("response_time_ms")) is not None]
        failures = Counter(r.get("failure_type") for r in items)
        rows.append({
            "model": key, "pokusaja": len(items),
            "uspesnih": sum(r.get("validation_passed") == "1" for r in items),
            "uspeh_pct": pct(sum(r.get("validation_passed") == "1" for r in items), len(items)),
            "iz_prve_pct": pct(sum(r.get("first_attempt_passed") == "1" for r in items), len(items)),
            "ponovni_zahtev": sum((num(r.get("format_retries")) or 0) > 0 for r in items),
            "formalno_iz_prve_pct": pct(sum(r.get("first_attempt_passed") == "1" for r in answered), len(answered)),
            **{f"pad_{f}": failures.get(f, 0) for f in FAILURES},
            "prosek_ms": round(statistics.mean(times)) if times else None,
            "medijana_ms": round(statistics.median(times)) if times else None,
        })
    return columns, rows


def artifacts_table(artifacts):
    groups = defaultdict(list)
    for a in artifacts:
        groups[group_key(a)].append(a)
    columns = ["model", "predloga", *DECISIONS, "prihvaceno_pct", "izmena_pct", "odbaceno_pct", "prosek_razdaljine_norm",
               "mogucih_duplikata", "potvrdjenih_duplikata",
               *[f"model_{d}" for d in DIFFICULTY], *[f"nast_{d}" for d in DIFFICULTY],
               *[f"model_{b}" for b in BLOOM], *[f"nast_{b}" for b in BLOOM]]
    rows = []
    for key, items in sorted(groups.items()):
        status = Counter(a.get("status") for a in items)
        decided = sum(status[s] for s in DECISIONS[:3])
        edits = [num(a.get("edit_distance_norm")) for a in items
                 if a.get("status") == "prihvaceno_izmena" and num(a.get("edit_distance_norm")) is not None]
        rows.append({
            "model": key, "predloga": len(items), **{s: status.get(s, 0) for s in DECISIONS},
            "prihvaceno_pct": pct(status["prihvaceno"], decided), "izmena_pct": pct(status["prihvaceno_izmena"], decided),
            "odbaceno_pct": pct(status["odbaceno"], decided),
            "prosek_razdaljine_norm": round(statistics.mean(edits), 4) if edits else None,
            "mogucih_duplikata": sum(a.get("possible_duplicate") == "1" for a in items),
            "potvrdjenih_duplikata": sum(a.get("reviewed_duplicate") == "1" for a in items),
            **{f"model_{d}": sum(a.get("model_difficulty") == d for a in items) for d in DIFFICULTY},
            **{f"nast_{d}": sum(a.get("reviewed_difficulty") == d for a in items) for d in DIFFICULTY},
            **{f"model_{b}": sum(a.get("model_bloom_level") == b for a in items) for b in BLOOM},
            **{f"nast_{b}": sum(a.get("reviewed_bloom_level") == b for a in items) for b in BLOOM},
        })
    return columns, rows


def dimensions(artifacts):
    return [c[3:] for c in (artifacts[0].keys() if artifacts else []) if c.startswith("r1_")]


def scores_table(artifacts):
    dims = dimensions(artifacts)
    groups = defaultdict(list)
    for a in artifacts:
        groups[group_key(a)].append(a)
    columns = ["model", *dims]
    rows = []
    for key, items in sorted(groups.items()):
        row = {"model": key}
        for d in dims:
            values = [num(a.get(f"r1_{d}")) for a in items if num(a.get(f"r1_{d}")) is not None]
            row[d] = round(statistics.mean(values), 2) if values else None
        rows.append(row)
    return columns, rows


SCALE = (1, 2, 3, 4, 5)


def score_distribution_table(artifacts):
    """Raspodela ocena (runda 1, nastavnik koji odlučuje) po modelu i kriterijumu."""
    dims = dimensions(artifacts)
    groups = defaultdict(list)
    for a in artifacts:
        groups[group_key(a)].append(a)
    columns = ["model", "kriterijum", "broj_ocena", *[f"ocena_{v}" for v in SCALE], "prosek"]
    rows = []
    for key, items in sorted(groups.items()):
        for d in dims:
            values = [num(a.get(f"r1_{d}")) for a in items if num(a.get(f"r1_{d}")) is not None]
            counts = Counter(int(v) for v in values)
            rows.append({"model": key, "kriterijum": d, "broj_ocena": len(values),
                         **{f"ocena_{v}": counts.get(v, 0) for v in SCALE},
                         "prosek": round(statistics.mean(values), 2) if values else None,
                         "red": f"{key} · {d}"})
    return columns, rows


def agreement_table(artifacts, evaluations):
    """Saglasnost: (kolone, redovi, poruka ili None)."""
    dims = dimensions(artifacts)
    columns = ["poredjenje", "stavka", "parova", "kapa", "vrsta_kape", "alfa", "vrsta_alfe"]
    rows = []
    has_second = any(a.get("second_rater") for a in artifacts)

    eval_units = defaultdict(lambda: defaultdict(list))  # dimenzija -> predlog -> vrednosti svih ocenjivača
    for e in evaluations or []:
        value = e.get("value")
        if value is None:
            continue
        eval_units[e["dimension_key"]][e["artifact_id"]].append(num(value) if e.get("level") == "ordinal" else value)

    def alpha_for(key, pairs, level):
        units = list(eval_units[key].values()) if key in eval_units else [list(p) for p in pairs]
        return krippendorff_alpha(units, level)

    if has_second:
        for d in dims:
            pairs = [(num(a.get(f"r1_{d}")), num(a.get(f"r2_{d}"))) for a in artifacts]
            pairs = [p for p in pairs if None not in p]
            rows.append({"poredjenje": "nastavnik vs. druga ocena", "stavka": d, "parova": len(pairs),
                         "kapa": cohen_kappa(*zip(*pairs), weights="quadratic", categories=range(1, 6)) if pairs else None,
                         "vrsta_kape": "težinska (kvadratna)", "alfa": alpha_for(d, pairs, "ordinal"), "vrsta_alfe": "ordinalna"})
        for field, cats in (("difficulty", DIFFICULTY), ("bloom_level", BLOOM)):
            pairs = [(a.get(f"reviewed_{field}"), a.get(f"second_{field}")) for a in artifacts]
            pairs = [p for p in pairs if None not in p]
            rows.append({"poredjenje": "nastavnik vs. druga ocena", "stavka": field, "parova": len(pairs),
                         "kapa": cohen_kappa(*zip(*pairs), categories=cats) if pairs else None,
                         "vrsta_kape": "nominalna", "alfa": alpha_for(f"label_{field}", pairs, "nominal"),
                         "vrsta_alfe": "nominalna"})
    for field, cats in (("difficulty", DIFFICULTY), ("bloom_level", BLOOM)):
        pairs = [(a.get(f"model_{field}"), a.get(f"reviewed_{field}")) for a in artifacts]
        pairs = [p for p in pairs if None not in p]
        rows.append({"poredjenje": "model vs. nastavnik", "stavka": field, "parova": len(pairs),
                     "kapa": cohen_kappa(*zip(*pairs), categories=cats) if pairs else None,
                     "vrsta_kape": "nominalna", "alfa": krippendorff_alpha([list(p) for p in pairs], "nominal") if pairs else None,
                     "vrsta_alfe": "nominalna"})
    return columns, rows, (None if has_second else NO_SECOND_RATING)


# ---------- izlaz ----------

def write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def markdown(columns, rows):
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        lines.append("| " + " | ".join(fmt(row.get(c)) for c in columns) + " |")
    return "\n".join(lines)


def _escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_stacked(path, title, rows, segments, label="model", left=260):
    """Horizontalni složeni stubci (udeo svakog segmenta u redu)."""
    width, bar_h, gap = 500 + left, 22, 12
    height = 70 + len(rows) * (bar_h + gap) + 30
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
             f'<rect width="100%" height="100%" fill="white"/><text x="10" y="22" font-size="15" font-weight="bold">{_escape(title)}</text>']
    for i, name in enumerate(segments):
        parts.append(f'<rect x="{10 + i * 120}" y="34" width="12" height="12" fill="{COLORS[i % len(COLORS)]}"/>'
                     f'<text x="{26 + i * 120}" y="45">{_escape(name)}</text>')
    for r_i, row in enumerate(rows):
        y = 60 + r_i * (bar_h + gap)
        total = sum(row.get(s) or 0 for s in segments)
        parts.append(f'<text x="{left - 8}" y="{y + 15}" text-anchor="end">{_escape(row[label])}</text>')
        x = left
        for s_i, s in enumerate(segments):
            value = row.get(s) or 0
            w = (width - left - 20) * value / total if total else 0
            if w:
                parts.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{COLORS[s_i % len(COLORS)]}">'
                             f'<title>{_escape(s)}: {value}</title></rect>')
            x += w
        if not total:
            parts.append(f'<text x="{left}" y="{y + 15}" fill="#666">nema podataka</text>')
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def svg_grouped(path, title, columns, rows, scale_max=5):
    """Prosečne ocene: za svaki kriterijum po jedan stubac za svaki model."""
    dims = [c for c in columns if c != "model"]
    width, left, bar_h = 760, 200, 12
    block = bar_h * max(len(rows), 1) + 14
    height = 60 + len(rows) * 18 + len(dims) * block + 20
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
             f'<rect width="100%" height="100%" fill="white"/><text x="10" y="22" font-size="15" font-weight="bold">{_escape(title)}</text>']
    for i, row in enumerate(rows):
        parts.append(f'<rect x="10" y="{34 + i * 18}" width="12" height="12" fill="{COLORS[i % len(COLORS)]}"/>'
                     f'<text x="26" y="{45 + i * 18}">{_escape(row["model"])}</text>')
    top = 40 + len(rows) * 18
    for d_i, d in enumerate(dims):
        y0 = top + d_i * block
        parts.append(f'<text x="{left - 8}" y="{y0 + block / 2}" text-anchor="end">{_escape(d)}</text>')
        for r_i, row in enumerate(rows):
            value = row.get(d)
            if value is None:
                continue
            w = (width - left - 60) * value / scale_max
            parts.append(f'<rect x="{left}" y="{y0 + r_i * bar_h}" width="{w:.1f}" height="{bar_h - 2}" fill="{COLORS[r_i % len(COLORS)]}">'
                         f'<title>{_escape(row["model"])}: {value}</title></rect>'
                         f'<text x="{left + w + 4:.1f}" y="{y0 + r_i * bar_h + 10}" font-size="10">{value}</text>')
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def analyze(artifacts_path, runs_path=None, evaluations_path=None, out_dir="analiza_izlaz", out=print):
    artifacts = read_csv(artifacts_path)
    runs = read_csv(runs_path) if runs_path else None
    evaluations = read_csv(evaluations_path) if evaluations_path else None
    os.makedirs(out_dir, exist_ok=True)

    report = [f"# Analiza eksperimenta\n\nIzvor: `{os.path.basename(artifacts_path)}`"
              + (f", `{os.path.basename(runs_path)}`" if runs_path else "")
              + (f", `{os.path.basename(evaluations_path)}`" if evaluations_path else "")
              + f"\n\nPredloga: {len(artifacts)}" + (f", poziva modela: {len(runs)}" if runs is not None else "") + "\n"]
    if not artifacts:
        out("Fajl sa predlozima nema redova - nema šta da se analizira.")

    if runs is not None:
        columns, rows = runs_table(runs)
        write_csv(os.path.join(out_dir, "tabela_pozivi.csv"), columns, rows)
        svg_stacked(os.path.join(out_dir, "grafikon_padovi.svg"), "Ishod poziva po modelu",
                    [{**r, "uspeh": r["uspesnih"]} for r in rows], ["uspeh", *[f"pad_{f}" for f in FAILURES]])
        report += ["## Pozivi modela", markdown(columns, rows), ""]

    columns, rows = artifacts_table(artifacts)
    write_csv(os.path.join(out_dir, "tabela_predlozi.csv"), columns, rows)
    svg_stacked(os.path.join(out_dir, "grafikon_odluke.svg"), "Odluke nastavnika po modelu", rows, list(DECISIONS))
    report += ["## Predlozi i odluke", markdown(columns, rows), ""]

    columns, rows = scores_table(artifacts)
    write_csv(os.path.join(out_dir, "tabela_ocene.csv"), columns, rows)
    svg_grouped(os.path.join(out_dir, "grafikon_ocene.svg"), "Prosečne ocene po kriterijumu (nastavnik)", columns, rows)
    report += ["## Prosečne ocene po kriterijumu (nastavnik koji odlučuje)", markdown(columns, rows), ""]

    columns, rows = score_distribution_table(artifacts)
    write_csv(os.path.join(out_dir, "tabela_raspodela_ocena.csv"), columns, rows)
    svg_stacked(os.path.join(out_dir, "grafikon_raspodela_ocena.svg"), "Raspodela ocena po kriterijumu (nastavnik)",
                rows, [f"ocena_{v}" for v in SCALE], label="red", left=430)
    report += ["## Raspodela ocena po kriterijumu (broj ocena 1-5, nastavnik koji odlučuje)", markdown(columns, rows), ""]

    columns, rows, message = agreement_table(artifacts, evaluations)
    write_csv(os.path.join(out_dir, "tabela_saglasnost.csv"), columns, rows)
    report += ["## Saglasnost", (f"**{message}**\n" if message else "") + markdown(columns, rows), ""]
    if message:
        out(message)

    with open(os.path.join(out_dir, "izvestaj.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    out(f"Izveštaj: {os.path.join(out_dir, 'izvestaj.md')} (+ tabela_*.csv, grafikon_*.svg)")
    return {"agreement": rows, "message": message}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/analyze_experiment.py")
    parser.add_argument("--artifacts", required=True, help="CSV kind=artifacts")
    parser.add_argument("--runs", help="CSV kind=runs (opciono)")
    parser.add_argument("--evaluations", help="CSV kind=evaluations (opciono, za alfu sa svim ocenjivačima)")
    parser.add_argument("--out", default="analiza_izlaz")
    args = parser.parse_args(argv)
    analyze(args.artifacts, args.runs, args.evaluations, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
