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


if __name__ == "__main__":
    unittest.main()
