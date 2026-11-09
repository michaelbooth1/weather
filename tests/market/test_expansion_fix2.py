"""Guards: T046 N1-N3, dated empty-source evidence, per-family conditions and S6 divergences."""

import itertools
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from weather.market.hko_settlement import HKODailyExtractAdapter, parse_daily_extract
from weather.market.metar_reports import parse_metar
from weather.market.metar_settlement import MetarSettlementAdapter, possible_bins
from weather.market.settlement_public import PublicSettlementClient
from weather.market.venue_settlement_rules import settlement_bucket
from weather.market.weather_universe import load_weather_universe, parse_bin_label
from weather.sources.metar_history import report_temperature_c

U = load_weather_universe()
UTC = timezone.utc
DAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 9, 6, tzinfo=UTC)
DEADLINE = datetime(2026, 11, 10, 4, 59, tzinfo=UTC)
START, END = datetime(2026, 11, 5, tzinfo=UTC), datetime(2026, 11, 10, 12, tzinfo=UTC)
F_BINS = [parse_bin_label(label) for label in ("63°F or below", "64-65°F", "66-67°F", "68-69°F", "70°F or higher")]
C_BINS = [parse_bin_label(label) for label in ("13°C or below", "14°C", "15°C or higher")]
HK_BINS = [parse_bin_label(label, continuous=True) for label in ("26°C or below", "27°C", "28°C", "29°C", "30°C", "31°C or higher")]


def report(raw, receipt=None):
    return parse_metar(raw, START, END, receipt_time=receipt)


def evaluate(records, city="toronto", as_of=NOW, **kwargs):
    return MetarSettlementAdapter().evaluate(U[city], DAY, records, as_of=as_of, **kwargs)


def hko_snapshot(high, low, read_at=None):
    raw = json.dumps({"stn": {"data": [{"month": 11, "dayData": [
        ["05", "1020", high, "25", low, "20", "70", "50", "0"]]}]}})
    return parse_daily_extract(raw, 2026, 11, read_at=read_at)


@pytest.mark.parametrize("missing_family", ["highest", "lowest"])
@pytest.mark.parametrize("verified", [False, True])
def test_hko_fallback_is_per_family(missing_family, verified):
    now = datetime(2026, 11, 13, 5, tzinfo=UTC)
    high, low = ("***", "23.1") if missing_family == "highest" else ("30.3", "***")
    snapshot = hko_snapshot(high, low, now)
    adapter = HKODailyExtractAdapter(lambda day: snapshot)
    present_family = "lowest" if missing_family == "highest" else "highest"
    result = adapter.evaluate(U["hong-kong"], date(2026, 11, 5), as_of=now,
                              family=present_family, initial_publication_verified=verified)
    assert result.status == ("final" if verified else "initial_publication_unverified")
    assert result.status_for(missing_family) == "lowest_bracket_fallback"
    assert result.maximum == (None if missing_family == "highest" else Decimal("30.3"))
    assert result.minimum == (None if missing_family == "lowest" else Decimal("23.1"))
    if not verified:
        assert all(p.possible for p in possible_bins(result, present_family, HK_BINS))
    # Even a result requested for the missing family cannot contaminate the present family.
    missing = adapter.evaluate(U["hong-kong"], date(2026, 11, 5), as_of=now, family=missing_family)
    assert missing.status == "lowest_bracket_fallback"
    assert all(p.possible for p in possible_bins(missing, present_family, HK_BINS))


@pytest.mark.parametrize("read_at", [None, datetime(2026, 11, 6, tzinfo=UTC), datetime(2026, 11, 14, tzinfo=UTC)])
def test_stale_unknown_and_future_hko_empty_reads_do_not_resolve(read_at):
    result = HKODailyExtractAdapter(lambda day: hko_snapshot("***", "***", read_at)).evaluate(
        U["hong-kong"], date(2026, 11, 5), as_of=datetime(2026, 11, 13, 5, tzinfo=UTC))
    assert result.status != "lowest_bracket_fallback"
    assert all(p.possible for p in possible_bins(result, "highest", HK_BINS))


