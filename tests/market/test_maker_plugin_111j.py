"""111j: why the 111a production re-run evaluated no band; synthetic production layouts only.

Production capture is local-T+0 only: the snapshot loop refuses a pre-local-day
event and the CLOB loop captures each market's local-today event. A T+1/T+2
event folder therefore holds no rows on the run date. These tests reproduce that
layout with the production writers (shared forecast-payload CAS, NBP attestation,
CLOB token store, 88a evidence store, release-serving lineage). No production data.
"""
from datetime import timedelta
import json

import pytest

from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS, parse_market_invariant_attestation
from weather.market.maker_plugin_runner import run
from weather.release_serving import (
    clear_process_serving_bundle_cache,
    get_process_active_serving_bundle,
    serving_bundle_lineage,
)
from weather.schema_registry import schema_version
from weather.sources.nbm_probabilistic_tmax import nbp_raw_payload
from tests.market.test_maker_plugin import NOW as BASE_NOW, fixture, served_inputs
from tests.market.test_maker_plugin_111a import token_rows, write_tokens
from tests.market.test_maker_plugin_dry_run import NOW, jsonl, layout, report

ISSUE = BASE_NOW.replace(hour=13)


def two_day_bulletin(spec, shift=0):
    """One NBP cycle holding T+0 and T+1 maxima (min/max pairs per group)."""
    lines = [f" {spec.icao} NBM V4.3 NBP GUIDANCE {ISSUE:%m/%d/%Y %H%M} UTC", "FHR   -1 11| 23 35"]
    for code, value in zip(("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"),
                           (65, 70, 75, 80, 85, 75, 8)):
        lines.append(f"{code:<6} 40 {value}| 41 {value + shift}")
    return "\n".join(lines) + "\n"


def t1_layout(tmp_path, *, text=None, minutes=1):
    """T+1 event with an empty own folder; the T+0 folder holds the shared NBP manifest."""
    args, folder, segment = layout(tmp_path, minutes=minutes)
    for name in ("snapshots_long.csv", "forecast_payloads.jsonl", "snapshot_explanations.jsonl"):
        (folder / name).unlink()
    _, rows, spec, target, _, _ = fixture(lead=1, now=NOW)
    t0 = target - timedelta(days=1)
    t0_folder = folder.parent / folder.name.replace(f"-{target.day}-", f"-{t0.day}-")
    url = ("https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
           f"blend.{ISSUE:%Y%m%d}/{ISSUE:%H}/text/blend_nbptx.t{ISSUE:%H}z")
    fetched = (BASE_NOW - timedelta(minutes=30)).isoformat()
    attested = parse_market_invariant_attestation(
        "nbm_probabilistic_tmax", nbp_raw_payload(text or two_day_bulletin(spec), spec.icao, t0, url, fetched))
    stored = SharedForecastPayloadCAS(args.data_root / "forecast_payload_cas").put(attested["payload_bytes"])
    _, lineage = served_inputs(rows)
    row = dict(lineage, event_slug=t0_folder.name, schema_version=schema_version("forecast_payload_manifest"),
               market_id=spec.id, target_date=t0.isoformat(), source="nbm_probabilistic_tmax", fetched_at=fetched,
               source_url=url, request_key=attested["request_key"], cycle_key=attested["cycle_key"],
               extraction_schema=attested["extraction_schema"], extraction_identity=attested["extraction_identity"],
               payload_storage_scope=stored["storage_scope"], payload_cas_kind=stored["cas_kind"],
               payload_hash_algorithm=stored["payload_hash_algorithm"], payload_hash=stored["payload_hash"],
               payload_bytes=stored["payload_bytes"], payload_ref=stored["payload_ref"],
               payload_encoding=attested["encoding"], payload_media_type=attested["media_type"],
               raw_payload_retained=True)
    jsonl(t0_folder / "forecast_payloads.jsonl", [row])
    return args, folder, t0_folder


def outcomes(args):
    return [o for r in report(args)["records"] for o in r["outcomes"]]


def test_t1_event_is_evaluated_end_to_end_from_t0_bulletin_and_identity_bands(tmp_path):
    args, folder, _ = t1_layout(tmp_path, minutes=2)
    # The CLOB loop first captures this event on its own local day: after the run date.
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert summary["status"] == "COMPLETE"
    assert not [k for k in summary["unavailable"] if k.startswith(("descriptor:", "fair_value:", "nbp"))]
    coverage = summary["coverage"]
    assert coverage["band_tokens.batch_after_run_date"] == 1
    assert coverage["band_basis.lead1.condition_identity"] == 6
    assert coverage["end_to_end.lead1"] == 6
    assert coverage["nbp_blobs.verified"] == 1
    assert coverage["files_read.nbp_blobs"] == 1  # Two minutes, one verified read.
    assert summary["mass_coverage"] == {"complete_unit_mass": 2}
    for outcome in outcomes(args):
        assert outcome["band_basis"] == "condition_identity"
        assert outcome["descriptor"]["source_hashes"]["band_basis"] == "condition_identity"
        assert outcome["fair_value"]["model_id"] == "nbp-v2-piecewise-linear"
        assert outcome["decision"]["reasons"] == ["MISSING_CONSERVATIVE_FILL_BOUND"]  # Default hazard.
    # The cycle's second group is the T+1 maximum (the shifted column).
    shifted, _, _ = t1_layout(tmp_path / "shifted", text=two_day_bulletin(fixture(lead=1, now=NOW)[2], shift=5))
    write_tokens(shifted.data_root / "snapshots" / folder.name, [token_rows(NOW + timedelta(days=1))], "jsonl")
    run(shifted)
    before = {o["condition_id"]: o["fair_value"]["p_yes"] for o in outcomes(args)}
    after = {o["condition_id"]: o["fair_value"]["p_yes"] for o in outcomes(shifted)}
    assert after != before
    assert sum(after.values()) == pytest.approx(1) and sum(before.values()) == pytest.approx(1)


