"""MG-1 shadow tape: capture wiring, served-output invariance, frozen config, outcome blindness.

Guards: item 190 owner Q1-Q3 (2026-10-08) and the MG-1 pre-registration §1-§2.2; the
docs/operations/nbm-target-period-contract.md "MG-1 stage tape" section.
"""

import ast
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.collection import nbm_guidance_read_shadow as shadow
from weather.collection.snapshot_tracker import SnapshotStore
from weather.model import nbm_guidance_read as stage
from weather.model.source_adapters import FETCH_META_KEY
from weather.paths import config_path, repo_path
from weather.schema_registry import schema_version

TARGET = date(2026, 6, 18)
CAPTURED = datetime(2026, 6, 18, 14, 0, tzinfo=timezone.utc)
SLUG = "highest-temperature-in-new-york-city-on-june-18-2026"


class FakeFahrenheitClient:
    target_date = TARGET
    spec = SimpleNamespace(display_unit="F")

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


def _nbm_item(**overrides):
    payload = {
        "available": True,
        "period_kind": "maximum",
        "target_date": TARGET.isoformat(),
        "issued_at": "2026-06-18T07:00:00+00:00",
        "valid_time_utc": "2026-06-19T00:00:00+00:00",
        "mean_native": 81.4,
        "stddev_native": 2.2,
        FETCH_META_KEY: {
            "parser_version": "nbm-probabilistic-tmax-parser-v2",
            "response_received_at": "2026-06-18T08:10:00+00:00",
            "cache_status": "fresh",
            "stale": False,
        },
    }
    payload.update(overrides)
    return {"ok": True, "stale": False, "status": "ok", "data": payload}


def _model(**nbm_overrides):
    return {
        "distribution": {79: 0.1, 80: 0.3, 82: 0.4, 84: 0.2},
        "top_temp": 82,
        "sources": {"nbm_probabilistic_tmax": _nbm_item(**nbm_overrides)},
        "feature_vector": {"guidance_physical_floor": 78.0, "high_so_far": 80.2, "trusted_current_max": None},
    }


def _event():
    return {"slug": SLUG, "markets": []}


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


