from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.scorer import (
    UNIT_ALIASES,
    build_scoring_summary,
    extract_catalog_ids,
    extract_numeric_atoms,
    load_catalog,
    normalize_unit,
    normalize_text,
    score_record,
    score_run,
)


def make_context(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "institutions": [
                    {"institution_id": "ORG001", "institution_name": "江苏省A市农商行"},
                    {"institution_id": "ORG004", "institution_name": "江苏省D市农商行"},
                    {"institution_id": "ORG010", "institution_name": "江苏省J市农商行"},
                ],
                "metrics": [
                    {"metric_id": "ZB001", "name": "各项存款余额", "unit": "亿元"},
                    {"metric_id": "ZB013", "name": "不良贷款率", "unit": "%"},
                    {"metric_id": "ZB015", "name": "拨备覆盖率", "unit": "%"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def base_record(**overrides):
    record = {
        "run_id": "train",
        "sequence": 1,
        "revision": 1,
        "question_id": "TRAIN-S-01",
        "split": "TRAIN",
        "question_type": "单值",
        "difficulty": "简单",
        "question": "测试问题",
        "expected_answer": "江苏省A市农商行2025-06-15：42.02亿元。",
        "comparison_status": "not_scored",
        "run_status": "success",
        "plan_status": "executable",
        "columns": [
            "institution_id",
            "institution_name",
            "date",
            "metric_id",
            "metric_name",
            "metric_value",
            "unit",
        ],
        "rows": [["ORG001", "江苏省A市农商行", "2025-06-15", "ZB001", "各项存款余额", 42.02, "亿元"]],
        "summary": "江苏省A市农商行2025-06-15：42.02亿元。",
        "error": None,
        "metadata": {},
    }
    record.update(overrides)
    return record


class EvaluationScorerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.context = self.root / "context.json"
        make_context(self.context)
        self.catalog = load_catalog(self.context)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_single_value_passes(self):
        scored = score_record(base_record(), self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")
        self.assertEqual(scored["comparison_score"], 1.0)

    def test_wrong_numeric_value_fails(self):
        record = base_record(
            rows=[["ORG001", "江苏省A市农商行", "2025-06-15", "ZB001", "各项存款余额", 41.02, "亿元"]],
            summary="江苏省A市农商行2025-06-15：41.02亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertTrue(scored["comparison"]["components"]["numbers"]["missing"])

    def test_missing_second_metric_fails(self):
        record = base_record(
            question="不良贷款率和拨备覆盖率分别是多少？",
            expected_answer="不良贷款率1.45%，拨备覆盖率155.85%。",
            columns=["metric_id", "metric_name", "metric_value", "unit"],
            rows=[["ZB013", "不良贷款率", 1.45, "%"]],
            summary="不良贷款率1.45%。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertTrue(
            scored["comparison"]["components"]["numbers"]["missing"]
        )

    def test_structured_non_executable_status_passes(self):
        record = base_record(
            expected_answer="基期日期早于正式数据范围，数据不可用。",
            run_status="non_executable",
            plan_status="data_unavailable",
            rows=[],
            columns=[],
            summary=None,
            error={"code": "DATA_UNAVAILABLE", "message": "超出数据范围"},
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")
        self.assertEqual(scored["comparison"]["mode"], "structured_status")

    def test_structured_status_mismatch_fails(self):
        record = base_record(
            expected_answer="需要补充比较基准后才能判断。",
            run_status="non_executable",
            plan_status="pending_project_definition",
            rows=[],
            columns=[],
            summary=None,
            error={"code": "PENDING_PROJECT_DEFINITION", "message": "待定义"},
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")

    def test_ranking_fact_detects_wrong_rank(self):
        record = base_record(
            question="全省不良贷款率排名如何？",
            expected_answer="江苏省J市农商行0.77%，第1名；江苏省D市农商行1.62%，第13名。",
            columns=["institution_id", "institution_name", "metric_value", "unit", "rank"],
            rows=[
                ["ORG010", "江苏省J市农商行", 0.77, "%", 2],
                ["ORG004", "江苏省D市农商行", 1.62, "%", 13],
            ],
            summary="江苏省J市农商行0.77%，第2名；江苏省D市农商行1.62%，第13名。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertEqual(
            scored["comparison"]["components"]["ranks"]["missing"],
            [1],
        )

    def test_extra_detail_does_not_make_correct_answer_fail(self):
        record = base_record(
            expected_answer="趋势判断：存在波动。",
            columns=["date", "metric_value", "unit", "trend"],
            rows=[
                ["2025-01-01", 90.12, "亿元", "存在波动"],
                ["2025-01-02", 90.35, "亿元", "存在波动"],
            ],
            summary="趋势判断：存在波动。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_unstructured_answer_is_marked_review(self):
        record = base_record(
            expected_answer="整体表现较好。",
            rows=[],
            columns=[],
            summary="经营情况总体稳健。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "review")
        self.assertIsNone(scored["comparison_score"])


    def test_supporting_parenthetical_numbers_are_optional(self):
        record = base_record(
            question="江苏省C市农商行比江苏省G市农商行的存款多多少？",
            expected_answer=(
                "多4.72亿（江苏省C市农商行115.75亿，"
                "江苏省G市农商行111.03亿）"
            ),
            columns=["value", "unit"],
            rows=[[4.72, "亿元"]],
            summary="计算结果为4.72亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_negative_value_encodes_decrease(self):
        record = base_record(
            question="净利润和年初相比变化了多少？",
            expected_answer="下降17.43万元",
            columns=["value", "unit"],
            rows=[[-17.43, "万元"]],
            summary="计算结果为-17.43万元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")
        self.assertIn(
            "summary_missing_semantic_direction",
            scored["quality_flags"],
        )

    def test_count_filter_direction_is_not_required(self):
        record = base_record(
            question="有多少家农商行的贷款余额超过全省平均值？",
            expected_answer="7家超过全省均值（59.20亿元）",
            columns=["count", "unit"],
            rows=[[7, "家"]],
            summary="计数结果为7家。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_percentage_point_unit_is_factually_compatible(self):
        record = base_record(
            question="不良贷款率比上个月底变动了多少？",
            expected_answer="下降0.06%",
            columns=["value", "unit"],
            rows=[[-0.06, "百分点"]],
            summary="计算结果为-0.06百分点。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_score_run_uses_latest_revision_and_writes_reports(self):
        run_root = self.root / "run"
        run_root.mkdir()
        records = [
            base_record(revision=1, summary="旧结果41.00亿元。"),
            base_record(revision=2),
        ]
        with (run_root / "results.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        summary = score_run(run_root, self.context)

        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["comparison_status_counts"], {"pass": 1})
        self.assertTrue((run_root / "scored_results.jsonl").is_file())
        self.assertTrue((run_root / "scoring_summary.json").is_file())
        self.assertTrue((run_root / "scoring_failures.jsonl").is_file())

    def test_summary_counts_manual_review(self):
        summary = build_scoring_summary(
            [
                {"comparison_status": "pass", "difficulty": "简单", "question_type": "单值"},
                {
                    "comparison_status": "fail",
                    "difficulty": "困难",
                    "question_type": "排名",
                    "comparison": {"components": {"numbers": {"passed": False}}},
                },
                {"comparison_status": "review", "difficulty": "困难", "question_type": "综合"},
            ]
        )
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["manual_review_total"], 1)
        self.assertEqual(summary["missing_component_counts"], {"numbers": 1})


    # ── 类别1: 元/万元/亿元换算 ──────────────────────────

    def test_yi_to_wan_conversion_passes(self):
        """亿元与万元跨单位等价换算"""
        record = base_record(
            question="各项存款余额是多少？",
            expected_answer="1.5亿元",
            columns=["metric_value", "unit"],
            rows=[[15000, "万元"]],
            summary="15000万元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_wan_to_yuan_conversion_passes(self):
        """万元与元跨单位等价换算"""
        record = base_record(
            question="净利润是多少？",
            expected_answer="3万元",
            columns=["value", "unit"],
            rows=[[30000, "元"]],
            summary="30000元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_yuan_to_yi_conversion_passes(self):
        """元与亿元跨单位等价换算"""
        record = base_record(
            question="总资产是多少？",
            expected_answer="2亿元",
            columns=["value", "unit"],
            rows=[[200000000, "元"]],
            summary="200000000元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 类别2: 机构名称、编号和简称 ──────────────────────

    def test_institution_short_name_alias_matches(self):
        """简称 A市 应匹配到 ORG001"""
        record = base_record(
            question="A市的不良贷款率是多少？",
            expected_answer="1.45%",
            columns=["institution_id", "metric_value", "unit"],
            rows=[["ORG001", 1.45, "%"]],
            summary="A市农商行不良贷款率1.45%。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_institution_wrong_org_fails(self):
        """系统输出 ORG010 的值但预期是 ORG001 → entities 不匹配"""
        record = base_record(
            question="哪家机构的不良贷款率最低？",
            expected_answer="江苏省A市农商行0.77%，第1名",
            columns=["institution_id", "institution_name", "metric_value", "unit", "rank"],
            rows=[["ORG010", "江苏省J市农商行", 0.88, "%", 2]],
            summary="江苏省J市农商行0.88%，第2名。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")

    def test_institution_id_in_answer_matches(self):
        """预期答案含 ORG001 ID 可与机构名互认"""
        record = base_record(
            question="ORG001的存款余额？",
            expected_answer="ORG001：42.02亿元",
            columns=["institution_id", "metric_value", "unit"],
            rows=[["ORG001", 42.02, "亿元"]],
            summary="ORG001各项存款余额42.02亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 类别3: 列表/集合题的顺序规则 ─────────────────────

    def test_multi_detail_reversed_order_passes(self):
        """列表结果顺序无关 A:1.45 B:155.85 与 B:155.85 A:1.45 等价"""
        record = base_record(
            question="不良贷款率和拨备覆盖率分别是多少？",
            expected_answer="不良贷款率1.45%，拨备覆盖率155.85%。",
            columns=["metric_id", "metric_value", "unit"],
            rows=[
                ["ZB015", 155.85, "%"],
                ["ZB013", 1.45, "%"],
            ],
            summary="拨备覆盖率155.85%，不良贷款率1.45%。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_multi_detail_missing_one_value_fails(self):
        """期望3个数值但系统只返回2个 → numbers缺失"""
        record = base_record(
            question="分别列出存款、贷款和不良贷款率。",
            expected_answer="存款42.02亿元，贷款33.52亿元，不良贷款率1.45%。",
            columns=["metric_id", "metric_value", "unit"],
            rows=[
                ["ZB001", 42.02, "亿元"],
                ["ZB002", 33.52, "亿元"],
            ],
            summary="存款42.02亿元，贷款33.52亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertTrue(scored["comparison"]["components"]["numbers"]["missing"])

    def test_multi_detail_all_values_present_passes(self):
        """期望3个数值全部返回 → pass"""
        record = base_record(
            question="分别列出存款、贷款和不良贷款率。",
            expected_answer="存款42.02亿元，贷款33.52亿元，不良贷款率1.45%。",
            columns=["metric_id", "metric_value", "unit"],
            rows=[
                ["ZB001", 42.02, "亿元"],
                ["ZB002", 33.52, "亿元"],
                ["ZB013", 1.45, "%"],
            ],
            summary="存款42.02亿元，贷款33.52亿元，不良贷款率1.45%。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 类别4: 综合题完整性 ──────────────────────────────

    def test_comprehensive_multi_component_pass(self):
        """综合题激活 entities+numbers+directions 全部匹配"""
        record = base_record(
            question="江苏省A市农商行的经营绩效如何？哪个指标增长最快？",
            question_type="综合",
            difficulty="复杂",
            expected_answer=(
                "江苏省A市农商行各项存款余额42.02亿元，较年初增加4.17亿元；"
                "不良贷款率1.45%，较年初下降0.12个百分点。"
            ),
            columns=["institution_id", "institution_name", "date", "metric_id",
                     "metric_name", "metric_value", "unit", "change", "change_unit"],
            rows=[
                ["ORG001", "江苏省A市农商行", "2025-06-15", "ZB001",
                 "各项存款余额", 42.02, "亿元", 4.17, "亿元"],
                ["ORG001", "江苏省A市农商行", "2025-06-15", "ZB013",
                 "不良贷款率", 1.45, "%", -0.12, "个百分点"],
            ],
            summary=(
                "江苏省A市农商行2025-06-15各项存款余额42.02亿元，"
                "较年初增加4.17亿元。不良贷款率1.45%，"
                "较年初下降0.12个百分点。"
            ),
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_comprehensive_missing_direction_fails(self):
        """综合题数值对但方向缺失 → fail"""
        record = base_record(
            question="江苏省A市农商行的经营绩效如何？",
            question_type="综合",
            difficulty="复杂",
            expected_answer="各项存款余额42.02亿元，较年初增加4.17亿元。",
            columns=["institution_id", "institution_name", "date", "metric_id",
                     "metric_name", "metric_value", "unit", "change", "change_unit"],
            rows=[
                ["ORG001", "江苏省A市农商行", "2025-06-15", "ZB001",
                 "各项存款余额", 42.02, "亿元", -4.17, "亿元"],
            ],
            summary="江苏省A市农商行各项存款余额42.02亿元，较年初下降4.17亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")

    def test_top_three_ranking_correct_passes(self):
        """排名前三：entity_facts 包含3个机构且名次1,2,3"""
        record = base_record(
            question="全省存款排名前三的机构是哪些？",
            expected_answer=(
                "第1名江苏省A市农商行42.02亿元；"
                "第2名江苏省D市农商行38.50亿元；"
                "第3名江苏省J市农商行35.10亿元。"
            ),
            columns=["institution_id", "institution_name", "metric_value", "unit", "rank"],
            rows=[
                ["ORG001", "江苏省A市农商行", 42.02, "亿元", 1],
                ["ORG004", "江苏省D市农商行", 38.50, "亿元", 2],
                ["ORG010", "江苏省J市农商行", 35.10, "亿元", 3],
            ],
            summary="排名前三：A市42.02亿元，D市38.50亿元，J市35.10亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 附加: 零值/空值/系统失败 ──────────────────────────

    def test_zero_value_handling(self):
        """零值指标应与预期0匹配"""
        record = base_record(
            question="净利润是多少？",
            expected_answer="0元",
            columns=["value", "unit"],
            rows=[[0, "元"]],
            summary="净利润为0元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    def test_null_summary_with_error_is_failure(self):
        """null summary + error → 运行失败"""
        record = base_record(
            summary=None,
            rows=[],
            columns=[],
            run_status="exception",
            error={"code": "RUNNER_EXCEPTION", "message": "Connection reset"},
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")

    def test_clarification_required_status_matches(self):
        """需要澄清 的非执行状态正确匹配"""
        record = base_record(
            expected_answer="需要补充比较基准后才能判断。",
            run_status="non_executable",
            plan_status="clarification_required",
            rows=[],
            columns=[],
            summary=None,
            error={"code": "CLARIFICATION_REQUIRED", "message": "需澄清"},
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")
        self.assertEqual(scored["comparison"]["mode"], "structured_status")


    def test_data_consistency_concern_flagged(self):
        """数值接近但超出容差 → data_consistency_concern 质量标记"""
        record = base_record(
            question="各项存款余额是多少？",
            expected_answer="42.02亿元",
            columns=["metric_value", "unit"],
            rows=[[41.50, "亿元"]],
            summary="各项存款余额41.50亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertIn("data_consistency_concern", scored["quality_flags"])

    def test_data_consistency_not_flagged_for_large_deviation(self):
        """数值严重偏离 → 不标记 data_consistency_concern"""
        record = base_record(
            question="各项存款余额是多少？",
            expected_answer="42.02亿元",
            columns=["metric_value", "unit"],
            rows=[[999.99, "亿元"]],
            summary="各项存款余额999.99亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "fail")
        self.assertNotIn("data_consistency_concern", scored["quality_flags"])


if __name__ == "__main__":
    unittest.main()
