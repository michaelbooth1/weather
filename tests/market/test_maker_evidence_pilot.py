"""88a recorder-only pilot P1: config contract, built-in selection ratchet, journal isolation.

Guards: docs/operations/DATA_LAYER_V2_PLAN.md S2+S9 and VR-1 (built-ins stay on all_specs();
built-in ids and per-city selection cannot change under any config state; P1 rows from the
default config path, reloaded per cycle, config_sha256 stamped) and DATA_LAYER_V2_CONTRACT.md
"Recorder-only rows"; owner Q16 (2026-10-15): pilot bands are outside the 10-01 maker-P&L
pre-registration's 12-market stratum, so no pilot row may reach a built-in journal or panel input.
"""
from datetime import datetime, timezone
import json

import pytest

from weather.market import maker_evidence_capture as capture
from weather.market.maker_evidence_pilot import (
    BLOCK, MAX_ROWS, PILOT_PARTITION, STRATUM, load_recorder_only,
)
from weather.market.maker_evidence_rewards import RewardSweep, RewardTrigger
from weather.market.maker_evidence_store import EvidenceStore, digest, encoded
from weather.market.maker_evidence_stream import PublicStream
from weather.market.market_registry import all_specs
from weather.paths import config_path

NOW = datetime(2026, 10, 16, 15, tzinfo=timezone.utc)
CONFIG = config_path("capture_families.json")
P1 = ["london", "shanghai", "paris", "seoul", "tokyo"]


def condition(*parts):
    return "0x" + digest(encoded(parts))


def market(slug, band):
    cid = condition(slug, band)
    return {"id": f"{slug}-{band}", "conditionId": cid, "active": True, "closed": False, "enableOrderBook": True,
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": json.dumps([str(int(cid[2:18], 16)), str(int(cid[18:34], 16))]),
            "rewardsMinSize": 20, "rewardsMaxSpread": 4.5,
            "clobRewards": [{"rewardsDailyRate": 1 + band, "startDate": "2026-10-01", "endDate": "2500-12-31"}]}


class Reader:
    """Public-shape fake: eleven rewarded bands per event, books by token, one reward record each."""

    def __init__(self, store, *, fail_pilot=False):
        self.store, self.fail_pilot = store, fail_pilot
        self.calls, self.token_market = [], {}

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None, partition=None,
             projection=None):
        self.calls.append((kind, partition))
        if self.fail_pilot and partition == PILOT_PARTITION:
            raise TimeoutError("public reply exceeded wall deadline")
        if url.endswith("/events"):
            slugs = [value for key, value in params if key == "slug"]
            reply = [{"id": slug, "slug": slug, "markets": [market(slug, band) for band in range(11)]} for slug in slugs]
            for row in (m for event in reply for m in event["markets"]):
                self.token_market.update((token, row["conditionId"]) for token in json.loads(row["clobTokenIds"]))
        elif url.endswith("/books"):
            reply = [{"market": self.token_market[row["token_id"]], "asset_id": row["token_id"],
                      "bids": [{"price": "0.40", "size": "50"}], "asks": [{"price": "0.45", "size": "50"}],
                      "tick_size": "0.01"} for row in body]
        else:
            cid = url.rsplit("/", 1)[1]
            reply = {"data": [{"condition_id": cid, "rewards_config": []}], "next_cursor": "LTE="}
        raw = json.dumps(reply).encode()
        self.store.record(kind, raw, change_key=change_key, partition=partition)
        return json.loads(raw)


def write_config(tmp_path, block):
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    if block is None:
        payload.pop(BLOCK, None)
    else:
        payload[BLOCK] = block
    path = tmp_path / "capture_families.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def shipped_rows():
    return json.loads(CONFIG.read_text(encoding="utf-8"))[BLOCK]["rows"]


