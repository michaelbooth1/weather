import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.io import read_csv_tail_rows_with_diagnostics
from weather.market.market_latest_inputs import load_latest_market_inputs
from weather.market.market_microstructure_features import clob_feature_rows_for_folder


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _tail_window_for_last_rows(path, row_count):
    lines = path.read_bytes().splitlines(keepends=True)
    # Include the newline immediately before the requested rows. The bounded
    # reader discards that boundary fragment, then starts on a complete row.
    return sum(len(line) for line in lines[-row_count:]) + 1


def _iso(value):
    return value.isoformat()


def _snapshot(snapshot_id, captured_at, filler=""):
    return {
        "snapshot_id": snapshot_id,
        "captured_at_utc": _iso(captured_at),
        "event_slug": "event",
        "market_id": "atlanta",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value_c": "80",
        "bin_value_hi": "81",
        "model_probability": "0.7",
        "market_yes": "0.5",
        "filler": filler,
    }


def _source(snapshot_id, captured_at, filler=""):
    return {
        "snapshot_id": snapshot_id,
        "captured_at_utc": _iso(captured_at),
        "source": "wu_current",
        "ok": "true",
        "status": "fresh",
        "stale": "false",
        "filler": filler,
    }


def _token(captured_at, token="token-80", filler=""):
    return {
        "captured_at_utc": _iso(captured_at),
        "market_id": "atlanta",
        "condition_id": "condition-80",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "outcome": "yes",
        "clob_token_id": token,
        "active": "true",
        "closed": "false",
        "filler": filler,
    }


def _book(captured_at, midpoint, filler=""):
    midpoint = float(midpoint)
    return {
        "captured_at_utc": _iso(captured_at),
        "event_slug": "event",
        "market_id": "atlanta",
        "condition_id": "condition-80",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "outcome": "yes",
        "clob_token_id": "token-80",
        "best_bid": str(midpoint - 0.01),
        "best_ask": str(midpoint + 0.01),
        "midpoint": str(midpoint),
        "spread": "0.02",
        "bid_depth_1pct": "10",
        "ask_depth_1pct": "12",
        "bid_depth_5pct": "20",
        "ask_depth_5pct": "22",
        "bid_depth_all": "30",
        "ask_depth_all": "32",
        "imbalance_1pct": "-0.09",
        "imbalance_5pct": "-0.04",
        "min_order_size": "1",
        "tick_size": "0.001",
        "filler": filler,
    }


def _price(captured_at, price, filler=""):
    return {
        "captured_at_utc": _iso(captured_at),
        "event_slug": "event",
        "market_id": "atlanta",
        "condition_id": "condition-80",
        "range_label": "80-81 F",
        "outcome": "yes",
        "clob_token_id": "token-80",
        "point_time_utc": _iso(captured_at),
        "price": str(price),
        "filler": filler,
    }


def _ws_event(captured_at, price, filler=""):
    return {
        "received_at_utc": _iso(captured_at),
        "event_slug": "event",
        "market_id": "atlanta",
        "event_type": "price_change",
        "asset_id": "token-80",
        "price": str(price),
        "side": "buy",
        "raw_sha1": f"sha-{captured_at.timestamp()}",
        "filler": filler,
    }


def _write_minimal_current_inputs(folder, snapshot_time, books):
    _write_csv(folder / "snapshots_long.csv", [
        _snapshot("prior", snapshot_time - timedelta(minutes=1)),
        _snapshot("latest", snapshot_time),
    ])
    _write_csv(folder / "source_status_long.csv", [
        _source("prior", snapshot_time - timedelta(minutes=1)),
        _source("latest", snapshot_time),
    ])
    _write_csv(folder / "clob_tokens.csv", [
        _token(snapshot_time - timedelta(seconds=30)),
        _token(snapshot_time + timedelta(seconds=5)),
    ])
    _write_csv(folder / "order_books_summary.csv", books)


class _CountingBinaryFile:
    def __init__(self, handle, counter):
        self._handle = handle
        self._counter = counter

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._handle.close()

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def read(self, *args, **kwargs):
        value = self._handle.read(*args, **kwargs)
        self._counter[0] += len(value)
        return value

    def readline(self, *args, **kwargs):
        value = self._handle.readline(*args, **kwargs)
        self._counter[0] += len(value)
        return value


