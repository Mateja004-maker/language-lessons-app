"""
Provider layer - jedinstven ulaz ka svim AI modelima.
Ovo je ZAJEDNIČKI fajl - i Anđin i Andrejev modul ga koriste na isti način.

Ideja: ostatak aplikacije uvek zove samo generate(...), nikad direktno
ne zna kako se konkretan model poziva. Time se modeli mogu menjati/dodavati
bez diranja ostatka koda, i mogu se porediti pod identičnim uslovima.
"""

import os
import time
import requests

# --- Konfiguracija modela (kasnije prebaciti API ključeve u .env, ne u kod) ---

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# Jedini izvor istine za default model po provideru - i _call_* funkcije
# ispod i pozivaoci van ovog fajla (npr. app.py) čitaju odavde, da model
# upisan u ai_models ostane dosledan modelu koji se stvarno poziva.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-2.0-flash",
    "mistral": "mistral-small-latest",
}


def _call_groq(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["groq"]) -> dict:
    """Poziva Groq API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    start = time.time()
    response = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=30,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"Groq API greška: {response.status_code} {response.text[:200]}",
            "response_time_ms": elapsed_ms,
        }

    data = response.json()
    text = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {}).get("total_tokens")

    return {
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }


def _call_gemini(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["gemini"]) -> dict:
    """Poziva Gemini API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    start = time.time()
    response = requests.post(
        GEMINI_URL.format(model=model),
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        },
        timeout=30,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"Gemini API greška: {response.status_code} {response.text[:200]}",
            "response_time_ms": elapsed_ms,
        }

    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    tokens = data.get("usageMetadata", {}).get("totalTokenCount")

    return {
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }


def _call_mistral(prompt: str, temperature: float = 0.7, model: str = DEFAULT_MODELS["mistral"]) -> dict:
    """Poziva Mistral API. Vraća sirov tekstualni odgovor + tehničke podatke."""
    start = time.time()
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
    elapsed_ms = int((time.time() - start) * 1000)

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"Mistral API greška: {response.status_code} {response.text[:200]}",
            "response_time_ms": elapsed_ms,
        }

    data = response.json()
    text = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {}).get("total_tokens")

    return {
        "success": True,
        "raw_text": text,
        "response_time_ms": elapsed_ms,
        "tokens_used": tokens,
    }


def generate(prompt: str, provider: str = "groq", options: dict | None = None) -> dict:
    """
    Jedinstvena funkcija koju ostatak aplikacije koristi.

    prompt   - tekst koji se šalje modelu
    provider - koji model koristiti: "groq", "gemini" ili "mistral"
    options  - dict, npr. {"temperature": 0.7}

    Vraća dict: {success, raw_text, response_time_ms, tokens_used} ili {success: False, error}
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

    return {"success": False, "error": f"Nepoznat provider: {provider}"}


if __name__ == "__main__":
    # Brz ručni test - pokreni "python ai_provider.py" da proveriš da li konekcija radi
    result = generate("Reci 'zdravo' na srpskom.", provider="groq")
    print(result)
