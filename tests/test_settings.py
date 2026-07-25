import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.errors import ConfigurationError
from app.core.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_loads_public_configuration_from_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "BANKINSIGHT_GENERATOR_MODE=hybrid\n"
                "BANKINSIGHT_LLM_MODEL=deepseek-v4-pro\n"
                "BANKINSIGHT_LLM_API_KEY=local-secret\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_env(env_file)
            self.assertEqual(settings.generator_mode, "hybrid")
            self.assertEqual(settings.llm_model, "deepseek-v4-pro")
            self.assertEqual(settings.llm_api_key, "local-secret")
            self.assertEqual(settings.data_environment, "real")

    def test_invalid_mode_is_rejected(self):
        with patch.dict(
            os.environ, {"BANKINSIGHT_GENERATOR_MODE": "unknown"}, clear=True
        ):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_explicit_demo_and_database_override(self):
        with patch.dict(
            os.environ,
            {"BANKINSIGHT_DATA_ENV": "demo", "BANKINSIGHT_DB_PATH": "custom.db"},
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.data_environment, "demo")
        self.assertEqual(settings.database_path_override, "custom.db")

    def test_invalid_data_environment_is_rejected(self):
        with patch.dict(os.environ, {"BANKINSIGHT_DATA_ENV": "auto"}, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