def test_csv_tail_reader_seeks_past_large_prefix(monkeypatch, tmp_path):
    path = tmp_path / "large.csv"
    rows = [
        {"batch": str(index), "value": "x" * 200}
        for index in range(20_000)
    ]
    _write_csv(path, rows)
    file_size = path.stat().st_size
    original_open = Path.open
    bytes_read = [0]

    def tracked_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self == path and args and args[0] == "rb":
            return _CountingBinaryFile(handle, bytes_read)
        return handle

    monkeypatch.setattr(Path, "open", tracked_open)
    tail, diagnostics = read_csv_tail_rows_with_diagnostics(path, max_bytes=4096)

    assert file_size > 4_000_000
    assert diagnostics["status"] == "ok"
    assert diagnostics["reached_start"] is False
    assert diagnostics["scanned_bytes"] <= 4096
    assert bytes_read[0] < 8192
    assert diagnostics["read_bytes"] == bytes_read[0]
    assert tail[-1]["batch"] == "19999"


def test_csv_tail_reader_rejects_concurrent_file_change(monkeypatch, tmp_path):
    path = tmp_path / "changing.csv"
    _write_csv(path, [
        {"batch": "prior", "value": "one"},
        {"batch": "latest", "value": "two"},
    ])
    original_open = Path.open

    class MutatingBinaryFile:
        def __init__(self, handle):
            self._handle = handle
            self._mutated = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self._handle.close()

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def readline(self, *args, **kwargs):
            return self._handle.readline(*args, **kwargs)

        def read(self, *args, **kwargs):
            value = self._handle.read(*args, **kwargs)
            requested = args[0] if args else -1
            if not self._mutated and requested != 1:
                self._mutated = True
                with original_open(path, "ab") as writer:
                    writer.write(b"concurrent,append\n")
            return value

    def mutating_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self == path and args and args[0] == "rb":
            return MutatingBinaryFile(handle)
        return handle

    monkeypatch.setattr(Path, "open", mutating_open)
    rows, diagnostics = read_csv_tail_rows_with_diagnostics(path, max_bytes=4096)

    assert rows == []
    assert diagnostics["status"] == "concurrent_modification"
    assert diagnostics["stable_during_read"] is False


def test_latest_projection_matches_full_reference_without_reading_large_prefix(monkeypatch, tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    filler = "x" * 120
    old_count = 5_000
    snapshots = [
        _snapshot(
            f"old-{index}",
            snapshot_time - timedelta(minutes=old_count - index + 10),
            filler,
        )
        for index in range(old_count)
    ]
    snapshots.extend([
        _snapshot("prior", snapshot_time - timedelta(minutes=1), filler),
        _snapshot("latest", snapshot_time, filler),
    ])
    sources = [
        _source(
            f"old-{index}",
            snapshot_time - timedelta(minutes=old_count - index + 10),
            filler,
        )
        for index in range(old_count)
    ]
    sources.extend([
        _source("prior", snapshot_time - timedelta(minutes=1), filler),
        _source("latest", snapshot_time, filler),
    ])
    tokens = [
        _token(
            snapshot_time - timedelta(minutes=old_count - index + 10),
            filler=filler,
        )
        for index in range(old_count)
    ]
    tokens.extend([
        _token(snapshot_time - timedelta(seconds=30), filler=filler),
        _token(snapshot_time + timedelta(seconds=5), filler=filler),
    ])
    books = [
        _book(
            snapshot_time - timedelta(seconds=(old_count - index) * 60 + 1_000),
            0.4,
            filler,
        )
        for index in range(old_count)
    ]
    books.extend([
        _book(snapshot_time - timedelta(seconds=400), 0.4, filler),
        _book(snapshot_time - timedelta(seconds=350), 0.4, filler),
        _book(snapshot_time - timedelta(seconds=80), 0.4, filler),
        _book(snapshot_time - timedelta(seconds=40), 0.5, filler),
        _book(snapshot_time - timedelta(seconds=10), 0.5, filler),
        _book(snapshot_time + timedelta(seconds=5), 0.51, filler),
    ])
    _write_csv(folder / "snapshots_long.csv", snapshots)
    _write_csv(folder / "source_status_long.csv", sources)
    _write_csv(folder / "clob_tokens.csv", tokens)
    _write_csv(folder / "order_books_summary.csv", books)

    tracked_paths = {
        folder / "snapshots_long.csv",
        folder / "source_status_long.csv",
        folder / "clob_tokens.csv",
        folder / "order_books_summary.csv",
    }
    counters = {path: [0] for path in tracked_paths}
    original_open = Path.open

    def tracked_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if self in counters and "b" in mode:
            return _CountingBinaryFile(handle, counters[self])
        return handle

    monkeypatch.setattr(Path, "open", tracked_open)

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        max_age_seconds=180,
        latest_group_max_scan_bytes=2048,
        book_history_max_scan_bytes=4096,
        enrichment_history_max_scan_bytes=1024,
    )
    projection_read_bytes = sum(counter[0] for counter in counters.values())
    reference = [
        row
        for row in clob_feature_rows_for_folder(folder, max_age_seconds=180, market_id="atlanta")
        if row.get("snapshot_id") == "latest"
    ]

    assert projection["diagnostics"]["projection"]["status"] == "PASS"
    assert projection["snapshot_rows"][0]["snapshot_id"] == "latest"
    assert projection["source_rows"][0]["snapshot_id"] == "latest"
    assert projection["book_rows"][0]["captured_at_utc"] == _iso(snapshot_time + timedelta(seconds=5))
    assert projection["clob_feature_rows"] == reference
    assert projection["clob_feature_rows"][0]["clob_midpoint_stickiness_seconds"] == 30.0
    assert projection["diagnostics"]["snapshots"]["file_size_bytes"] > 750_000
    assert projection["diagnostics"]["snapshots"]["scanned_bytes"] <= 2048
    assert projection["diagnostics"]["order_books"]["file_size_bytes"] > 1_000_000
    assert projection["diagnostics"]["order_books"]["scanned_bytes"] <= 4096
    assert projection["diagnostics"]["total_scanned_bytes"] < 16_000
    assert projection_read_bytes < 24_000
    assert projection["diagnostics"]["total_read_bytes"] == projection_read_bytes


