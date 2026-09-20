"""Hermetic tests for weather.market.reward_share_estimate (tmp_path only)."""

from __future__ import annotations

import gzip
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.market import reward_share_estimate as rse


V = 4.5
CONDITION = "0x" + "a" * 64
OTHER_CONDITION = "0x" + "b" * 64
UNREWARDED = "0x" + "c" * 64
SLUG = "highest-temperature-in-testville-on-september-17-2026"
EVENT_DATE = "2026-09-17"

BIDS = [(0.39, 100.0), (0.38, 10.0), (0.30, 500.0)]
ASKS = [(0.41, 50.0), (0.43, 40.0)]
# Hand computation, midpoint 0.40, v = 4.5c, min size 20:
#   bid 0.39 x100 at 1c -> (3.5/4.5)^2 * 100 = 4900/81 ; 0.38 x10 below min -> 0 ; 0.30 beyond v -> 0
#   ask 0.41 x50 at 1c -> 2450/81 ; ask 0.43 x40 at 3c -> (1.5/4.5)^2 * 40 = 40/9
COMP_ONE = 4900.0 / 81.0
COMP_TWO = 2450.0 / 81.0 + 40.0 / 9.0
OWN_20_AT_1C = 20.0 * 49.0 / 81.0


def test_module_under_test_is_this_checkout():
    # A worktree run must not silently import the production checkout.
    expected_src = Path(__file__).resolve().parents[2] / "src"
    assert expected_src in Path(rse.__file__).resolve().parents


def test_filenames_match_order_book_tape():
    tape = pytest.importorskip("weather.market.order_book_tape")
    assert rse.RAW_BOOK_FILENAME == tape.RAW_BOOK_FILENAME
    assert rse.RAW_BOOK_GZIP_FILENAME == tape.RAW_BOOK_GZIP_FILENAME
    assert rse.GZIP_LONG_FILENAME == tape.GZIP_LONG_FILENAME
    assert rse.LONG_FILENAME == tape.LONG_FILENAME


# ---- scoring -------------------------------------------------------------

def test_order_score_known_points():
    assert rse.order_score(50.0, 0.0, V, 20.0) == pytest.approx(50.0)
    assert rse.order_score(50.0, V, V, 20.0) == 0.0
    assert rse.order_score(50.0, 6.0, V, 20.0) == 0.0
    assert rse.order_score(19.99, 0.0, V, 20.0) == 0.0
    assert rse.order_score(20.0, 0.0, V, 20.0) == pytest.approx(20.0)
    assert rse.order_score(90.0, 1.5, V, 20.0) == pytest.approx(90.0 * (3.0 / 4.5) ** 2)
    assert rse.order_score(90.0, -1.5, V, 20.0) == pytest.approx(40.0)
    assert rse.order_score(50.0, None, V, 20.0) == 0.0
    assert rse.order_score(50.0, 1.0, 0.0, 20.0) == 0.0


def test_q_min_c_rule_inside_and_two_sided_outside():
    assert rse.q_min(10.0, 8.0, 0.50) == pytest.approx(8.0)
    assert rse.q_min(9.0, 1.0, 0.50) == pytest.approx(3.0)
    assert rse.q_min(10.0, 0.0, 0.50) == pytest.approx(10.0 / 3.0)
    assert rse.q_min(10.0, 0.0, 0.10) == pytest.approx(10.0 / 3.0)
    assert rse.q_min(10.0, 0.0, 0.90) == pytest.approx(10.0 / 3.0)
    assert rse.q_min(10.0, 0.0, 0.05) == 0.0
    assert rse.q_min(10.0, 0.0, 0.95) == 0.0
    assert rse.q_min(9.0, 1.0, 0.95) == pytest.approx(1.0)


def test_scoring_agrees_with_maker_incentive_feasibility():
    feasibility = pytest.importorskip("weather.market.maker_incentive_feasibility")
    market = SimpleNamespace(rewards_min_size=Decimal("20"), rewards_max_spread_cents=Decimal("4.5"))
    rules = SimpleNamespace(
        multiplier=Decimal("1"), single_side_divisor=Decimal("3"),
        single_side_midpoint_low=Decimal("0.1"), single_side_midpoint_high=Decimal("0.9"),
    )
    for price, size, cents in (("0.39", "20", 1.0), ("0.37", "100", 3.0), ("0.35", "100", 5.0), ("0.39", "19", 1.0)):
        quote = feasibility.BuyQuote("YES", "1", Decimal(price), Decimal(size))
        theirs = feasibility._order_score(quote, Decimal(size), Decimal("0.40"), market, rules)
        assert rse.order_score(float(size), cents, V, 20.0) == pytest.approx(float(theirs))
    for one, two, mid in ((10, 8, "0.5"), (9, 1, "0.5"), (10, 0, "0.05"), (10, 0, "0.1")):
        theirs = feasibility._q_min(Decimal(one), Decimal(two), Decimal(mid), rules)
        assert rse.q_min(float(one), float(two), float(mid)) == pytest.approx(float(theirs))


