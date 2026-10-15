"""Capture families: config contract, full-universe discovery, reward cadence, isolation from 88a."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from weather.market import maker_evidence_capture as capture
from weather.market.maker_evidence_family import (
    FAMILY_CONFIG, due_reward_reads, expected_events, family_universe, load_family,
)
from weather.market.maker_evidence_store import EvidenceStore, digest, encoded
from weather.market.market_registry import all_specs
from weather.paths import data_path

NOW = datetime(2026, 10, 15, 15, tzinfo=timezone.utc)


def cid(*parts):
    return "0x" + digest(encoded(parts))


def market(slug, band, *, rate=0., closed=False):
    condition = cid(slug, band)
    return {"id": f"{slug}-{band}", "conditionId": condition, "active": True, "closed": closed,
            "enableOrderBook": True, "outcomes": '["Yes", "No"]',
            "clobTokenIds": json.dumps([str(int(condition[2:18], 16)), str(int(condition[18:34], 16))]),
            "rewardsMinSize": 20, "rewardsMaxSpread": 4.5,
            "clobRewards": [{"rewardsDailyRate": rate, "startDate": "2026-10-01", "endDate": "2500-12-31"}] if rate else [],
            "description": "dropped by the discovery projection"}


class Reader:
    """Public-shape fake: Gamma events by slug, books by token, one reward record per condition."""

    def __init__(self, store, *, closed=(), rates=None):
        self.store, self.closed, self.rates = store, set(closed), rates or {}
        self.calls, self.token_market = [], {}

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None, partition=None):
        self.calls.append((url.rsplit("/", 1)[-1] if "/rewards/" not in url else "rewards", kind, partition))
        if url.endswith("/events"):
            slugs = [value for key, value in params if key == "slug"]
            reply = [{"id": slug, "slug": slug, "markets": [market(slug, band, rate=self.rates.get((slug, band), 0.),
                                                                   closed=(slug, band) in self.closed)
                                                            for band in range(11)]} for slug in slugs]
            for row in (m for event in reply for m in event["markets"]):
                self.token_market.update((token, row["conditionId"]) for token in json.loads(row["clobTokenIds"]))
        elif url.endswith("/books"):
            reply = [{"market": self.token_market[row["token_id"]], "asset_id": row["token_id"], "bids": [{"price": "0.4", "size": "50"}],
                      "asks": [{"price": "0.45", "size": "50"}], "tick_size": "0.01"} for row in body]
        else:
            condition = url.rsplit("/", 1)[1]
            reply = {"data": [{"condition_id": condition, "rewards_config": []}], "next_cursor": "LTE="}
        raw = json.dumps(reply).encode()
        self.store.record(kind, raw, change_key=change_key, partition=partition)
        return json.loads(raw)


@pytest.fixture
def family():
    return load_family("lowest_temperature")


@pytest.fixture
def store(tmp_path):
    return EvidenceStore(tmp_path / "family", clock=lambda: NOW)


def write_config(tmp_path, **changes):
    payload = json.loads(FAMILY_CONFIG.read_text(encoding="utf-8"))
    payload["families"]["lowest_temperature"].update(changes)
    path = tmp_path / "families.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_family_is_eleven_cities_without_chicago_in_its_own_root(family):
    cities = {spec.id for spec, _ in family.markets}
    assert len(cities) == 11 and "chicago" not in cities
    assert cities == {spec.id for spec in all_specs()} - {"chicago"}
    assert all(prefix == spec.slug_prefix.replace("highest-", "lowest-", 1) for spec, prefix in family.markets)
    assert family.root == data_path("maker_evidence_families", "lowest_temperature")
    assert family.floor_bytes == 70 * 1024**3 and family.day_ahead == (0, 1, 2)


@pytest.mark.parametrize("changes, message", [
    ({"markets": {"nyc": "lowest-temperature-in-nyc-on", "gotham": "lowest-temperature-in-gotham-on"}}, "registry ids"),
    ({"excluded_markets": {"nyc": "x"}}, "registry ids"),
    ({"markets": {"nyc": "lowest-temperature-in-nyc-on", "miami": "lowest-temperature-in-nyc-on"}}, "unique"),
    ({"markets": {"nyc": "highest-temperature-in-nyc-on"}}, "core 88a"),
    ({"day_ahead": [0, 0]}, "day_ahead"),
    ({"max_reward_reads_per_cycle": 1000}, "bounds"),
    ({"stop_below_free_gib": 39}, "bounds"),
])
def test_family_config_refuses_unsafe_definitions(tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        load_family("lowest_temperature", write_config(tmp_path, **changes))


def test_unknown_family_refused(family):
    with pytest.raises(ValueError, match="unknown capture family"):
        load_family("highest_temperature")


def test_expected_events_use_each_city_local_date(family):
    late = datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc)  # 23:30 New York, 20:30 Los Angeles on 10-15.
    expected = expected_events(family, late)
    assert len(expected) == 33
    assert expected["lowest-temperature-in-nyc-on-october-15-2026"] == ("nyc", 0)
    assert expected["lowest-temperature-in-los-angeles-on-october-17-2026"] == ("los-angeles", 2)
    assert not any("chicago" in slug for slug in expected)


def test_universe_keeps_every_active_condition_with_terms_and_partitions(family, store):
    slug = "lowest-temperature-in-nyc-on-october-15-2026"
    reader = Reader(store, closed={(slug, 0)}, rates={(slug, 5): 12.5})
    state = {}
    universe, shortages, missing = family_universe(reader, family, now=NOW, reward_state=state,
                                                   discover=capture.discover_events)
    assert len(universe) == 33 * 11 - 1 and shortages == [] and missing == []
    assert {row["family"] for row in universe} == {"lowest_temperature"}
    rewarded = [row for row in universe if row["reward_terms"]["daily_rate"]]
    assert [row["condition_id"] for row in rewarded] == [cid(slug, 5)]
    assert rewarded[0]["reward_terms"] == {"daily_rate": 12.5, "min_size": 20, "max_spread_cents": 4.5}
    # First cycle reads at most the cap; Gamma is 3 batched event reads for 33 slugs.
    assert sum(call[0] == "rewards" for call in reader.calls) == family.max_reward_reads_per_cycle
    assert sum(call[0] == "events" for call in reader.calls) == 3
    files = {path.name for path in store.folder.glob("*.jsonl")}
    assert "rewards-lowest_temperature.jsonl" in files and not any(name.startswith("reward-") for name in files)
    assert "universe-lowest_temperature-nyc.jsonl" in files and "universe-lowest_temperature-chicago.jsonl" not in files


def test_universe_body_is_change_only(family, store):
    reader = Reader(store)
    for _ in range(2):
        family_universe(reader, family, now=NOW, reward_state={}, discover=capture.discover_events)
    rows = [json.loads(line) for line in (store.folder / "universe-lowest_temperature-nyc.jsonl").read_text().splitlines()]
    assert [row["body_stored"] for row in rows] == [True, False]


def test_reward_reads_prioritise_changed_terms_then_sweep(family):
    rows = [{"condition_id": f"c{i}", "reward": {"rewards_config": []}} for i in range(3)]
    terms = digest(encoded({"rewards_config": []}))
    fresh = {"checked_at": NOW, "checked_at_utc": NOW.isoformat(), "gamma_terms_sha256": terms}
    old = NOW - timedelta(minutes=family.reward_sweep_minutes)
    state = {"c0": fresh, "c1": {**fresh, "gamma_terms_sha256": "changed"},
             "c2": {**fresh, "checked_at": old, "checked_at_utc": old.isoformat()}}
    assert due_reward_reads(rows, state, family, NOW) == ["c1", "c2"]
    assert due_reward_reads(rows, {**state, "c2": fresh}, family, NOW) == ["c1"]


def test_steady_state_reward_reads_follow_the_sweep(family, store):
    reader, state = Reader(store), {}
    reads = []
    for minute in range(31):
        before = len(reader.calls)
        family_universe(reader, family, now=NOW + timedelta(minutes=minute), reward_state=state,
                        discover=capture.discover_events)
        reads.append(sum(call[0] == "rewards" for call in reader.calls[before:]))
    assert max(reads) <= family.max_reward_reads_per_cycle
    # Every condition is re-read once per sweep after warm-up: 363 conditions over 15 minutes.
    assert sum(reads[16:31]) == 33 * 11


def run_family_capture(tmp_path, monkeypatch, *, free_gib):
    monkeypatch.setattr(capture, "lowest_priority", lambda: None)
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: free_gib * 1024**3)
    usage = type("Usage", (), {"free": free_gib * 1024**3})
    monkeypatch.setattr(capture.shutil, "disk_usage", lambda path: usage)
    readers = []
    def fake_reader(store, timeout):
        readers.append(Reader(store))
        readers[-1].metrics, readers[-1].close, readers[-1].deadline = (lambda: {"requests": len(readers[-1].calls)}), (lambda: None), 0
        return readers[-1]
    monkeypatch.setattr(capture, "PublicReader", fake_reader)
    monkeypatch.setattr(capture.PublicStream, "replace", lambda self, tokens: pytest.fail("family opened a websocket"))
    args = capture.build_parser().parse_args(["--family", "lowest_temperature", "--root", str(tmp_path / "family"),
                                              "--duration-seconds", "1"])
    return capture.capture(args), json.loads((tmp_path / "family" / "status.json").read_text()), readers


def test_family_capture_cycle_records_books_and_terms_without_websocket(tmp_path, monkeypatch):
    code, status, readers = run_family_capture(tmp_path, monkeypatch, free_gib=100)
    assert code == 0 and status["state"] == "COMPLETED" and status["cycles"] == 1
    assert status["family"] == "lowest_temperature" and status["universe_size"] == 363
    assert status["websocket"] == "none" and status["family_config_sha256"] == digest(FAMILY_CONFIG.read_bytes())
    kinds = [call[1] for call in readers[0].calls]
    assert kinds.count("books") == 8 and "ranking_books" not in kinds


def test_family_below_its_floor_opens_no_journal(tmp_path, monkeypatch):
    code, status, readers = run_family_capture(tmp_path, monkeypatch, free_gib=69)
    assert code == 2 and status["state"] == "STOPPED_FAMILY_DISK_FLOOR" and not readers
    assert [path.name for path in (tmp_path / "family").iterdir()] and not list((tmp_path / "family").glob("*/*"))


@pytest.mark.parametrize("root", [capture.DEFAULT_ROOT, capture.DEFAULT_ROOT / "lowest", capture.DEFAULT_ROOT.parent])
def test_family_never_shares_the_core_root_or_extras(tmp_path, root):
    args = capture.build_parser().parse_args(["--family", "lowest_temperature", "--root", str(root)])
    with pytest.raises(ValueError, match="88a root"):
        capture.capture(args)
    with pytest.raises(SystemExit):
        capture.main(["--family", "lowest_temperature", "--extra-conditions", str(tmp_path / "x.json")])


def test_family_storage_classification():
    from weather.operations.storage_classes import classify_storage_path
    journal = classify_storage_path("data/maker_evidence_families/lowest_temperature/2026-10-15/15-0123456789ab/books.jsonl.gz")
    assert journal.artifact_family == "passive_capture_family_evidence" and journal.protected
    status = classify_storage_path("data/maker_evidence_families/lowest_temperature/status.json")
    assert status.artifact_family == "passive_capture_family_status"
