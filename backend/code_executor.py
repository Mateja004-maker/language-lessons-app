"""
Izvršava Python kod (generisan od strane LLM-a, ili referentno rešenje) protiv
zadatih test primera (stdin -> očekivan stdout), u posebnom subprocess-u sa
vremenskim ograničenjem po test primeru.

Koristi se za mehaničku proveru tačnosti rešenja u režimu B (zadatak, odeljak
8: "za programske zadatke pripremiti automatske testove kojima se generisana
rešenja izvršavaju i proveravaju - tačnost rešenja ne sme da se ocenjuje
'od oka'.").

BEZBEDNOSNA NAPOMENA: ovo pokreće proizvoljan kod u pravom Python interpreteru
na ovoj mašini, BEZ sandbox/container izolacije. Prihvatljivo je za
kontrolisano, lokalno pokretanje evaluacije (mali, poznat broj poziva ka par
LLM provajdera, pokreće ga sam istraživač na sopstvenoj mašini), ali NIJE
bezbedno za produkcionu upotrebu gde bi krajnji korisnici mogli neposredno da
utiču na to koji se kod izvršava bez nadzora - ovo treba pomenuti kao rizik i
predložiti pravu sandbox izolaciju (npr. Docker kontejner bez mreže) kao meru
zaštite za produkcionu upotrebu (zadatak, odeljak 9, tačka 5).
"""

import subprocess
import sys

DEFAULT_TIMEOUT_SECONDS = 5.0


def _run_one(code: str, input_data: str, timeout_seconds: float) -> dict:
    """Pokreće code kao Python program, šalje input_data na stdin, vraća sirov
    rezultat izvršavanja (bez poređenja sa očekivanim izlazom)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=input_data or "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"timed_out": True, "returncode": None, "stdout": None, "stderr": None}

    return {
        "timed_out": False,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_against_test_cases(code: str, test_cases: list, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """
    code - Python izvorni kod kao string (kompletan program, čita stdin preko
           input(), piše rezultat preko print()).
    test_cases - lista dict-ova sa ključevima order_no, input_data,
                 expected_output (isti oblik kao redovi iz
                 exam_question_test_cases).
    timeout_seconds - maksimalno vreme izvršavanja PO test primeru.

    Vraća: {
        "all_passed": bool,
        "results": [
            {order_no, input_data, expected_output, actual_output, passed,
             error, timed_out},
            ...
        ]
    }
    all_passed je False i kad je lista test_cases prazna (nema šta da se
    proveri, pa se ne sme tumačiti kao uspeh).
    """
    results = []

    for tc in test_cases:
        order_no = tc.get("order_no")
        input_data = tc.get("input_data") or ""
        expected = (tc.get("expected_output") or "").strip()

        outcome = _run_one(code, input_data, timeout_seconds)

        if outcome["timed_out"]:
            results.append({
                "order_no": order_no,
                "input_data": input_data,
                "expected_output": expected,
                "actual_output": None,
                "passed": False,
                "error": f"Prekoračeno vreme izvršavanja ({timeout_seconds}s)",
                "timed_out": True,
            })
            continue

        if outcome["returncode"] != 0:
            stderr_snippet = (outcome["stderr"] or "").strip()[:500]
            results.append({
                "order_no": order_no,
                "input_data": input_data,
                "expected_output": expected,
                "actual_output": (outcome["stdout"] or "").strip() or None,
                "passed": False,
                "error": f"Program je zavrsio sa greskom (exit code {outcome['returncode']}): {stderr_snippet}",
                "timed_out": False,
            })
            continue

        actual = (outcome["stdout"] or "").strip()
        passed = actual == expected
        results.append({
            "order_no": order_no,
            "input_data": input_data,
            "expected_output": expected,
            "actual_output": actual,
            "passed": passed,
            "error": None if passed else "Izlaz se ne poklapa sa ocekivanim",
            "timed_out": False,
        })

    all_passed = len(results) > 0 and all(r["passed"] for r in results)
    return {"all_passed": all_passed, "results": results}
