"""The file_length message tells test-file authors that a split is allowed."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from code_linter.config import LIMIT_DEFAULTS
from code_linter.runner import source_issues

LIMITS = {**LIMIT_DEFAULTS, "max_file_lines": 3}


class SplitHintTests(unittest.TestCase):
    def messages(self, path):
        return [
            issue.message for issue in source_issues(Path(path), "\n" * 10, None, LIMITS) if issue.kind == "file_length"
        ]

    def test_test_files_get_the_split_hint(self):
        self.assertIn("Split it into modules", self.messages("crates/x/tests/codex.rs")[0])

    def test_other_files_keep_the_plain_message(self):
        self.assertNotIn("Split it", self.messages("src/app.rs")[0])


if __name__ == "__main__":
    unittest.main()
