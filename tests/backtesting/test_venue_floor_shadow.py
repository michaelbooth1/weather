from types import SimpleNamespace

import pytest

from weather.backtesting.venue_floor_shadow import evaluate_floor_shadow
from weather.backtesting.venue_floor_band_shadow import evaluate_floor_band_shadow, presentation_sha256


def fixture(family="highest", unit="F", as_of="2026-08-10T20:00:00Z"):
    spec = SimpleNamespace(slug="test-market", station_id="KZZZ", market_unit=unit,
                           settlement_kind="metar_routine", timezone="UTC", families=("highest", "lowest"))
    identity = dict(market=spec.slug, station="KZZZ", unit=unit, family=family)
    prior = dict(**identity, target_date="2026-08-10", as_of=as_of, capture_sha256="1" * 64, model_sha256="4" * 64,
                 stage="post_live_signals", mass={"90": .1, "92": .4, "94": .3, "96": .2})
    rule = dict(**identity, basis="retrospective_current_rule", sha256="2" * 64)
    evidence = dict(source="awc_raw_metar", station="KZZZ", capture_sha256="3" * 64, complete=True,
                    through=as_of, reports=[], **{"from": "2026-08-10T00:00:00Z"})
    return spec, dict(**identity, target_date="2026-08-10", as_of=as_of, rule=rule,
                      prior=prior, evidence=evidence, incumbent_bound=94)


def row(raw, receipt="2026-08-10T16:01:00Z"):
    return {"raw": raw, "receipt_time": receipt}


def band_fixture():
    spec, packet = fixture()
    prior = packet["prior"]
    prior.update(stage="pre_calibration_model", calibration=dict(
        capture_sha256="5" * 64, artifact_sha256="6" * 64, resolution_weight=0, cutoff_hour=20,
        exact_distribution={"temperature": 1},
    ))
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z 33/20 RMK T03330200")]
    p = {k: packet[k] for k in ("market", "station", "family", "unit", "as_of", "target_date")}
    p.update(
        recorded_at=packet["as_of"], prior_capture_sha256=prior["capture_sha256"], model_sha256=prior["model_sha256"],
        artifact_sha256=prior["calibration"]["artifact_sha256"], calibration_capture_sha256=prior["calibration"]["capture_sha256"],
        context={"observed_floor_bucket": 94, "cutoff_hour": 20, "lockin_strength": 0},
        distribution_kind="native_integer", boundary_active=False, market_bin={"preserve_distribution_coherence": True},
        exact_distribution={"temperature": 1}, final_degree_mass={"90": 0, "92": 0, "94": .6, "96": .4},
        bands=[
            dict(label=label, kind=kind, value=lo, value_hi=hi, model_probability=prob)
            for label, kind, lo, hi, prob in (
                ("91°F or below", "lte", 91, 91, 0), ("92-93°F", "eq", 92, 93, 0),
                ("94-95°F", "eq", 94, 95, .6), ("96°F or higher", "gte", 96, 96, .4),
            )
        ],
    )
    return spec, packet, p


def project_bands(spec, packet, p):
    packet["prior"]["presentation_sha256"] = presentation_sha256(p)
    return evaluate_floor_band_shadow(packet, spec, p)


def test_public_band_shadow_resuppresses_degree_only_and_reports_unredistributed_mass():
    spec, packet, p = band_fixture()
    result = project_bands(spec, packet, p)
    assert result["status"] == "closed_incumbent"
    assert result["incumbent_bound"] == 94 and result["candidate_bound"] == 92
    assert result["incumbent"]["public"] == result["presentation_only"]["public"] == [0, 0, .6, .4]
    assert result["native"]["candidate"][1] == pytest.approx(4 / 9)
    assert result["degree_only"]["public"] == pytest.approx([0, 0, 3 / 9, 2 / 9])
    assert result["degree_only"]["removed"] == pytest.approx(4 / 9)
    assert result["degree_only"]["added"] == 0
    assert result["degree_only"]["total"] == pytest.approx(5 / 9)
    assert not result["degree_only"]["scoreable_pmf"]
    assert result["joint"]["public"] == pytest.approx([0, 4 / 9, 3 / 9, 2 / 9])
    assert result["joint"]["scoreable_pmf"]


