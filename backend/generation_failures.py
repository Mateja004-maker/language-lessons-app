"""
Vrste padova generisanja sličnog pitanja i poruke korisniku (tačka I).
Bez Flask-a i baze.

failure_type (None = uspeh):
  infrastruktura - model NIJE odgovorio (ponavljanja već radi ai_provider):
    network     mrežna greška ili telo odgovora servisa koje nije JSON
    http_4xx    servis je odbio zahtev (401, 403, 404, 422 ...), osim 429
    rate_limit  429 / limit besplatnog nivoa (i OpenRouter greška code=429 u telu)
    http_5xx    greška servisa (5xx, i OpenRouter greška provajdera u telu)
  model - odgovor je stigao, ali nije upotrebljiv:
    empty         prazan odgovor / bez teksta / blokiran prompt
    invalid_json  tekst odgovora nije JSON (npr. markdown ograde)
    schema        JSON ne prolazi question_validation (broj odgovora, tačan odgovor, oznake ...)

Ponovni zahtev posle lošeg formata (FORMAT_FAILURES) radi generate_similar_for_question.
"""

import json
import re

import question_validation

INFRA_FAILURES = ("network", "http_4xx", "rate_limit", "http_5xx")
MODEL_FAILURES = ("empty", "invalid_json", "schema")
FAILURE_TYPES = INFRA_FAILURES + MODEL_FAILURES

# Posle lošeg formata model se pita još jednom, istim promptom i parametrima
FORMAT_FAILURES = ("invalid_json", "schema")
MAX_FORMAT_RETRIES = 1

INVALID_JSON_ERROR = "Odgovor modela nije validan JSON"

USER_MESSAGES = {
    "rate_limit": "Prekoračen je limit besplatnog nivoa za izabrani model. Pokušajte kasnije ili izaberite drugi model.",
    "http_5xx": "Servis modela je trenutno nedostupan. Pokušajte ponovo za nekoliko minuta.",
    "network": "Nije moguće povezati se sa servisom modela. Proverite vezu i pokušajte ponovo.",
    "http_4xx": "Servis modela je odbio zahtev (npr. neispravan API ključ ili podešavanje modela). Obratite se administratoru.",
    "empty": "Model nije vratio odgovor. Pokušajte ponovo ili izaberite drugi model.",
    "invalid_json": "Model je vratio odgovor u neispravnom formatu, i posle ponovljenog zahteva. Pokušajte ponovo ili izaberite drugi model.",
    "schema": "Model je vratio pitanje koje ne ispunjava pravila (broj odgovora, tačan odgovor ili oznake), i posle ponovljenog zahteva. Pokušajte ponovo ili izaberite drugi model.",
}
DEFAULT_USER_MESSAGE = "AI generisanje nije dalo iskoristiv predlog. Pokušajte ponovo."

_HTTP_STATUS_RE = re.compile(r" API greška: (\d{3})\b")
_BODY_CODE_RE = re.compile(r"greška u odgovoru \(code=(\w+)")
_EMPTY_MARKERS = ("prazan odgovor", "odgovor bez teksta", "odgovor bez choices", "odgovor bez candidates",
                  "prompt blokiran", "neočekivan tip content")


def classify_provider_error(error) -> str:
    """Vrsta pada za neuspeh koji je vratio ai_provider (success=False)."""
    text = error or ""
    match = _HTTP_STATUS_RE.search(text)
    if match:
        status = int(match.group(1))
        if status == 429:
            return "rate_limit"
        return "http_5xx" if status >= 500 else "http_4xx"
    match = _BODY_CODE_RE.search(text)
    if match:  # OpenRouter: greška u telu uz HTTP 200
        code = match.group(1)
        if code == "429":
            return "rate_limit"
        return "http_4xx" if code.isdigit() and 400 <= int(code) < 500 else "http_5xx"
    if any(marker in text for marker in _EMPTY_MARKERS):
        return "empty"
    return "network"  # mrežna greška, telo servisa koje nije JSON, nepoznato


def user_message(failure_type) -> str:
    return USER_MESSAGES.get(failure_type, DEFAULT_USER_MESSAGE)


def evaluate_similar_question(result, question_type, expected_answer_count, prompt_version):
    """Jedan odgovor modela -> (parsed_result | None, validation_errors | None, failure_type | None)."""
    if not result.get("success"):
        error = result.get("error", "Nepoznata greška pri pozivu AI modela")
        return None, error, classify_provider_error(error)
    try:
        parsed = json.loads(result["raw_text"])
    except (ValueError, TypeError):
        return None, INVALID_JSON_ERROR, "invalid_json"
    validation = question_validation.validate(parsed, question_type, expected_answer_count, prompt_version)
    if not validation.passed:
        return parsed, "; ".join(validation.errors), "schema"
    return parsed, None, None


def evaluate_similar_set(result, k, prompt_version):
    """Odgovor modela za SKUP (tačka J) -> (parsed | None, SetValidationResult | None,
    validation_errors | None, failure_type | None). Uspeh = bar jedna ispravna stavka."""
    if not result.get("success"):
        error = result.get("error", "Nepoznata greška pri pozivu AI modela")
        return None, None, error, classify_provider_error(error)
    try:
        parsed = json.loads(result["raw_text"])
    except (ValueError, TypeError):
        return None, None, INVALID_JSON_ERROR, "invalid_json"
    validation = question_validation.validate_set(parsed, k, prompt_version)
    if not validation.passed:
        return parsed, validation, "; ".join(validation.errors), "schema"
    return parsed, validation, None, None


def classify_stored_run(validation_passed, raw_response, validation_errors):
    """Vrsta pada za STARI run (pre ove tačke) iz sačuvanih kolona - za jednokratnu dopunu."""
    if validation_passed:
        return None
    if raw_response is None:
        return classify_provider_error(validation_errors)
    if (validation_errors or "") == INVALID_JSON_ERROR:
        return "invalid_json"
    return "schema"
