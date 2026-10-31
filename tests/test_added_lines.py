import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.added_lines import added_lines, parse_hunks


class AddedLinesTests(unittest.TestCase):
    def test_hunks_return_only_added_line_numbers(self):
        diff = "@@ -2,2 +2,3 @@\n-old\n+one\n+two\n same\n@@ -9 +11,0 @@\n-removed\n"
        self.assertEqual(parse_hunks(diff), {2, 3})

    def test_added_source_starting_with_double_plus_is_counted(self):
        diff = "diff --git a/source.js b/source.js\n--- a/source.js\n+++ b/source.js\n@@ -1 +1 @@\n-old\n+++counter;\n"
        self.assertEqual(parse_hunks(diff), {1})

    def test_worktree_includes_uncommitted_and_untracked_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            tracked = root / "tracked.py"
            tracked.write_text("old = 1\n")
            subprocess.run(["git", "-C", str(root), "add", "tracked.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            tracked.write_text("old = 1\nnew = 2\n")
            (root / "untracked.py").write_text("fresh = 3\n")
            result = added_lines(root, "worktree")
            self.assertEqual(result, {"tracked.py": {2}, "untracked.py": {1}})


if __name__ == "__main__":
    unittest.main()
