"""
Saglasnost ocenjivača (tačka G): Koenova kapa i Kripendorfova alfa.
Samo standardna biblioteka (bez numpy/sklearn), da analiza radi na čistoj instalaciji.

- cohen_kappa(a, b, weights=None | "linear" | "quadratic", categories=None):
  dva ocenjivača, isti predmeti. Nominalna (bez težina) za kategorije (težina,
  Blumov nivo), težinska kvadratna za Likert ocene 1-5.
- krippendorff_alpha(units, level="nominal" | "ordinal" | "interval"):
  units = lista jedinica, svaka lista vrednosti svih ocenjivača (None = nema
  ocene); radi sa više ocenjivača i nedostajućim ocenama.
Obe vraćaju None kada se saglasnost ne može izračunati (premalo podataka ili
nema varijacije), umesto da puknu.
"""

from collections import Counter
from itertools import permutations


def cohen_kappa(a, b, weights=None, categories=None):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    cats = sorted(set(categories) if categories else {v for pair in pairs for v in pair})
    k = len(cats)
    if k < 2:
        return None
    index = {c: i for i, c in enumerate(cats)}

    def weight(i, j):
        if weights is None:
            return 0.0 if i == j else 1.0
        distance = abs(i - j) / (k - 1)
        return distance if weights == "linear" else distance ** 2

    n = len(pairs)
    observed = sum(weight(index[x], index[y]) for x, y in pairs) / n
    pa = Counter(index[x] for x, _ in pairs)
    pb = Counter(index[y] for _, y in pairs)
    expected = sum(pa[i] * pb[j] * weight(i, j) for i in range(k) for j in range(k)) / (n * n)
    if expected == 0:
        return None
    return 1 - observed / expected


def _delta2(level, c, k, totals, order):
    if c == k:
        return 0.0
    if level == "nominal":
        return 1.0
    if level == "interval":
        return float(c - k) ** 2
    # ordinal: (zbir marginala od c do k - (n_c + n_k) / 2)^2, po redosledu vrednosti
    lo, hi = sorted((order[c], order[k]))
    values = sorted(order, key=order.get)
    between = sum(totals[v] for v in values[lo:hi + 1])
    return (between - (totals[c] + totals[k]) / 2) ** 2


def krippendorff_alpha(units, level="nominal"):
    pairable = [[v for v in unit if v is not None] for unit in units]
    pairable = [u for u in pairable if len(u) >= 2]
    if not pairable:
        return None
    coincidence = Counter()
    for unit in pairable:
        m = len(unit)
        for c, k in permutations(unit, 2):
            coincidence[(c, k)] += 1 / (m - 1)
    totals = Counter()
    for (c, _), value in coincidence.items():
        totals[c] += value
    n = sum(totals.values())
    values = sorted(totals)
    if len(values) < 2:
        return None
    order = {v: i for i, v in enumerate(values)}
    d_observed = sum(o * _delta2(level, c, k, totals, order) for (c, k), o in coincidence.items())
    d_expected = sum(totals[c] * totals[k] * _delta2(level, c, k, totals, order) for c in values for k in values)
    if d_expected == 0:
        return None
    return 1 - (n - 1) * d_observed / d_expected
