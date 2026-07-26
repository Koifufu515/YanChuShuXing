from __future__ import annotations

import sqlite3

from fastapi import APIRouter

from app.bootstrap.container import PROJECT_ROOT
from app.core.data_source import resolve_database_path
from app.core.settings import Settings


router = APIRouter(prefix="/api/v1", tags=["examples"])


@router.get("/examples")
def query_examples() -> dict[str, list[dict[str, str]]]:
    """Build safe example questions from the active business catalog, never answers."""
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    database = resolve_database_path(
        PROJECT_ROOT,
        settings.data_environment,
        settings.database_path_override,
    )
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        institution_name = connection.execute(
            "SELECT institution_name FROM institutions ORDER BY institution_id LIMIT 1"
        ).fetchone()[0]
        metric_name = connection.execute(
            "SELECT metric_name FROM metrics ORDER BY metric_id LIMIT 1"
        ).fetchone()[0]
        date_min, date_max = connection.execute(
            "SELECT MIN(data_date), MAX(data_date) FROM metric_facts"
        ).fetchone()
    finally:
        connection.close()
    return {
        "examples": [
            {
                "result_type": "单值",
                "question": f"查询{institution_name}在{date_max}的{metric_name}",
            },
            {
                "result_type": "排名",
                "question": f"查询{date_max}{metric_name}机构排名",
            },
            {
                "result_type": "趋势",
                "question": (
                    f"查询{institution_name}从{date_min}到{date_max}的{metric_name}趋势"
                ),
            },
        ]
    }
