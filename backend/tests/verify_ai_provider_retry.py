"""Provera ponovnih pokusaja i attempts/finish_reason u ai_provider.generate().

Pokretanje (iz foldera backend/):
    python tests/verify_ai_provider_retry.py

BEZ MREZE: requests.post je zamenjen lazom funkcijom koja vraca unapred
zadat niz odgovora, a time.sleep samo belezi trazene pauze (nema cekanja).
Nijedan pravi servis se ne poziva i API kljucevi se ne koriste.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import ai_provider  # noqa: E402

results = []
OLD_SUCCESS_KEYS = {"success", "raw_text", "response_time_ms", "tokens_used"}


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


OK_BODY = {
    "groq": {"choices": [{"message": {"content": "{\"x\": 1}"}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}},
    "openrouter": {"choices": [{"message": {"content": "{\"x\": 1}"}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}},
    "gemini": {"candidates": [{"content": {"parts": [{"text": "{\"x\": 1}"}]}, "finishReason": "STOP"}], "usageMetadata": {"totalTokenCount": 42}},
    "mistral": {"choices": [{"message": {"content": "{\"x\": 1}"}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}},
}
FINISH = {"groq": "stop", "openrouter": "stop", "gemini": "STOP"}
NETWORK = "NETWORK"  # oznaka u nizu: lazni poziv baca requests.ConnectionError


def run(provider, sequence):
    """Pozove generate() sa zadatim nizom odgovora; vraca (rezultat, broj_poziva, pauze)."""
    calls, pauses = [], []

    def fake_post(*args, **kwargs):
        if len(calls) >= len(sequence):
            raise AssertionError("generate() je pozvao requests.post vise puta nego sto je zadato")
        item = sequence[len(calls)]
        calls.append(kwargs.get("json"))
        if item == NETWORK:
            raise requests.ConnectionError("lazna mrezna greska")
        return item

    requests.post = fake_post
    ai_provider.time.sleep = pauses.append
    result = ai_provider.generate("prompt", provider=provider, options={"temperature": 0.7})
    return result, len(calls), pauses


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def ok_resp(provider):
    return FakeResponse(200, OK_BODY[provider])


def main():
    for p in ("groq", "gemini", "openrouter"):
        # 1) uspeh iz prve: isti kljucevi i vrednosti kao pre + attempts/finish_reason
        res, n, pauses = run(p, [ok_resp(p)])
        old_part = {k: res.get(k) for k in OLD_SUCCESS_KEYS}
        ok = (
            set(res) == OLD_SUCCESS_KEYS | {"attempts", "finish_reason"}
            and old_part["success"] is True and old_part["raw_text"] == "{\"x\": 1}"
            and old_part["tokens_used"] == 42 and isinstance(old_part["response_time_ms"], int)
            and res["attempts"] == 1 and res["finish_reason"] == FINISH[p] and n == 1 and pauses == []
        )
        record(f"{p}: uspeh iz prve", f"isti rezultat kao pre, attempts=1, finish_reason={FINISH[p]}",
               f"kljucevi={sorted(res)}, attempts={res.get('attempts')}, finish={res.get('finish_reason')}, poziva={n}", ok)

        # 2) 503 pa uspeh
        res, n, pauses = run(p, [FakeResponse(503, "unavailable"), ok_resp(p)])
        record(f"{p}: 503 pa uspeh", "success, attempts=2, pauza [5]",
               f"success={res['success']}, attempts={res['attempts']}, pauze={pauses}",
               res["success"] and res["attempts"] == 2 and n == 2 and pauses == [5])

        # 3) 400 se ne ponavlja
        res, n, pauses = run(p, [FakeResponse(400, "bad request"), ok_resp(p)])
        record(f"{p}: 400 se ne ponavlja", "1 poziv, success=False, attempts=1",
               f"poziva={n}, success={res['success']}, attempts={res['attempts']}, error={res['error'][:40]}",
               n == 1 and res["success"] is False and res["attempts"] == 1 and "400" in res["error"] and pauses == [])

        # 4) trajna greska: 3 pokusaja, pa success False sa razlogom
        res, n, pauses = run(p, [FakeResponse(503, "unavailable")] * 3)
        record(f"{p}: trajni 503", "3 poziva, pauze [5, 15], success=False, razlog sa '(pokušaja: 3)'",
               f"poziva={n}, pauze={pauses}, error={res['error']}",
               n == 3 and pauses == [5, 15] and res["success"] is False and res["attempts"] == 3
               and "503" in res["error"] and "(pokušaja: 3)" in res["error"])

    # ostali slucajevi (na groq-u, isti kod za sva tri)
    res, n, pauses = run("groq", [NETWORK] * 3)
    record("groq: trajna mrezna greska", "3 poziva, success=False, razlog mrezna greska",
           f"poziva={n}, pauze={pauses}, error={res['error']}",
           n == 3 and pauses == [5, 15] and res["success"] is False and "mrežna greška (ConnectionError) (pokušaja: 3)" in res["error"])

    res, n, pauses = run("groq", [NETWORK, ok_resp("groq")])
    record("groq: mrezna greska pa uspeh", "success, attempts=2", f"success={res['success']}, attempts={res['attempts']}",
           res["success"] and res["attempts"] == 2 and pauses == [5])

    res, n, pauses = run("groq", [FakeResponse(500, "e"), FakeResponse(502, "e"), ok_resp("groq")])
    record("groq: 500, 502 pa uspeh", "success, attempts=3, pauze [5, 15]", f"attempts={res['attempts']}, pauze={pauses}",
           res["success"] and res["attempts"] == 3 and pauses == [5, 15])

    for status in (401, 403, 404, 422):
        res, n, _ = run("groq", [FakeResponse(status, "x"), ok_resp("groq")])
        record(f"groq: {status} se ne ponavlja", "1 poziv", f"poziva={n}, success={res['success']}", n == 1 and res["success"] is False)

    for header, expected in (("10", [10.0]), ("120", [30.0]), ("1", [5])):
        res, n, pauses = run("groq", [FakeResponse(429, "rate", {"Retry-After": header}), ok_resp("groq")])
        record(f"groq: 429 sa Retry-After={header}", f"pauza {expected}", f"pauze={pauses}, attempts={res['attempts']}",
               res["success"] and pauses == expected)

    res, n, pauses = run("groq", [FakeResponse(429, "rate"), ok_resp("groq")])
    record("groq: 429 bez Retry-After", "pauza [5]", f"pauze={pauses}", res["success"] and pauses == [5])

    res, n, pauses = run("groq", [FakeResponse(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})])
    record("groq: prazan odgovor (bez ponavljanja)", "1 poziv, finish_reason=length", f"poziva={n}, finish={res.get('finish_reason')}, error={res['error']}",
           n == 1 and res["success"] is False and res["finish_reason"] == "length")

    # mistral se ne dira: bez ponavljanja i bez novih kljuceva
    res, n, pauses = run("mistral", [FakeResponse(503, "unavailable"), ok_resp("mistral")])
    record("mistral: 503 se ne ponavlja", "1 poziv, bez attempts/finish_reason", f"poziva={n}, kljucevi={sorted(res)}",
           n == 1 and "attempts" not in res and "finish_reason" not in res)


def print_table():
    head = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e, g if len(g) <= 90 else g[:87] + "...", s) for c, e, g, s in results]
    widths = [max(len(str(r[i])) for r in rows + [head]) for i in range(4)]
    line = " | ".join(h.ljust(w) for h, w in zip(head, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    failed = sum(1 for r in results if r[3] != "OK")
    print(f"\nUkupno: {len(results)}, palo: {failed}")
    return failed


if __name__ == "__main__":
    real_post, real_sleep = requests.post, ai_provider.time.sleep
    try:
        main()
    finally:
        requests.post, ai_provider.time.sleep = real_post, real_sleep
    sys.exit(1 if print_table() else 0)
