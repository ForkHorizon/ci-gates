"""Lock files are fingerprinted by where packages come from; approved content passes. Parity with CI-Scope-Web."""

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import ClassVar

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "protected_files.py"
SPEC = importlib.util.spec_from_file_location("protected_files", SCRIPT)
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["protected_files"] = pf
SPEC.loader.exec_module(pf)

LOCK = '[[package]]\nname = "futures-util"\nversion = "0.3.31"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
LOCK_BUMPED = LOCK.replace("0.3.31", "0.3.34")
LOCK_GIT = LOCK + '\n[[package]]\nname = "evil"\nsource = "git+https://example.test/evil#0123456789abcdef"\n'
DENY = "[advisories]\nignore = []\n"
DENY_NEW = '[advisories]\nignore = ["RUSTSEC-2026-0001"]\n'


class LockFileAndApprovalTests(unittest.TestCase):
    patterns: ClassVar[list[str]] = ["Cargo.lock", "deny.toml"]

    def baseline(self, lock_fingerprint=None):
        return {
            "Cargo.lock": lock_fingerprint or pf.fingerprint_file("Cargo.lock", LOCK),
            "deny.toml": pf.fingerprint_file("deny.toml", DENY),
        }

    def kinds(self, observed, baseline=None, approved=None):
        found = pf.check_protected_files(baseline or self.baseline(), observed, self.patterns, approved)
        return [f"{item.kind}:{item.path}" for item in found]

    def test_a_version_bump_in_a_lock_file_passes(self):
        self.assertEqual(self.kinds({"Cargo.lock": LOCK_BUMPED, "deny.toml": DENY}), [])

    def test_a_new_package_source_in_a_lock_file_is_caught(self):
        self.assertEqual(
            self.kinds({"Cargo.lock": LOCK_GIT, "deny.toml": DENY}),
            ["modified:Cargo.lock"],
        )

    def test_a_baseline_taken_when_lock_files_were_fingerprinted_whole_still_matches(
        self,
    ):
        legacy = hashlib.sha256(LOCK.encode("utf-8")).hexdigest()
        self.assertEqual(
            self.kinds({"Cargo.lock": LOCK, "deny.toml": DENY}, self.baseline(legacy)),
            [],
        )
        self.assertEqual(
            self.kinds({"Cargo.lock": LOCK_GIT, "deny.toml": DENY}, self.baseline(legacy)),
            ["modified:Cargo.lock"],
        )

    def test_approved_content_passes_and_nothing_else_does(self):
        approved = {"deny.toml": {pf.fingerprint_file("deny.toml", DENY_NEW)}}
        self.assertEqual(
            self.kinds({"Cargo.lock": LOCK, "deny.toml": DENY_NEW}, approved=approved),
            [],
        )
        self.assertEqual(
            self.kinds(
                {"Cargo.lock": LOCK, "deny.toml": DENY_NEW + "# more\n"},
                approved=approved,
            ),
            ["modified:deny.toml"],
        )
        self.assertEqual(
            self.kinds({"Cargo.lock": LOCK, "deny.toml": DENY_NEW}),
            ["modified:deny.toml"],
        )

    def test_an_approved_deletion_passes_whether_or_not_the_file_is_observed(self):
        approved = {"deny.toml": {None}}
        self.assertEqual(self.kinds({"Cargo.lock": LOCK, "deny.toml": None}, approved=approved), [])
        self.assertEqual(self.kinds({"Cargo.lock": LOCK}, approved=approved), [])
        self.assertEqual(self.kinds({"Cargo.lock": LOCK, "deny.toml": None}), ["deleted:deny.toml"])


# Produced by CI-Scope-Web lock-scope.ts via fingerprintFile for the same inputs: lock files are fingerprinted by
# where packages come from. Any change to how either side reads a lock file must change both.
LOCK_VECTORS = [
    (
        "Cargo.lock",
        '[[package]]\nname = "futures-util"\nversion = "0.3.31"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "aaa"\n\n[[package]]\nname = "x"\nsource = "git+https://example.test/x#0123456789abcdef"\n',
        "cbab9b43f99a9a8c27e2920249e8b0d9495577df02ff3e06370017b86544c00f",
    ),
    (
        "Cargo.lock",
        '[[package]]\nname = "local"\nversion = "0.1.0"\n',
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    (
        "package-lock.json",
        '{"packages":{"node_modules/a":{"version":"1.0.0","resolved":"https://registry.npmjs.org/a/-/a-1.0.0.tgz","integrity":"sha512-x"},"node_modules/b":{"resolved":"git+ssh://git@github.com/org/b.git#0123456789abcdef"}}}',
        "cb714b7476b043d63e1f586dc02b9b03d1796983500e6e63fcdecf9e15b14a96",
    ),
    (
        "pnpm-lock.yaml",
        "packages:\n  a@1.0.0:\n    resolution: {integrity: sha512-x, tarball: https://registry.npmjs.org/a/-/a-1.0.0.tgz}\n  b@github:org/b:\n    resolution: {tarball: https://codeload.github.com/org/b/tar.gz/0123456789abcdef}\n",
        "b37767b53ebbeeaedc904ca058c5cce0915b8976d5fb0c2d7e52631f854cb31c",
    ),
    (
        "uv.lock",
        '[[package]]\nname = "x"\nsource = { registry = "https://pypi.org/simple" }\n\n[[package]]\nname = "y"\nsource = { git = "https://example.test/y?rev=1111111#11111110123456" }\n',
        "59ecb9a2e9b05f7667d8c77020cc1f895dd336aa155ec463e1446270fa8e3213",
    ),
    (
        "yarn.lock",
        'a@^1:\n  version "1.0.0"\n  resolved "https://registry.yarnpkg.com/a/-/a-1.0.0.tgz#abcdef0123456789"\n',
        "eebcf0cdf28f7ab85b2cc0cb42e07b627aa54ce2b60940685c20bf7b78c87382",
    ),
]


class LockScopeParityTests(unittest.TestCase):
    def test_every_vector_matches_the_typescript_fingerprint(self):
        for path, content, expected in LOCK_VECTORS:
            with self.subTest(path=path):
                self.assertEqual(pf.fingerprint_file(path, content), expected)


if __name__ == "__main__":
    unittest.main()
