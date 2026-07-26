from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PAGE = ROOT / "candidate_frontend" / "chart_audit.html"
EDGE = os.environ.get("YCSX_EDGE_PATH", "")


@unittest.skipUnless(EDGE and Path(EDGE).exists(), "set YCSX_EDGE_PATH to run the local ECharts DOM audit")
class CandidateChartBrowserTest(unittest.TestCase):
    def test_named_field_mapping_and_full_chart_rendering_in_browser(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ycsx_chart_audit_") as profile:
            result = subprocess.run(
                [
                    EDGE,
                    "--headless",
                    "--disable-gpu",
                    "--disable-crash-reporter",
                    "--disable-breakpad",
                    "--no-first-run",
                    f"--user-data-dir={profile}",
                    "--allow-file-access-from-files",
                    "--virtual-time-budget=5000",
                    "--dump-dom",
                    AUDIT_PAGE.as_uri(),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('data-audit="pass"', result.stdout)
        self.assertIn("趋势渲染全部 486 个点", result.stdout)
        self.assertIn("ECharts 在浏览器 DOM 中生成两个 SVG 图表", result.stdout)


if __name__ == "__main__":
    unittest.main()