def _write_once(root, **patches):
    store = SnapshotStore(root=root, event_slug=SLUG)
    with patch.multiple("weather.collection.nbm_guidance_read_shadow", **patches) if patches else _null():
        result = store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED)
    files = {name: (root / name).read_bytes() for name in SERVED_ARTIFACTS if (root / name).exists()}
    tape_path = root / shadow.TAPE_FILENAME
    tape = [json.loads(line) for line in tape_path.read_text(encoding="utf-8").splitlines()] if tape_path.exists() else []
    return result, files, tape


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestShadowRow(unittest.TestCase):
    def _row(self, model=None, client=None):
        model = model or _model()
        client = client or FakeFahrenheitClient()
        band_rows = [
            {
                "bin_kind": b["kind"],
                "bin_value_c": b["value"],
                "bin_value_hi_c": b["value_hi"],
                "range_label": b["label"],
                "model_probability": client.bin_probability(model["distribution"], b),
            }
            for b in client.market_bins({})
        ]
        return shadow.build_row(
            snapshot_id="s1",
            captured_at=CAPTURED,
            event_slug=SLUG,
            market_id="nyc",
            target_date=TARGET,
            model=model,
            model_client=client,
            band_rows=band_rows,
            captured_input_hash="abc",
            runtime_fields={"runtime_git_commit": "c0ffee", "runtime_source_fingerprint": "fp"},
            release_lineage={"release_id": "", "release_identity_status": "unbound"},
        ), band_rows

    def test_eligible_read_produces_mg1_vector_bound_to_hashes(self):
        row, band_rows = self._row()
        self.assertEqual(row["schema_version"], schema_version("nbm_guidance_read_shadow"))
        self.assertEqual(row["status"], stage.STATUS_MG1)
        self.assertIsNone(row["reason"])
        self.assertEqual(row["stage_id"], stage.STAGE_ID)
        self.assertEqual(row["stage_config_sha256"], stage.stage_config_sha256())
        self.assertEqual(row["stage_code_sha256"], stage.stage_code_sha256())
        self.assertEqual(row["captured_input_hash"], "abc")
        self.assertEqual(row["runtime_git_commit"], "c0ffee")
        self.assertEqual(row["floor"], 80.2)
        self.assertEqual(row["floor_bucket"], 80)
        self.assertFalse(row["pit_violation"])
        self.assertTrue(row["read"]["eligible"])
        self.assertAlmostEqual(sum(row["stage_vector"]), 1.0, places=12)
        self.assertEqual(row["stage_vector"][0], 0.0)  # 79 F or below is below B = 80
        self.assertEqual(row["served_vector"], [r["model_probability"] for r in band_rows])
        json.dumps(row)  # the row must be JSON-serialisable as written

    def test_ineligible_read_falls_back_to_served_vector(self):
        row, band_rows = self._row(model=_model(period_kind="minimum"))
        self.assertEqual(row["status"], stage.STATUS_FALLBACK)
        self.assertEqual(row["reason"], "period_kind_not_maximum")
        self.assertEqual(row["stage_vector"], [r["model_probability"] for r in band_rows])

    def test_issue_after_capture_is_a_recorded_pit_violation(self):
        row, _ = self._row(model=_model(issued_at="2026-06-18T15:00:00+00:00"))
        self.assertEqual(row["status"], stage.STATUS_FALLBACK)
        self.assertTrue(row["pit_violation"])

    def test_celsius_market_falls_back_out_of_scope(self):
        client = FakeFahrenheitClient()
        client.spec = SimpleNamespace(display_unit="C")
        row, _ = self._row(client=client)
        self.assertEqual(row["reason"], "unit_not_fahrenheit")

    def test_missing_served_probability_is_skipped(self):
        row = shadow.build_row(
            snapshot_id="s1", captured_at=CAPTURED, event_slug=SLUG, market_id="nyc", target_date=TARGET,
            model=_model(), model_client=FakeFahrenheitClient(),
            band_rows=[{"bin_kind": "lte", "bin_value_c": 79, "bin_value_hi_c": 79, "model_probability": None}],
            captured_input_hash="",
        )
        self.assertEqual(row["status"], shadow.STATUS_SKIPPED)
        self.assertEqual(row["reason"], "served_vector_incomplete")


class TestSnapshotStoreWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp) / "event"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _fresh(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        return self.root

    def test_one_row_per_snapshot(self):
        _result, _files, tape = _write_once(self._fresh())
        self.assertEqual(len(tape), 1)
        self.assertEqual(tape[0]["status"], stage.STATUS_MG1)
        self.assertEqual(tape[0]["event_slug"], SLUG)
        replay = json.loads((self.root / "replay_inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(tape[0]["captured_input_hash"], replay["captured_input_hash"])

    def test_served_artifacts_are_byte_identical_with_stage_on_or_off(self):
        result_on, files_on, tape_on = _write_once(self._fresh())
        result_off, files_off, tape_off = _write_once(
            self._fresh(), build_row=_raise("stage disabled for the invariance test")
        )
        self.assertEqual(sorted(files_on), sorted(files_off))
        self.assertIn("snapshots.jsonl", files_on)
        for name in files_on:
            self.assertEqual(files_on[name], files_off[name], name)
        self.assertEqual(result_on, result_off)
        self.assertEqual(tape_on[0]["status"], stage.STATUS_MG1)
        self.assertEqual(tape_off[0]["status"], shadow.STATUS_ERROR)
        self.assertIn("stage disabled", tape_off[0]["reason"])

    def test_tape_write_failure_never_blocks_the_snapshot(self):
        store = SnapshotStore(root=self._fresh(), event_slug=SLUG)
        original = SnapshotStore.append_jsonl

        def failing(self_, path, payload, **kwargs):
            if Path(path).name == shadow.TAPE_FILENAME:
                raise OSError("disk full")
            return original(self_, path, payload, **kwargs)

        with patch.object(SnapshotStore, "append_jsonl", failing):
            result = store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED)
        self.assertTrue(result["written"])
        self.assertTrue((self.root / "snapshots.jsonl").exists())
        self.assertFalse((self.root / shadow.TAPE_FILENAME).exists())

    def test_builder_does_not_mutate_served_rows(self):
        store = SnapshotStore(root=self._fresh(), event_slug=SLUG)
        seen = {}
        real = shadow.build_row

        def spy(**kwargs):
            seen["before"] = json.dumps(kwargs["band_rows"], sort_keys=True, default=str)
            row = real(**kwargs)
            seen["after"] = json.dumps(kwargs["band_rows"], sort_keys=True, default=str)
            return row

        with patch("weather.collection.nbm_guidance_read_shadow.build_row", spy):
            store.write(_event(), _model(), FakeFahrenheitClient(), CAPTURED)
        self.assertEqual(seen["before"], seen["after"])


def _raise(message):
    def boom(**_kwargs):
        raise RuntimeError(message)

    return boom


class TestFrozenConfig(unittest.TestCase):
    def test_frozen_config_entry_matches_the_stage_module(self):
        frozen = json.loads(config_path("mg1_guidance_read_stage.json").read_text(encoding="utf-8"))
        self.assertEqual(frozen["stage_id"], stage.STAGE_ID)
        self.assertEqual(frozen["constants"], stage.STAGE_CONSTANTS)
        self.assertEqual(frozen["config_sha256"], stage.stage_config_sha256())
        self.assertEqual(
            frozen["code_sha256"],
            stage.stage_code_sha256(),
            "nbm_guidance_read.py changed: a rule change needs a new stage id and pre-registration, "
            "a non-rule change needs an owner-reviewed re-freeze of config/mg1_guidance_read_stage.json",
        )


# Modules allowed to be imported (transitively at the first level) by the stage and tape modules.
_ALLOWED_WEATHER_IMPORTS = {
    "weather.model.nbm_guidance_read",
    "weather.model.source_adapters",
    "weather.sources.nbm_probabilistic_tmax",
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


class TestNoOutcomeJoin(unittest.TestCase):
    STAGE_MODULES = (
        repo_path("src", "weather", "model", "nbm_guidance_read.py"),
        repo_path("src", "weather", "collection", "nbm_guidance_read_shadow.py"),
    )

    def test_stage_and_tape_modules_import_no_outcome_loader(self):
        for path in self.STAGE_MODULES:
            for name in _weather_imports(path):
                module = name if name in _ALLOWED_WEATHER_IMPORTS else name.rsplit(".", 1)[0]
                self.assertIn(
                    module,
                    _ALLOWED_WEATHER_IMPORTS | {"weather.model", "weather.collection"},
                    f"{path.name} imports {name}",
                )
                self.assertFalse(
                    any(token in name.lower() for token in _OUTCOME_TOKENS),
                    f"{path.name} imports an outcome-shaped module {name}",
                )

    def test_no_reporting_backtesting_or_daily_refresh_module_reads_the_tape(self):
        roots = [
            repo_path("src", "weather", "reporting"),
            repo_path("src", "weather", "backtesting"),
            repo_path("src", "weather", "scoring"),
        ]
        files = [p for root in roots for p in root.rglob("*.py")]
        files += list(repo_path("src", "weather", "operations").glob("daily_refresh*.py"))
        self.assertTrue(files)
        offenders = [
            str(p) for p in files
            if "nbm_guidance_read_shadow" in p.read_text(encoding="utf-8", errors="replace")
        ]
        self.assertEqual(offenders, [], "the MG-1 tape may be joined to outcomes only by a pre-registered D0 look")


if __name__ == "__main__":
    unittest.main()
