import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))
coverage = importlib.import_module("code_linter.coverage")


class ProbeStream:
    def __init__(self, payload=b"rule allow\n"):
        self.payload = payload
        self.requested = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size):
        self.requested = size
        return self.payload[:size]


class UnknownSurfaceProbeTests(unittest.TestCase):
    def make_path(self, directory, name="custom.dsl"):
        path = Path(directory) / name
        path.write_text("placeholder\n", encoding="utf-8")
        return path

    def test_probe_requests_only_configured_sample_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ProbeStream()
            with patch.object(Path, "open", return_value=stream):
                result = coverage.unknown_text_surface(path)
        self.assertEqual(result, ("unknown text/config", ".dsl"))
        self.assertEqual(stream.requested, coverage.UNKNOWN_TEXT_SAMPLE_BYTES)

    def test_probe_does_not_use_unbounded_read_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ProbeStream()
            with (
                patch.object(Path, "open", return_value=stream),
                patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded probe")),
            ):
                result = coverage.unknown_text_surface(path)
        self.assertEqual(result, ("unknown text/config", ".dsl"))
        self.assertEqual(stream.requested, coverage.UNKNOWN_TEXT_SAMPLE_BYTES)

    def test_probe_classifies_binary_marker_without_reading_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ProbeStream(b"a" * 8191 + b"\x00" + b"tail")
            with patch.object(Path, "open", return_value=stream):
                result = coverage.unknown_text_surface(path)
        self.assertIsNone(result)
        self.assertEqual(stream.requested, coverage.UNKNOWN_TEXT_SAMPLE_BYTES)

    def test_probe_classifies_utf8_prefix_as_unknown_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            stream = ProbeStream(("é" * 4096).encode("utf-8"))
            with patch.object(Path, "open", return_value=stream):
                result = coverage.unknown_text_surface(path)
        self.assertEqual(result, ("unknown text/config", ".dsl"))

    def test_probe_preserves_structured_read_error_on_open_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory)
            with patch.object(Path, "open", side_effect=PermissionError("denied")):
                result = coverage.unknown_text_surface(path)
        self.assertEqual(result.category, "coverage_read_error")
        self.assertEqual(result.extension, ".dsl")
        self.assertEqual(result.message, "Unable to read unknown coverage input.")

    def test_probe_skips_documentary_files_without_opening_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory, "README")
            with patch.object(Path, "open", side_effect=AssertionError("documentation probe")):
                result = coverage.unknown_text_surface(path)
        self.assertIsNone(result)

    def test_probe_skips_known_binary_extensionless_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory, "payload")
            stream = ProbeStream(b"\x00binary")
            with patch.object(Path, "open", return_value=stream):
                result = coverage.unknown_text_surface(path)
        self.assertIsNone(result)

    def test_probe_preserves_extensionless_unknown_label(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_path(directory, "custom")
            stream = ProbeStream()
            with patch.object(Path, "open", return_value=stream):
                result = coverage.unknown_text_surface(path)
        self.assertEqual(result, ("unknown text/config", "extensionless"))


if __name__ == "__main__":
    unittest.main()