@pytest.mark.parametrize("read_at", [None, DEADLINE-timedelta(seconds=1), DEADLINE+timedelta(hours=1)])
def test_wu_empty_requires_a_post_deadline_read_available_as_of_evaluation(read_at):
    result = evaluate([], as_of=DEADLINE, wu_empty=True, wu_read_at=read_at)
    assert result.status == "awaiting_wu_fallback"
    assert all(p.possible for p in possible_bins(result, "highest", C_BINS))
    result = evaluate([], as_of=DEADLINE, wu_empty=True, wu_read_at=DEADLINE)
    assert result.status == "lowest_bracket_fallback"
    for item in possible_bins(result, "highest", C_BINS):
        assert item.conditional_until == DEADLINE
        assert item.invalidating_events == ("wu_publication_or_revision", "clearly_erroneous_print_correction")


def test_hko_and_wu_conditions_use_the_source_that_decided_the_result():
    now = datetime(2026, 11, 13, 5, tzinfo=UTC)
    hko = HKODailyExtractAdapter(lambda day: hko_snapshot("30.3", "***", now)).evaluate(
        U["hong-kong"], date(2026, 11, 5), as_of=now, initial_publication_verified=True)
    highest = possible_bins(hko, "highest", HK_BINS)
    lowest = possible_bins(hko, "lowest", HK_BINS)
    assert all(p.conditional_until == now for p in highest)
    assert all(p.conditional_until == datetime(2026, 11, 13, 4, 59, tzinfo=UTC) for p in lowest)
    assert all(p.invalidating_events == ("hko_publication_or_revision", "clearly_erroneous_print_correction") for p in highest+lowest)
    wu = evaluate([], as_of=DEADLINE, wu_values=(Decimal(14), Decimal(3)))
    assert all(p.conditional_until == DEADLINE and "wu_publication_or_revision" in p.invalidating_events
               for p in possible_bins(wu, "highest", C_BINS))


def test_valid_t_group_governs_over_two_body_temperatures():
    records = [report("METAR KLGA 081500Z 18/04 RMK T01780040"),
               report("METAR KLGA 081800Z 20/04 21/05 RMK T02060040"),
               report("METAR KLGA 090500Z 10/04")]
    result = evaluate(records, city="nyc")
    assert result.status == "final"
    assert result.maximum == 69
    assert [p.interval.label for p in possible_bins(result, "highest", F_BINS) if p.possible] == ["68-69°F"]


@pytest.mark.parametrize("defect", ["20/04 21/05", "20/04 RMK T02060040 T02160040", "2X/04", "20/04 RMK T02X"])
def test_an_unusable_routine_report_cannot_be_silently_dropped_from_final(defect):
    # Last case has a usable body, so it remains a full report despite its bad T-token.
    records = [report("METAR KLGA 081500Z 18/04 RMK T01780040"),
               report(f"METAR KLGA 081800Z {defect}"), report("METAR KLGA 090500Z 10/04")]
    result = evaluate(records, city="nyc")
    if records[1].temperature_c is not None:
        assert result.status == "final"
    else:
        assert result.status == "parse_incomplete"
        assert "routine_day_parse_defect" in result.notes
        assert [p.possible for p in possible_bins(result, "highest", F_BINS)] == [False, True, True, True, True]
        assert [p.possible for p in possible_bins(result, "lowest", F_BINS)] == [True, True, False, False, False]


def test_true_temperature_absence_and_replaced_defects_are_distinct():
    valid = report("METAR CYYZ 081500Z 14/04")
    missing = report("METAR CYYZ 081800Z NIL")
    assert not missing.has_parse_defect
    assert evaluate([valid, missing, report("METAR CYYZ 090500Z 10/04")]).status == "final"
    assert evaluate([report("METAR CYYZ 081800Z 2X/04"), report("METAR CYYZ 090500Z 10/04")],
                    as_of=DEADLINE, wu_empty=True, wu_read_at=DEADLINE).status == "source_unavailable"
    old = report("METAR CYYZ 081800Z 2X/04", datetime(2026, 11, 8, 18, 5, tzinfo=UTC))
    fix = report("METAR COR CYYZ 081800Z 15/04", datetime(2026, 11, 8, 18, 40, tzinfo=UTC))
    result = evaluate([fix, old, report("METAR CYYZ 090500Z 10/04")])
    assert (result.status, result.maximum) == ("final", 15)


