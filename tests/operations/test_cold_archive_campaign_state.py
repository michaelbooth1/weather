"""Restart and accounting checks use small immutable metadata only."""
from collections import Counter
import json
import pytest
from weather.operations import cold_archive_campaign_state as state
from weather.operations import cold_archive_campaign as campaign
from weather.operations import production_cold_archive_stage as archive


class Adapter:
    def __init__(self, fail_after=None):
        self.calls, self.results, self.fail_after = Counter(), {}, fail_after
    def admit(self, phase, completed):
        pass
    def execute(self, phase, claim, completed):
        self.calls[phase] += 1
        result = {"phase": phase, "status": "PASS", "elapsed_seconds": 1, "deadline_seconds": 100}
        self.results[phase] = result
        if phase == self.fail_after:
            self.fail_after = None
            raise ConnectionError("connection lost after remote completion")
        return result
    def recover(self, phase, claim, completed):
        return self.results.get(phase)
    def verify(self, phase, evidence):
        assert evidence["phase"] == phase and evidence["status"] == "PASS"


@pytest.mark.parametrize("phase", ["stage", "upload", "reclaim", "backup"])
def test_disconnect_after_commit_never_repeats_mutation(tmp_path, phase):
    root = tmp_path / "batch"
    adapter = Adapter(fail_after=phase)
    with pytest.raises(ConnectionError):
        state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    completed = state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    assert tuple(completed) == state.PHASES
    assert adapter.calls == Counter({name: 1 for name in state.PHASES})
    # A fully completed batch performs no new action on another restart.
    state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    assert adapter.calls["reclaim"] == adapter.calls["upload"] == 1


def test_unknown_started_action_pauses_without_redispatch(tmp_path):
    root = tmp_path / "batch"
    adapter = Adapter(fail_after="upload")
    with pytest.raises(ConnectionError):
        state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    adapter.results.pop("upload")
    with pytest.raises(state.CampaignPaused, match="reconciliation"):
        state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    assert adapter.calls["upload"] == 1
    assert adapter.calls["reclaim"] == 0


def test_stop_is_at_phase_boundary_and_binding_cannot_change(tmp_path):
    root = tmp_path / "batch"
    adapter = Adapter()
    with pytest.raises(state.CampaignPaused, match="boundary"):
        state.BatchJournal(root, {"archive_id": "a1"}).run(
            adapter, stop_requested=lambda: adapter.calls["copy"] == 1)
    assert adapter.calls["stage"] == adapter.calls["copy"] == 1 and not adapter.calls["encrypt"]
    with pytest.raises(ValueError, match="binding"):
        state.BatchJournal(root, {"archive_id": "different"})
    state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    assert adapter.calls["copy"] == 1


def test_tampered_completion_is_rejected_before_any_new_action(tmp_path):
    root = tmp_path / "batch"
    adapter = Adapter()
    state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)
    path = root / "00-stage.done.json"
    value = json.loads(path.read_text())
    value["document"]["evidence"]["status"] = "corrupt"
    path.write_text(json.dumps(value))
    with pytest.raises(archive.ArchiveStageError, match="self-hash"):
        state.BatchJournal(root, {"archive_id": "a1"}).run(adapter)


def test_remaining_queue_excludes_entire_overlapping_chunk():
    def row(name):
        return dict(path=name, size_bytes=1, allocated_bytes=4096, device=1, file_id=1, mtime_ns=1)
    plan = archive._seal({"chunks": [
        {"chunk_id": "chunk-00000", "files": [row("a"), row("b")]},
        {"chunk_id": "chunk-00001", "files": [row("c")]}]}, "plan_hash")
    ready, isolated = state.remaining_chunks(plan, ["a"])
    assert [item["chunk_id"] for item in ready] == ["chunk-00001"]
    assert isolated[0]["remaining_allocated_bytes"] == 4096
    with pytest.raises(ValueError, match="outside"):
        state.remaining_chunks(plan, ["unknown"])


def test_three_real_large_batches_and_margin_are_required():
    phases = {phase: {"evidence": {"elapsed_seconds": 79, "deadline_seconds": 100}}
              for phase in state.PHASES}
    batch = {"logical_bytes": 1024 * archive.MIB, "phases": phases}
    assert state.qualification([batch] * 2) is False
    assert state.qualification([batch] * 3)
    phases["upload"]["evidence"]["elapsed_seconds"] = 81
    with pytest.raises(state.CampaignPaused, match="margin"):
        state.qualification([batch] * 3)


def test_window_end_is_exclusive_and_protected_gap_is_not_admitted():
    config = {"windows": [
        {"start": "2026-09-10T17:10:38Z", "end": "2026-09-10T22:00:00Z", "owner_exception": "dated"},
        {"start": "2026-09-11T04:30:00Z", "end": "2026-09-11T08:45:00Z", "owner_exception": ""}]}
    assert campaign.active_window(config, campaign.utc("2026-09-10T21:59:59Z"))["owner_exception"] == "dated"
    with pytest.raises(state.CampaignPaused, match="windows"):
        campaign.active_window(config, campaign.utc("2026-09-10T22:00:00Z"))


def test_eta_requires_real_qualification_and_counts_verified_source_bytes():
    assert state.remaining_estimate([], 1000) is None
    phases = {phase: {"elapsed_seconds": 1.0, "evidence": {
        "deadline_seconds": 300, "elapsed_seconds": 1.0}} for phase in state.PHASES}
    batches = [{"logical_bytes": 1024 * archive.MIB, "reclaimed_allocated_bytes": 1000,
                "phases": phases} for _ in range(3)]
    estimate = state.remaining_estimate(batches, 10000)
    assert estimate["active_seconds_estimate"] == 132
    assert estimate["remaining_source_bytes"] == 10000
    assert estimate["excludes_resource_and_schedule_waits"] is True
    batches[-1]["reclaimed_allocated_bytes"] = 0
    with pytest.raises(state.CampaignPaused, match="throughput"):
        state.remaining_estimate(batches, 10000)
