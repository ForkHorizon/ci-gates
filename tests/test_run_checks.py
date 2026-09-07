import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_reporting import MAX_LOG_BYTES
SPEC = importlib.util.spec_from_file_location("run_checks", ROOT / "scripts/run-checks.py")
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class RunChecksTests(unittest.TestCase):
    def test_adapter_commands_do_not_use_shell(self):
        check = type("Check", (), {"type": "python-quality", "config": None, "params": {}, "workdir": "."})()
        commands = RUN.commands_for(check, ROOT, ROOT, "base", "head")
        self.assertEqual(commands[0][:2], ["ruff", "check"])
        self.assertTrue(all(command[0] != "sh" for command in commands))

    def test_code_linter_auto_mode_and_signature_guard_match_event(self):
        check = type("Check", (), {"type": "code-linter", "config": ".code-linter.json", "params": {"mode": "auto"}})()
        changed = RUN.commands_for(check, ROOT, ROOT, "base", "head", "pull_request")
        all_files = RUN.commands_for(check, ROOT, ROOT, "base", "head", "schedule")
        self.assertIn("policy_signature_guard.py", changed[0][1])
        self.assertEqual(changed[1][changed[1].index("--mode") + 1], "changed")
        self.assertEqual(len(all_files), 1)
        self.assertEqual(all_files[0][all_files[0].index("--mode") + 1], "all")

    def test_swift_quality_skips_build_without_changing_dead_code_scope(self):
        check = type("Check", (), {"type": "swift-quality", "config": ".swift-quality-gate.json", "params": {"run_build": False}})()
        commands = RUN.commands_for(check, ROOT, ROOT, "base", "head", "pull_request")
        self.assertEqual([command[command.index("--stage") + 1] for command in commands], ["format", "dead-code"])
        self.assertEqual(commands[0][commands[0].index("--mode") + 1], "changed")
        self.assertEqual(commands[1][commands[1].index("--mode") + 1], "all")

    def test_slop_review_preserves_workflow_default_model(self):
        check = type("Check", (), {"type": "slop-review", "config": ".slop-review.json", "params": {}})()
        command = RUN.commands_for(check, ROOT, ROOT, "base", "head")[0]
        self.assertEqual(command[command.index("--model") + 1], RUN.DEFAULT_AI_MODEL)

    def test_python_quality_uses_strict_fallback_without_project_config(self):
        with tempfile.TemporaryDirectory() as directory:
            check = type("Check", (), {"type": "python-quality", "config": None, "params": {}, "workdir": "."})()
            commands = RUN.commands_for(check, Path(directory), ROOT, "base", "head")
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
                [[RUN.sys.executable, "-c", f"print('token={secret}'); print('x' * 100000)" ]],
                Path(directory), 2, Path(directory) / "check.log")
            log = (Path(directory) / "check.log").read_text()
        self.assertEqual(code, 0)
        self.assertNotIn(secret, log)
        self.assertLessEqual(len(log.encode()), MAX_LOG_BYTES)
        self.assertIn("[TRUNCATED]", log)

    def test_checks_sharing_resource_are_serialized(self):
        manifest = type("Manifest", (), {"root": ROOT})()
        args = type("Args", (), {"base": "base", "head": "head", "timeout": 2})()
        output = Path(tempfile.mkdtemp())
        locks = {"xcode": threading.Lock()}
        checks = [type("Check", (), {"id": str(i), "type": "swift-compile", "config": None,
                                     "params": {}, "workdir": ".", "resources": ("xcode",),
                                     "required": True})() for i in range(2)]
        active = 0
        peak = 0
        gate = threading.Lock()
        original = RUN.run_process

        def fake_process(*_args):
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
            workers = [threading.Thread(target=RUN.run_check, args=(check, args, manifest, ROOT, output, locks))
                       for check in checks]
            for worker in workers: worker.start()
            for worker in workers: worker.join()
        finally:
            RUN.run_process = original
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
