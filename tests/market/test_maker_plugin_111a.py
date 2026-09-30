"""111a: fixes from the first real-data dry run; synthetic production layouts only.

Each test reproduces one defect from docs/roadmap/evidence-110h-dry-run-20260926
with the production writer's layout: the shared forecast-payload CAS, an
over-cap CLOB token file, an over-cap settlement ledger, the T+0 capture
coverage limit, and the per-run input budget. No production data or venue.
"""
import gzip
import json
from datetime import timedelta

import pytest

from weather.collection.forecast_payload_cas import (
    SharedForecastPayloadCAS,
    parse_market_invariant_attestation,
    resolve_forecast_payload_bytes,
)
from weather.market import maker_plugin_capture
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.maker_plugin_capture import Reader
from weather.market.maker_plugin_runner import run
from weather.market.maker_plugin_sources import BAND_FIELDS, Sources, compress_bands, token_batch
from weather.market.market_microstructure_capture import MarketMicrostructureStore, token_rows_from_event
from weather.schema_registry import schema_version
from weather.sources.nbm_probabilistic_tmax import nbp_raw_payload
from tests.market.test_maker_plugin import NOW as BASE_NOW
from tests.market.test_maker_plugin import bulletin, fixture, ledger, served_inputs
from tests.market.test_maker_plugin_dry_run import NOW, jsonl, layout, report

ATLANTA = next(s for s in BUILTIN_SPECS if s.id == "atlanta")
SMALL_CAP = 256 * 1024


def fair_values(args):
    return {o["condition_id"]: o["fair_value"] for r in report(args)["records"] for o in r["outcomes"]}


