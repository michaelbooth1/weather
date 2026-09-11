"""Reproduce only the preselected, already-evaluated frozen 2025 predictions."""
from __future__ import annotations

import csv
from datetime import datetime
import io
import math
from pathlib import Path
import pickle

from weather.calibration.residual_preflight_io import (
    MAX_FEATURE_BYTES, PreflightError, canonical_digest, digest, json_bytes,
    mutation_refused, read_bound,
)

BASELINE = "temperature_residual_baseline"
CHALLENGER = "eleven_field_residual_challenger"
MODEL_SHA256 = {
    BASELINE: "c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797",
    CHALLENGER: "0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5",
}
DESIGN_SHA256 = "bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb"
SELECTION_SHA256 = "75e85b381340b0362f25568e0f638ff58a55488057e03fe79ae634c2b8629921"
PREDICTIONS_SHA256 = "6888cdf6655448defd5b46b811ecd9bcf36b397b425b8322f37d083619a9b876"
TRAINING_SHA256 = "5581c517e8a76399e7e0bdbac1c31ec059d67be977a0f7b54057d602018571b8"
TERMINAL_SHA256 = "1bb76d52daadecc2a4f978af56a0476c9ee43ae9ac097a8162630b51c803a656"


def load_selection(record, harness):
    if record.get("sha256") != SELECTION_SHA256:
        raise PreflightError("selection:not_the_predeclared_sample")
    selected = json_bytes(read_bound(record))
    expected = [
        {"market": market, "target_date": day, "native_unit": harness.MARKET_UNITS[market]}
        for market in harness.MARKETS
        for day in ("2025-05-10", "2025-08-29" if market == "denver" else "2025-08-31")
    ]
    if (selected.get("records") != expected
            or selected.get("design_sha256") != DESIGN_SHA256
            or selected.get("primary_leads") != list(harness.LEADS_PRIMARY)
            or selected.get("native_prediction_absolute_tolerance") != 1e-10
            or selected.get("relative_tolerance") != 0
            or selected.get("new_outcome_reads") is not False):
        raise PreflightError("selection:contract_changed")
    return selected


def _bound_fixed(record, expected):
    if record.get("sha256") != expected:
        raise PreflightError("evidence:unreviewed_replacement")
    return read_bound(record)


def verified_model_bytes(records, training):
    """Verify BOTH authorized model images before any deserialization."""
    if not isinstance(records, list) or len(records) != 2:
        raise PreflightError("model:pair_required")
    expected = {item["arm"]: item for item in training["artifacts"]}
    bodies = {}
    for record in records:
        arm = record.get("arm")
        if arm not in MODEL_SHA256 or arm in bodies:
            raise PreflightError("model:arm_scope")
        if (record.get("sha256") != MODEL_SHA256[arm]
                or record.get("sha256") != expected[arm]["sha256"]
                or record.get("bytes") != expected[arm]["bytes"]):
            raise PreflightError("model:frozen_identity")
        bodies[arm] = read_bound(record)
        mutation_refused(bodies[arm], record)
    return bodies


def decode_model(body, arm, harness):
    if digest(body) != MODEL_SHA256.get(arm):
        raise PreflightError("model:unreviewed_pickle_bytes")
    payload = pickle.loads(body)
    feature_order = harness.BASELINE_FEATURES if arm == BASELINE else harness.CHALLENGER_FEATURES
    if (not isinstance(payload, dict)
            or payload.get("artifact_version") != "multiyear_nwp_residual_model_v1"
            or payload.get("arm") != arm
            or payload.get("design_sha256") != DESIGN_SHA256
            or payload.get("estimator_configuration") != harness.MODEL_CONFIG
            or tuple(payload.get("feature_order") or ()) != tuple(feature_order)):
        raise PreflightError("model:payload_contract")
    return payload