# ---- share arithmetic, capital -------------------------------------------

def test_share_under_both_assumptions_hand_computed():
    result = rse.evaluate_sample(BIDS, ASKS, max_spread_cents=V, min_size=20.0)
    assert result["status"] == "ok"
    assert result["midpoint"] == pytest.approx(0.40)
    assert result["competing_q_one"] == pytest.approx(COMP_ONE)
    assert result["competing_q_two"] == pytest.approx(COMP_TWO)
    # (a) one two-sided competitor: min side (34.69) beats max side / 3 (20.16)
    assert result["competing_single"] == pytest.approx(COMP_TWO)
    # (b) many perfectly two-sided makers: mean of the sides
    assert result["competing_many"] == pytest.approx((COMP_ONE + COMP_TWO) / 2.0)
    assert result["qualifying_size_one"] == pytest.approx(100.0)
    assert result["qualifying_size_two"] == pytest.approx(90.0)

    quote = result["quotes"][(20.0, 1.0)]
    assert quote["bid_price"] == pytest.approx(0.39)
    assert quote["ask_price"] == pytest.approx(0.41)
    assert quote["own_q_min"] == pytest.approx(OWN_20_AT_1C)
    assert quote["share_single"] == pytest.approx(OWN_20_AT_1C / (OWN_20_AT_1C + COMP_TWO))
    assert quote["share_many"] == pytest.approx(OWN_20_AT_1C / (OWN_20_AT_1C + (COMP_ONE + COMP_TWO) / 2.0))
    assert quote["share_single"] > quote["share_many"]
    # capital: 20 * 0.39 on the YES bid + 20 * (1 - 0.41) on the NO bid
    assert quote["capital_pusd"] == pytest.approx(19.6)

    wide = result["quotes"][(100.0, 3.0)]
    assert wide["own_q_min"] == pytest.approx(100.0 / 9.0)
    assert wide["capital_pusd"] == pytest.approx(100 * 0.37 + 100 * (1 - 0.43))


def test_quote_sizes_below_band_minimum_are_not_run():
    result = rse.evaluate_sample(BIDS, ASKS, max_spread_cents=V, min_size=100.0)
    assert {size for size, _distance in result["quotes"]} == {100.0}
    # with min size 100 only the 100-share bid level still qualifies
    assert result["competing_q_one"] == pytest.approx(COMP_ONE)
    assert result["competing_q_two"] == 0.0
    assert result["competing_single"] == pytest.approx(COMP_ONE / 3.0)


def test_single_competitor_outside_interval_requires_two_sides():
    bids = [(0.04, 200.0)]
    asks = [(0.06, 10.0)]  # below min size: competitor is one-sided
    result = rse.evaluate_sample(bids, asks, max_spread_cents=V, min_size=20.0)
    assert result["midpoint"] == pytest.approx(0.05)
    assert result["competing_single"] == 0.0
    assert result["competing_many"] > 0.0
    quote = result["quotes"][(20.0, 1.0)]
    assert quote["share_single"] == pytest.approx(1.0)
    assert 0.0 < quote["share_many"] < 1.0
    # 5c from a 0.05 midpoint cannot be bid: one-sided, and outside [0.10, 0.90] that earns nothing
    far = rse.evaluate_sample(bids, asks, max_spread_cents=V, min_size=20.0, distances_cents=(5.0,))
    assert far["quotes"][(20.0, 5.0)]["bid_price"] is None
    assert far["quotes"][(20.0, 5.0)]["own_q_min"] == 0.0
    assert far["quotes"][(20.0, 5.0)]["share_single"] == 0.0


