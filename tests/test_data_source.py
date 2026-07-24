import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.errors import ConfigurationError
from app.core.data_source import (
    describe_data_source,
    resolve_active_real_release,
    resolve_database_path,
)
from scripts.data.import_official_workbook import import_workbook
from test_real_import_contract import _workbook


class DataSourceTest(unittest.TestCase):
    def test_default_real_missing_does_not_fall_back_to_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "processed").mkdir(parents=True)
            (root / "data" / "processed" / "bankinsight.db").touch()
            with self.assertRaisesRegex(ConfigurationError, "正式数据库尚未初始化"):
                resolve_database_path(root)

    def test_demo_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data" / "processed" / "bankinsight.db"
            path.parent.mkdir(parents=True)
            path.touch()
            self.assertEqual(resolve_database_path(root, "demo"), path.resolve())

    def test_override_supports_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "custom.db"
            path.touch()
            self.assertEqual(
                resolve_database_path(root, "real", "custom.db"), path.resolve()
            )

    def test_active_release_reconstructs_paths_and_checks_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "official.xlsx"
            _workbook(source)
            import_workbook(source, root / "data" / "real", root / "data" / "private")
            release = resolve_active_real_release(root)
            self.assertTrue(release.business_database.is_file())
            self.assertTrue(release.evaluation_database.is_file())

            evaluation = release.evaluation_database
            import sqlite3

            connection = sqlite3.connect(evaluation)
            connection.execute("UPDATE import_manifest SET source_sha256='mismatch'")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ConfigurationError, "不一致"):
                resolve_active_real_release(root)

    def test_readiness_honors_real_database_override_without_active_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "official.xlsx"
            _workbook(source)
            result = import_workbook(
                source, root / "data" / "real", root / "data" / "private"
            )
            (root / "data" / "private" / "official" / "active_release.json").unlink()
            payload = describe_data_source(
                root, "real", result["business_database"]
            )
            self.assertTrue(payload["database_ready"])
            self.assertEqual(payload["institution_count"], 1)