def test_latest_projection_fails_closed_when_stickiness_boundary_exceeds_scan(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    _write_csv(folder / "snapshots_long.csv", [
        _snapshot("prior", snapshot_time - timedelta(minutes=1)),
        _snapshot("latest", snapshot_time),
    ])
    _write_csv(folder / "source_status_long.csv", [
        _source("prior", snapshot_time - timedelta(minutes=1)),
        _source("latest", snapshot_time),
    ])
    _write_csv(folder / "clob_tokens.csv", [
        _token(snapshot_time - timedelta(seconds=30)),
        _token(snapshot_time + timedelta(seconds=5)),
    ])
    _write_csv(folder / "order_books_summary.csv", [
        _book(snapshot_time - timedelta(seconds=1000 - index * 10), 0.5, "x" * 80)
        for index in range(100)
    ])

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        book_history_max_scan_bytes=16_000,
    )

    assert projection["clob_feature_rows"] == []
    assert projection["diagnostics"]["projection"]["status"] == "BLOCK"
    assert projection["diagnostics"]["order_books"]["status"] == "scan_limit_exhausted"
    assert "stickiness" in projection["diagnostics"]["order_books"]["error"]


def test_latest_projection_rejects_incomplete_csv_tail(tmp_path):
    folder = tmp_path / "event"
    folder.mkdir()
    (folder / "snapshots_long.csv").write_bytes(
        b"snapshot_id,captured_at_utc\nlatest,2026-07-15T20:00:00+00:00"
    )

    projection = load_latest_market_inputs(folder, market_id="atlanta")

    assert projection["snapshot_rows"] == []
    assert projection["diagnostics"]["snapshots"]["status"] == "incomplete_tail"
    assert projection["diagnostics"]["projection"]["status"] == "BLOCK"


def test_latest_projection_rejects_structurally_malformed_csv_suffix(tmp_path):
    folder = tmp_path / "event"
    folder.mkdir()
    (folder / "snapshots_long.csv").write_bytes(
        b"snapshot_id,captured_at_utc\n"
        b"latest,2026-07-15T20:00:00+00:00,unexpected\n"
    )

    projection = load_latest_market_inputs(folder, market_id="atlanta")

    assert projection["snapshot_rows"] == []
    assert projection["diagnostics"]["snapshots"]["status"] == "malformed_csv"
    assert projection["diagnostics"]["projection"]["status"] == "BLOCK"


