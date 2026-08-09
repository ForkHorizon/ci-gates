import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


class SwiftMultilineClosureCompilerTests(unittest.TestCase):
    def assert_parses_as_swift(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.swift"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["swiftc", "-parse", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_valid_multiline_reproducers_parse_with_swiftc(self):
        sources = [
            """let closure = {
    (a: Int, b: Int, c: Int)
    in
    a + b + c
}
""",
            """let closure = { [weak owner]
    (a: Int, b: Int, c: Int)
    in
    owner?.use(a)
}
""",
            """let result = values.map(
    {
        (a: Int, b: Int, c: Int)
        in
        a + b + c
    }
)
""",
            """let outer = {
    (a: Int, b: Int, c: Int)
    in
    values.map(
        {
            (x: Int, y: Int, z: Int)
            in
            x + y + z
        }
    )
}
""",
            """let closure = {
    (values: [Result<[String: Set<Int>], Error>],
     fallback: (Int, String) -> Bool,
     result: Swift.Result<Int, Error>)
    in
    values.isEmpty && fallback(1, "value") && result != nil
}
""",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assert_parses_as_swift(source)


if __name__ == "__main__":
    unittest.main()
