from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

RULES_VERSION = "norm-2026.07.18-1"

_FULLWIDTH = str.maketrans(
    "０１２３４５６７８９．，％（）：",
    "0123456789.,%():",
)
_THOUSAND_SEP = re.compile(r"(?<=\d),(?=\d{3}(?![0-9]))")
_AMOUNT = re.compile(r"(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)")
_PERCENT_POINT = re.compile(r"(-?\d+(?:\.\d+)?)\s*个百分点")
_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_PLAIN = re.compile(r"-?\d+(?:\.\d+)?")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATE_CN_FULL = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_DATE_CN_MONTH_END = re.compile(r"^(\d{4})年(\d{1,2})月(?:末|底)$")
_ORG_NAME = re.compile(r"[\u4e00-\u9fa5]{1,2}省[\u4e00-\u9fa5]{1,8}市农商行")

_AMOUNT_MULTIPLIER = {"亿元": 100_000_000.0, "万元": 10_000.0, "元": 1.0}


@dataclass(frozen=True)
class Number:
    value: float
    kind: str  # amount | percent | percent_point | plain


def normalize_text(text: str) -> str:
    normalized = text.translate(_FULLWIDTH).replace("，", ",")
    while _THOUSAND_SEP.search(normalized):
        normalized = _THOUSAND_SEP.sub("", normalized)
    return normalized


def extract_numbers(text: str) -> list[Number]:
    normalized = normalize_text(text)
    matches: list[tuple[int, Number]] = []
    consumed: list[tuple[int, int]] = []

    for pattern, kind in (
        (_AMOUNT, "amount"),
        (_PERCENT_POINT, "percent_point"),
        (_PERCENT, "percent"),
    ):
        for match in pattern.finditer(normalized):
            value = float(match.group(1))
            if kind == "amount":
                value *= _AMOUNT_MULTIPLIER[match.group(2)]
            matches.append((match.start(), Number(value=value, kind=kind)))
            consumed.append((match.start(), match.end()))

    for match in _PLAIN.finditer(normalized):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        matches.append(
            (match.start(), Number(value=float(match.group(0)), kind="plain"))
        )

    matches.sort(key=lambda item: item[0])
    return [number for _, number in matches]


def normalize_date_expression(text: str) -> str | None:
    stripped = normalize_text(text.strip())
    match = _DATE_ISO.match(stripped)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = _DATE_CN_FULL.match(stripped)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = _DATE_CN_MONTH_END.match(stripped)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def extract_org_names(text: str) -> list[str]:
    seen: list[str] = []
    for match in _ORG_NAME.finditer(text):
        name = match.group(0)
        if name not in seen:
            seen.append(name)
    return seen
