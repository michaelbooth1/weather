"""88a recorder-only pilot P1: config contract, built-in selection ratchet, journal isolation.

Guards: docs/operations/DATA_LAYER_V2_PLAN.md S2+S9 and VR-1 (built-ins stay on all_specs();
built-in ids and per-city selection cannot change under any config state; P1 rows from the
default config path, reloaded per cycle, config_sha256 stamped) and DATA_LAYER_V2_CONTRACT.md
"Recorder-only rows"; owner Q16 (2026-10-15): pilot bands are outside the 10-01 maker-P&L
pre-registration's 12-market stratum, so no pilot row may reach a built-in journal or panel input.
Also the 88a data hold to UTC 10-30 (DATA_LAYER_V2_PLAN.md VR-1, S2+S9; master 10-15): the pilot and
sweep land off, built-in bands keep the pre-S9 every-minute reward read until 2026-10-31T00:00Z
whatever the config says, and a pilot cycle or pilot trade-socket failure never stops the built-ins.
Shipped state since the owner's 2026-10-23 phase-2 plan (DECISION_LOG lines 258/259/265): the pilot is
on for R1 (the five P1 cities) and R2 (Munich, Madrid, Beijing, Wellington, Hong Kong); the sweep stays
off and the built-ins stay legacy. The built-in selection ratchet is unchanged.
"""
from argparse import Namespace
from datetime import datetime, timezone
import json

import pytest

from weather.market import maker_evidence_capture as capture
from weather.market.maker_evidence_pilot import (
    BLOCK, BUILT_IN_LEGACY_UNTIL, MAX_ROWS, PILOT_PARTITION, STRATUM, built_ins_event_driven, load_recorder_only,
)
from weather.market.maker_evidence_rewards import RewardSweep, RewardTrigger
from weather.market.maker_evidence_store import EvidenceStore, digest, encoded
from weather.market.maker_evidence_stream import PublicStream
from weather.market.market_registry import all_specs
from weather.paths import config_path

NOW = datetime(2026, 10, 16, 15, tzinfo=timezone.utc)
CONFIG = config_path("capture_families.json")
P1 = ["london", "shanghai", "paris", "seoul", "tokyo"]
R2 = ["munich", "madrid", "beijing", "wellington", "hong_kong"]  # DECISION_LOG 2026-10-23 (lines 258/259)
SHIPPED = P1 + R2


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
        self.calls, self.keys, self.token_market = [], [], {}

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None, partition=None,
             projection=None):
        self.calls.append((kind, partition))
        self.keys.append((kind, partition, change_key))
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


def pilot_on(**changes):
    return {"pilot": "on", "rewards_sweep": "on", "rows": shipped_rows(), **changes}


def test_shipped_block_is_the_r1_r2_pilot_and_agrees_with_the_location_registry():
    config = load_recorder_only(CONFIG)
    assert [m.id for m in config.markets] == SHIPPED
    assert config.config_sha256 == digest(CONFIG.read_bytes())
    locations = {row["id"]: row for row in json.loads(config_path("locations.json").read_text(encoding="utf-8"))["locations"]}
    for m in config.markets:
        row = locations[m.location_id]
        assert m.slug_prefix == row["polymarket"]["event_slug_prefix"]
        assert str(m.tz) == row["timezone"] and m.series == "highest" and m.horizons == (0, 1, 2)
    assert not {m.id for m in config.markets} & {spec.id for spec in all_specs()}


def test_absent_block_means_no_pilot_no_sweep_and_legacy_built_ins(tmp_path):
    config = load_recorder_only(write_config(tmp_path, None))
    assert config.markets == () and not config.sweep_enabled and config.built_in_reward_cadence == "legacy"


def test_shipped_config_records_r1_r2_with_sweep_off_and_switching_is_config_only(tmp_path):
    """Master 10-15 (Q3) landed it disabled; owner 2026-10-23 (DECISION_LOG lines 258/259/265) switches R1+R2 on.

    The sweep stays off and the built-ins legacy. Switching the pilot off again is a config-only flip.
    """
    shipped = load_recorder_only(CONFIG)
    assert (shipped.pilot, shipped.rewards_sweep, shipped.built_in_reward_cadence) == ("on", "off", "legacy")
    assert [m.id for m in shipped.active_markets] == SHIPPED and not shipped.sweep_enabled
    off = load_recorder_only(write_config(tmp_path, pilot_on(pilot="off")))
    assert off.markets == shipped.markets and off.active_markets == ()
    on = load_recorder_only(write_config(tmp_path, pilot_on()))
    assert [m.id for m in on.active_markets] == SHIPPED and on.sweep_enabled
    for key, value in (("pilot", "maybe"), ("built_in_reward_cadence", "hourly")):
        with pytest.raises(ValueError, match=key):
            load_recorder_only(write_config(tmp_path, pilot_on(**{key: value})))