def test_latest_projection_rejects_malformed_optional_jsonl_evidence(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    _write_minimal_current_inputs(folder, snapshot_time, [
        _book(snapshot_time - timedelta(seconds=400), 0.4),
        _book(snapshot_time - timedelta(seconds=310), 0.4),
        _book(snapshot_time - timedelta(seconds=70), 0.48),
        _book(snapshot_time - timedelta(seconds=40), 0.5),
        _book(snapshot_time - timedelta(seconds=10), 0.5),
        _book(snapshot_time + timedelta(seconds=5), 0.51),
    ])
    (folder / "market_ws.jsonl").write_text('{"payload":\n', encoding="utf-8")

    projection = load_latest_market_inputs(folder, market_id="atlanta")

    assert projection["clob_feature_rows"] == []
    assert projection["diagnostics"]["market_ws_jsonl"]["status"] == "malformed_jsonl"
    assert projection["diagnostics"]["projection"]["status"] == "BLOCK"


def test_feature_projection_matches_reference_at_exact_history_boundaries(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    prefix = [
        _book(snapshot_time - timedelta(seconds=1_000 - index * 10), 0.35, "x" * 80)
        for index in range(50)
    ]
    books = [
        *prefix,
        _book(snapshot_time - timedelta(seconds=310), 0.4),
        _book(snapshot_time - timedelta(seconds=70), 0.48),
        _book(snapshot_time - timedelta(seconds=40), 0.5),
        _book(snapshot_time - timedelta(seconds=10), 0.5),
        _book(snapshot_time + timedelta(seconds=5), 0.51),
    ]
    _write_minimal_current_inputs(folder, snapshot_time, books)
    book_window = _tail_window_for_last_rows(folder / "order_books_summary.csv", 5)

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        book_history_max_scan_bytes=book_window,
    )
    reference = [
        row
        for row in clob_feature_rows_for_folder(folder, market_id="atlanta")
        if row.get("snapshot_id") == "latest"
    ]

    assert projection["diagnostics"]["projection"]["status"] == "PASS"
    assert projection["diagnostics"]["order_books"]["reached_start"] is False
    assert projection["clob_feature_rows"] == reference
    feature = projection["clob_feature_rows"][0]
    assert feature["clob_midpoint_change_60s"] == pytest.approx(0.02)
    assert feature["clob_midpoint_change_300s"] == pytest.approx(0.1)
    assert feature["clob_midpoint_stickiness_seconds"] == 30.0


def test_feature_projection_fails_when_suffix_cannot_prove_300_second_horizon(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    prefix = [
        _book(snapshot_time - timedelta(seconds=1_000 - index * 10), 0.35, "x" * 80)
        for index in range(50)
    ]
    # The omitted t-400 point is still within the reference transform's
    # 90-second tolerance around the t-310 target. The bounded suffix begins
    # at t-309, so it cannot prove whether that omitted point exists.
    books = [
        *prefix,
        _book(snapshot_time - timedelta(seconds=400), 0.4),
        _book(snapshot_time - timedelta(seconds=309), 0.4),
        _book(snapshot_time - timedelta(seconds=70), 0.48),
        _book(snapshot_time - timedelta(seconds=40), 0.5),
        _book(snapshot_time - timedelta(seconds=10), 0.5),
        _book(snapshot_time + timedelta(seconds=5), 0.51),
    ]
    _write_minimal_current_inputs(folder, snapshot_time, books)
    book_window = _tail_window_for_last_rows(folder / "order_books_summary.csv", 5)

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        book_history_max_scan_bytes=book_window,
    )

    assert projection["clob_feature_rows"] == []
    assert projection["diagnostics"]["order_books"]["status"] == "scan_limit_exhausted"
    assert "300-second feature window" in projection["diagnostics"]["order_books"]["error"]
    assert projection["diagnostics"]["projection"]["status"] == "BLOCK"


def test_stale_book_projection_matches_reference_without_unneeded_history(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    prefix = [
        _book(snapshot_time - timedelta(seconds=2_000 - index * 10), 0.4, "x" * 80)
        for index in range(50)
    ]
    books = [
        *prefix,
        _book(snapshot_time - timedelta(seconds=181), 0.5),
        _book(snapshot_time + timedelta(seconds=5), 0.51),
    ]
    _write_minimal_current_inputs(folder, snapshot_time, books)
    book_window = _tail_window_for_last_rows(folder / "order_books_summary.csv", 2)

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        max_age_seconds=180,
        book_history_max_scan_bytes=book_window,
    )
    reference = [
        row
        for row in clob_feature_rows_for_folder(
            folder,
            max_age_seconds=180,
            market_id="atlanta",
        )
        if row.get("snapshot_id") == "latest"
    ]

    assert projection["diagnostics"]["projection"]["status"] == "PASS"
    assert projection["clob_feature_rows"] == reference
    assert projection["clob_feature_rows"][0]["clob_feature_available"] == 0.0
    assert projection["clob_feature_rows"][0]["clob_book_age_seconds"] == 181.0


def test_enrichment_projection_matches_reference_at_count_and_change_horizons(tmp_path):
    folder = tmp_path / "event"
    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    books = [
        *[
            _book(snapshot_time - timedelta(seconds=2_000 - index * 10), 0.35, "x" * 80)
            for index in range(50)
        ],
        _book(snapshot_time - timedelta(seconds=310), 0.4),
        _book(snapshot_time - timedelta(seconds=70), 0.48),
        _book(snapshot_time - timedelta(seconds=40), 0.5),
        _book(snapshot_time - timedelta(seconds=10), 0.5),
        _book(snapshot_time + timedelta(seconds=5), 0.51),
    ]
    _write_minimal_current_inputs(folder, snapshot_time, books)
    filler = "x" * 120
    price_rows = [
        *[
            _price(
                snapshot_time - timedelta(seconds=(100 - index) * 60 + 1_000),
                0.3,
                filler,
            )
            for index in range(100)
        ],
        _price(snapshot_time - timedelta(seconds=320), 0.38),
        _price(snapshot_time - timedelta(seconds=80), 0.41),
        _price(snapshot_time - timedelta(seconds=20), 0.42),
    ]
    ws_rows = [
        *[
            _ws_event(
                snapshot_time - timedelta(seconds=(100 - index) * 60 + 1_000),
                0.3,
                filler,
            )
            for index in range(100)
        ],
        _ws_event(snapshot_time - timedelta(seconds=300), 0.35),
        _ws_event(snapshot_time - timedelta(seconds=70), 0.4),
        _ws_event(snapshot_time - timedelta(seconds=10), 0.45),
    ]
    _write_csv(folder / "price_history.csv", price_rows)
    _write_csv(folder / "market_ws_events.csv", ws_rows)
    enrichment_window = max(
        _tail_window_for_last_rows(folder / "price_history.csv", 3),
        _tail_window_for_last_rows(folder / "market_ws_events.csv", 3),
    )

    projection = load_latest_market_inputs(
        folder,
        market_id="atlanta",
        book_history_max_scan_bytes=_tail_window_for_last_rows(
            folder / "order_books_summary.csv",
            5,
        ),
        enrichment_history_max_scan_bytes=enrichment_window,
    )
    reference = [
        row
        for row in clob_feature_rows_for_folder(folder, market_id="atlanta")
        if row.get("snapshot_id") == "latest"
    ]

    assert projection["diagnostics"]["projection"]["status"] == "PASS"
    assert projection["diagnostics"]["price_history"]["reached_start"] is False
    assert projection["diagnostics"]["market_ws_events"]["reached_start"] is False
    assert projection["clob_feature_rows"] == reference
    feature = projection["clob_feature_rows"][0]
    assert feature["clob_price_history_points_300s"] == 2.0
    assert feature["clob_price_history_change_60s"] == pytest.approx(0.01)
    assert feature["clob_price_history_change_300s"] == pytest.approx(0.04)
    assert feature["clob_ws_event_count_60s"] == 1.0
    assert feature["clob_ws_event_count_300s"] == 3.0
    assert feature["clob_ws_price_change_60s"] == pytest.approx(0.05)


def test_discover_inputs_blocks_rows_when_bounded_projection_is_unproven(monkeypatch, tmp_path):
    from weather.market import taker_bot_cli

    snapshot_time = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
    unsafe_assembly_calls = []
    latest_inputs = {
        "snapshot_rows": [_snapshot("latest", snapshot_time)],
        "source_rows": [_source("latest", snapshot_time)],
        "token_rows": [_token(snapshot_time)],
        "book_rows": [_book(snapshot_time, 0.5)],
        "clob_feature_rows": [{"snapshot_id": "latest"}],
        "diagnostics": {
            "projection": {
                "ok": False,
                "status": "BLOCK",
                "detail": "order_books:scan_limit_exhausted",
            }
        },
    }
    monkeypatch.setattr(
        taker_bot_cli,
        "load_latest_market_inputs",
        lambda *args, **kwargs: latest_inputs,
    )
    monkeypatch.setattr(
        taker_bot_cli,
        "assemble_taker_inputs_for_market",
        lambda *args, **kwargs: unsafe_assembly_calls.append(True) or [{"unsafe": True}],
    )

    rows, summaries = taker_bot_cli.discover_inputs(
        "2026-07-15",
        markets="atlanta",
        snapshots_root=tmp_path,
        event_metadata_state={"required": False},
    )

    assert rows == []
    assert unsafe_assembly_calls == []
    assert summaries[0]["status"] == "BLOCK"
    assert summaries[0]["first_failing_gate"]["name"] == "bounded_latest_inputs"
    assert summaries[0]["latest_input_diagnostics"] == latest_inputs["diagnostics"]