def core_selection(store):
    reader = Reader(store)
    trigger = RewardTrigger(reader)
    trigger.begin_cycle()
    rows, shortages, missing = capture.build_universe(
        reader, all_specs(), now=NOW, rewards=capture.lane_rewards(trigger, RewardSweep(reader), True, None))
    return [(row["city"], row["day_ahead"], row["condition_id"], row["modelled_reward_20"], row["ranking_terms"])
            for row in rows], shortages, missing


def test_shipped_block_is_the_p1_pilot_and_agrees_with_the_location_registry():
    config = load_recorder_only(CONFIG)
    assert [m.id for m in config.markets] == P1 and config.sweep_enabled
    assert config.config_sha256 == digest(CONFIG.read_bytes())
    locations = {row["id"]: row for row in json.loads(config_path("locations.json").read_text(encoding="utf-8"))["locations"]}
    for m in config.markets:
        row = locations[m.location_id]
        assert m.slug_prefix == row["polymarket"]["event_slug_prefix"]
        assert str(m.tz) == row["timezone"] and m.series == "highest" and m.horizons == (0, 1, 2)
    assert not {m.id for m in config.markets} & {spec.id for spec in all_specs()}


def test_absent_block_means_no_pilot_and_the_sweep_on(tmp_path):
    config = load_recorder_only(write_config(tmp_path, None))
    assert config.markets == () and config.sweep_enabled


def row(**changes):
    base = dict(shipped_rows()[0])
    base.update(changes)
    return base


@pytest.mark.parametrize("rows, message", [
    ([row(id="nyc")], "built-in market"),
    ([row(location_id="toronto")], "built-in market"),
    ([row(id="extra_nyc", slug_prefix="highest-temperature-in-nyc-on")], "built-in or capture-family"),
    ([row(id="low_nyc", series="lowest", slug_prefix="lowest-temperature-in-nyc-on")], "built-in or capture-family"),
    ([row(slug_prefix="lowest-temperature-in-london-on")], "slug_prefix"),
    ([row(), row()], "unique"),
    ([row(horizons=[0, 1])], "horizons"),
    ([row(tz="Mars/Olympus")], "IANA"),
    ([row(band_policy="all_bands")], "band_policy"),
    ([{**row(), "unexpected": 1}], "fields"),
    ([row(id=f"city{n}", slug_prefix=f"highest-temperature-in-city{n}-on") for n in range(MAX_ROWS + 1)], "at most"),
])
def test_loader_refuses_every_row_that_could_touch_a_built_in_or_family(tmp_path, rows, message):
    with pytest.raises(ValueError, match=message):
        load_recorder_only(write_config(tmp_path, {"rewards_sweep": "on", "rows": rows}))


def test_rewards_sweep_kill_switch_is_a_config_flip(tmp_path):
    assert not load_recorder_only(write_config(tmp_path, {"rewards_sweep": "off", "rows": []})).sweep_enabled
    with pytest.raises(ValueError, match="rewards_sweep"):
        load_recorder_only(write_config(tmp_path, {"rewards_sweep": "maybe", "rows": []}))


def test_built_in_selection_is_identical_with_and_without_the_pilot(tmp_path):
    """Ratchet: the 12 built-ins' ids and per-city selection are unchanged under every config state."""
    alone = EvidenceStore(tmp_path / "alone", clock=lambda: NOW)
    baseline = core_selection(alone)
    assert {city for city, *_ in baseline[0]} == {spec.id for spec in all_specs()}
    assert all(sum(r[0] == spec.id for r in baseline[0]) == 10 for spec in all_specs())
    for state, block in [("pilot", {"rewards_sweep": "on", "rows": shipped_rows()}),
                         ("sweep_off", {"rewards_sweep": "off", "rows": shipped_rows()}),
                         ("malformed", {"rewards_sweep": "on", "rows": [row(id="nyc")]}), ("absent", None)]:
        store = EvidenceStore(tmp_path / state, clock=lambda: NOW)
        pilot_state = {"state": "OFF", "cycles": 0, "failed_cycles": 0}
        config = capture.load_recorder_only_safely(store, pilot_state, path=write_config(tmp_path, block))
        assert core_selection(store) == baseline, state
        reader = Reader(store)
        trigger = RewardTrigger(reader)
        trigger.begin_cycle()
        capture.capture_recorder_only(reader, store, config, trigger, RewardSweep(reader), True,
                                      PublicStream(store, trades_only=True, partition=PILOT_PARTITION), pilot_state)
        assert core_selection(store) == baseline, state
        if state == "malformed":
            assert config is None and pilot_state["state"] == "CONFIG_ERROR"


