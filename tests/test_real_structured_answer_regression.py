from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
import uuid
from typing import Any


RUN_REAL_REGRESSION = (
    os.getenv(
        "RUN_REAL_STRUCTURED_REGRESSION",
        "",
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
    }
)

BASE_URL = os.getenv(
    "BANKINSIGHT_TEST_BASE_URL",
    "http://127.0.0.1:8512",
).rstrip("/")

REQUEST_TIMEOUT_SECONDS = int(
    os.getenv(
        "BANKINSIGHT_TEST_TIMEOUT_SECONDS",
        "150",
    )
)


@unittest.skipUnless(
    RUN_REAL_REGRESSION,
    (
        "设置 RUN_REAL_STRUCTURED_REGRESSION=1 "
        "后才运行真实结构化回答回归。"
    ),
)
class RealStructuredAnswerRegressionTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls) -> None:
        health_url = f"{BASE_URL}/health"

        try:
            with urllib.request.urlopen(
                health_url,
                timeout=10,
            ) as response:
                if response.status != 200:
                    raise RuntimeError(
                        "健康检查状态码异常："
                        f"{response.status}"
                    )
        except Exception as exc:
            raise RuntimeError(
                "真实回归后端不可用："
                f"{health_url}"
            ) from exc

    def _post_question(
        self,
        *,
        case_name: str,
        question: str,
    ) -> dict[str, Any]:
        request_body = json.dumps(
            {
                "question": question,
                "user_id": (
                    "real_structured_regression"
                ),
                "conversation_id": (
                    f"regression_{case_name}_"
                    f"{uuid.uuid4().hex}"
                ),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{BASE_URL}/api/v1/query",
            data=request_body,
            headers={
                "Content-Type": (
                    "application/json"
                ),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=(
                    REQUEST_TIMEOUT_SECONDS
                ),
            ) as response:
                response_text = (
                    response.read().decode(
                        "utf-8"
                    )
                )

                self.assertEqual(
                    response.status,
                    200,
                    response_text,
                )

        except urllib.error.HTTPError as exc:
            response_text = (
                exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
            )
            self.fail(
                f"{case_name}返回HTTP "
                f"{exc.code}：{response_text}"
            )

        except urllib.error.URLError as exc:
            self.fail(
                f"{case_name}请求失败：{exc}"
            )

        try:
            payload = json.loads(
                response_text
            )
        except json.JSONDecodeError as exc:
            self.fail(
                f"{case_name}返回内容不是JSON："
                f"{response_text}"
            )
            raise AssertionError from exc

        self.assertIsInstance(
            payload,
            dict,
        )

        return payload

    def _assert_success(
        self,
        *,
        payload: dict[str, Any],
        expected_answer_type: str,
        accepted_final_operators: set[str],
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        error = payload.get("error")

        self.assertIsNone(
            error,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

        answer = payload.get("answer")
        metadata = payload.get("metadata")

        self.assertIsInstance(
            answer,
            dict,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )
        self.assertIsInstance(
            metadata,
            dict,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

        assert isinstance(answer, dict)
        assert isinstance(metadata, dict)

        query_plan = metadata.get(
            "query_plan"
        )

        self.assertIsInstance(
            query_plan,
            dict,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

        assert isinstance(query_plan, dict)

        self.assertEqual(
            answer.get("answer_type"),
            expected_answer_type,
        )

        self.assertTrue(
            str(
                answer.get("headline") or ""
            ).strip(),
            "结构化回答缺少headline。",
        )
        self.assertTrue(
            str(
                answer.get("summary") or ""
            ).strip(),
            "结构化回答缺少summary。",
        )

        status = query_plan.get("status")

        self.assertIsInstance(
            status,
            dict,
        )
        assert isinstance(status, dict)

        self.assertEqual(
            status.get("code"),
            "executable",
        )

        operations = query_plan.get(
            "operations"
        )

        self.assertIsInstance(
            operations,
            list,
        )
        self.assertTrue(
            operations,
            "查询计划没有operations。",
        )

        assert isinstance(operations, list)

        final_operation = operations[-1]

        self.assertIsInstance(
            final_operation,
            dict,
        )
        assert isinstance(
            final_operation,
            dict,
        )

        final_operator = (
            final_operation.get(
                "operator_id"
            )
        )

        self.assertIn(
            final_operator,
            accepted_final_operators,
            (
                "最终算子不符合预期："
                f"{final_operator}；"
                "允许值为"
                f"{sorted(accepted_final_operators)}"
            ),
        )

        return (
            answer,
            query_plan,
            operations,
        )

    def _assert_table(
        self,
        *,
        answer: dict[str, Any],
        expected_columns: list[str],
        expected_row_count: int,
    ) -> list[list[Any]]:
        table = answer.get("table")

        self.assertIsInstance(
            table,
            dict,
        )
        assert isinstance(table, dict)

        self.assertEqual(
            table.get("columns"),
            expected_columns,
        )

        rows = table.get("rows")

        self.assertIsInstance(
            rows,
            list,
        )
        assert isinstance(rows, list)

        self.assertEqual(
            len(rows),
            expected_row_count,
        )

        for row in rows:
            self.assertIsInstance(
                row,
                list,
            )
            self.assertEqual(
                len(row),
                len(expected_columns),
            )

        return rows

    def test_direct_single_metric_value(
        self,
    ) -> None:
        payload = self._post_question(
            case_name="direct_single",
            question=(
                "江苏省I市农商行在"
                "2025-11-30的"
                "不良贷款率是多少？"
            ),
        )

        answer, _, _ = (
            self._assert_success(
                payload=payload,
                expected_answer_type=(
                    "direct_metric_values"
                ),
                accepted_final_operators={
                    "OP001",
                },
            )
        )

        rows = self._assert_table(
            answer=answer,
            expected_columns=[
                "指标",
                "数值",
                "单位",
            ],
            expected_row_count=1,
        )

        self.assertEqual(
            rows[0][0],
            "不良贷款率",
        )
        self.assertEqual(
            rows[0][2],
            "%",
        )
        self.assertEqual(
            answer.get("key_metrics"),
            [],
        )
        self.assertIsNone(
            answer.get("chart_spec")
        )

    def test_direct_multiple_metric_values(
        self,
    ) -> None:
        payload = self._post_question(
            case_name="direct_multiple",
            question=(
                "江苏省I市农商行在"
                "2025-11-30的"
                "不良贷款率和拨备覆盖率"
                "分别是多少？"
            ),
        )

        answer, _, _ = (
            self._assert_success(
                payload=payload,
                expected_answer_type=(
                    "direct_metric_values"
                ),
                accepted_final_operators={
                    "OP019",
                },
            )
        )

        rows = self._assert_table(
            answer=answer,
            expected_columns=[
                "指标",
                "数值",
                "单位",
            ],
            expected_row_count=2,
        )

        self.assertEqual(
            [
                row[0]
                for row in rows
            ],
            [
                "不良贷款率",
                "拨备覆盖率",
            ],
        )
        self.assertEqual(
            [
                row[2]
                for row in rows
            ],
            [
                "%",
                "%",
            ],
        )
        self.assertEqual(
            answer.get("key_metrics"),
            [],
        )
        self.assertIsNone(
            answer.get("chart_spec")
        )

    def test_target_multi_metric_ranking(
        self,
    ) -> None:
        payload = self._post_question(
            case_name=(
                "target_multi_metric_ranking"
            ),
            question=(
                "2025年底，江苏省M市农商行"
                "在规模（贷款）、质量（不良率）、"
                "效益（净利润）三方面排名"
                "各是多少？"
            ),
        )

        answer, _, _ = (
            self._assert_success(
                payload=payload,
                expected_answer_type="ranking",
                accepted_final_operators={
                    "OP019",
                    "OP011",
                    "OP012",
                    "OP013",
                },
            )
        )

        rows = self._assert_table(
            answer=answer,
            expected_columns=[
                "机构",
                "指标",
                "指标值",
                "单位",
                "全省排名",
                "排名口径",
            ],
            expected_row_count=3,
        )

        self.assertEqual(
            {
                row[1]
                for row in rows
            },
            {
                "各项贷款余额",
                "不良贷款率",
                "净利润",
            },
        )

        self.assertTrue(
            all(
                row[0]
                == "江苏省M市农商行"
                for row in rows
            )
        )

        for row in rows:
            self.assertRegex(
                str(row[4]),
                r"^第\d+名$",
            )

        self.assertEqual(
            answer.get("key_metrics"),
            [],
        )
        self.assertIsNone(
            answer.get("chart_spec")
        )

    def test_deposit_balance_top_three(
        self,
    ) -> None:
        payload = self._post_question(
            case_name="deposit_top_three",
            question=(
                "2025年底，全省13家农商行"
                "各项存款余额排名前三的"
                "是哪些机构？"
            ),
        )

        answer, _, _ = (
            self._assert_success(
                payload=payload,
                expected_answer_type="ranking",
                accepted_final_operators={
                    "OP013",
                    "OP019",
                },
            )
        )

        rows = self._assert_table(
            answer=answer,
            expected_columns=[
                "机构",
                "各项存款余额",
                "单位",
                "全省排名",
                "排名口径",
            ],
            expected_row_count=3,
        )

        self.assertEqual(
            [
                row[0]
                for row in rows
            ],
            [
                "江苏省C市农商行",
                "江苏省G市农商行",
                "江苏省F市农商行",
            ],
        )
        self.assertEqual(
            [
                row[3]
                for row in rows
            ],
            [
                "第1名",
                "第2名",
                "第3名",
            ],
        )
        self.assertTrue(
            all(
                row[2] == "亿元"
                for row in rows
            )
        )

        chart = answer.get("chart_spec")

        self.assertIsInstance(
            chart,
            dict,
        )
        assert isinstance(chart, dict)

        self.assertEqual(
            chart.get("chart_type"),
            "bar",
        )
        self.assertEqual(
            chart.get("categories"),
            [
                "江苏省C市农商行",
                "江苏省G市农商行",
                "江苏省F市农商行",
            ],
        )
        self.assertEqual(
            answer.get("key_metrics"),
            [],
        )

    def test_npl_rate_bottom_four(
        self,
    ) -> None:
        payload = self._post_question(
            case_name="npl_bottom_four",
            question=(
                "2025年底，全省13家农商行中，"
                "不良贷款率控制得最差的"
                "4家机构是哪几家？"
            ),
        )

        answer, _, _ = (
            self._assert_success(
                payload=payload,
                expected_answer_type="ranking",
                accepted_final_operators={
                    "OP013",
                    "OP019",
                },
            )
        )

        rows = self._assert_table(
            answer=answer,
            expected_columns=[
                "机构",
                "不良贷款率",
                "单位",
                "全省排名",
                "排名口径",
            ],
            expected_row_count=4,
        )

        self.assertEqual(
            [
                row[0]
                for row in rows
            ],
            [
                "江苏省F市农商行",
                "江苏省H市农商行",
                "江苏省I市农商行",
                "江苏省D市农商行",
            ],
        )
        self.assertEqual(
            [
                row[3]
                for row in rows
            ],
            [
                "第10名",
                "第11名",
                "第12名",
                "第13名",
            ],
        )
        self.assertTrue(
            all(
                row[2] == "%"
                for row in rows
            )
        )
        self.assertTrue(
            all(
                row[4] == "低值优先"
                for row in rows
            )
        )

        chart = answer.get("chart_spec")

        self.assertIsInstance(
            chart,
            dict,
        )
        assert isinstance(chart, dict)

        self.assertEqual(
            chart.get("chart_type"),
            "bar",
        )
        self.assertEqual(
            chart.get("categories"),
            [
                "江苏省F市农商行",
                "江苏省H市农商行",
                "江苏省I市农商行",
                "江苏省D市农商行",
            ],
        )
        self.assertEqual(
            answer.get("key_metrics"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