def selected_surfaces(corpus_root, files, selection, harness, units):
    """Parse values only after row date membership in the fixed sample is known."""
    selected = {(row["market"], row["target_date"]) for row in selection["records"]}
    expected_paths = {
        f"units/{market}--2025--{segment}/completed/normalized.csv"
        for market in harness.MARKETS for segment in harness.SEGMENTS
    }
    if (not isinstance(files, list) or len(files) != 24
            or {row.get("relative_path") for row in files} != expected_paths):
        raise PreflightError("features:file_scope")
    if sum(row["bytes"] for row in files) > 384 * 1024 * 1024:
        raise PreflightError("features:total_bound")
    accumulators, seen, input_rows, selected_rows = {}, set(), 0, 0
    mutation_control = False
    root = Path(corpus_root)
    if not root.is_absolute():
        raise PreflightError("features:absolute_root_required")
    for record in files:
        market = record["relative_path"].split("/")[1].split("--")[0]
        bound = {**record, "path": str(root / record["relative_path"])}
        body = read_bound(bound, maximum=MAX_FEATURE_BYTES)
        if not mutation_control:
            mutation_control = mutation_refused(body, bound)
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig"), newline=""))
        if tuple(next(reader, ())) != harness.CSV_COLUMNS:
            raise PreflightError("features:header")
        for row in reader:
            input_rows += 1
            if len(row) != len(harness.CSV_COLUMNS) or row[0] != market:
                raise PreflightError("features:shape_or_market")
            # No value conversion, aggregation or outcome join before selection.
            if (market, row[1][:10]) not in selected:
                continue
            field = row[2]
            if field == harness.EXCLUDED_FIELD:
                continue
            if field not in harness.FIELDS:
                raise PreflightError("features:field")
            stamp = datetime.fromisoformat(row[1])
            lead = int(row[3])
            unit = "°" + harness.MARKET_UNITS[market] if field == "temperature_2m" else units[field]
            if (stamp.year != 2025 or stamp.minute or stamp.second or stamp.microsecond
                    or lead not in harness.LEADS_SENSITIVITY or row[5] != unit
                    or row[6] != "fixed_lead_day_offset" or row[7] != "open_meteo_previous_runs"):
                raise PreflightError("features:unit_lead_or_pit")
            key = (market, stamp.date().isoformat(), lead, field, stamp.hour)
            if key in seen:
                raise PreflightError("features:duplicate_hour")
            seen.add(key)
            value = float(row[4])
            if not math.isfinite(value):
                raise PreflightError("features:nonfinite")
            selected_rows += 1
            for summary in harness._summary_targets(field, stamp.hour):
                accumulator_key = (market, stamp.date().isoformat(), lead, summary)
                accumulators.setdefault(accumulator_key, harness._Accumulator()).add(value)
        del body
    surfaces = {}
    for market, target in sorted(selected):
        surfaces[(market, target)] = {
            lead: {
                name: harness._finish_accumulator(
                    name, accumulators.get((market, target, lead, name), harness._Accumulator()),
                ) for name in harness.SUMMARY_NAMES
            } for lead in harness.LEADS_SENSITIVITY
        }
    return surfaces, {
        "input_files": len(files), "input_bytes": sum(row["bytes"] for row in files),
        "csv_rows_visited": input_rows, "included_selected_rows_parsed": selected_rows,
        "selected_market_days": len(selected), "input_byte_mutation_refused": mutation_control,
        "outcome_values_converted_or_scored": False,
    }


def retained_predictions(body, selection):
    selected = {(row["market"], row["target_date"]): row["native_unit"] for row in selection["records"]}
    columns = ("raw_temperature_anchor_native", BASELINE + "_native", CHALLENGER + "_native")
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""))
    header = reader.fieldnames or []
    if len(set(header)) != len(header) or not set(("market", "target_date", "native_unit", *columns)) <= set(header):
        raise PreflightError("predictions:header")
    output = {}
    for row in reader:
        key = (row["market"], row["target_date"])
        if key not in selected:
            continue
        if key in output or row["native_unit"] != selected[key]:
            raise PreflightError("predictions:identity")
        values = {column: float(row[column]) for column in columns}
        if not all(math.isfinite(value) for value in values.values()):
            raise PreflightError("predictions:nonfinite")
        # Deliberately never access outcome_native, even on these old rows.
        output[key] = values
    if set(output) != set(selected):
        raise PreflightError("predictions:selected_row_missing")
    return output


