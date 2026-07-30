from __future__ import annotations

import argparse
import calendar
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "data" / "private" / "evaluation" / "runs"
DEFAULT_CONTEXT = PROJECT_ROOT / "config" / "query_planner" / "query_planner_context.json"

STATUS_CODE_TO_ERROR = {
    "clarification_required": "CLARIFICATION_REQUIRED",
    "pending_project_definition": "PENDING_PROJECT_DEFINITION",
    "data_unavailable": "DATA_UNAVAILABLE",
}

STATUS_PATTERNS = {
    "clarification_required": (
        r"需要澄清",
        r"需澄清",
        r"需要补充",
        r"请补充",
        r"请问.{0,40}(标准|口径|基准|比较)",
        r"无法判断.{0,40}(标准|口径|基准|比较)",
    ),
    "pending_project_definition": (
        r"待项目确认",
        r"口径待定义",
        r"待定义",
        r"业务概念.{0,20}待确认",
        r"无法自行展开",
    ),
    "data_unavailable": (
        r"数据不可用",
        r"超出.{0,20}数据范围",
        r"早于.{0,20}数据范围",
        r"晚于.{0,20}数据范围",
        r"缺少.{0,20}数据",
        r"无可用数据",
    ),
}

UNIT_ALIASES = {
    "％": "%",
    "百分比": "%",
    "亿元": "亿元",
    "亿": "亿元",
    "万元/网点": "万元/网点",
    "万元／网点": "万元/网点",
    "万元每网点": "万元/网点",
    "万元": "万元",
    "万": "万元",
    "元": "元",
    "人": "人",
    "万元/人": "万元/人",
    "个百分点": "个百分点",
    "百分点": "个百分点",
    "%": "%",
    "户": "户",
    "家": "家",
    "天": "天",
    "条": "条",
    "笔": "笔",
    "个": "个",
    "网点": "网点",
}
UNIT_PATTERN = "|".join(
    sorted((re.escape(item) for item in UNIT_ALIASES), key=len, reverse=True)
)

DIRECTION_PATTERNS = {
    "increase": (r"增加", r"增长", r"上升", r"提高"),
    "decrease": (r"减少", r"下降", r"降低"),
    "unchanged": (r"保持不变", r"持平", r"未变", r"不变"),
    "above": (r"高于", r"超过", r"大于"),
    "below": (r"低于", r"少于", r"小于"),
    "fluctuation": (r"存在波动", r"波动"),
    "maximum": (r"最高", r"最大"),
    "minimum": (r"最低", r"最小"),
    "best": (r"最好", r"最优", r"控制得最好"),
    "worst": (r"最差", r"最弱", r"控制得最差"),
}

INTEGER_UNITS = frozenset({"户", "家", "天", "条", "笔", "个", "网点"})

_UNIT_CONVERSION = {
    "亿元": Decimal("100000000"),
    "万元": Decimal("10000"),
    "元": Decimal("1"),
}

_COMPATIBLE_UNIT_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"亿元", "万元", "元"}),
    frozenset({"%", "个百分点"}),
    frozenset({"万元", "万元/网点"}),
)


@dataclass(frozen=True)
class Catalog:
    institution_aliases: Mapping[str, tuple[str, ...]]
    metric_aliases: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class NumericAtom:
    value: Decimal
    unit: str | None
    raw: str


@dataclass(frozen=True)
class EntityFact:
    institution_id: str
    value: Decimal | None = None
    unit: str | None = None
    rank: int | None = None
    date: str | None = None


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_unit(value: object) -> str | None:
    return UNIT_ALIASES.get(normalize_text(value))


def decimal_value(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"结果文件不存在：{path}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path} 第{line_number}行不是合法JSON。") from exc
            if not isinstance(payload, dict):
                raise RuntimeError(f"{path} 第{line_number}行顶层必须是JSON对象。")
            records.append(payload)
    return records


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"无法序列化对象：{type(value).__name__}")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=_json_default)
                + "\n"
            )


