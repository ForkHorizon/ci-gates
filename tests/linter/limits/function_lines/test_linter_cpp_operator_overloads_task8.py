import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("cpp_operator_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["cpp_operator_linter"] = linter
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


class CppOperatorOverloadRegressionTests(unittest.TestCase):
    def functions(self, source):
        return linter.brace_function_lengths(source, "cpp")

    def issues(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Sample.cpp"
            path.write_text(source, encoding="utf-8")
            return linter.check_paths(root, [path], LIMITS)

    def test_member_arithmetic_operator_is_detected(self):
        source = """struct Number {
    Number operator+(const Number& other) const {
        Work(other);
        return *this;
    }
};
"""
        self.assertEqual(self.functions(source), [("operator+", 2, 4, 1)])

    def test_free_comparison_operator_is_detected(self):
        source = """bool operator==(const Number& left, const Number& right) {
    return left.value == right.value;
}
"""
        self.assertEqual(self.functions(source), [("operator==", 1, 3, 2)])

    def test_shift_operator_is_detected(self):
        source = """std::ostream& operator<<(std::ostream& out, const Number& value) {
    return out;
}
"""
        self.assertEqual(self.functions(source), [("operator<<", 1, 3, 2)])

    def test_subscript_operator_is_detected_and_parameter_checked(self):
        source = """struct Table {
    int& operator[](int row, int column) const {
        return cells[row][column];
    }
};
"""
        self.assertEqual(self.functions(source), [("operator[]", 2, 3, 2)])
        self.assertEqual(self.issues(source), [])

    def test_call_operator_uses_the_real_parameter_list(self):
        source = """struct Callable {
    int operator()(int first, int second, int third) const {
        return first + second + third;
    }
};
"""
        self.assertEqual(self.functions(source), [("operator()", 2, 3, 3)])
        self.assertEqual([issue.kind for issue in self.issues(source)], ["max_parameters"])

    def test_conversion_operator_without_return_type_is_detected(self):
        source = """struct Number {
    explicit operator bool() const {
        return value != 0;
    }
};
"""
        self.assertEqual(self.functions(source), [("operator bool", 2, 3, 0)])
        self.assertEqual(self.issues(source), [])

    def test_qualified_operator_definition_is_detected(self):
        source = """Number math::Number::operator-(const Number& other) const {
    Work(other);
    return *this;
}
"""
        self.assertEqual(self.functions(source), [("operator-", 1, 4, 1)])

    def test_const_ref_and_noexcept_qualifiers_do_not_change_detection(self):
        source = """Number Number::operator*(const Number& other) const & noexcept {
    Work(other);
    return *this;
}
"""
        self.assertEqual(self.functions(source), [("operator*", 1, 4, 1)])

    def test_multiline_operator_parameters_are_counted_from_declaration(self):
        source = """struct Number {
    Number operator+(
        const Number& left,
        const Number& right
    ) const
    {
        return left;
    }
};
"""
        self.assertEqual(self.functions(source), [("operator+", 2, 7, 2)])
        self.assertEqual([issue.kind for issue in self.issues(source)], ["function_length"])

    def test_body_brace_on_next_line_is_measured(self):
        source = """struct Number {
    Number operator-(const Number& other) const
    {
        return other;
    }
};
"""
        self.assertEqual(self.functions(source), [("operator-", 2, 4, 1)])

    def test_inline_expression_body_is_one_line(self):
        source = """struct Number {
    int operator()(int value) const { return value; }
};
"""
        self.assertEqual(self.functions(source), [("operator()", 2, 1, 1)])
        self.assertEqual(self.issues(source), [])

    def test_nested_classes_keep_operator_methods_distinct(self):
        source = """struct Outer {
    struct Inner {
        Inner operator+(const Inner& other) const {
            return other;
        }
    };
    Outer operator+(const Outer& other) const {
        return other;
    }
};
"""
        self.assertEqual(
            self.functions(source),
            [("operator+", 3, 3, 1), ("operator+", 7, 3, 1)],
        )

    def test_comments_and_strings_containing_operator_text_are_ignored(self):
        source = """// Number operator+(int a, int b) { fake(); }
const char* text = "operator[](int row, int column) { fake(); }";
Number operator+(const Number& other) const {
    return other;
}
"""
        self.assertEqual(self.functions(source), [("operator+", 3, 3, 1)])

    def test_malformed_operator_signature_does_not_create_phantom_function(self):
        source = """struct Number {
    Number operator+(const Number& other {
        return other;
    }
};
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_call_like_operator_block_is_not_a_declaration(self):
        source = """value.operator+(first, second, third) {
    Fake();
    Fake();
    Fake();
}
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_operator_new_and_delete_array_names_are_detected(self):
        source = """void* operator new[](unsigned long size) {
    return Allocate(size);
}
void operator delete[](void* pointer) noexcept {
    Release(pointer);
}
"""
        self.assertEqual(
            self.functions(source),
            [("operator new[]", 1, 3, 1), ("operator delete[]", 4, 3, 1)],
        )

    def test_operator_body_still_enforces_nesting(self):
        source = """Number Number::operator+(const Number& other) const {
    if (first) {
        if (second) {
            if (third) {
                Work();
            }
        }
    }
    return other;
}
"""
        self.assertEqual(self.functions(source), [("operator+", 1, 10, 1)])
        self.assertTrue(any(issue.kind == "nesting_depth" for issue in self.issues(source)))

    def test_line_accounting_ignores_fake_braces_in_operator_literals(self):
        source = """Number Number::operator+(const Number& other) const {
    const char* fake = "{ operator()(a, b, c) { } }";

    // operator[](a, b, c) { }
    return other;
}
"""
        self.assertEqual(self.functions(source), [("operator+", 1, 6, 1)])

    def test_ordinary_methods_constructors_destructors_and_control_blocks_remain(self):
        source = """struct Number {
    Number(int value) {
        Work(value);
    }
    ~Number() {
        Cleanup();
    }
    int value() const {
        return value_;
    }
    void run() {
        if (value_) {
            Work();
        }
    }
};
"""
        names = [item[0] for item in self.functions(source)]
        self.assertEqual(names, ["Number", "~Number", "value", "run"])

    def test_free_operator_limits_report_length_and_parameters(self):
        source = """Number operator+(const Number& first, const Number& second, const Number& third) {
    Work(first);
    Work(second);
    Work(third);
}
"""
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 1), ("max_parameters", 1)],
        )

    def test_public_cli_reports_operator_violations(self):
        source = """struct Number {
    int operator()(int first, int second, int third) const {
        Work(first);
        Work(second);
        Work(third);
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
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("function_length", result.stdout)
        self.assertIn("max_parameters", result.stdout)


if __name__ == "__main__":
    unittest.main()
