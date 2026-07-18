import unittest

from evaluation.normalization import (
    RULES_VERSION,
    Number,
    extract_numbers,
    extract_org_names,
    normalize_date_expression,
    normalize_text,
)


class NormalizeTextTest(unittest.TestCase):
    def test_fullwidth_and_thousand_separators(self) -> None:
        self.assertEqual(normalize_text("１，２３４．５％"), "1234.5%")
        self.assertEqual(normalize_text("金额 1,234,567.89 元"), "金额 1234567.89 元")


class ExtractNumbersTest(unittest.TestCase):
    def test_amount_units_converted_to_yuan(self) -> None:
        numbers = extract_numbers("余额为1.5亿元，另有200万元和300元")
        self.assertEqual(
            numbers,
            [
                Number(value=150_000_000.0, kind="amount"),
                Number(value=2_000_000.0, kind="amount"),
                Number(value=300.0, kind="amount"),
            ],
        )

    def test_percent_vs_percent_point(self) -> None:
        numbers = extract_numbers("不良率为1.23%，比上月下降0.1个百分点")
        self.assertEqual(
            numbers,
            [
                Number(value=1.23, kind="percent"),
                Number(value=0.1, kind="percent_point"),
            ],
        )

    def test_plain_numbers_and_counts(self) -> None:
        numbers = extract_numbers("共有13家机构，排名第2")
        self.assertEqual(
            numbers,
            [Number(value=13.0, kind="plain"), Number(value=2.0, kind="plain")],
        )

    def test_no_numbers(self) -> None:
        self.assertEqual(extract_numbers("没有数值"), [])


class NormalizeDateTest(unittest.TestCase):
    def test_iso_kept(self) -> None:
        self.assertEqual(normalize_date_expression("2025-12-31"), "2025-12-31")

    def test_chinese_full_date(self) -> None:
        self.assertEqual(normalize_date_expression("2025年12月31日"), "2025-12-31")

    def test_month_end_expressions(self) -> None:
        self.assertEqual(normalize_date_expression("2025年12月末"), "2025-12-31")
        self.assertEqual(normalize_date_expression("2025年6月底"), "2025-06-30")
        self.assertEqual(normalize_date_expression("2024年2月末"), "2024-02-29")

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(normalize_date_expression("最近一段时间"))


class ExtractOrgNamesTest(unittest.TestCase):
    def test_extracts_in_order_without_duplicates(self) -> None:
        text = "排名依次为测试省甲市农商行、测试省乙市农商行，其中测试省甲市农商行领先"
        self.assertEqual(
            extract_org_names(text),
            ["测试省甲市农商行", "测试省乙市农商行"],
        )

    def test_rules_version_present(self) -> None:
        self.assertTrue(RULES_VERSION.startswith("norm-"))


if __name__ == "__main__":
    unittest.main()
