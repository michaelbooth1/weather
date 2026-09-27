from types import SimpleNamespace
import csv
from datetime import datetime, timedelta, timezone
import json

import pytest

from weather.market import clob_capture_cache as cache
from weather.market.market_latest_inputs import _latest_time_group


def test_sparse_token_updates_drop_unchanged_tokens_in_existing_reader():
    old = "2026-08-01T00:00:00+00:00"
    new = "2026-08-01T00:01:00+00:00"
    day_open = [{"clob_token_id": token, "captured_at_utc": old} for token in ("a", "b")]
    sparse = [*day_open, {"clob_token_id": "a", "captured_at_utc": new}]
    selected = _latest_time_group(sparse, {"status": "ok", "reached_start": True})
    assert {row["clob_token_id"] for row in selected} == {"a"}
    complete = [*day_open, *[dict(row, captured_at_utc=new) for row in day_open]]
    selected = _latest_time_group(complete, {"status": "ok", "reached_start": True})
    assert {row["clob_token_id"] for row in selected} == {"a", "b"}


def test_gamma_cache_expiry_isolation_day_roll_and_failure(monkeypatch):
    cache._EVENTS.clear()
    clock, calls = [0.0], []
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class Client:
        config = SimpleNamespace(event_slug="fixture-day1", target_date="2026-08-01")

        def get_event(self):
            calls.append(self.config.event_slug)
            return {"slug": self.config.event_slug, "markets": [{"id": "one"}]}

    first = cache.capture_event(Client())
    first["markets"].clear()
    clock[0] = 599
    assert len(cache.capture_event(Client())["markets"]) == 1
    assert len(calls) == 1
    clock[0] = 600
    cache.capture_event(Client())
    assert len(calls) == 2
    tomorrow = Client()
    tomorrow.config = SimpleNamespace(event_slug="fixture-day2", target_date="2026-08-02")
    cache.capture_event(tomorrow)
    assert len(calls) == 3
    clock[0] = 1200
    monkeypatch.setattr(Client, "get_event", lambda self: (_ for _ in ()).throw(OSError("fixture outage")))
    with pytest.raises(OSError, match="fixture outage"):
        cache.capture_event(Client())


def test_price_history_appends_normal_poll_and_preserves_corrections(tmp_path, monkeypatch):
    from weather.market import market_microstructure_capture as capture

    path = tmp_path / "price_history.csv"
    row = {"market_id": "fixture", "clob_token_id": "a", "point_timestamp": "1", "price": "0.5"}
    capture._upsert_price_history_rows(path, [row])
    first = path.read_bytes()
    writes = []
    original = capture.write_csv_rows
    monkeypatch.setattr(capture, "write_csv_rows", lambda *a, **k: (writes.append(a[0]), original(*a, **k))[1])
    capture._upsert_price_history_rows(path, [row, dict(row, point_timestamp="2")])
    assert path.read_bytes().startswith(first)
    assert not writes
    unchanged = path.read_bytes(), path.stat().st_mtime_ns
    capture._upsert_price_history_rows(path, [row])
    assert (path.read_bytes(), path.stat().st_mtime_ns) == unchanged
    capture._upsert_price_history_rows(path, [dict(row, price="0.6")])
    assert writes == [path]
    with path.open(newline="", encoding="utf-8") as handle:
        assert [item["price"] for item in csv.DictReader(handle)] == ["0.6", "0.5"]


