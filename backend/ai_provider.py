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


def _call_groq(prompt: str, temperature: float = 0.7, model: str = "llama-3.1-8b-instant") -> dict:
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


# --- Ovde se kasnije dodaju _call_gemini, _call_mistral, na isti način ---


def generate(prompt: str, provider: str = "groq", options: dict | None = None) -> dict:
    """
    Jedinstvena funkcija koju ostatak aplikacije koristi.

    prompt   - tekst koji se šalje modelu
    provider - koji model koristiti: "groq" (za sad jedini implementiran)
    options  - dict, npr. {"temperature": 0.7}

    Vraća dict: {success, raw_text, response_time_ms, tokens_used} ili {success: False, error}
    """
    options = options or {}
    temperature = options.get("temperature", 0.7)

    if provider == "groq":
        return _call_groq(prompt, temperature=temperature)

    # elif provider == "gemini":
    #     return _call_gemini(prompt, temperature=temperature)

    return {"success": False, "error": f"Nepoznat provider: {provider}"}


if __name__ == "__main__":
    # Brz ručni test - pokreni "python ai_provider.py" da proveriš da li konekcija radi
    result = generate("Reci 'zdravo' na srpskom.", provider="groq")
    print(result)
