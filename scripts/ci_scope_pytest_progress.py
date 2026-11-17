"""pytest plugin: prints `::ci-scope-progress::` markers (test n of total) for CI Scope's live task view.

Loaded by ci_scope_run.run_command through PYTEST_ADDOPTS only while the agent asks for activity.
Standard library only; silent without CI_SCOPE_PYTEST_PROGRESS=1, so nested pytest runs stay quiet.
"""

import json
import os
import time

ENV = "CI_SCOPE_PYTEST_PROGRESS"
MIN_INTERVAL = 0.5
STATE = {"total": 0, "done": 0, "last": 0.0, "on": False}


def _marker(step, current, total, detail=""):
    payload = {"step": step, "current": current, "total": total, "detail": detail[:160], "version": 1}
    print("\n::ci-scope-progress:: " + json.dumps(payload), flush=True)  # leading \n: dots may precede it


def pytest_configure(config):
    STATE["on"] = os.environ.pop(ENV, "") == "1" and not hasattr(config, "workerinput")  # not xdist workers


def pytest_collection_finish(session):
    if STATE["on"]:
        STATE["total"] = len(session.items)
        _marker("pytest", 0, STATE["total"], "collected")


def pytest_runtest_logreport(report):
    if not STATE["on"] or (report.when != "call" and not (report.when == "setup" and report.outcome != "passed")):
        return
    STATE["done"] += 1
    now = time.monotonic()
    if now - STATE["last"] >= MIN_INTERVAL or STATE["done"] == STATE["total"]:
        STATE["last"] = now
        _marker("pytest", STATE["done"], STATE["total"], report.nodeid)
