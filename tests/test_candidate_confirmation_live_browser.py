from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


EDGE = os.environ.get("YCSX_EDGE_PATH", "")
BASE_URL = os.environ.get("YCSX_CONFIRMATION_URL", "")


@unittest.skipUnless(EDGE and Path(EDGE).exists() and BASE_URL, "set Edge path and live candidate URL")
class CandidateConfirmationLiveBrowserTest(unittest.TestCase):
    def test_waiting_selection_refresh_history_and_confirmed_result(self):
        with tempfile.TemporaryDirectory(prefix="ycsx_confirmation_browser_") as profile:
            before = self._dom(profile, "intent_demo=before")
            self.assertIn("待确认", before)
            self.assertIn("需要确认", before)
            self.assertIn("各项存款余额", before)
            self.assertNotIn("最终采用条件", before)

            selecting = self._dom(profile, "intent_demo=selecting")
            self.assertIn("选择中", selecting)
            self.assertIn("自定义时间增长", selecting)
            self.assertIn('data-confirm-field="custom_start_date"', selecting)

            restored = self._dom(profile, "")
            self.assertIn("选择中", restored)
            self.assertIn("哪家银行存款增长最好", restored)
            self.assertIn("历史会话", restored)

        with tempfile.TemporaryDirectory(prefix="ycsx_confirmation_confirmed_") as confirmed_profile:
            confirmed = self._dom(confirmed_profile, "intent_demo=confirmed", budget=9000)
            self.assertIn("最终采用条件", confirmed)
            self.assertIn("同比增长", confirmed)
            self.assertIn("metric_value", confirmed)
            self.assertNotIn("CLARIFICATION_REQUIRED", confirmed)

    def _dom(self, profile: str, query: str, budget: int = 6000) -> str:
        url = f"{BASE_URL.rstrip('/')}?{query}" if query else BASE_URL.rstrip("/")
        result = subprocess.run(
            [EDGE, "--headless", "--disable-gpu", "--disable-crash-reporter", "--disable-breakpad", "--no-first-run", f"--user-data-dir={profile}", f"--virtual-time-budget={budget}", "--dump-dom", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout


if __name__ == "__main__":
    unittest.main()