def test_outside_window_and_invalid_calendar_time_are_distinct():
    start, end = datetime(2026, 11, 8, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC)
    old = parse_metar("METAR CYYZ 071800Z 14/04", start, end)
    invalid = parse_metar("METAR CYYZ 311800Z 14/04", start, end)
    assert "outside_fetch_window" in old.flags and not old.has_parse_defect
    assert invalid.has_unreadable_time
    result = evaluate([report("METAR CYYZ 081800Z 14/04"), invalid, report("METAR CYYZ 090500Z 10/04")])
    assert result.status == "final"  # No receipt time can attribute this invalid stamp to a day.


def test_unattributed_lines_are_diagnostics_without_station_day_effects():
    text = "METAR CYYZ 081500Z 14/04\nMETAR ??? 081800Z 21/05\nMETAR CYYZ 090500Z 10/04"
    reports, diagnostics = PublicSettlementClient(get=lambda url: text).metars(["CYYZ"], NOW)
    assert all(r.station == "CYYZ" for r in reports)
    assert diagnostics["parse_flags"]["unattributed_lines"] == 1
    result = evaluate(reports)
    assert (result.status, result.maximum) == ("final", 14)


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_receipt_order_wins_for_every_list_permutation(order):
    records = [report("METAR CYYZ 081800Z 20/04", datetime(2026, 11, 8, 18, 5, tzinfo=UTC)),
               report("METAR COR CYYZ 081800Z 15/04", datetime(2026, 11, 8, 18, 40, tzinfo=UTC)),
               report("METAR CYYZ 090500Z 10/04", datetime(2026, 11, 9, 5, 3, tzinfo=UTC))]
    result = evaluate([records[i] for i in order])
    assert (result.status, result.maximum, result.cutoff) == ("final", 15, records[2].receipt_time)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("receipt_kind", ["unknown", "mixed", "tied"])
def test_ambiguous_revision_order_is_rejected_inside_evaluate(reverse, receipt_kind):
    receipt = datetime(2026, 11, 8, 18, 5, tzinfo=UTC)
    first = report("METAR CYYZ 081800Z 20/04", receipt if receipt_kind != "unknown" else None)
    second = report("METAR COR CYYZ 081800Z 15/04", receipt if receipt_kind == "tied" else None)
    records = [first, second]
    if reverse:
        records.reverse()
    result = evaluate(records + [report("METAR CYYZ 090500Z 10/04")])
    assert result.status == "source_unavailable"
    assert "ambiguous_routine_revision" in result.notes
    assert all(p.possible for p in possible_bins(result, "highest", C_BINS))


@pytest.mark.parametrize("extra", ["SPECI CYYZ 081800Z 25/04", "METAR CYYZ 081800Z  14/04"])
def test_special_or_whitespace_variants_do_not_create_a_revision_conflict(extra):
    text = "METAR CYYZ 090500Z 10/04\nMETAR CYYZ 081800Z 14/04\n" + extra
    client = PublicSettlementClient(get=lambda url: text)
    records, diagnostics = client.metars(["CYYZ"], NOW)
    assert "ambiguous_source_revision" not in diagnostics["parse_flags"]
    result = evaluate(records)
    assert (result.status, result.maximum) == ("final", 14)


@pytest.mark.parametrize("raw,legacy_bucket,strict_bucket", [
    ("06/M03 RMK T00562039", 43, 42),
    ("06/M03 RMK T00560039 T00610039", 42, None),
    ("06/M03 07/M03", 43, None),
    ("12/// RMK AO2", None, 54),
])
def test_additional_legacy_divergence_classes_are_documented_not_changed(raw, legacy_bucket, strict_bucket):
    raw = "METAR KDEN 081800Z " + raw
    legacy, _ = report_temperature_c(raw)
    strict = report(raw).temperature_c
    assert (None if legacy is None else settlement_bucket(legacy, "F")) == legacy_bucket
    assert (None if strict is None else settlement_bucket(strict, "F")) == strict_bucket