def test_half_cent_midpoint_snaps_quote_outward():
    quote = rse.hypothetical_quote(0.395, 1.0, 0.01)
    assert quote["bid_price"] == pytest.approx(0.38)
    assert quote["ask_price"] == pytest.approx(0.41)
    assert quote["bid_distance_cents"] == pytest.approx(1.5)
    assert quote["ask_distance_cents"] == pytest.approx(1.5)


def test_min_size_for_mid_moves_the_midpoint():
    bids = [(0.40, 5.0), (0.38, 100.0)]
    asks = [(0.42, 100.0)]
    plain = rse.evaluate_sample(bids, asks, max_spread_cents=V, min_size=20.0)
    adjusted = rse.evaluate_sample(bids, asks, max_spread_cents=V, min_size=20.0, min_size_for_mid=True)
    assert plain["midpoint"] == pytest.approx(0.41)
    assert adjusted["midpoint"] == pytest.approx(0.40)


def test_one_sided_and_crossed_books_are_not_scored():
    assert rse.evaluate_sample([], ASKS, max_spread_cents=V, min_size=20.0)["status"] == "one_sided_book"
    assert rse.evaluate_sample([(0.5, 30.0)], [(0.5, 30.0)], max_spread_cents=V, min_size=20.0)["status"] == "crossed_book"


def test_quote_capital():
    assert rse.quote_capital(100.0, 0.39, 0.41) == pytest.approx(98.0)
    assert rse.quote_capital(20.0, None, 0.06) == pytest.approx(18.8)
    assert rse.quote_capital(20.0, 0.04, None) == pytest.approx(0.8)


# ---- refusal --------------------------------------------------------------

def test_refuses_to_write_under_data(tmp_path):
    with pytest.raises(rse.OutputLocationRefused):
        rse.ensure_outside_data(tmp_path / "data" / "out")
    with pytest.raises(rse.OutputLocationRefused):
        rse.ensure_outside_data(tmp_path / "DATA" / "nested" / "out")
    with pytest.raises(rse.OutputLocationRefused):
        rse.ensure_outside_data(rse.DATA_ROOT / "analysis")
    with pytest.raises(rse.OutputLocationRefused):
        rse.ensure_outside_data(tmp_path / "books" / "x", extra_protected=[tmp_path / "books"])
    assert rse.ensure_outside_data(tmp_path / "out") == (tmp_path / "out").resolve()


# ---- end to end ------------------------------------------------------------

def _record(condition_id, outcome, captured_at_utc, bids, asks, *, local=None):
    return {
        "book": {
            "asks": [{"price": str(price), "size": str(size)} for price, size in asks],
            "bids": [{"price": str(price), "size": str(size)} for price, size in bids],
            "market": condition_id,
            "tick_size": "0.01",
        },
        "capture_id": f"{condition_id[-4:]}-{outcome}-{captured_at_utc}",
        "captured_at_utc": captured_at_utc,
        "token": {
            "captured_at_local": local or captured_at_utc.replace("+00:00", "-04:00"),
            "condition_id": condition_id,
            "outcome": outcome,
        },
    }


def _write_rates(path, **overrides):
    band = {
        "rate": 100.0, "min_size": 20, "max_spread_cents": V, "event_date": EVENT_DATE,
        "location_id": "testville", "event_slug": SLUG,
        "rates_by_days_to_event": {"0": 100.0},
    }
    band.update(overrides)
    path.write_text(json.dumps({"_meta": {"note": "ignored"}, CONDITION: band, "bad": {"rate": "x"}}), encoding="utf-8")
    return path


def _write_tape(folder, lines):
    folder.mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / rse.RAW_BOOK_GZIP_FILENAME, "wt", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def _standard_lines():
    local = "2026-09-17T08:00:05-04:00"
    return [
        json.dumps(_record(CONDITION, "Yes", "2026-09-17T12:00:05+00:00", BIDS, ASKS, local=local), sort_keys=True),
        json.dumps(_record(CONDITION, "No", "2026-09-17T12:00:06+00:00", [], [], local=local), sort_keys=True),
        json.dumps(_record(CONDITION, "Yes", "2026-09-17T12:00:40+00:00", BIDS, ASKS, local=local), sort_keys=True),
        json.dumps(_record(UNREWARDED, "Yes", "2026-09-17T12:00:41+00:00", BIDS, ASKS, local=local), sort_keys=True),
        "{this is not json",
        json.dumps({"book": "not an object"}),
        "",
        json.dumps(_record(CONDITION, "Yes", "2026-09-17T12:01:05+00:00", [], ASKS, local=local), sort_keys=True),
    ]


