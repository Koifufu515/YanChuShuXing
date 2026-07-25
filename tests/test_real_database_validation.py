import tempfile
import unittest
import json
import sqlite3
from pathlib import Path

from test_real_import_contract import _workbook


class RealDatabaseValidationTest(unittest.TestCase):
    def _release(self, root: Path):
        from scripts.data.import_official_workbook import import_workbook

        source = root / "official.xlsx"
        _workbook(source)
        return import_workbook(source, root / "real", root / "private")

    def test_validation_ignores_untrusted_paths_in_active_file(self) -> None:
        from scripts.data.import_official_workbook import import_workbook
        from scripts.data.validate_real_database import ReleaseValidationError, validate_active_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "official.xlsx"; _workbook(source)
            import_workbook(source, root / "real", root / "private")
            manifest = root / "private" / "official" / "active_release.json"
            data = json.loads(manifest.read_text(encoding="utf-8")); data["ignored_path"] = str(root / "outside.db")
            manifest.write_text(json.dumps(data), encoding="utf-8")
            result = validate_active_release(root / "private", root / "real")
            self.assertEqual(result["status"], "ok")

    def test_validation_runs_six_query_categories_for_active_release(self) -> None:
        from scripts.data.import_official_workbook import import_workbook
        from scripts.data.validate_real_database import validate_active_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "official.xlsx"
            _workbook(source)
            import_workbook(source, root / "real", root / "private")
            result = validate_active_release(root / "private")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["checks"]), 6)

    def test_validation_rejects_manifest_count_mismatch_after_fact_delete(self) -> None:
        from scripts.data.validate_real_database import ReleaseValidationError, validate_active_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._release(root)
            connection = sqlite3.connect(release["business_database"])
            connection.execute("DELETE FROM metric_facts")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ReleaseValidationError, "行数"):
                validate_active_release(root / "private", root / "real")

    def test_validation_rejects_duplicate_dimension_names(self) -> None:
        from scripts.data.validate_real_database import ReleaseValidationError, validate_active_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._release(root)
            connection = sqlite3.connect(release["business_database"])
            connection.execute("INSERT INTO institutions VALUES ('I2', '机构一')")
            connection.execute(
                "UPDATE import_manifest SET institution_count=institution_count+1"
            )
            connection.commit()
            connection.close()
            evaluation = sqlite3.connect(release["evaluation_database"])
            evaluation.execute(
                "UPDATE import_manifest SET institution_count=institution_count+1"
            )
            evaluation.commit()
            evaluation.close()
            with self.assertRaisesRegex(ReleaseValidationError, "机构名称不唯一"):
                validate_active_release(root / "private", root / "real")
