"""t3-r3 shadow tape: capture wiring, served-output invariance, replay, outcome blindness.

Guards: remaining-rise 13-16 pre-registration §1 (shadow only, never served) and §8 validity conditions
(artifact hash, METAR freshness, captured-input replay within 1e-12); owner OD-B1 (2026-10-15).
"""

import ast
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weather.collection import remaining_rise_floor_shadow as shadow
from weather.collection.snapshot_tracker import SnapshotStore
from weather.model import remaining_rise_floor as stage
from weather.operations.storage_classes import CANONICAL_EVIDENCE, classify_storage_path
from weather.paths import repo_path
from weather.schema_registry import schema_version

TARGET = date(2026, 6, 18)
CAPTURED = datetime(2026, 6, 18, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT at KLGA
SLUG = "highest-temperature-in-nyc-on-june-18-2026"


class FakeFahrenheitClient:
    target_date = TARGET
    spec = SimpleNamespace(display_unit="F", icao="KLGA", timezone="America/New_York")

    def market_bins(self, _event):
        return [
            {"label": "79 F or below", "kind": "lte", "value": 79, "value_hi": 79, "status": "active"},
            {"label": "80-81 F", "kind": "eq", "value": 80, "value_hi": 81, "status": "active"},
            {"label": "82-83 F", "kind": "eq", "value": 82, "value_hi": 83, "status": "active"},
            {"label": "84 F or higher", "kind": "gte", "value": 84, "value_hi": 84, "status": "active"},
        ]

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        low, high = int(bin_data["value"]), int(bin_data["value_hi"])
        kind = bin_data["kind"]
        total = 0.0
        for temp, prob in distribution.items():
            temp = int(temp)
            if (kind == "lte" and temp <= low) or (kind == "gte" and temp >= low) or (
                kind == "eq" and low <= temp <= high
            ):
                total += float(prob)
        return total

    def source_data(self, _sources, _name):
        return {}

    def forecast_ensemble_metrics(self, *_args, **_kwargs):
        return {}

    def max_row_temp(self, _rows):
        return None


def _metar(stale=False, obs_time="2026-06-18T13:51:00Z"):
    return {"ok": True, "stale": stale, "data": {"rows": [{"obs_time": "2026-06-18T12:51:00Z"}, {"obs_time": obs_time}]}}


def _model(stale=False, floor=80.2, obs_time="2026-06-18T13:51:00Z"):
    return {
        "distribution": {79: 0.1, 80: 0.3, 82: 0.4, 84: 0.2},
        "top_temp": 82,
        "sources": {"metar": _metar(stale, obs_time)},
        "feature_vector": {"guidance_physical_floor": 78.0, "high_so_far": floor, "trusted_current_max": None},
    }


def _band_rows(client, model):
    return [
        {
            "bin_kind": b["kind"],
            "bin_value_c": b["value"],
            "bin_value_hi_c": b["value_hi"],
            "range_label": b["label"],
            "model_probability": client.bin_probability(model["distribution"], b),
        }
        for b in client.market_bins({})
    ]


def _row(model=None, client=None, captured_at=CAPTURED, **kwargs):
    model = model or _model()
    client = client or FakeFahrenheitClient()
    band_rows = _band_rows(client, model)
    row = shadow.build_row(
        snapshot_id="s1",
        captured_at=captured_at,
        event_slug=SLUG,
        market_id="nyc",
        target_date=TARGET,
        model=model,
        model_client=client,
        band_rows=band_rows,
        captured_input_hash="abc",
        runtime_fields={"runtime_git_commit": "c0ffee", "runtime_source_fingerprint": "fp"},
        release_lineage={"release_id": "", "release_identity_status": "unbound"},
        **kwargs,
    )
    return row, band_rows


class TestShadowRow:
    def test_eligible_row_carries_stage_vector_and_bindings(self):
        row, band_rows = _row()
        table = stage.load_table()
        cell = table.cell("KLGA", 6, 10)
        expected = stage.apply(
            [stage.band_from_row(r) for r in band_rows], [r["model_probability"] for r in band_rows],
            floor=80.2, cell=cell, metar_stale=False, on_target_date=True, artifact_sha256=table.sha256,
        )
        assert row["schema_version"] == schema_version("remaining_rise_floor_shadow")
        assert row["status"] == stage.STATUS_STAGE and row["reason"] is None
        assert row["stage_id"] == stage.STAGE_ID
        assert row["stage_config_sha256"] == stage.stage_config_sha256()
        assert row["stage_code_sha256"] == stage.stage_code_sha256()
        assert row["artifact_sha256"] == stage.ARTIFACT_SHA256
        assert row["captured_input_hash"] == "abc" and row["runtime_git_commit"] == "c0ffee"
        assert (row["floor"], row["floor_bucket"]) == (80.2, 80)
        assert row["cell_key"]["hour"] == 10 and row["cell"]["station"] == "KLGA"
        assert row["stage_vector"] == list(expected.vector)
        assert row["stage_vector"][0] == 0.0  # 79 F or below is below B = 80
        assert sum(row["stage_vector"]) == pytest.approx(1.0, abs=1e-12)
        assert row["served_vector"] == [r["model_probability"] for r in band_rows]
        assert row["metar"]["newest_obs_time_utc"] == "2026-06-18T13:51:00+00:00"
        assert row["metar"]["newest_age_minutes"] == pytest.approx(9.0)
        json.dumps(row, allow_nan=False)

    def test_replay_reproduces_the_stored_vector_exactly(self):
        table = stage.load_table()
        for model in (_model(), _model(stale=True), _model(floor=None)):
            row, _ = _row(model=model)
            stored = json.loads(json.dumps(row))
            assert shadow.replay_row(stored, table) == row["stage_vector"]

    def test_stale_metar_falls_back_to_served(self):
        row, band_rows = _row(model=_model(stale=True))
        assert (row["status"], row["reason"]) == (stage.STATUS_FALLBACK, "metar_stale")
        assert row["stage_vector"] == [r["model_probability"] for r in band_rows]

    def test_metar_newer_than_capture_is_recorded(self):
        row, _ = _row(model=_model(obs_time="2026-06-18T14:05:00Z"))
        assert row["metar"]["newest_after_capture"] is True

    def test_celsius_market_falls_back(self):
        client = FakeFahrenheitClient()
        client.spec = SimpleNamespace(display_unit="C", icao="KLGA", timezone="America/New_York")
        row, _ = _row(client=client)
        assert row["reason"] == "unit_not_fahrenheit"

    def test_missing_artifact_falls_back_on_hash(self):
        with patch.object(stage, "load_table", side_effect=OSError("missing")):
            row, _ = _row()
        assert row["artifact_sha256"] is None
        assert row["reason"] == "artifact_hash_mismatch"

    def test_missing_served_probability_is_skipped(self):
        row = shadow.build_row(
            snapshot_id="s1", captured_at=CAPTURED, event_slug=SLUG, market_id="nyc", target_date=TARGET,
            model=_model(), model_client=FakeFahrenheitClient(),
            band_rows=[{"bin_kind": "lte", "bin_value_c": 79, "bin_value_hi_c": 79, "model_probability": None}],
            captured_input_hash="",
        )
        assert (row["status"], row["reason"]) == (shadow.STATUS_SKIPPED, "served_vector_incomplete")

    def test_error_row_keeps_identity(self):
        row = shadow.error_row(
            RuntimeError("boom"), snapshot_id="s1", captured_at=CAPTURED, event_slug=SLUG, market_id="nyc",
            target_date=TARGET, unit=None, captured_input_hash="abc", runtime_fields=None, release_lineage=None,
        )
        assert (row["status"], row["reason"], row["stage_vector"]) == (shadow.STATUS_ERROR, "RuntimeError: boom", None)
        assert row["snapshot_id"] == "s1" and row["captured_input_hash"] == "abc"
        assert shadow.replay_row(row, stage.load_table()) is None


SERVED_ARTIFACTS = (
    "snapshots_long.csv",
    "snapshots_wide.csv",
    "snapshots.jsonl",
    "replay_inputs.jsonl",
    "features_long.csv",
    "features.jsonl",
    "variant_predictions_long.csv",
    "variant_predictions.jsonl",
)


def _event():
    return {"slug": SLUG, "markets": []}


def _fresh(root):
    root.mkdir(parents=True, exist_ok=False)
    return root


def _write_once(root, runtime_guard=None, build_row=None):
    store = SnapshotStore(root=root, event_slug=SLUG)
    if build_row is None:
        result = store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED, runtime_guard=runtime_guard)
    else:
        with patch.object(shadow, "build_row", build_row):
            result = store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED, runtime_guard=runtime_guard)
    files = {name: (root / name).read_bytes() for name in SERVED_ARTIFACTS if (root / name).exists()}
    tape_path = root / shadow.TAPE_FILENAME
    tape = [json.loads(line) for line in tape_path.read_text(encoding="utf-8").splitlines()] if tape_path.exists() else []
    return result, files, tape