def _run(tmp_path, **kwargs):
    arguments = dict(
        rates_json=tmp_path / "rates.json", snapshots_root=tmp_path / "books",
        dates=[EVENT_DATE], output_dir=tmp_path / "out",
    )
    arguments.update(kwargs)
    return rse.run_estimate(**arguments)


def test_end_to_end_counts_shares_caps_and_outputs(tmp_path):
    _write_rates(tmp_path / "rates.json")
    _write_tape(tmp_path / "books" / SLUG, _standard_lines())
    report = _run(tmp_path)

    counters = report["counters"]
    assert counters["bands_invalid"] == 1
    assert counters["malformed_rows"] == 2
    assert counters["records_skipped_no_outcome"] == 1
    assert counters["records_skipped_unrewarded_condition"] == 1
    assert counters["records_skipped_same_minute"] == 1
    assert counters["minute_samples_used"] == 2
    assert report["bounds"]["truncated_by_max_rows"] is False
    assert report["sources"][0]["representation"] == "raw_jsonl_gzip"

    rows = {(row["quote_size"], row["quote_distance_cents"]): row for row in report["bands"]}
    row = rows[(20.0, 1.0)]
    assert row["days_to_event_class"] == "same_day"
    assert row["rate_basis"] == "exact_days_to_event"
    assert row["minutes_with_book_sample"] == 2
    assert row["scored_samples"] == 1
    assert row["sample_status_counts"] == {"ok": 1, "one_sided_book": 1}
    assert row["coverage_pct_of_1440_minutes"] == pytest.approx(100.0 * 2 / 1440)
    share_single = OWN_20_AT_1C / (OWN_20_AT_1C + COMP_TWO)
    assert row["mean_share_single"] == pytest.approx(share_single)
    assert row["reward_per_day_single"] == pytest.approx(share_single * 100.0)
    # never scaled up: the no-assumption figure counts unsampled minutes as zero
    assert row["reward_sampled_minutes_only_single"] == pytest.approx(share_single * 100.0 / 1440)
    assert row["mean_capital_pusd"] == pytest.approx(19.6)
    assert row["reward_per_day_per_100_pusd_single"] == pytest.approx(share_single * 100.0 / 19.6 * 100.0)
    assert row["exceeds_cap"] == {"10": True, "50": False, "200": False}
    assert rows[(100.0, 1.0)]["exceeds_cap"] == {"10": True, "50": True, "200": False}

    fleet = {(t["quote_size"], t["quote_distance_cents"]): t for t in report["fleet_totals"]}
    total = fleet[(20.0, 1.0)]
    assert total["location_id"] == "ALL"
    assert total["min_size_class"] == "min_size_20"
    assert total["within_cap"]["10"]["bands"] == 0
    assert total["within_cap"]["10"]["bands_flagged_over_cap"] == 1
    assert total["within_cap"]["10"]["reward_per_day_single"] == 0.0
    assert total["within_cap"]["50"]["reward_per_day_single"] == pytest.approx(share_single * 100.0)
    assert report["location_totals"][0]["location_id"] == "testville"

    written = json.loads((tmp_path / "out" / rse.JSON_OUTPUT_NAME).read_text(encoding="utf-8"))
    assert written["schema_version"] == rse.SCHEMA_VERSION
    markdown = (tmp_path / "out" / rse.MARKDOWN_OUTPUT_NAME).read_text(encoding="utf-8")
    assert "Not a receivable" in markdown
    assert "testville" in markdown


def test_custom_cap_is_reported_and_rate_fallback_is_flagged(tmp_path):
    _write_rates(tmp_path / "rates.json", rates_by_days_to_event={"1": 40.0}, rate=40.0, rate_days_to_event=1)
    _write_tape(tmp_path / "books" / SLUG, _standard_lines())
    report = _run(tmp_path, cap_pusd=25.0)
    row = next(r for r in report["bands"] if r["quote_size"] == 20.0 and r["quote_distance_cents"] == 1.0)
    assert row["rate_basis"] == "fallback_other_days_to_event"
    assert row["daily_rate"] == 40.0
    assert row["exceeds_cap"] == {"25": False, "50": False, "200": False}
    assert report["fleet_totals"][0]["bands_rate_not_exact_days_to_event"] == 1