def test_pilot_lane_journals_only_in_pilot_partitions_and_stamps_its_stratum(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    monkeypatch.setattr(PublicStream, "replace", lambda self, tokens: setattr(self, "tokens", tuple(tokens)))
    core_selection(store)
    core_files = set(store.files)
    reader = Reader(store)
    trigger = RewardTrigger(reader)
    trigger.begin_cycle()
    config = load_recorder_only(CONFIG)
    trades = PublicStream(store, trades_only=True, partition=PILOT_PARTITION)
    pilot_state = {"state": "OFF", "cycles": 0, "failed_cycles": 0}
    universe = capture.capture_recorder_only(reader, store, config, trigger, RewardSweep(reader), True, trades, pilot_state)
    assert pilot_state["state"] == "CAPTURING" and len(universe) == 50 and len(trades.tokens) == 100
    assert {r["city"] for r in universe} == set(P1)
    assert all(r["stratum"] == STRATUM and r["config_sha256"] == config.config_sha256 for r in universe)
    assert {partition for _, partition in reader.calls} == {PILOT_PARTITION}
    new_files = set(store.files) - core_files
    pilot_assets = set(reader.token_market)  # Every token on a pilot event, selected or not.
    for name in new_files:
        assert name.endswith("-pilot.jsonl") or name.startswith("universe-pilot-") or (
            name.startswith("book-") and name[5:-6] in pilot_assets), name
    assert {f"universe-pilot-{city}.jsonl" for city in P1} <= new_files
    # The panel reads books.jsonl / ranking_books.jsonl / trades.jsonl only; no pilot token is in them.
    for journal in ("books.jsonl", "ranking_books.jsonl", "trades.jsonl", "discovery.jsonl"):
        path = store.folder / journal
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        assert not any(asset in text for asset in pilot_assets), journal
    assert trades.channel == "pilot_trades"


def test_pilot_failure_never_fails_or_changes_the_built_in_cycle(tmp_path):
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    reader = Reader(store, fail_pilot=True)
    trigger = RewardTrigger(reader)
    trigger.begin_cycle()
    pilot_state = {"state": "OFF", "cycles": 0, "failed_cycles": 0}
    universe = capture.capture_recorder_only(reader, store, load_recorder_only(CONFIG), trigger, RewardSweep(reader),
                                             True, PublicStream(store, trades_only=True, partition=PILOT_PARTITION),
                                             pilot_state)
    assert universe == [] and pilot_state["state"] == "DEGRADED" and pilot_state["failed_cycles"] == 1
    assert store.failure is None and "recorder_only_cycle_error.jsonl" in store.files


def test_config_errors_are_journaled_once_per_distinct_error(tmp_path):
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    pilot_state = {"state": "OFF", "cycles": 0, "failed_cycles": 0}
    bad = write_config(tmp_path, {"rewards_sweep": "on", "rows": [row(id="nyc")]})
    for _ in range(3):
        assert capture.load_recorder_only_safely(store, pilot_state, path=bad) is None
    assert store.files["recorder_only_config_error.jsonl"]["records"] == 1
    good = capture.load_recorder_only_safely(store, pilot_state, path=CONFIG)
    assert good is not None and pilot_state["config_sha256"] == good.config_sha256


def test_only_a_trade_channel_takes_a_partition(tmp_path):
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    with pytest.raises(ValueError, match="trade channel"):
        PublicStream(store, partition=PILOT_PARTITION)
    assert PublicStream(store, trades_only=True).channel == "trades"
