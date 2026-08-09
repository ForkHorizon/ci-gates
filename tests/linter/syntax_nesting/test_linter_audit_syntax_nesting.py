import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("audit_fixes_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["audit_fixes_linter"] = linter
spec.loader.exec_module(linter)


class SyntaxAndParserTests(unittest.TestCase):
    def test_invalid_python_is_always_a_syntax_error(self):
        issues = linter.check_syntax("broken.py", "def broken(:\n    pass\n", "python")
        self.assertEqual([issue.kind for issue in issues], ["syntax_error"])

    def test_unclosed_c_style_function_is_a_syntax_error(self):
        issues = linter.check_syntax("broken.cs", "void Broken() {\n    Work();\n", "csharp")
        self.assertEqual([issue.kind for issue in issues], ["syntax_error"])

    def test_multiline_javascript_arrow_is_measured(self):
        source = "const process = (\n    a, b, c, d, e, f\n) => {\n    work();\n}\n"
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("process", 1, 5, 6)],
        )

    def test_csharp_expression_body_parameters_are_measured(self):
        source = "public int Sum(int a, int b, int c, int d, int e, int f) => a + b;"
        self.assertEqual(linter.brace_function_lengths(source, "csharp")[0][3], 6)

    def test_ruby_no_parentheses_and_multiline_parameters_are_measured(self):
        plain = "def process a, b, c, d, e, f\n  nil\nend\n"
        multiline = "def process(\n  a, b, c, d, e, f\n)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(plain)[0][3], 6)
        self.assertEqual(linter.ruby_function_lengths(multiline)[0][3], 6)

    def test_ruby_strings_and_heredocs_do_not_close_a_method(self):
        source = 'def long_method\n  puts "end"\n  text = <<~TEXT\nend\nTEXT\n'
        source += "  work\n" * 50 + "end\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][2], 56)
        self.assertEqual(linter.check_syntax("x.rb", "items << CONSTANT\n", "ruby"), [])

    def test_ruby_lowercase_heredoc_does_not_close_a_method(self):
        source = (
            "def build_query\n"
            "  sql = <<~sql\n"
            "    SELECT * FROM users\n"
            "    -- this query does not end here\n"
            "  sql\n"
            "  query\n"
            "end\n"
        )
        self.assertEqual(
            linter.ruby_function_lengths(source),
            [("build_query", 1, 7, 0)],
        )
        self.assertEqual(linter.check_syntax("x.rb", source, "ruby"), [])

    def test_javascript_regex_brace_does_not_close_a_function(self):
        source = "function longMethod() {\n  const matcher = /}/;\n" + "  work();\n" * 50 + "}\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript")[0][2], 53)

    def test_additional_supported_function_forms_are_measured(self):
        cases = [
            (
                "items.map((value) => {\n  return value;\n});",
                "javascript",
                "<anonymous>",
                1,
            ),
            ("static func ==(a: Item, b: Item) -> Bool { true }", "swift", "==", 2),
            ("subscript(a: Int, b: Int) -> Int { a }", "swift", "subscript", 2),
            ("fun `when`(a: Int, b: Int) { }", "kotlin", "when", 2),
            ("def [](a, b)\n nil\nend\n", "ruby", "[]", 2),
            ("function* run(a, b, c, d, e, f) { return a; }", "javascript", "run", 6),
            (
                "const object = { run(a, b, c, d, e, f) {\n  return a;\n} };",
                "javascript",
                "run",
                6,
            ),
        ]
        for source, language, name, parameters in cases:
            with self.subTest(language=language, name=name):
                functions = linter.function_lengths(source, language)
                self.assertEqual((functions[0][0], functions[0][3]), (name, parameters))

    def test_javascript_generator_and_object_methods_enforce_limits(self):
        sources = [
            "function* run(a, b, c, d, e, f) {\n" + "  work();\n" * 51 + "}\n",
            "const object = { run(a, b, c, d, e, f) {\n" + "  work();\n" * 51 + "} };\n",
        ]
        for source in sources:
            with self.subTest(source=source[:20]):
                self.assertEqual(
                    linter.brace_function_lengths(source, "javascript")[0][2:],
                    (53, 6),
                )

    def test_bodyless_declaration_parameters_are_measured(self):
        source = "public abstract void Run(int a, int b, int c, int d, int e, int f);"
        self.assertEqual(linter.brace_function_lengths(source, "csharp")[0][3], 6)

    def test_php_hash_comments_and_heredocs_are_masked(self):
        source = "<?php\n# if ($fake) {\n$text = <<<TEXT\nif ($fake) {\nTEXT;\nfunction run() {}\n"
        self.assertEqual(linter.check_syntax("x.php", source, "php"), [])
        self.assertEqual(linter.brace_function_lengths(source, "php")[0][0], "run")


