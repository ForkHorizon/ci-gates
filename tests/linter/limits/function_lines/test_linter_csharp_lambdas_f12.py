import importlib.util
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


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 2,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class CSharpLambdaRegressionTests(unittest.TestCase):
    def issues(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Sample.cs"
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], LIMITS)

    def function_results(self, source):
        return linter_checker.brace_function_lengths(source, "csharp")

    def test_return_parenthesized_lambda_is_detected(self):
        source = "return (a, b, c) => a + b + c;\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_return_bare_lambda_is_detected(self):
        source = "return item => item.Value;\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 1)])
        self.assertEqual(self.issues(source), [])

    def test_return_explicitly_typed_lambda_is_detected(self):
        source = "return (int a, string b, bool c) => a.ToString() + b + c;\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_conditional_lambda_expression_is_detected(self):
        source = "return ready ? (a, b, c) => a + b + c : fallback;\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_method_argument_lambda_is_detected(self):
        source = "return source.Select((a, b, c) => a + b + c);\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_contextual_delegate_assignment_is_detected(self):
        source = "Func<int, int, int, int> transform = (a, b, c) => a + b + c;\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_async_contextual_lambda_is_detected(self):
        source = "return async (a, b, c) => await CombineAsync(a, b, c);\n"
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_multiline_parameter_list_is_counted_from_header_line(self):
        source = """Func<int, int, int, int> transform = (
    int first,
    string second,
    bool third
) => first + second.Length + (third ? 1 : 0);
"""
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_lambda_body_brace_on_next_line_is_a_block(self):
        source = """Func<int, int, int, int> transform = (a, b, c) =>
{
    Use(a);
    Use(b);
    Use(c);
};
"""
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 6, 3)])
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 1), ("max_parameters", 1)],
        )

    def test_multiline_method_argument_lambda_with_next_line_brace_is_checked(self):
        source = """return source.Select(
    (a, b, c) =>
    {
        Use(a);
        Use(b);
        Use(c);
    });
"""
        self.assertEqual(self.function_results(source), [("<anonymous>", 2, 6, 3)])
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 2), ("max_parameters", 2)],
        )

    def test_lambda_parameter_list_can_start_before_contextual_return(self):
        source = """return (
    int first,
    int second,
    int third
) => first + second + third;
"""
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_nested_contextual_lambdas_keep_start_lines_and_limits(self):
        source = """Func<int, Func<int, int, int>, int> outer = (a, b, c) =>
{
    return (x, y, z) =>
    {
        Use(x);
        Use(y);
        Use(z);
    };
};
"""
        self.assertEqual(
            self.function_results(source),
            [("<anonymous>", 3, 6, 3), ("<anonymous>", 1, 9, 3)],
        )
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [
                ("function_length", 3),
                ("max_parameters", 3),
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_generic_type_heavy_lambda_counts_top_level_parameters(self):
        source = (
            "return (Dictionary<string, List<int>> first, "
            "Func<int, string> second, CancellationToken token) => first.Count;\n"
        )
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 3)])
        self.assertEqual([(issue.kind, issue.line) for issue in self.issues(source)], [("max_parameters", 1)])

    def test_lambda_body_control_flow_still_enforces_nesting(self):
        source = """return (a, b) =>
{
    if (a)
    {
        if (b)
        {
            if (a && b)
            {
                return 1;
            }
        }
    }
};
"""
        nesting = [issue for issue in self.issues(source) if issue.kind == "nesting_depth"]
        self.assertEqual(
            [(issue.kind, issue.line) for issue in nesting],
            [("nesting_depth", 8), ("nesting_depth", 7)],
        )

    def test_comments_and_strings_containing_arrow_are_ignored(self):
        source = """string text = "return (a, b, c) => a + b + c"; // (x, y, z) => fake
if (left >= right)
{
    Use(text);
}
"""
        self.assertEqual(self.function_results(source), [])
        self.assertEqual(self.issues(source), [])

    def test_comparison_operators_are_not_lambdas(self):
        source = """if (left >= right && right <= limit)
{
    return left == right;
}
"""
        self.assertEqual(self.function_results(source), [])
        self.assertEqual(self.issues(source), [])

    def test_incomplete_single_line_lambda_does_not_create_phantom_function(self):
        source = "return (a, b, c) =>\n"
        self.assertEqual(self.function_results(source), [])
        self.assertEqual(self.issues(source), [])

    def test_incomplete_multiline_lambda_does_not_create_phantom_function(self):
        source = """var transform = (
    int first,
    int second,
    int third
) =>
"""
        self.assertEqual(self.function_results(source), [])
        self.assertEqual(self.issues(source), [])

    def test_multiline_expression_lambda_has_deterministic_one_line_length(self):
        source = """var transform = first
    => first.Value;
"""
        self.assertEqual(self.function_results(source), [("<anonymous>", 1, 1, 1)])
        self.assertEqual(self.issues(source), [])

    def test_public_linter_reports_contextual_lambda_violations(self):
        source = """return (a, b, c) =>
{
    Use(a);
    Use(b);
    Use(c);
};
"""
        issues = self.issues(source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [("function_length", 1), ("max_parameters", 1)],
        )


if __name__ == "__main__":
    unittest.main()
