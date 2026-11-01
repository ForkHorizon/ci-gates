"""Tests for the AGENTS.md / CLAUDE.md volatile-fact gate."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_docs_stable import check, scan_text


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class ScanTextTests(unittest.TestCase):
    def rules(self, text):
        return [rule for _, rule, _ in scan_text(text)]

    def test_flags_dates_markers_shas_and_pr_numbers(self):
        self.assertEqual(self.rules("Decommissioned 2026-09-14."), ["no-date"])
        self.assertEqual(self.rules("Last updated by the team"), ["no-updated-marker"])
        self.assertEqual(self.rules("pin " + "a" * 40), ["no-commit-sha"])
        self.assertEqual(self.rules("see PR #123"), ["no-pr-number"])

    def test_stable_prose_passes(self):
        self.assertEqual(self.rules("Run `scripts/check` before committing. Repos talk only over contracts."), [])

    def test_suppression_needs_a_reason(self):
        self.assertEqual(self.rules("Cutover 2026-09-14 <!-- allow-volatile: historical anchor -->"), [])
        self.assertEqual(self.rules("Cutover 2026-09-14 <!-- allow-volatile: -->"), ["no-date"])

    def test_only_selected_lines_are_scanned(self):
        text = "old 2026-01-01\nnew 2026-02-02\n"
        self.assertEqual([number for number, _, _ in scan_text(text, {2})], [2])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "AGENTS.md").write_text("Existing note from 2026-01-01.\n")
        (self.root / "README.md").write_text("Dated 2026-01-01.\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.temp.cleanup()

    def test_new_mode_ignores_existing_lines_and_other_files(self):
        self.assertEqual(check(self.root, "new", "worktree", "HEAD~1", "HEAD"), [])
        (self.root / "AGENTS.md").write_text("Existing note from 2026-01-01.\nStatus as of today.\n")
        (self.root / "README.md").write_text("Dated 2026-01-01.\nUpdated on Monday.\n")
        found = check(self.root, "new", "worktree", "HEAD~1", "HEAD")
        self.assertEqual([(f.path, f.line, f.rule_id) for f in found], [("AGENTS.md", 2, "no-updated-marker")])

    def test_all_mode_scans_every_agent_doc_but_not_other_markdown(self):
        found = check(self.root, "all", "worktree", "HEAD~1", "HEAD")
        self.assertEqual([f.path for f in found], ["AGENTS.md"])

    def test_nested_claude_md_is_covered(self):
        (self.root / "sub").mkdir()
        (self.root / "sub/CLAUDE.md").write_text("Done 2026-03-03\n")
        found = check(self.root, "new", "worktree", "HEAD~1", "HEAD")
        self.assertEqual([f.path for f in found], ["sub/CLAUDE.md"])


if __name__ == "__main__":
    unittest.main()
