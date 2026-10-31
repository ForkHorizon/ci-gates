import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.duplicate_blocks import CheckOptions, check, find_duplicates, significant_lines


class DuplicateBlocksTests(unittest.TestCase):
    def test_normalization_drops_blank_comments_imports_and_closers(self):
        lines = significant_lines(["import os", "# note", "  ", "value = 1", "}"])
        self.assertEqual(lines, ["value = 1"])
        self.assertEqual(significant_lines(["*args = values"]), ["*args = values"])

    def test_added_twelve_line_copy_is_reported_but_six_line_copy_is_not(self):
        source = Path(__file__).parent / "fixtures/duplicate_source.py"
        block = source.read_text().splitlines()[1:]
        files = {"source.py": source.read_text().splitlines(), "copy.py": block}
        added = {"copy.py": set(range(1, len(block) + 1))}
        self.assertTrue(find_duplicates(files, added, min_lines=10))
        short_files = {
            "source.py": source.read_text().splitlines(),
            "copy.py": block[:6],
        }
        short_added = {"copy.py": set(range(1, 7))}
        self.assertEqual(find_duplicates(short_files, short_added, min_lines=10), [])

    def test_overlapping_matches_merge_to_one_report(self):
        block = [f"value_{index} = {index}" for index in range(12)]
        files = {"source.py": block, "copy.py": block + block[2:10]}
        matches = find_duplicates(files, {"copy.py": set(range(1, 21))}, min_lines=10)
        self.assertEqual(len(matches), 1)

    def test_worktree_copy_compares_against_unchanged_source(self):
        source = Path(__file__).parent / "fixtures/duplicate_source.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "source.py").write_text(source.read_text())
            subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            (root / "copy.py").write_text(source.read_text())
            matches = check(root, CheckOptions("new", "worktree", "HEAD~1", "HEAD", 10, None))
            self.assertTrue(matches)


if __name__ == "__main__":
    unittest.main()