class NestingTests(unittest.TestCase):
    def assert_nesting_count(self, source, language, limit, expected):
        issues = linter.check_nesting_depth("depth-fixture", source, language, limit)
        self.assertEqual(len(issues), expected)

    def test_brace_free_csharp_nesting_is_measured(self):
        source = "void Run() {\n if (a)\n  if (b)\n   if (c)\n    Work();\n}\n"
        self.assertEqual(len(linter.check_nesting_depth("x.cs", source, "csharp", 2)), 1)

    def test_ruby_end_nesting_is_measured(self):
        source = "def run\n if a\n  while b\n   if c\n    work\n   end\n  end\n end\nend\n"
        self.assertEqual(len(linter.check_nesting_depth("x.rb", source, "ruby", 2)), 1)

    def test_php_alternative_nesting_is_measured(self):
        source = "if ($a):\n if ($b):\n  work();\n endif;\nendif;\n"
        self.assertEqual(len(linter.check_nesting_depth("x.php", source, "php", 1)), 1)

    def test_labeled_loop_is_measured(self):
        source = "outer: for (let i = 0; i < 1; i++) {\n  work();\n}\n"
        self.assertEqual(len(linter.check_nesting_depth("x.js", source, "javascript", 0)), 1)

    def test_same_line_brace_free_csharp_nesting_is_measured(self):
        source = "void Run() {\n if (a) if (b) Work();\n}\n"
        self.assertEqual(len(linter.check_nesting_depth("x.cs", source, "csharp", 1)), 1)

    def test_braced_and_brace_free_csharp_depth_is_combined(self):
        source = "void Run() {\n if (a) {\n  if (b)\n   if (c)\n    Work();\n }\n}\n"
        self.assertEqual(len(linter.check_nesting_depth("x.cs", source, "csharp", 2)), 1)

    def test_php_alternative_and_braced_depth_is_combined(self):
        source = "if ($a) {\n if ($b):\n  work();\n endif;\n}\n"
        self.assertEqual(len(linter.check_nesting_depth("x.php", source, "php", 1)), 1)

    def test_php_braced_and_alternative_depth_is_combined(self):
        source = "if ($a):\n if ($b) {\n  work();\n }\nendif;\n"
        self.assertEqual(len(linter.check_nesting_depth("x.php", source, "php", 1)), 1)

    def test_braced_depth_one_at_limit_passes(self):
        source = "if (a) {\n work();\n}\n"
        self.assert_nesting_count(source, "csharp", 1, 0)

    def test_braced_depth_three_over_limit_fails(self):
        source = "if (a) {\n if (b) {\n  if (c) {\n   work();\n  }\n }\n}\n"
        self.assert_nesting_count(source, "csharp", 2, 1)

    def test_braced_depth_four_at_limit_passes(self):
        source = "if (a) {\n if (b) {\n  if (c) {\n   if (d) {\n    work();\n   }\n  }\n }\n}\n"
        self.assert_nesting_count(source, "javascript", 4, 0)

    def test_unbraced_depth_two_over_limit_fails(self):
        source = "if (a)\n if (b)\n  Work();\n"
        self.assert_nesting_count(source, "java", 1, 1)

    def test_unbraced_depth_four_over_limit_fails(self):
        source = "if (a)\n if (b)\n  if (c)\n   if (d)\n    Work();\n"
        self.assert_nesting_count(source, "csharp", 3, 1)

    def test_one_braced_plus_two_unbraced_depth_three_fails(self):
        source = "if (a) {\n if (b)\n  if (c)\n   Work();\n}\n"
        self.assert_nesting_count(source, "csharp", 2, 1)

    def test_two_braced_plus_two_unbraced_depth_four_fails(self):
        source = "if (a) {\n if (b) {\n  if (c)\n   if (d)\n    Work();\n }\n}\n"
        self.assert_nesting_count(source, "csharp", 3, 1)

    def test_three_inline_unbraced_conditions_over_limit_fail(self):
        source = "if (a) if (b) if (c) Work();\n"
        self.assert_nesting_count(source, "typescript", 2, 1)

    def test_java_braced_outer_with_unbraced_inner_fails(self):
        source = "if (a) {\n if (b)\n  if (c)\n   work();\n}\n"
        self.assert_nesting_count(source, "java", 2, 1)

    def test_java_two_inline_unbraced_conditions_over_limit_fail(self):
        source = "if (a) if (b) work();\n"
        self.assert_nesting_count(source, "java", 1, 1)

    def test_labeled_braced_loop_with_unbraced_if_combines_depth(self):
        source = "outer: for (let i = 0; i < n; i++) {\n if (ready) work();\n}\n"
        self.assert_nesting_count(source, "javascript", 1, 1)

    def test_typescript_two_braced_plus_unbraced_depth_three_fails(self):
        source = "if (a) {\n for (const item of items) {\n  if (item.ready)\n   work(item);\n }\n}\n"
        self.assert_nesting_count(source, "typescript", 2, 1)

    def test_kotlin_when_brace_plus_unbraced_if_combines_depth(self):
        source = "when (value) {\n 1 -> {\n  if (ready)\n   work()\n }\n}\n"
        self.assert_nesting_count(source, "kotlin", 1, 1)

    def test_php_alternative_depth_three_over_limit_fails(self):
        source = "if ($a):\n foreach ($items as $item):\n  while ($item):\n   work();\n  endwhile;\n endforeach;\nendif;\n"
        self.assert_nesting_count(source, "php", 2, 1)

    def test_php_alternative_outer_with_braced_inner_combines_depth(self):
        source = "if ($a):\n if ($b) {\n  work();\n }\nendif;\n"
        self.assert_nesting_count(source, "php", 1, 1)


if __name__ == "__main__":
    unittest.main()
