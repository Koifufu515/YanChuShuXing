from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import perf_counter


class ReleaseValidationError(RuntimeError):
    pass


def _manifest(path: Path) -> tuple[str, str]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT run_id, source_sha256 FROM import_manifest").fetchone()
    finally:
        connection.close()
    if row is None:
        raise ReleaseValidationError("数据库缺少导入 manifest")
    return row


def validate_active_release(private_root: Path) -> dict[str, object]:
    private_root = Path(private_root).resolve()
    active_path = private_root / "official" / "active_release.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    run_id = active["run_id"]
    business = (private_root.parents[0] / "real" / "releases" / run_id / "bankinsight_real.db").resolve()
    evaluation = (private_root / "evaluation" / "releases" / run_id / "questions.db").resolve()
    if Path(active["business_database"]).resolve() != business or Path(active["evaluation_database"]).resolve() != evaluation:
        raise ReleaseValidationError("发布路径不在允许的版本目录中")
    expected = (active["run_id"], active["source_sha256"])
    if _manifest(business) != expected or _manifest(evaluation) != expected:
        raise ReleaseValidationError("业务库与评测库版本不一致")
    connection = sqlite3.connect(f"file:{business.resolve()}?mode=ro", uri=True)
    try:
        sample = connection.execute("SELECT institution_id, metric_id, data_date FROM metric_facts LIMIT 1").fetchone()
        if sample is None:
            raise ReleaseValidationError("业务库没有指标事实")
        institution_id, metric_id, data_date = sample
        checks = [
            ("single_value", "SELECT metric_value_scaled FROM metric_facts WHERE institution_id=? AND metric_id=? AND data_date=?", (institution_id, metric_id, data_date)),
            ("period_compare", "SELECT data_date, metric_value_scaled FROM metric_facts WHERE institution_id=? AND metric_id=? ORDER BY data_date LIMIT 2", (institution_id, metric_id)),
            ("ranking", "SELECT institution_id, metric_value_scaled FROM metric_facts WHERE metric_id=? AND data_date=? ORDER BY metric_value_scaled DESC", (metric_id, data_date)),
            ("trend", "SELECT data_date, metric_value_scaled FROM metric_facts WHERE institution_id=? AND metric_id=? ORDER BY data_date", (institution_id, metric_id)),
            ("comparison", "SELECT institution_id, metric_id, metric_value_scaled FROM metric_facts WHERE data_date=? ORDER BY institution_id, metric_id", (data_date,)),
            ("average", "SELECT AVG(metric_value_scaled) FROM metric_facts WHERE metric_id=?", (metric_id,)),
        ]
        results = []
        for name, sql, parameters in checks:
            started = perf_counter()
            rows = connection.execute(sql, parameters).fetchall()
            results.append({"name": name, "row_count": len(rows), "duration_ms": round((perf_counter() - started) * 1000, 3)})
    finally:
        connection.close()
    return {"status": "ok", "run_id": expected[0], "checks": results}
