"""MG-1 stage replay/check CLI: L1/L2 reproduction, L3 byte re-derivation, D0 check, refusals.

Guards: MG-1 pre-registration §6 ("Replay": 100% within 1e-12) and §8 (v2 mean from primary bytes);
OD32 D0 helper; item 190 owner Q3 (outcome-blind tape). Synthetic fixtures only, no outcomes.
"""

import ast
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.backtesting import nbm_guidance_read_replay as replay
from weather.collection import nbm_guidance_read_shadow as shadow
from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
from weather.collection.snapshot_tracker import SnapshotStore
from weather.model import nbm_guidance_read as stage
from weather.model.source_adapters import FETCH_META_KEY
from weather.paths import data_path, repo_path
from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax

TARGET = date(2026, 10, 20)
SLUG = "highest-temperature-in-nyc-on-october-20-2026"
FIRST = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
SECOND = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
FIXTURE = repo_path("tests", "fixtures", "nbm_target_fix", "p0", "20260917T12Z-KLGA.txt")


class FakeFahrenheitClient:
    target_date = TARGET
    spec = SimpleNamespace(display_unit="F")

    def market_bins(self, _event):
        return [
            {"label": "59 F or below", "kind": "lte", "value": 59, "value_hi": 59, "status": "active"},
            {"label": "60-61 F", "kind": "eq", "value": 60, "value_hi": 61, "status": "active"},
            {"label": "62-63 F", "kind": "eq", "value": 62, "value_hi": 63, "status": "active"},
            {"label": "64 F or higher", "kind": "gte", "value": 64, "value_hi": 64, "status": "active"},
        ]

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        low, high, kind = int(bin_data["value"]), int(bin_data["value_hi"]), bin_data["kind"]
        return sum(
            float(p) for t, p in distribution.items()
            if (kind == "lte" and int(t) <= low) or (kind == "gte" and int(t) >= low)
            or (kind == "eq" and low <= int(t) <= high)
        )

    def source_data(self, _sources, _name):
        return {}

    def forecast_ensemble_metrics(self, *_args, **_kwargs):
        return {}

    def max_row_temp(self, _rows):
        return None


def _model(**overrides):
    payload = {
        "available": True,
        "period_kind": "maximum",
        "target_date": TARGET.isoformat(),
        "issued_at": "2026-10-20T07:00:00+00:00",
        "valid_time_utc": "2026-10-21T00:00:00+00:00",
        "mean_native": 61.4,
        "stddev_native": 2.2,
        "parser_version": "nbm-probabilistic-tmax-parser-v2",
        FETCH_META_KEY: {"response_received_at": "2026-10-20T08:10:00+00:00", "cache_status": "fresh"},
    }
    payload.update(overrides)
    return {
        "distribution": {59: 0.1, 60: 0.3, 62: 0.4, 64: 0.2},
        "top_temp": 62,
        "sources": {"nbm_probabilistic_tmax": {"ok": True, "stale": False, "data": payload}},
        "feature_vector": {"guidance_physical_floor": 58.0, "high_so_far": 60.2, "trusted_current_max": None},
    }


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.snapshots = self.tmp / "snapshots"
        self.folder = self.snapshots / SLUG
        self.folder.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_two_snapshots(self):
        store = SnapshotStore(root=self.folder, event_slug=SLUG)
        event = {"slug": SLUG, "markets": []}
        store.write(event, _model(), FakeFahrenheitClient(), FIRST)
        store.write(event, _model(period_kind="minimum"), FakeFahrenheitClient(), SECOND)

    def run_cli(self, *args, name="out.jsonl"):
        out = self.tmp / "reports" / name
        code = replay.main([*args, "--out", str(out), "--snapshots-root", str(self.snapshots)])
        lines = out.read_text(encoding="utf-8").splitlines() if out.exists() else []
        return code, [json.loads(line) for line in lines]

    def rewrite(self, name, mutate):
        path = self.folder / name
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        mutate(rows)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class TestReplayL1L2(_Tmp):
    def test_store_written_tape_reproduces_at_l1_and_l2(self):
        self.write_two_snapshots()
        code, lines = self.run_cli(str(self.folder))
        rows, summary = lines[:-1], lines[-1]
        self.assertEqual(code, 0)
        self.assertEqual(summary["kind"], replay.SUMMARY_KIND)
        self.assertEqual(summary["replay_check"], "PASS")
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["status"], {stage.STATUS_MG1: 1, stage.STATUS_FALLBACK: 1})
        self.assertEqual(summary["fallback_reasons"], {"period_kind_not_maximum": 1})
        self.assertEqual(summary["non_maximum_period_kind"], 1)
        self.assertTrue(all(row["l1"] == "reproduced" and row["l2"] == "reproduced" for row in rows))
        self.assertTrue(all(row["t_plus_0"] for row in rows))
        self.assertEqual(summary["coverage"][0]["tape_rows"], 2)
        self.assertEqual(summary["coverage"][0]["t_plus_0_snapshots"], 2)

    def test_perturbed_stage_vector_fails_l1(self):
        self.write_two_snapshots()

        def nudge(rows):
            rows[0]["stage_vector"][1] += 1e-9

        self.rewrite(shadow.TAPE_FILENAME, nudge)
        code, lines = self.run_cli(str(self.folder))
        self.assertEqual(code, replay.REPLAY_FAILED_EXIT)
        self.assertEqual(lines[-1]["l1_failures"], 1)
        self.assertEqual(lines[0]["l1"], "mismatch")

    def test_changed_captured_input_fails_l2_only(self):
        self.write_two_snapshots()

        def change_mean(rows):
            rows[0]["sources"]["nbm_probabilistic_tmax"]["data"]["mean_native"] = 61.5

        self.rewrite("replay_inputs.jsonl", change_mean)
        code, lines = self.run_cli(str(self.folder))
        self.assertEqual(code, replay.REPLAY_FAILED_EXIT)
        self.assertEqual(lines[-1]["l1_failures"], 0)
        self.assertEqual(lines[-1]["l2_failures"], 1)
        self.assertIn("read", lines[0]["l2_differs"])

    def test_missing_replay_record_fails_l2(self):
        self.write_two_snapshots()
        self.rewrite("replay_inputs.jsonl", lambda rows: rows.pop())
        code, lines = self.run_cli(str(self.folder))
        self.assertEqual(code, replay.REPLAY_FAILED_EXIT)
        self.assertEqual(lines[1]["l2"], "inputs_missing")

    def test_stage_hash_drift_fails_l1(self):
        self.write_two_snapshots()

        def drift(rows):
            rows[0]["stage_code_sha256"] = "0" * 64

        self.rewrite(shadow.TAPE_FILENAME, drift)
        _code, lines = self.run_cli(str(self.folder))
        self.assertEqual(lines[0]["l1"], "stage_hash_mismatch")


