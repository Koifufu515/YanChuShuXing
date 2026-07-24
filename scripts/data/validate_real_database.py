from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from time import perf_counter


class ReleaseValidationError(RuntimeError):
    pass


MANIFEST_COLUMNS = (
    "run_id",
    "source_sha256",
    "schema_version",
    "created_at_utc",
    "institution_count",
    "metric_count",
    "fact_count",
    "derived_dimension_count",
)


def validate_active_release(
    private_root: Path, real_root: Path | None = None
) -> dict[str, object]:
    private_root = Path(private_root).resolve()
    real_root = Path(real_root).resolve() if real_root else private_root.parent / "real"
    active_path = private_root / "official" / "active_release.json"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        run_id = _text(active, "run_id")
        source_sha256 = _text(active, "source_sha256")
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ReleaseValidationError("active_release.json 无法读取或格式错误") from exc

    business = _inside_release(real_root, run_id, "bankinsight_real.db")
    evaluation = _inside_release(
        private_root / "evaluation", run_id, "questions.db"
    )
    for path, label in ((business, "业务库"), (evaluation, "评测库")):
        if not path.is_file():
            raise ReleaseValidationError(f"{label}不存在")

    business_manifest = _manifest(business)
    evaluation_manifest = _manifest(evaluation)
    if business_manifest != evaluation_manifest:
        raise ReleaseValidationError("业务库与评测库 manifest 不一致")
    if business_manifest["run_id"] != run_id or business_manifest["source_sha256"] != source_sha256:
        raise ReleaseValidationError("active release 与数据库 manifest 不一致")

    _sqlite_integrity(business, "业务库")
    _sqlite_integrity(evaluation, "评测库")
    counts, dates = _validate_business_cube(business, business_manifest)
    question_count = _count(evaluation, "evaluation_questions")
    checks = _query_smoke_checks(business)
    return {
        "status": "ok",
        "run_id": run_id,
        "schema_version": business_manifest["schema_version"],
        **counts,
        "question_count": question_count,
        **dates,
        "checks": checks,
    }


def _text(payload: object, key: str) -> str:
    value = payload[key] if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip() or "/" in value or "\\" in value:
        raise ReleaseValidationError(f"active_release.json 的 {key} 无效")
    return value.strip()


def _inside_release(root: Path, run_id: str, filename: str) -> Path:
    releases = (Path(root).resolve() / "releases").resolve()
    path = (releases / run_id / filename).resolve()
    if releases not in path.parents:
        raise ReleaseValidationError("发布路径发生逃逸")
    return path


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.create_function(
        "scaled_value", 2, lambda value, scale: None if value is None or scale is None else value / (10**scale), deterministic=True
    )
    return connection


def _manifest(path: Path) -> dict[str, object]:
    connection = _connect(path)
    try:
        row = connection.execute(
            f"SELECT {', '.join(MANIFEST_COLUMNS)} FROM import_manifest"
        ).fetchone()
    except sqlite3.Error as exc:
        raise ReleaseValidationError("数据库 manifest 无法读取") from exc
    finally:
        connection.close()
    if row is None:
        raise ReleaseValidationError("数据库缺少 manifest")
    return dict(zip(MANIFEST_COLUMNS, row))


def _sqlite_integrity(path: Path, label: str) -> None:
    connection = _connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != [("ok",)]:
        raise ReleaseValidationError(f"{label}完整性检查失败")
    if foreign_keys:
        raise ReleaseValidationError(f"{label}外键检查失败")


