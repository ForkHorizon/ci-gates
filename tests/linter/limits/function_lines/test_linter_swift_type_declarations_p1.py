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
    "max_nesting_depth": 10,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}

APPLOGGER = """enum LogLevel: String { case info }
@MainActor
final class AppLogger {
    static let shared = AppLogger()
    private let queue = DispatchQueue(label: "logger")
    init() {
        queue.async { [self] in print(queue) }
    }
    func debug(_ event: String, _ message: String, context: [String: Any] = [:]) {
        print(event, message, context)
    }
    private func log(_ level: LogLevel, event: String, _ message: String, context: [String: Any], synchronous: Bool = false) {
        let work = { [self] in print(level, event, message, context, synchronous) }
        queue.async(execute: work)
    }
}
"""

CORPUS_CASES = {
    "RunnerWorkItem.swift": """struct RunnerWorkItem: Identifiable {
    let id: String
    let title: String
    let detail: String
}
""",
    "URL+SafeAppend.swift": """extension URL {
    func safelyAppendingPathComponent(_ pathComponent: String, isDirectory: Bool = false) throws -> URL {
        pathComponent.isEmpty ? self : appendingPathComponent(pathComponent, isDirectory: isDirectory)
    }
}
""",
    "AutomationScriptInstallMode.swift": """enum AutomationScriptInstallMode: String, CaseIterable, Identifiable {
    case localBroker
    var id: String { rawValue }
    func detail(for script: String?) -> String { script ?? "none" }
}
""",
}


class SwiftTypeDeclarationP1Tests(unittest.TestCase):
    def functions(self, source):
        return linter_checker.brace_function_lengths(source, "swift")

    def issues(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Fixture.swift"
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], LIMITS)

    def assert_method_limits(self, source, name):
        functions = self.functions(source)
        self.assertEqual([(item[0], item[3]) for item in functions], [(name, 3)])
        self.assertEqual(
            [issue.kind for issue in self.issues(source)],
            ["function_length", "max_parameters"],
        )

    def test_class_declaration_is_not_a_function(self):
        self.assertEqual(self.functions("final class AppLogger(a: Int, b: Int, c: Int) {}\n"), [])

    def test_struct_declaration_is_not_a_function(self):
        self.assertEqual(self.functions("struct Payload(a: Int, b: Int, c: Int) {}\n"), [])

    def test_enum_declaration_is_not_a_function(self):
        self.assertEqual(self.functions("enum Result { case value(a: Int, b: Int, c: Int) }\n"), [])

    def test_protocol_declaration_is_not_a_function(self):
        self.assertEqual(self.functions("protocol Service { init(a: Int, b: Int, c: Int) }\n"), [])

    def test_extension_declaration_is_not_a_function(self):
        source = 'private extension String { static let sample = String(repeating: "x", count: 3) }\n'
        self.assertEqual(self.functions(source), [])

    def test_class_method_still_has_both_limits(self):
        self.assert_method_limits(
            "class Box {\n    func run(a: Int, b: Int, c: Int) {\n        a\n        b\n        c\n    }\n}\n",
            "run",
        )

    def test_struct_initializer_still_has_both_limits(self):
        self.assert_method_limits(
            "struct Box {\n    init(a: Int, b: Int, c: Int) {\n        self.a = a\n        self.b = b\n        self.c = c\n    }\n}\n",
            "init",
        )

    def test_enum_method_still_has_both_limits(self):
        self.assert_method_limits(
            "enum Box {\n    func value(a: Int, b: Int, c: Int) {\n        print(a)\n        print(b)\n        print(c)\n    }\n}\n",
            "value",
        )

    def test_extension_method_still_has_both_limits(self):
        self.assert_method_limits(
            "extension Box {\n    func value(a: Int, b: Int, c: Int) {\n        print(a)\n        print(b)\n        print(c)\n    }\n}\n",
            "value",
        )

    def test_protocol_requirement_is_not_measured_without_a_body(self):
        source = "protocol Service {\n    func run(a: Int, b: Int, c: Int)\n}\n"
        self.assertEqual(self.functions(source), [])

    def test_app_logger_corpus_keeps_named_methods_and_drops_type_false_positive(self):
        functions = self.functions(APPLOGGER)
        names = [item[0] for item in functions]
        self.assertIn("debug", names)
        self.assertIn("log", names)
        self.assertNotIn("AppLogger", names)
        self.assertNotIn("<anonymous>", [item[0] for item in functions if item[1] == 3])

    def test_app_logger_log_method_still_reports_both_limits(self):
        issues = self.issues(APPLOGGER)
        log_issues = [issue for issue in issues if issue.line == 12]
        self.assertEqual([issue.kind for issue in log_issues], ["function_length", "max_parameters"])

    def test_ci_scope_runner_work_item_corpus_has_no_function_false_positive(self):
        self.assertEqual(self.functions(CORPUS_CASES["RunnerWorkItem.swift"]), [])

    def test_ci_scope_url_extension_corpus_keeps_only_real_method(self):
        names = [item[0] for item in self.functions(CORPUS_CASES["URL+SafeAppend.swift"])]
        self.assertEqual(names, ["safelyAppendingPathComponent"])

    def test_ci_scope_enum_corpus_keeps_real_computed_method(self):
        names = [item[0] for item in self.functions(CORPUS_CASES["AutomationScriptInstallMode.swift"])]
        self.assertEqual(names, ["detail"])

    def test_main_actor_class_header_does_not_seed_a_closure_candidate(self):
        source = "@MainActor\nfinal class Model {\n    let service = Service()\n    func load() {\n        service.run()\n    }\n}\n"
        self.assertEqual([item[0] for item in self.functions(source)], ["load"])

    def test_imports_and_property_initializers_do_not_hide_following_methods(self):
        source = "import Foundation\nclass Model {\n    let service = Service()\n    func load(a: Int, b: Int, c: Int) {\n        a\n        b\n        c\n    }\n}\n"
        self.assert_method_limits(source, "load")

    def test_inline_type_header_preserves_inline_method_detection(self):
        source = "struct Box { func run(a: Int, b: Int, c: Int) { print(a); print(b); print(c) } }\n"
        self.assertEqual([(item[0], item[3]) for item in self.functions(source)], [("run", 3)])


if __name__ == "__main__":
    unittest.main()
