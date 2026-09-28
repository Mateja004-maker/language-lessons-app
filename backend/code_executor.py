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

Minimalna zaštita (bez Docker-a), da bi se smanjila SLUČAJNA šteta i curenje
tajni kroz okruženje procesa - NIJE sandbox protiv namerno zlonamernog koda:
- svako pokretanje u zasebnom, praznom privremenom direktorijumu koji se
  posle briše;
- python -I (izolovani režim: cwd nije na sys.path, ignorišu se PYTHON*
  promenljive i user site-packages) i -X utf8 (stdin/stdout u UTF-8);
- env podprocesa sadrži samo PATH (i SYSTEMROOT na Windows-u) - nijedna
  promenljiva iz .env (API ključevi, lozinka baze) ne prelazi u podproces;
- stdout/stderr ograničeni na MAX_OUTPUT_BYTES - preko toga proces se ubija;
- timeout i prekoračenje izlaza ubijaju celo stablo procesa (taskkill /F /T
  na Windows-u, process group + killpg na Linux-u).
Ne pokriva: čitanje/pisanje fajlova van privremenog foldera apsolutnom
putanjom, mrežu, memoriju/CPU, procese koji se odvoje od stabla.
"""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_OUTPUT_BYTES = 100 * 1024  # po toku (stdout/stderr) i po pokretanju
# actual_output u rezultatu se seče na ovoliko znakova - ceo rezultat se upisuje
# u ai_generation_runs.accuracy_check_details (TEXT, max 64 KB).
MAX_REPORTED_OUTPUT_CHARS = 1000
_POLL_INTERVAL_SECONDS = 0.05
_READER_JOIN_SECONDS = 2.0


def _minimal_env() -> dict:
    """Samo ono bez čega interpreter ne može da se pokrene."""
    env = {"PATH": os.environ.get("PATH", "")}
    if os.name == "nt":
        # bez SYSTEMROOT Python na Windows-u ume da padne već pri pokretanju
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    return env


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Ubija proces i sve njegove potomke (ne samo direktni proces)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _read_limited(stream, sink: list, overflow: threading.Event) -> None:
    """Čita tok do MAX_OUTPUT_BYTES; višak odbacuje (i dalje čita, da proces
    ne zablokira na punom pipe-u) i javlja prekoračenje preko overflow."""
    total = 0
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        if total < MAX_OUTPUT_BYTES:
            sink.append(chunk[: MAX_OUTPUT_BYTES - total])
        total += len(chunk)
        if total > MAX_OUTPUT_BYTES:
            overflow.set()
    stream.close()


def _write_stdin(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except OSError:
        pass  # program je izašao ili zatvorio stdin pre nego što je sve pročitao
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _decode(chunks: list) -> str:
    # isto kao ranije text=True: UTF-8 i univerzalni krajevi redova (\r\n -> \n)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _clip(text):
    if text is None or len(text) <= MAX_REPORTED_OUTPUT_CHARS:
        return text
    return text[:MAX_REPORTED_OUTPUT_CHARS] + " ...[skraćeno]"


def _run_one(code: str, input_data: str, timeout_seconds: float) -> dict:
    """Pokreće code kao Python program, šalje input_data na stdin, vraća sirov
    rezultat izvršavanja (bez poređenja sa očekivanim izlazom)."""
    with tempfile.TemporaryDirectory(prefix="code_exec_", ignore_cleanup_errors=True) as workdir:
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True  # sopstvena grupa procesa za killpg

        proc = subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=_minimal_env(),
            **popen_kwargs,
        )

        overflow = threading.Event()
        stdout_chunks, stderr_chunks = [], []
        threads = [
            threading.Thread(target=_write_stdin, args=(proc.stdin, (input_data or "").encode("utf-8")), daemon=True),
            threading.Thread(target=_read_limited, args=(proc.stdout, stdout_chunks, overflow), daemon=True),
            threading.Thread(target=_read_limited, args=(proc.stderr, stderr_chunks, overflow), daemon=True),
        ]
        for t in threads:
            t.start()

        timed_out = False
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                proc.wait(timeout=_POLL_INTERVAL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if overflow.is_set():
                    _kill_process_tree(proc)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    _kill_process_tree(proc)
                    break

        proc.wait()
        for t in threads:
            t.join(timeout=_READER_JOIN_SECONDS)

    if timed_out:
        return {"timed_out": True, "returncode": None, "stdout": None, "stderr": None,
                "output_limit_exceeded": False}

    return {
        "timed_out": False,
        "returncode": proc.returncode,
        "stdout": _decode(stdout_chunks),
        "stderr": _decode(stderr_chunks),
        "output_limit_exceeded": overflow.is_set(),
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

        if outcome["output_limit_exceeded"]:
            results.append({
                "order_no": order_no,
                "input_data": input_data,
                "expected_output": expected,
                "actual_output": _clip((outcome["stdout"] or "").strip() or None),
                "passed": False,
                "error": f"Prekoračena dozvoljena veličina izlaza ({MAX_OUTPUT_BYTES // 1024} KB)",
                "timed_out": False,
            })
            continue

        if outcome["returncode"] != 0:
            stderr_snippet = (outcome["stderr"] or "").strip()[:500]
            results.append({
                "order_no": order_no,
                "input_data": input_data,
                "expected_output": expected,
                "actual_output": _clip((outcome["stdout"] or "").strip() or None),
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
            "actual_output": _clip(actual),
            "passed": passed,
            "error": None if passed else "Izlaz se ne poklapa sa ocekivanim",
            "timed_out": False,
        })

    all_passed = len(results) > 0 and all(r["passed"] for r in results)
    return {"all_passed": all_passed, "results": results}
