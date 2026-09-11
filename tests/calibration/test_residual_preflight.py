from __future__ import annotations

import base64
import csv
from dataclasses import replace
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from weather.calibration import residual_preflight as core
from weather.calibration import residual_preflight_inputs as inputs
from weather.calibration import residual_preflight_io as bound_io
from weather.calibration import residual_preflight_simulation as simulation


def binding(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"path": str(path.resolve()), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def test_byte_substitution_rejected_with_unchanged_length(tmp_path):
    record = binding(tmp_path / "input", b"original")
    assert bound_io.read_bound(record) == b"original"
    assert bound_io.mutation_refused(b"original", record)
    Path(record["path"]).write_bytes(b"changed!")
    with pytest.raises(bound_io.PreflightError, match="sha256_differ"):
        bound_io.read_bound(record)


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_json_ambiguity_is_rejected(body):
    with pytest.raises(bound_io.PreflightError):
        bound_io.json_bytes(body)


def test_size_bound_precedes_file_access(tmp_path):
    with pytest.raises(bound_io.PreflightError, match="size_bound"):
        bound_io.read_bound({"path": str(tmp_path / "absent"), "bytes": 100, "sha256": "0" * 64}, maximum=99)


def test_unreviewed_model_is_rejected_before_deserialization(monkeypatch):
    monkeypatch.setattr(inputs.pickle, "loads", lambda _: pytest.fail("unverified pickle executed"))
    with pytest.raises(bound_io.PreflightError, match="unreviewed_pickle_bytes"):
        inputs.decode_model(b"untrusted pickle", inputs.BASELINE, None)
    with pytest.raises(bound_io.PreflightError, match="frozen_identity"):
        inputs.verified_model_bytes(
            [{"arm": inputs.BASELINE, "bytes": 1, "sha256": "0" * 64}, {}],
            {"artifacts": [{"arm": inputs.BASELINE, "bytes": 1, "sha256": "0" * 64}]},
        )


def test_selection_change_refused_before_opening_file(monkeypatch):
    monkeypatch.setattr(inputs, "read_bound", lambda *_: pytest.fail("changed selection opened"))
    with pytest.raises(bound_io.PreflightError, match="predeclared_sample"):
        inputs.load_selection({"sha256": "0" * 64}, None)


def test_source_change_is_rejected_before_import(tmp_path, monkeypatch):
    frozen = "src/weather/frozen_fixture.py"
    record = binding(tmp_path / frozen, b"fixed")
    monkeypatch.setattr(core, "FROZEN_SOURCES", {frozen: record["sha256"]})
    monkeypatch.setattr(core, "PRODUCER_FILES", set())
    assert len(core.verify_source_bindings(tmp_path, [])) == 1
    (tmp_path / frozen).write_bytes(b"other")
    with pytest.raises(bound_io.PreflightError, match="sha256_differ"):
        core.verify_source_bindings(tmp_path, [])


def test_retained_prediction_reader_ignores_outcomes_and_unselected_values():
    header = "market,target_date,native_unit,outcome_native,raw_temperature_anchor_native,temperature_residual_baseline_native,eleven_field_residual_challenger_native\n"
    rows = "toronto,2025-05-10,C,DO_NOT_PARSE,20,21,22\nnyc,2025-05-11,F,DO_NOT_PARSE,invalid,invalid,invalid\n"
    selection = {"records": [{"market": "toronto", "target_date": "2025-05-10", "native_unit": "C"}]}
    result = inputs.retained_predictions((header + rows).encode(), selection)
    assert result[("toronto", "2025-05-10")][inputs.BASELINE + "_native"] == 21
    with pytest.raises(bound_io.PreflightError, match="identity"):
        inputs.retained_predictions((header + rows + rows.splitlines()[0] + "\n").encode(), selection)


def _feature_fixture(tmp_path):
    from weather.calibration import multiyear_nwp_residual as harness
    from weather.sources.previous_runs_research_collection import EXPECTED_UNITS

    selection = {"records": [{"market": market, "target_date": "2025-05-10", "native_unit": unit}
                              for market, unit in (("dallas", "F"), ("toronto", "C"))]}
    files = []
    for market in harness.MARKETS:
        for segment in harness.SEGMENTS:
            relative = f"units/{market}--2025--{segment}/completed/normalized.csv"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(harness.CSV_COLUMNS)
            if market in {"dallas", "toronto"} and segment == harness.SEGMENTS[0]:
                for lead in harness.LEADS_SENSITIVITY:
                    for field in harness.FIELDS:
                        unit = "°" + harness.MARKET_UNITS[market] if field == "temperature_2m" else EXPECTED_UNITS[field]
                        for hour in range(24):
                            writer.writerow([market, f"2025-05-10T{hour:02}:00", field, lead,
                                             lead + hour, unit, "fixed_lead_day_offset", "open_meteo_previous_runs"])
                writer.writerow([market, "2025-05-10T00:00", harness.EXCLUDED_FIELD, 1, "NOT_A_VALUE", "%", "", ""])
                writer.writerow([market, "2025-05-11T00:00", "temperature_2m", 1, "NOT_A_VALUE", "?", "", ""])
            row = binding(tmp_path / relative, stream.getvalue().encode())
            files.append({key: value for key, value in row.items() if key != "path"} | {"relative_path": relative})
    return harness, EXPECTED_UNITS, selection, files


def test_selected_features_preserve_native_units_and_exact_frozen_summary(tmp_path):
    harness, units, selection, files = _feature_fixture(tmp_path)
    surfaces, audit = inputs.selected_surfaces(tmp_path, files, selection, harness, units)
    assert set(surfaces) == {("dallas", "2025-05-10"), ("toronto", "2025-05-10")}
    assert audit["selected_market_days"] == 2
    assert audit["input_byte_mutation_refused"]
    assert audit["outcome_values_converted_or_scored"] is False
    for key, surface in surfaces.items():
        assert surface[2]["temperature_2m_daily_max"] == 25
        assert surface[2]["cloud_cover_09_18_mean"] == 15.5
        assert surface[2]["shortwave_radiation_07_20_integral"] == 217
        vector, anchor = harness.feature_vector(market=key[0], target_date=key[1], leads=surface,
                                               selected_leads=harness.LEADS_PRIMARY, challenger=False)
        assert anchor == 27.5
        assert len(vector) == 17


@pytest.mark.parametrize("change", ["unit", "duplicate_hour"])
def test_selected_feature_semantics_reject_wrong_unit_or_duplicate_hour(tmp_path, change):
    harness, units, selection, files = _feature_fixture(tmp_path)
    record = next(row for row in files if row["relative_path"].startswith("units/dallas--2025--may"))
    path = tmp_path / record["relative_path"]
    lines = path.read_text(encoding="utf-8").splitlines()
    if change == "unit":
        lines[1] = lines[1].replace("°F", "°C")
    else:
        lines.append(lines[1])
    body = ("\n".join(lines) + "\n").encode()
    changed = binding(path, body)
    record.update(bytes=changed["bytes"], sha256=changed["sha256"])
    with pytest.raises(bound_io.PreflightError):
        inputs.selected_surfaces(tmp_path, files, selection, harness, units)


def test_dependency_content_change_is_rejected_even_with_same_metadata(tmp_path, monkeypatch):
    records = []
    for package, import_name in bound_io.PACKAGES.items():
        runtime = tmp_path / import_name / "__init__.py"
        body = b"VERSION = 'fixture'\n"
        binding(runtime, body)
        info = tmp_path / (package + "-1.dist-info")
        encoded = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("=")
        csv_record = f"{import_name}/__init__.py,sha256={encoded},{len(body)}\n".encode()
        for name, value in (("METADATA", b"Version: 1\n"), ("RECORD", csv_record)):
            records.append({"package": package, **binding(info / name, value)})
    monkeypatch.setattr(bound_io.sysconfig, "get_path", lambda _: str(tmp_path))
    result = bound_io.verify_dependencies(records)
    assert result["runtime_files"] == 4
    (tmp_path / "numpy/__init__.py").write_bytes(b"VERSION = 'changed'\n")
    with pytest.raises(bound_io.PreflightError, match="content_changed"):
        bound_io.verify_dependencies(records)


def test_two_way_intercept_variance_matches_independent_scalar_calculation():
    panel = np.array([[1., 2.], [4., 8.], [3., 7.]])
    dates, markets = panel.shape
    n = dates * markets
    mean = sum(float(x) for row in panel for x in row) / n
    residuals = [[float(x) - mean for x in row] for row in panel]
    date_meat = dates / (dates - 1) * sum(sum(row) ** 2 for row in residuals)
    market_meat = markets / (markets - 1) * sum(sum(row[j] for row in residuals) ** 2 for j in range(markets))
    cell_meat = n / (n - 1) * sum(x * x for row in residuals for x in row)
    expected = (date_meat + market_meat - cell_meat) / n ** 2
    result = simulation.variance_estimators(panel, hac_lags=0)
    assert result["two_way_crv1"][0] == pytest.approx(expected)
    assert result["date_hac7_plus_market_minus_cell"][0] == pytest.approx(expected)
    assert simulation.variance_estimators(panel * 3 + 100)["two_way_crv1"][0] == pytest.approx(9 * expected)
    assert simulation.variance_estimators(panel[::-1, ::-1])["two_way_crv1"][0] == pytest.approx(expected)


def test_nonpositive_variances_are_preserved_for_refusal():
    constant = simulation.variance_estimators(np.ones((3, 4)))
    assert all(values[0] == 0 for values in constant.values())
    checkerboard = simulation.variance_estimators(np.array([[1., -1.], [-1., 1.]]))
    assert checkerboard["two_way_crv1"][0] < 0


def test_oracle_covariance_has_date_persistence_and_market_floor():
    scenario = {"markets": 2, "date_sd": 1., "market_sd": .5, "cell_sd": 2.,
                "date_ar1": .5, "late_sd_multiplier": 1.}
    assert simulation.oracle_variance(2, scenario)["total"] == pytest.approx(1.875)
    scenario["late_sd_multiplier"] = 2.
    assert simulation.oracle_variance(2, scenario)["total"] == pytest.approx(4.375)
    floor = {**scenario, "date_sd": 0., "cell_sd": 0.}
    assert simulation.oracle_variance(60, floor)["total"] == simulation.oracle_variance(240, floor)["total"] == .125


def test_power_direction_and_monte_carlo_counts_on_small_synthetic_fixture(monkeypatch):
    monkeypatch.setattr(simulation, "SCENARIOS", (simulation.SCENARIOS[0],))
    result = simulation.run_grid({**simulation.DEFAULT_CONFIG, "replicates": 100, "batch_size": 25})
    assert result["alpha_spent"] == 0 and result["real_dates_required"] is None
    for row in result["rows"]:
        powers = [effect["positive_lower_bound_probability"]["rate"] for effect in row["effect_scenarios"]]
        assert powers == sorted(powers)
        assert row["null_one_sided_false_positive"]["replicates"] == 100
        assert row["null_two_sided_95_coverage"]["mc_95_interval"][0] <= row["null_two_sided_95_coverage"]["rate"]
        if row["method"] == "known_covariance_oracle":
            assert row["invalid_variance"]["count"] == 0


def test_outputs_cannot_overwrite_prior_attempt(tmp_path):
    path = tmp_path / "report.json"
    bound_io.write_new_json(path, {"status": "kept"})
    with pytest.raises(FileExistsError):
        bound_io.write_new_json(path, {"status": "replaced"})
    assert json.loads(path.read_text()) == {"status": "kept"}


def test_preflight_imports_resolve_to_the_test_checkout():
    root = Path(__file__).resolve().parents[2]
    for module in (core, inputs, bound_io, simulation):
        path = Path(module.__file__).resolve()
        expected = root / "src" / Path(*module.__name__.split(".")).with_suffix(".py")
        assert path == expected
        print({"module": module.__name__, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
