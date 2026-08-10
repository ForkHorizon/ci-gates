import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
paths = importlib.import_module("code_linter.paths")
code_linter = importlib.import_module("code_linter")
swift_paths = importlib.import_module("swift_quality_support")


class NonUTF8GitPathTests(unittest.TestCase):
    def completed(self, stdout=b"", stderr=b"", returncode=0):
        return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)

    def assert_preserves_raw_name(self, path):
        self.assertEqual(os.fsencode(path.name), b"bad\xff.py")
        self.assertTrue(str(path).endswith("bad\udcff.py"))

    def test_code_linter_all_repo_paths_preserves_non_utf8_filename(self):
        with patch.object(paths.subprocess, "run", return_value=self.completed(b"src/bad\xff.py\0")):
            found = paths.all_repo_paths(Path("/repo"))
        self.assertEqual(len(found), 1)
        self.assert_preserves_raw_name(found[0])

    def test_code_linter_changed_paths_preserves_non_utf8_filename(self):
        with patch.object(
            paths.subprocess,
            "run",
            return_value=self.completed(b"src/bad\xff.py\0"),
        ) as run:
            found = paths.changed_paths(Path("/repo"), "base", "head")
        self.assertEqual(len(found), 1)
        self.assert_preserves_raw_name(found[0])
        self.assertFalse(run.call_args.kwargs["text"])

    def test_code_linter_git_error_with_non_utf8_stderr_is_structured(self):
        failed = self.completed(stderr=b"git failed: \xff\n", returncode=1)
        error = io.StringIO()
        with (
            patch.object(paths.subprocess, "run", side_effect=[failed, failed]),
            contextlib.redirect_stderr(error),
            self.assertRaises(SystemExit),
        ):
            paths.changed_paths(Path("/repo"), "base", "head")
        self.assertIn("Unable to collect changed files", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

    def test_github_diagnostic_escapes_filesystem_surrogate_bytes(self):
        self.assertEqual(code_linter.escape_github_data("bad\udcff.py"), "bad%FF.py")

    def test_swift_all_repo_paths_preserves_non_utf8_filename(self):
        with patch.object(swift_paths.subprocess, "run", return_value=self.completed(b"src/bad\xff.py\0")):
            found = swift_paths.all_repo_paths(Path("/repo"))
        self.assertEqual(len(found), 1)
        self.assert_preserves_raw_name(found[0])

    def test_swift_changed_paths_preserves_non_utf8_filename(self):
        with patch.object(
            swift_paths.subprocess,
            "run",
            return_value=self.completed(b"src/bad\xff.py\0"),
        ) as run:
            found = swift_paths.changed_paths(Path("/repo"), "base", "head")
        self.assertEqual(len(found), 1)
        self.assert_preserves_raw_name(found[0])
        self.assertFalse(run.call_args.kwargs["text"])

    def test_swift_git_error_with_non_utf8_stderr_is_structured(self):
        failed = self.completed(stderr=b"git failed: \xff\n", returncode=1)
        with (
            patch.object(swift_paths.subprocess, "run", side_effect=[failed, failed]),
            self.assertRaises(SystemExit),
        ):
            swift_paths.changed_paths(Path("/repo"), "base", "head")

    def test_real_git_can_report_non_utf8_tracked_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_name = os.fsdecode(b"bad\xff.py")
            path = root / raw_name
            try:
                with open(os.fsencode(path), "wb") as source:
                    source.write(b"value = 1\n")
            except OSError as error:
                self.skipTest(f"filesystem rejects invalid-byte names: {error}")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            found = paths.all_repo_paths(root)
        self.assertEqual([os.fsencode(item.name) for item in found], [b"bad\xff.py"])


if __name__ == "__main__":
    unittest.main()
