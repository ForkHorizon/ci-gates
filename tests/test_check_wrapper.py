import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CheckWrapperTests(unittest.TestCase):
    def test_wrapper_passes_tier_and_writes_compact_result_under_temp_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            gates = base / "gates"
            (repo / "scripts").mkdir(parents=True)
            (gates / "scripts").mkdir(parents=True)
            (repo / ".ci-scope.json").write_text('{"version":1,"slow_ms":500,"checks":[]}')
            (gates / "scripts/run-checks.py").write_text(
                "import json,sys\n"
                "args=sys.argv\n"
                "out=args[args.index('--result-file')+1]\n"
                "json.dump({'status':'passed','tier':args[args.index('--tier')+1],"
                "'started_at':'start','finished_at':'end','git_head':'abc','dirty':True,"
                "'checks':[{'id':'lint','status':'passed','duration_ms':700}], 'slow':['lint']},open(out,'w'))\n"
                "print('OK  1 checks, 0.7s')\n"
            )
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "README.md").write_text("repo\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:owner/sample.git"], check=True
            )
            home = base / "home"
            env = dict(os.environ, HOME=str(home), CI_SCOPE_GATES=str(gates))
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check"), "full"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            output = home / ".ci-scope/checks/owner-sample.json"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OK  1 checks, 0.7s", result.stdout)
            self.assertIn("SLOW lint", result.stdout)
            self.assertEqual(json.loads(output.read_text())["tier"], "full")

    def test_failed_check_keeps_reported_full_log_available(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            gates = base / "gates"
            (repo / "scripts").mkdir(parents=True)
            (gates / "scripts").mkdir(parents=True)
            (repo / ".ci-scope.json").write_text('{"version":1,"checks":[]}')
            (gates / "scripts/run-checks.py").write_text(
                "import pathlib,sys\n"
                "args=sys.argv\n"
                "out=pathlib.Path(args[args.index('--output')+1])/'logs/lint.log'\n"
                "out.parent.mkdir(parents=True)\n"
                "out.write_text('lint failed\\n')\n"
                "print(f'FAIL lint\\nfull log: {out}')\n"
                "sys.exit(1)\n"
            )
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "README.md").write_text("repo\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:owner/sample.git"], check=True
            )
            home_target = base / "real-home"
            home_target.mkdir()
            home = base / "home"
            home.symlink_to(home_target, target_is_directory=True)
            env = dict(os.environ, HOME=str(home), CI_SCOPE_GATES=str(gates))
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check")],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            log_path = next(
                line.removeprefix("full log: ") for line in result.stdout.splitlines() if line.startswith("full log: ")
            )
            self.assertTrue(Path(log_path).is_file())
            self.assertEqual(Path(log_path).read_text(), "lint failed\n")

    def test_setup_failure_without_a_reported_log_cleans_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            gates = base / "gates"
            (repo / "scripts").mkdir(parents=True)
            (gates / "scripts").mkdir(parents=True)
            (repo / ".ci-scope.json").write_text('{"version":1,"checks":[]}')
            (gates / "scripts/run-checks.py").write_text("print('setup failed')\nraise SystemExit(2)\n")
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "README.md").write_text("repo\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:owner/sample.git"], check=True
            )
            home = base / "home"
            env = dict(os.environ, HOME=str(home), CI_SCOPE_GATES=str(gates))
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check")],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("setup failed", result.stdout)
            self.assertEqual(list((home / ".ci-scope/checks").iterdir()), [])


class CheckWrapperArgumentTests(unittest.TestCase):
    def test_quiet_flag_is_accepted_but_unknown_flags_are_rejected(self):
        for args, expected in ((["--quiet"], 2), (["--bogus"], 2)):
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check"), *args],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if args == ["--quiet"]:
                self.assertNotIn("usage:", result.stderr)
            else:
                self.assertIn("usage:", result.stderr)
            self.assertEqual(result.returncode, expected)


if __name__ == "__main__":
    unittest.main()
