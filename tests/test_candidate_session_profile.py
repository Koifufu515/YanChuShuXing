from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CandidateSessionProfileTest(
    unittest.TestCase
):
    def test_identity_panel_contract_is_present(
        self,
    ) -> None:
        frontend = ROOT / "candidate_frontend"

        index = (
            frontend / "index.html"
        ).read_text("utf-8")
        app_source = (
            frontend / "app.js"
        ).read_text("utf-8")

        for element_id in (
            "session-name",
            "session-role",
            "session-profile",
            "session-subject",
            "session-role-label",
            "session-institution-scope",
            "session-rm-scope",
            "session-masking",
            "session-capabilities",
            "security-nav",
        ):
            self.assertIn(
                f'id="{element_id}"',
                index,
            )

        self.assertIn(
            'apiFetch(\n        "/api/v1/session/me"',
            app_source,
        )
        self.assertIn(
            "const profile=await loadSessionProfile()",
            app_source,
        )
        self.assertIn(
            "if(getSessionToken()) await loadSessionProfile()",
            app_source,
        )

    def test_profile_normalization_and_labels(
        self,
    ) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(
  "candidate_frontend/app.js",
  "utf8"
);

const sandbox = {
  window: {
    addEventListener() {},
    YCSXResultAdapter: {},
  },
  console,
  setTimeout,
  clearTimeout,
};

vm.runInNewContext(source, sandbox);

const utils = (
  sandbox.window.YCSXCandidateUtils
);

const profile = utils.normalizeSessionProfile({
  request_id: "req-session",
  subject_id: "rm001",
  display_name: "RM001客户经理",
  role: "relationship_manager",
  role_label: "客户经理",
  authenticated: true,
  masking_profile: "standard",
  institution_scope: {
    enforced: true,
    all_access: false,
    ids: ["ORG009"],
  },
  relationship_manager_scope: {
    enforced: true,
    all_access: false,
    ids: ["RM001"],
  },
  capabilities: {
    can_query: true,
    can_view_permission_demo: true,
    can_view_security_alerts: false,
    row_scope_active: true,
  },
});

if (!profile) process.exit(1);
if (profile.subjectId !== "rm001") process.exit(2);
if (profile.roleLabel !== "客户经理") process.exit(3);
if (profile.institutionScope.ids[0] !== "ORG009") process.exit(4);
if (profile.relationshipManagerScope.ids[0] !== "RM001") process.exit(5);
if (!profile.capabilities.rowScopeActive) process.exit(6);

const institution = utils.sessionScopeSummary(
  profile.institutionScope,
  {allLabel: "全部机构", noneLabel: "未限制"}
);

const capabilities = utils.sessionCapabilitySummary(
  profile.capabilities
);

if (institution !== "ORG009") process.exit(7);
if (capabilities !== "智能问数、权限演示") process.exit(8);

console.log(JSON.stringify({
  subjectId: profile.subjectId,
  institution,
  capabilities,
}));
"""

        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "subjectId": "rm001",
                "institution": "ORG009",
                "capabilities": (
                    "智能问数、权限演示"
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
