import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
config_io = importlib.import_module("code_linter.config_io")
code_linter = importlib.import_module("code_linter")


class ConfigProbeStream:
    def __init__(self, payload=b"{}\n", read_error=None):
        self.payload = payload
        self.read_error = read_error
        self.requested = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size):
        self.requested = size
        if self.read_error is not None:
            raise self.read_error
        return self.payload[:size]


class BoundedConfigReadTests(unittest.TestCase):
    def make_path(self, directory, name=".code-linter.json"):
        path = Path(directory) / name
        path.write_text("{}\n", encoding="utf-8")
        return path

    def capture_config_error(self, path, action, *fragments):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            action()
        report = error.getvalue()
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("Traceback", report)
        self.assertIn(f"file={path.as_posix()}", report)
        for fragment in fragments:
            self.assertIn(fragment, report)
        return report

    def test_config_probe_requests_only_one_byte_beyond_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream()
            with patch.object(Path, "open", return_value=stream):
                text = config_io.read_config_text(path, config_io.config_error)
        self.assertEqual(text, "{}\n")
        self.assertEqual(stream.requested, config_io.MAX_CONFIG_BYTES + 1)

    def test_config_probe_does_not_use_unbounded_read_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream()
            with (
                patch.object(Path, "open", return_value=stream),
                patch.object(Path, "read_text", side_effect=AssertionError("unbounded config read")),
            ):
                text = config_io.read_config_text(path, config_io.config_error)
        self.assertEqual(text, "{}\n")
        self.assertEqual(stream.requested, config_io.MAX_CONFIG_BYTES + 1)

    def test_oversized_config_is_rejected_without_loading_the_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream(b"{" + b" " * config_io.MAX_CONFIG_BYTES + b"}")
            with patch.object(Path, "open", return_value=stream):
                report = self.capture_config_error(
                    path,
                    lambda: config_io.read_config_text(path, config_io.config_error),
                    "Code Linter config exceeds safety limit",
                )
        self.assertNotIn("Traceback", report)

    def test_config_at_limit_is_returned_for_json_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream(b"{" + b" " * (config_io.MAX_CONFIG_BYTES - 2) + b"}")
            with patch.object(Path, "open", return_value=stream):
                self.assertEqual(code_linter.load_config(path), code_linter.DEFAULT_CONFIG)
        self.assertEqual(stream.requested, config_io.MAX_CONFIG_BYTES + 1)

    def test_open_os_error_remains_a_structured_config_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            with patch.object(Path, "open", side_effect=PermissionError(13, "Permission denied")):
                report = self.capture_config_error(
                    path,
                    lambda: config_io.read_config_text(path, config_io.config_error),
                    "Unable to read Code Linter config",
                    "Permission denied",
                )
        self.assertNotIn("Traceback", report)

    def test_stream_read_os_error_remains_a_structured_config_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream(read_error=OSError(5, "Input/output error"))
            with patch.object(Path, "open", return_value=stream):
                report = self.capture_config_error(
                    path,
                    lambda: config_io.read_config_text(path, config_io.config_error),
                    "Unable to read Code Linter config",
                    "Input/output error",
                )
        self.assertEqual(stream.requested, config_io.MAX_CONFIG_BYTES + 1)
        self.assertNotIn("Traceback", report)

    def test_invalid_utf8_remains_a_structured_config_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ConfigProbeStream(b"{\xff")
            with patch.object(Path, "open", return_value=stream):
                report = self.capture_config_error(
                    path,
                    lambda: config_io.read_config_text(path, config_io.config_error),
                    "Unable to read Code Linter config",
                    "UTF-8",
                )
        self.assertNotIn("Traceback", report)

    def test_public_cli_rejects_oversized_config_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".code-linter.json"
            config.write_bytes(b"{" + b" " * config_io.MAX_CONFIG_BYTES + b"}")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Code Linter config exceeds safety limit", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
