"""111k: tied NBP knots, identity inside WeatherUniverse, captured-set mass, forecast gaps.

The tie trace uses a tracked public NBP bulletin (tests/fixtures/nbm_target_fix,
KAUS 2026-09-17 01Z); everything else is synthetic. No production data.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import pytest

from maker_core.contracts import OutcomeView, Unavailable
from weather.market.maker_plugin.fair_value import WeatherFairValue, integrate, model_id, percentile_cdf
from weather.market.maker_plugin.nbp import parse
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.market.maker_plugin_runner import run
from tests.market.test_maker_plugin import NOW as BASE_NOW, bulletin, fixture
from tests.market.test_maker_plugin_111a import token_rows, write_tokens
from tests.market.test_maker_plugin_111j import outcomes, t1_layout, two_day_bulletin
from tests.market.test_maker_plugin_dry_run import NOW

KAUS = Path(__file__).parents[1] / "fixtures" / "nbm_target_fix" / "20260917T01Z-KAUS.txt"


def raw_bulletin(text, station, target, fetched):
    return {"text": text, "station_id": station, "target_date": target.isoformat(), "fetched_at": fetched.isoformat(),
            "payload_hash": hashlib.sha256(text.encode()).hexdigest()}


def frozen_110b_cdf(knots, x):
    """The 110b interpolation verbatim, for strictly increasing knots."""
    qs = (.10, .25, .50, .75, .90)
    if not math.isfinite(x):
        return 0.0 if x < 0 else 1.0
    index = next((i for i in range(4) if x <= knots[i + 1]), 3)
    value = qs[index] + (x - knots[index]) * (qs[index + 1] - qs[index]) / (knots[index + 1] - knots[index])
    return max(0., min(1., value))


def test_real_kaus_bulletin_tie_traced_from_text_to_band_probabilities():
    text = KAUS.read_text()
    # Bulletin text, verbatim (the target maximum is the first token of group 0):
    #   UTC    00  12| ...      FHR    23  35| ...
    #   TXNP1  97  71| TXNP2  98  72| TXNP5  99  73| TXNP7 100  74| TXNP9 100  75
    assert "TXNP7 100  74|" in text and "TXNP9 100  75|" in text
    issue = datetime(2026, 9, 17, 1, tzinfo=timezone.utc)
    target = date(2026, 9, 17)  # 9/16 20:00 CDT at issue: the T+1 maximum, valid 9/18 00Z (FHR 23).
    parsed_issue, knots, slot = parse(raw_bulletin(text, "KAUS", target, issue + timedelta(hours=1)), "KAUS", target)
    assert parsed_issue == issue and slot[:3] == (0, 0, 23.0)
    assert knots == (97., 98., 99., 100., 100.)  # P75 = P90: whole-degree rounding, not a parse error.
    assert model_id(knots) == "nbp-v2-piecewise-linear-atoms-resolution-tails"
    bands = {"le96": (-math.inf, 96.5), "97": (96.5, 97.5), "98": (97.5, 98.5), "99": (98.5, 99.5),
             "100": (99.5, 100.5), "ge101": (100.5, math.inf)}
    joint = integrate(bands, lambda x: percentile_cdf(knots, x))
    # By hand: F(96.5) = .10 - .5 * .15; F(97.5) = .175; F(98.5) = .375; F(99.5) = .625;
    # F(100.5) = .90 + .5 * .15: the tied P75/P90 pair is read one degree apart (Amendment 2).
    expected = {"le96": .025, "97": .15, "98": .2, "99": .25, "100": .35, "ge101": .025}
    assert joint == pytest.approx(expected, abs=1e-12)
    assert math.fsum(joint.values()) == pytest.approx(1, abs=1e-12)


def test_strictly_increasing_knots_keep_the_frozen_110b_values_and_identity():
    knots = (93., 94., 95., 96., 97.)
    xs = [-math.inf, math.inf] + [80 + i / 4 for i in range(120)]
    assert [percentile_cdf(knots, x) for x in xs] == [frozen_110b_cdf(knots, x) for x in xs]
    assert model_id(knots) == "nbp-v2-piecewise-linear"


@pytest.mark.parametrize("knots, below, above", [
    ((70., 70., 72., 74., 76.), .025, None),  # Tied first pair: tail at .15 per degree (Amendment 2).
    ((70., 72., 74., 76., 76.), None, .975),  # Tied last pair.
    ((70., 72., 72., 72., 76.), None, None),  # Interior atom of mass .50.
])
def test_tied_knots_are_atoms_of_a_monotone_cdf(knots, below, above):
    xs = [60 + i / 8 for i in range(160)]
    values = [percentile_cdf(knots, x) for x in xs]
    assert values == sorted(values) and values[0] == 0 and values[-1] == 1
    if below is not None:
        assert percentile_cdf(knots, knots[0] - .5) == pytest.approx(below)
    if above is not None:
        assert percentile_cdf(knots, knots[4] + .5) == pytest.approx(above)
    if knots[1:4] == (72., 72., 72.):
        # F(72.5) = .75 + .5 * .15 / 4 and F(71.5) = .10 + 1.5 * .15 / 2: the .50 atom plus both slopes.
        assert percentile_cdf(knots, 72.5) - percentile_cdf(knots, 71.5) == pytest.approx(.76875 - .2125)


def test_decreasing_knots_are_refused():
    text = KAUS.read_text().replace("TXNP9 100  75|", "TXNP9  98  75|", 1)
    target = date(2026, 9, 17)
    with pytest.raises(ValueError, match="decreasing_percentile_knots"):
        parse(raw_bulletin(text, "KAUS", target, datetime(2026, 9, 17, 2, tzinfo=timezone.utc)), "KAUS", target)


def tied_bulletin(spec):
    issue = BASE_NOW.replace(hour=13)
    lines = [f" {spec.icao} NBM V4.3 NBP GUIDANCE {issue:%m/%d/%Y %H%M} UTC", "FHR   -1 11| 23 35"]
    for code, value in zip(("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"),
                           (70, 75, 75, 80, 85, 75, 8)):
        lines.append(f"{code:<6} 40 {value}| 41 {value}")
    return "\n".join(lines) + "\n"


def test_tied_bulletin_is_evaluated_end_to_end_with_captured_set_verdict(tmp_path):
    spec = fixture(lead=1, now=NOW)[2]
    args, folder, _ = t1_layout(tmp_path, text=tied_bulletin(spec))
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert not [k for k in summary["unavailable"] if k.startswith(("descriptor:", "fair_value:"))]
    assert summary["coverage"]["fair_value_model.lead1.nbp-v2-piecewise-linear-atoms"] == 3
    assert summary["coverage"]["end_to_end.lead1"] == 3
    assert summary["captured_set_mass"] == {"lead1.complete_unit_mass": 1}
    assert summary["verdict"]["bar"] == "PASS"
    assert "**Exam-line plugin bar: PASS.**" in (args.output / "report.md").read_text()
    # Each NBP view carries what a hand check needs; recomputing from it gives the view.
    for outcome in outcomes(args):
        read = outcome["nbp_read"]
        assert read["knots"] == [70., 75., 75., 80., 85.] and read["slot"] == [1, 1, 35.0]
        assert read["source_payload"] and read["issue"] == BASE_NOW.replace(hour=13).isoformat()
        bands = {cid: tuple(float(v) for v in edges) for cid, edges in read["bands"].items()}
        joint = integrate(bands, lambda x: percentile_cdf(tuple(read["knots"]), x))
        assert outcome["fair_value"]["p_yes"] == joint[outcome["condition_id"]]


def test_unbooked_band_leaves_captured_set_complete_and_all_band_partial(tmp_path):
    # Band 3 (tokens 104/105) is not in 88a's selected set: no book at any minute.
    args, folder, _ = t1_layout(tmp_path, uncaptured_tokens=("104", "105"))
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert summary["unavailable"] == {"descriptor:book_not_captured": 1}
    assert summary["mass_coverage"] == {"partial": 1}
    assert summary["all_band_mass"] == {"lead1.partial": 1}
    assert summary["captured_set_mass"] == {"lead1.complete_unit_mass": 1}
    assert not summary["captured_set_reasons"]
    record = outcomes(args)
    assert [o["captured_by_88a"] for o in record] == [True, True, False]
    mass = json.loads((args.output / "report.json").read_bytes())["records"][0]["probability_mass"]
    # The unbooked band's mass is in the joint, so the captured marginals sum below one.
    assert mass["captured_set"]["joint_sum"] == pytest.approx(1)
    assert mass["captured_set"]["sum_available"] < 1 and mass["captured_set"]["bands"] == 2
    verdict = summary["verdict"]
    assert verdict["bar"] == "PASS"
    assert "complete with unit mass on 1 of 1 lead-1 records" in verdict["mass_statement"]
    assert "complete on 0 lead-1 records" in verdict["mass_statement"]  # All-band count beside it.


def test_verdict_fails_without_lead1_evaluation(tmp_path):
    args, _, _ = t1_layout(tmp_path)  # No band capture at all.
    summary = run(args)
    assert summary["verdict"]["bar"] == "FAIL"
    assert summary["captured_set_mass"] == {"lead1.partial": 1}
    assert summary["captured_set_reasons"] == {"lead1.descriptor:missing_captured_band_metadata": 3}
    failed = {c["check"] for c in summary["verdict"]["checks"] if not c["pass"]}
    assert failed == {"end_to_end.lead1 > 0", "lead-1 records with complete unit mass over the captured band set > 0"}


def identity_rows(rows, when, tokens=None):
    return [{"event_slug": r["event_slug"], "captured_at_utc": when.isoformat(), "condition_id": r["condition_id"],
             "bin_kind": r["bin_kind"], "bin_value_c": r["bin_value_c"], "bin_value_hi_c": r["bin_value_hi_c"],
             "tokens": (tokens or {}).get(r["condition_id"], {"YES": r["clob_yes_token_id"], "NO": r["clob_no_token_id"]})}
            for r in rows]


def test_identity_check_lives_in_the_universe_for_every_caller():
    base, rows, spec, target, discovery, books = fixture(lead=1)
    market = base.discover(BASE_NOW, 2).markets[0]
    later = identity_rows(rows, BASE_NOW + timedelta(days=1))
    raw = bulletin(spec, target)
    # No point-in-time discovery: the batch cannot be verified, whoever asks.
    alone = WeatherUniverse(identity_band_rows=later)
    with pytest.raises(ValueError, match="band_identity_unverified"):
        alone.bands(market.event_id, BASE_NOW)
    assert WeatherFairValue(alone, bulletins=[raw]).evaluate(market, BASE_NOW).reason == "band_identity_unverified"
    # Discovery listing exactly the batch's contracts verifies it.
    verified = WeatherUniverse(discovery=[discovery], books=[books], identity_band_rows=later)
    assert set(verified.bands(market.event_id, BASE_NOW)) == {r["condition_id"] for r in rows}
    assert isinstance(WeatherFairValue(verified, bulletins=[raw]).evaluate(market, BASE_NOW), OutcomeView)
    assert verified.describe(market.condition_id, BASE_NOW).source_hashes["band_basis"] == "condition_identity"
    # Discovery before its capture clock is not point in time.
    with pytest.raises(ValueError, match="band_identity_unverified"):
        verified.bands(market.event_id, BASE_NOW - timedelta(hours=1))
    # Another YES token under the same condition: refused for descriptors and fair value alike.
    other = identity_rows(rows, BASE_NOW + timedelta(days=1),
                          {rows[0]["condition_id"]: {"YES": "999", "NO": rows[0]["clob_no_token_id"]}})
    wrong = WeatherUniverse(discovery=[discovery], books=[books], identity_band_rows=other)
    with pytest.raises(ValueError, match="band_identity_mismatch"):
        wrong.discover(BASE_NOW, 2)
    assert WeatherFairValue(wrong, bulletins=[raw]).evaluate(market, BASE_NOW).reason == "band_identity_mismatch"
    # A point-in-time band capture never needs discovery.
    assert set(WeatherUniverse(band_rows=rows, identity_band_rows=other).bands(market.event_id, BASE_NOW)) == {
        r["condition_id"] for r in rows}


def test_observed_discovery_is_point_in_time():
    _, rows, _, _, discovery, _ = fixture(lead=1)
    universe = WeatherUniverse(identity_band_rows=identity_rows(rows, BASE_NOW + timedelta(days=1)))
    with pytest.raises(ValueError, match="band_identity_unverified"):
        universe.bands(rows[0]["event_slug"], BASE_NOW)
    universe.observe_discovery([discovery])
    assert len(universe.bands(rows[0]["event_slug"], BASE_NOW)) == 3


ISSUE = BASE_NOW.replace(hour=13)  # Valid until the 19Z cycle's expected availability, 20:00Z.


@pytest.mark.parametrize("bulletins, gap", [
    ([], "no_bulletin"),
    ([dict(ISSUE=ISSUE, fetched=ISSUE + timedelta(minutes=70))], "expired_next_cycle_not_captured"),
    ([dict(ISSUE=ISSUE, fetched=ISSUE + timedelta(minutes=70)),
      dict(ISSUE=ISSUE.replace(hour=19), fetched=ISSUE.replace(hour=20, minute=45))], "expired_next_cycle_fetched_late"),
    ([dict(ISSUE=ISSUE, fetched=ISSUE.replace(hour=20, minute=10))], "fetched_after_expiry"),
    ([dict(ISSUE=ISSUE, fetched=ISSUE + timedelta(minutes=70), other_target=True)], "no_cycle_with_target"),
])
def test_missing_forecast_gap_is_classified(bulletins, gap):
    universe, _, spec, target, _, _ = fixture(lead=1)
    market = universe.discover(BASE_NOW, 2).markets[0]
    as_of = ISSUE.replace(hour=20, minute=30)
    raws = []
    for b in bulletins:
        raw = bulletin(spec, target + timedelta(days=3) if b.get("other_target") else target,
                       issue=b["ISSUE"], fetched=b["fetched"])
        raws.append(dict(raw, target_date=target.isoformat()))
    provider = WeatherFairValue(universe, bulletins=raws)
    view = provider.evaluate(market, as_of)
    assert isinstance(view, Unavailable) and view.reason == "missing_point_in_time_forecast"
    assert provider.forecast_gap(market, as_of) == gap


def test_dry_run_reports_the_gap_of_each_missing_forecast(tmp_path):
    spec = fixture(lead=1, now=NOW)[2]
    args, folder, _ = t1_layout(tmp_path, text=two_day_bulletin(spec).replace("-1 11| 23 35", "-1 11"))
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert summary["coverage"]["missing_forecast.lead1.no_cycle_with_target"] == 3
    # Issue 13Z, expected at 14Z; the manifest's 15:15Z capture bounds availability: 75 min late.
    assert [k for k in summary["coverage"] if k.startswith("nbp_capture_vs_expected_availability.")] == [
        "nbp_capture_vs_expected_availability.late_over_60m"]
    assert {o["forecast_gap"] for o in outcomes(args)} == {"no_cycle_with_target"}
