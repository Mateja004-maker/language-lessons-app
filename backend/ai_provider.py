"""
Provider layer - jedinstven ulaz ka svim AI modelima.
Ovo je ZAJEDNIČKI fajl - i Anđin i Andrejev modul ga koriste na isti način.

Ideja: ostatak aplikacije uvek zove samo generate(...), nikad direktno
ne zna kako se konkretan model poziva. Time se modeli mogu menjati/dodavati
bez diranja ostatka koda, i mogu se porediti pod identičnim uslovima.
"""

import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

# --- Konfiguracija modela (kasnije prebaciti API ključeve u .env, ne u kod) ---

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Jedini izvor istine za default model po provideru - i _call_* funkcije
# ispod i pozivaoci van ovog fajla (npr. app.py) čitaju odavde, da model
# upisan u ai_models ostane dosledan modelu koji se stvarno poziva.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-3.6-flash",
    "mistral": "mistral-small-latest",
    "openrouter": "nvidia/nemotron-3-super-120b-a12b:free",
}


# --- Otpornost na neočekivan odgovor ---
# Svaki neuspeh (mreža, telo koje nije JSON, odgovor bez teksta) vraća
# {"success": False, "error": ..., "response_time_ms": ...} umesto izuzetka,
# da bi pozivalac mogao da upiše run sa razlogom greške. U poruku ide samo
# ime tipa mrežnog izuzetka, ne njegov tekst - on sadrži URL, a Gemini ključ
# je u query parametru.

def _failure(error: str, elapsed_ms: int) -> dict:
    return {"success": False, "error": error, "response_time_ms": elapsed_ms}


# --- Ponovni pokušaji (groq, gemini, openrouter; mistral namerno ne) ---
# Do 2 ponavljanja, samo za 429, 5xx i mrežne greške; ostali 4xx se ne
# ponavljaju. Pauza pre 2. i 3. pokušaja je 5s i 15s. Ako provajder pošalje
# Retry-After, čeka se koliko traži (ali najviše 30s), a ne kraće od pauze.

RETRY_PAUSES_S = (5, 15)
RETRY_AFTER_MAX_S = 30


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def _retry_after_seconds(response):
    """Retry-After u sekundama (broj ili HTTP datum), ograničen na RETRY_AFTER_MAX_S; None ako ga nema."""
    value = (response.headers or {}).get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0.0), RETRY_AFTER_MAX_S)


def _post_with_retry(*args, **kwargs):
    """requests.post sa ponovnim pokušajima.
    Vraća (response, exception, attempts, elapsed_ms); tačno jedno od
    response/exception nije None. elapsed_ms je trajanje POSLEDNJEG pokušaja
    (bez pauza), da response_time_ms i dalje meri odziv modela."""
    attempts = 0
    while True:
        attempts += 1
        start = time.time()
        try:
            response, exception = requests.post(*args, **kwargs), None
        except requests.RequestException as e:
            response, exception = None, e
        elapsed_ms = int((time.time() - start) * 1000)

        retryable = exception is not None or _is_retryable_status(response.status_code)
        if not retryable or attempts > len(RETRY_PAUSES_S):
            return response, exception, attempts, elapsed_ms

        pause = RETRY_PAUSES_S[attempts - 1]
        if response is not None:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                pause = max(pause, retry_after)
        time.sleep(pause)


def _attempts_note(attempts: int) -> str:
    return f" (pokušaja: {attempts})" if attempts > 1 else ""


def _with_meta(result: dict, attempts: int, finish_reason) -> dict:
    """Dodaje attempts i finish_reason (vrednost kako je provajder vraća, ili
    None ako odgovor nije stigao do tela) u rezultat; ostali ključevi ostaju isti."""
    result["attempts"] = attempts
    result["finish_reason"] = finish_reason
    return result


def _openai_finish_reason(data):
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason")
    return None


def _gemini_finish_reason(data):
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        return candidates[0].get("finishReason")
    return None


def _extract_openai_text(data, label: str):
    """Groq i Mistral (OpenAI format). Vraća (text, None) ili (None, poruka)."""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return None, f"{label}: odgovor bez choices"

    choice = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = choice.get("finish_reason")
    content = (choice.get("message") or {}).get("content")

    if content is not None and not isinstance(content, str):
        return None, f"{label}: neočekivan tip content ({type(content).__name__}, finish_reason={finish_reason})"
    if not content or not content.strip():
        return None, f"{label}: prazan odgovor (finish_reason={finish_reason})"
    return content, None


