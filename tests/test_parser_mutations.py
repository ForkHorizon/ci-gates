from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-parser-mutations.py"
SPEC = importlib.util.spec_from_file_location("parser_mutation_runner", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class ParserMutationStageTests(unittest.TestCase):
    def test_stage_has_six_targeted_mutations(self):
        self.assertGreaterEqual(len(RUNNER.MUTATIONS), 6)

    def test_mutation_names_are_unique_and_stable(self):
        names = [mutation.name for mutation in RUNNER.MUTATIONS]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_mutations_target_only_code_linter_parser_modules(self):
        for mutation in RUNNER.MUTATIONS:
            self.assertTrue(mutation.relative_path.startswith("scripts/code_linter/"))
            self.assertTrue(mutation.relative_path.endswith(".py"))

    def test_each_mutation_has_one_focused_unittest_module(self):
        for mutation in RUNNER.MUTATIONS:
            with self.subTest(mutation=mutation.name):
                self.assertTrue(mutation.test_module.startswith("tests."))
                self.assertNotIn(" ", mutation.test_module)

    def test_each_clean_source_contains_exactly_one_mutation_site(self):
        for mutation in RUNNER.MUTATIONS:
            with self.subTest(mutation=mutation.name):
                source = (ROOT / mutation.relative_path).read_text(encoding="utf-8")
                self.assertEqual(source.count(mutation.old), 1)
                self.assertNotEqual(mutation.old, mutation.new)

    def test_mutation_command_uses_current_python_and_unittest(self):
        for mutation in RUNNER.MUTATIONS:
            with self.subTest(mutation=mutation.name):
                self.assertEqual(mutation.command[0], "{python}")
                self.assertEqual(mutation.command[1:3], ("-m", "unittest"))

    def test_runner_lists_mutations_deterministically(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--list"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [mutation.name for mutation in RUNNER.MUTATIONS])

    def test_runner_rejects_unknown_mutation_name(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--mutation", "does-not-exist"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown mutation", result.stderr)

    def test_apply_mutation_rejects_missing_source_site(self):
        mutation = RUNNER.Mutation("bad", "scripts/code_linter/syntax.py", "not present", "replacement", ("tests.foo",))
        with self.assertRaises(RUNNER.MutationError):
            RUNNER.apply_mutation(ROOT, mutation)

    def test_runner_reports_success_only_when_all_mutations_are_killed(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--mutation", RUNNER.MUTATIONS[0].name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{RUNNER.MUTATIONS[0].name}: killed", result.stdout)
        self.assertIn("1/1 killed", result.stdout)


if __name__ == "__main__":
    unittest.main()
