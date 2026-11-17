import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest import mock

from scripts import ci_scope_activity as activity
from scripts import ci_scope_pytest_progress as plugin
from scripts import ci_scope_run as run

MARKER = '::ci-scope-progress:: {"step":"lint","current":2,"total":9,"detail":"src/a.swift","version":1}'


def events(env, action):
    err = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
        action()
    return [json.loads(line.removeprefix("@@activity ")) for line in err.getvalue().splitlines()]


class ActivityTests(unittest.TestCase):
    def test_silent_unless_the_agent_asks(self):
        self.assertEqual(events({}, lambda: activity.emit({"check": "x"})), [])

    def test_parses_a_gate_marker(self):
        self.assertEqual(activity.parse_marker(MARKER)["detail"], "src/a.swift")
        self.assertIsNone(activity.parse_marker("plain output"))

    def test_run_command_relays_the_markers_a_command_prints(self):
        script = f"import time; print({MARKER!r}, flush=True); time.sleep(1.5)"

        def go():
            run.CURRENT["check"] = "code-linter"
            run.run_command([sys.executable, "-c", script], Path(tempfile.gettempdir()))

        got = events({"CI_SCOPE_ACTIVITY": "1"}, go)
        self.assertEqual(
            got,
            [
                {
                    "check": "code-linter",
                    "state": "running",
                    "step": "lint",
                    "current": 2,
                    "total": 9,
                    "detail": "src/a.swift",
                }
            ],
        )

    def test_pytest_plugin_reports_test_n_of_total(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {plugin.ENV: "1"}), contextlib.redirect_stdout(out):
            plugin.pytest_configure(Obj())
            plugin.pytest_collection_finish(Obj(items=[1, 2]))
            for node in ("t.py::a", "t.py::b"):
                plugin.pytest_runtest_logreport(Obj(when="call", outcome="passed", nodeid=node))
        marks = [activity.parse_marker(line) for line in out.getvalue().splitlines()]
        marks = [m for m in marks if m]
        self.assertEqual([(m["current"], m["total"]) for m in marks], [(0, 2), (1, 2), (2, 2)])
        self.assertEqual(marks[-1]["detail"], "t.py::b")
        self.assertNotIn(plugin.ENV, os.environ)  # nested pytest runs stay quiet


if __name__ == "__main__":
    unittest.main()
