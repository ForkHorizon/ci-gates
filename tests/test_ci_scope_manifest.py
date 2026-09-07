import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ci_scope_manifest import ManifestError, canonical_manifest, load_manifest, resolve_manifest, validate_only


def valid_manifest():
    return {
        "version": 1,
        "checks": [
            {"id": "code-linter", "type": "code-linter", "config": ".code-linter.json"},
            {"id": "slop-review", "type": "slop-review", "depends_on": ["code-linter"]},
        ],
    }


class CiScopeManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".code-linter.json").write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_resolves_catalog_types_and_filters_event(self):
        result = resolve_manifest(valid_manifest(), root=self.root, event="merge_group")
        self.assertEqual([check.id for check in result.active_checks], ["code-linter", "slop-review"])
        self.assertTrue(result.checks[0].required)
        self.assertFalse(result.checks[1].required)
        self.assertEqual(result.checks[1].resources, ("ollama",))

    def test_unknown_type_and_parameter_fail_closed(self):
        value = valid_manifest()
        value["checks"][0]["type"] = "run-shell"
        with self.assertRaisesRegex(ManifestError, "unknown check type"):
            resolve_manifest(value, root=self.root)
        value = valid_manifest()
        value["checks"][0]["params"] = {"command": "echo unsafe"}
        with self.assertRaisesRegex(ManifestError, "unknown parameter"):
            resolve_manifest(value, root=self.root)
        value = valid_manifest()
        value["checks"][0]["params"] = {1: "unsafe"}
        with self.assertRaisesRegex(ManifestError, "parameter names must be strings"):
            resolve_manifest(value, root=self.root)

    def test_required_status_is_trusted_catalog_policy(self):
        value = valid_manifest()
        value["checks"][0]["required"] = False
        with self.assertRaisesRegex(ManifestError, "fixed by the trusted catalog"):
            resolve_manifest(value, root=self.root)

    def test_duplicate_ids_missing_dependencies_and_cycles_fail(self):
        value = valid_manifest()
        value["checks"][1]["id"] = "code-linter"
        with self.assertRaisesRegex(ManifestError, "duplicates"):
            resolve_manifest(value, root=self.root)
        value = valid_manifest()
        value["checks"][1]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(ManifestError, "unknown check"):
            resolve_manifest(value, root=self.root)
        value = valid_manifest()
        value["checks"][0]["depends_on"] = ["slop-review"]
        with self.assertRaisesRegex(ManifestError, "dependency cycle"):
            resolve_manifest(value, root=self.root)

    def test_paths_are_relative_and_symlink_escape_is_rejected(self):
        value = valid_manifest()
        value["checks"][0]["config"] = "../outside.json"
        with self.assertRaisesRegex(ManifestError, "relative path"):
            resolve_manifest(value, root=self.root)
        outside = self.root.parent / "ci-scope-outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        try:
            (self.root / "linked.json").symlink_to(outside)
            value = valid_manifest()
            value["checks"][0]["config"] = "linked.json"
            with self.assertRaisesRegex(ManifestError, "outside"):
                resolve_manifest(value, root=self.root)
        finally:
            outside.unlink()

    def test_load_and_validate_only_cli_are_deterministic(self):
        path = self.root / ".ci-scope.json"
        path.write_text(json.dumps(valid_manifest()), encoding="utf-8")
        result = validate_only(path, root=self.root)
        self.assertEqual(canonical_manifest(result)["version"], 1)
        command = [sys.executable, str(ROOT / "scripts/validate-ci-scope.py"), "--root", str(self.root), "--validate-only"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["version"], 1)

    def test_malformed_json_is_rejected(self):
        path = self.root / "bad.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "invalid JSON"):
            load_manifest(path)


if __name__ == "__main__":
    unittest.main()
