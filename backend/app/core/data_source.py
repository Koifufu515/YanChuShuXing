from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.application.errors import ConfigurationError


REAL = "real"
DEMO = "demo"
VALID_DATA_ENVIRONMENTS = frozenset({REAL, DEMO})


@dataclass(frozen=True)
class RealRelease:
    run_id: str
    source_sha256: str
    business_database: Path
    evaluation_database: Path
    schema_version: str


def resolve_database_path(
    project_root: Path,
    data_environment: str = REAL,
    database_path_override: str = "",
) -> Path:
    root = Path(project_root).resolve()
    override = database_path_override.strip()
    if override:
        candidate = Path(override)
        path = candidate if candidate.is_absolute() else root / candidate
        path = path.resolve()
        if not path.is_file():
            raise ConfigurationError("BANKINSIGHT_DB_PATH 指向的数据库不存在。")
        return path
    if data_environment == DEMO:
        path = root / "data" / "processed" / "bankinsight.db"
        if not path.is_file():
            raise ConfigurationError("Demo 数据库尚未初始化。")
        return path.resolve()
    if data_environment != REAL:
        raise ConfigurationError("BANKINSIGHT_DATA_ENV 必须是 real 或 demo。")
    return resolve_active_real_release(root).business_database


def resolve_active_real_release(project_root: Path) -> RealRelease:
    root = Path(project_root).resolve()
    active_path = root / "data" / "private" / "official" / "active_release.json"
    try:
        payload = json.loads(active_path.read_text(encoding="utf-8"))
        run_id = _required_text(payload, "run_id")
        source_sha256 = _required_text(payload, "source_sha256")
    except (OSError, json.JSONDecodeError, TypeError, ConfigurationError) as exc:
        raise ConfigurationError(
            "正式数据库尚未初始化，请先执行正式数据导入和验收。"
        ) from exc

    business = _release_path(root / "data" / "real", run_id, "bankinsight_real.db")
    evaluation = _release_path(
        root / "data" / "private" / "evaluation", run_id, "questions.db"
    )
    if not business.is_file() or not evaluation.is_file():
        raise ConfigurationError("正式数据库尚未初始化，请先执行正式数据导入和验收。")

    business_manifest = _manifest(business)
    evaluation_manifest = _manifest(evaluation)
    expected = (run_id, source_sha256)
    if business_manifest[:2] != expected or evaluation_manifest[:2] != expected:
        raise ConfigurationError("正式业务库与评测库发布版本不一致。")
    if business_manifest != evaluation_manifest:
        raise ConfigurationError("正式业务库与评测库 manifest 不一致。")
    return RealRelease(
        run_id=run_id,
        source_sha256=source_sha256,
        business_database=business,
        evaluation_database=evaluation,
        schema_version=business_manifest[2],
    )


def describe_data_source(
    project_root: Path,
    data_environment: str,
    database_path_override: str = "",
) -> dict[str, object]:
    if data_environment == DEMO:
        path = resolve_database_path(project_root, DEMO)
        return {"data_environment": DEMO, "database_ready": path.is_file()}
    if database_path_override.strip():
        business_database = resolve_database_path(
            project_root, REAL, database_path_override
        )
    else:
        business_database = resolve_active_real_release(project_root).business_database
    try:
        connection = sqlite3.connect(
            f"file:{business_database}?mode=ro", uri=True
        )
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ConfigurationError("正式数据库完整性检查失败。")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ConfigurationError("正式数据库外键检查失败。")
            institution_count = connection.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
            metric_count = connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
            fact_count = connection.execute("SELECT COUNT(*) FROM metric_facts").fetchone()[0]
            date_min, date_max = connection.execute(
                "SELECT MIN(data_date), MAX(data_date) FROM metric_facts"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ConfigurationError("正式数据库就绪检查失败。") from exc
    manifest = _manifest(business_database)
    if (institution_count, metric_count, fact_count) != (
        manifest[4], manifest[5], manifest[6]
    ):
        raise ConfigurationError("正式数据库行数验收失败。")
    return {
        "data_environment": REAL,
        "database_ready": True,
        "run_id": str(manifest[0]),
        "schema_version": str(manifest[2]),
        "institution_count": institution_count,
        "metric_count": metric_count,
        "fact_count": fact_count,
        "date_min": date_min,
        "date_max": date_max,
    }


def _release_path(root: Path, run_id: str, filename: str) -> Path:
    releases = (Path(root).resolve() / "releases").resolve()
    path = (releases / run_id / filename).resolve()
    if releases not in path.parents:
        raise ConfigurationError("正式数据发布路径不合法。")
    return path


def _required_text(payload: object, key: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), str):
        raise ConfigurationError("active_release.json 格式不正确。")
    value = payload[key].strip()
    if not value or "/" in value or "\\" in value:
        raise ConfigurationError("active_release.json 格式不正确。")
    return value


def _manifest(path: Path) -> tuple[str, str, str, str, int, int, int, int]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT run_id, source_sha256, schema_version, created_at_utc, "
                "institution_count, metric_count, fact_count, derived_dimension_count "
                "FROM import_manifest"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ConfigurationError("正式数据库 manifest 无法读取。") from exc
    if row is None:
        raise ConfigurationError("正式数据库缺少 manifest。")
    return tuple(row)  # type: ignore[return-value]
