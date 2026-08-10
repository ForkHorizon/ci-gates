import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("cpp_destructor_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["cpp_destructor_linter"] = linter
spec.loader.exec_module(linter)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 2,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class CppDestructorRegressionTests(unittest.TestCase):
    def functions(self, source):
        return linter.brace_function_lengths(source, "cpp")

    def issues(self, source, limits=LIMITS):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Sample.cpp"
            path.write_text(source, encoding="utf-8")
            return linter.check_paths(root, [path], limits)

    def test_inline_member_destructor_is_detected(self):
        source = """struct Widget {
    ~Widget() { Cleanup(); }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 1, 0)])

    def test_qualified_out_of_line_destructor_is_detected(self):
        source = """struct Widget { ~Widget(); };
Widget::~Widget() { Cleanup(); }
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 1, 0)])

    def test_namespaced_qualified_destructor_is_detected(self):
        source = """namespace Namespace { struct Widget { ~Widget(); }; }
Namespace::Widget::~Widget() noexcept { Cleanup(); }
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 1, 0)])

    def test_noexcept_and_override_destructor_qualifiers_are_detected(self):
        source = """struct Base { virtual ~Base() noexcept {} };
struct Widget : Base {
    ~Widget() noexcept override { Cleanup(); }
};
"""
        self.assertEqual(
            self.functions(source),
            [("~Base", 1, 1, 0), ("~Widget", 3, 1, 0)],
        )

    def test_multiline_destructor_signature_counts_zero_parameters(self):
        source = """struct Widget {
    ~Widget(
    ) noexcept
    {
        Cleanup();
    }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 5, 0)])

    def test_body_brace_on_next_line_is_measured(self):
        source = """struct Widget {
    ~Widget() noexcept
    {
        Cleanup();
        Cleanup();
    }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 5, 0)])
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 2)],
        )

    def test_nested_class_destructors_are_tracked_independently(self):
        source = """struct Outer {
    struct Inner {
        ~Inner() { Cleanup(); }
    };
    ~Outer() { Cleanup(); }
};
"""
        self.assertEqual(
            self.functions(source),
            [("~Inner", 3, 1, 0), ("~Outer", 5, 1, 0)],
        )

    def test_comments_and_strings_containing_destructor_syntax_are_ignored(self):
        source = """// ~Fake() { fake(); }
const char* text = "Namespace::Widget::~Fake() { fake(); }";
struct Widget {
    ~Widget() { Cleanup(); }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 4, 1, 0)])

    def test_destructor_call_expression_is_not_a_definition(self):
        source = """void release(Widget* widget) {
    widget->~Widget();
    widget.~Widget();
}
"""
        self.assertEqual(self.functions(source), [("release", 1, 4, 1)])

    def test_malformed_destructor_signature_does_not_create_phantom_function(self):
        source = """struct Widget {
    ~Widget( {
        Cleanup();
    }
};
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_incomplete_out_of_line_destructor_is_not_reported_as_a_body(self):
        source = """struct Widget { ~Widget(); };
Widget::~Widget(
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_destructor_line_accounting_is_deterministic_with_literal_braces(self):
        source = """struct Widget {
    ~Widget() {
        const char* fake = "{ }";
        // } ~Fake() {
        Cleanup();
    }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 5, 0)])

    def test_destructor_function_length_limit_is_enforced(self):
        source = """struct Widget {
    ~Widget() {
        Cleanup();
        Cleanup();
        Cleanup();
    }
};
"""
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 2)],
        )

    def test_destructor_parameter_limit_path_reports_zero_parameters(self):
        source = """struct Widget {
    ~Widget() { Cleanup(); }
};
"""
        limits = {**LIMITS, "max_parameters": -1}
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source, limits)],
            [("max_parameters", 2)],
        )

    def test_destructor_nesting_limit_is_enforced(self):
        source = """struct Widget {
    ~Widget() {
        if (first) {
            if (second) {
                if (third) {
                    Cleanup();
                }
            }
        }
    }
};
"""
        self.assertEqual(self.functions(source), [("~Widget", 2, 9, 0)])
        self.assertTrue(any(issue.kind == "nesting_depth" for issue in self.issues(source)))

    def test_constructors_methods_and_operator_overloads_remain_distinct(self):
        source = """struct Widget {
    Widget(int value) { Store(value); }
    ~Widget() { Cleanup(); }
    int value() const { return value_; }
    Widget operator+(const Widget& other) const { return other; }
};
"""
        self.assertEqual(
            [item[0] for item in self.functions(source)],
            ["Widget", "~Widget", "value", "operator+"],
        )

    def test_public_cli_reports_destructor_violations(self):
        source = """struct Widget {
    ~Widget() {
        Cleanup();
        Cleanup();
        Cleanup();
    }
};
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.cpp").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, '
                '"max_parameters": 2, "max_nesting_depth": 2, '
                '"max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "code-linter.py"),
                    "--root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("function_length", result.stdout)


if __name__ == "__main__":
    unittest.main()