def test_built_ins_stay_on_the_legacy_reward_cadence_until_the_hold_ends(tmp_path):
    flipped = load_recorder_only(write_config(tmp_path, pilot_on(built_in_reward_cadence="event_driven")))
    before = datetime(2026, 10, 30, 23, 59, 59, tzinfo=timezone.utc)
    assert BUILT_IN_LEGACY_UNTIL == datetime(2026, 10, 31, tzinfo=timezone.utc)
    assert not built_ins_event_driven(flipped, before)
    assert built_ins_event_driven(flipped, BUILT_IN_LEGACY_UNTIL)
    assert built_ins_event_driven(flipped, before, dry_run=True)  # Scratch roots only.
    for config in (load_recorder_only(CONFIG), None):
        assert not built_ins_event_driven(config, BUILT_IN_LEGACY_UNTIL)
    reader = Reader(EvidenceStore(tmp_path / "root", clock=lambda: NOW))
    hook, event_driven = capture.built_in_reward_hook(flipped, RewardTrigger(reader), RewardSweep(reader), True, before)
    assert hook is capture.read_every_cycle and not event_driven


# The pre-S9 universe row and event, in key order (maker_evidence_capture.py at 658592038).
PRE_S9_ROW_KEYS = ["condition_id", "city", "day_ahead", "event_slug", "tokens", "modelled_reward_20",
                   "clob_reward_content_sha256", "ranking_terms"]
PRE_S9_EVENT_KEYS = ["city", "bands", "shortages", "missing_events", "candidate_count", "ranking"]


