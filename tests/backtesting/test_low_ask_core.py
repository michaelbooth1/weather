"""Synthetic witnesses for the received-time paper policy.

Guards: T093 / DESIGN_B LOW-ASK-1 cuts, causality, native units and locked cash.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from weather.backtesting.low_ask.contracts import (CITIES, FIRST, UTC, Refusal,
                                                  digest, iso, local_cut)
from weather.backtesting.low_ask.core import (candidate, running_minimum, select_band,
                                            simulate)
from weather.paths import repo_path

H = "a" * 64
PARSER = digest(repo_path("src/weather/market/metar_reports.py").read_bytes())


def synthetic_event(city="atlanta", day=FIRST):
    zone, station, unit = CITIES[city]
    return {"city": city, "family": "lowest", "target_date": day.isoformat(),
            "event_id": f"synthetic-{city}-{day}", "received_utc": iso(local_cut(day, zone, 17) - timedelta(days=1)),
            "rule_received_utc": iso(local_cut(day, zone, 17) - timedelta(days=1)),
            "rule_sha256": H, "rule_status": "reviewed", "source": "metar_routine",
            "station": station, "unit": unit, "zone": zone, "rounding": "ties_to_higher_integer",
            "parser_sha256": PARSER, "fallback_required": False, "source_verified": True, "active": True,
            "bins": [{"band_id": "synthetic-band", "yes_token": f"yes-{city}-{day}",
                      "lower": None, "upper": None, "lower_closed": False, "upper_closed": False,
                      "tick": "0.01", "min_size": "5"}]}


def synthetic_rows(event=None, price="0.40", size="5"):
    event = event or synthetic_event()
    day = date.fromisoformat(event["target_date"])
    rows = {r: [] for r in ("events", "observations", "books", "heartbeats", "resolutions", "integrity")}
    rows["events"] = [event]
    for h in range(18):
        observed = datetime.combine(day, datetime.min.time(), ZoneInfo(event["zone"])) + timedelta(hours=h, minutes=5)
        observed = observed.astimezone(UTC)
        raw = f"METAR {event['station']} {observed:%d%H%M}Z 00000KT 10SM CLR 10/05 A3000"
        rows["observations"].append({"event_id": event["event_id"], "received_utc": iso(observed + timedelta(seconds=5)),
            "observed_utc": iso(observed), "source": "metar_routine", "station": event["station"],
            "report_key": iso(observed), "source_sequence": h + 1, "raw": raw,
            "raw_sha256": digest(raw.encode()), "native_value": None, "status": "valid", "parser_sha256": PARSER})
    token = event["bins"][0]["yes_token"]
    for hour in (17, 18):
        cut = local_cut(day, event["zone"], hour)
        execute = cut + timedelta(seconds=30)
        rows["books"].append({"event_id": event["event_id"], "received_utc": iso(execute),
            "response_utc": iso(execute - timedelta(seconds=1)), "exchange_utc": iso(execute - timedelta(seconds=1)),
            "yes_token": token, "book_id": f"book-{token}-{hour}", "full": True, "active": True,
            "integrity_ok": True, "asks": [[price, size], ["0.99", "100"]], "sequence": hour})
        for offset in (-60, 0, 30):
            rows["heartbeats"].append({"event_id": event["event_id"], "yes_token": token,
                                       "received_utc": iso(cut + timedelta(seconds=offset)), "ok": True})
    return rows


def run(rows, as_of=None):
    return simulate(rows, as_of=as_of or datetime(2026, 11, 18, 12, tzinfo=UTC), latency_seconds=Decimal(30))


def actual(result, city="atlanta", day=FIRST):
    return [r for r in result["decisions"] if r["city"] == city and r["target_date"] == day.isoformat()]


def resolution(event, hour=20, payout="1", revision=1, **changes):
    day = date.fromisoformat(event["target_date"])
    at = local_cut(day, event["zone"], 18) + timedelta(hours=hour - 18)
    row = {"event_id": event["event_id"], "yes_token": event["bins"][0]["yes_token"],
           "effective_utc": iso(at), "received_utc": iso(at), "revision": revision,
           "final": True, "payout_per_share": payout, "treatment": "normal", "evidence_sha256": H}
    row.update(changes)
    return row


@pytest.mark.parametrize("day,hour,expected", [
    (date(2026, 3, 7), 17, "2026-03-07T22:00:00Z"),
    (date(2026, 3, 8), 17, "2026-03-08T21:00:00Z"),
    (date(2026, 10, 31), 18, "2026-10-31T22:00:00Z"),
    (date(2026, 11, 1), 18, "2026-11-01T23:00:00Z"),
])
def test_dst_cuts_are_local_wall_time(day, hour, expected):
    assert iso(local_cut(day, "America/New_York", hour)) == expected


def test_date_line_and_pacific_next_utc_date():
    assert iso(local_cut(FIRST, "Pacific/Auckland", 17)) == "2026-11-17T04:00:00Z"
    assert iso(local_cut(FIRST, "Pacific/Honolulu", 18)) == "2026-11-18T04:00:00Z"
    rows = synthetic_rows(synthetic_event("seattle"))
    assert iso(local_cut(FIRST, "America/Los_Angeles", 18)) == "2026-11-18T02:00:00Z"
    assert [r["status"] for r in actual(run(rows), "seattle")] == ["filled", "filled"]


def test_five_shares_fees_reserve_and_no_daily_cash_reset():
    rows = synthetic_rows()
    result = run(rows)
    fills = actual(result)
    assert [r["shares"] for r in fills] == ["5", "5"]
    assert all(Decimal(r["fee_per_share"]) == Decimal("0.012") for r in fills)
    assert all(Decimal(r["reserve_per_share"]) == Decimal("0.01") for r in fills)
    assert Decimal(result["cash"]) == Decimal("295.780")
    assert Decimal(result["locked"]) == Decimal("4.220")
    assert Decimal(result["net_lower"]) == Decimal("-4.220")
    assert result["unresolved"] == 2
    assert result == run(deepcopy(rows))


def test_missing_and_stale_observations_skip():
    rows = synthetic_rows()
    rows["observations"] = []
    assert {r["reason"] for r in actual(run(rows))} == {"observation_coverage"}
    rows = synthetic_rows()
    rows["observations"] = rows["observations"][:15]
    assert {r["reason"] for r in actual(run(rows))} == {"observation_stale"}


def test_discovery_status_cannot_override_captured_execution_status():
    rows = synthetic_rows()
    rows["events"][0]["active"] = False
    assert [r["status"] for r in actual(run(rows))] == ["filled", "filled"]
    rows["books"][0]["active"] = False
    assert actual(run(rows))[0]["reason"] == "book_integrity"


def test_correction_received_after_cut_cannot_change_earlier_minimum():
    rows = synthetic_rows()
    # Only midnight has 10C; all other routine reports have 20C.
    for r in rows["observations"][1:]:
        r["raw"] = r["raw"].replace("10/05", "20/05")
    event = rows["events"][0]
    cut17 = local_cut(FIRST, event["zone"], 17)
    corrected = dict(rows["observations"][0], raw=rows["observations"][0]["raw"].replace("10/05", "20/05"),
                     received_utc=iso(cut17 + timedelta(minutes=1)), source_sequence=100)
    rows["observations"].append(corrected)
    assert running_minimum(event, rows["observations"], cut17)[0] == 50
    assert running_minimum(event, rows["observations"], cut17 + timedelta(hours=1))[0] == 68
    # Disappearing from a later source response does not delete the retained report.
    assert running_minimum(event, rows["observations"][:-1], cut17 + timedelta(hours=1))[0] == 50


def test_speci_does_not_replace_routine_at_same_key():
    rows = synthetic_rows()
    event = rows["events"][0]
    cut = local_cut(FIRST, event["zone"], 17)
    r = dict(rows["observations"][0], raw=rows["observations"][0]["raw"].replace("METAR", "SPECI").replace("10/05", "M20/M25"),
             received_utc=iso(cut - timedelta(seconds=5)), source_sequence=100)
    rows["observations"].append(r)
    assert running_minimum(event, rows["observations"], cut)[0] == 50


def test_native_rounding_t_group_and_negative_half_tie():
    rows = synthetic_rows(synthetic_event("toronto"))
    for r in rows["observations"]:
        r["raw"] += " RMK T10051010"
    event = rows["events"][0]
    assert running_minimum(event, rows["observations"], local_cut(FIRST, event["zone"], 17))[0] == 0


def test_verified_received_wu_fallback_is_allowed_but_stub_is_not():
    rows = synthetic_rows(synthetic_event("toronto"))
    event = rows["events"][0]
    event.update(source="wu_intraday", station="synthetic-configured-WU", fallback_required=True)
    for row in rows["observations"]:
        row.update(source="wu_intraday", station=event["station"], raw="synthetic WU print",
                   native_value="-0.5")
    cut = local_cut(FIRST, event["zone"], 17)
    assert running_minimum(event, rows["observations"], cut) == (0, None)
    event["source_verified"] = False
    assert running_minimum(event, rows["observations"], cut)[1] == "source_rule"


def test_ties_at_band_edge_require_exactly_one_container():
    event = synthetic_event()
    low = dict(event["bins"][0], upper="50", upper_closed=True)
    high = dict(event["bins"][0], band_id="upper", yes_token="upper", lower="50", lower_closed=False)
    event["bins"] = [low, high]
    assert select_band(event, Decimal(50)) == low
    high["lower_closed"] = True
    assert select_band(event, Decimal(50)) is None
    high["lower_closed"] = False
    low["upper_closed"] = False
    assert select_band(event, Decimal(50)) is None


@pytest.mark.parametrize("change,reason", [
    ({"response_utc": "2026-11-17T22:00:27Z"}, "book_integrity"),
    ({"exchange_utc": "2026-11-17T22:00:20Z"}, "book_integrity"),
    ({"active": False}, "book_integrity"),
    ({"integrity_ok": False}, "book_integrity"),
    ({"asks": [["0.40", "4.99"], ["0.41", "100"]]}, "partial_fill_refused"),
    ({"asks": [["0.99", "100"]]}, "price_limit"),
    ({"asks": []}, "no_ask"),
])
def test_first_full_book_failure_does_not_choose_later_favorable_book(change, reason):
    rows = synthetic_rows()
    rows["books"][0].update(change)
    later = dict(rows["books"][0], received_utc="2026-11-17T22:00:31Z", response_utc="2026-11-17T22:00:30Z",
                 exchange_utc="2026-11-17T22:00:30Z", active=True, integrity_ok=True,
                 asks=[["0.20", "100"]], book_id="later", sequence=99)
    rows["books"].append(later)
    assert actual(run(rows))[0]["reason"] == reason


def test_book_window_boundaries_and_pending_cut():
    rows = synthetic_rows()
    event = rows["events"][0]
    cut = local_cut(FIRST, event["zone"], 17)
    for offset, status in ((29, "skip"), (30, "filled"), (90, "filled"), (91, "skip")):
        at = cut + timedelta(seconds=offset)
        rows["books"][0].update(received_utc=iso(at), response_utc=iso(at), exchange_utc=iso(at))
        rows["heartbeats"].append({"event_id": event["event_id"], "yes_token": event["bins"][0]["yes_token"],
                                   "received_utc": iso(at), "ok": True})
        assert actual(run(rows))[0]["status"] == status
    rows["books"] = []
    assert actual(run(rows, cut + timedelta(seconds=50)))[0]["status"] == "pending"


def test_book_heartbeat_gap_and_minimum_size_refused():
    rows = synthetic_rows()
    rows["heartbeats"] = []
    assert {r["reason"] for r in actual(run(rows))} == {"book_integrity"}
    rows = synthetic_rows()
    rows["events"][0]["bins"][0]["min_size"] = "5.01"
    assert {r["reason"] for r in actual(run(rows))} == {"minimum_size"}


def test_physical_snapshot_liquidity_cannot_be_used_twice():
    rows = synthetic_rows()
    rows["books"][1]["book_id"] = rows["books"][0]["book_id"]
    decisions = actual(run(rows))
    assert decisions[0]["status"] == "filled"
    assert decisions[1]["reason"] == "depth_reuse"


def test_ambiguous_revision_and_morning_coverage_refuse():
    rows = synthetic_rows()
    event = rows["events"][0]
    cut = local_cut(FIRST, event["zone"], 17)
    conflict = dict(rows["observations"][0], raw=rows["observations"][0]["raw"].replace("10/05", "20/05"))
    rows["observations"].append(conflict)
    with pytest.raises(Refusal, match="ambiguous_revision"):
        running_minimum(event, rows["observations"], cut)
    rows = synthetic_rows()
    rows["observations"] = rows["observations"][6:]
    assert running_minimum(event, rows["observations"], cut)[1] == "observation_coverage"


def test_resolution_receipt_delay_void_and_correction_cash():
    rows = synthetic_rows()
    event = rows["events"][0]
    cut18 = local_cut(FIRST, event["zone"], 18)
    rows["resolutions"] = [resolution(event, hour=17, received_utc=iso(cut18 + timedelta(minutes=30)))]
    before = run(rows, cut18 + timedelta(minutes=15))
    assert before["unresolved"] == 2 and Decimal(before["cash"]) == Decimal("295.780")
    after = run(rows, cut18 + timedelta(hours=1))
    assert after["unresolved"] == 0 and Decimal(after["cash"]) == Decimal("305.780")
    rows["resolutions"] = [resolution(event, payout="0.40", treatment="refund")]
    refund = run(rows)
    assert Decimal(refund["net_lower"]) == Decimal("-0.220")
    rows["resolutions"].append(resolution(event, hour=21, payout="0", revision=2))
    assert Decimal(run(rows)["net_lower"]) == Decimal("-4.220")


def test_late_integrity_failure_preserves_population_and_loss_bound():
    rows = synthetic_rows()
    event = rows["events"][0]
    rows["resolutions"] = [resolution(event)]
    rows["integrity"] = [{"event_id": event["event_id"], "book_id": rows["books"][0]["book_id"],
                          "ok": False, "received_utc": "2026-11-18T10:00:00Z", "evidence_sha256": H}]
    result = run(rows)
    assert len(actual(result)) == 2 and result["doubtful_fills"] == 1
    assert Decimal(result["net_lower"]) == Decimal("0.780")


def test_known_bad_proof_is_not_filled_and_repeat_receipt_cannot_undo_correction():
    rows = synthetic_rows()
    event = rows["events"][0]
    rows["integrity"] = [{"event_id": event["event_id"], "book_id": rows["books"][0]["book_id"],
                          "ok": False, "received_utc": "2026-11-17T22:00:29Z", "evidence_sha256": H}]
    assert actual(run(rows))[0]["reason"] == "book_integrity"
    repeat = dict(rows["observations"][0], received_utc="2026-11-17T21:59:00Z", source_sequence=99)
    rows["observations"].append(repeat)
    with pytest.raises(Refusal, match="first_seen_identity"):
        run(rows)


def test_separate_account_global_cash_locks_and_no_reset():
    combined = {k: [] for k in synthetic_rows()}
    for delta in range(4):
        for city in CITIES:
            rows = synthetic_rows(synthetic_event(city, FIRST + timedelta(days=delta)), price="0.98", size="100")
            for key in combined:
                combined[key].extend(rows[key])
    result = run(combined, datetime(2026, 11, 22, tzinfo=UTC))
    fills = [d for d in result["decisions"] if d["status"] == "filled"]
    assert len(fills) == 60
    assert Decimal(result["locked"]) <= 300 and Decimal(result["cash"]) >= 0
    assert any(d.get("reason") == "cash_cap" for d in result["decisions"])
    assert fills[:2][0]["city"] == "atlanta"  # Earliest UTC, then city slug.


def test_wrong_date_family_station_and_unsupported_fallback():
    rows = synthetic_rows()
    rows["events"][0]["target_date"] = "2026-11-16"
    with pytest.raises(Refusal, match="date_scope"):
        run(rows)
    rows = synthetic_rows()
    rows["events"][0]["family"] = "highest"
    with pytest.raises(Refusal, match="event_scope"):
        run(rows)
    rows = synthetic_rows()
    rows["events"][0]["station"] = "KBKF"
    assert {d["reason"] for d in actual(run(rows))} == {"source_rule"}
    rows = synthetic_rows()
    rows["events"][0]["fallback_required"] = True
    assert {d["reason"] for d in actual(run(rows))} == {"source_rule"}
