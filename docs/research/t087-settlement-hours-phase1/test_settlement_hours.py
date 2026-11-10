"""Synthetic only. No fixture file, runtime store, network or Gamma read."""
from copy import deepcopy
import csv
import io
from datetime import date, datetime, time, timedelta, timezone

import pytest

import settlement_hours as sh


def observation(local, c, market="nyc", prefix="METAR", cor=False, receipt=None, declared=3):
    spec = sh.SPECS[market]
    valid = datetime.fromisoformat(local).astimezone(timezone.utc)
    station = "KDEN" if market == "denver" else spec.icao
    tenths = round(abs(c) * 10)
    token = f"T{int(c < 0)}{tenths:03d}"
    raw = f"{prefix} {station} {valid:%d%H%M}Z {'COR ' if cor else ''}00000KT 10SM 10/00 A3000 RMK {token}"
    row = {"valid": valid.isoformat(), "metar": raw.strip(), "declared_report_type": declared}
    if receipt:
        row["receipt_time"] = receipt
    return row


def day(rows, *, market="nyc", target="2026-10-24", hours=27, end_hour=0, bands=None, paid=None):
    spec = sh.SPECS[market]
    end = datetime.combine(date.fromisoformat(target) + timedelta(days=1), time(end_hour), spec.tz)
    station = "KDEN" if market == "denver" else spec.icao
    if bands is None:
        bands = ["67 F or below", "68-69 F", "70-71 F", "72 F or above"]
    end_text = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"market_id": market, "target_date": target,
            "resolution_source_url": f"https://aviationweather.gov/api/data/metar?ids={station}&format=raw&date={end_text}&hours={hours}",
            "bands": bands, "paid_band": paid or bands[-1], "observations": rows, "complete": True}


def run(row):
    return sh.analyze({"schema": sh.SCHEMA, "through": sh.THROUGH.isoformat(), "days": [row]}, synthetic=True)


def result(row):
    output = run(row)
    assert output["refusals"] == []
    return output["comparable_days"][0]


def test_front_previous_evening_warmer_paid_extended():
    row = day([observation("2026-10-23T21:00:00-04:00", 22),
               observation("2026-10-24T14:00:00-04:00", 20)])
    output = run(row)
    assert output["differing_market_days"] == 1
    got = output["differences"][0]
    assert got["strict"]["degree"] == 68
    assert got["linked_through_day_end"]["degree"] == 72
    assert got["linked_matches_paid"] and not got["strict_matches_paid"]
    assert output["expected_market_days"] == 216
    assert len(output["missing_keys"]) == 215
    assert output["effective_dates"] == ["2026-10-24"]


@pytest.mark.parametrize("paid,strict_match,linked_match", [("68-69 F", True, False), ("70-71 F", False, False)])
def test_paid_can_match_strict_or_neither(paid, strict_match, linked_match):
    got = result(day([observation("2026-10-23T21:00:00-04:00", 22),
                      observation("2026-10-24T14:00:00-04:00", 20)], paid=paid))
    assert got["strict_matches_paid"] is strict_match
    assert got["linked_matches_paid"] is linked_match


def test_27_and_30_with_different_end_anchors_share_21_start():
    nyc = result(day([observation("2026-10-23T21:00:00-04:00", 22),
                      observation("2026-10-24T14:00:00-04:00", 20)]))
    chi = result(day([observation("2026-10-23T21:00:00-05:00", 22, "chicago"),
                      observation("2026-10-24T14:00:00-05:00", 20, "chicago")],
                     market="chicago", hours=30, end_hour=3))
    assert nyc["bands_differ"] and chi["bands_differ"]
    assert not nyc["next_morning_tail_not_read"]
    assert chi["next_morning_tail_not_read"]
    assert datetime.fromisoformat(chi["linked_start_utc"]).astimezone(sh.SPECS["chicago"].tz).hour == 21


def test_27_vs_30_at_same_03_anchor_changes_which_evening_is_included():
    rows = [observation("2026-10-23T21:00:00-05:00", 22, "chicago"),
            observation("2026-10-24T14:00:00-05:00", 20, "chicago")]
    assert result(day(rows, market="chicago", hours=30, end_hour=3))["bands_differ"]
    assert not result(day(rows, market="chicago", hours=27, end_hour=3))["bands_differ"]


