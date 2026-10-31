import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from swift_quality_support import collect_swift_paths


class SwiftWorktreeTests(unittest.TestCase):
    def test_format_path_collection_includes_uncommitted_swift_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            path = root / "Changed.swift"
            path.write_text("struct Old {}\n")
            subprocess.run(["git", "-C", str(root), "add", "Changed.swift"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            path.write_text("struct New {}\n")
            actual = collect_swift_paths(root, {"ignore": []}, Namespace(mode="worktree", base="", head=""))
            self.assertEqual(actual, [path])


if __name__ == "__main__":
    unittest.main()
