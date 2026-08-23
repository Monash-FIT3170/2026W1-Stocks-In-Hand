import json
import os
import unittest
from unittest.mock import patch

from app.services import ollama


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OllamaProviderTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "test-model:latest",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_rejects_non_local_endpoint(self):
        with (
            patch.dict(
                os.environ,
                {"OLLAMA_BASE_URL": "https://models.example.com"},
            ),
            self.assertRaisesRegex(RuntimeError, "localhost"),
        ):
            ollama.ensure_model_available()

    def test_checks_that_model_is_installed(self):
        with patch.object(
            ollama,
            "urlopen",
            return_value=FakeResponse({"models": [{"name": "test-model:latest"}]}),
        ):
            ollama.ensure_model_available()

    def test_summarises_with_structured_local_response(self):
        response = {
            "message": {
                "content": json.dumps(
                    {
                        "summary": "The company released its half-year result.",
                        "about": "The filing covers revenue and earnings.",
                        "changed": "Revenue increased from the prior period.",
                        "matters": "The result updates the earnings outlook.",
                        "sentiment_label": "positive",
                        "sentiment_confidence": 0.82,
                    }
                )
            }
        }
        with patch.object(
            ollama,
            "urlopen",
            return_value=FakeResponse(response),
        ) as mocked:
            result = ollama.summarise_announcement(
                title="Half Year Results",
                category="HalfYearResults",
                extracted_data={"revenue": "up"},
                raw_text="Revenue increased during the half year.",
            )

        self.assertEqual(result["sentiment_label"], "positive")
        self.assertEqual(result["sentiment_confidence"], 0.82)
        request = mocked.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "test-model:latest")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])

    def test_rejects_invalid_sentiment(self):
        content = {
            "summary": "Summary",
            "about": "About",
            "changed": "Changed",
            "matters": "Matters",
            "sentiment_label": "bullish",
            "sentiment_confidence": 0.8,
        }
        with self.assertRaisesRegex(RuntimeError, "sentiment label"):
            ollama._parse_content(json.dumps(content))


if __name__ == "__main__":
    unittest.main()
