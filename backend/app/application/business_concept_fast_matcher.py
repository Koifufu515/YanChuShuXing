from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any


_DATE_PATTERN = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


@dataclass(frozen=True)
class MainMetricsQueryMatch:
    institution_id: str
    institution_name: str
    data_date: str


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized)


def match_main_metrics_query(
    question: str,
    context: Mapping[str, Any],
) -> MainMetricsQueryMatch | None:
    normalized_question = _normalize_text(question)

    has_good_request = (
        "表现较好" in normalized_question
        or "指标较好" in normalized_question
    )
    has_bad_request = (
        "表现较差" in normalized_question
        or "指标较差" in normalized_question
    )

    if not (
        "主要经营指标" in normalized_question
        and "排名" in normalized_question
        and has_good_request
        and has_bad_request
    ):
        return None

    matched_dates = {
        match.group(1)
        for match in _DATE_PATTERN.finditer(normalized_question)
    }
    if len(matched_dates) != 1:
        return None

    data_date = next(iter(matched_dates))

    try:
        query_date = date.fromisoformat(data_date)
    except ValueError:
        return None

    data_range = context.get("data_range")
    if not isinstance(data_range, Mapping):
        return None

    try:
        start_date = date.fromisoformat(str(data_range["start_date"]))
        end_date = date.fromisoformat(str(data_range["end_date"]))
    except (KeyError, TypeError, ValueError):
        return None

    if not start_date <= query_date <= end_date:
        return None

    institutions = context.get("institutions")
    if not isinstance(institutions, list):
        return None

    matched_institutions: list[tuple[str, str]] = []

    for institution in institutions:
        if not isinstance(institution, Mapping):
            continue

        institution_id = institution.get("institution_id")
        institution_name = institution.get("institution_name")

        if not isinstance(institution_id, str) or not isinstance(
            institution_name,
            str,
        ):
            continue

        if _normalize_text(institution_name) in normalized_question:
            matched_institutions.append(
                (institution_id, institution_name)
            )

    if len(matched_institutions) != 1:
        return None

    institution_id, institution_name = matched_institutions[0]

    return MainMetricsQueryMatch(
        institution_id=institution_id,
        institution_name=institution_name,
        data_date=data_date,
    )
