from weather.operations.windows_process_lifetime import (
    summarize_process_lifetime,
)


def _record(
    pid,
    creation_time,
    *,
    working_set=100,
    commit=80,
):
    return {
        "pid": pid,
        "creation_time_100ns": creation_time,
        "terminal_creation_time_100ns": creation_time,
        "creation_time_identity_match": True,
        "exit_time_100ns": creation_time + 10,
        "image_path": f"C:\\process-{pid}.exe",
        "job_membership_verified": True,
        "job_membership_observations": 1,
        "process_exited": True,
        "terminal_query_succeeded": True,
        "peak_working_set_bytes": working_set,
        "peak_commit_bytes": commit,
    }


def _accounting(*, total=2, active=0, terminated=0):
    return {
        "total_processes": total,
        "active_processes": active,
        "terminated_processes": terminated,
    }


def _summarize(records, *, accounting=None, failures=(), retained=None, closed=None):
    retained = len(records) if retained is None else retained
    closed = retained if closed is None else closed
    return summarize_process_lifetime(
        records,
        failures,
        accounting or _accounting(total=len(records)),
        retained_handle_count=retained,
        closed_handle_count=closed,
    )


def test_summary_accepts_exact_terminal_process_tree_and_sums_lifetime_peaks():
    payload = _summarize([
        _record(101, 1000, working_set=120, commit=90),
        _record(102, 2000, working_set=140, commit=110),
    ])

    assert payload["status"] == "PASS"
    assert payload["tracked_process_count"] == 2
    assert payload["lifetime_working_set_upper_bound_bytes"] == 260
    assert payload["lifetime_commit_upper_bound_bytes"] == 200
    assert all(payload["checks"].values())


def test_summary_fails_when_job_lifetime_process_was_missed():
    payload = _summarize(
        [_record(101, 1000)],
        accounting=_accounting(total=2),
    )

    assert payload["status"] == "FAIL"
    assert payload["checks"]["every_job_process_observed"] is False


def test_summary_fails_without_terminal_peak_capture():
    row = _record(101, 1000)
    row.update({
        "process_exited": False,
        "terminal_query_succeeded": False,
        "exit_time_100ns": 0,
        "peak_working_set_bytes": 0,
        "peak_commit_bytes": 0,
    })
    payload = _summarize([row])

    assert payload["status"] == "FAIL"
    assert payload["checks"]["all_processes_signaled_exit"] is False
    assert payload["checks"]["all_terminal_queries_succeeded"] is False
    assert payload["checks"]["all_lifetime_peaks_positive"] is False


def test_summary_fails_duplicate_process_instance_or_identity_change():
    duplicate = _summarize([
        _record(101, 1000),
        _record(101, 1000),
    ])
    changed = _record(102, 2000)
    changed["creation_time_identity_match"] = False
    identity_changed = _summarize([changed])

    assert duplicate["status"] == "FAIL"
    assert duplicate["checks"]["unique_process_instances"] is False
    assert identity_changed["status"] == "FAIL"
    assert identity_changed["checks"]["all_process_identities_stable"] is False


def test_summary_distinguishes_sequential_pid_reuse_by_creation_time():
    payload = _summarize([
        _record(101, 1000),
        _record(101, 2000),
    ])

    assert payload["status"] == "PASS"
    assert payload["checks"]["unique_process_instances"] is True


def test_summary_fails_capture_error_limit_termination_or_handle_leak():
    capture_error = _summarize(
        [_record(101, 1000)],
        failures=[{"kind": "open_process_failed", "pid": 102}],
    )
    limit_termination = _summarize(
        [_record(101, 1000)],
        accounting=_accounting(total=1, terminated=1),
    )
    leaked_handle = _summarize(
        [_record(101, 1000)],
        retained=1,
        closed=0,
    )

    assert capture_error["status"] == "FAIL"
    assert capture_error["checks"]["no_unexplained_capture_failures"] is False
    assert limit_termination["status"] == "FAIL"
    assert (
        limit_termination["checks"]["no_job_limit_terminated_processes"]
        is False
    )
    assert leaked_handle["status"] == "FAIL"
    assert leaked_handle["checks"]["all_retained_handles_closed"] is False


def test_summary_tolerates_benign_identity_query_race_when_accounting_is_exact():
    """A process exiting between handle-open and query is an observation race.

    It cost the settlement chain 4 days in August 2026: one such failure in
    3,402 capture calls hard-stopped a step whose other 18 checks all passed.
    """

    payload = _summarize(
        [_record(101, 1000)],
        failures=[{
            "kind": "process_identity_query_failed",
            "pid": 102,
            "detail": "OSError: [Errno 31] a device attached is not functioning",
        }],
    )

    assert payload["status"] == "PASS"
    assert payload["checks"]["no_unexplained_capture_failures"] is True
    assert payload["benign_capture_failure_count"] == 1
    assert payload["unexplained_capture_failure_count"] == 0
    # The failure is still reported -- tolerated, never hidden.
    assert len(payload["capture_failures"]) == 1


def test_benign_race_does_not_excuse_an_unobserved_job_process():
    """The whole safety argument: containment is proven independently.

    If the skipped process were still Job-bound, accounting would disagree with
    the observed rows and the summary must FAIL even though the only capture
    failure is a benign one.
    """

    payload = _summarize(
        [_record(101, 1000)],
        accounting=_accounting(total=2),
        failures=[{"kind": "process_identity_query_failed", "pid": 102}],
    )

    assert payload["status"] == "FAIL"
    assert payload["checks"]["every_job_process_observed"] is False
    assert payload["checks"]["no_unexplained_capture_failures"] is True


def test_benign_race_does_not_excuse_a_live_process_or_a_job_kill():
    still_running = _summarize(
        [_record(101, 1000)],
        accounting=_accounting(total=1, active=1),
        failures=[{"kind": "process_identity_query_failed", "pid": 102}],
    )
    job_killed = _summarize(
        [_record(101, 1000)],
        accounting=_accounting(total=1, terminated=1),
        failures=[{"kind": "process_identity_query_failed", "pid": 102}],
    )

    assert still_running["status"] == "FAIL"
    assert still_running["checks"]["job_quiesced"] is False
    assert job_killed["status"] == "FAIL"
    assert job_killed["checks"]["no_job_limit_terminated_processes"] is False


def test_process_not_in_job_is_never_benign():
    """Containment evidence must stay fatal -- it is the point of the tracker."""

    payload = _summarize(
        [_record(101, 1000)],
        failures=[{"kind": "process_not_in_job", "pid": 102}],
    )

    assert payload["status"] == "FAIL"
    assert payload["checks"]["no_unexplained_capture_failures"] is False
    assert payload["unexplained_capture_failure_count"] == 1