def _raise(message):
    def boom(**_kwargs):
        raise RuntimeError(message)

    return boom


class TestSnapshotStoreWiring:
    def test_one_row_per_snapshot(self, tmp_path):
        root = _fresh(tmp_path / "event")
        _result, _files, tape = _write_once(root)
        assert len(tape) == 1
        assert tape[0]["status"] == stage.STATUS_STAGE
        assert tape[0]["event_slug"] == SLUG and tape[0]["target_date"] == "2026-06-18"
        replay = json.loads((root / "replay_inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert tape[0]["captured_input_hash"] == replay["captured_input_hash"]

    def test_served_artifacts_are_byte_identical_with_stage_on_or_off(self, tmp_path):
        # One runtime guard for both writes: its current-identity probe is timestamped.
        guard = SnapshotStore(root=_fresh(tmp_path / "probe"), event_slug=SLUG).runtime_identity_guard()
        root = tmp_path / "event"
        result_on, files_on, tape_on = _write_once(_fresh(root), guard)
        shutil.rmtree(root)  # same root for both writes: the result carries the paths
        result_off, files_off, tape_off = _write_once(
            _fresh(root), guard, build_row=_raise("stage disabled for the invariance test")
        )
        assert sorted(files_on) == sorted(files_off)
        assert "snapshots.jsonl" in files_on
        for name in files_on:
            assert files_on[name] == files_off[name], name
        assert result_on == result_off
        assert tape_on[0]["status"] == stage.STATUS_STAGE
        assert tape_off[0]["status"] == shadow.STATUS_ERROR
        assert "stage disabled" in tape_off[0]["reason"]

    def test_tape_write_failure_never_blocks_the_snapshot(self, tmp_path):
        root = _fresh(tmp_path / "event")
        store = SnapshotStore(root=root, event_slug=SLUG)
        original = SnapshotStore.append_jsonl

        def failing(self_, path, payload, **kwargs):
            if Path(path).name == shadow.TAPE_FILENAME:
                raise OSError("disk full")
            return original(self_, path, payload, **kwargs)

        with patch.object(SnapshotStore, "append_jsonl", failing):
            result = store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED)
        assert result["written"]
        assert (root / "snapshots.jsonl").exists()
        assert not (root / shadow.TAPE_FILENAME).exists()

    def test_builder_does_not_mutate_served_rows(self, tmp_path):
        store = SnapshotStore(root=_fresh(tmp_path / "event"), event_slug=SLUG)
        seen = {}
        real = shadow.build_row

        def spy(**kwargs):
            seen["before"] = json.dumps(kwargs["band_rows"], sort_keys=True, default=str)
            row = real(**kwargs)
            seen["after"] = json.dumps(kwargs["band_rows"], sort_keys=True, default=str)
            return row

        with patch.object(shadow, "build_row", spy):
            store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED)
        assert seen["before"] == seen["after"]

    def test_tape_is_classified_as_canonical_evidence(self):
        classification = classify_storage_path(f"data/snapshots/{SLUG}/{shadow.TAPE_FILENAME}")
        assert classification.storage_class == CANONICAL_EVIDENCE
        assert classification.protected