def test_public_band_shadow_upper_endpoint_remains_eligible():
    spec, packet, p = band_fixture()
    packet["incumbent_bound"] = p["context"]["observed_floor_bucket"] = 93
    packet["prior"]["mass"] = {"92": .4, "93": .1, "94": .3, "96": .2}
    p["final_degree_mass"] = {"92": 0, "93": 1 / 6, "94": .5, "96": 1 / 3}
    for band, observed in zip(p["bands"], [0, 1 / 6, .5, 1 / 3]):
        band["model_probability"] = observed
    result = project_bands(spec, packet, p)
    assert result["incumbent"]["public"][1] == pytest.approx(1 / 6)
    assert result["degree_only"]["public"][1] == pytest.approx(.5)
    assert result["degree_only"]["scoreable_pmf"]


def test_public_band_shadow_forced_upper_tail_adds_and_removes_mass():
    spec, packet, p = band_fixture()
    p["bands"] = p["bands"][:2] + [dict(label="94°F or higher", kind="gte", value=94, value_hi=94, model_probability=1)]
    result = project_bands(spec, packet, p)
    held = result["degree_only"]
    assert held["public"] == [0, 0, 1] and held["scoreable_pmf"]
    assert held["added"] == pytest.approx(4 / 9)
    assert held["removed"] == pytest.approx(4 / 9)
    assert result["joint"]["public"] == pytest.approx([0, 4 / 9, 5 / 9])


def test_public_band_shadow_zero_celsius_with_signed_native_ladder():
    spec, packet, p = band_fixture()
    spec.market_unit = "C"
    for section in (packet, packet["rule"], packet["prior"], p):
        section["unit"] = "C"
    packet["incumbent_bound"] = p["context"]["observed_floor_bucket"] = 2
    packet["prior"]["mass"] = {"-1": .2, "0": .3, "2": .5}
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z 00/M02")]
    p["final_degree_mass"] = {"-1": 0, "0": 0, "2": 1}
    p["bands"] = [
        dict(label="-1°C or below", kind="lte", value=-1, value_hi=-1, model_probability=0),
        dict(label="0-1°C", kind="eq", value=0, value_hi=1, model_probability=0),
        dict(label="2°C or higher", kind="gte", value=2, value_hi=2, model_probability=1),
    ]
    out = project_bands(spec, packet, p)
    assert out["candidate_bound"] == 0
    assert out["degree_only"]["public"] == [0, 0, 1]
    assert out["joint"]["public"] == pytest.approx([0, .375, .625])


def test_public_band_shadow_missing_routine_evidence_abstains():
    spec, packet, p = band_fixture()
    packet["evidence"]["reports"] = []
    assert project_bands(spec, packet, p)["reason"] == "missing"


@pytest.mark.parametrize("config", [{}, {"enabled": False}])
def test_public_band_shadow_disabled_overlay_allows_degree_only_rescue(config):
    spec, packet, p = band_fixture()
    p["market_bin"] = config
    result = project_bands(spec, packet, p)
    assert result["degree_only"]["public"] == result["joint"]["public"]
    assert result["degree_only"]["public"][1] == pytest.approx(4 / 9)


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("market_bin", {"enabled": True, "preserve_distribution_coherence": False, "method": "market_shrink"}, "unsupported_noncoherent_market_bin_route"),
    ("distribution_kind", "continuous_density", "unsupported_distribution_or_intervening_guard"),
    ("boundary_active", True, "unsupported_distribution_or_intervening_guard"),
    ("recorded_at", "2026-08-10T20:00:01Z", "presentation_after_decision"),
    ("context", {"observed_floor_bucket": 93, "lockin_strength": 0, "cutoff_hour": 20}, "unmatched_presentation_context"),
    ("exact_distribution", {"temperature": 2}, "unbound_presentation"),
    ("final_degree_mass", {"90": 0, "92": 0, "94": .55, "96": .45}, "incumbent_final_degree_mismatch"),
])
def test_public_band_shadow_abstains_before_exposing_candidate(field, value, reason):
    spec, packet, p = band_fixture()
    p[field] = value
    assert project_bands(spec, packet, p) == {"status": "abstained", "reason": reason}


def test_public_band_shadow_requires_exact_capture_binding_and_zero_support_closure():
    spec, packet, p = band_fixture()
    packet["prior"]["presentation_sha256"] = "f" * 64
    assert evaluate_floor_band_shadow(packet, spec, p)["reason"] == "unbound_presentation"
    p["bands"][1]["model_probability"] = 1e-18
    assert project_bands(spec, packet, p)["reason"] == "incumbent_public_band_mismatch"