def test_30_at_midnight_needs_18_and_is_refused_not_silently_clipped():
    output = run(day([observation("2026-10-24T14:00:00-04:00", 20)], hours=30))
    assert output["refusals"][0]["reason"] == "link_needs_observations_before_authorized_21"
    assert output["comparable_market_days"] == 0


def test_dst_fall_back_both_0130_and_elapsed_link_start():
    row = day([observation("2026-10-31T21:00:00-04:00", 30),
               observation("2026-10-31T22:00:00-04:00", 22),
               observation("2026-11-01T01:30:00-04:00", 20),
               observation("2026-11-01T01:30:00-05:00", 20)], target="2026-11-01")
    got = result(row)
    assert got["strict"]["routine_temperature_count"] == 2
    assert len(got["strict"]["maximum_times_utc"]) == 2
    assert got["linked_through_day_end"]["degree"] == 72  # 21:00 is outside this 27h link
    assert got["linked_start_utc"] == "2026-11-01T02:00:00+00:00"  # 22:00 EDT
    _, start, end = sh.bounds(sh.SPECS["nyc"], date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


def test_ties_keep_all_times_and_same_band_degree_change_is_not_difference():
    rows = [observation("2026-10-23T21:00:00-04:00", 20),
            observation("2026-10-24T13:00:00-04:00", 20),
            observation("2026-10-24T14:00:00-04:00", 20)]
    got = result(day(rows, paid="68-69 F"))
    assert len(got["strict"]["maximum_times_utc"]) == 2
    assert len(got["linked_through_day_end"]["maximum_times_utc"]) == 3
    assert not got["bands_differ"]
    assert got["strict_matches_paid"] and got["linked_matches_paid"]
    rows[0] = observation("2026-10-23T21:00:00-04:00", 20.6)
    got = result(day(rows, paid="68-69 F"))
    assert got["strict"]["degree"] == 68
    assert got["linked_through_day_end"]["degree"] == 69
    assert not got["bands_differ"]


@pytest.mark.parametrize("market,c,degree,bands", [
    ("nyc", 2.5, 37, ["36 F or below", "37 F or above"]),
    ("toronto", 15.5, 16, ["15 C or below", "16 C or above"]),
    ("toronto", -2.5, -2, ["-3 C or below", "-2 C or above"]),
])
def test_half_up_ties_reuse_native_repo_rounding(market, c, degree, bands):
    got = result(day([observation("2026-10-24T14:00:00-04:00", c, market)],
                     market=market, bands=bands))
    assert got["strict"]["degree"] == degree


def test_routine_filter_t_group_and_body_fallback():
    rows = [observation("2026-10-24T14:00:00-04:00", 20, prefix=""),
            observation("2026-10-24T15:00:00-04:00", 40, prefix="SPECI"),
            observation("2026-10-24T16:00:00-04:00", 41, prefix="", declared=None)]
    assert result(day(rows))["strict"]["degree"] == 68  # T0200 beats body 10/00
    rows[0]["metar"] = rows[0]["metar"].replace("10/00", "20/00").replace("T0200", "T0BAD")
    assert result(day(rows))["strict"]["degree"] == 68  # malformed T -> body 20


def test_correction_replaces_original_even_when_original_arrives_last():
    rows = [observation("2026-10-24T14:00:00-04:00", 20, cor=True),
            observation("2026-10-24T14:00:00-04:00", 24)]
    assert result(day(rows))["strict"]["degree"] == 68


def test_late_correction_uses_production_selector_and_timestamp_only_deadline():
    rows = [observation("2026-10-24T14:00:00-04:00", 20),
            observation("2026-10-24T14:00:00-04:00", 24, cor=True, receipt="2026-10-25T04:51:00Z")]
    row = day(rows)
    assert run(row)["refusals"][0]["reason"] == "correction_needs_next_routine_timestamp"
    row["next_routine_time_utc"] = "2026-10-25T04:51:00Z"
    got = result(row)
    assert got["strict"]["degree"] == 68 and got["rejected_late_corrections"] == 1


def test_denver_kden_and_utc_midnight_is_not_local_midnight():
    got = result(day([observation("2026-10-24T23:55:00-06:00", 20, "denver")], market="denver"))
    assert got["station"] == "KDEN" and got["strict"]["degree"] == 68


@pytest.mark.parametrize("local", ["2026-10-23T20:59:59-04:00", "2026-10-25T00:00:00-04:00"])
def test_envelope_excludes_before_21_and_at_next_midnight(local):
    assert run(day([observation(local, 20)]))["refusals"][0]["reason"] == "observation_outside_authorized_envelope"


def test_no_routine_no_fallback_unknown_paid_missing_band_and_incomplete():
    row = day([observation("2026-10-24T14:00:00-04:00", 40, prefix="SPECI")])
    assert run(row)["refusals"][0]["reason"] == "no_routine_temperature_in_window"
    row["complete"] = False
    assert run(row)["refusals"][0]["reason"] == "extract_not_certified_complete"
    row["complete"] = True
    row["paid_band"] = None
    assert run(row)["refusals"][0]["reason"] == "paid_band_not_final_or_not_in_event_menu"
    row["paid_band"] = "72 F or above"
    row["bands"] = ["67 F or below", "70 F or above"]
    assert run(row)["refusals"][0]["reason"] == "event_bands_do_not_partition_integer_degrees"


def test_refuse_extra_fields_duplicate_days_and_wrong_dates():
    row = day([observation("2026-10-24T14:00:00-04:00", 20)])
    row["price"] = 0.1
    assert run(row)["refusals"][0]["reason"] == "schema_fields"
    del row["price"]
    payload = {"schema": sh.SCHEMA, "through": sh.THROUGH.isoformat(), "days": [row]}
    with pytest.raises(sh.Refused, match="phase1_post_09_29_read_forbidden"):
        sh.analyze(payload)
    payload["days"].append(deepcopy(row))
    with pytest.raises(sh.Refused, match="out_of_scope_or_duplicate_market_date"):
        sh.analyze(payload, synthetic=True)
    payload["days"] = [row]
    row["target_date"] = "2026-11-10"
    with pytest.raises(sh.Refused, match="out_of_scope_or_duplicate_market_date"):
        sh.analyze(payload, synthetic=True)


def test_cli_phase1_guard_precedes_any_extract_file_open(tmp_path):
    with pytest.raises(SystemExit) as caught:
        sh.main(["--extract", str(tmp_path / "DOES_NOT_EXIST.json"), "--out", str(tmp_path / "out.json")])
    assert caught.value.code == 2
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("market", ["nyc", "toronto", "denver"])
def test_strict_reading_reproduces_production_daily_label_on_synthetic_csv(market):
    from weather.backtesting import venue_rule_labels as vrl

    rows = [observation("2026-10-24T13:00:00-04:00", 20.5, market),
            observation("2026-10-24T14:00:00-04:00", 24, market),
            observation("2026-10-24T14:00:00-04:00", 20.5, market, cor=True),
            observation("2026-10-24T15:00:00-04:00", 40, market, prefix="SPECI")]
    spec = sh.SPECS[market]
    bands = ["20 C or below", "21 C or above"] if market == "toronto" else None
    got = result(day(rows, market=market, bands=bands))
    # The production daily builder needs a later report to close the date.
    # This synthetic closure report is not part of the analysis extract.
    closure = observation("2026-10-25T14:00:00-04:00", 10, market)
    station = "KDEN" if market == "denver" else spec.icao
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["valid", "tmpc", "metar"])
    for row in rows + [closure]:
        writer.writerow([sh.utc(row["valid"]).strftime("%Y-%m-%d %H:%M"), 10, row["metar"]])
    reports = vrl.reports_from_csv(buffer.getvalue(), spec, station, declared_report_type=3)
    production = vrl.venue_daily_labels(reports, spec)["2026-10-24"]
    assert got["strict"]["degree"] == production["max_temp_bucket"]
    assert got["strict"]["max_native"] == production["max_temp"]
    assert got["strict"]["routine_temperature_count"] == production["label_routine_report_count"]
