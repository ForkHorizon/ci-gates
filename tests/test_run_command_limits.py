import sys
import tempfile
import unittest
from pathlib import Path

from scripts import ci_scope_run as run


class RunCommandLimitTests(unittest.TestCase):
    def test_the_tail_of_the_output_is_returned_with_the_exit_code(self):
        code, output = run.run_command(
            [sys.executable, "-c", "print('a'*10000); print('the end'); raise SystemExit(3)"],
            Path(tempfile.gettempdir()),
        )
        self.assertEqual(code, 3)
        self.assertTrue(output.rstrip().endswith("the end"))
        self.assertLessEqual(len(output), run.MAX_OUTPUT)

    def test_a_command_that_floods_its_output_is_stopped_not_buffered(self):
        original = run.MAX_CAPTURE_BYTES
        self.addCleanup(setattr, run, "MAX_CAPTURE_BYTES", original)
        run.MAX_CAPTURE_BYTES = 1024 * 1024
        script = "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n    sys.stdout.flush()\n"
        code, output = run.run_command([sys.executable, "-c", script], Path(tempfile.gettempdir()))
        self.assertNotEqual(code, 0)
        self.assertLessEqual(len(output), run.MAX_OUTPUT)

    def test_a_missing_program_is_reported_not_raised(self):
        code, output = run.run_command(["definitely-not-a-program-xyz"], Path(tempfile.gettempdir()))
        self.assertEqual(code, 127)
        self.assertTrue(output)


if __name__ == "__main__":
    unittest.main()