def reproduce(manifest, harness, units):
    import numpy as np

    selection = load_selection(manifest["selection"], harness)
    training = json_bytes(_bound_fixed(manifest["training"], TRAINING_SHA256))
    terminal = json_bytes(_bound_fixed(manifest["terminal"], TERMINAL_SHA256))
    if (training.get("design_sha256") != DESIGN_SHA256 or training.get("models_fitted") != 2
            or training.get("status") != "PASS"):
        raise PreflightError("training:contract")
    files = terminal["feature_audit"]["source_files"]
    bodies = verified_model_bytes(manifest["models"], training)
    prior_body = _bound_fixed(manifest["predictions"], PREDICTIONS_SHA256)
    prior = retained_predictions(prior_body, selection)
    surfaces, feature_audit = selected_surfaces(manifest["corpus_root"], files, selection, harness, units)
    bundles = {arm: decode_model(body, arm, harness) for arm, body in bodies.items()}
    clone = decode_model(bodies[BASELINE], BASELINE, harness)
    records, baseline_matrix, challenger_matrix, anchors = [], [], [], []
    for selected in selection["records"]:
        market, day = selected["market"], selected["target_date"]
        args = {"market": market, "target_date": day, "leads": surfaces[(market, day)], "selected_leads": harness.LEADS_PRIMARY}
        baseline, anchor = harness.feature_vector(**args, challenger=False)
        challenger, other_anchor = harness.feature_vector(**args, challenger=True)
        if anchor != other_anchor:
            raise PreflightError("features:anchor_disagreement")
        baseline_matrix.append(baseline)
        challenger_matrix.append(challenger)
        anchors.append(anchor)
        records.append({**selected, "feature_vector_sha256": {
            BASELINE: canonical_digest(baseline), CHALLENGER: canonical_digest(challenger),
        }})
    anchor_array = np.asarray(anchors, dtype=float)
    baseline_array, challenger_array = np.asarray(baseline_matrix), np.asarray(challenger_matrix)
    predicted = {
        "raw_temperature_anchor_native": anchor_array,
        BASELINE + "_native": anchor_array + bundles[BASELINE]["estimator"].predict(baseline_array),
        CHALLENGER + "_native": anchor_array + bundles[CHALLENGER]["estimator"].predict(challenger_array),
    }
    clone_values = anchor_array + clone["estimator"].predict(baseline_array)
    if not np.array_equal(clone_values, predicted[BASELINE + "_native"]):
        raise PreflightError("control:clone_prediction_difference")
    maximum = 0.0
    for index, row in enumerate(records):
        expected = prior[(row["market"], row["target_date"])]
        row["predictions"] = {}
        for column, values in predicted.items():
            actual = float(values[index])
            difference = actual - expected[column]
            if not math.isfinite(actual):
                raise PreflightError("prediction:nonfinite")
            maximum = max(maximum, abs(difference))
            row["predictions"][column] = {"retained": expected[column], "reproduced": actual, "difference_native": difference}
    return {
        "status": "REPRODUCED" if maximum <= 1e-10 else "REPRODUCTION_BLOCKED",
        "absolute_tolerance_native": 1e-10, "relative_tolerance": 0,
        "maximum_absolute_difference_native": maximum, "records": records,
        "feature_audit": feature_audit, "clone_maximum_difference": 0.0,
        "artifact_substitution_refused_before_decode": True,
        "models_fitted": 0, "new_outcome_reads": False, "skill_estimate": None,
        "interpretation": "Numerical reproduction on 24 already-evaluated market-days; three dates are not an inference sample.",
    }
