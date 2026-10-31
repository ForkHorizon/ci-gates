import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_reporting import MAX_LOG_BYTES
from ci_scope_adapters import commands_for

SPEC = importlib.util.spec_from_file_location("run_checks", ROOT / "scripts/run-checks.py")
RUN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUN
SPEC.loader.exec_module(RUN)


def measure_peak(checks, context):
    active = 0
    peak = 0
    gate = threading.Lock()
    original = RUN.run_process

    def fake_process(*_args, **_kwargs):
        nonlocal active, peak
        with gate:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with gate:
            active -= 1
        return 0, "ok"

    RUN.run_process = fake_process
    try:
        workers = [threading.Thread(target=RUN.run_check, args=(check, context)) for check in checks]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        RUN.run_process = original
    return peak


class RunChecksTests(unittest.TestCase):
    def test_adapter_commands_do_not_use_shell(self):
        check = type(
            "Check",
            (),
            {"type": "python-quality", "config": None, "params": {}, "workdir": "."},
        )()
        commands = commands_for(check, ROOT, ROOT, ("base", "head"))
        self.assertEqual(commands[0][:2], ["ruff", "check"])
        self.assertTrue(all(command[0] != "sh" for command in commands))

    def test_code_linter_auto_mode_and_signature_guard_match_event(self):
        check = type(
            "Check",
            (),
            {
                "type": "code-linter",
                "config": ".code-linter.json",
                "params": {"mode": "auto"},
            },
        )()
        changed = commands_for(check, ROOT, ROOT, ("base", "head"), "pull_request")
        all_files = commands_for(check, ROOT, ROOT, ("base", "head"), "schedule")
        self.assertIn("policy_signature_guard.py", changed[0][1])
        self.assertEqual(changed[1][changed[1].index("--mode") + 1], "changed")
        self.assertEqual(len(all_files), 1)
        self.assertEqual(all_files[0][all_files[0].index("--mode") + 1], "all")

    def test_worktree_mode_skips_commit_signature_guard(self):
        check = type(
            "Check",
            (),
            {"type": "code-linter", "config": None, "params": {"mode": "worktree"}},
        )()
        commands = commands_for(check, ROOT, ROOT, ("base", "head"), "local")
        self.assertEqual(len(commands), 1)
        self.assertIn("--mode", commands[0])
        self.assertEqual(commands[0][commands[0].index("--mode") + 1], "worktree")

    def test_code_shape_adapters_scan_new_worktree_lines(self):
        for check_type, script in (
            ("forbidden-constructs", "forbidden_constructs.py"),
            ("duplicate-blocks", "duplicate_blocks.py"),
        ):
            check = type(
                "Check",
                (),
                {"type": check_type, "config": None, "params": {"mode": "new"}},
            )()
            command = commands_for(check, ROOT, ROOT, ("base", "head"), "local")[0]
            self.assertTrue(command[1].endswith(script))
            self.assertEqual(command[command.index("--git-mode") + 1], "worktree")
            self.assertEqual(command[command.index("--mode") + 1], "new")

    def test_tier_dependency_excluded_from_run_counts_as_satisfied(self):
        dependent = type(
            "Check",
            (),
            {
                "id": "dependent",
                "type": "code-linter",
                "required": True,
                "depends_on": ("dependency",),
            },
        )()
        results = {}
        self.assertEqual(RUN.ready_checks([dependent], results, {"dependent"}), [dependent])

    def test_report_uses_only_checks_selected_for_tier(self):
        full = type("Check", (), {"id": "slow-check"})()
        fast = type("Check", (), {"id": "fast-check"})()
        manifest = type("Manifest", (), {"active_checks": (fast, full)})()
        args = type("Args", (), {"base": "base", "head": "head", "event": "local"})()
        report = RUN.build_report(
            args,
            manifest,
            "digest",
            {"fast-check": {"id": "fast-check", "status": "passed"}},
            [fast],
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual([check["id"] for check in report["checks"]], ["fast-check"])

    def test_tier_dependency_failure_still_skips_dependent(self):
        dependent = type(
            "Check",
            (),
            {
                "id": "dependent",
                "type": "code-linter",
                "required": True,
                "depends_on": ("dependency",),
            },
        )()
        results = {"dependency": {"status": "failed"}}
        self.assertEqual(RUN.ready_checks([dependent], results, {"dependency", "dependent"}), [])
        self.assertEqual(results["dependent"]["status"], "skipped")

    def test_quiet_success_is_one_line_and_failure_prints_tail_and_absolute_log(self):
        success = StringIO()
        with redirect_stdout(success):
            RUN.print_quiet({"checks": [{"status": "passed"}, {"status": "passed"}]}, ROOT, 1.2, 30)
        self.assertEqual(success.getvalue(), "OK  2 checks, 1.2s\n")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            log = output / "logs/bad.log"
            log.parent.mkdir()
            log.write_text("one\ntwo\nfile.py:3: invalid\n")
            failure = StringIO()
            report = {
                "checks": [
                    {
                        "id": "lint",
                        "status": "failed",
                        "detail": "command failed",
                        "log": "logs/bad.log",
                    }
                ]
            }
            with redirect_stdout(failure):
                RUN.print_quiet(report, output, 0.1, 2)
            self.assertIn("FAIL lint  command failed", failure.getvalue())
            self.assertIn("two\nfile.py:3: invalid", failure.getvalue())
            self.assertIn(f"full log: {log.resolve()}", failure.getvalue())

    def test_swift_quality_skips_build_without_changing_dead_code_scope(self):
        check = type(
            "Check",
            (),
            {
                "type": "swift-quality",
                "config": ".swift-quality-gate.json",
                "params": {"run_build": False},
            },
        )()
        commands = commands_for(check, ROOT, ROOT, ("base", "head"), "pull_request")
        self.assertEqual(
            [command[command.index("--stage") + 1] for command in commands],
            ["format", "dead-code"],
        )
        self.assertEqual(commands[0][commands[0].index("--mode") + 1], "changed")
        self.assertEqual(commands[1][commands[1].index("--mode") + 1], "all")

    def test_slop_review_preserves_workflow_default_model(self):
        check = type(
            "Check",
            (),
            {"type": "slop-review", "config": ".slop-review.json", "params": {}},
        )()
        command = commands_for(check, ROOT, ROOT, ("base", "head"))[0]
        self.assertEqual(command[command.index("--model") + 1], RUN.DEFAULT_AI_MODEL)

    def test_python_quality_uses_strict_fallback_without_project_config(self):
        with tempfile.TemporaryDirectory() as directory:
            check = type(
                "Check",
                (),
                {
                    "type": "python-quality",
                    "config": None,
                    "params": {},
                    "workdir": ".",
                },
            )()
            commands = commands_for(check, Path(directory), ROOT, ("base", "head"))
        self.assertEqual(commands[0][2:4], ["--config", str(ROOT / "configs/ruff-strict.toml")])

    def test_process_timeout_terminates_process_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            code, detail = RUN.run_process(
                [[RUN.sys.executable, "-c", "import time; time.sleep(5)"]],
                Path(directory),
                1,
                Path(directory) / "check.log",
            )
        self.assertEqual(code, 124)
        self.assertIn("timed out", detail)

    def test_process_logs_are_redacted_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = "ghp_" + "x" * 30
            code, _ = RUN.run_process(
                [
                    [
                        RUN.sys.executable,
                        "-c",
                        f"print('token={secret}'); print('x' * 100000)",
                    ]
                ],
                Path(directory),
                2,
                Path(directory) / "check.log",
            )
            log = (Path(directory) / "check.log").read_text()
        self.assertEqual(code, 0)
        self.assertNotIn(secret, log)
        self.assertLessEqual(len(log.encode()), MAX_LOG_BYTES)
        self.assertIn("[TRUNCATED]", log)

    def test_checks_sharing_resource_are_serialized(self):
        manifest = type("Manifest", (), {"root": ROOT})()
        args = type(
            "Args",
            (),
            {"base": "base", "head": "head", "event": "pull_request", "timeout": 2},
        )()
        output = Path(tempfile.mkdtemp())
        context = RUN.RunContext(args, manifest, ROOT, output, {"xcode": threading.Lock()})
        checks = [
            type(
                "Check",
                (),
                {
                    "id": str(i),
                    "type": "swift-compile",
                    "config": None,
                    "params": {},
                    "workdir": ".",
                    "resources": ("xcode",),
                    "required": True,
                },
            )()
            for i in range(2)
        ]
        self.assertEqual(measure_peak(checks, context), 1)


if __name__ == "__main__":
    unittest.main()
