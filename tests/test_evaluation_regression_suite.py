from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.scorer import load_catalog, score_record


CONTEXT_PATH = Path(__file__).resolve().parent / "evaluation" / "context_regression.json"


class RegressionSuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CONTEXT_PATH)

    def _base_record(self, **overrides):
        record = {
            "run_id": "regression",
            "sequence": 1,
            "revision": 1,
            "question_id": "REG-001",
            "split": "REG",
            "question_type": "单值",
            "difficulty": "简单",
            "question": "测试问题",
            "expected_answer": "",
            "comparison_status": "not_scored",
            "run_status": "success",
            "plan_status": "executable",
            "columns": [],
            "rows": [],
            "summary": "",
            "error": None,
            "metadata": {},
        }
        record.update(overrides)
        return record

    # ── 场景1: 长指标名与短别名重叠 ──────────────────────
    def test_long_short_metric_name_alias_overlap(self):
        """‘不良率’（民间简称）应与‘不良贷款率’通过metric别名匹配"""
        record = self._base_record(
            question_id="REG-R01",
            question="A市的不良率是多少？",
            expected_answer="江苏省A市农商行不良贷款率1.45%。",
            question_type="单值",
            columns=["institution_id", "metric_value", "unit"],
            rows=[["ORG001", 1.45, "%"]],
            summary="江苏省A市农商行不良贷款率1.45%。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景2: 复合指标公式括号 ────────────────────────
    def test_composite_formula_brackets_do_not_break_scoring(self):
        """(A+B)/C 括号表达式不影响数值提取"""
        record = self._base_record(
            question_id="REG-R02",
            question="A市和B市的存款合计是多少？",
            expected_answer="A市与B市合计85.54亿元。",
            question_type="单值",
            columns=["value", "unit"],
            rows=[[85.54, "亿元"]],
            summary="合计(A市+B市)为85.54亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景3: 主观“大不大”问法 ────────────────────────
    def test_subjective_big_question_not_misclassified(self):
        """‘贷款规模大不大’属于主观模糊问法，评分器应正常处理数值"""
        record = self._base_record(
            question_id="REG-R03",
            question="A市农商行的贷款规模大不大？",
            expected_answer="各项贷款余额33.52亿元。",
            question_type="单值",
            columns=["institution_id", "metric_value", "unit"],
            rows=[["ORG001", 33.52, "亿元"]],
            summary="江苏省A市农商行各项贷款余额为33.52亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景4: 经营绩效排名 vs 纯数值排名 ──────────────
    def test_performance_ranking_vs_numeric_ranking(self):
        """不良贷款率 越低越好 (performance direction)，评分器应识别方向"""
        record = self._base_record(
            question_id="REG-R04",
            question="全省哪家农商行控制得最好？",
            expected_answer="江苏省A市农商行不良贷款率0.77%，第1名。",
            question_type="排名",
            columns=["institution_id", "institution_name", "metric_value", "unit", "rank"],
            rows=[
                ["ORG001", "江苏省A市农商行", 0.77, "%", 1],
                ["ORG002", "江苏省B市农商行", 1.20, "%", 2],
            ],
            summary="A市农商行不良贷款率0.77%，控制得最好；B市1.20%，第2名。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景5: 上季度末 vs 较年初 ──────────────────────
    def test_quarter_end_vs_year_begin_date_parsing(self):
        """‘上季度末’和‘较年初’日期表达均应被正确提取"""
        record = self._base_record(
            question_id="REG-R05",
            question="A市上季度末的存款余额较年初变化了多少？",
            expected_answer="2025-03-31存款余额40.50亿元，较2025-01-01增加1.48亿元。",
            question_type="单值",
            columns=["institution_id", "date", "metric_value", "unit", "change", "change_unit"],
            rows=[["ORG001", "2025-03-31", 40.50, "亿元", 1.48, "亿元"]],
            summary="2025年3月31日存款余额40.50亿元，较年初增加1.48亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景6: 总量与分项核对 ──────────────────────────
    def test_total_vs_component_sum(self):
        """总量与分项之和的核对——要求三个分项全部存在"""
        record = self._base_record(
            question_id="REG-R06",
            question="A市、B市、C市的各项贷款余额分别是多少？",
            expected_answer=(
                "江苏省A市农商行33.52亿元；"
                "江苏省B市农商行28.10亿元；"
                "江苏省C市农商行25.30亿元。"
            ),
            question_type="综合",
            difficulty="普通",
            columns=["institution_id", "institution_name", "metric_value", "unit"],
            rows=[
                ["ORG001", "江苏省A市农商行", 33.52, "亿元"],
                ["ORG002", "江苏省B市农商行", 28.10, "亿元"],
                ["ORG003", "江苏省C市农商行", 25.30, "亿元"],
            ],
            summary="A市33.52亿元、B市28.10亿元、C市25.30亿元。",
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景7: 综合经营分析 ────────────────────────────
    def test_comprehensive_analysis_all_components_pass(self):
        """综合题需激活 entity_facts + numbers + directions 三个组件"""
        record = self._base_record(
            question_id="REG-R07",
            question="分析A市农商行的经营绩效，包括存款、贷款和不良贷款率。",
            question_type="综合",
            difficulty="复杂",
            expected_answer=(
                "江苏省A市农商行各项存款余额42.02亿元，较年初增加4.17亿元；"
                "各项贷款余额33.52亿元，较年初上升2.30亿元；"
                "不良贷款率1.45%，较年初下降0.12个百分点。"
            ),
            columns=["institution_id", "institution_name", "metric_name",
                     "metric_value", "unit", "change", "change_unit"],
            rows=[
                ["ORG001", "江苏省A市农商行", "各项存款余额", 42.02, "亿元", 4.17, "亿元"],
                ["ORG001", "江苏省A市农商行", "各项贷款余额", 33.52, "亿元", 2.30, "亿元"],
                ["ORG001", "江苏省A市农商行", "不良贷款率", 1.45, "%", -0.12, "个百分点"],
            ],
            summary=(
                "各项存款余额42.02亿元，较年初增加4.17亿元。"
                "各项贷款余额33.52亿元，较年初上升2.30亿元。"
                "不良贷款率1.45%，较年初下降0.12个百分点。"
            ),
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")

    # ── 场景8: 查询计划验证失败后的自动修复 ──────────────
    def test_plan_repair_attempted_does_not_affect_scoring(self):
        """repair_attempted=True 不应影响评分——只要最终 rows 正确即 pass"""
        record = self._base_record(
            question_id="REG-R08",
            question="A市2025-06-15的净利润是多少？",
            expected_answer="净利润128.35万元。",
            question_type="单值",
            columns=["institution_id", "date", "metric_value", "unit"],
            rows=[["ORG001", "2025-06-15", 128.35, "万元"]],
            summary="计江苏省A市农商行净利润128.35万元。",
            metadata={"plan_repair_attempted": True},
        )
        scored = score_record(record, self.catalog)
        self.assertEqual(scored["comparison_status"], "pass")


if __name__ == "__main__":
    unittest.main()
