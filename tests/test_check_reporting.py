import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_reporting", ROOT / "scripts/check_reporting.py")
REPORTING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORTING)


class CheckReportingTests(unittest.TestCase):
    def test_writes_redacted_bounded_atomic_artifacts_and_split_timings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "ghp_" + "x" * 30
            REPORTING.write_report(
                root,
                ({"message": f"token={secret}", "path": "/Users/a/private"} for _ in range(1100)),
                {"status": "ok"},
                ordinary_ms=12,
                ai_ms=34,
            )
            events = (root / "events.jsonl").read_text().splitlines()
            result = json.loads((root / "result.json").read_text())
            self.assertEqual(len(events), 1000)
            self.assertNotIn(secret, "\n".join(events))
            self.assertNotIn("/Users/a/private", events[0])
            self.assertEqual(result["timings"], {"ordinary_ms": 12, "ai_ms": 34})

    def test_redacts_secrets_in_object_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            secret = "ghp_" + "x" * 30
            REPORTING.write_events(path, [{f"credential={secret}": "value"}])
            self.assertNotIn(secret, path.read_text())

    def test_empty_events_is_empty_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            REPORTING.write_events(path, [])
            self.assertEqual(path.read_text(), "")


if __name__ == "__main__":
    unittest.main()
