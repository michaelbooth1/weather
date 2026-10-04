import csv
import json
from datetime import date, datetime, timezone

import pytest

from weather.operations import replay_status_backfill as replay
from weather.operations import stage_a_settlement as stage
from weather.backtesting import settlement_ledger as ledger
from tests.market.test_market_day_labels import _write_toronto_tape, _resolved_event


SLUG = "highest-temperature-in-toronto-on-may-27-2026"


def test_replay_warm_path_is_identical_and_never_parses_evidence(tmp_path, monkeypatch):
    folder = tmp_path / SLUG
    folder.mkdir()
    (folder / "snapshots.jsonl").write_text(json.dumps({"snapshot_id": "s", "event_slug": SLUG}) + "\n")
    args = dict(as_of_date=date(2026, 5, 28))
    assert replay.repair_folder(folder, **args)["action"] == "written"
    full = replay.repair_folder(folder, incremental=False, **args)
    original = replay.folder_evidence
    monkeypatch.setattr(replay, "folder_evidence", lambda *_: pytest.fail("parsed unchanged evidence"))
    assert replay.repair_folder(folder, **args) == full
    monkeypatch.setattr(replay, "folder_evidence", original)
    with (folder / "snapshots.jsonl").open("a") as handle:
        handle.write(json.dumps({"snapshot_id": "s2", "event_slug": SLUG}) + "\n")
    changed = replay.repair_folder(folder, **args)
    assert changed["action"] == "written"
    assert changed["snapshot_count"] == 2
    assert replay.build_backfill_payload(snapshots_root=tmp_path, as_of="2026-06-20")["folders"] == []
    assert len(replay.build_backfill_payload(snapshots_root=tmp_path, as_of="2026-06-20", recent_days=0)["folders"]) == 1


def test_csv_byte_count_preserves_multiline_and_unterminated_rows(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_bytes(b"a,b\r\n1,2\r\n3,4")
    assert replay._csv_row_count(path) == 2
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([["a", "b"], ["multi\nline", "x"], ["ordinary", "y"]])
    assert replay._csv_row_count(path) == 2


def test_labels_skip_old_load_summary_once_and_reuse_terminal_venue_evidence(tmp_path, monkeypatch):
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 28, tzinfo=timezone.utc)

    monkeypatch.setattr(ledger, "datetime", FrozenClock)
    monkeypatch.setattr(stage, "datetime", FrozenClock)
    folder = tmp_path / SLUG
    folder.mkdir()
    _write_toronto_tape(folder)
    summary = tmp_path / "daily.csv"
    summary.write_text("local_date,max_temp_c,max_temp_bucket_c,row_count\n2026-05-27,25,25,24\n")
    kwargs = dict(daily_summary_path=summary, labels_csv=tmp_path / "labels.csv",
                  ledger_root=tmp_path / "ledger", reconcile_polymarket=True)
    calls = []
    monkeypatch.setattr(ledger, "fetch_gamma_event", lambda *_: calls.append(1) or _resolved_event("25 C"))
    full = ledger.finalize_folders([folder], **kwargs)
    assert calls == [1]
    recent = stage.finalize_incremental([folder], as_of_date=date(2026, 5, 28), **kwargs)
    assert calls == [1]
    assert recent == full
    for key in ("settlement_bucket", "quality_grade", "promotion_countable", "polymarket_reconciliation",
                "material_coverage_grade", "reconciliation_status"):
        assert recent[0][key] == full[0][key]
    monkeypatch.setattr(ledger, "_finalize_folder_with_retry", lambda *_args, **_kwargs: pytest.fail("old labeled folder finalized"))
    assert stage.finalize_incremental([folder], as_of_date=date(2026, 6, 20), **kwargs)[0]["event_slug"] == SLUG


def test_recent_and_unlabeled_folders_share_summary_read(tmp_path, monkeypatch):
    folders = [tmp_path / SLUG, tmp_path / SLUG.replace("27", "28")]
    for folder in folders:
        folder.mkdir()
    calls, seen = [], []
    monkeypatch.setattr(ledger, "load_daily_summary", lambda path: calls.append(path) or {})

    def finalize(folder, **kwargs):
        seen.append(kwargs["daily_index"])
        return {"event_slug": folder.name, "market_id": "toronto"}

    monkeypatch.setattr(ledger, "_finalize_folder_with_retry", finalize)
    stage.finalize_incremental(folders, as_of_date=date(2026, 6, 20),
                              daily_summary_path=tmp_path / "daily.csv",
                              labels_csv=tmp_path / "labels.csv", ledger_root=tmp_path / "ledger")
    assert len(calls) == 1
    assert len(seen) == 2 and seen[0] is seen[1]


def test_retained_venue_winner_cannot_hide_changed_local_bucket():
    prior = {"polymarket_reconciliation": ledger.build_reconciliation("fixture", 25, {},
                                                                     event=_resolved_event("25 C"))}
    event = stage.retained_resolved_event(prior)
    assert ledger.build_reconciliation("fixture", 24, {}, event=event)["status"] == "mismatch"
    prior["polymarket_reconciliation"]["event_closed"] = False
    assert stage.retained_resolved_event(prior) is None
