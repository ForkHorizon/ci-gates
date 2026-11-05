"""Rust scenarios for the existing-test protection detector: moved, disabled and ignored tests."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_protection import scan


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


FIRST, SECOND = (
    "#[test]\nfn one() {\n    assert_eq!(1, 1);\n}\n\n",
    '#[tokio::test(flavor = "multi_thread")]\nasync fn two() {\n    assert!(true);\n    assert!(2 > 1);\n}\n',
)
BIG = FIRST + SECOND
CARGO = '[package]\nname = "x"\n'


class RustScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "tests").mkdir()
        (self.root / "tests/big.rs").write_text(BIG)
        (self.root / "Cargo.toml").write_text(CARGO)
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.temp.cleanup()

    def found(self):
        return sorted(f.rule_id for f in scan(self.root, "worktree", "HEAD~1", "HEAD"))

    def split(self, *, keep_asserts=True):
        (self.root / "tests/big").mkdir()
        (self.root / "tests/big/a.rs").write_text(FIRST)
        (self.root / "tests/big/b.rs").write_text(SECOND if keep_asserts else SECOND.replace("assert!(2 > 1);", ""))

    def test_splitting_a_file_and_deleting_the_original_is_allowed(self):
        self.split()
        (self.root / "tests/big.rs").unlink()
        self.assertEqual(self.found(), [])

    def test_deleting_a_test_file_without_moving_its_tests_is_blocked(self):
        (self.root / "tests/big.rs").unlink()
        self.assertEqual(self.found(), ["test-deleted"])

    def test_a_move_that_drops_a_test_or_assertions_is_blocked(self):
        self.split(keep_asserts=False)
        (self.root / "tests/big.rs").unlink()
        self.assertEqual(self.found(), ["test-deleted"])
        (self.root / "tests/big/b.rs").unlink()
        self.assertEqual(self.found(), ["test-deleted"])

    def test_turning_off_test_discovery_in_cargo_toml_is_blocked(self):
        (self.root / "Cargo.toml").write_text(CARGO + "autotests = false\n")
        self.assertEqual(self.found(), ["test-build-config-changed"])
        (self.root / "Cargo.toml").write_text(CARGO + '\n[[test]]\nname = "big"\npath = "tests/other.rs"\n')
        self.assertEqual(self.found(), ["test-build-config-changed"])

    def test_unrelated_cargo_toml_edits_pass(self):
        (self.root / "Cargo.toml").write_text(CARGO + 'version = "2"\n[dependencies]\nfoo = "1"\n')
        self.assertEqual(self.found(), [])

    def test_new_ignore_and_empty_cfg_markers_are_flagged(self):
        (self.root / "tests/new.rs").write_text("#[test]\n#[ignore]\nfn a() {}\n\n#[cfg(any())]\n#[test]\nfn b() {}\n")
        git(self.root, "add", "-N", "tests/new.rs")
        self.assertEqual(self.found(), ["test-skip-added", "test-skip-added"])


if __name__ == "__main__":
    unittest.main()
