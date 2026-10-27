"""Incremental per-folder evidence for the Stage-A replay_status_backfill step.

Guards: the replay_status_backfill evidence cache must leave the step payload
byte-for-byte equivalent to the full recompute (2026-10-22 Stage-A overrun,
3212 s of a 3600 s child budget), reuse only folders whose read files are
unchanged, and fail to a full recompute on a corrupt or foreign-version cache.
"""
import csv
import json
import os
import shutil
from types import SimpleNamespace

import pytest

from weather.operations import replay_status_backfill as rsb
from weather.operations.daily_refresh_trading_steps import run_replay_status_backfill_step


AS_OF = "2026-06-17"
WITH_INPUTS = "highest-temperature-in-nyc-on-june-14-2026"
SNAPSHOT_ONLY = "highest-temperature-in-nyc-on-june-15-2026"
EMPTY = "highest-temperature-in-nyc-on-june-16-2026"
ACTIVE = "highest-temperature-in-nyc-on-june-20-2026"
OTHER_MARKET = "highest-temperature-in-atlanta-on-june-16-2026"


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _snapshot(slug, index=1):
    return {
        "snapshot_id": f"{slug}-snap-{index}",
        "captured_at_utc": "2026-06-14T18:00:00+00:00",
        "captured_at_local": "2026-06-14T14:00:00-04:00",
        "event_slug": slug,
    }


def _write_source_status(path):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["snapshot_id", "source", "ok", "stale", "status"])
        writer.writeheader()
        writer.writerow({"snapshot_id": "s", "source": "wu_current", "ok": "True", "stale": "False", "status": "fresh"})


def _make_folder(root, slug, *, replay=True, snapshots=True):
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    if snapshots:
        _write_jsonl(folder / "snapshots.jsonl", [_snapshot(slug)])
        _write_source_status(folder / "source_status_long.csv")
    if replay:
        _write_jsonl(folder / rsb.REPLAY_INPUTS_FILENAME, [{
            **_snapshot(slug),
            "schema_version": "toronto_replay_inputs_v0.1",
            "sources": {"wu_current": {"ok": True, "stale": False, "data": {}}},
        }])
    return folder


def _make_tree(root):
    root.mkdir(parents=True, exist_ok=True)
    _make_folder(root, WITH_INPUTS)
    _make_folder(root, SNAPSHOT_ONLY, replay=False)
    (root / EMPTY).mkdir()
    _make_folder(root, ACTIVE)
    _make_folder(root, OTHER_MARKET)
    return root


def _comparable(payload, root=None):
    text = json.dumps({k: v for k, v in payload.items() if k != "generated_at_utc"}, sort_keys=True)
    if root is not None:
        text = text.replace(json.dumps(str(root))[1:-1], "<ROOT>")
    return json.loads(text)


def _build(root, cache=None):
    return rsb.build_backfill_payload(snapshots_root=root, as_of=AS_OF, evidence_cache=cache)


def _incremental(root, cache_path):
    cache = rsb.EvidenceCache.load(cache_path)
    payload = _build(root, cache)
    cache.save(cache_path)
    return payload, cache


@pytest.fixture
def parse_log(monkeypatch):
    """Record every JSON/CSV parse folder_evidence and existing_status_summary make."""
    log = []

    def counting(name, function):
        def wrapper(path, *args, **kwargs):
            log.append((name, str(path)))
            return function(path, *args, **kwargs)
        return wrapper

    monkeypatch.setattr(rsb, "read_jsonl", counting("read_jsonl", rsb.read_jsonl))
    monkeypatch.setattr(rsb, "read_json", counting("read_json", rsb.read_json))
    monkeypatch.setattr(rsb, "_csv_row_count", counting("csv", rsb._csv_row_count))
    return log


def _parsed_folders(log):
    return {os.path.basename(os.path.dirname(path)) for _name, path in log}


def _primed(tmp_path):
    """A steady-state tree: one direct pass has written every repairable status."""
    root = _make_tree(tmp_path / "snapshots")
    _build(root)
    return root