def _extract_gemini_text(data):
    """Gemini. Uzima prvi deo koji ima tekst. Vraća (text, None) ili (None, poruka)."""
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list) or not candidates:
        prompt_feedback = data.get("promptFeedback") if isinstance(data, dict) else None
        block_reason = (prompt_feedback or {}).get("blockReason")
        if block_reason:
            return None, f"Gemini: prompt blokiran (blockReason={block_reason})"
        return None, "Gemini: odgovor bez candidates"

    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    parts = (candidate.get("content") or {}).get("parts") or []
    for part in parts:
        text = part.get("text") if isinstance(part, dict) else None
        if isinstance(text, str) and text.strip():
            return text, None

    detail = f"finishReason={candidate.get('finishReason')}"
    blocked = [
        rating.get("category")
        for rating in candidate.get("safetyRatings") or []
        if isinstance(rating, dict) and rating.get("blocked")
    ]
    if blocked:
        detail += f", blokirane kategorije={','.join(blocked)}"
    return None, f"Gemini: odgovor bez teksta ({detail})"


def _call_groq(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["groq"]) -> dict:
    """Poziva Groq API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    response, exception, attempts, elapsed_ms = _post_with_retry(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=30,
    )
    if exception is not None:
        return _with_meta(
            _failure(f"Groq: mrežna greška ({type(exception).__name__}){_attempts_note(attempts)}", elapsed_ms),
            attempts, None,
        )

    if response.status_code != 200:
        return _with_meta({
            "success": False,
            "error": f"Groq API greška: {response.status_code} {response.text[:200]}{_attempts_note(attempts)}",
            "response_time_ms": elapsed_ms,
        }, attempts, None)

    try:
        data = response.json()
    except ValueError:
        return _with_meta(_failure("Groq: odgovor nije validan JSON", elapsed_ms), attempts, None)
    finish_reason = _openai_finish_reason(data)
    text, error = _extract_openai_text(data, "Groq")
    if error:
        return _with_meta(_failure(error, elapsed_ms), attempts, finish_reason)
    tokens = data.get("usage", {}).get("total_tokens")

    return _with_meta({
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }, attempts, finish_reason)


def _call_gemini(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["gemini"]) -> dict:
    """Poziva Gemini API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    response, exception, attempts, elapsed_ms = _post_with_retry(
        GEMINI_URL.format(model=model),
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        },
        timeout=30,
    )
    if exception is not None:
        return _with_meta(
            _failure(f"Gemini: mrežna greška ({type(exception).__name__}){_attempts_note(attempts)}", elapsed_ms),
            attempts, None,
        )

    if response.status_code != 200:
        return _with_meta({
            "success": False,
            "error": f"Gemini API greška: {response.status_code} {response.text[:200]}{_attempts_note(attempts)}",
            "response_time_ms": elapsed_ms,
        }, attempts, None)

    try:
        data = response.json()
    except ValueError:
        return _with_meta(_failure("Gemini: odgovor nije validan JSON", elapsed_ms), attempts, None)
    finish_reason = _gemini_finish_reason(data)
    text, error = _extract_gemini_text(data)
    if error:
        return _with_meta(_failure(error, elapsed_ms), attempts, finish_reason)
    tokens = data.get("usageMetadata", {}).get("totalTokenCount")

    return _with_meta({
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }, attempts, finish_reason)