def test_t1_bulletin_captured_for_the_t0_event_is_used(tmp_path):
    # Bands captured before the minute: only the bulletin location is under test.
    args, folder, _ = t1_layout(tmp_path)
    write_tokens(folder, [token_rows(NOW - timedelta(minutes=10))], "jsonl")
    summary = run(args)
    assert summary["coverage"]["band_basis.lead1.point_in_time_capture"] == 3
    assert summary["coverage"]["files_read.nbp_pool_manifests"] == 1  # Only the T+0 folder has one.
    assert {o["fair_value"]["model_id"] for o in outcomes(args)} == {"nbp-v2-piecewise-linear"}
    assert summary["coverage"]["end_to_end.lead1"] == 3


def test_cycle_without_the_target_maximum_is_not_used(tmp_path):
    spec = fixture(lead=1, now=NOW)[2]
    one_day = two_day_bulletin(spec).replace("-1 11| 23 35", "-1 11")
    args, folder, _ = t1_layout(tmp_path, text=one_day)
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert summary["unavailable"]["fair_value:missing_point_in_time_forecast"] == 3


def test_identity_bands_refuse_when_discovery_lists_other_contracts(tmp_path):
    args, folder, _ = t1_layout(tmp_path)
    batch = token_rows(NOW + timedelta(days=1))
    batch[0] = dict(batch[0], clob_token_id="999")  # Another contract under the same condition id.
    write_tokens(folder, [batch], "jsonl")
    summary = run(args)
    assert summary["unavailable"]["descriptor:band_identity_mismatch"] == 3
    assert "end_to_end.lead1" not in summary["coverage"]


def test_identity_bands_refuse_a_changed_partition(tmp_path):
    args, folder, _ = t1_layout(tmp_path)
    batch = token_rows(NOW + timedelta(days=1))
    extra = [dict(r, condition_id="0x" + "f" * 64, clob_token_id=str(900 + i), range_label="90°F or higher",
                  bin_kind="gte", bin_value=90, bin_value_hi=90) for i, r in enumerate(batch[-2:])]
    write_tokens(folder, [batch + extra], "jsonl")
    summary = run(args)
    assert summary["unavailable"]["descriptor:band_identity_mismatch"] == 3


def test_point_in_time_capture_wins_over_identity(tmp_path):
    args, folder, _ = layout(tmp_path)  # Own-folder snapshot rows exist at the minute.
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    summary = run(args)
    assert summary["coverage"]["band_basis.lead1.point_in_time_capture"] == 3
    assert {o["band_basis"] for o in outcomes(args)} == {"point_in_time_capture"}


def test_no_band_capture_at_all_is_a_reported_coverage_limit(tmp_path):
    args, _, _ = t1_layout(tmp_path)
    summary = run(args)
    assert summary["unavailable"]["descriptor:missing_captured_band_metadata"] == 3
    assert summary["coverage"]["band_basis.lead1.none"] == 3
    assert summary["coverage"]["band_tokens.missing_file"] == 1


def test_unreadable_pooled_manifest_is_corrupt_not_fallback(tmp_path):
    args, folder, t0_folder = t1_layout(tmp_path)
    write_tokens(folder, [token_rows(NOW + timedelta(days=1))], "jsonl")
    (t0_folder / "forecast_payloads.jsonl").write_bytes(b"{not json\n")
    summary = run(args)
    assert summary["unavailable"]["fair_value:corrupt_supporting_input"] == 3
    assert summary["unavailable"]["clock:corrupt_clock_input"] == 3


def test_research_unbound_served_rows_stay_unavailable_and_t0_is_outside_informed_v0(tmp_path):
    # A host without artifacts/releases: the production resolver and lineage writer.
    clear_process_serving_bundle_cache()
    try:
        bundle = get_process_active_serving_bundle(pointer_path=tmp_path / "releases" / "current_release.json",
                                                   releases_root=tmp_path / "releases", check_runtime=False)
    finally:
        clear_process_serving_bundle_cache()
    lineage = serving_bundle_lineage(bundle)
    assert lineage["release_identity_status"] == "research_unbound_non_countable" and not lineage["release_id"]
    args, folder, _ = layout(tmp_path / "t0", lead=0)
    manifest = json.loads((folder / "forecast_payloads.jsonl").read_text())
    manifest.update({k: lineage[k] for k in ("release_id", "release_manifest_sha256", "release_identity_status")})
    jsonl(folder / "forecast_payloads.jsonl", [manifest])
    summary = run(args)
    assert summary["unavailable"]["fair_value:served_snapshot_release_unbound"] == 3
    assert summary["decision_reasons"] == {"HORIZON_NOT_ELIGIBLE": 3}
