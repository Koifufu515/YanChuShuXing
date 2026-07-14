import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.application.errors import (
    ConfigurationError,
    InvalidProviderOutputError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.application.models import LLMRequest


class _Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class DeepSeekProviderTest(unittest.TestCase):
    def _provider(self, api_key="secret-key"):
        from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider

        return DeepSeekLLMProvider(
            base_url="https://api.deepseek.com",
            api_key=api_key,
            model="deepseek-v4-flash",
        )

    @patch("urllib.request.urlopen")
    def test_normal_response_uses_json_output_without_leaking_key(self, urlopen):
        urlopen.return_value = _Response(
            {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "model": "deepseek-v4-flash",
            }
        )

        result = self._provider().complete(
            LLMRequest(system_prompt="return json", user_prompt="question")
        )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(result.text, '{"ok": true}')
        self.assertNotIn("secret-key", repr(result))

    @patch("urllib.request.urlopen", side_effect=TimeoutError())
    def test_timeout_is_normalized(self, _urlopen):
        with self.assertRaises(ProviderTimeoutError):
            self._provider().complete(LLMRequest("system", "user"))

    @patch("urllib.request.urlopen", side_effect=URLError("offline"))
    def test_network_failure_is_normalized(self, _urlopen):
        with self.assertRaises(ProviderUnavailableError):
            self._provider().complete(LLMRequest("system", "user"))

    @patch("urllib.request.urlopen")
    def test_http_error_does_not_expose_response_or_key(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://api.deepseek.com/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"secret upstream body"}'),
        )
        with self.assertRaises(ProviderUnavailableError) as raised:
            self._provider().complete(LLMRequest("system", "user"))
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("401", str(raised.exception))

    @patch("urllib.request.urlopen")
    def test_empty_or_invalid_response_is_normalized(self, urlopen):
        for payload in ({"choices": []}, {"choices": [{"message": {"content": ""}}]}):
            with self.subTest(payload=payload):
                urlopen.return_value = _Response(payload)
                with self.assertRaises(InvalidProviderOutputError):
                    self._provider().complete(LLMRequest("system", "user"))

    def test_missing_key_is_structured_configuration_error(self):
        with self.assertRaises(ConfigurationError):
            self._provider(api_key="").complete(LLMRequest("system", "user"))
