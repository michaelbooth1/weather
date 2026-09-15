"""Real Git crash states never gain retry, publication or downstream authority."""

import pytest

from test_qualification_merge_tree import merge_fixture
from test_qualification_merge_session import checked_fixture, prepare
from weather.operations.qualification import reconciliation, records


@pytest.mark.parametrize("state", ["prepared", "pending", "committed", "published"])
def test_actual_commit_dispositions_are_observations_only(merge_fixture, state):
    fixture, run = merge_fixture, merge_fixture[-1]
    checked = checked_fixture(fixture)
    baseline = prepare(fixture, checked)
    if state != "prepared":
        run("merge", "--no-commit", "--no-ff", fixture[3])
    if state in {"committed", "published"}:
        run("commit", "-qm", "fixture committed")
    if state == "published":
        run("update-ref", "refs/remotes/origin/master", run("rev-parse", "HEAD"))
    before = run("rev-parse", "HEAD")
    result = reconciliation.inspect_tree(checked, fixture[0], prepared_baseline=baseline)
    assert result["disposition"] == {
        "prepared": "UNCOMMITTED_REQUIRES_REVIEW", "pending": "UNCOMMITTED_REQUIRES_REVIEW",
        "committed": "MERGED_UNPUBLISHED_REQUIRES_REVIEW", "published": "PUBLISHED_CURRENT"}[state]
    assert result["historical_proof_upgraded"] is False and result["downstream_authorized"] is False
    assert run("rev-parse", "HEAD") == before


def test_terminal_config_refresh_does_not_allow_source_rewrite(merge_fixture):
    fixture, run = merge_fixture, merge_fixture[-1]
    checked = checked_fixture(fixture)
    baseline = prepare(fixture, checked)
    run("merge", "--no-commit", "--no-ff", fixture[3])
    run("commit", "-qm", "fixture committed")
    run("update-ref", "refs/remotes/origin/master", run("rev-parse", "HEAD"))
    (fixture[1] / "config/locations.json").write_bytes(b'{"later_refresh":true}\n')
    result = reconciliation.inspect_tree(checked, fixture[0], prepared_baseline=baseline)
    assert result["disposition"] == "PUBLISHED_CURRENT" and result["downstream_authorized"] is False
    (fixture[1] / "module.py").write_bytes(b"unreviewed = True\n")
    with pytest.raises(records.QualificationError, match="working source/config"):
        reconciliation.inspect_tree(checked, fixture[0], prepared_baseline=baseline)


def test_unreviewed_commit_cannot_be_reconciled_as_original_merge(merge_fixture):
    fixture, run = merge_fixture, merge_fixture[-1]
    checked = checked_fixture(fixture)
    baseline = prepare(fixture, checked)
    run("merge", "--no-commit", "--no-ff", fixture[3])
    (fixture[1] / "module.py").write_bytes(b"unreviewed = True\n")
    run("add", "module.py")
    run("commit", "-qm", "unreviewed resolution")
    with pytest.raises(records.QualificationError, match="committed merge differs"):
        reconciliation.inspect_tree(checked, fixture[0], prepared_baseline=baseline)


def test_complete_native_health_keeps_finite_float_telemetry_as_data(tmp_path):
    import hashlib
    import json
    value = {"capture": {"ok": True, "workers": [{"heartbeat_age_seconds": 1.125}]}, "execution_tape": None}
    ref = reconciliation.retain_health(tmp_path, value)
    raw = (tmp_path / ref["path"]).read_bytes()
    assert json.loads(raw) == value and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    assert records.decode(records.encode({"health": ref})) == {"health": ref}
    with pytest.raises(FileExistsError):
        reconciliation.retain_health(tmp_path, value)