def test_days_to_event_uses_local_capture_date(tmp_path):
    _write_rates(tmp_path / "rates.json")
    line = json.dumps(_record(
        CONDITION, "Yes", "2026-09-17T02:00:05+00:00", BIDS, ASKS, local="2026-09-16T22:00:05-04:00",
    ), sort_keys=True)
    _write_tape(tmp_path / "books" / SLUG, [line])
    report = _run(tmp_path)
    assert {row["days_to_event_class"] for row in report["bands"]} == {"T+1"}
    assert {row["rate_basis"] for row in report["bands"]} == {"fallback_other_days_to_event"}


def test_empty_inputs_write_an_honest_empty_report(tmp_path):
    _write_rates(tmp_path / "rates.json")
    (tmp_path / "books").mkdir()
    report = _run(tmp_path)
    assert report["bands"] == []
    assert report["fleet_totals"] == []
    assert report["sources"] == [{"event_slug": SLUG, "status": "no_closed_book_source"}]
    assert report["coverage"]["rewarded_bands_without_any_sample"] == [CONDITION]
    assert "(no scored samples)" in (tmp_path / "out" / rse.MARKDOWN_OUTPUT_NAME).read_text(encoding="utf-8")

    _write_tape(tmp_path / "books" / SLUG, [])
    assert _run(tmp_path)["bands"] == []

    no_match = _run(tmp_path, dates=["2026-01-01"])
    assert no_match["sources"] == []
    assert no_match["coverage"]["rewarded_bands_in_scope"] == 0


def test_live_files_are_refused_unless_allowed(tmp_path):
    _write_rates(tmp_path / "rates.json")
    folder = tmp_path / "books" / SLUG
    folder.mkdir(parents=True)
    (folder / rse.RAW_BOOK_FILENAME).write_text(_standard_lines()[0] + "\n", encoding="utf-8")
    assert _run(tmp_path)["sources"][0]["status"] == "no_closed_book_source"
    allowed = _run(tmp_path, allow_live_files=True)
    assert allowed["sources"][0]["representation"] == "raw_jsonl"
    assert allowed["counters"]["minute_samples_used"] == 1


def test_max_rows_is_a_hard_stop_and_is_reported(tmp_path):
    _write_rates(tmp_path / "rates.json")
    _write_tape(tmp_path / "books" / SLUG, _standard_lines())
    report = _run(tmp_path, max_rows=1)
    assert report["bounds"]["truncated_by_max_rows"] is True
    assert report["bounds"]["rows_read"] == 1
    assert report["counters"]["minute_samples_used"] == 1


def test_max_events_bounds_the_run(tmp_path):
    second_slug = SLUG.replace("testville", "othertown")
    rates = {
        CONDITION: {"rate": 1.0, "min_size": 20, "max_spread_cents": V, "event_date": EVENT_DATE,
                    "location_id": "testville", "event_slug": SLUG},
        OTHER_CONDITION: {"rate": 1.0, "min_size": 20, "max_spread_cents": V, "event_date": EVENT_DATE,
                          "location_id": "othertown", "event_slug": second_slug},
    }
    (tmp_path / "rates.json").write_text(json.dumps(rates), encoding="utf-8")
    (tmp_path / "books").mkdir()
    report = _run(tmp_path, max_events=1)
    assert report["bounds"]["events_selected"] == 1
    assert report["bounds"]["events_dropped_by_max_events"] == [SLUG]
    assert report["sources"][0]["event_slug"] == second_slug


def test_corrupt_gzip_is_counted_not_fatal(tmp_path):
    _write_rates(tmp_path / "rates.json")
    folder = tmp_path / "books" / SLUG
    folder.mkdir(parents=True)
    (folder / rse.RAW_BOOK_GZIP_FILENAME).write_bytes(b"this is not gzip data")
    report = _run(tmp_path)
    assert report["sources"][0]["status"] == "read_error_partial"
    assert report["counters"]["unreadable_files"] == 1


