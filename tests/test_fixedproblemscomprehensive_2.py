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


class FixedProblemsComprehensiveTestSuitePart2(unittest.TestCase):
    def test_problem8_3_csharp_where_class_constraint(self):
        cs_code = "public class Service {\n    public void Save<T>() where T : class {}\n}"
        issues = linter_checker.check_types_per_file("Service.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    def test_problem8_4_csharp_where_struct_constraint(self):
        cs_code = "public class Data {\n    public void Load<T>() where T : struct {}\n}"
        issues = linter_checker.check_types_per_file("Data.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    def test_problem8_5_csharp_where_new_constraint(self):
        cs_code = "public class Factory {\n    public void Create<T>() where T : new() {}\n}"
        issues = linter_checker.check_types_per_file("Factory.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    def test_problem9_1_go_multiline_receiver_basic(self):
        go_code = "func (\n    s *Server\n) Process(a int) {\n    return\n}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Process")

    def test_problem9_2_go_pointer_receiver(self):
        go_code = "func (r *Runner) Run() {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Run")

    def test_problem9_3_go_value_receiver(self):
        go_code = "func (c Client) Connect() {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Connect")

    def test_problem9_4_go_multiline_signature(self):
        go_code = "func (s *Server) Handle(\n    req *Request,\n) {\n    return\n}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Handle")

    def test_problem9_5_go_function_without_receiver(self):
        go_code = "func Standalone(x int) {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Standalone")

    def test_problem10_1_github_path_standard_file(self):
        rel = linter_checker.github_path(Path("src/main.py"))
        self.assertTrue(isinstance(rel, str) and len(rel) > 0)

    def test_problem10_2_github_path_nested_file(self):
        rel = linter_checker.github_path(Path("a/b/c/d.swift"))
        self.assertTrue(isinstance(rel, str) and len(rel) > 0)

    def test_problem10_3_escape_github_message_newlines(self):
        esc = linter_checker.escape_github_message("a\nb")
        self.assertEqual(esc, "a%0Ab")

    def test_problem10_4_escape_github_message_percent(self):
        esc = linter_checker.escape_github_message("100%")
        self.assertEqual(esc, "100%25")

    def test_problem10_5_escape_github_message_carriage(self):
        esc = linter_checker.escape_github_message("a\rb")
        self.assertEqual(esc, "a%0Db")


if __name__ == "__main__":
    unittest.main()
