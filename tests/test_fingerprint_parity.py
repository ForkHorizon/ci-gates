import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "protected_files.py"
SPEC = importlib.util.spec_from_file_location("protected_files", SCRIPT)
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["protected_files"] = pf
SPEC.loader.exec_module(pf)

# Produced by CI-Scope-Web protected-files-contract.ts for the same inputs (fingerprintFile). Any change to how
# either side reads a file must change both, or these stop matching.
TYPESCRIPT_VECTORS = [
    (
        "Cargo.toml",
        '[workspace]\nmembers = ["crates/*"]\n\n[workspace.dependencies]\nserde = "1"\n\n[workspace.lints.rust]\nunsafe_code = "forbid"\n\n[workspace.lints.clippy]\nall = "warn"\n',
        "e1bd837456631cf2fdb49081229ce87f008fb0b4af8b11d844a7b1e8ca19a761",
    ),
    (
        "Cargo.toml",
        '[workspace]\nmembers = ["a"]\nlints.rust.unsafe_code = "forbid"\n',
        "26cf197e40e97490ce8783add57cf0fd19b27abb912f865c6700d5236a26152c",
    ),
    (
        "Cargo.toml",
        '[workspace]\nmembers = ["a"]\nlints.rust.unsafe_code = "allow"\n',
        "234aef69744b5b03c74d3425bc319c3918e478afb6cb1a58095f065fc5cb764c",
    ),
    (
        "Cargo.toml",
        '[workspace.lints.rust]\n"unsafe_code" = "forbid"\n',
        "26cf197e40e97490ce8783add57cf0fd19b27abb912f865c6700d5236a26152c",
    ),
    (
        "Cargo.toml",
        '[workspace.lints]\nrust = { unsafe_code = "forbid" }\n',
        "69b2735406e7ff17c332a1b1c7d968d2dfb3a8753a2abcdf520e5589ca421198",
    ),
    (
        "Cargo.toml",
        '[workspace.lints]\nrust = {\n  unsafe_code = "forbid",\n  dead_code = "warn"\n}\n',
        "93172aab31569601c60d627a8645c96ebeee5f1189496020c3cfa7d8a78bd62f",
    ),
    (
        "Cargo.toml",
        '[package]\nname = "x"\nlints.workspace = true\n',
        "2a2888ee9c398ccb3e9067d21c153e69506fe5a19d17a7c183af7ce5d6919435",
    ),
    ("Cargo.toml", '[package]\nname = "x"\n', "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    (
        "Cargo.toml",
        '[dependencies]\nserde = "1"\n[workspace.lints.clippy]\nall = "warn" # trusted\n',
        "9167516e23adb11a7296b2932fec87fbc3fc4528d34ccd6cc0ff0557e4c92691",
    ),
    (
        "Cargo.toml",
        '[workspace.lints.rust]\nb = "warn"\na = "deny"\n',
        "ab7706d1fd022064e19436a24edb1f19f224483c56f103edf5f14f8f62f8e95a",
    ),
    (
        "Cargo.toml",
        '[workspace.lints.rust]\nx   =    "has # inside"\n',
        "be2f8cba20d651bf11db765ad9c6fbb59d0cb2599180646fc6b7cd7044908a7e",
    ),
    (
        "Cargo.toml",
        "[workspace.lints.rust]\nx = '''\nmulti\nline\n'''\n",
        "67bc446ae1e90e10554f3ba57429925bafc57d0e6bc7f149be0fd857bef6f162",
    ),
    (
        "Cargo.toml",
        '[workspace.lints."a.b"]\nc = 1\n',
        "5bcba38239a8a902b79fe38881dbe1cd354dfeac26d529750621214fc2bb8e0f",
    ),
    (
        "pyproject.toml",
        '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["E"]\n',
        "faa2862f50afe69c2fc6be5a3a1997d5403724c8ecea879cd0d2948c7f1618e2",
    ),
    (
        "pyproject.toml",
        '[project]\nname = "x"\ntool.ruff.line-length = 100\n[tool.hatch]\nx = 1\n',
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    (
        "package.json",
        '{"name":"client","version":"1.0.0","scripts":{"test":"node --test","typecheck":"tsc --noEmit","start":"node ."},"dependencies":{"a":"1"}}',
        "1b9192f45c2d81a95064ae40086e93db7443740426e357339fade1d820e89da0",
    ),
    (
        "package.json",
        '{"name":"client","version":"9.9.9","scripts":{"test":"node --test","typecheck":"tsc --noEmit","start":"node ."},"dependencies":{"b":"2"}}',
        "1b9192f45c2d81a95064ae40086e93db7443740426e357339fade1d820e89da0",
    ),
    (
        "package.json",
        '{"scripts":{"postinstall":"curl x | sh","verify":"echo ok"},"eslintConfig":{"rules":{"semi":"off"}}}',
        "b72fa61d3f070e04ee38fedfae8929065aad6461339ade0bb5090603ebf9b72d",
    ),
    ("package.json", "{not json", "92072df399cb74703f8e86f450d552bc0bb01eeeb98a90985a1b7772c8fd0016"),
    ("deny.toml", "[advisories]\n", "29c3b3fd47a73c667752eba9599a53ab6eb24d3a4eb5e8c5786d7519cd8bd1ad"),
]


class FingerprintParityTests(unittest.TestCase):
    def test_every_vector_matches_the_typescript_fingerprint(self):
        for path, content, expected in TYPESCRIPT_VECTORS:
            with self.subTest(path=path, content=content[:40]):
                self.assertEqual(pf.fingerprint_file(path, content), expected)

    def test_a_dotted_lint_key_is_part_of_the_fingerprint(self):
        forbid = pf.fingerprint_file("Cargo.toml", '[workspace]\nlints.rust.unsafe_code = "forbid"\n')
        allow = pf.fingerprint_file("Cargo.toml", '[workspace]\nlints.rust.unsafe_code = "allow"\n')
        self.assertNotEqual(forbid, allow)

    def test_a_dotted_key_and_a_section_are_the_same_setting(self):
        dotted = pf.fingerprint_file("Cargo.toml", '[workspace]\nlints.rust.unsafe_code = "forbid"\n')
        section = pf.fingerprint_file("Cargo.toml", '[workspace.lints.rust]\nunsafe_code = "forbid"\n')
        self.assertEqual(dotted, section)

    def test_every_package_script_is_protected(self):
        base = pf.fingerprint_file("package.json", '{"scripts": {"test": "node --test"}}')
        self.assertNotEqual(
            base, pf.fingerprint_file("package.json", '{"scripts": {"test": "node --test", "verify": "echo ok"}}')
        )
        self.assertNotEqual(
            base, pf.fingerprint_file("package.json", '{"scripts": {"test": "node --test", "postinstall": "x"}}')
        )
        self.assertEqual(
            base,
            pf.fingerprint_file(
                "package.json", '{"version": "2", "scripts": {"test": "node --test"}, "dependencies": {"a": "1"}}'
            ),
        )


if __name__ == "__main__":
    unittest.main()