@pytest.mark.parametrize("case", ["missing_bin", "overlap", "wrong_unit", "wrong_endpoint", "lowest"])
def test_public_band_shadow_rejects_incompatible_ladders_and_families(case):
    spec, packet, p = band_fixture()
    if case == "lowest":
        packet["family"] = "lowest"
    elif case == "missing_bin":
        p["bands"].pop(1)
    elif case == "overlap":
        p["bands"].append(dict(p["bands"][1]))
    elif case == "wrong_unit":
        p["bands"][1]["label"] = "92-93°C"
    else:
        p["bands"][1]["value_hi"] = 92
    expected = "unsupported_family_or_stage" if case == "lowest" else "incomplete_or_invalid_native_ladder"
    assert project_bands(spec, packet, p)["reason"] == expected


def test_first_stage_matches_one_sided_operator_and_restores_routine_winner_mass():
    spec, packet = fixture()
    packet["evidence"]["reports"] = [
        row("METAR KZZZ 101550Z 33/20 RMK T03330200"),
        row("SPECI KZZZ 101555Z 34/20 RMK T03440200"),
        row("METAR KYYY 101555Z 40/20"),
        row("METAR KZZZ 101700Z 39/20", "2026-08-10T20:01:00Z"),
    ]
    result = evaluate_floor_shadow(packet, spec)
    assert (result["status"], result["routine_count"], result["witness_value_basis"]) == ("running", 1, "t_group")
    before, after = result["incumbent"], result["candidate"]
    assert before["bound"] == 94 and after["bound"] == 92
    assert before["excluded_prior_mass"] == pytest.approx(.5)
    assert after["excluded_prior_mass"] == pytest.approx(.1)
    assert before["mass"][92] == pytest.approx(.4e-6 / (.5 + .5e-6))
    assert after["mass"][92] == pytest.approx(.4 / (.9 + .1e-6))
    assert sum(after["mass"].values()) == pytest.approx(1)


@pytest.mark.parametrize("marker", ["METAR COR", "METAR"])
def test_receipt_order_can_lower_bound_and_next_day_report_closes_revisions(marker):
    spec, packet = fixture(as_of="2026-08-11T01:00:00Z")
    records = [
        row("METAR KZZZ 101550Z 36/20"),
        row(f"{marker} KZZZ 101550Z 33/20", "2026-08-10T16:20:00Z"),
        row("METAR KZZZ 110005Z 25/20", "2026-08-11T00:11:00Z"),
        row("METAR COR KZZZ 101550Z 40/20", "2026-08-11T00:12:00Z"),
    ]
    packet["evidence"]["reports"] = list(reversed(records))
    result = evaluate_floor_shadow(packet, spec)
    assert (result["status"], result["candidate"]["bound"]) == ("final", 91)
    assert result["witness_receipt"] == "2026-08-10T16:20:00+00:00"
    assert result["conditional_until"] == "2026-08-11T00:11:00+00:00"


def test_lowest_mirror_rounds_negative_half_up_and_preserves_equal_degree():
    spec, packet = fixture("lowest", "C")
    packet["prior"]["mass"] = {"-2": .2, "-1": .3, "0": .5}
    packet["incumbent_bound"] = -2
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z M02/M05 RMK T10151050"),
                                     row("SPECI KZZZ 101555Z M04/M05")]
    candidate = evaluate_floor_shadow(packet, spec)["candidate"]
    assert candidate["bound"] == -1 and candidate["excluded_prior_mass"] == .5
    assert candidate["mass"][-1] == pytest.approx(.3 / (.5 + .5e-6))


def test_zero_is_a_valid_bound():
    spec, packet = fixture("highest", "C")
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z 00/M02")]
    packet["prior"]["mass"] = {"-1": .2, "0": .8}
    assert evaluate_floor_shadow(packet, spec)["candidate"]["excluded_prior_mass"] == .2


@pytest.mark.parametrize(("family", "incumbent", "expected"), [
    ("highest", 94, {90: 0, 92: .5, 94: .3, 96: .2}),
    ("lowest", 90, {90: .1, 92: .9, 94: 0, 96: 0}),
])
def test_actual_lockin_operator_moves_excluded_mass_to_equal_native_anchor(family, incumbent, expected):
    spec, packet = fixture(family)
    packet["incumbent_bound"] = incumbent
    packet["prior"]["stage"] = "input_to_apply_lockin_observed_floor"
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z 33/20 RMK T03330200")]
    out = evaluate_floor_shadow(packet, spec)
    assert out["incumbent"]["mass"][92] == 0
    assert out["candidate"]["mass"] == pytest.approx(expected)
    assert out["candidate"]["excluded_after_mass"] == 0