def _count(path: Path, table: str) -> int:
    connection = _connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def _validate_business_cube(
    path: Path, manifest: dict[str, object]
) -> tuple[dict[str, int], dict[str, str]]:
    connection = _connect(path)
    try:
        counts = {
            "institution_count": int(connection.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]),
            "metric_count": int(connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]),
            "fact_count": int(connection.execute("SELECT COUNT(*) FROM metric_facts").fetchone()[0]),
            "derived_dimension_count": int(connection.execute("SELECT COUNT(*) FROM derived_dimensions").fetchone()[0]),
        }
        expected = {
            key: int(manifest[key])
            for key in counts
        }
        if counts != expected:
            raise ReleaseValidationError("业务库行数与 manifest 不一致")
        checks = {
            "机构编号": "SELECT COUNT(*)-COUNT(DISTINCT institution_id) FROM institutions",
            "机构名称": "SELECT COUNT(*)-COUNT(DISTINCT institution_name) FROM institutions",
            "指标编号": "SELECT COUNT(*)-COUNT(DISTINCT metric_id) FROM metrics",
            "指标名称": "SELECT COUNT(*)-COUNT(DISTINCT metric_name) FROM metrics",
        }
        for label, sql in checks.items():
            if connection.execute(sql).fetchone()[0]:
                raise ReleaseValidationError(f"{label}不唯一")
        if connection.execute(
            "SELECT COUNT(*) FROM metric_facts WHERE institution_id IS NULL OR metric_id IS NULL OR data_date IS NULL OR metric_value_scaled IS NULL"
        ).fetchone()[0]:
            raise ReleaseValidationError("事实表核心字段存在 NULL")
        if connection.execute(
            "SELECT COUNT(*) FROM metric_facts WHERE typeof(metric_value_scaled) <> 'integer'"
        ).fetchone()[0]:
            raise ReleaseValidationError("metric_value_scaled 不是 SQLite integer")
        if connection.execute(
            "SELECT COUNT(*) FROM metric_facts f LEFT JOIN institutions i USING(institution_id) WHERE i.institution_id IS NULL"
        ).fetchone()[0] or connection.execute(
            "SELECT COUNT(*) FROM metric_facts f LEFT JOIN metrics m USING(metric_id) WHERE m.metric_id IS NULL"
        ).fetchone()[0]:
            raise ReleaseValidationError("事实表存在失联维度")

        date_min, date_max, date_count = connection.execute(
            "SELECT MIN(data_date), MAX(data_date), COUNT(DISTINCT data_date) FROM metric_facts"
        ).fetchone()
        calendar_days = int(connection.execute(
            "SELECT CAST(julianday(MAX(data_date))-julianday(MIN(data_date)) AS INTEGER)+1 FROM metric_facts"
        ).fetchone()[0])
        if date_count != calendar_days:
            raise ReleaseValidationError("指标数据日期不连续")
        expected_per_day = counts["institution_count"] * counts["metric_count"]
        incomplete_dates = connection.execute(
            "SELECT data_date FROM metric_facts GROUP BY data_date "
            "HAVING COUNT(*)<>? OR COUNT(DISTINCT institution_id)<>? OR COUNT(DISTINCT metric_id)<>? LIMIT 1",
            (expected_per_day, counts["institution_count"], counts["metric_count"]),
        ).fetchone()
        if incomplete_dates:
            raise ReleaseValidationError("存在不完整的数据日期")
        incomplete_pairs = connection.execute(
            "SELECT institution_id, metric_id FROM metric_facts GROUP BY institution_id, metric_id HAVING COUNT(DISTINCT data_date)<>? LIMIT 1",
            (date_count,),
        ).fetchone()
        if incomplete_pairs:
            raise ReleaseValidationError("存在不完整的机构指标时间序列")
    finally:
        connection.close()
    return counts, {"date_min": date_min, "date_max": date_max}


def _query_smoke_checks(path: Path) -> list[dict[str, object]]:
    connection = _connect(path)
    try:
        sample = connection.execute(
            "SELECT institution_id, metric_id, data_date FROM metric_facts LIMIT 1"
        ).fetchone()
        if sample is None:
            raise ReleaseValidationError("业务库没有指标事实")
        institution_id, metric_id, data_date = sample
        queries = [
            ("single_value", "SELECT scaled_value(f.metric_value_scaled,m.value_scale) FROM metric_facts f JOIN metrics m USING(metric_id) WHERE f.institution_id=? AND f.metric_id=? AND f.data_date=?", (institution_id, metric_id, data_date)),
            ("time_series", "SELECT data_date, scaled_value(f.metric_value_scaled,m.value_scale) FROM metric_facts f JOIN metrics m USING(metric_id) WHERE f.institution_id=? AND f.metric_id=? ORDER BY data_date", (institution_id, metric_id)),
            ("ranking", "SELECT institution_id, scaled_value(f.metric_value_scaled,m.value_scale) FROM metric_facts f JOIN metrics m USING(metric_id) WHERE f.metric_id=? AND f.data_date=? ORDER BY 2 DESC", (metric_id, data_date)),
            ("period_average", "SELECT AVG(scaled_value(f.metric_value_scaled,m.value_scale)) FROM metric_facts f JOIN metrics m USING(metric_id) WHERE f.metric_id=?", (metric_id,)),
            ("multi_metric", "SELECT metric_id, scaled_value(f.metric_value_scaled,m.value_scale) FROM metric_facts f JOIN metrics m USING(metric_id) WHERE f.institution_id=? AND f.data_date=? ORDER BY metric_id", (institution_id, data_date)),
            ("scaled_value", "SELECT scaled_value(f.metric_value_scaled,m.value_scale) FROM metric_facts f JOIN metrics m USING(metric_id) LIMIT 1", ()),
        ]
        results = []
        for name, sql, parameters in queries:
            started = perf_counter()
            rows = connection.execute(sql, parameters).fetchall()
            if not rows:
                raise ReleaseValidationError(f"查询烟雾测试失败：{name}")
            results.append({"name": name, "row_count": len(rows), "duration_ms": round((perf_counter()-started)*1000, 3)})
        return results
    finally:
        connection.close()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="验收言出数行正式数据发布")
    parser.add_argument("--private-root", type=Path, default=root / "data" / "private")
    parser.add_argument("--real-root", type=Path, default=root / "data" / "real")
    args = parser.parse_args()
    try:
        result = validate_active_release(args.private_root, args.real_root)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