def _bump_mtime(path):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


def test_cold_incremental_pass_equals_full_pass_including_writes(tmp_path):
    full_root = _make_tree(tmp_path / "a" / "snapshots")
    inc_root = tmp_path / "b" / "snapshots"
    shutil.copytree(full_root, inc_root)

    full = _build(full_root)
    incremental, cache = _incremental(inc_root, tmp_path / "b" / "cache.json")

    assert incremental["summary"]["written_folder_count"] == 3
    assert _comparable(incremental, inc_root) == _comparable(full, full_root)
    assert cache.stats()["load_status"] == "missing"
    assert cache.stats()["evidence_reused"] == 0


def test_warm_incremental_pass_equals_full_pass(tmp_path):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    _incremental(root, cache_path)

    warm, cache = _incremental(root, cache_path)

    assert _comparable(warm) == _comparable(_build(root))
    assert cache.stats()["evidence_reused"] == 5
    assert cache.stats()["status_reused"] == 3


def test_second_pass_parses_no_unchanged_folder(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    assert _parsed_folders(parse_log) == {WITH_INPUTS, SNAPSHOT_ONLY, EMPTY, ACTIVE, OTHER_MARKET}
    parse_log.clear()

    _payload, cache = _incremental(root, cache_path)

    assert parse_log == []
    assert cache.stats()["evidence_computed"] == 0
    assert cache.stats()["status_computed"] == 0


def test_changed_file_recomputes_only_that_folder(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    _write_jsonl(root / SNAPSHOT_ONLY / "snapshots.jsonl", [_snapshot(SNAPSHOT_ONLY, 1), _snapshot(SNAPSHOT_ONLY, 2)])
    parse_log.clear()

    payload, cache = _incremental(root, cache_path)

    assert _parsed_folders(parse_log) == {SNAPSHOT_ONLY}
    assert cache.stats()["evidence_computed"] == 1
    assert cache.stats()["status_computed"] == 0
    row = next(row for row in payload["folders"] if row["event_slug"] == SNAPSHOT_ONLY)
    assert row["snapshot_count"] == 2
    assert _comparable(payload) == _comparable(_build(root))


def test_same_size_rewrite_with_new_mtime_recomputes(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    _bump_mtime(root / WITH_INPUTS / "source_status_long.csv")
    parse_log.clear()

    _payload, cache = _incremental(root, cache_path)

    assert _parsed_folders(parse_log) == {WITH_INPUTS}
    assert cache.stats()["evidence_computed"] == 1


def test_status_file_change_recomputes_only_the_status_summary(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    summary_path = root / WITH_INPUTS / rsb.REPLAY_STATUS_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["folder_status"] = "evaluation_only"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    parse_log.clear()

    payload, cache = _incremental(root, cache_path)

    assert cache.stats()["status_computed"] == 1
    assert cache.stats()["evidence_computed"] == 0
    row = next(row for row in payload["folders"] if row["event_slug"] == WITH_INPUTS)
    assert row["training_ready"] is False
    assert row["training_ready_reason"] == "replay_status_evaluation_only"
    assert _comparable(payload) == _comparable(_build(root))


def test_new_folder_is_added(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    new_slug = "highest-temperature-in-nyc-on-june-13-2026"
    _make_folder(root, new_slug)
    parse_log.clear()

    payload, cache = _incremental(root, cache_path)

    assert new_slug in {row["event_slug"] for row in payload["folders"]}
    assert _parsed_folders(parse_log) == {new_slug}
    assert str(root / new_slug) in json.loads(cache_path.read_text(encoding="utf-8"))["entries"]
    assert cache.stats()["entry_count"] == 6
    assert next(row for row in payload["folders"] if row["event_slug"] == new_slug)["action"] == "written"
    # The pass wrote the new folder's status; the next one is read-only again.
    steady, _cache = _incremental(root, cache_path)
    assert _comparable(steady) == _comparable(_build(root))


def test_removed_folder_is_dropped(tmp_path):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    shutil.rmtree(root / OTHER_MARKET)

    payload, cache = _incremental(root, cache_path)

    assert OTHER_MARKET not in {row["event_slug"] for row in payload["folders"]}
    entries = json.loads(cache_path.read_text(encoding="utf-8"))["entries"]
    assert str(root / OTHER_MARKET) not in entries
    assert cache.stats()["dropped_entry_count"] == 1
    assert cache.stats()["entry_count"] == 4
    assert _comparable(payload) == _comparable(_build(root))


@pytest.mark.parametrize(
    "content, expected_status",
    [
        ("{not json", "corrupt"),
        ("", "corrupt"),
        (json.dumps([1, 2]), "corrupt"),
        (json.dumps({"format": "something_else", "version": 1, "entries": {}}), "corrupt"),
        (json.dumps({"format": rsb.EVIDENCE_CACHE_FORMAT, "version": 1, "entries": []}), "corrupt"),
        (json.dumps({"format": rsb.EVIDENCE_CACHE_FORMAT, "version": 1, "entries": {"x": 3}}), "corrupt"),
    ],
)
def test_corrupt_cache_gives_full_recompute(tmp_path, parse_log, content, expected_status):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    cache_path.write_text(content, encoding="utf-8")
    parse_log.clear()

    payload, cache = _incremental(root, cache_path)

    assert cache.stats()["load_status"] == expected_status
    assert cache.stats()["evidence_reused"] == 0
    assert cache.stats()["evidence_computed"] == 5
    assert _parsed_folders(parse_log) == {WITH_INPUTS, SNAPSHOT_ONLY, EMPTY, ACTIVE, OTHER_MARKET}
    assert _comparable(payload) == _comparable(_build(root))
    # The rewritten cache is valid again and serves the next pass.
    _again, warm = _incremental(root, cache_path)
    assert warm.stats()["evidence_computed"] == 0


@pytest.mark.parametrize("stored_version", [rsb.EVIDENCE_CACHE_VERSION + 1, str(rsb.EVIDENCE_CACHE_VERSION), None])
def test_foreign_version_in_file_gives_full_recompute(tmp_path, stored_version):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    document = json.loads(cache_path.read_text(encoding="utf-8"))
    document["version"] = stored_version
    cache_path.write_text(json.dumps(document), encoding="utf-8")

    _payload, cache = _incremental(root, cache_path)

    assert cache.stats()["load_status"] == "version_mismatch"
    assert cache.stats()["evidence_reused"] == 0


def test_code_version_bump_gives_full_recompute(tmp_path, monkeypatch, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    monkeypatch.setattr(rsb, "EVIDENCE_CACHE_VERSION", rsb.EVIDENCE_CACHE_VERSION + 1)
    parse_log.clear()

    payload, cache = _incremental(root, cache_path)

    assert cache.stats()["load_status"] == "version_mismatch"
    assert cache.stats()["evidence_computed"] == 5
    assert len(_parsed_folders(parse_log)) == 5
    assert json.loads(cache_path.read_text(encoding="utf-8"))["version"] == rsb.EVIDENCE_CACHE_VERSION
    assert _comparable(payload) == _comparable(_build(root))


def test_logic_key_mismatch_gives_full_recompute(tmp_path):
    root = _primed(tmp_path)
    cache_path = tmp_path / "cache.json"
    _incremental(root, cache_path)
    document = json.loads(cache_path.read_text(encoding="utf-8"))
    document["logic_key"] = "0" * 64
    cache_path.write_text(json.dumps(document), encoding="utf-8")

    _payload, cache = _incremental(root, cache_path)

    assert cache.stats()["load_status"] == "logic_mismatch"
    assert cache.stats()["evidence_reused"] == 0
    assert cache.stats()["evidence_computed"] == 5


def test_unresolvable_archived_input_is_not_cached_and_fails_like_the_direct_call(tmp_path):
    root = _primed(tmp_path)
    marker = root / EMPTY / ".cold_archive" / (rsb.RECONSTRUCTED_FILENAME + ".json")
    marker.parent.mkdir(parents=True)
    marker.write_text("{not a marker", encoding="utf-8")

    with pytest.raises(Exception) as direct:
        _build(root)
    with pytest.raises(Exception) as cached:
        _build(root, rsb.EvidenceCache.empty())

    assert type(cached.value) is type(direct.value)


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    root = _primed(tmp_path)
    cache_path = tmp_path / "out" / "cache.json"
    _incremental(root, cache_path)

    assert sorted(path.name for path in cache_path.parent.iterdir()) == ["cache.json"]
    document = json.loads(cache_path.read_text(encoding="utf-8"))
    assert document["format"] == rsb.EVIDENCE_CACHE_FORMAT
    assert document["version"] == rsb.EVIDENCE_CACHE_VERSION


def _step_args(tmp_path, root, **overrides):
    values = {
        "snapshots_root": str(root),
        "backtest_root": str(tmp_path / "backtest"),
        "folders": [],
        "as_of": AS_OF,
        "overwrite_replay_status": False,
        "reconstruct_missing_replay_inputs": False,
        "include_active_replay_status": False,
        "skip_replay_status_backfill": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _step_payload(result):
    with open(result["json_out"], encoding="utf-8") as handle:
        return json.load(handle)


def _output_text_without_timestamp(path):
    with open(path, encoding="utf-8") as handle:
        return [line for line in handle if "generated_at_utc" not in line and not line.startswith("Generated:")]


def test_step_incremental_and_forced_full_equal_the_direct_call(tmp_path, parse_log):
    root = _primed(tmp_path)
    cache_path = tmp_path / "backtest" / rsb.EVIDENCE_CACHE_FILENAME

    first = run_replay_status_backfill_step(_step_args(tmp_path, root))
    warm = run_replay_status_backfill_step(_step_args(tmp_path, root))
    parse_log.clear()
    forced = run_replay_status_backfill_step(_step_args(tmp_path, root, replay_backfill_full=True))
    direct = _build(root)

    assert first["evidence_mode"] == "incremental"
    assert warm["evidence_cache"]["evidence_computed"] == 0
    assert warm["evidence_cache_out"] == str(cache_path)
    assert forced["evidence_mode"] == "full"
    assert forced["evidence_cache"]["load_status"] == "forced_full"
    assert forced["evidence_cache"]["evidence_reused"] == 0
    assert len(_parsed_folders(parse_log)) == 5
    for result in (first, warm, forced):
        assert _comparable(_step_payload(result)) == _comparable(direct)
        assert result["summary"] == direct["summary"]
    direct_json, direct_report = rsb.write_outputs(
        direct, json_out=tmp_path / "direct" / "out.json", report_out=tmp_path / "direct" / "out.md"
    )
    assert _output_text_without_timestamp(warm["json_out"]) == _output_text_without_timestamp(direct_json)
    assert _output_text_without_timestamp(warm["report_out"]) == _output_text_without_timestamp(direct_report)
    # The forced pass re-seeds the cache for the next incremental pass.
    after = run_replay_status_backfill_step(_step_args(tmp_path, root))
    assert after["evidence_cache"]["evidence_computed"] == 0


def test_step_with_explicit_folders_keeps_the_direct_call_and_no_cache(tmp_path):
    root = _primed(tmp_path)

    result = run_replay_status_backfill_step(_step_args(tmp_path, root, folders=[str(root / WITH_INPUTS)]))

    assert result["evidence_mode"] == "direct"
    assert result["evidence_cache"] is None
    assert result["evidence_cache_out"] is None
    assert not (tmp_path / "backtest" / rsb.EVIDENCE_CACHE_FILENAME).exists()
    assert _step_payload(result)["summary"]["folder_count"] == 1


def test_daily_refresh_parser_accepts_replay_backfill_full():
    from weather.operations.daily_refresh import build_parser

    parser = build_parser()
    assert parser.parse_args(["run"]).replay_backfill_full is False
    assert parser.parse_args(["run", "--replay-backfill-full"]).replay_backfill_full is True
