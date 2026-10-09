"""Synthetic-fixture tests for the maker P&L desk-study power rule script.

Guards: the frozen N_req formula and branch table, the N_req <= 14 embargo decision, hard refusal of
every date after 2026-09-29 (embargo 09-30..10-15 included), never decoding ledger rows outside the
pilot, sealed-file integrity refusal, the output-path guard, and the strictly-through own-token fill
and NP_S arithmetic on a synthetic 88a store.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from tools.research import maker_pnl_power_rule_pilot as pilot
from weather.market.market_config import event_slug_for_date

CID = "0x" + "ab" * 32
YES, NO = "111", "222"
EVENT = date(2026, 9, 28)


def test_power_rule_matches_the_frozen_formula():
    means = {"2026-09-26": 0.0, "2026-09-27": 0.2, "2026-09-28": -0.2, "2026-09-29": 0.4}
    rule = pilot.power_rule(means)
    values = list(means.values())
    mean = sum(values) / 4
    sigma_d = math.sqrt(sum((v - mean) ** 2 for v in values) / 3)
    assert rule["n"] == 4
    assert rule["sigma_d"] == pytest.approx(sigma_d)
    assert rule["c"] == pytest.approx(0.584375, abs=1e-5)
    assert rule["sigma_up"] == pytest.approx(sigma_d * math.sqrt(3 / rule["c"]))
    assert rule["n_req"] == math.ceil(((1.645 + 0.842) * rule["sigma_up"] / 1.0) ** 2)
    assert rule["branch"] == "PANEL_STAYS_14"
    assert pilot.decision(rule)["embargo_end_to"] == "2026-10-31"


@pytest.mark.parametrize("spread,branch", [(1.0, "PANEL_EXTENDED_TO_N_REQ"), (3.0, "UNDECIDABLE_AT_DELTA")])
def test_power_rule_branches_above_14_leave_the_embargo_unchanged(spread, branch):
    rule = pilot.power_rule({"a": -spread, "b": spread, "c": 0.0, "d": spread / 2})
    assert rule["n_req"] > 14 and rule["branch"] == branch
    assert pilot.decision(rule)["action"] == "EMBARGO_END_UNCHANGED"
    assert pilot.decision(rule)["embargo_end_to"] == "2026-11-13"


def test_fewer_than_two_dates_runs_the_panel_at_28():
    rule = pilot.power_rule({"2026-09-28": 3.0})
    assert rule["sigma_d"] is None and rule["panel_event_dates"] == 28
    assert pilot.decision(rule)["action"] == "EMBARGO_END_UNCHANGED"


@pytest.mark.parametrize("value", ["2026-09-30", "2026-10-07", "2026-10-15"])
def test_embargo_dates_refuse(value):
    with pytest.raises(pilot.Refused, match="embargo"):
        pilot.guard_date(value, "probe")


@pytest.mark.parametrize("value", ["2026-10-16", "2026-11-01"])
def test_dates_after_the_pilot_refuse(value):
    with pytest.raises(pilot.Refused, match="after 2026-09-29"):
        pilot.guard_date(value, "probe")


def test_cli_refuses_an_embargo_date_before_touching_inputs(tmp_path, capsys):
    code = pilot.main(["--maker-evidence-root", str(tmp_path / "missing"), "--settlement-root", str(tmp_path),
                       "--output", str(tmp_path / "out.json"), "--date", "2026-10-03"])
    assert code == 3 and "embargo" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_output_guard_refuses_data_dirs_and_existing_files(tmp_path):
    with pytest.raises(pilot.Refused):
        pilot.check_output(tmp_path / "data" / "out.json")
    existing = tmp_path / "out.json"
    existing.write_text("{}")
    with pytest.raises(pilot.Refused):
        pilot.check_output(existing)


# --------------------------------------------------------------------------- synthetic 88a store

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class SegmentWriter:
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True)
        self.files = {}

    def append(self, name, row):
        stats = self.files.setdefault(name, {"bytes": 0, "records": 0, "data": b""})
        row = {**row, "offset": stats["bytes"]}
        line = (json.dumps(row, sort_keys=True) + "\n").encode()
        stats["data"] += line
        stats["last_offset"] = stats["bytes"]
        stats["bytes"] += len(line)
        stats["records"] += 1
        return row["offset"]

    def seal(self):
        manifest = {}
        for name, stats in self.files.items():
            (self.folder / name).write_bytes(stats["data"])
            manifest[name] = {"sha256": hashlib.sha256(stats["data"]).hexdigest(), "bytes": stats["bytes"],
                              "records": stats["records"], "last_offset": stats["last_offset"]}
        (self.folder / "manifest.json").write_text(json.dumps({"files": manifest}))


def build_store(root, settle):
    spec = pilot.all_specs()[0]
    slug = event_slug_for_date(EVENT, spec.id)
    book = {"market": CID, "asset_id": YES, "tick_size": "0.01",
            "bids": [{"price": "0.48", "size": "500"}, {"price": "0.47", "size": "500"}],
            "asks": [{"price": "0.52", "size": "500"}, {"price": "0.53", "size": "500"}]}
    reward = {"data": [{"condition_id": CID, "rewards_max_spread": 3.5, "rewards_min_size": 50,
                        "rewards_config": [{"rate_per_day": 10.0, "start_date": "2026-09-01",
                                            "end_date": "2026-10-31"}], "event_slug": slug}]}
    reward_file = "reward-" + hashlib.sha256(f"reward:{CID}:first".encode()).hexdigest()[:24] + ".jsonl"
    fills = {datetime(2026, 9, 27, 12, 0, 30, tzinfo=timezone.utc).timestamp(): (YES, "0.47", "10"),
             datetime(2026, 9, 27, 13, 0, 30, tzinfo=timezone.utc).timestamp(): (NO, "0.47", "100")}
    sequence = 0
    for day in (date(2026, 9, 27), date(2026, 9, 28)):
        writer = SegmentWriter(root / day.isoformat() / "00-0123456789ab")
        base = datetime.combine(day, datetime.min.time(), timezone.utc).timestamp()
        writer.append("universe-" + spec.id + ".jsonl", {
            "kind": "universe", "captured_at_utc": iso(base), "body_utf8": json.dumps(
                {"city": spec.id, "bands": [{"condition_id": CID, "city": spec.id, "day_ahead": 1,
                                             "event_slug": slug, "tokens": [YES, NO]}]})})
        stored_at = None
        for minute in range(1440):
            at = base + minute * 60
            if minute % 60 == 0:
                if stored_at is None:
                    stored_at = writer.append(reward_file, {"kind": "rewards", "http_status": 200, "body_stored": True,
                                                            "captured_at_utc": iso(at), "body_utf8": json.dumps(reward)})
                else:
                    writer.append(reward_file, {"kind": "rewards", "http_status": 200, "body_stored": False,
                                                "captured_at_utc": iso(at),
                                                "payload_ref": {"file": reward_file, "offset": stored_at}})
            sequence += 1
            offset = writer.append("book-" + YES + ".jsonl", {"sequence": sequence, "body_utf8": json.dumps(book)})
            writer.append("books.jsonl", {"kind": "books", "http_status": 200, "sequence": sequence,
                                          "captured_at_utc": iso(at + 5), "parts": [
                                              {"literal_utf8": "["}, {"file": "book-" + YES + ".jsonl", "offset": offset},
                                              {"literal_utf8": "]"}]})
            if at + 30 in fills:
                token, price, size = fills[at + 30]
                writer.append("trades.jsonl", {"kind": "stream", "captured_at_utc": iso(at + 31), "body_utf8": json.dumps(
                    {"event_type": "last_trade_price", "asset_id": token, "price": price, "size": size,
                     "side": "SELL", "timestamp": str(int((at + 30) * 1000))})})
        writer.seal()
    ledger = settle / spec.id / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {"event_slug": slug, "target_date": EVENT.isoformat(), "polymarket_winning_band": "20 C",
           "polymarket_reconciliation": {"winning_markets": [{"label": "20 C", "condition_id": CID}]}}
    ledger.write_text(json.dumps(row, sort_keys=True) + "\n"
                      + '{"target_date": "2026-10-02", this row is not JSON and must never be decoded\n')
    return spec


def test_synthetic_store_end_to_end(tmp_path, capsys):
    root, settle = tmp_path / "store", tmp_path / "settle"
    build_store(root, settle)
    out = tmp_path / "result" / "power.json"
    assert pilot.main(["--maker-evidence-root", str(root), "--settlement-root", str(settle),
                       "--output", str(out), "--master-sha", "f" * 40]) == 0
    document = json.loads(out.read_text())
    included = [r for r in document["band_days"] if r["excluded"] is None]
    assert len(included) == 1
    row = included[0]
    assert row["quote_date"] == "2026-09-27" and row["admissible_minutes"] == 1440
    assert row["fills"] == 2 and row["filled_shares"] == pytest.approx(85.0)
    # YES bid 10 @ 0.48 and NO bid 75 @ YES-price 0.52, mid 0.50, settles YES (mark 1).
    assert row["spread"] == pytest.approx(10 * 0.02 + 75 * 0.02)
    assert row["as_s"] == pytest.approx(-10 * 0.5 + 75 * 0.5)
    assert row["rew"] > 0
    assert row["np_s"] == pytest.approx(row["rew"] + row["spread"] - row["as_s"])
    assert document["power_rule"]["branch"] == "SIGMA_D_UNDEFINED_PANEL_28"
    assert document["decision"]["action"] == "EMBARGO_END_UNCHANGED"
    assert document["diagnostics"]["ledger_rows_outside_pilot_skipped_undecoded"] == 1
    assert document["envelope"]["master_sha"] == "f" * 40
    body = {k: v for k, v in document.items() if k not in ("envelope", "result_sha256")}
    assert document["result_sha256"] == hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_tampered_sealed_file_refuses(tmp_path, capsys):
    root, settle = tmp_path / "store", tmp_path / "settle"
    build_store(root, settle)
    trades = root / "2026-09-27" / "00-0123456789ab" / "trades.jsonl"
    original = trades.read_bytes()
    tampered = original.replace(b'\\"size\\": \\"10\\"', b'\\"size\\": \\"99\\"')
    assert tampered != original
    trades.write_bytes(tampered)
    code = pilot.main(["--maker-evidence-root", str(root), "--settlement-root", str(settle),
                       "--output", str(tmp_path / "out.json")])
    assert code == 3 and "integrity mismatch" in capsys.readouterr().err


def test_dry_run_reads_metadata_only(tmp_path):
    root, settle = tmp_path / "store", tmp_path / "settle"
    build_store(root, settle)
    out = tmp_path / "dry.json"
    assert pilot.main(["--maker-evidence-root", str(root), "--settlement-root", str(settle),
                       "--output", str(out), "--dry-run"]) == 0
    document = json.loads(out.read_text())
    assert document["sealed_segments"] == 2
    assert "2026-09-25" in document["diagnostics"]["missing_88a_days"]


def test_simulation_fills_only_strictly_through_own_token_prints():
    start = datetime(2026, 9, 27, tzinfo=timezone.utc).timestamp()
    sample = pilot.make_sample(start, [(0.48, 500), (0.47, 500)], [(0.52, 500), (0.53, 500)], 0.01)
    terms = [pilot.Terms(start, ((10.0, "2026-09-01", "2026-10-31"),), 50.0, 3.5)]
    prints = [(start + 10, 0, 0.48, 50.0, 1),   # at the bid: not strictly through
              (start + 20, 1, 0.45, 5.0, 2),    # NO print below 1 - 0.52: fills NO leg
              (start + 25, 0, 0.55, 5.0, 3)]    # YES print above ask: never fills the NO leg
    sim = pilot.simulate_band_day([sample], prints, terms, start, start + 120)
    assert sim["fills"] == [(start + 20, 5.0, 0.52, -1)]
    assert sim["diagnostics"]["opposite_token_prints_that_would_qualify"] == 1
    assert sim["admissible_minutes"] == 2  # rests 120 s < 5-minute maximum
