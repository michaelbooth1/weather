"""Pytest setup for calibration fixtures."""

import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_verified_b_scorers(request: pytest.FixtureRequest):
    # Keep the B-1 hash-pinned test module intact. Its wrapper registers
    # temporary scorers that later tests would try to hash by source path.
    if request.node.path.name != "test_b_look_end_to_end_s0_s1.py":
        yield
        return

    prefix = "weather.calibration._b_scorer_s1_"
    previous = {name: module for name, module in sys.modules.copy().items() if name.startswith(prefix)}
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if name.startswith(prefix):
                sys.modules.pop(name, None)
        sys.modules.update(previous)