_ALLOWED_WEATHER_IMPORTS = {
    "weather.artifacts",
    "weather.units",
    "weather.model",
    "weather.model.remaining_rise_floor",
    "weather.schema_registry",
}
_OUTCOME_TOKENS = ("settle", "settlement", "panel", "score", "outcome", "88a", "wu_history", "realized", "observed_high")


def _weather_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("weather"):
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names if alias.name.startswith("weather"))
    return names


class TestNoOutcomeJoin:
    STAGE_MODULES = (
        repo_path("src", "weather", "model", "remaining_rise_floor.py"),
        repo_path("src", "weather", "collection", "remaining_rise_floor_shadow.py"),
        repo_path("src", "weather", "backtesting", "remaining_rise_floor_decision.py"),
    )

    def test_stage_tape_and_decision_modules_import_no_outcome_loader(self):
        for path in self.STAGE_MODULES:
            for name in _weather_imports(path):
                allowed = name in _ALLOWED_WEATHER_IMPORTS or name.rsplit(".", 1)[0] in _ALLOWED_WEATHER_IMPORTS
                assert allowed, f"{path.name} imports {name}"
                assert not any(token in name.lower() for token in _OUTCOME_TOKENS), name

    def test_no_reporting_backtesting_or_daily_refresh_module_reads_the_tape(self):
        roots = [repo_path("src", "weather", name) for name in ("reporting", "backtesting", "scoring")]
        files = [p for root in roots if root.exists() for p in root.rglob("*.py")]
        files += list(repo_path("src", "weather", "operations").glob("daily_refresh*.py"))
        assert files
        offenders = [
            str(p) for p in files
            if "remaining_rise_floor_shadow" in p.read_text(encoding="utf-8", errors="replace")
        ]
        assert offenders == [], "the t3-r3 tape may be joined to outcomes only by the pre-registered look"
