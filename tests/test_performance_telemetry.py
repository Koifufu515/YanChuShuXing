import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.adapters.planning.llm_query_planner import LLMQueryPlanner
from app.application.models import (
    LLMCallTelemetry,
    LLMResponse,
    LLMUsage,
)
from scripts.performance.profile_one_query import (
    build_profile,
    main,
    render_text,
    summarize_profiles,
)


SCHEMA = {
    "type": "object",
    "required": ["status", "operations", "checks"],
    "properties": {
        "status": {"type": "object"},
        "operations": {"type": "array"},
        "checks": {"type": "array"},
    },
}
VALID_PLAN = {
    "status": {"code": "executable"},
    "operations": [{"step": 1}],
    "checks": [],
}


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, _request):
        return self.responses.pop(0)


def response(text, latency, prompt_tokens):
    return LLMResponse(
        text=json.dumps(text),
        model="fake-model",
        latency_ms=latency,
        telemetry=LLMCallTelemetry(
            latency_ms=latency,
            request_body_bytes=321,
            response_body_bytes=123,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                prompt_cache_hit_tokens=prompt_tokens - 1,
                prompt_cache_miss_tokens=1,
                completion_tokens=5,
                total_tokens=prompt_tokens + 5,
            ),
        ),
    )


class PlannerTelemetryTest(unittest.TestCase):
    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_initial_success_has_no_repair_metrics(self, _validate):
        planner = LLMQueryPlanner(
            FakeProvider([response(VALID_PLAN, 7.5, 10)]),
            "prompt",
            SCHEMA,
            {},
            20,
        )

        result = planner.plan("测试")

        self.assertTrue(result.success)
        self.assertFalse(result.repair_attempted)
        self.assertEqual(result.latency_ms, 7.5)
        self.assertEqual(result.performance.initial.llm.usage.prompt_tokens, 10)
        self.assertIsNone(result.performance.repair)
        self.assertGreaterEqual(result.performance.initial.parse_ms, 0)
        self.assertGreaterEqual(result.performance.initial.schema_validation_ms, 0)
        self.assertGreaterEqual(result.performance.initial.business_validation_ms, 0)

    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_repair_metrics_and_tokens_are_separate(self, _validate):
        invalid = {"status": {"code": "executable"}, "checks": []}
        planner = LLMQueryPlanner(
            FakeProvider(
                [response(invalid, 7.5, 10), response(VALID_PLAN, 3.25, 20)]
            ),
            "prompt",
            SCHEMA,
            {},
            20,
        )

        result = planner.plan("测试")

        self.assertTrue(result.success)
        self.assertTrue(result.repair_attempted)
        self.assertEqual(result.latency_ms, 10.75)
        self.assertEqual(result.performance.initial.llm.usage.prompt_tokens, 10)
        self.assertEqual(result.performance.repair.llm.usage.prompt_tokens, 20)
        self.assertEqual(result.query_plan, VALID_PLAN)
        self.assertIn("performance", asdict(result))

    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_invalid_repair_json_keeps_original_failure(self, _validate):
        invalid = {"status": {"code": "executable"}, "checks": []}
        bad_repair = LLMResponse("not-json", "fake-model", 3)
        planner = LLMQueryPlanner(
            FakeProvider([response(invalid, 5, 10), bad_repair]),
            "prompt",
            SCHEMA,
            {},
            20,
        )

        result = planner.plan("测试")

        self.assertFalse(result.success)
        self.assertTrue(result.repair_attempted)
        self.assertEqual(result.latency_ms, 8)
        self.assertIsNotNone(result.performance.repair)

    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_repair_that_is_still_invalid_remains_failed(self, _validate):
        first_invalid = {"status": {"code": "executable"}, "checks": []}
        second_invalid = {"status": {"code": "executable"}, "operations": []}
        planner = LLMQueryPlanner(
            FakeProvider(
                [response(first_invalid, 5, 10), response(second_invalid, 3, 20)]
            ),
            "prompt",
            SCHEMA,
            {},
            20,
        )

        result = planner.plan("测试")

        self.assertFalse(result.success)
        self.assertTrue(result.repair_attempted)
        self.assertEqual(result.query_plan, second_invalid)
        self.assertEqual(result.latency_ms, 8)


class PerformanceReportTest(unittest.TestCase):
    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_text_and_json_profiles_are_safe_and_complete(self, _validate):
        planner = LLMQueryPlanner(
            FakeProvider([response(VALID_PLAN, 7.5, 10)]),
            "prompt-with-secret",
            SCHEMA,
            {},
            20,
        )
        profile = build_profile(planner.plan("official question"), 9.0)
        report = {"summary": summarize_profiles([profile]), "runs": [profile]}

        text = render_text(report)
        encoded = json.dumps(report, ensure_ascii=False)

        self.assertIn("模型：fake-model", text)
        self.assertIn("初次 LLM 耗时", text)
        self.assertIn("operation_count", encoded)
        self.assertNotIn("official question", encoded)
        self.assertNotIn("prompt-with-secret", encoded)
        self.assertNotIn("Authorization", encoded)
        self.assertNotIn("Bearer", encoded)

    def test_missing_api_key_returns_clear_error(self):
        settings = SimpleNamespace(llm_api_key="")
        stderr = io.StringIO()
        with patch(
            "scripts.performance.profile_one_query._load_settings",
            return_value=settings,
        ), redirect_stderr(stderr):
            exit_code = main(["--question", "测试"])

        self.assertEqual(exit_code, 2)
        self.assertIn("BANKINSIGHT_LLM_API_KEY", stderr.getvalue())

    @patch(
        "app.adapters.planning.llm_query_planner.validate_business_rules",
        return_value=[],
    )
    def test_cli_writes_parseable_json_and_text_without_network(self, _validate):
        planner = LLMQueryPlanner(
            FakeProvider([response(VALID_PLAN, 7.5, 10)]),
            "prompt",
            SCHEMA,
            {},
            20,
        )
        settings = SimpleNamespace(
            llm_api_key="test-only-key",
            llm_base_url="https://example.invalid",
            llm_model="fake-model",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "profile.json"
            text_path = Path(temp_dir) / "profile.txt"
            with patch(
                "scripts.performance.profile_one_query._load_settings",
                return_value=settings,
            ), patch(
                "scripts.performance.profile_one_query.DeepSeekLLMProvider",
                return_value=object(),
            ), patch(
                "app.bootstrap.container._build_query_planner",
                return_value=planner,
            ):
                exit_code = main(
                    [
                        "--question",
                        "测试",
                        "--json-output",
                        str(json_path),
                        "--text-output",
                        str(text_path),
                    ]
                )

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["summary"]["successful_runs"], 1)
            self.assertIn("单题查询规划性能报告", text_path.read_text(encoding="utf-8"))
            self.assertNotIn("test-only-key", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
