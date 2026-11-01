"""Run with:  python -m unittest discover -s tests -p test_blog.py -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import blog  # noqa: E402

README = """# Copilot Billing Health Check

Oct 30, 2026 · @Chad Cox

A read-only health check that reviews Microsoft 365 Copilot spending policies, the groups they use and the people in them.

## Prerequisites

- A Global Reader or Billing Administrator role
- PowerShell 7

## Install

1. Run Install-Module Microsoft.Graph.Authentication
2. Run the script

```powershell
.\\Get-CopilotBillingHealth.ps1 -SkipBalances
```

### Parameters

-SkipBalances skips credit balances.

## What it checks

Each policy is compared with the recommended setup and every finding comes with a fix.
"""

ROOT_README = """# Copilot

| Folder | What it is | What you get |
| --- | --- | --- |
| [Billing Health Check](Billing%20Health%20Check/README.md) | A read-only check of spending policies | A scored HTML report |
"""

SCRIPT = """Connect-MgGraph -Environment $Environment -Scopes @(
    "Group.Read.All",
    "CopilotCostManagement.Read.All"
)"""

CFG = {"site": {"title": "Watch", "url": "https://example.github.io/watch/"},
       "blog": {"repo": "me/Copilot", "author": "Me", "hashtags": ["Copilot"]}}


class BlogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.src = base / "src"
        proj = self.src / "Billing Health Check"
        proj.mkdir(parents=True)
        (proj / "README.md").write_text(README)
        (proj / "Get-CopilotBillingHealth.ps1").write_text(SCRIPT)
        (self.src / "Draft Without Readme").mkdir()
        (self.src / ".github").mkdir()
        (self.src / "README.md").write_text(ROOT_README)
        docs = base / "docs"
        self.patches = [mock.patch.object(blog, "DATA", docs / "data" / "blog.json"),
                        mock.patch.object(blog, "PAGES", docs / "blog")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_step_sections_are_removed(self):
        rm = blog.readme_material(README)
        self.assertEqual(rm["title"], "Copilot Billing Health Check")
        self.assertNotIn("Install-Module", rm["text"])
        self.assertNotIn("SkipBalances", rm["text"])          # code and Parameters gone
        self.assertIn("What it checks", rm["text"])
        self.assertEqual(rm["needs"], ["A Global Reader or Billing Administrator role", "PowerShell 7"])
        self.assertTrue(rm["intro"][0].startswith("A read-only health check"))   # byline skipped

    def test_new_folders_get_one_post_each(self):
        made = blog.run(self.src, CFG, use_ai=False, today="2026-11-01T12:00:00+00:00")
        self.assertEqual(made, ["Billing Health Check"])      # no readme, dot folder: skipped
        post = json.loads(blog.DATA.read_text())["posts"][0]
        self.assertEqual(post["source"], "https://github.com/me/Copilot/tree/main/Billing%20Health%20Check")
        self.assertIn("Microsoft Graph permissions: CopilotCostManagement.Read.All, Group.Read.All", post["needs"])
        self.assertIn("https://example.github.io/watch/blog/billing-health-check.html", post["linkedin"])
        self.assertTrue(post["linkedin"].endswith("#Copilot"))
        self.assertFalse(blog.has_steps(post["linkedin"]))
        page = (blog.PAGES / "billing-health-check.html").read_text()
        self.assertIn('property="og:title"', page)
        self.assertEqual(blog.run(self.src, CFG, use_ai=False), [])   # written once only

    def test_regenerate_and_readme_change(self):
        blog.run(self.src, CFG, use_ai=False)
        (self.src / "Billing Health Check" / "README.md").write_text(README + "\nMore.\n")
        blog.run(self.src, CFG, use_ai=False)
        self.assertTrue(json.loads(blog.DATA.read_text())["posts"][0]["readme_changed"])
        self.assertEqual(blog.run(self.src, CFG, use_ai=False, force={"billing-health-check"}),
                         ["Billing Health Check"])

    def test_model_reply_with_steps_is_refused(self):
        good = {"title": "T", "summary": "S", "purpose": "P", "audience": "A",
                "needs": ["x"], "gets": ["y"], "linkedin": "Hook\n\n{LINK}"}
        self.assertIsNotNone(blog.parse_reply(json.dumps(good)))
        bad = dict(good, purpose="First run Install-Module Microsoft.Graph")
        self.assertIsNone(blog.parse_reply(json.dumps(bad)))
        self.assertIsNone(blog.parse_reply("not json"))


if __name__ == "__main__":
    unittest.main()