class TestRefusals(_Tmp):
    def test_folder_before_the_mg1_floor_is_refused(self):
        early = self.snapshots / "highest-temperature-in-nyc-on-october-10-2026"
        early.mkdir()
        code, lines = self.run_cli(str(early))
        self.assertEqual(code, 2)
        self.assertEqual(lines, [])

    def test_scan_skips_folders_before_the_floor(self):
        (self.snapshots / "highest-temperature-in-nyc-on-october-10-2026").mkdir()
        selected = replay.select_folders([], self.snapshots)
        self.assertEqual([folder.name for folder, _spec, _target in selected], [SLUG])

    def test_from_date_before_the_floor_is_refused(self):
        code, _ = self.run_cli("--from-date", "2026-10-01")
        self.assertEqual(code, 2)

    def test_out_inside_data_or_existing_is_refused(self):
        with self.assertRaises(replay.ReplayRefused):
            replay.check_out_path(data_path("nbm_guidance_read_replay_probe.jsonl"))
        existing = self.tmp / "exists.jsonl"
        existing.write_text("", encoding="utf-8")
        with self.assertRaises(replay.ReplayRefused):
            replay.check_out_path(existing)

    def test_d0_check_day_before_the_floor_is_refused(self):
        code, _ = self.run_cli("--d0-check", "--day", "2026-10-14", name="d0.json")
        self.assertEqual(code, 2)


class FakeParser:
    def __init__(self, payloads):
        self.payloads = payloads

    def parse(self, digest, _station, _target):
        return self.payloads[digest]


def _payload(issue, mean=61.4, sd=2.2, available=True):
    return {"available": available, "period_kind": "maximum", "issued_at": issue,
            "mean_native": mean, "stddev_native": sd}