def latest_records_by_question(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = record.get("question_id")
        if isinstance(question_id, str) and question_id:
            latest[question_id] = dict(record)
    return latest


def load_catalog(context_path: Path) -> Catalog:
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    institutions: dict[str, tuple[str, ...]] = {}
    for item in payload.get("institutions", []):
        institution_id = normalize_text(item.get("institution_id"))
        name = normalize_text(item.get("institution_name"))
        if not institution_id or not name:
            continue
        match = re.search(r"江苏省([A-Z])市农商行", name)
        aliases = {institution_id, name}
        if match:
            letter = match.group(1)
            aliases.update({f"{letter}市", f"{letter}市农商行", f"江苏省{letter}市"})
        institutions[institution_id] = tuple(sorted(aliases, key=len, reverse=True))

    metrics: dict[str, tuple[str, ...]] = {}
    for item in payload.get("metrics", []):
        metric_id = normalize_text(item.get("metric_id"))
        name = normalize_text(item.get("name"))
        if metric_id and name:
            metrics[metric_id] = (name, metric_id)

    return Catalog(institution_aliases=institutions, metric_aliases=metrics)


def infer_expected_status(expected_answer: str) -> str | None:
    text = normalize_text(expected_answer)
    matches = [
        status
        for status, patterns in STATUS_PATTERNS.items()
        if any(re.search(pattern, text) for pattern in patterns)
    ]
    return matches[0] if len(matches) == 1 else None


def actual_status(record: Mapping[str, Any]) -> str | None:
    plan_status = normalize_text(record.get("plan_status"))
    if plan_status:
        return plan_status

    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        query_plan = metadata.get("query_plan")
        if isinstance(query_plan, Mapping):
            status = query_plan.get("status")
            if isinstance(status, Mapping):
                code = normalize_text(status.get("code"))
                if code:
                    return code

    error = record.get("error")
    if isinstance(error, Mapping):
        code = normalize_text(error.get("code"))
        for status, error_code in STATUS_CODE_TO_ERROR.items():
            if code == error_code:
                return status
    return None


def _row_objects(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("rows")
    columns = record.get("columns")
    if not isinstance(rows, list):
        return []

    objects: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            objects.append(dict(row))
            continue
        if isinstance(row, (list, tuple)) and isinstance(columns, list):
            objects.append(
                {
                    str(column): row[index] if index < len(row) else None
                    for index, column in enumerate(columns)
                }
            )
    return objects


def _first_value(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def actual_text(record: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("summary",):
        value = record.get(key)
        if value:
            parts.append(normalize_text(value))

    for row in _row_objects(record):
        parts.append(
            " ".join(
                f"{key}={normalize_text(value)}"
                for key, value in row.items()
                if value is not None
            )
        )
        rank = row.get("rank")
        if rank is not None:
            parts.append(f"第{rank}名")
        value = _first_value(
            row,
            (
                "metric_value",
                "value",
                "difference",
                "change",
                "result_value",
                "share_percent",
                "count",
            ),
        )
        unit = _first_value(row, ("unit", "result_unit", "count_unit"))
        if value is not None and unit is not None:
            parts.append(f"{value}{unit}")

    error = record.get("error")
    if isinstance(error, Mapping):
        parts.append(normalize_text(error.get("code")))
        parts.append(normalize_text(error.get("message")))

    return "\n".join(item for item in parts if item)


def extract_catalog_ids(
    text: str,
    aliases: Mapping[str, Sequence[str]],
) -> set[str]:
    normalized = normalize_text(text)
    found: set[str] = set()
    for canonical_id, options in aliases.items():
        if any(option and option in normalized for option in options):
            found.add(canonical_id)
    return found


def extract_dates(text: str) -> set[str]:
    normalized = normalize_text(text)
    dates: set[str] = set()

    for year, month, day in re.findall(
        r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?",
        normalized,
    ):
        dates.add(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")

    for year in re.findall(r"(?<!\d)(20\d{2})年(?:底|年末)", normalized):
        dates.add(f"{int(year):04d}-12-31")

    for year in re.findall(r"(?<!\d)(20\d{2})年初", normalized):
        dates.add(f"{int(year):04d}-01-01")

    for year, quarter in re.findall(
        r"(?<!\d)(20\d{2})年([一二三四1234])季度末",
        normalized,
    ):
        quarter_map = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
        month = quarter_map[quarter] * 3
        day = calendar.monthrange(int(year), month)[1]
        dates.add(f"{int(year):04d}-{month:02d}-{day:02d}")

    for year, month in re.findall(
        r"(?<!\d)(20\d{2})年(\d{1,2})月(?:末|底)",
        normalized,
    ):
        day = calendar.monthrange(int(year), int(month))[1]
        dates.add(f"{int(year):04d}-{int(month):02d}-{day:02d}")

    for year, month in re.findall(
        r"(?<!\d)(20\d{2})[-/.](\d{1,2})(?![-/.\d])",
        normalized,
    ):
        day = calendar.monthrange(int(year), int(month))[1]
        dates.add(f"{int(year):04d}-{int(month):02d}-{day:02d}")

    return dates


def extract_ranks(text: str) -> set[int]:
    return {int(value) for value in re.findall(r"第\s*(\d+)\s*名", normalize_text(text))}


def extract_directions(text: str) -> set[str]:
    normalized = normalize_text(text)
    return {
        label
        for label, patterns in DIRECTION_PATTERNS.items()
        if any(re.search(pattern, normalized) for pattern in patterns)
    }


def _masked_numeric_text(text: str) -> str:
    normalized = normalize_text(text)
    patterns = (
        r"(?<!\d)20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?",
        r"(?<!\d)20\d{2}[-/.]\d{1,2}(?![-/.\d])",
        r"(?<!\d)20\d{2}年(?:底|年末|年初|全年)?",
        r"\b(?:ORG|ZB)\d+\b",
        r"第\s*\d+\s*名",
        r"(?:前|后|top|bottom)\s*\d+\s*名?",
    )
    for pattern in patterns:
        normalized = re.sub(pattern, " ", normalized)
    return normalized


def extract_numeric_atoms(text: str) -> list[NumericAtom]:
    masked = _masked_numeric_text(text)
    atoms: list[NumericAtom] = []
    occupied: list[tuple[int, int]] = []

    unit_regex = re.compile(rf"(?<![\dA-Za-z])(-?\d+(?:\.\d+)?)\s*({UNIT_PATTERN})")
    for match in unit_regex.finditer(masked):
        value = decimal_value(match.group(1))
        unit = normalize_unit(match.group(2))
        if value is not None:
            atoms.append(NumericAtom(value=value, unit=unit, raw=match.group(0)))
            occupied.append(match.span())

    def is_occupied(start: int, end: int) -> bool:
        return any(start < right and end > left for left, right in occupied)

    bare_regex = re.compile(r"(?<![\dA-Za-z])(-?\d+(?:\.\d+)?)(?![\dA-Za-z])")
    for match in bare_regex.finditer(masked):
        if is_occupied(*match.span()):
            continue
        value = decimal_value(match.group(1))
        if value is not None:
            atoms.append(NumericAtom(value=value, unit=None, raw=match.group(0)))
    return atoms


def numeric_tolerance(atom: NumericAtom) -> Decimal:
    if atom.unit in INTEGER_UNITS:
        return Decimal("0")
    return Decimal("0.011")


def numeric_atoms_match(
    expected: Sequence[NumericAtom],
    actual: Sequence[NumericAtom],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    used: set[int] = set()
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for expected_atom in expected:
        candidate_index: int | None = None
        candidate_distance: Decimal | None = None
        for index, actual_atom in enumerate(actual):
            if index in used:
                continue
            if expected_atom.unit is not None and actual_atom.unit != expected_atom.unit:
                continue
            distance = abs(expected_atom.value - actual_atom.value)
            if distance > numeric_tolerance(expected_atom):
                continue
            if candidate_distance is None or distance < candidate_distance:
                candidate_index = index
                candidate_distance = distance

        expected_payload = {
            "value": str(expected_atom.value),
            "unit": expected_atom.unit,
            "raw": expected_atom.raw,
        }
        if candidate_index is None:
            missing.append(expected_payload)
            continue

        used.add(candidate_index)
        actual_atom = actual[candidate_index]
        matched.append(
            {
                "expected": expected_payload,
                "actual": {
                    "value": str(actual_atom.value),
                    "unit": actual_atom.unit,
                    "raw": actual_atom.raw,
                },
            }
        )
    return matched, missing


def actual_entity_facts(
    record: Mapping[str, Any],
    catalog: Catalog,
) -> list[EntityFact]:
    facts: list[EntityFact] = []
    for row in _row_objects(record):
        row_text = " ".join(normalize_text(value) for value in row.values())
        institutions = extract_catalog_ids(row_text, catalog.institution_aliases)
        if len(institutions) != 1:
            continue
        institution_id = next(iter(institutions))
        value = decimal_value(
            _first_value(row, ("metric_value", "value", "difference", "change", "result_value"))
        )
        unit = normalize_unit(_first_value(row, ("unit", "result_unit")))
        rank_value = decimal_value(row.get("rank"))
        rank = int(rank_value) if rank_value is not None else None
        date_value = normalize_text(row.get("date"))
        date = next(iter(extract_dates(date_value)), None)
        facts.append(
            EntityFact(
                institution_id=institution_id,
                value=value,
                unit=unit,
                rank=rank,
                date=date,
            )
        )
    return facts


def expected_entity_facts(
    expected_answer: str,
    catalog: Catalog,
) -> list[EntityFact]:
    text = normalize_text(expected_answer)
    occurrences: list[tuple[int, int, str]] = []
    for institution_id, aliases in catalog.institution_aliases.items():
        best: tuple[int, int, str] | None = None
        for alias in aliases:
            match = re.search(re.escape(alias), text)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), match.end(), institution_id)
        if best is not None:
            occurrences.append(best)

    occurrences.sort()
    facts: list[EntityFact] = []
    for index, (start, end, institution_id) in enumerate(occurrences):
        next_start = occurrences[index + 1][0] if index + 1 < len(occurrences) else min(len(text), end + 160)
        segment = text[start:next_start]
        numbers = extract_numeric_atoms(segment)
        ranks = sorted(extract_ranks(segment))
        dates = sorted(extract_dates(segment))
        preferred = next((item for item in numbers if item.unit is not None), numbers[0] if numbers else None)
        facts.append(
            EntityFact(
                institution_id=institution_id,
                value=preferred.value if preferred else None,
                unit=preferred.unit if preferred else None,
                rank=ranks[0] if ranks else None,
                date=dates[0] if dates else None,
            )
        )
    return facts


def compare_entity_facts(
    expected_facts: Sequence[EntityFact],
    actual_facts: Sequence[EntityFact],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for expected in expected_facts:
        candidates = [
            actual
            for actual in actual_facts
            if actual.institution_id == expected.institution_id
        ]
        found = False
        for actual in candidates:
            if expected.rank is not None and actual.rank != expected.rank:
                continue
            if expected.date is not None and actual.date != expected.date:
                continue
            if expected.value is not None:
                if actual.value is None:
                    continue
                expected_atom = NumericAtom(expected.value, expected.unit, str(expected.value))
                if expected.unit is not None and actual.unit != expected.unit:
                    continue
                if abs(expected.value - actual.value) > numeric_tolerance(expected_atom):
                    continue
            found = True
            break
        if not found:
            missing.append(asdict(expected))
    return missing


def _component(expected_values: set[Any], actual_values: set[Any]) -> dict[str, Any]:
    missing = sorted(expected_values - actual_values, key=str)
    return {
        "expected": sorted(expected_values, key=str),
        "actual": sorted(actual_values, key=str),
        "missing": missing,
        "passed": not missing,
    }



def _query_plan(record: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    query_plan = metadata.get("query_plan")
    return query_plan if isinstance(query_plan, Mapping) else {}


def _output_definition(record: Mapping[str, Any]) -> Mapping[str, Any]:
    output = _query_plan(record).get("output")
    return output if isinstance(output, Mapping) else {}


def _strip_parenthetical_support(text: str) -> str:
    previous = normalize_text(text)
    while True:
        current = re.sub(r"[（(][^（）()]*[）)]", " ", previous)
        if current == previous:
            return normalize_text(current)
        previous = current


def _is_multi_detail_question(question: str) -> bool:
    text = normalize_text(question)
    patterns = (
        r"分别(?:是|占|列出|多少)",
        r"各多少",
        r"各季度末",
        r"逐一对比",
        r"包含",
        r"各项指标",
        r"环比.*同比",
        r"同比.*环比",
        r"最高日.*最低日",
        r"最高值.*最低值",
        r"变动方向分别",
        r"三个维度",
        r"前.*后.*分别",
        r"是不是等于.*差额",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _is_entity_selection_question(question: str) -> bool:
    text = normalize_text(question)
    return any(
        token in text
        for token in (
            "谁",
            "哪家",
            "哪些",
            "哪几家",
            "排名前三",
            "排名最后",
            "排第一",
            "最高值出现在哪家",
            "最低值在哪家",
        )
    )


def _requires_dates(question: str) -> bool:
    text = normalize_text(question)
    return any(
        token in text
        for token in (
            "哪个季度",
            "各季度末",
            "最高日",
            "最低日",
            "什么日期",
            "出现在哪",
        )
    )


def _single_result_expected_text(question: str, expected_answer: str) -> str:
    question_text = normalize_text(question)
    expected = normalize_text(expected_answer)

    # 只问结果时，括号内通常是官方答案附带的验算过程。
    if not _is_multi_detail_question(question_text):
        expected = _strip_parenthetical_support(expected)

    # 对“高多少、差多少、合计多少”等问题，优先锁定结果短语，
    # 避免把官方答案附带的两个原始值误当成必答项。
    cue_pattern = (
        r"(?:差额|相差|高出|低出|多|少|增加|增长|上升|下降|减少|"
        r"日均|合计)[^，。；]*"
    )
    matches = list(re.finditer(cue_pattern, expected))
    if matches and not _is_multi_detail_question(question_text):
        segment = matches[-1].group(0)
        if extract_numeric_atoms(segment):
            return segment

    return expected


def _select_expected_numbers(
    question: str,
    expected_answer: str,
) -> list[NumericAtom]:
    question_text = normalize_text(question)
    selected_text = _single_result_expected_text(
        question_text,
        expected_answer,
    )
    atoms = extract_numeric_atoms(selected_text)

    # 只问机构是谁时，数值是补充信息，机构匹配才是硬条件。
    if _is_entity_selection_question(question_text) and not any(
        token in question_text
        for token in ("各多少", "增幅各是多少", "水平", "是多少？全省排第几")
    ):
        return []

    if _is_multi_detail_question(question_text):
        return atoms

    # 计数题只把被询问的计数作为主答案，均值或比例说明不是必答项。
    if "有多少家" in question_text or "有几家" in question_text:
        selected = [atom for atom in atoms if atom.unit == "家"]
        return selected[:1] or atoms[:1]
    if "有多少天" in question_text:
        selected = [atom for atom in atoms if atom.unit == "天"]
        return selected[:1] or atoms[:1]

    # 排名题的名次由 rank 组件核验，数值按题目是否询问决定。
    if "排第几" in question_text:
        return atoms[:1]

    # 普通单结果问题只要求一个主结果。
    return atoms[:1]


def _units_compatible(
    expected_unit: str | None,
    actual_unit: str | None,
    question: str,
) -> bool:
    if expected_unit is None:
        return True
    if expected_unit == actual_unit:
        return True

    for family in _COMPATIBLE_UNIT_FAMILIES:
        if expected_unit in family and actual_unit in family:
            return True

    question_text = normalize_text(question)
    pair = {expected_unit, actual_unit}
    if pair == {"万元", "万元/网点"} and "网点平均" in question_text:
        return True
    return False


def _normalize_to_base_unit(value: Decimal, unit: str | None) -> Decimal:
    if unit is None:
        return value
    factor = _UNIT_CONVERSION.get(unit)
    if factor is None:
        return value
    return value * factor


def _check_data_consistency(
    expected_atom: NumericAtom,
    actual_atoms: Sequence[NumericAtom],
    question: str,
    tolerance: Decimal,
    quality_flags: list[str],
) -> None:
    for actual_atom in actual_atoms:
        if not _units_compatible(expected_atom.unit, actual_atom.unit, question):
            continue
        if expected_atom.unit and actual_atom.unit and expected_atom.unit != actual_atom.unit:
            ev = _normalize_to_base_unit(expected_atom.value, expected_atom.unit)
            av = _normalize_to_base_unit(actual_atom.value, actual_atom.unit)
        else:
            ev = expected_atom.value
            av = actual_atom.value
        distance = abs(ev - av)
        if distance > tolerance and expected_atom.value != 0:
            relative = distance / abs(ev)
            if relative < Decimal("0.05"):
                quality_flags.append("data_consistency_concern")
                return


def _numeric_atoms_match_for_question(
    expected: Sequence[NumericAtom],
    actual: Sequence[NumericAtom],
    question: str,
    expected_directions: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    used: set[int] = set()
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    quality_flags: list[str] = []
    directional = bool(
        expected_directions
        & {"increase", "decrease", "above", "below"}
    )

    for expected_atom in expected:
        candidate_index: int | None = None
        candidate_distance: Decimal | None = None
        for index, actual_atom in enumerate(actual):
            if index in used:
                continue
            if not _units_compatible(
                expected_atom.unit,
                actual_atom.unit,
                question,
            ):
                continue

            need_conversion = bool(
                expected_atom.unit and actual_atom.unit and expected_atom.unit != actual_atom.unit
            )
            if need_conversion:
                expected_base = _normalize_to_base_unit(expected_atom.value, expected_atom.unit)
                actual_base = _normalize_to_base_unit(actual_atom.value, actual_atom.unit)
                conversion_factor = max(
                    _UNIT_CONVERSION.get(expected_atom.unit, Decimal("1")),
                    _UNIT_CONVERSION.get(actual_atom.unit, Decimal("1")),
                )
                effective_tolerance = numeric_tolerance(expected_atom) * conversion_factor
            else:
                expected_base = expected_atom.value
                actual_base = actual_atom.value
                effective_tolerance = numeric_tolerance(expected_atom)

            direct_distance = abs(expected_base - actual_base)
            magnitude_distance = abs(
                abs(expected_base) - abs(actual_base)
            )
            distance = min(
                direct_distance,
                magnitude_distance if directional else direct_distance,
            )
            if distance > effective_tolerance:
                continue
            if candidate_distance is None or distance < candidate_distance:
                candidate_index = index
                candidate_distance = distance

        expected_payload = {
            "value": str(expected_atom.value),
            "unit": expected_atom.unit,
            "raw": expected_atom.raw,
        }
        if candidate_index is None:
            missing.append(expected_payload)
            _check_data_consistency(expected_atom, actual, question, effective_tolerance, quality_flags)
            continue

        used.add(candidate_index)
        actual_atom = actual[candidate_index]
        if expected_atom.unit != actual_atom.unit:
            quality_flags.append("unit_expression")
        matched.append(
            {
                "expected": expected_payload,
                "actual": {
                    "value": str(actual_atom.value),
                    "unit": actual_atom.unit,
                    "raw": actual_atom.raw,
                },
            }
        )

    return matched, missing, sorted(set(quality_flags))


def _actual_numeric_values(record: Mapping[str, Any]) -> list[Decimal]:
    values: list[Decimal] = []
    for row in _row_objects(record):
        for key in (
            "difference",
            "change",
            "value",
            "metric_value",
            "count",
            "result_value",
        ):
            if key not in row or row[key] is None:
                continue
            value = decimal_value(row[key])
            if value is not None:
                values.append(value)
                break
    return values


def _infer_actual_directions(
    record: Mapping[str, Any],
    question: str,
    actual: str,
) -> set[str]:
    directions = extract_directions(actual)
    question_text = normalize_text(question)
    values = _actual_numeric_values(record)

    if any(
        token in question_text
        for token in ("变化", "变动", "增幅", "环比", "同比", "较年初")
    ):
        if any(value > 0 for value in values):
            directions.add("increase")
        if any(value < 0 for value in values):
            directions.add("decrease")
        if values and all(value == 0 for value in values):
            directions.add("unchanged")

    if "全省均值" in question_text or "高还是低" in question_text:
        if any(value > 0 for value in values):
            directions.add("above")
        if any(value < 0 for value in values):
            directions.add("below")
        if values and all(value == 0 for value in values):
            directions.add("unchanged")

    # 时间序列同时保留细分趋势和首尾总体方向。
    rows = _row_objects(record)
    series = []
    for row in rows:
        date_value = normalize_text(row.get("date"))
        metric_value = decimal_value(row.get("metric_value"))
        if date_value and metric_value is not None:
            series.append((date_value, metric_value))
    if len(series) >= 2:
        series.sort(key=lambda item: item[0])
        if series[-1][1] > series[0][1]:
            directions.add("increase")
        elif series[-1][1] < series[0][1]:
            directions.add("decrease")
        else:
            directions.add("unchanged")

    return directions


def _required_entities(
    question: str,
    expected_answer: str,
    catalog: Catalog,
) -> set[str]:
    if not _is_entity_selection_question(question):
        return set()
    return extract_catalog_ids(
        expected_answer,
        catalog.institution_aliases,
    )


def _required_ranks(question: str, expected_answer: str) -> set[int]:
    question_text = normalize_text(question)
    if "排第几" in question_text or "排名" in question_text:
        return extract_ranks(expected_answer)
    return set()


def _required_dates(question: str, expected_answer: str) -> set[str]:
    return extract_dates(expected_answer) if _requires_dates(question) else set()


def _required_entity_facts(
    question: str,
    expected_answer: str,
    catalog: Catalog,
    expected_numbers: Sequence[NumericAtom],
) -> list[EntityFact]:
    if not _is_entity_selection_question(question):
        return []
    facts = expected_entity_facts(expected_answer, catalog)
    if not expected_numbers and "排第几" not in normalize_text(question):
        return [
            EntityFact(institution_id=fact.institution_id)
            for fact in facts
        ]
    return facts


def _presentation_flags(
    record: Mapping[str, Any],
    expected_directions: set[str],
    actual_explicit_directions: set[str],
    numeric_quality_flags: Sequence[str],
) -> list[str]:
    flags = set(numeric_quality_flags)
    summary = normalize_text(record.get("summary"))
    if expected_directions and not (
        expected_directions & actual_explicit_directions
    ):
        flags.add("summary_missing_semantic_direction")
    if re.search(r"\b[a-z]+(?:_[a-z]+)+\b", summary):
        flags.add("english_internal_field_name")
    if len(summary) > 280:
        flags.add("summary_too_long")
    return sorted(flags)


def score_record(record: Mapping[str, Any], catalog: Catalog) -> dict[str, Any]:
    scored = dict(record)
    question = normalize_text(record.get("question"))
    expected_answer = normalize_text(record.get("expected_answer"))
    actual = actual_text(record)
    expected_status = infer_expected_status(expected_answer)
    observed_status = actual_status(record)

    if expected_status is not None:
        passed = expected_status == observed_status
        scored["comparison_status"] = "pass" if passed else "fail"
        scored["comparison_score"] = 1.0 if passed else 0.0
        scored["quality_flags"] = []
        scored["comparison"] = {
            "mode": "structured_status",
            "expected_status": expected_status,
            "actual_status": observed_status,
            "reason": (
                "结构化非执行状态一致。"
                if passed
                else "结构化非执行状态不一致。"
            ),
        }
        return scored

    if record.get("run_status") != "success":
        scored["comparison_status"] = "fail"
        scored["comparison_score"] = 0.0
        scored["quality_flags"] = []
        scored["comparison"] = {
            "mode": "executable_answer",
            "expected_status": "success",
            "actual_status": record.get("run_status"),
            "reason": "预期为可执行答案，但运行未成功。",
        }
        return scored

    expected_entities = _required_entities(
        question,
        expected_answer,
        catalog,
    )
    actual_entities = extract_catalog_ids(
        actual,
        catalog.institution_aliases,
    )
    expected_dates = _required_dates(question, expected_answer)
    actual_dates = extract_dates(actual)
    expected_ranks = _required_ranks(question, expected_answer)
    actual_ranks = extract_ranks(actual)

    selected_expected_text = _single_result_expected_text(
        question,
        expected_answer,
    )
    expected_directions = extract_directions(selected_expected_text)
    # 计数题中的“高于/低于”描述筛选条件，不是需要系统复述的主答案。
    if any(token in question for token in ("有多少家", "有几家", "有多少天")):
        expected_directions -= {"above", "below"}
    # 阈值题由数值和达标结论共同表达；“高于阈值”不要求逐字复述。
    if any(token in question for token in ("满足", "最低要求", "监管要求", "有没有超过")):
        expected_directions -= {"above", "below"}
    actual_explicit_directions = extract_directions(actual)
    actual_directions = _infer_actual_directions(
        record,
        question,
        actual,
    )

    expected_numbers = _select_expected_numbers(
        question,
        expected_answer,
    )
    actual_numbers = extract_numeric_atoms(actual)
    (
        matched_numbers,
        missing_numbers,
        numeric_quality_flags,
    ) = _numeric_atoms_match_for_question(
        expected_numbers,
        actual_numbers,
        question,
        expected_directions,
    )

    expected_facts = _required_entity_facts(
        question,
        expected_answer,
        catalog,
        expected_numbers,
    )
    actual_facts = actual_entity_facts(record, catalog)
    missing_facts = compare_entity_facts(
        expected_facts,
        actual_facts,
    )

    entity_component = _component(expected_entities, actual_entities)
    date_component = _component(expected_dates, actual_dates)
    rank_component = _component(expected_ranks, actual_ranks)
    direction_component = _component(
        expected_directions,
        actual_directions,
    )
    numeric_component = {
        "expected": [
            {
                "value": str(item.value),
                "unit": item.unit,
                "raw": item.raw,
            }
            for item in expected_numbers
        ],
        "matched": matched_numbers,
        "missing": missing_numbers,
        "passed": not missing_numbers,
    }
    fact_component = {
        "expected": [asdict(item) for item in expected_facts],
        "actual": [asdict(item) for item in actual_facts],
        "missing": missing_facts,
        "passed": not missing_facts,
    }

    components = {
        "entities": entity_component,
        "dates": date_component,
        "ranks": rank_component,
        "directions": direction_component,
        "numbers": numeric_component,
        "entity_facts": fact_component,
    }
    active_components = [
        name
        for name, expected_values in (
            ("entities", expected_entities),
            ("dates", expected_dates),
            ("ranks", expected_ranks),
            ("directions", expected_directions),
            ("numbers", expected_numbers),
            ("entity_facts", expected_facts),
        )
        if expected_values
    ]

    if not active_components:
        status = "review"
        score = None
        reason = "预期答案缺少可稳定抽取的主答案要素，需要人工复核。"
    else:
        failed_components = [
            name
            for name in active_components
            if not components[name]["passed"]
        ]
        passed_count = len(active_components) - len(failed_components)
        score = round(passed_count / len(active_components), 4)
        status = "pass" if not failed_components else "fail"
        reason = (
            "主答案所需事实要素均已匹配。"
            if status == "pass"
            else "主答案存在缺失或不匹配的事实要素。"
        )

    quality_flags = _presentation_flags(
        record,
        expected_directions,
        actual_explicit_directions,
        numeric_quality_flags,
    )
    scored["comparison_status"] = status
    scored["comparison_score"] = score
    scored["quality_flags"] = quality_flags
    scored["comparison"] = {
        "mode": "intent_aware_deterministic",
        "reason": reason,
        "active_components": active_components,
        "components": components,
    }
    return scored

def build_scoring_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(
        normalize_text(record.get("comparison_status")) or "unknown"
        for record in records
    )
    by_difficulty: dict[str, Counter[str]] = defaultdict(Counter)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    missing_components: Counter[str] = Counter()
    quality_flag_counts: Counter[str] = Counter()

    for record in records:
        status = normalize_text(record.get("comparison_status")) or "unknown"
        difficulty = normalize_text(record.get("difficulty")) or "未标注"
        question_type = normalize_text(record.get("question_type")) or "未标注"
        by_difficulty[difficulty][status] += 1
        by_type[question_type][status] += 1
        for flag in record.get("quality_flags") or []:
            quality_flag_counts[str(flag)] += 1

        comparison = record.get("comparison")
        if not isinstance(comparison, Mapping):
            continue
        components = comparison.get("components")
        if not isinstance(components, Mapping):
            continue
        for name, component in components.items():
            if isinstance(component, Mapping) and component.get("passed") is False:
                missing_components[str(name)] += 1

    total = len(records)
    passed = status_counts.get("pass", 0)
    failed = status_counts.get("fail", 0)
    review = status_counts.get("review", 0)
    deterministically_scored = passed + failed
    return {
        "total": total,
        "comparison_status_counts": dict(sorted(status_counts.items())),
        "deterministically_scored_total": deterministically_scored,
        "manual_review_total": review,
        "pass_rate_all": round(passed / total, 4) if total else None,
        "pass_rate_scored": (
            round(passed / deterministically_scored, 4)
            if deterministically_scored
            else None
        ),
        "by_difficulty": {
            key: dict(sorted(value.items())) for key, value in sorted(by_difficulty.items())
        },
        "by_question_type": {
            key: dict(sorted(value.items())) for key, value in sorted(by_type.items())
        },
        "missing_component_counts": dict(sorted(missing_components.items())),
        "quality_flag_counts": dict(sorted(quality_flag_counts.items())),
    }


def score_run(run_root: Path, context_path: Path = DEFAULT_CONTEXT) -> dict[str, Any]:
    run_root = Path(run_root)
    source_records = read_jsonl(run_root / "results.jsonl")
    latest = latest_records_by_question(source_records)
    ordered = sorted(
        latest.values(),
        key=lambda item: (int(item.get("sequence") or 0), str(item.get("question_id") or "")),
    )
    catalog = load_catalog(Path(context_path))
    scored = [score_record(record, catalog) for record in ordered]
    summary = build_scoring_summary(scored)

    write_jsonl(run_root / "scored_results.jsonl", scored)
    write_json(run_root / "scoring_summary.json", summary)
    write_jsonl(
        run_root / "scoring_failures.jsonl",
        [
            record
            for record in scored
            if record.get("comparison_status") in {"fail", "review"}
        ],
    )
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="离线比较批量评测结果与预期答案，不调用大模型。"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--run-dir", type=Path)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_root = args.run_dir if args.run_dir is not None else DEFAULT_RUNS_ROOT / args.run_id
    summary = score_run(run_root, args.context)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
