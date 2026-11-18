"""run_command hands checks an env without the git hook's repository-location variables."""

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from scripts import ci_scope_run as run


class RunCommandEnvTests(unittest.TestCase):
    def test_a_check_run_from_a_git_hook_does_not_see_the_hooks_repository(self):
        script = "import os; print(os.environ.get('GIT_DIR'), os.environ.get('GIT_WORK_TREE'), os.environ.get('KEEP'))"
        hook_env = {"GIT_DIR": "/somewhere/.git", "GIT_WORK_TREE": "/somewhere", "KEEP": "1"}
        with unittest.mock.patch.dict("os.environ", hook_env):
            code, output = run.run_command([sys.executable, "-c", script], Path(tempfile.gettempdir()))
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "None None 1")


if __name__ == "__main__":
    unittest.main()
