"""Testovi vrste pada i poruka (python tests/test_generation_failures.py iz backend/). Samo stdlib."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generation_failures import (  # noqa: E402
    FAILURE_TYPES,
    USER_MESSAGES,
    classify_provider_error,
    classify_stored_run,
    evaluate_similar_question,
    user_message,
)

GOOD = {"question_text": "P?", "answers": [{"answer_text": "a", "is_correct": True}, {"answer_text": "b", "is_correct": False}]}


class ProviderErrors(unittest.TestCase):
    def test_http_statuses(self):
        for text, expected in (
            ("Groq API greška: 429 rate limit (pokušaja: 3)", "rate_limit"),
            ("Gemini API greška: 503 unavailable (pokušaja: 3)", "http_5xx"),
            ("OpenRouter API greška: 500 x", "http_5xx"),
            ("Groq API greška: 401 unauthorized", "http_4xx"),
            ("Gemini API greška: 404 not found", "http_4xx"),
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_provider_error(text), expected)

    def test_network_and_unknown(self):
        self.assertEqual(classify_provider_error("Groq: mrežna greška (ConnectionError) (pokušaja: 3)"), "network")
        self.assertEqual(classify_provider_error("Groq: odgovor nije validan JSON"), "network")
        self.assertEqual(classify_provider_error(None), "network")

    def test_openrouter_error_in_body(self):
        self.assertEqual(classify_provider_error("OpenRouter: greška u odgovoru (code=429, message=x)"), "rate_limit")
        self.assertEqual(classify_provider_error("OpenRouter: greška u odgovoru (code=502, message=x)"), "http_5xx")
        self.assertEqual(classify_provider_error("OpenRouter: greška u odgovoru (code=400, message=x)"), "http_4xx")
        self.assertEqual(classify_provider_error("OpenRouter: greška u odgovoru (code=None, message=x)"), "http_5xx")

    def test_empty(self):
        for text in ("Groq: prazan odgovor (finish_reason=length)", "Gemini: odgovor bez teksta (finishReason=MAX_TOKENS)",
                     "Gemini: prompt blokiran (blockReason=SAFETY)", "OpenRouter: odgovor bez choices"):
            self.assertEqual(classify_provider_error(text), "empty", text)


class Evaluate(unittest.TestCase):
    def test_success(self):
        self.assertEqual(evaluate_similar_question({"success": True, "raw_text": json.dumps(GOOD)}, "mc", 2, "mc-v2"),
                         (GOOD, None, None))

    def test_invalid_json_and_fences(self):
        for raw in ("ovo nije json", "```json\n" + json.dumps(GOOD) + "\n```"):
            parsed, error, kind = evaluate_similar_question({"success": True, "raw_text": raw}, "mc", 2, "mc-v2")
            self.assertEqual((parsed, error, kind), (None, "Odgovor modela nije validan JSON", "invalid_json"))

    def test_schema(self):
        _, error, kind = evaluate_similar_question({"success": True, "raw_text": json.dumps(GOOD)}, "mc", 3, "mc-v2")
        self.assertEqual(kind, "schema")
        self.assertIn("3 ponuđenih", error)

    def test_provider_failure(self):
        _, error, kind = evaluate_similar_question({"success": False, "error": "Groq API greška: 429 x"}, "mc", 2, "mc-v2")
        self.assertEqual((error, kind), ("Groq API greška: 429 x", "rate_limit"))


class Messages(unittest.TestCase):
    def test_every_type_has_message_without_raw_text(self):
        for kind in FAILURE_TYPES:
            message = user_message(kind)
            self.assertIn(kind, USER_MESSAGES)
            self.assertNotIn("API greška", message)
        self.assertIn("limit", user_message("rate_limit"))
        self.assertTrue(user_message("nepoznato"))


class StoredRuns(unittest.TestCase):
    def test_backfill_classification(self):
        self.assertIsNone(classify_stored_run(1, "{}", None))
        self.assertEqual(classify_stored_run(0, "```json", "Odgovor modela nije validan JSON"), "invalid_json")
        self.assertEqual(classify_stored_run(0, "{}", "Očekivano je tačno 4 ponuđenih odgovora"), "schema")
        self.assertEqual(classify_stored_run(0, None, "Gemini API greška: 404 model not found"), "http_4xx")
        self.assertEqual(classify_stored_run(0, None, "Groq: mrežna greška (ReadTimeout)"), "network")


if __name__ == "__main__":
    unittest.main(verbosity=1)
