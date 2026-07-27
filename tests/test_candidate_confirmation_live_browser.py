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
    def test_frontend_has_no_local_intent_confirmation_demo(self):
        with tempfile.TemporaryDirectory(prefix="ycsx_query_plan_browser_") as profile:
            dom = self._dom(profile, "")
            self.assertIn("历史会话", dom)
            self.assertNotIn("还需确认", dom)
            self.assertNotIn("增长方式", dom)
            self.assertNotIn("全部13家正式机构", dom)

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