class TestL3(unittest.TestCase):
    SPEC = SimpleNamespace(icao="KLGA")
    ROW = {
        "captured_at_utc": "2026-10-20T14:00:00+00:00",
        "target_date": TARGET.isoformat(),
        "read": {"eligible": True, "issued_at": "2026-10-20T07:00:00+00:00", "v2_mean": 61.4, "v2_stddev": 2.2},
    }

    @staticmethod
    def _bulletins(**available):
        return {
            digest: {"payload_hash": digest, "available_at": datetime.fromisoformat(value)}
            for digest, value in available.items()
        }

    def test_same_issue_values_reproduce_and_newest_matches(self):
        bulletins = self._bulletins(a="2026-10-20T08:10:00+00:00", b="2026-10-20T15:10:00+00:00")
        parser = FakeParser({"a": _payload("2026-10-20T07:00:00+00:00"), "b": _payload("2026-10-20T13:00:00+00:00")})
        result = replay.replay_l3(self.ROW, self.SPEC, bulletins, parser)
        self.assertEqual(result["l3"], "reproduced")
        self.assertFalse(result["l3_newest_mismatch"])  # b was not yet available at 14:00

    def test_a_newer_available_bulletin_is_counted_not_failed(self):
        bulletins = self._bulletins(a="2026-10-20T08:10:00+00:00", b="2026-10-20T13:50:00+00:00")
        parser = FakeParser({"a": _payload("2026-10-20T07:00:00+00:00"), "b": _payload("2026-10-20T13:00:00+00:00")})
        result = replay.replay_l3(self.ROW, self.SPEC, bulletins, parser)
        self.assertTrue(result["l3_ok"])
        self.assertTrue(result["l3_newest_mismatch"])

    def test_value_mismatch_and_missing_bulletin_fail(self):
        bulletins = self._bulletins(a="2026-10-20T08:10:00+00:00")
        result = replay.replay_l3(self.ROW, self.SPEC, bulletins, FakeParser({"a": _payload(
            "2026-10-20T07:00:00+00:00", mean=61.5)}))
        self.assertEqual(result["l3"], "value_mismatch")
        result = replay.replay_l3(self.ROW, self.SPEC, {}, FakeParser({}))
        self.assertEqual(result["l3"], "bulletin_not_retained")
        self.assertFalse(result["l3_ok"])

    def test_bulletin_parser_reads_verified_cas_bytes_through_parser_v2(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            data = FIXTURE.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            cas = SharedForecastPayloadCAS(tmp)
            self.assertEqual(cas.put(data, expected_digest=digest)["payload_hash"], digest)
            parsed = replay.BulletinParser(cas).parse(digest, "KLGA", "2026-09-17")
            expected = parse_nbp_station_tmax(data.decode("utf-8"), "KLGA", "2026-09-17", parser_version=2)
            self.assertEqual(parsed, expected)
            missing = replay.BulletinParser(cas).parse("f" * 64, "KLGA", "2026-09-17")
            self.assertFalse(missing["available"])
            self.assertTrue(missing["reason"].startswith("bytes_unreadable"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestD0Check(_Tmp):
    def _write(self, name, rows):
        (self.folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def _day(self, *, parser="nbm-probabilistic-tmax-parser-v2", tape_ids=("s1", "s2")):
        self._write("forecast_payloads.jsonl", [
            {"source": "nbm_probabilistic_tmax", "captured_at_utc": "2026-10-20T14:00:00+00:00",
             "parser_version": "nbm-probabilistic-tmax-parser-v2"},
            {"source": "nbm_probabilistic_tmax", "captured_at_utc": "2026-10-20T15:00:00+00:00",
             "parser_version": parser},
            {"source": "open_meteo", "captured_at_utc": "2026-10-20T15:00:00+00:00", "parser_version": "x"},
        ])
        self._write("snapshots.jsonl", [
            {"snapshot_id": "s1", "captured_at_utc": "2026-10-20T14:00:00+00:00"},
            {"snapshot_id": "s2", "captured_at_utc": "2026-10-20T15:00:00+00:00"},
            {"snapshot_id": "s0", "captured_at_utc": "2026-10-20T03:00:00+00:00"},  # 10-19 local: not T+0
        ])
        self._write(shadow.TAPE_FILENAME, [
            {"snapshot_id": sid, "status": stage.STATUS_MG1, "stage_config_sha256": stage.stage_config_sha256(),
             "stage_code_sha256": stage.stage_code_sha256()}
            for sid in tape_ids
        ])

    def test_full_v2_day_with_full_tape_coverage_gives_a_candidate(self):
        self._day()
        result = replay.d0_check(self.snapshots, TARGET)
        self.assertTrue(result["condition_b_parser_2"]["met"])
        self.assertEqual(result["condition_b_parser_2"]["nbm_manifest_rows"], 2)
        self.assertTrue(result["condition_c_stage_capture"]["met"])
        self.assertEqual(result["condition_c_stage_capture"]["t_plus_0_snapshots"], 2)
        self.assertEqual(result["candidate_d0"], (TARGET + timedelta(days=1)).isoformat())
        code, _ = self.run_cli("--d0-check", "--day", TARGET.isoformat(), name="d0.json")
        self.assertEqual(code, 0)

    def test_one_v1_manifest_row_fails_condition_b(self):
        self._day(parser="nbm-probabilistic-tmax-parser-v1")
        result = replay.d0_check(self.snapshots, TARGET)
        self.assertFalse(result["condition_b_parser_2"]["met"])
        self.assertIsNone(result["candidate_d0"])
        code, _ = self.run_cli("--d0-check", "--day", TARGET.isoformat(), name="d0.json")
        self.assertEqual(code, replay.D0_NOT_MET_EXIT)

    def test_one_uncovered_t0_snapshot_fails_condition_c(self):
        self._day(tape_ids=("s1",))
        result = replay.d0_check(self.snapshots, TARGET)
        self.assertFalse(result["condition_c_stage_capture"]["met"])
        self.assertEqual(result["condition_c_stage_capture"]["uncovered_count"], 1)


_OUTCOME_TOKENS = ("settle", "panel", "score", "outcome", "88a", "wu_history", "realized", "label")


class TestOutcomeBlind(unittest.TestCase):
    def test_replay_module_imports_no_outcome_loader(self):
        path = repo_path("src", "weather", "backtesting", "nbm_guidance_read_replay.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("weather"):
                names.add(node.module)
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        self.assertTrue(any(name.startswith("weather.") for name in names))
        offenders = sorted(name for name in names if any(token in name.lower() for token in _OUTCOME_TOKENS))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
