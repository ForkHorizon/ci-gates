import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class LinterCheckerRulesTestsPart2(unittest.TestCase):
    def setUp(self):
        self.config = {
            "max_file_lines": 300,
            "max_function_lines": 50,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }

    def test_go_function_signature_with_multiple_return_values(self):
        go_code = """
func Compute(a, b, c int, d string, e float64, f bool) (res1 int, res2 string, err error) {
    return
}
"""
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            6,
            "Should count 6 input parameters and ignore return parameter list",
        )

    def test_comments_interspersed_with_blank_lines(self):
        code = """
# Line 1
# Line 2
# Line 3

# Line 4
# Line 5
# Line 6
"""
        issues = linter_checker.check_comment_blocks("test.py", code, "python", 5)
        self.assertEqual(
            len(issues),
            1,
            "Blank lines must not let adjacent comment blocks evade the limit",
        )

    def test_switch_case_sibling_nesting_depth(self):
        swift_code = """
func check(val: Int) {
    switch val {
    case 1: print(1)
    case 2: print(2)
    case 3: print(3)
    case 4: print(4)
    case 5: print(5)
    default: break
    }
}
"""
        issues = linter_checker.check_nesting_depth("check.swift", swift_code, "swift", 4)
        self.assertEqual(len(issues), 0, "Sibling cases should not accumulate nesting depth")

    def test_rust_impl_blocks_and_trait_definitions(self):
        rust_code = """
struct MyStruct;
trait MyTrait {}
impl MyTrait for MyStruct {}
"""
        issues = linter_checker.check_types_per_file("lib.rs", rust_code, "rust", 2)
        self.assertEqual(
            len(issues),
            0,
            "Should count struct and trait (2) and not count impl as type definition",
        )

    def test_csharp_attributes_and_generic_return_types(self):
        cs_code = """
[HttpGet]
[ProducesResponseType(typeof(List<Item>), 200)]
public async Task<List<Item>> GetItems(int a, int b, int c, int d, int e, int f) {
    return null;
}
"""
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            6,
            "Attributes and generic return types should not disrupt parameter counting",
        )

    def test_single_line_expression_functions(self):
        kt_code = """fun add(a: Int, b: Int) = a + b"""
        lengths = linter_checker.brace_function_lengths(kt_code, "kotlin")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][2], 1, "Single line function should be reported as length 1")

    def test_closures_and_lambdas_inside_functions(self):
        swift_code = """
func calculate() {
    let items = [1, 2, 3]
    items.map { x in x * 2 }
    items.filter { y in y > 1 }
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(
            lengths,
            [
                ("<anonymous>", 4, 1, 1),
                ("<anonymous>", 5, 1, 1),
                ("calculate", 2, 5, 0),
            ],
        )

    def test_python_match_case_nesting(self):
        code = """
def parse(data):
    match data:
        case {"type": "A"}:
            if True:
                for x in range(5):
                    if x > 2:
                        while x < 4:
                            print(x)
"""
        issues = linter_checker.check_nesting_depth("parse.py", code, "python", 4)
        self.assertGreater(len(issues), 0, "Python match/case blocks should count toward nesting depth")

    def test_multiline_raw_string_literals(self):
        code = """
def test_fn():
    sql = \"\"\"
    class FakeClass:
        def fake_method():
            pass
    # comment 1
    # comment 2
    # comment 3
    # comment 4
    # comment 5
    # comment 6
    \"\"\"
