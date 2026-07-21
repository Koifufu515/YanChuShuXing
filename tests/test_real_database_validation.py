import tempfile
import unittest
import json
from pathlib import Path

from test_real_import_contract import _workbook


class RealDatabaseValidationTest(unittest.TestCase):
    def test_validation_rejects_manifest_database_outside_release_roots(self) -> None:
        from scripts.data.import_official_workbook import import_workbook
        from scripts.data.validate_real_database import ReleaseValidationError, validate_active_release

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "official.xlsx"; _workbook(source)
            import_workbook(source, root / "real", root / "private")
            manifest = root / "private" / "official" / "active_release.json"
            data = json.loads(manifest.read_text(encoding="utf-8")); data["business_database"] = str(root / "outside.db")
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ReleaseValidationError):
                validate_active_release(root / "private")

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
