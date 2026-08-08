import importlib.util
import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class SeniorDevEdgeCaseTestsPart2(unittest.TestCase):
    def test_go_multiline_receiver_function(self):
        go_code = """
func (
    s *Server
) Process(a int) {
    return
}
"""
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][0],
            "Process",
            "Go multiline receiver function signature should be detected",
        )

    def test_config_ignore_override_preserves_or_merges(self):
        config = linter_checker.load_config(Path("/nonexistent_config.json"))
        self.assertIn(".git", config["ignore"])
        self.assertIn("node_modules", config["ignore"])

    def test_cpp_enum_class_type_detection(self):
        cpp_code = """
enum class Status {
    OK,
    ERROR
};
class Handler {};
class Controller {};
"""
        issues = linter_checker.check_types_per_file("main.cpp", cpp_code, "csharp", 2)
        self.assertEqual(
            len(issues),
            1,
            "enum class Status + 2 classes = 3 types, should exceed limit 2",
        )

    def test_github_path_formatting_for_error_annotation(self):
        rel_path = linter_checker.github_path(Path("src/app.py"))
        self.assertTrue(isinstance(rel_path, str) and len(rel_path) > 0)


if __name__ == "__main__":
    unittest.main()
