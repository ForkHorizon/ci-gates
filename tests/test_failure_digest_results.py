"""Tests for failure_digest on real failed-check logs and for the result items ci_scope_run builds from them."""

import unittest
from pathlib import Path

from scripts import ci_scope_run as run
from scripts import failure_digest as fd

FIXTURES = Path(__file__).parent / "fixtures" / "failure_digest"
PROGRESS = '::ci-scope-progress:: {"step": "lint", "current": 1, "total": 2, "detail": "a.ts", "version": 1}\n'
ANNOTATED = (
    "::error file=src/a.ts,line=1,title=file_length::File has 609 lines; limit is 600.\n"
    "::error file=src/a.ts,line=128,title=function_length::App has 481 lines; function/method limit is 80.\n"
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class RealLogTests(unittest.TestCase):
    def test_golden_lines_from_real_failed_checks(self):
        expected = {
            "code-linter-2.log": "scripts/forbidden_constructs.py:1 file_length: File has 344 lines; limit is 300.",
            "python-quality-1.log": "planning/tests/test_browser_first_plan.py:1 I001: [*] Import block is un-sorted or un-formatted",
            "file-roles-1.log": "apps/web/src/terminal-session-state.ts:1 missing-file-header: new file needs a one-line header comment",
        }
        for name, line in expected.items():
            self.assertTrue(fd.digest(fixture(name)).line().startswith(line), name)

    def test_tests_removed_and_protected_files_have_no_line_number(self):
        line = fd.digest(fixture("test-protection-1.log")).line()
        self.assertIn("crates/shardraild/Cargo.toml test-build-config-changed", line)

    def test_stack_traces_stay_unstructured_with_an_excerpt(self):
        for name in ("web-tests-1.log", "web-quality-1.log"):
            found = fd.digest(fixture(name))
            self.assertFalse(found.structured, name)
            self.assertIn("MODULE_NOT_FOUND" if "quality" in name else "ERR_MODULE_NOT_FOUND", found.excerpt)

    def test_every_other_real_log_is_structured(self):
        for log in FIXTURES.glob("*.log"):
            if log.name.startswith(("web-",)):
                continue
            self.assertTrue(fd.digest(log.read_text(encoding="utf-8")).structured, log.name)


class CheckResultTests(unittest.TestCase):
    def test_a_passed_check_has_no_detail(self):
        self.assertEqual(run.check_result("lint", 0, "ignored"), {"id": "lint", "status": "passed", "detail": ""})

    def test_a_structured_failure_gets_the_digest_line_as_detail(self):
        result = run.check_result("code-linter", 1, PROGRESS + ANNOTATED)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["detail"].startswith("src/a.ts:1 file_length"))
        self.assertNotIn("excerpt", result)

    def test_an_unstructured_failure_carries_a_bounded_excerpt_for_the_agent(self):
        result = run.check_result("web-tests", 1, "x\n" * 20_000 + "Error: Cannot find package 'esbuild'\n")
        self.assertTrue(result["unstructured"])
        self.assertLessEqual(len(result["detail"]), run.MAX_RAW_DETAIL)
        self.assertLessEqual(len(result["excerpt"]), fd.MAX_EXCERPT)
        self.assertTrue(result["excerpt"].rstrip().endswith("esbuild'"))

    def test_the_verdict_line_names_the_location_of_a_structured_failure(self):
        verdict = run.verdict_line([run.check_result("code-linter", 1, ANNOTATED)])
        self.assertIn("code-linter: src/a.ts:1 file_length", verdict)


if __name__ == "__main__":
    unittest.main()