def test_long_csv_fallback_groups_levels_and_counts_bad_rows(tmp_path):
    _write_rates(tmp_path / "rates.json")
    folder = tmp_path / "books" / SLUG
    folder.mkdir(parents=True)
    header = "capture_id,captured_at_utc,captured_at_local,event_slug,market_id,polymarket_market_id,condition_id,range_label,outcome,clob_token_id,side,level_index,price,size,cumulative_size"
    base = f"2026-09-17T12:00:05+00:00,2026-09-17T08:00:05-04:00,{SLUG},testville,1,{CONDITION},20C"
    rows = [header]
    for side, levels in (("bid", BIDS), ("ask", ASKS)):
        for index, (price, size) in enumerate(levels, start=1):
            rows.append(f"cap1,{base},Yes,tok,{side},{index},{price},{size},0")
    rows.append(f"cap1,{base},Yes,tok,ask,9,not-a-price,5,0")
    rows.append(f"cap2,{base},No,tok2,bid,1,0.59,50,0")
    with gzip.open(folder / rse.GZIP_LONG_FILENAME, "wt", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(rows) + "\n")
    report = _run(tmp_path)
    assert report["sources"][0]["representation"] == "gzip_csv"
    assert report["counters"]["malformed_rows"] == 1
    assert report["counters"]["records_skipped_no_outcome"] == 1
    row = next(r for r in report["bands"] if r["quote_size"] == 20.0 and r["quote_distance_cents"] == 1.0)
    assert row["mean_share_single"] == pytest.approx(OWN_20_AT_1C / (OWN_20_AT_1C + COMP_TWO))


# ---- rates extraction and CLI ---------------------------------------------

def _snapshot(target_date, rate):
    return {
        "verified_for_target_date": target_date,
        "markets": [
            {"condition_id": CONDITION.upper().replace("0X", "0x"), "event_date": EVENT_DATE,
             "location_id": "testville", "event_slug": SLUG, "question": "q",
             "liquidity_rewards": {"current_daily_rate_usdc": rate, "rewards_min_size": 20.0,
                                   "rewards_max_spread_cents": 4.5}},
            {"condition_id": UNREWARDED, "event_date": EVENT_DATE, "location_id": "testville",
             "event_slug": SLUG, "liquidity_rewards": {"current_daily_rate_usdc": 0.0,
                                                       "rewards_min_size": 20.0, "rewards_max_spread_cents": 4.5}},
            {"condition_id": OTHER_CONDITION, "event_date": "2026-09-18", "location_id": "testville",
             "event_slug": "x", "liquidity_rewards": {"current_daily_rate_usdc": 7.0,
                                                      "rewards_min_size": 100.0, "rewards_max_spread_cents": 4.5}},
        ],
    }


def test_extract_rates_files_each_rate_under_its_days_to_event(tmp_path):
    early = tmp_path / "early.json"
    same_day = tmp_path / "same_day.json"
    early.write_text(json.dumps(_snapshot("2026-09-16", 40.0)), encoding="utf-8")
    same_day.write_text(json.dumps(_snapshot("2026-09-17", 100.0)), encoding="utf-8")
    mapping = rse.extract_rates([early, same_day], dates=[EVENT_DATE])
    assert set(mapping) == {"_meta", CONDITION}
    band = mapping[CONDITION]
    assert band["rates_by_days_to_event"] == {"1": 40.0, "0": 100.0}
    assert band["rate"] == 100.0
    assert band["rate_days_to_event"] == 0
    assert (band["min_size"], band["max_spread_cents"], band["location_id"]) == (20.0, 4.5, "testville")
    assert UNREWARDED in rse.extract_rates([same_day], dates=[EVENT_DATE], include_unrewarded=True)


def test_cli_extract_then_estimate_and_refusals(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(_snapshot("2026-09-17", 100.0)), encoding="utf-8")
    rates = tmp_path / "rates.json"
    assert rse.main(["extract-rates", "--snapshot", str(snapshot), "--output", str(rates), "--dates", EVENT_DATE]) == 0
    assert rse.main(["extract-rates", "--snapshot", str(snapshot), "--output", str(tmp_path / "data" / "r.json")]) == 2

    _write_tape(tmp_path / "books" / SLUG, _standard_lines())
    common = ["estimate", "--rates-json", str(rates), "--snapshots-root", str(tmp_path / "books"), "--dates", EVENT_DATE]
    assert rse.main(common + ["--output-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / rse.JSON_OUTPUT_NAME).is_file()
    assert rse.main(common + ["--output-dir", str(tmp_path / "data" / "out")]) == 2
    assert not (tmp_path / "data").exists()
    assert rse.main(common + ["--output-dir", str(tmp_path / "books" / "out")]) == 2
    assert rse.main(common + ["--output-dir", str(tmp_path / "out2"), "--max-rows", "1"]) == 3
    assert "REFUSED" in capsys.readouterr().err
