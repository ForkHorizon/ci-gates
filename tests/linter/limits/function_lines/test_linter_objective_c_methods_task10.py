import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("objective_c_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["objective_c_linter"] = linter
spec.loader.exec_module(linter)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 1,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class ObjectiveCMethodDetectionTests(unittest.TestCase):
    def lengths(self, source):
        return linter.brace_function_lengths(source, "objective_c")

    def issues(self, filename, source, limits=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter.check_paths(root, [path], limits or LIMITS)

    def test_instance_void_unary_selector_is_detected(self):
        source = "- (void)reset {\n    clear_state();\n}\n"
        self.assertEqual(self.lengths(source), [("reset", 1, 3, 0)])

    def test_class_value_return_selector_is_detected(self):
        source = "+ (NSInteger)count {\n    return 1;\n}\n"
        self.assertEqual(self.lengths(source), [("count", 1, 3, 0)])

    def test_object_return_type_and_pointer_return_type_are_detected(self):
        source = """- (NSObject *)objectValue {
    return _object;
}
- (char *)bufferValue {
    return _buffer;
}
"""
        self.assertEqual(
            self.lengths(source),
            [("objectValue", 1, 3, 0), ("bufferValue", 4, 3, 0)],
        )

    def test_multi_part_selector_name_and_parameter_slots_are_preserved(self):
        source = """- (void)setValue:(id)value forKey:(NSString *)key {
    store(value, key);
}
"""
        self.assertEqual(self.lengths(source), [("setValue:forKey:", 1, 3, 2)])

    def test_typed_parameters_with_nested_types_count_each_selector_slot(self):
        source = """- (void)configure:(NSDictionary<NSString *, NSArray<NSNumber *> *> *)options
             error:(NSError **)error {
    apply(options, error);
}
"""
        self.assertEqual(self.lengths(source), [("configure:error:", 1, 4, 2)])

    def test_variadic_selector_counts_fixed_argument_and_variadic_slot(self):
        source = """- (void)appendFormat:(NSString *)format, ... {
    append(format);
}
"""
        self.assertEqual(self.lengths(source), [("appendFormat:", 1, 3, 2)])

    def test_multiline_selector_segments_are_detected(self):
        source = """- (void)firstPart:(id)first
           secondPart:(id)second
           thirdPart:(id)third {
    consume(first, second, third);
}
"""
        self.assertEqual(self.lengths(source), [("firstPart:secondPart:thirdPart:", 1, 5, 3)])

    def test_body_brace_on_next_line_keeps_start_line_and_length(self):
        source = """+ (void)refresh:(id)value
{
    begin(value);
    finish(value);
}
"""
        self.assertEqual(self.lengths(source), [("refresh:", 1, 5, 1)])

    def test_method_prefix_can_span_lines(self):
        source = """-
(void)reset {
    clear_state();
}
"""
        self.assertEqual(self.lengths(source), [("reset", 1, 4, 0)])

    def test_method_return_type_can_span_lines(self):
        source = """- (
void
)reset {
    clear_state();
}
"""
        self.assertEqual(self.lengths(source), [("reset", 1, 5, 0)])

    def test_unary_selector_with_trailing_attribute_is_detected(self):
        source = """- (void)reset __attribute__((objc_requires_super)) {
    clear_state();
}
"""
        self.assertEqual(self.lengths(source), [("reset", 1, 3, 0)])

    def test_category_method_is_detected_without_class_scope_heuristics(self):
        source = """@implementation Widget (Private)
- (void)privateWork:(id)value {
    use(value);
}
@end
"""
        self.assertEqual(self.lengths(source), [("privateWork:", 2, 3, 1)])

    def test_comments_and_strings_containing_selector_syntax_are_ignored(self):
        source = """// - (void)fake:(id)value { bogus(); }
const char *text = "- (void)alsoFake:(id)value { bogus(); }";
- (void)realMethod:(id)value {
    use(value);
}
"""
        self.assertEqual(self.lengths(source), [("realMethod:", 3, 3, 1)])

    def test_same_line_c_label_is_not_a_selector_component(self):
        source = """- (void)reset { if (ready) { cleanup: clear_state(); } }
"""
        self.assertEqual(self.lengths(source), [("reset", 1, 1, 0)])

    def test_same_line_selector_expression_is_not_a_selector_component(self):
        source = """- (void)reset { register_callback(@selector(foo:)); }
"""
        self.assertEqual(self.lengths(source), [("reset", 1, 1, 0)])

    def test_new_method_discards_incomplete_previous_header(self):
        source = """- (void)missing:(id)value
- (void)real {
    work();
}
"""
        self.assertEqual(self.lengths(source), [("real", 2, 3, 0)])

    def test_label_continuation_after_incomplete_header_fails_closed(self):
        source = """- (void)missing:(id)value
cleanup: { clear_state(); }
"""
        self.assertEqual(self.lengths(source), [])

    def test_malformed_or_incomplete_method_headers_are_not_detected(self):
        source = """- (void)missingBody:(id)value;
- (void)unclosed:(id)value
- (void)missingReturnType value
"""
        self.assertEqual(self.lengths(source), [])

    def test_line_accounting_is_deterministic_for_multiple_methods(self):
        source = """- (void)one {
    work();
}

+ (id)two:(id)value
{
    return value;
}
"""
        expected = [("one", 1, 3, 0), ("two:", 5, 4, 1)]
        self.assertEqual(self.lengths(source), expected)
        self.assertEqual(self.lengths(source), expected)

    def test_function_and_parameter_limits_are_enforced_for_objective_c_methods(self):
        source = """- (void)overloaded:(id)one second:(id)two third:(id)three {
    first_step();
    second_step();
    third_step();
    fourth_step();
}
"""
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues("Limits.m", source)],
            [("function_length", 1), ("max_parameters", 1)],
        )

    def test_nesting_limit_is_enforced_inside_objective_c_method(self):
        source = """- (void)nested:(id)value {
    if (value) {
        if (ready()) {
            use(value);
        }
    }
}
"""
        issues = self.issues("Nesting.m", source, {**LIMITS, "max_function_lines": 20})
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("nesting_depth", 3)])

    def test_objective_c_control_blocks_are_not_methods(self):
        source = """if (ready) {
    work();
}
while (pending) {
    wait();
}
"""
        self.assertEqual(self.lengths(source), [])
        self.assertEqual(self.issues("Control.m", source), [])

    def test_c_and_cpp_functions_remain_detected(self):
        source = """int c_function(int a, int b) {
    return a + b;
}
"""
        cpp = """int cpp_function(int a, int b) {
    return a + b;
}
"""
        self.assertEqual(linter.brace_function_lengths(source, "c"), [("c_function", 1, 3, 2)])
        self.assertEqual(linter.brace_function_lengths(cpp, "cpp"), [("cpp_function", 1, 3, 2)])

    def test_public_cli_reports_objective_c_method_limits(self):
        source = """- (void)cliMethod:(id)one second:(id)two third:(id)three {
    a();
    b();
    c();
    d();
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.m").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, "max_parameters": 2, '
                '"max_nesting_depth": 10, "max_comment_lines": 20, "max_doc_comment_lines": 20, '
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

    def test_valid_objective_c_fixture_compiles_when_clang_is_available(self):
        clang = shutil.which("clang")
        if clang is None:
            self.skipTest("clang is unavailable; Objective-C compiler validation skipped")
        source = """typedef struct objc_object *id;
typedef struct objc_object NSObject;
typedef long NSInteger;
@interface Widget
- (void)configure:(id)value error:(id *)error;
@end
@implementation Widget
- (void)configure:(id)value error:(id *)error
{
    (void)value;
    (void)error;
}
+ (NSInteger)count
{
    return 1;
}
@end
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.m"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [clang, "-fsyntax-only", "-x", "objective-c", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