def test_features_append_parity_correction_and_interrupted_pair(tmp_path, monkeypatch):
    from weather.market import market_microstructure_features as features

    reference = tmp_path / "reference"
    reference.mkdir()
    rows = [{"market_id": "fixture", "snapshot_id": "1", "bin_kind": "eq", "bin_value": 1}]
    monkeypatch.setattr(features, "clob_feature_rows_for_folder", lambda *a, **k: list(rows))
    features.write_clob_feature_rows(tmp_path, append_only=True)
    paths = [tmp_path / "clob_features_long.csv", tmp_path / "clob_features.jsonl"]
    prefixes = [path.read_bytes() for path in paths]
    rows.append(dict(rows[0], snapshot_id="2"))
    features.write_clob_feature_rows(tmp_path, append_only=True)
    assert all(path.read_bytes().startswith(prefix) for path, prefix in zip(paths, prefixes))
    stable = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    features.write_clob_feature_rows(tmp_path, append_only=True)
    assert stable == [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    # Simulate a crash after the CSV append and before the JSONL append.
    paths[1].write_bytes(prefixes[1])
    features.write_clob_feature_rows(tmp_path, append_only=True)
    features.write_clob_feature_rows(reference)
    assert all(path.read_bytes() == (reference / path.name).read_bytes() for path in paths)
    rows[0] = dict(rows[0], bin_value=3)
    features.write_clob_feature_rows(tmp_path, append_only=True)
    features.write_clob_feature_rows(reference)
    assert all(path.read_bytes() == (reference / path.name).read_bytes() for path in paths)


def _tokens(moment, count=2):
    return [{"clob_token_id": str(token), "condition_id": str(token // 2), "market_id": "fixture",
             "event_slug": "fixture", "range_label": "20 C", "bin_kind": "eq", "bin_value": 20,
             "unit": "C", "outcome": "Yes" if token % 2 == 0 else "No", "active": True,
             "closed": False, "captured_at_utc": moment.isoformat(), "captured_at_local": moment.isoformat(),
             "gamma_best_bid": 0.4, "gamma_volume": 100} for token in range(count)]


def test_complete_batches_static_change_hour_day_restart_and_corrupt_cache(tmp_path):
    from weather.market.market_microstructure_capture import MarketMicrostructureStore
    from weather.market.clob_token_cadence import IDENTITY_FIELDS

    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    store = MarketMicrostructureStore(root=tmp_path, event_slug="fixture")
    store.token_path.write_text("captured_at_utc,clob_token_id\nlegacy,a\n", encoding="utf-8")
    original = store.token_path.read_bytes()
    assert store.write_token_rows(_tokens(now)) == 2
    assert store.token_path.read_bytes().startswith(original)
    warm = store.token_path.read_bytes()
    later = _tokens(now + timedelta(minutes=1))
    later[0]["gamma_volume"] = 999
    later[0]["gamma_best_bid"] = 0.7
    restarted = MarketMicrostructureStore(root=tmp_path, event_slug="fixture")
    assert restarted.write_token_rows(later) == 0
    assert store.token_path.read_bytes() == warm
    # Every declared identity field affects the key and writes all tokens.
    for field in IDENTITY_FIELDS:
        changed = [dict(row) for row in later]
        changed[0][field] = "changed"
        assert store.write_token_rows(changed) == 2, field
        assert store.write_token_rows(later) == 2, field
    metadata = [{"clob_token_id": "0", "tick_size": 0.01, "min_order_size": 5}]
    assert store.write_token_rows(later, book_metadata=metadata) == 2
    assert store.write_token_rows(later, book_metadata=metadata) == 0
    metadata[0]["tick_size"] = 0.001
    assert store.write_token_rows(later, book_metadata=metadata) == 2
    metadata[0]["min_order_size"] = 10
    assert store.write_token_rows(later, book_metadata=metadata) == 2
    assert store.write_token_rows(_tokens(now + timedelta(hours=1)), book_metadata=metadata) == 2
    assert store.write_token_rows(_tokens(now + timedelta(days=1)), book_metadata=metadata) == 2
    (tmp_path / ".clob-token-batch.json").write_text("broken", encoding="utf-8")
    assert store.write_token_rows(_tokens(now + timedelta(days=1)), book_metadata=metadata) == 2


def test_full_day_rows_and_volatile_reader_coverage(tmp_path):
    from weather.market.market_microstructure_capture import MarketMicrostructureStore, summarize_order_book
    from weather.market.market_microstructure_constants import BOOK_SUMMARY_COLUMNS, TOKEN_COLUMNS
    from weather.market.portable_live_candidate_preflight import MAX_PUBLIC_INPUT_AGE_SECONDS

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    store = MarketMicrostructureStore(root=tmp_path, event_slug="fixture")
    counts = []
    for minute in range(1440):
        rows = _tokens(start + timedelta(minutes=minute), 20)
        for row in rows:
            row["gamma_volume"] = minute
        counts.append(store.write_token_rows(rows))
    assert sum(counts) == 24 * 20
    assert len([count for count in counts if count]) == 24
    with store.token_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == TOKEN_COLUMNS
        written = list(reader)
    for hour in range(24):
        selected = [row for row in written if row["captured_at_utc"][11:13] == f"{hour:02}"]
        assert len(selected) == 20
        assert {row["clob_token_id"] for row in selected} == {str(n) for n in range(20)}
    token = _tokens(start)[0]
    token.update(gamma_best_ask=0.6, gamma_last_trade_price=0.5)
    summary = summarize_order_book({"asset_id": "0", "bids": [], "asks": []}, token, start)
    for field in ("gamma_best_bid", "gamma_best_ask", "gamma_last_trade_price"):
        assert field in BOOK_SUMMARY_COLUMNS
        assert summary[field] == token[field]
    assert MAX_PUBLIC_INPUT_AGE_SECONDS == 600  # retained gate; hourly token age can BLOCK
    assert len([json.loads(line) for line in store.token_jsonl_path.read_text().splitlines()]) == 480
