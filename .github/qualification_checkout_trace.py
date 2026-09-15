"""Development-only attribution of the observed native CI checkout cache leak."""

import json
import os
from pathlib import Path
import sys

import pytest


class CheckoutTrace:
    def __init__(self):
        self.root = Path.cwd()
        self.seen = False
        self.destination = Path(os.environ["RUNNER_TEMP"]) / "qualification-checkout-trace.jsonl"

    def record(self, nodeid, phase):
        target = self.root / "Microsoft"
        if self.seen or not target.exists():
            return
        self.seen = True
        paths = []
        for parent, directories, files in os.walk(target, followlinks=False):
            paths.extend(str((Path(parent) / name).relative_to(self.root)) for name in files)
            if len(paths) >= 100:
                break
        with self.destination.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"nodeid": nodeid, "phase": phase, "paths": paths[:100]}) + "\n")

    def pytest_sessionstart(self, session):
        self.record(None, "before-session")

    def pytest_runtest_logreport(self, report):
        self.record(report.nodeid, report.when)


if __name__ == "__main__":
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[CheckoutTrace()]))