"""
        issues = linter_checker.check_types_per_file("test.py", code, "python", 2)
        self.assertEqual(
            len(issues),
            0,
            "Class inside string literal should not be counted as top-level type",
        )

    def test_language_overrides_config(self):
        config = {
            "max_file_lines": 300,
            "max_function_lines": 50,
            "language_overrides": {"swift": {"max_function_lines": 10}},
        }
        swift_limits = linter_checker.limits_for_language(config, "swift")
        py_limits = linter_checker.limits_for_language(config, "python")
        self.assertEqual(swift_limits["max_function_lines"], 10)
        self.assertEqual(py_limits["max_function_lines"], 50)

    def test_glob_pattern_ignore_matcher(self):
        ignore_patterns = ["DerivedData", "*.gen.swift", "**/vendor/*"]
        self.assertTrue(linter_checker.should_ignore("App/DerivedData/Build/Cache.swift", ignore_patterns))
        self.assertTrue(linter_checker.should_ignore("App/Sources/Model.gen.swift", ignore_patterns))
        self.assertFalse(linter_checker.should_ignore("App/Sources/Model.swift", ignore_patterns))

    # fmt: off
    def _csharp_functions(self, source):
        return linter_checker.brace_function_lengths(source, "csharp")

    def test_csharp_destructor_over_limit_is_named_and_counted(self):
        self.assertEqual(self._csharp_functions("class C {\n    ~C() {\n        x();\n        y();\n        z();\n    }\n}\n"), [("~C", 2, 5, 0)])

    def test_csharp_destructor_at_limit_is_still_measured(self):
        self.assertEqual(self._csharp_functions("class C {\n    ~C() {\n        x();\n    }\n}\n"), [("~C", 2, 3, 0)])

    def test_csharp_destructor_multiline_parentheses_and_whitespace(self):
        self.assertEqual(self._csharp_functions("class C {\n    ~C (\n    )\n    {\n        x();\n    }\n}\n"), [("~C", 2, 5, 0)])

    def test_csharp_destructor_nested_braces_counts_outer_body(self):
        self.assertEqual(self._csharp_functions("class C {\n    ~C() {\n        if (ready) {\n            x();\n        }\n        y();\n    }\n}\n"), [("~C", 2, 6, 0)])

    def test_csharp_destructor_ignores_comment_and_string_fake_declarations(self):
        source = 'class C {\n    // ~Fake() { fake(); }\n    string text = "~AlsoFake() { nope(); }";\n    ~C() {\n        x();\n    }\n}\n'
        self.assertEqual(self._csharp_functions(source), [("~C", 4, 3, 0)])

    def test_csharp_multiple_classes_and_destructors_are_all_tracked(self):
        source = "class First {\n    ~First() {\n        first();\n    }\n}\nclass Second {\n    ~Second() {\n        second();\n        more();\n    }\n}\n"
        self.assertEqual(self._csharp_functions(source), [("~First", 2, 3, 0), ("~Second", 7, 4, 0)])

    def test_csharp_constructor_and_destructor_keep_distinct_names(self):
        source = "class C {\n    C() {\n        construct();\n    }\n    ~C() {\n        dispose();\n    }\n}\n"
        functions = self._csharp_functions(source)
        self.assertEqual([item[0] for item in functions], ["C", "~C"])
        self.assertEqual([item[1] for item in functions], [2, 5])

    def test_csharp_method_and_destructor_coexist(self):
        source = "class C {\n    public void Run() {\n        work();\n    }\n    ~C() {\n        cleanup();\n        more();\n    }\n}\n"
        self.assertEqual(self._csharp_functions(source), [("Run", 2, 3, 0), ("~C", 5, 4, 0)])

    def test_csharp_attribute_context_does_not_hide_destructor(self):
        self.assertEqual(self._csharp_functions("class C {\n    [Obsolete]\n    ~C() {\n        x();\n        y();\n    }\n}\n"), [("~C", 3, 4, 0)])

    def test_csharp_destructor_public_reporting_enforces_configured_limit(self):
        source = "class C {\n    ~C() {\n        x();\n        y();\n        z();\n    }\n}\n"
        config = {
            "max_file_lines": 100,
            "max_function_lines": 3,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Destructor.cs"
            path.write_text(source, encoding="utf-8")
            issues = linter_checker.check_paths(path.parent, [path], config)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("function_length", 2)])
        self.assertIn("C has 5 lines", issues[0].message)

    def test_csharp_call_like_text_and_lambda_are_not_destructors(self):
        source = "class C {\n    void Run() {\n        Log(~Name());\n        var callback = () => {\n            work();\n        };\n    }\n}\n"
        names = [item[0] for item in self._csharp_functions(source)]
        self.assertIn("Run", names)
        self.assertNotIn("~Name", names)

    def test_csharp_destructor_body_lines_and_name_are_stable_with_nested_class(self):
        source = "class Outer {\n    class Inner {\n        ~Inner() {\n            release();\n            if (pending) {\n                retry();\n            }\n        }\n    }\n}\n"
        self.assertEqual(self._csharp_functions(source), [("~Inner", 3, 6, 0)])

    # fmt: on

    def test_full_file_all_six_rules_stress_test(self):
        python_code = """
# Comment 1
# Comment 2
# Comment 3
# Comment 4
# Comment 5
# Comment 6

class Type1:
    pass

class Type2:
    pass

class Type3:
    def overloaded_method(p1, p2, p3, p4, p5, p6):
        if True:
            for i in range(1):
                if i == 0:
                    while i < 1:
                        if i == 0:
                            print(i)
"""
        config = {
            "max_file_lines": 10,
            "max_function_lines": 5,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            mock_root = Path(directory)
            source = mock_root / "StressTest.py"
            source.write_text(python_code, encoding="utf-8")
            issues = linter_checker.check_paths(mock_root, [source], config)

        issue_kinds = {issue.kind for issue in issues}
        self.assertIn("file_length", issue_kinds)
        self.assertIn("function_length", issue_kinds)
        self.assertIn("max_parameters", issue_kinds)
        self.assertIn("nesting_depth", issue_kinds)
        self.assertIn("comment_block", issue_kinds)
        self.assertIn("types_per_file", issue_kinds)


if __name__ == "__main__":
    unittest.main()
