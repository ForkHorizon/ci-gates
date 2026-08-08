import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("linter_under_test", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_under_test"] = linter
spec.loader.exec_module(linter)


class SeniorLinterRegressionTests(unittest.TestCase):
    def assert_function(self, source, language, expected_name, expected_parameters):
        functions = linter.brace_function_lengths(source, language)
        self.assertEqual(len(functions), 1)
        self.assertEqual(functions[0][0], expected_name)
        self.assertEqual(functions[0][3], expected_parameters)

    def assert_type_count(self, source, language, expected_count):
        issues = linter.check_types_per_file("fixture", source, language, 0)
        self.assertEqual(len(issues), 1)
        self.assertIn(f"File defines {expected_count} types", issues[0].message)

    def test_01_go_generic_function_is_measured(self):
        self.assert_function("func Map[T any](value T) T {\n return value\n}", "go", "Map", 1)

    def test_02_typescript_generic_function_is_measured(self):
        self.assert_function("function map<T>(value: T): T {\n return value\n}", "typescript", "map", 1)

    def test_03_csharp_generic_method_is_measured(self):
        self.assert_function(
            "public static T Create<T>(value T) {\n return value;\n}",
            "csharp",
            "Create",
            1,
        )

    def test_04_java_generic_method_is_measured(self):
        self.assert_function("public <T> T identity(T value) {\n return value;\n}", "java", "identity", 1)

    def test_05_kotlin_generic_function_is_measured(self):
        self.assert_function("fun <T> identity(value: T): T {\n return value\n}", "kotlin", "identity", 1)

    def test_06_swift_multiline_string_does_not_raise_nesting(self):
        source = 'let message = """\nif fake {\nif fake {\n"""\n'
        self.assertEqual(linter.check_nesting_depth("fixture", source, "swift", 1), [])

    def test_07_javascript_template_literal_does_not_raise_nesting(self):
        source = "const message = `\nif (fake) {\n`;\n"
        self.assertEqual(linter.check_nesting_depth("fixture", source, "javascript", 0), [])

    def test_08_csharp_verbatim_string_does_not_raise_nesting(self):
        source = 'var message = @"\nif (fake) {\n";\n'
        self.assertEqual(linter.check_nesting_depth("fixture", source, "csharp", 0), [])

    def test_09_java_text_block_does_not_raise_nesting(self):
        source = 'String message = """\nif (fake) {\n""";\n'
        self.assertEqual(linter.check_nesting_depth("fixture", source, "java", 0), [])

    def test_10_swift_nested_block_comment_does_not_raise_nesting(self):
        source = "/* outer\n/* inner */\nif fake {\n*/\n"
        self.assertEqual(linter.check_nesting_depth("fixture", source, "swift", 0), [])

    def test_11_template_literal_comments_are_not_comment_blocks(self):
        source = "const message = `\n// prose, not a comment\n// still string data\n`;\n"
        self.assertEqual(linter.check_comment_blocks("fixture", source, "javascript", 1), [])

    def test_12_csharp_record_forms_count_as_types(self):
        self.assert_type_count("record User;\nrecord struct Point;\nrecord class Event;", "csharp", 3)

    def test_13_swift_protocols_count_as_types(self):
        self.assert_type_count("protocol Service {}\nprotocol Repository {}", "swift", 2)

    def test_14_go_named_types_count_as_types(self):
        self.assert_type_count("type Config struct{}\ntype Store interface{}", "go", 2)

    def test_15_typescript_type_aliases_do_not_count_as_types(self):
        # Aliases cost a reader nothing; classes/interfaces/enums still count.
        source = "type UserId = string;\ntype RetryCount = number;"
        self.assertEqual(linter.check_types_per_file("fixture", source, "typescript", 0), [])
        self.assert_type_count("type UserId = string;\ninterface Store {}\nclass Client {}", "typescript", 2)

    def test_16_rust_traits_and_unions_count_as_types(self):
        self.assert_type_count("trait Render {}\nunion Bits { raw: u32 }", "rust", 2)

    def test_17_php_traits_count_as_types(self):
        self.assert_type_count("trait Loggable {}\ntrait Cacheable {}", "php", 2)

    def test_18_trailing_slash_ignore_means_directory(self):
        self.assertTrue(linter.should_ignore("generated/api/client.py", ["generated/"]))

    def test_19_root_directory_ignore_does_not_require_star(self):
        self.assertTrue(linter.should_ignore("artifacts/result.ts", ["artifacts/"]))

    def test_20_go_anonymous_function_is_not_named_func(self):
        functions = linter.brace_function_lengths("callback := func(value int) {\n println(value)\n}", "go")
        self.assertEqual(functions[0][0], "<anonymous>")


if __name__ == "__main__":
    unittest.main()
