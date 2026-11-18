"""pytest plugin: prints `::ci-scope-progress::` markers (test n of total) for CI Scope's live task view.

Loaded by ci_scope_run.run_command through PYTEST_ADDOPTS only while the agent asks for activity.
Standard library only; silent without CI_SCOPE_PYTEST_PROGRESS=1, so nested pytest runs stay quiet.
"""

import json
import os
import time

try:
    from pytest import hookimpl
except ImportError:  # imported outside pytest (unit tests run by unittest): no hook validation to satisfy

    def hookimpl(**options):
        def mark(function):
            function.pytest_impl = options  # the attribute pytest's own marker sets
            return function

        return mark


ENV = "CI_SCOPE_PYTEST_PROGRESS"
MIN_INTERVAL = 0.5
STATE = {"total": 0, "done": 0, "last": 0.0, "on": False, "seen": set()}


def _marker(step, current, total, detail=""):
    payload = {"step": step, "current": current, "total": total, "detail": detail[:160], "version": 1}
    print("\n::ci-scope-progress:: " + json.dumps(payload), flush=True)  # leading \n: dots may precede it


def pytest_configure(config):
    STATE.update(total=0, done=0, last=0.0, seen=set())
    STATE["on"] = os.environ.pop(ENV, "") == "1" and not hasattr(config, "workerinput")  # not xdist workers


def pytest_collection_finish(session):
    if STATE["on"] and session.items:  # with xdist the controller collects nothing; its workers report below
        STATE["total"] = len(session.items)
        _marker("pytest", 0, STATE["total"], "collected")


@hookimpl(optionalhook=True)  # xdist's hook: unknown, and fatal, without xdist installed
def pytest_xdist_node_collection_finished(ids):
    """xdist: each worker collects every test, so the first one to finish tells the controller the total."""
    if STATE["on"] and not STATE["total"]:
        STATE["total"] = len(ids)
        _marker("pytest", 0, STATE["total"], "collected")


def pytest_runtest_logreport(report):
    if not STATE["on"] or (report.when != "call" and not (report.when == "setup" and report.outcome != "passed")):
        return
    if report.nodeid in STATE["seen"]:  # subtests and reruns report the same test again
        return
    STATE["seen"].add(report.nodeid)
    STATE["done"] += 1
    now = time.monotonic()
    if now - STATE["last"] >= MIN_INTERVAL or STATE["done"] == STATE["total"]:
        STATE["last"] = now
        _marker("pytest", STATE["done"], STATE["total"], report.nodeid)
