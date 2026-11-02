import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "protected_files.py"
SPEC = importlib.util.spec_from_file_location("protected_files", SCRIPT)
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["protected_files"] = pf
SPEC.loader.exec_module(pf)

CARGO = '[workspace]\nmembers = ["crates/*"]\n\n[workspace.dependencies]\nserde = "1"\n\n[workspace.lints.rust]\nunsafe_code = "forbid"\n\n[workspace.lints.clippy]\nall = "warn"\n'
PACKAGE = json.dumps({"name": "client", "version": "1.0.0", "scripts": {"test": "node --test", "typecheck": "tsc --noEmit", "start": "node ."}, "dependencies": {"a": "1"}}, separators=(",", ":"))
PYPROJECT = '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["E"]\n'
PATTERNS = ["Cargo.toml", "**/Cargo.toml", "package.json", "deny.toml", "clippy.toml", ".github/**"]

# Fingerprints produced by CI-Scope-Web protected-files-contract.ts for the same inputs.
TYPESCRIPT_VECTORS = {
    ("Cargo.toml", CARGO): "ebdb8188030fb511bab7aeaced039b72c3fd65ae91dd50b804ea2e97d90063ab",
    ("package.json", PACKAGE): "8739c55ffd6b5eef13b309bc01b7907f926a8b0a48304ab54dfbb1665b62d446",
    ("pyproject.toml", PYPROJECT): "1290bc9cfa09d4679fa472d3e8e771eb85f707c0a884c5576d885945e516022e",
    ("deny.toml", "[advisories]\n"): "29c3b3fd47a73c667752eba9599a53ab6eb24d3a4eb5e8c5786d7519cd8bd1ad",
}


class ProtectedFilesTests(unittest.TestCase):
    def kinds(self, observed, baseline=None):
        baseline = baseline or {
            "Cargo.toml": pf.fingerprint_file("Cargo.toml", CARGO),
            "package.json": pf.fingerprint_file("package.json", PACKAGE),
            "deny.toml": pf.fingerprint_file("deny.toml", "[advisories]\n"),
        }
        return [f"{item.kind}:{item.path}" for item in pf.check_protected_files(baseline, observed, PATTERNS)]

    def same(self):
        return {"Cargo.toml": CARGO, "package.json": PACKAGE, "deny.toml": "[advisories]\n"}

    def test_fingerprints_match_the_typescript_implementation(self):
        for (path, content), expected in TYPESCRIPT_VECTORS.items():
            with self.subTest(path=path):
                self.assertEqual(pf.fingerprint_file(path, content), expected)

    def test_patterns(self):
        self.assertTrue(pf.matches_pattern("**/Cargo.toml", "Cargo.toml"))
        self.assertTrue(pf.matches_pattern("**/Cargo.toml", "crates/a/Cargo.toml"))
        self.assertFalse(pf.matches_pattern("Cargo.toml", "crates/a/Cargo.toml"))
        self.assertTrue(pf.matches_pattern(".github/**", ".github/workflows/ci.yml"))
        self.assertTrue(pf.matches_pattern(".eslintrc*", ".eslintrc.json"))
        self.assertFalse(pf.matches_pattern(".eslintrc*", "src/.eslintrc.json"))
        self.assertFalse(pf.matches_pattern("Cargo.toml", "Cargo-toml"))
        self.assertEqual(pf.select_protected_paths(["src/a.rs", "Cargo.toml", "crates/x/Cargo.toml", "deny.toml"], PATTERNS), ["Cargo.toml", "crates/x/Cargo.toml", "deny.toml"])

    def test_unchanged_and_dependency_edits_pass(self):
        self.assertEqual(self.kinds(self.same()), [])
        bumped = {**self.same(), "Cargo.toml": CARGO.replace('serde = "1"', 'serde = "2"')}
        self.assertEqual(self.kinds(bumped), [])
        dep = {**self.same(), "package.json": json.dumps({**json.loads(PACKAGE), "dependencies": {"a": "1", "b": "2"}})}
        self.assertEqual(self.kinds(dep), [])

    def test_lint_weakening_is_caught(self):
        weakened = CARGO.replace("[workspace.lints.clippy]", 'unused_variables = "allow"\ndead_code = "allow"\n\n[workspace.lints.clippy]')
        self.assertEqual(self.kinds({**self.same(), "Cargo.toml": weakened}), ["modified:Cargo.toml"])
        self.assertEqual(self.kinds({**self.same(), "Cargo.toml": CARGO.replace('all = "warn"', 'all = "allow"')}), ["modified:Cargo.toml"])

    def test_new_test_hook_script_is_caught(self):
        scripts = {**json.loads(PACKAGE)["scripts"], "pretest": "cargo build"}
        changed = json.dumps({**json.loads(PACKAGE), "scripts": scripts})
        self.assertEqual(self.kinds({**self.same(), "package.json": changed}), ["modified:package.json"])

    def test_deleted_added_and_ignored_files(self):
        self.assertEqual(self.kinds({**self.same(), "deny.toml": None}), ["deleted:deny.toml"])
        missing = self.same()
        del missing["deny.toml"]
        self.assertEqual(self.kinds(missing), ["deleted:deny.toml"])
        self.assertEqual(self.kinds({**self.same(), "clippy.toml": "x = 1\n"}), ["added:clippy.toml"])
        self.assertEqual(self.kinds({**self.same(), "src/main.rs": "fn main() {}"}), [])
        self.assertEqual(self.kinds({**self.same(), ".github/workflows/x.yml": "name: x\n"}), ["added:.github/workflows/x.yml"])


if __name__ == "__main__":
    unittest.main()