def shared_nbp(args, folder):
    """Write the production v2 shared-CAS layout and return its manifest row."""
    _, rows, spec, target, _, _ = fixture(lead=1, now=NOW)
    issue = BASE_NOW.replace(hour=13)
    # A national bulletin: another station first (different values), then ours.
    national = bulletin(ATLANTA, target, shift=20)["text"] + bulletin(spec, target)["text"]
    url = ("https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
           f"blend.{issue:%Y%m%d}/{issue:%H}/text/blend_nbptx.t{issue:%H}z")
    fetched = (BASE_NOW - timedelta(minutes=30)).isoformat()
    attested = parse_market_invariant_attestation(
        "nbm_probabilistic_tmax", nbp_raw_payload(national, spec.icao, target, url, fetched))
    cas_root = args.data_root / "forecast_payload_cas"
    stored = SharedForecastPayloadCAS(cas_root).put(attested["payload_bytes"])
    _, lineage = served_inputs(rows)
    row = dict(lineage, schema_version=schema_version("forecast_payload_manifest"), market_id=spec.id,
               target_date=target.isoformat(), source="nbm_probabilistic_tmax", fetched_at=fetched,
               source_url=url, request_key=attested["request_key"], cycle_key=attested["cycle_key"],
               extraction_schema=attested["extraction_schema"], extraction_identity=attested["extraction_identity"],
               payload_storage_scope=stored["storage_scope"], payload_cas_kind=stored["cas_kind"],
               payload_hash_algorithm=stored["payload_hash_algorithm"], payload_hash=stored["payload_hash"],
               payload_bytes=stored["payload_bytes"], payload_ref=stored["payload_ref"],
               payload_encoding=attested["encoding"], payload_media_type=attested["media_type"],
               raw_payload_retained=True, raw_payload_path="Z:/elsewhere/never-followed.blob")
    # The fixture is the canonical store's own layout: its resolver agrees.
    assert stored["payload_ref"].endswith(".blob")
    assert resolve_forecast_payload_bytes(row, shared_cas_root=cas_root) == attested["payload_bytes"]
    jsonl(folder / "forecast_payloads.jsonl", [row])
    for path in sorted((folder / "forecast_payloads").rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    (folder / "forecast_payloads").rmdir()
    return row, cas_root / stored["payload_ref"]


def test_shared_cas_matches_legacy(tmp_path):
    legacy_args, _, _ = layout(tmp_path / "l", minutes=2)
    run(legacy_args)
    args, folder, _ = layout(tmp_path / "s", minutes=2)
    shared_nbp(args, folder)
    summary = run(args)
    assert summary["status"] == "COMPLETE"
    assert not [key for key in summary["unavailable"] if key.startswith(("nbp:", "fair_value:"))]
    assert summary["coverage"]["nbp_blobs.verified"] == 1
    assert summary["coverage"]["files_read.nbp_blobs"] == 1  # Two minutes, one read.
    assert summary["coverage"]["input_bytes.nbp_blobs"] > 0
    for record in report(args)["records"]:
        assert record["source_coverage"]["bulletins"]["point_in_time_rows"] == 1
        assert record["probability_mass"]["complete"]
    shared, legacy = fair_values(args), fair_values(legacy_args)
    assert {cid: v["p_yes"] for cid, v in shared.items()} == {cid: v["p_yes"] for cid, v in legacy.items()}
    assert all(v["model_id"] == "nbp-v2-piecewise-linear" for v in shared.values())


@pytest.mark.parametrize("defect", ["blob_bytes", "byte_count", "ref", "identity", "missing"])
def test_shared_cas_defects_fail_closed(tmp_path, defect):
    args, folder, _ = layout(tmp_path)
    row, blob = shared_nbp(args, folder)
    if defect == "blob_bytes":
        blob.write_bytes(blob.read_bytes() + b" ")
    elif defect == "missing":
        blob.unlink()
    else:
        if defect == "byte_count":
            row["payload_bytes"] += 1
        elif defect == "ref":
            row["payload_ref"] = row["payload_ref"].replace(".blob", ".json")
        else:
            row["extraction_identity"] = dict(row["extraction_identity"], station_id=ATLANTA.icao)
        jsonl(folder / "forecast_payloads.jsonl", [row])
    summary = run(args)
    assert summary["unavailable"]["fair_value:corrupt_supporting_input"] == 3
    assert summary["unavailable"]["clock:corrupt_clock_input"] == 3
    expected = {"blob_bytes": "nbp:retained_payload_hash_mismatch",
                "byte_count": "nbp:retained_payload_byte_count_mismatch", "ref": "nbp:shared_payload_ref_mismatch",
                "identity": "nbp:shared_payload_identity_invalid", "missing": "nbp:FileNotFoundError"}[defect]
    assert summary["unavailable"][expected] == 1


LABELS = ("69°F or below", "70-79°F", "80°F or higher")  # The fixture's three native bands.


def token_rows(when):
    """CLOB token rows from the production flattener for the fixture's Gamma event."""
    _, _, spec, _, discovery, _ = fixture(lead=1, now=NOW)
    event = json.loads(discovery["body_utf8"])[0]
    event["markets"] = [dict(m, groupItemTitle=label) for m, label in zip(event["markets"], LABELS)]
    return token_rows_from_event(event, spec.id, captured_at=when)


def write_tokens(folder, batches, fmt):
    """Append batches through the production store writer (CSV and JSONL twins)."""
    store = MarketMicrostructureStore(root=folder, event_slug=folder.name)
    for batch in batches:
        store.write_token_rows(batch)
    if fmt == "jsonl":
        (folder / "clob_tokens.csv").unlink()
        return folder / "clob_tokens.jsonl"
    (folder / "clob_tokens.jsonl").unlink()
    path = folder / "clob_tokens.csv.gz"  # The closed-day tiering form.
    path.write_bytes(gzip.compress((folder / "clob_tokens.csv").read_bytes()))
    (folder / "clob_tokens.csv").unlink()
    return path


@pytest.mark.parametrize("fmt", ["jsonl", "csv.gz"])
def test_t1_band_metadata_streams_first_token_batch_from_over_cap_file(tmp_path, monkeypatch, fmt):
    monkeypatch.setattr(maker_plugin_capture, "MAX_FILE_BYTES", SMALL_CAP)
    args, folder, _ = layout(tmp_path, minutes=2)
    (folder / "snapshots_long.csv").unlink()  # T+1: no point-in-time snapshot rows.
    first = NOW - timedelta(minutes=10)
    later = [token_rows(NOW + timedelta(minutes=i)) for i in range(1, 150)]
    path = write_tokens(folder, [token_rows(first)] + later, fmt)
    logical = gzip.decompress(path.read_bytes()) if fmt == "csv.gz" else path.read_bytes()
    assert len(logical) > SMALL_CAP
    with pytest.raises(ValueError, match="file_byte_limit"):  # The former whole-file load.
        Reader(args.data_root, 60, 1024**3).read(path)
    summary = run(args)
    assert "descriptor:missing_captured_band_metadata" not in summary["unavailable"]
    assert summary["mass_coverage"] == {"complete_unit_mass": 2}
    assert summary["coverage"]["files_read.band_tokens"] == 1
    assert summary["coverage"]["band_tokens.events_with_batch"] == 1
    assert summary["coverage"]["input_bytes.band_tokens"] <= 2 * 65536 < len(logical)
    assert {r["band_token_batch_utc"] for r in report(args)["records"]} == {first.isoformat()}


def test_token_batch_after_minute_is_identity_only(tmp_path):
    # 111j: a later batch describes the same immutable contracts, so it is used
    # as condition identity (see test_maker_plugin_111j), never as a capture at
    # the minute: the report keeps the batch's own clock.
    args, folder, _ = layout(tmp_path)
    (folder / "snapshots_long.csv").unlink()
    write_tokens(folder, [token_rows(NOW + timedelta(hours=1))], "jsonl")
    summary = run(args)
    assert "descriptor:missing_captured_band_metadata" not in summary["unavailable"]
    assert summary["coverage"]["band_basis.lead1.condition_identity"] == 3
    assert {r["band_token_batch_utc"] for r in report(args)["records"]} == {(NOW + timedelta(hours=1)).isoformat()}


def test_token_batches_refuse_ambiguous_metadata():
    _, rows, _, _, _, _ = fixture(lead=1, now=NOW)
    batch = token_rows(NOW)
    bands = token_batch(batch, rows[0]["event_slug"])
    assert [(b["condition_id"], b["bin_kind"], b["bin_value_c"], b["bin_value_hi_c"]) for b in bands] == [
        (r["condition_id"], r["bin_kind"], r["bin_value_c"], r["bin_value_hi_c"]) for r in rows]
    with pytest.raises(ValueError, match="token_band_incomplete_pair"):
        token_batch(batch[:-1], rows[0]["event_slug"])
    with pytest.raises(ValueError, match="token_negative_label_unsupported"):
        token_batch([dict(batch[0], range_label="-2°C or below")] + batch[1:], rows[0]["event_slug"])
    with pytest.raises(ValueError, match="token_event_mismatch"):
        token_batch(batch, "highest-temperature-in-nyc-on-january-12-2030")
    # Unchanged repeats compress away; a changed capture is always retained.
    repeat = [dict(r, captured_at_utc=(NOW + timedelta(minutes=1)).isoformat()) for r in bands]
    changed = [dict(repeat[0], captured_at_utc=(NOW + timedelta(minutes=2)).isoformat(), bin_value_c=68)]
    projected = [{k: r[k] for k in BAND_FIELDS} for r in bands + changed]  # Token ids are identity-only.
    assert compress_bands(bands + repeat + changed) == projected


def test_over_cap_ledger_is_streamed_once_for_run_events_only(tmp_path, monkeypatch):
    monkeypatch.setattr(maker_plugin_capture, "MAX_FILE_BYTES", SMALL_CAP)
    args, folder, _ = layout(tmp_path, minutes=2)
    _, rows, spec, _, _, _ = fixture(lead=1, now=NOW)
    settled_target = NOW.date() - timedelta(days=1)
    settled = fixture(lead=0, now=NOW - timedelta(days=1))[1]
    settled_row = ledger(settled, spec, settled_target)
    unrelated = [dict(settled_row, event_slug=f"highest-temperature-in-nyc-on-march-{d}-2029", padding="x" * 2000)
                 for d in range(1, 29) for _ in range(5)]
    later = dict(ledger(rows, spec, NOW.date() + timedelta(days=1)))  # Recorded after the run date.
    path = args.data_root / "settlements" / "nyc" / "ledger.jsonl"
    jsonl(path, unrelated + [settled_row, later])
    assert path.stat().st_size > SMALL_CAP
    summary = run(args)
    assert not [key for key in summary["unavailable"] if key.startswith("settlements:")]
    assert summary["coverage"]["files_read.settlements"] == 1
    assert summary["coverage"]["settlements.rows"] == 1  # Only the in-window, recorded-by-run-end revision.
    sources = Sources(Reader(args.data_root, 60, 1024**3), args.date, ["nyc"])
    assert sources.ledger(spec, settled_row["event_slug"]) == [settled_row]
    assert sources.ledger(spec, later["event_slug"]) == []


def test_t0_band_without_captured_book_is_a_named_capture_limit(tmp_path):
    _, rows, _, _, _, _ = fixture(lead=0, now=NOW)
    args, _, _ = layout(tmp_path, lead=0, uncaptured_tokens={rows[0]["clob_yes_token_id"], rows[0]["clob_no_token_id"]})
    summary = run(args)
    assert summary["unavailable"]["descriptor:book_not_captured"] == 1
    assert summary["coverage"]["unavailable.lead0.descriptor:book_not_captured"] == 1
    assert "descriptor:missing_point_in_time_input" not in summary["unavailable"]
    record = report(args)["records"][0]
    assert record["lead_days"] == 0
    assert sum("decision" in o for o in record["outcomes"]) == 2


def test_supporting_inputs_are_loaded_once_per_run(tmp_path):
    args, folder, _ = layout(tmp_path, minutes=5)
    _, rows, _, _, _, _ = fixture(lead=1, now=NOW)
    trigger = {"event_slug": rows[0]["event_slug"], "current_captured_at_utc": (NOW - timedelta(hours=1)).isoformat()}
    future = {"event_slug": rows[0]["event_slug"], "current_captured_at_utc": "2030-01-12T00:00:00+00:00"}
    other = {"event_slug": "highest-temperature-in-nyc-on-march-1-2029", "current_captured_at_utc": NOW.isoformat()}
    jsonl(args.data_root / "snapshots" / "observation_triggers.jsonl", [trigger, future, other])
    summary = run(args)
    coverage = summary["coverage"]
    assert summary["records_written"] == 5
    assert coverage["cache.loads"] == 1 and coverage["cache.hits"] == 4 and not coverage["cache.reloads"]
    for source in ("snapshots", "nbp_manifests", "explanations", "triggers", "nbp_legacy"):
        assert coverage["files_read." + source] == 1, source
        assert coverage["input_bytes." + source] > 0, source
    assert coverage["triggers.rows"] == 1  # Future and out-of-window rows are not retained.
    assert coverage["input_bytes.maker_evidence"] > 0
    assert summary["max_cache_bytes"] == 512 * 1024**2


def test_cache_budget_overflow_is_explicit(tmp_path):
    args, _, _ = layout(tmp_path, minutes=3)
    args.max_cache_bytes = 1
    summary = run(args)
    coverage = summary["coverage"]
    assert summary["status"] == "COMPLETE"
    assert coverage["cache.event_over_budget"] == 3
    assert coverage["cache.loads"] == 1 and coverage["cache.reloads"] == 2
    assert coverage["files_read.snapshots"] == 3
    args.output = tmp_path / "invalid"
    args.max_cache_bytes = 0
    with pytest.raises(ValueError, match="invalid_cache_budget"):
        run(args)


def scan_fallback_candidates(forecasts, event_id, spec, target, as_of):
    """The pre-111a full scan, kept verbatim as the parity oracle."""
    from weather.market.maker_plugin.inputs import timestamp
    candidates = []
    for row in forecasts:
        if row.get("target_date") != target.isoformat() or row.get("event_slug") != event_id:
            continue
        if row.get("forecast_kind") != "daily_high" or timestamp(row["captured_at_utc"]) > as_of:
            continue
        issue_text = row.get("provider_issue_time") or row.get("provider_update_time")
        if not issue_text:
            continue
        issue = timestamp(issue_text)
        if (target - issue.astimezone(spec.tz).date()).days != 1:
            continue
        if issue <= timestamp(row["captured_at_utc"]) <= as_of < issue + timedelta(hours=24):
            candidates.append({"issue": issue.isoformat(), "row": row})
    return candidates


@pytest.mark.parametrize("seed", range(12))
def test_indexed_fallback_equals_full_scan(seed):
    import random
    from weather.market.maker_plugin.fair_value import WeatherFairValue
    rng = random.Random(seed)
    universe, rows, spec, target, _, _ = fixture(lead=1, now=NOW)
    slug = rows[0]["event_slug"]
    forecasts = []
    for i in range(150):
        captured = NOW - timedelta(minutes=rng.randrange(-120, 900))
        issue = captured - timedelta(minutes=rng.randrange(-30, 900))
        row = {"event_slug": rng.choice([slug, slug, "other"]), "target_date": rng.choice([target.isoformat()] * 3 + ["x"]),
               "forecast_kind": rng.choice(["daily_high"] * 4 + ["hourly"]), "captured_at_utc": captured.isoformat(),
               "provider_issue_time": rng.choice([issue.isoformat()] * 4 + [None, ""]),
               "provider_update_time": rng.choice([issue.isoformat(), None]),
               "source": "s", "valid_time": "v", "forecast_high_c": 70}
        defect = rng.random() if seed % 3 == 0 else 1.0  # Two in three seeds are clean.
        if defect < .03:
            row.pop("captured_at_utc")
        elif defect < .06:
            row["captured_at_utc"] = "not-a-time"
        elif defect < .09:
            row["provider_issue_time"] = "2030-01-10T10:00:00"  # Naive clock.
        forecasts.append(row)
    provider = WeatherFairValue(universe, forecasts=forecasts)
    kinds = set()
    for minutes in range(-60, 1500, 37):
        as_of = NOW + timedelta(minutes=minutes)
        outcomes = []
        for collect in (lambda: scan_fallback_candidates(forecasts, slug, spec, target, as_of),
                        lambda: provider._fallback_candidates(slug, spec, target, as_of)):
            try:
                outcomes.append(("ok", collect()))
            except (ValueError, KeyError, TypeError) as exc:
                outcomes.append(("error", type(exc), str(exc)))
        assert outcomes[0] == outcomes[1]
        kinds.add((outcomes[0][0], bool(outcomes[0][0] == "ok" and outcomes[0][1])))
    assert seed % 3 == 0 or ("ok", True) in kinds


def test_minute_stride_is_explicit_and_bounded(tmp_path):
    args, _, _ = layout(tmp_path, minutes=6)  # Captured minutes 15:20 .. 15:25.
    args.minute_stride = 5
    summary = run(args)
    assert summary["minute_stride"] == 5
    assert [r["minute_utc"][-5:] for r in report(args)["records"]] == ["15:20", "15:25"]
    assert summary["coverage"]["segment_minutes.skipped_by_stride"] == 4
    for stride in (0, 61, True):
        args.output, args.minute_stride = tmp_path / f"bad-{stride}", stride
        with pytest.raises(ValueError, match="invalid_minute_stride"):
            run(args)


def test_refused_shared_blob_is_read_once(tmp_path):
    args, folder, _ = layout(tmp_path, minutes=2)
    row, blob = shared_nbp(args, folder)
    blob.write_bytes(blob.read_bytes() + b" ")
    later = dict(row, captured_at_utc=(NOW - timedelta(minutes=1)).isoformat())
    jsonl(folder / "forecast_payloads.jsonl", [row, later])
    summary = run(args)
    assert summary["unavailable"]["nbp:retained_payload_hash_mismatch"] == 2
    assert summary["coverage"]["input_bytes.nbp_blobs"] == blob.stat().st_size