def _call_mistral(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["mistral"]) -> dict:
    """Poziva Mistral API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    start = time.time()
    try:
        response = requests.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        return _failure(f"Mistral: mrežna greška ({type(e).__name__})", int((time.time() - start) * 1000))
    elapsed_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"Mistral API greška: {response.status_code} {response.text[:200]}",
            "response_time_ms": elapsed_ms,
        }

    try:
        data = response.json()
    except ValueError:
        return _failure("Mistral: odgovor nije validan JSON", elapsed_ms)
    text, error = _extract_openai_text(data, "Mistral")
    if error:
        return _failure(error, elapsed_ms)
    tokens = data.get("usage", {}).get("total_tokens")

    return {
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }


def _openrouter_error(data):
    """OpenRouter može da vrati grešku u telu i uz status 200 - na vrhu
    odgovora ili u choices[0] (greška provajdera tokom generisanja). Vraća
    poruku ili None. metadata se namerno ne prenosi (ume da sadrži dugačak
    sirov odgovor provajdera)."""
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if not err:
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            err = choices[0].get("error")
    if not err:
        return None
    if isinstance(err, dict):
        return f"OpenRouter: greška u odgovoru (code={err.get('code')}, message={str(err.get('message'))[:200]})"
    return f"OpenRouter: greška u odgovoru ({str(err)[:200]})"


def _call_openrouter(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["openrouter"]) -> dict:
    """Poziva OpenRouter API (OpenAI format). Vraća sirov tekstualni odgovor + tehničke podatke."""
    response, exception, attempts, elapsed_ms = _post_with_retry(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=30,
    )
    if exception is not None:
        return _with_meta(
            _failure(f"OpenRouter: mrežna greška ({type(exception).__name__}){_attempts_note(attempts)}", elapsed_ms),
            attempts, None,
        )

    if response.status_code != 200:
        return _with_meta({
            "success": False,
            "error": f"OpenRouter API greška: {response.status_code} {response.text[:200]}{_attempts_note(attempts)}",
            "response_time_ms": elapsed_ms,
        }, attempts, None)

    try:
        data = response.json()
    except ValueError:
        return _with_meta(_failure("OpenRouter: odgovor nije validan JSON", elapsed_ms), attempts, None)
    finish_reason = _openai_finish_reason(data)
    error = _openrouter_error(data)
    if error:
        return _with_meta(_failure(error, elapsed_ms), attempts, finish_reason)
    text, error = _extract_openai_text(data, "OpenRouter")
    if error:
        return _with_meta(_failure(error, elapsed_ms), attempts, finish_reason)
    tokens = data.get("usage", {}).get("total_tokens")

    return _with_meta({
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }, attempts, finish_reason)


def generate(prompt: str, provider: str = "groq", options: dict | None = None) -> dict:
    """
    Jedinstvena funkcija koju ostatak aplikacije koristi.

    prompt   - tekst koji se šalje modelu
    provider - koji model koristiti: "groq", "gemini", "mistral" ili "openrouter"
    options  - dict, npr. {"temperature": 0.7}

    Vraća dict: {success, raw_text, response_time_ms, tokens_used} ili {success: False, error}.
    Za groq, gemini i openrouter rezultat (i uspeh i greška) ima još:
    attempts (broj HTTP pokušaja, 1-3) i finish_reason (kako ga provajder
    vraća; None ako odgovor nije stigao do tela). Mistral ih nema.
    """
    options = options or {}
    temperature = options.get("temperature", 0.7)
    # Aditivna izmena (02.09.2026, Andrej): omogucava eksplicitno prosledjivanje
    # imena modela kroz options["model"], da bi se resio nepostojeci default
    # groq model (llama-3.1-8b-instant vise ne postoji na Groq API-ju). Ne menja
    # ponasanje postojecih poziva koji ne prosledjuju "model" - i dalje padaju
    # na iste hardkodovane default-e kao do sada (ukljucujuci Andjine pozive).
    model = options.get("model")

    if provider == "groq":
        if model is not None:
            return _call_groq(prompt, temperature=temperature, model=model)
        return _call_groq(prompt, temperature=temperature)

    elif provider == "gemini":
        if model is not None:
            return _call_gemini(prompt, temperature=temperature, model=model)
        return _call_gemini(prompt, temperature=temperature)

    elif provider == "mistral":
        if model is not None:
            return _call_mistral(prompt, temperature=temperature, model=model)
        return _call_mistral(prompt, temperature=temperature)

    elif provider == "openrouter":
        if model is not None:
            return _call_openrouter(prompt, temperature=temperature, model=model)
        return _call_openrouter(prompt, temperature=temperature)

    return {"success": False, "error": f"Nepoznat provider: {provider}"}


if __name__ == "__main__":
    # Brz ručni test - pokreni "python ai_provider.py" da proveriš da li konekcija radi
    result = generate("Reci 'zdravo' na srpskom.", provider="groq")
    print(result)