@pytest.mark.parametrize(("family", "old", "eligible"), [
    ("highest", 94, {92, 94, 96}), ("lowest", 90, {90, 92}),
])
def test_recorded_exact_calibration_preserves_captured_uniform_prior_and_degree_direction(family, old, eligible):
    spec, packet = fixture(family)
    packet["incumbent_bound"] = old
    packet["prior"].update(stage="pre_calibration_model", calibration=dict(capture_sha256="5" * 64,
        resolution_weight=0, cutoff_hour=20, exact_distribution={"prior_weight": 1}))
    packet["evidence"]["reports"] = [row("METAR KZZZ 101550Z 33/20 RMK T03330200")]
    out = evaluate_floor_shadow(packet, spec)
    assert out["incumbent"]["mass"][92] == 0
    assert set(k for k, p in out["candidate"]["mass"].items() if p > 0) == eligible
    assert out["candidate"]["mass"][92] == pytest.approx(1 / len(eligible))
    packet["prior"]["calibration"]["exact_distribution"] = {"enabled": False}
    out = evaluate_floor_shadow(packet, spec)
    assert out["incumbent"]["mass"] == out["candidate"]["mass"]


def test_empty_calibration_support_is_unscorable():
    spec, packet = fixture()
    packet["incumbent_bound"] = 999
    packet["prior"].update(stage="pre_calibration_model", calibration=dict(capture_sha256="5" * 64,
        resolution_weight=0, cutoff_hour=20, exact_distribution={}))
    assert evaluate_floor_shadow(packet, spec)["reason"] == "empty_calibrated_support"


def test_no_reports_yet_does_not_create_a_bound():
    spec, packet = fixture()
    out = evaluate_floor_shadow(packet, spec)
    assert out["status"] == "missing" and out["candidate"]["bound"] is None
    assert out["candidate"]["mass"][92] == .4


@pytest.mark.parametrize(("change", "reason"), [
    ({"complete": False}, "incomplete_asof_capture"),
    ({"through": "2026-08-10T19:59:00Z"}, "incomplete_asof_capture"),
    ({"station": "KYYY"}, "wrong_source_or_station"),
    ({"reports": [row("METAR KZZZ 101550Z 33/20", None)]}, "receipt_missing"),
    ({"reports": [row("101550Z 33/20")]}, "unattributable_station"),
    ({"reports": [row("METAR KZZZ 101550Z 33/20", "2026-08-10T15:49:00Z")]}, "receipt_predates_observation"),
    ({"reports": [row("METAR KZZZ 101550Z 31/20 RMK T0333")]}, "raw_parser_disagreement"),
    ({"reports": [row("METAR KZZZ 101550Z 33/20"), row("METAR KZZZ 101550Z 35/20")]}, "source_unavailable"),
])
def test_unreliable_evidence_abstains(change, reason):
    spec, packet = fixture()
    packet["evidence"].update(change)
    out = evaluate_floor_shadow(packet, spec)
    assert out["reason"] == reason and "candidate" not in out


def test_dated_event_cannot_use_later_rule_and_tomorrow_cannot_use_todays_floor():
    spec, packet = fixture()
    packet["rule"].update(basis="dated_event", recorded_at="2026-08-11T00:00:00Z", effective_from="2026-10-23")
    assert evaluate_floor_shadow(packet, spec)["reason"] == "rule_not_yet_admissible"
    spec, packet = fixture(as_of="2026-08-09T23:59:59Z")
    assert evaluate_floor_shadow(packet, spec)["reason"] == "before_target_local_day"


@pytest.mark.parametrize("field", ["stage", "station", "mass", "capture_sha256"])
def test_unusable_prior_rejected(field):
    spec, packet = fixture()
    packet["prior"][field] = {"stage": "p_served", "station": "KYYY", "mass": {0: .7}, "capture_sha256": ""}[field]
    with pytest.raises(ValueError):
        evaluate_floor_shadow(packet, spec)


def test_confirmed_wu_fallback_uses_native_values_and_real_read_time():
    spec, packet = fixture(as_of="2026-08-12T05:00:00Z")
    wu = dict(station="KZZZ", unit="F", target_date=packet["target_date"], read_at="2026-08-12T04:00:00Z",
              status="published", high="92.5", low="70")
    packet["evidence"]["wu"] = wu
    out = evaluate_floor_shadow(packet, spec)
    assert out["status"] == "wu_fallback" and out["candidate"]["bound"] == 93
    wu["read_at"] = "2026-08-11T16:00:00Z"
    assert evaluate_floor_shadow(packet, spec)["reason"] == "fallback_read_before_deadline"
    wu.update(read_at="2026-08-12T04:00:00Z", status="confirmed_empty")
    assert evaluate_floor_shadow(packet, spec)["reason"] == "lowest_bracket_fallback"
    wu["station"] = "KYYY"
    assert evaluate_floor_shadow(packet, spec)["reason"] == "fallback_identity_mismatch"
