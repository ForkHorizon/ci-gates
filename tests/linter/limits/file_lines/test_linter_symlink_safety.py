import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_security", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_security"] = linter
spec.loader.exec_module(linter)

paths = importlib.import_module("code_linter.paths")
runner = importlib.import_module("code_linter.runner")


class SymlinkSafetyTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(mode="all", base="", head="", config=".code-linter.json")

    def init_repo(self, root, config="{}\n"):
        (root / ".code-linter.json").write_text(config, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)

    def assert_collection_rejected(self, root):
        with self.assertRaises(SystemExit) as raised:
            linter.collect_paths(root, linter.load_config(root / ".code-linter.json"), self.args())
        self.assertEqual(raised.exception.code, 2)

    def test_in_repo_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.data").write_text("safe\n", encoding="utf-8")
            os.symlink("target.data", root / "linked.data")
            self.init_repo(root)
            self.assert_collection_rejected(root)

    def test_ignored_symlink_is_rejected_before_ignore_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.symlink("missing.py", root / "linked.py")
            self.init_repo(root, '{"ignore": ["linked.py"]}\n')
            self.assert_collection_rejected(root)

    def test_broken_unknown_symlink_is_rejected_before_target_stat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.symlink("missing.data", root / "linked.data")
            self.init_repo(root)
            self.assert_collection_rejected(root)

    def test_non_source_symlink_is_rejected_before_content_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.txt").write_text("secret\n", encoding="utf-8")
            os.symlink("target.txt", root / "linked.txt")
            self.init_repo(root)
            with patch.object(paths, "unknown_text_surface", side_effect=AssertionError("probed symlink")):
                self.assert_collection_rejected(root)

    def test_direct_reader_rejects_symlink_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.py"
            target.write_text("value = 1\n", encoding="utf-8")
            linked = root / "linked.py"
            os.symlink(target, linked)
            with patch.object(runner, "_read_limited_bytes", side_effect=AssertionError("opened symlink")):
                text, error = runner.read_source(linked, Path("linked.py"))
            self.assertIsNone(text)
            self.assertEqual(error.kind, "file_symlink")

    def test_oversized_file_short_circuits_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.py"
            source.write_bytes(b"x" * (linter.MAX_FILE_BYTES + 1))
            with patch.object(runner, "_read_limited_bytes", side_effect=AssertionError("opened large file")):
                text, error = runner.read_source(source, Path("large.py"))
            self.assertIsNone(text)
            self.assertEqual(error.kind, "file_size")

    def test_file_at_byte_limit_is_read_and_decoded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "limit.py"
            source.write_bytes(b"x" * linter.MAX_FILE_BYTES)
            text, error = runner.read_source(source, Path("limit.py"))
            self.assertIsNone(error)
            self.assertEqual(len(text), linter.MAX_FILE_BYTES)

    def test_growth_after_lstat_is_rejected_after_bounded_read(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "growing.py"
            source.write_text("x\n", encoding="utf-8")
            with patch.object(runner, "_read_limited_bytes", return_value=b"x" * (linter.MAX_FILE_BYTES + 1)):
                text, error = runner.read_source(source, Path("growing.py"))
            self.assertIsNone(text)
            self.assertEqual(error.kind, "file_size")

    def test_invalid_utf8_is_rejected_without_second_file_read(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.py"
            source.write_bytes(b"placeholder")
            with patch.object(runner, "_read_limited_bytes", return_value=b"\xff") as read:
                text, error = runner.read_source(source, Path("invalid.py"))
            self.assertIsNone(text)
            self.assertEqual(error.kind, "encoding")
            self.assertIn("UTF-8", error.message)
            read.assert_called_once_with(source)

    def test_limited_reader_requests_no_follow_open(self):
        with (
            patch.object(runner.os, "open", return_value=41) as open_file,
            patch.object(runner.os, "read", side_effect=[b"ok", b""]),
            patch.object(runner.os, "close"),
        ):
            self.assertEqual(runner._read_limited_bytes(Path("unused.py")), b"ok")
        flags = open_file.call_args.args[1]
        expected = runner.os.O_RDONLY | getattr(runner.os, "O_NOFOLLOW", 0)
        self.assertEqual(flags, expected)


if __name__ == "__main__":
    unittest.main()
