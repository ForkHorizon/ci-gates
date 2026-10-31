import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from code_linter.paths import candidate_paths


class WorktreePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "config",
                "user.email",
                "test@example.invalid",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        (self.root / ".code-linter.json").write_text("{}\n")
        (self.root / "tracked.py").write_text("old = 1\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"], check=True)
        (self.root / "tracked.py").write_text("committed = 1\n")
        subprocess.run(["git", "-C", str(self.root), "add", "tracked.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "second"], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def paths(self, mode):
        return {
            path.relative_to(self.root).as_posix()
            for path in candidate_paths(
                self.root,
                Namespace(mode=mode, base="HEAD", head="HEAD", config=".code-linter.json"),
            )
        }

    def test_worktree_includes_uncommitted_and_untracked_but_changed_does_not(self):
        (self.root / "tracked.py").write_text("new = 2\n")
        (self.root / "new.py").write_text("new = 3\n")
        self.assertEqual(self.paths("changed"), set())
        self.assertEqual(self.paths("worktree"), {"tracked.py", "new.py"})


if __name__ == "__main__":
    unittest.main()
