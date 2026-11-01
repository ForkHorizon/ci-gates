import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.policy_preflight import (
    make_policy_record,
    preflight,
)


class PolicyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".ci-scope.json").write_text('{"version":1}\n', encoding="utf-8")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/ci-scope.yml").write_text("name: CI Scope\n", encoding="utf-8")
        self.policy_path = self.root.parent / "policy.json"
        files = {
            ".ci-scope.json": _sha(self.root / ".ci-scope.json"),
            ".github/workflows/ci-scope.yml": _sha(self.root / ".github/workflows/ci-scope.yml"),
        }
        self.policy_path.write_text(
            json.dumps(
                make_policy_record(
                    repository="ForkHorizon/Soma",
                    branch="developer",
                    approved_sha="a" * 40,
                    files=files,
                    protected_patterns=(".github/workflows/**",),
                    gates_sha="b" * 40,
                    checks=({"id": "code-linter", "required": True},),
                )
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()
        self.policy_path.unlink(missing_ok=True)

    def test_approved_checkout_passes_without_signature_only_when_explicit(self):
        result = preflight(
            self.root,
            self.policy_path,
            repository="ForkHorizon/Soma",
            branch="developer",
            require_signature=False,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.status, "passed")

    def test_signature_is_required_by_default(self):
        result = preflight(self.root, self.policy_path, require_signature=True)
        self.assertEqual(result.status, "policy_signature_invalid")

    def test_gates_pin_is_bound_to_policy(self):
        result = preflight(self.root, self.policy_path, gates_sha="c" * 40, require_signature=False)
        self.assertEqual(result.status, "policy_mismatch")

    def test_changed_protected_file_fails_closed(self):
        (self.root / ".ci-scope.json").write_text('{"version":2}\n', encoding="utf-8")
        result = preflight(self.root, self.policy_path, require_signature=False)
        self.assertEqual(result.status, "policy_mismatch")
        self.assertIn("changed:.ci-scope.json", result.mismatches)

    def test_deleted_file_fails_closed(self):
        (self.root / ".ci-scope.json").unlink()
        result = preflight(self.root, self.policy_path, require_signature=False)
        self.assertEqual(result.status, "policy_mismatch")
        self.assertIn("missing:.ci-scope.json", result.mismatches)

    def test_added_file_matching_protected_pattern_fails_closed(self):
        (self.root / ".github/workflows/extra.yml").write_text("name: bypass\n", encoding="utf-8")
        result = preflight(self.root, self.policy_path, require_signature=False)
        self.assertEqual(result.status, "policy_mismatch")
        self.assertIn("unexpected:.github/workflows/extra.yml", result.mismatches)

    def test_policy_digest_tampering_is_invalid(self):
        value = json.loads(self.policy_path.read_text(encoding="utf-8"))
        value["gates_sha"] = "c" * 40
        self.policy_path.write_text(json.dumps(value), encoding="utf-8")
        result = preflight(self.root, self.policy_path, require_signature=False)
        self.assertEqual(result.status, "policy_invalid")
        self.assertIn("policy_digest", result.reason)

    def test_digest_is_order_independent_for_checks_files_and_patterns(self):
        value = json.loads(self.policy_path.read_text(encoding="utf-8"))
        value["checks"] = [{"id": "z", "required": True}, {"id": "a", "required": False}]
        value["protected_patterns"] = ["z/**", "a/**"]
        value["files"] = list(reversed(value["files"]))
        unsigned = {key: item for key, item in value.items() if key != "policy_digest"}
        sorted_value = {
            **unsigned,
            "checks": sorted(value["checks"], key=lambda item: item["id"]),
            "protected_patterns": sorted(value["protected_patterns"]),
            "files": sorted(value["files"], key=lambda item: item["path"]),
        }
        value["policy_digest"] = make_policy_record(
            **{**sorted_value, "files": {item["path"]: item["sha256"] for item in sorted_value["files"]}}
        )["policy_digest"]
        self.policy_path.write_text(json.dumps(value), encoding="utf-8")
        result = preflight(self.root, self.policy_path, require_signature=False)
        self.assertNotEqual(result.status, "policy_invalid", result.reason)
        value["checks"][0]["required"] = False
        self.policy_path.write_text(json.dumps(value), encoding="utf-8")
        tampered = preflight(self.root, self.policy_path, require_signature=False)
        self.assertEqual(tampered.status, "policy_invalid")

    def test_repository_and_branch_are_bound_to_record(self):
        result = preflight(
            self.root,
            self.policy_path,
            repository="ForkHorizon/Other",
            branch="developer",
            require_signature=False,
        )
        self.assertEqual(result.status, "policy_mismatch")

        result = preflight(
            self.root,
            self.policy_path,
            repository="ForkHorizon/Soma",
            branch="developer",
            base_sha="c" * 40,
            require_signature=False,
        )
        self.assertEqual(result.status, "policy_mismatch")
        result = preflight(
            self.root,
            self.policy_path,
            repository="ForkHorizon/Soma",
            branch="main",
            require_signature=False,
        )
        self.assertEqual(result.status, "policy_mismatch")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
