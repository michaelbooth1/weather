"""The real live launcher runner must shut down cooperatively when its caller's stdin is open.

Windows PowerShell answers Ctrl+Break inside a running script by entering its
debugger and reading a command from stdin. If the launcher child inherited an
open stdin (an operator console, or a pipe the caller holds) that read blocks,
the script never reaches its own exit, and every interrupted live session ends
as a forced Job teardown after the cleanup reserve. The runner therefore starts
the child with stdin on the null device, so the debugger reads EOF and resumes.

This test drives the production ``_default_launcher_runner`` in a helper
process whose stdin is a pipe the test keeps open for the whole run, so the
launcher's caller has exactly the open-stdin shape that blocked. The child is a
stub script: no orders, credentials, wallet or network.

Guards: cooperative Ctrl+Break shutdown of the live launcher child
(docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md) regardless of caller stdin.
"""

from __future__ import annotations

import os

import pytest

from tests.operations.live_launcher_break_harness import assert_cooperative_break, run_break_case
from weather.operations import international_live_session_runner as runner

# Timing contract (same shape as the cooperative Ctrl+Break test beside it):
# - STARTUP_ALLOWANCE: runner call to deadline; must exceed PowerShell start-up
#   so the break lands while the script runs.
# - TAIL: the script exits 3 on its own this long after the deadline.
# - GRACE: the runner's cleanup grace (production reserve is 20 s). A forced
#   teardown cannot report before the deadline plus GRACE; a cooperative exit
#   must arrive within TAIL + MARGIN of the deadline, which leaves GAP seconds
#   of separation below GRACE. MARGIN absorbs slow CI runners: a cooperative
#   run on windows-latest was observed returning 4.9 s after the deadline.
STARTUP_ALLOWANCE_SECONDS = 3.0
TAIL_SECONDS = 0.5
GRACE_SECONDS = 12.0
MARGIN_SECONDS = 7.5
GAP_SECONDS = 4.0
COOPERATIVE_EXIT_CODE = 3


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_shuts_down_cooperatively_with_caller_stdin_open(tmp_path):
    # The helper's stdin is a pipe this test keeps open for the whole run, so the
    # launcher's caller has exactly the open-stdin shape that blocked. The helper
    # gets its own hidden console, so Ctrl+Break is delivered on every host, and
    # the stub's DebuggerStop handler proves it without console text.
    rc, text, outcome, events = run_break_case(
        tmp_path, runner.__file__, allowance=STARTUP_ALLOWANCE_SECONDS, tail=TAIL_SECONDS,
        grace=GRACE_SECONDS, caller_stdin_open=True)
    assert TAIL_SECONDS + MARGIN_SECONDS <= GRACE_SECONDS - GAP_SECONDS
    # Started as the live template starts the runner: no silencing Popen patch loaded.
    assert outcome is not None and outcome["sitecustomize_loaded"] is False and outcome["popen_silenced"] is False, text
    assert_cooperative_break(
        rc, text, outcome, events, runner_file=runner.__file__,
        max_return_after_deadline_s=TAIL_SECONDS + MARGIN_SECONDS,
        max_elapsed_s=STARTUP_ALLOWANCE_SECONDS + GRACE_SECONDS)


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_a_runner_that_never_sends_ctrl_break_fails_the_precondition(tmp_path):
    """Mutant: with no Ctrl+Break the stub still exits 3 on its own and the runner reports a
    'cooperative' outcome; only the stub's own BREAK marker tells the two apart."""
    rc, text, outcome, events = run_break_case(
        tmp_path, runner.__file__, allowance=STARTUP_ALLOWANCE_SECONDS, tail=TAIL_SECONDS,
        grace=GRACE_SECONDS, caller_stdin_open=True, mutant="no_break")
    assert outcome is not None and outcome["cooperative"] is True  # the outcome alone cannot see it
    assert "BREAK" not in dict(events)
    with pytest.raises(AssertionError, match="never reached the stub"):
        assert_cooperative_break(
            rc, text, outcome, events, runner_file=runner.__file__,
            max_return_after_deadline_s=TAIL_SECONDS + MARGIN_SECONDS,
            max_elapsed_s=STARTUP_ALLOWANCE_SECONDS + GRACE_SECONDS)


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_a_helper_that_loads_sitecustomize_loses_the_break_and_fails(tmp_path):
    """Mutant (2026-10-06 root cause): with the repository sitecustomize loaded, every child is
    created with CREATE_NO_WINDOW, so the PowerShell child sits on its own console and the
    runner's Ctrl+Break never reaches it. The outcome still reads "cooperative"; only the
    BREAK marker exposes it, and the check must fail."""
    rc, text, outcome, events = run_break_case(
        tmp_path, runner.__file__, allowance=STARTUP_ALLOWANCE_SECONDS, tail=TAIL_SECONDS,
        grace=GRACE_SECONDS, caller_stdin_open=True, mutant="sitecustomize")
    assert outcome is not None and outcome["sitecustomize_loaded"] is True and outcome["popen_silenced"] is True, text
    assert outcome["cooperative"] is True and "BREAK" not in dict(events), (events, outcome)
    with pytest.raises(AssertionError, match="never reached the stub"):
        assert_cooperative_break(
            rc, text, outcome, events, runner_file=runner.__file__,
            max_return_after_deadline_s=TAIL_SECONDS + MARGIN_SECONDS,
            max_elapsed_s=STARTUP_ALLOWANCE_SECONDS + GRACE_SECONDS)