def test_legacy_built_in_reward_reads_keep_the_pre_s9_cadence_and_record_shape(tmp_path):
    """Under the shipped config every selected built-in band's record is read every cycle, as before S9."""
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    reader = Reader(store)
    sweep, trigger = RewardSweep(reader), RewardTrigger(reader)
    config = load_recorder_only(CONFIG)
    events = []
    original = store.event

    def spy(kind, payload, **kwargs):
        events.append((kind, payload))
        return original(kind, payload, **kwargs)

    store.event = spy
    for cycle in range(3):
        trigger.begin_cycle()
        hook, event_driven = capture.built_in_reward_hook(config, trigger, sweep, config.sweep_enabled, NOW)
        assert not event_driven
        start = len(reader.keys)
        rows, _, _ = capture.build_universe(reader, all_specs(), now=NOW, rewards=hook)
        reward_keys = [key for kind, _, key in reader.keys[start:] if kind == "rewards"]
        assert reward_keys == [f"reward:{row['condition_id']}:first" for row in rows], cycle
        assert len(rows) == 120 and all(list(row) == PRE_S9_ROW_KEYS for row in rows)
    universe = [payload for kind, payload in events if kind == "universe"]
    assert universe and all(list(payload) == PRE_S9_EVENT_KEYS for payload in universe)
    assert not any(name.startswith(("rewards_current", "rewards_sweep")) for name in store.files)
    assert {kind for kind, _ in reader.calls} == {"discovery", "ranking_books", "rewards"}


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
    for state, block in [("pilot", pilot_on()), ("sweep_off", pilot_on(rewards_sweep="off")),
                         ("event_driven", pilot_on(built_in_reward_cadence="event_driven")),
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
    config = load_recorder_only(write_config(tmp_path, pilot_on()))
    trades = PublicStream(store, trades_only=True, partition=PILOT_PARTITION)
    pilot_state = {"state": "OFF", "cycles": 0, "failed_cycles": 0}
    universe = capture.capture_recorder_only(reader, store, config, trigger, RewardSweep(reader), True, trades, pilot_state)
    assert pilot_state["state"] == "CAPTURING" and len(universe) == 10 * len(SHIPPED)
    assert len(trades.tokens) == 20 * len(SHIPPED)  # Two tokens per band; the stream opens a socket per 100.
    assert {r["city"] for r in universe} == set(SHIPPED)
    assert all(r["stratum"] == STRATUM and r["config_sha256"] == config.config_sha256 for r in universe)
    assert {partition for _, partition in reader.calls} == {PILOT_PARTITION}
    new_files = set(store.files) - core_files
    pilot_assets = set(reader.token_market)  # Every token on a pilot event, selected or not.
    for name in new_files:
        assert name.endswith("-pilot.jsonl") or name.startswith("universe-pilot-") or (
            name.startswith("book-") and name[5:-6] in pilot_assets), name
    assert {f"universe-pilot-{city}.jsonl" for city in SHIPPED} <= new_files
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
    universe = capture.capture_recorder_only(reader, store, load_recorder_only(write_config(tmp_path, pilot_on())),
                                             trigger, RewardSweep(reader),
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
    assert pilot_state["markets"] == SHIPPED  # Shipped rows are on (R1+R2, DECISION_LOG 2026-10-23).
    assert good is not None and pilot_state["config_sha256"] == good.config_sha256


def test_only_a_trade_channel_takes_a_partition(tmp_path):
    store = EvidenceStore(tmp_path / "root", clock=lambda: NOW)
    with pytest.raises(ValueError, match="trade channel"):
        PublicStream(store, partition=PILOT_PARTITION)
    assert PublicStream(store, trades_only=True).channel == "trades"


class FakeTime:
    def __init__(self):
        self.now = 0.

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.)

    @property
    def cycle(self):
        return int(self.now // 60)


class LoopReader(Reader):
    """The fake public reader inside capture(): pilot reads fail in cycle 1."""

    def __init__(self, store, clock):
        super().__init__(store)
        self.clock, self.deadline, self.by_cycle = clock, 0., []

    def read(self, url, **kwargs):
        self.by_cycle.append((self.clock.cycle, kwargs.get("kind"), kwargs.get("partition")))
        if kwargs.get("partition") == PILOT_PARTITION and self.clock.cycle == 1:
            raise TimeoutError("injected pilot cycle failure")
        return super().read(url, **kwargs)

    def metrics(self):
        return {"requests": len(self.by_cycle)}

    def close(self):
        pass


class LoopStream:
    """The fake websocket: the pilot trade socket fails (closed by the venue) in cycle 2."""

    def __init__(self, clock, store, *, trades_only=False, partition=None):
        self.clock, self.partition, self.trades_only = clock, partition, trades_only
        self.channel = f"{partition}_trades" if partition else ("trades" if trades_only else "market")
        self.replaced, self.closed = [], False

    def replace(self, tokens):
        if self.partition and self.clock.cycle == 2:
            self.closed = True
            raise ConnectionError("injected pilot trade socket close code=1006")
        self.replaced.append((self.clock.cycle, len(tokens)))

    def replace_window(self, tokens, end):
        pass

    def stop(self):
        pass

    def metrics(self):
        return {"channel": self.channel, "connected": not self.closed}


def test_pilot_cycle_and_trade_socket_failures_never_stop_the_built_in_loop(tmp_path, monkeypatch):
    """Master 10-15 (Q1): same process accepted; the pilot's failures stay the pilot's."""
    clock, streams, readers = FakeTime(), [], []

    def make_reader(store, timeout):
        readers.append(LoopReader(store, clock))
        return readers[-1]

    def make_stream(store, **kwargs):
        streams.append(LoopStream(clock, store, **kwargs))
        return streams[-1]

    monkeypatch.setattr(capture, "time", clock)
    monkeypatch.setattr(capture, "lowest_priority", lambda: None)
    monkeypatch.setattr(capture, "disk_band", lambda free: "green")
    monkeypatch.setattr(capture, "RECORDER_ONLY_CONFIG", write_config(tmp_path, pilot_on()))
    monkeypatch.setattr(capture, "PublicReader", make_reader)
    monkeypatch.setattr(capture, "PublicStream", make_stream)
    root = tmp_path / "evidence"
    args = Namespace(root=root, extra_conditions=None, family=None, duration_seconds=200, dry_run=False,
                     stream_cap_bytes=capture.DEFAULT_STREAM_CAP, request_timeout_seconds=5., recorder_only_config=None)
    capture.capture(args)
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert (status["state"], status["cycles"], status["failed_cycles"]) == ("COMPLETED", 3, 0)
    pilot = status["recorder_only"]
    assert pilot["state"] == "DEGRADED" and (pilot["cycles"], pilot["failed_cycles"]) == (1, 2)
    assert "ConnectionError" in pilot["last_error"]
    assert status["rewards"]["built_in_cadence"] == "legacy"
    calls = readers[0].by_cycle
    for cycle in range(3):  # Built-in discovery, ranking, rewards and books were read every cycle.
        assert {kind for c, kind, partition in calls if c == cycle and partition is None} >= {
            "discovery", "ranking_books", "rewards", "books"}, cycle
    core_trades = next(s for s in streams if s.trades_only and s.partition is None)
    assert core_trades.replaced == [(0, 240), (1, 240), (2, 240)]
    assert next(s for s in streams if s.partition).closed
