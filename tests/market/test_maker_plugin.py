"""Offline synthetic captured-shape checks for handoff 110b."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import runpy

import pytest

from maker_core.contracts import OutcomeView, Pending, SettlementFact, Unavailable, ExposureModel
from maker_core.contracts.conformance import FixtureClock, check_conformance
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.maker_plugin.clock import WeatherInformationClock, STATION_ROUTINE_MINUTES
from weather.market.maker_plugin.exposure import WeatherExposure
from weather.market.maker_plugin.fair_value import WeatherFairValue, integrate, percentile_cdf
from weather.market.maker_plugin.inputs import digest, timestamp
from weather.market.maker_plugin.nbp import parse, slot_for_target_v2, valid_until
from weather.market.maker_plugin.settlement import WeatherSettlement, REVISION_FIELDS
from weather.market.maker_plugin.universe import WeatherUniverse

NOW = datetime(2030, 1, 10, 15, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "maker_plugin"
ORACLE = runpy.run_path(str(FIXTURES / "v2_slot_oracle.py"))


def envelope(payload, when, kind):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    result = {"sequence": 1, "captured_at_utc": when.isoformat(), "kind": kind,
              "response_bytes": len(raw.encode()), "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
              "body_stored": True, "http_status": 200, "body_utf8": raw}
    if kind == "discovery":
        result.update(representation="selection_projection", stored_sha256=result["response_sha256"],
                      content_sha256=result["response_sha256"], change_key="discovery:synthetic")
    return result


def fixture(city="nyc", lead=1, now=NOW):
    spec = next(s for s in BUILTIN_SPECS if s.id == city)
    target = now.astimezone(spec.tz).date() + timedelta(days=lead)
    slug = f"{spec.slug_prefix}-{target.strftime('%B').lower()}-{target.day}-{target.year}"
    captured = now - timedelta(minutes=5)
    bands = [("lte", 69, 69), ("eq", 70, 79), ("gte", 80, 80)] if spec.unit == "F" else [
        ("lte", 19, 19), ("eq", 20, 25), ("gte", 26, 26)]
    rows, markets, books = [], [], []
    for index, (kind, lo, hi) in enumerate(bands):
        cid = "0x" + f"{index + 1:064x}"
        yes, no = str(100 + 2 * index), str(101 + 2 * index)
        markets.append({"id": str(index), "conditionId": cid, "active": True, "closed": False,
                        "enableOrderBook": True, "outcomes": '["No", "Yes"]',
                        "clobTokenIds": json.dumps([no, yes]), "rewardsMinSize": 20})
        rows.append({"snapshot_id": "synthetic-snapshot", "captured_at_utc": captured.isoformat(),
                     "captured_at_local": captured.astimezone(spec.tz).isoformat(), "event_slug": slug,
                     "model_version": "synthetic-model", "feature_schema_version": "synthetic",
                     "condition_id": cid, "clob_yes_token_id": yes, "clob_no_token_id": no,
                     "bin_kind": kind, "bin_value_c": lo, "bin_value_hi_c": hi,
                     "range_label": f"synthetic-{index}", "model_probability": (.2, .6, .2)[index],
                     "market_yes": .4, "market_no": .6})
        books.extend({"market": cid, "asset_id": token, "timestamp": "1894287300000",
                      "tick_size": "0.01", "min_order_size": "5", "neg_risk": True,
                      "bids": [{"price": "0.4", "size": "75"}],
                      "asks": [{"price": "0.6", "size": "75"}]} for token in (yes, no))
    discovery = envelope([{"id": "event-synthetic", "slug": slug, "markets": markets}], captured, "discovery")
    books_record = envelope(books, captured, "books")
    universe = WeatherUniverse(discovery=[discovery], books=[books_record], band_rows=rows)
    return universe, rows, spec, target, discovery, books_record


def bulletin(spec, target, issue=NOW.replace(hour=13), fetched=NOW-timedelta(minutes=30), shift=0):
    valid = datetime.combine(target + timedelta(days=1), datetime.min.time(), timezone.utc)
    lead = (valid - issue).total_seconds() / 3600
    # 13/19Z carries minimum first: token 1 is the target maximum.
    lines = [f" {spec.icao} NBM V4.3 NBP GUIDANCE {issue:%m/%d/%Y %H%M} UTC",
             f"FHR   {lead - 12:g} {lead:g}"]
    for code, value in zip(("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"),
                           (65, 70, 75, 80, 85, 75, 8)):
        lines.append(f"{code:<6} 40 {value + shift}")
    text = "\n".join(lines) + "\n"
    return {"schema_version": "nbm_probabilistic_tmax_v0.1", "source": "nbm_probabilistic_tmax",
            "source_kind": "nbp_station_text", "station_id": spec.icao, "target_date": target.isoformat(),
            "source_url": None, "fetched_at": fetched.isoformat(),
            "payload_hash": hashlib.sha256(text.encode()).hexdigest(), "text": text}


def forecast(rows, spec, target, now=NOW):
    issue = now - timedelta(hours=1)
    return {"snapshot_id": "forecast-synthetic", "event_slug": rows[0]["event_slug"],
            "target_date": target.isoformat(), "source": "eccc", "forecast_kind": "daily_high",
            "captured_at_utc": (now - timedelta(minutes=30)).isoformat(),
            "provider_issue_time": issue.isoformat(), "provider_update_time": issue.isoformat(),
            "issue_time": issue.isoformat(), "issue_time_basis": "provider_issue_time",
            "valid_time": f"{target}T18:00:00+00:00", "forecast_high_c": 75 if spec.unit == "F" else 23}


def served_inputs(rows):
    base = {key: rows[0][key] for key in ("snapshot_id", "event_slug", "captured_at_utc")}
    explanation = {**base, "explanations": {"probability_calibration_context": {
        "afternoon_residual_centering": {"active": True, "reason": "afternoon_residual_centering_applied",
                                          "context_key": "market=nyc|afternoon", "shift": -.3}}}}
    source = {**base, "release_id": "synthetic-release", "release_manifest_sha256": "a" * 64,
              "release_identity_status": "verified_variant_serving_bundle"}
    return explanation, source


def ledger(rows, spec, target, previous=None, status="match", bucket=75):
    recorded = datetime.combine(target + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=15)
    row = {"schema_version": "settlement_ledger_v0.1", "event_slug": rows[0]["event_slug"],
           "market_id": spec.id, "target_date": target.isoformat(), "settlement_bucket": bucket,
           "settlement_high": bucket, "settlement_unit": spec.unit, "winning_band": "70-79 F",
           "winning_band_kind": "eq", "winning_band_value": 70, "winning_band_value_hi": 79,
           "polymarket_winning_band": "70-79 F", "reconciliation_status": status,
           "settlement_source": "wu_history", "finalized_at_utc": recorded.isoformat()}
    row["label_hash"] = digest(row)
    row.update(ledger_record_type="settlement_revision", revision_number=1 if not previous else 2,
               recorded_at_utc=(recorded + timedelta(hours=1 if previous else 0)).isoformat(),
               previous_label_hash=previous["label_hash"] if previous else None,
               supersedes_revision_id=previous["revision_id"] if previous else None)
    seed = {key: row.get(key) for key in ("event_slug", "revision_number", "recorded_at_utc", "label_hash", "supersedes_revision_id")}
    row["revision_id"] = "sha256:" + digest(seed)
    before = {k: v for k, v in (previous or {}).items() if k not in REVISION_FIELDS}
    after = {k: v for k, v in row.items() if k not in REVISION_FIELDS}
    row["revision_changes"] = [{"field": k, "old": before.get(k), "new": after.get(k)}
                               for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    row["revision_provenance"] = {"finalized_at_utc": row["finalized_at_utc"]}
    return row


@pytest.mark.parametrize("mode", ["nbp1", "nbp2", "fallback_F", "fallback_C", "served"])
def test_all_provider_conformance(mode):
    city = "toronto" if mode == "fallback_C" else "nyc"
    lead = 0 if mode == "served" else 2 if mode == "nbp2" else 1
    universe, rows, spec, target, _, _ = fixture(city, lead)
    kwargs = {}
    if mode.startswith("nbp"):
        kwargs["bulletins"] = [bulletin(spec, target)]
    elif mode.startswith("fallback"):
        kwargs["forecasts"] = [forecast(rows, spec, target)]
    else:
        explanation, source = served_inputs(rows)
        kwargs.update(snapshots=rows, explanations=[explanation], source_rows=[source])
    provider = WeatherFairValue(universe, **kwargs)
    information = WeatherInformationClock(universe)
    settlement = WeatherSettlement(universe)
    def advance():
        future_time = NOW + timedelta(hours=1)
        future_discovery = dict(universe.discovery[0], captured_at_utc=future_time.isoformat())
        universe.discovery += (future_discovery,)
        universe.band_rows += tuple(dict(r, captured_at_utc=future_time.isoformat()) for r in rows)
        settlement.ledger_rows += (ledger(rows, spec, target),)
        if "bulletins" in kwargs:
            future = bulletin(spec, target, fetched=NOW + timedelta(hours=1), shift=1)
            provider.bulletins += (future,)
            information.bulletins += (future,)
        elif "forecasts" in kwargs:
            future = dict(kwargs["forecasts"][0], captured_at_utc=(NOW+timedelta(hours=1)).isoformat(), forecast_high_c=99)
            provider.forecasts += (future,)
        else:
            provider.snapshots += tuple(dict(r, captured_at_utc=(NOW+timedelta(hours=1)).isoformat()) for r in rows)
    check_conformance(universe=universe, fair_value=provider, information=information,
        settlement=settlement, clock=FixtureClock(NOW, NOW-timedelta(hours=2), NOW+timedelta(days=1)),
        advance_inputs=advance)


@pytest.mark.parametrize("station", list(ORACLE["NBM_NBP_STATION_TIMEZONES"]) + ["CYYZ", "UNKNOWN"])
@pytest.mark.parametrize("cycle", [0, 1, 7, 12, 13, 19])
@pytest.mark.parametrize("target", [date(2030, 1, 11), date(2030, 1, 12), date(2030, 3, 10), date(2030, 11, 3)])
def test_v2_slot_parity(station, cycle, target):
    issue = datetime.combine(target-timedelta(days=1), datetime.min.time(), timezone.utc).replace(hour=cycle)
    rows = {"FHR": [(float(lead), float(lead+12)) for lead in range(0, 96, 24)]}
    # Include realistic 00Z labels at every tested cycle.
    offset = (24-cycle) % 24
    rows["FHR"] = [(float(offset+i*24), float(offset+i*24+12)) for i in range(4)]
    assert slot_for_target_v2(rows, issue, target, station) == ORACLE["_slot_for_target_v2"](rows, issue, target, station)


def test_nbp_parser_selects_maximum_not_minimum_and_tails():
    universe, _, spec, target, _, _ = fixture()
    raw = bulletin(spec, target)
    issue, knots, slot = parse(raw, spec.icao, target)
    assert knots == (65, 70, 75, 80, 85) and slot[1] == 1
    assert valid_until(issue) == NOW.replace(hour=20)
    markets = universe.discover(NOW, 2).markets
    views = [WeatherFairValue(universe, bulletins=[raw]).evaluate(m, NOW) for m in markets]
    assert all(isinstance(v, OutcomeView) for v in views)
    assert sum(v.p_yes for v in views) == pytest.approx(1)
    assert [v.p_yes for v in views] == pytest.approx([.235, .49, .275])
    for v in views:
        assert v.stdev == pytest.approx(math.sqrt(v.p_yes*(1-v.p_yes)) * (2/24+.25))
    assert percentile_cdf(knots, -100) == 0 and percentile_cdf(knots, 1000) == 1


@pytest.mark.parametrize("defect", ["missing", "future", "stale", "sentinel", "duplicate", "reversed", "hash", "clock", "conflict"])
def test_nbp_unavailable(defect):
    universe, _, spec, target, _, _ = fixture()
    raw = bulletin(spec, target)
    if defect == "future": raw["fetched_at"] = (NOW+timedelta(seconds=1)).isoformat()
    if defect == "stale": raw = bulletin(spec, target, issue=NOW.replace(hour=7))
    if defect == "sentinel": raw["text"] = raw["text"].replace("40 75", "40 -99")
    if defect == "duplicate": raw["text"] += "FHR   23 35\n"
    if defect == "reversed": raw["text"] = raw["text"].replace("40 70", "40 90")
    if defect == "clock": raw["fetched_at"] = NOW.replace(hour=12).isoformat()
    if defect != "hash": raw["payload_hash"] = hashlib.sha256(raw["text"].encode()).hexdigest()
    else: raw["payload_hash"] = "0"*64
    inputs = [] if defect == "missing" else [raw]
    if defect == "conflict": inputs.append(bulletin(spec, target, shift=1))
    result = WeatherFairValue(universe, bulletins=inputs).evaluate(universe.discover(NOW, 2).markets[1], NOW)
    assert isinstance(result, Unavailable)


def test_actual_price_fields_cannot_contaminate_fair_value():
    universe, rows, spec, target, discovery, books = fixture()
    raw = bulletin(spec, target)
    market = universe.discover(NOW, 2).markets[1]
    before = WeatherFairValue(universe, bulletins=[raw]).evaluate(market, NOW)
    for row in rows:
        row.update(market_yes=.99, market_no=.01, edge=999)
    altered = WeatherUniverse(discovery=[discovery], books=[books], band_rows=rows)
    assert WeatherFairValue(altered, bulletins=[raw]).evaluate(market, NOW) == before


@pytest.mark.parametrize("city", [s.id for s in BUILTIN_SPECS])
def test_registered_universe_and_exposure(city):
    universe, _, spec, target, _, _ = fixture(city)
    result = universe.discover(NOW, 2)
    assert len(result.markets) == 3
    for m in result.markets:
        assert m.native_unit == spec.unit and m.neg_risk_group == m.event_id
        assert m.min_order_size == 5  # reward minimum is 20
        assert m.outcome_tokens["YES"] in {"100", "102", "104"}
        assert m.close_at_utc.astimezone(spec.tz).date() == target+timedelta(days=1)
        assert isinstance(WeatherExposure(), ExposureModel)
        assert sum(WeatherExposure().factors(m).values()) == 1


def test_missing_metadata_refused_and_snapshot_inputs_detached():
    universe, rows, _, _, discovery, books = fixture()
    before = universe.discover(NOW, 2)
    rows[0]["bin_value_c"] = 999
    assert universe.discover(NOW, 2) == before
    with pytest.raises(ValueError, match="missing_captured_band"):
        WeatherUniverse(discovery=[discovery], books=[books]).discover(NOW, 2)


def test_partition_gap_overlap_and_missing_tail_fail_closed():
    for bands in ({"a": (-math.inf, 1), "b": (2, math.inf)},
                  {"a": (-math.inf, 2), "b": (1, math.inf)}, {"a": (0, 1)}):
        with pytest.raises(ValueError): integrate(bands, normal_cdf)


def normal_cdf(x):
    return (1+math.erf(x/math.sqrt(2)))/2


@pytest.mark.parametrize("defect", ["capture_fallback", "future", "stale", "target", "lead2", "conflict"])
def test_fallback_refuses_unproven_or_wrong_lead(defect):
    universe, rows, spec, target, _, _ = fixture(lead=2 if defect == "lead2" else 1)
    raw = forecast(rows, spec, target)
    if defect == "capture_fallback": raw.update(provider_issue_time=None, provider_update_time=None)
    if defect == "future": raw["captured_at_utc"] = (NOW+timedelta(minutes=1)).isoformat()
    if defect == "stale": raw.update(provider_issue_time=(NOW-timedelta(days=1)).isoformat())
    if defect == "target": raw["target_date"] = "2030-01-13"
    inputs = [raw]
    if defect == "conflict": inputs.append(dict(raw, forecast_high_c=100))
    assert isinstance(WeatherFairValue(universe, forecasts=inputs).evaluate(universe.discover(NOW, 2).markets[1], NOW), Unavailable)


@pytest.mark.parametrize("defect", ["stage", "release", "expiry", "future", "zero", "conflict"])
def test_served_unavailable(defect):
    universe, rows, _, _, _, _ = fixture(lead=0)
    explanation, source = served_inputs(rows)
    if defect == "stage": explanation["explanations"] = {}
    if defect == "release": source["release_identity_status"] = "research_unbound_non_countable"
    if defect == "zero": rows[1]["model_probability"] = 0
    if defect == "future": rows[1]["captured_at_utc"] = (NOW+timedelta(minutes=1)).isoformat()
    if defect == "conflict": rows.append(dict(rows[1], model_probability=.4))
    as_of = NOW+timedelta(minutes=10) if defect == "expiry" else NOW
    provider = WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source])
    assert isinstance(provider.evaluate(universe.discover(NOW, 2).markets[1], as_of), Unavailable)


def test_clock_schedules_and_observed_fetch_are_pit():
    universe, _, spec, target, _, _ = fixture()
    markets = universe.discover(NOW, 2).markets
    clock = WeatherInformationClock(universe, bulletins=[bulletin(spec, target)])
    events = clock.upcoming(markets, NOW, NOW+timedelta(hours=6))
    assert {e.scheduled_at_utc.minute for e in events if e.kind == "scheduled_print"} == {51}
    assert NOW.replace(hour=15, minute=30) in {e.scheduled_at_utc for e in events if e.kind == "model_cycle"}
    assert NOW.replace(hour=19) in {e.scheduled_at_utc for e in events if e.kind == "model_cycle"}
    assert clock.observe(markets, NOW-timedelta(hours=1)) == ()
    seen = clock.observe(markets, NOW)
    assert len(seen) == 3 and all(e.detected_at_utc == NOW-timedelta(minutes=30) for e in seen)


def test_new_high_decidedness_only_from_trusted_print():
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = {"reason": "wu_history_high_increased", "source": "wu_history", "previous_value": 74.,
           "current_value": 80., "previous_bucket": 74, "current_bucket": 80,
           "observed_at": (NOW-timedelta(minutes=1)).isoformat(), "detail": "Synthetic print.",
           "market_id": spec.id, "event_slug": rows[0]["event_slug"], "target_date": target.isoformat(),
           "unit": spec.unit, "current_captured_at_utc": NOW.isoformat(),
           "previous_captured_at_utc": (NOW-timedelta(minutes=2)).isoformat()}
    clock = WeatherInformationClock(universe, triggers=[row])
    assert clock.observe(markets, NOW-timedelta(seconds=1)) == ()
    events = clock.observe(markets, NOW)
    assert len([e for e in events if e.kind == "new_high"]) == 3
    assert len([e for e in events if e.kind == "decided"]) == 3
    assert WeatherInformationClock(universe, triggers=[dict(row, source="metar")]).observe(markets, NOW) == ()


def test_settlement_pit_reconciliation_and_revision_hashes():
    universe, rows, spec, target, _, _ = fixture()
    market = universe.discover(NOW, 2).markets[1]
    first = ledger(rows, spec, target, status="not_requested")
    second = ledger(rows, spec, target, previous=first)
    resolver = WeatherSettlement(universe, ledger_rows=[first, second])
    assert isinstance(resolver.resolve(market, NOW), Pending)
    assert isinstance(resolver.resolve(market, timestamp(first["recorded_at_utc"])), Pending)
    result = resolver.resolve(market, timestamp(second["recorded_at_utc"]))
    assert isinstance(result, SettlementFact) and result.p_yes == 1
    corrupted = dict(second, settlement_bucket=66)
    assert isinstance(WeatherSettlement(universe, ledger_rows=[first, corrupted]).resolve(
        market, timestamp(second["recorded_at_utc"])), Pending)
    assert isinstance(WeatherSettlement(universe, ledger_rows=[second]).resolve(
        market, timestamp(second["recorded_at_utc"])), Pending)


def test_ledger_fixture_matches_canonical_hash_validator():
    from weather.backtesting.settlement_ledger import verify_ledger_history
    _, rows, spec, target, _, _ = fixture()
    first = ledger(rows, spec, target)
    assert verify_ledger_history([first])["status"] == "PASS"


def test_integer_eq_band_and_zero_upper_bound():
    from weather.market.maker_plugin.inputs import band
    assert band({"bin_kind": "eq", "bin_value_c": -2, "bin_value_hi_c": 0}) == (-2.5, .5)
    assert band({"bin_kind": "eq", "bin_value_c": 0}) == (-.5, .5)


@pytest.mark.parametrize("city,expected", [("nyc", 1), ("los-angeles", 0)])
def test_local_midnight_horizon(city, expected):
    universe, _, _, _, _, _ = fixture(city, lead=0, now=NOW.replace(hour=6))
    assert len(universe.discover(NOW.replace(hour=8), 2).markets) == 3 * expected


@pytest.mark.parametrize("city", [s.id for s in BUILTIN_SPECS])
def test_every_station_minute(city):
    universe, _, spec, _, _, _ = fixture(city)
    events = WeatherInformationClock(universe).upcoming(universe.discover(NOW, 2).markets, NOW, NOW+timedelta(hours=1))
    assert {e.scheduled_at_utc.minute for e in events if e.kind == "scheduled_print"} == set(STATION_ROUTINE_MINUTES[spec.icao])


def test_ambiguous_slot_rejected_like_v2_and_invalid_bulletin_native_units():
    universe, _, spec, target, _, _ = fixture()
    issue = NOW.replace(hour=13)
    rows = {"FHR": [(35., None), (35., None)]}
    assert slot_for_target_v2(rows, issue, target, spec.icao) == ORACLE["_slot_for_target_v2"](rows, issue, target, spec.icao)
    assert slot_for_target_v2(rows, issue, target, spec.icao)[1] == "target_max_ambiguous"
    from dataclasses import replace
    market = replace(universe.discover(NOW, 2).markets[0], native_unit="C")
    assert isinstance(WeatherFairValue(universe, bulletins=[bulletin(spec, target)]).evaluate(market, NOW), Unavailable)


def test_served_market_prices_ignored_but_stage_and_release_retained():
    universe, rows, _, _, _, _ = fixture(lead=0)
    explanation, source = served_inputs(rows)
    market = universe.discover(NOW, 2).markets[1]
    def evaluate():
        return WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source]).evaluate(market, NOW)
    before = evaluate()
    assert before.p_yes == .6 and "afternoon_residual_centering" in before.model_id
    rows[1].update(market_yes=.99, market_no=.01, edge=-100)
    assert evaluate() == before
    explanation["explanations"]["probability_calibration_context"]["afternoon_residual_centering"]["shift"] = -.4
    assert evaluate().inputs_hash != before.inputs_hash


def test_closed_market_and_malformed_book_rules():
    universe, rows, _, _, discovery, books = fixture()
    payload = json.loads(discovery["body_utf8"])
    payload[0]["markets"][0]["closed"] = True
    closed = envelope(payload, NOW-timedelta(minutes=5), "discovery")
    assert len(WeatherUniverse(discovery=[closed], books=[books], band_rows=rows).discover(NOW, 2).markets) == 2
    book_rows = json.loads(books["body_utf8"])
    book_rows[0]["min_order_size"] = "6"
    mismatch = envelope(book_rows, NOW-timedelta(minutes=5), "books")
    with pytest.raises(ValueError, match="ambiguous_book_rules"):
        WeatherUniverse(discovery=[discovery], books=[mismatch], band_rows=rows).discover(NOW, 2)


def test_provider_offset_timestamps_normalized_naive_rejected():
    assert timestamp("2030-01-10T10:00:00-05:00") == NOW
    with pytest.raises(ValueError): timestamp("2030-01-10T15:00:00")


def test_settlement_reconciled_but_inconsistent_bucket_still_pending():
    universe, rows, spec, target, _, _ = fixture()
    row = ledger(rows, spec, target, bucket=65)
    market = universe.discover(NOW, 2).markets[0]
    result = WeatherSettlement(universe, ledger_rows=[row]).resolve(market, timestamp(row["recorded_at_utc"]))
    assert isinstance(result, Pending) and "excludes" in result.reason


def test_corrupted_nbp_cannot_silently_become_fallback():
    universe, rows, spec, target, _, _ = fixture()
    raw = bulletin(spec, target)
    raw["payload_hash"] = "0" * 64
    result = WeatherFairValue(universe, bulletins=[raw], forecasts=[forecast(rows, spec, target)]).evaluate(
        universe.discover(NOW, 2).markets[1], NOW)
    assert isinstance(result, Unavailable) and result.reason == "nbp_payload_hash_mismatch"
