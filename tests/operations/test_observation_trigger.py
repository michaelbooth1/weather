import csv
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys_path = os.path.abspath("src")
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)

from observation_trigger import (  # noqa: E402
    build_triggered_replay_report,
    detect_observation_triggers,
    ensure_decision,
    observation_state_from_sources,
    run_loop,
    run_once,
)
from snapshot_tracker import SnapshotStore, backfill_source_status  # noqa: E402
from toronto_model import TorontoHighTempModel  # noqa: E402


def obs_state(high=20.0, current=20.1, metar=None, swob=None, status=None, captured="2026-06-13T16:00:00+00:00"):
    return {
        "market_id": "toronto",
        "event_slug": "highest-temperature-in-toronto-on-june-13-2026",
        "target_date": "2026-06-13",
        "unit": "C",
        "captured_at_utc": captured,
        "values": {
            "wu_history_high": high,
            "wu_history_latest_time": captured,
            "wu_current_temp": current,
            "wu_current_max_since_7am": current,
            "wu_current_time": captured,
            "metar_temp": metar,
            "metar_report_time": captured,
            "eccc_swob_max": swob,
            "eccc_swob_latest_temp": swob,
            "eccc_swob_latest_time": captured,
        },
        "source_status": status or {
            "wu_history": {"ok": True, "status": "fresh", "stale": False, "fetched_at": captured},
            "wu_current": {"ok": True, "status": "fresh", "stale": False, "fetched_at": captured},
        },
    }


class FakeModelClient:
    target_date = date(2026, 6, 13)
    market_id = "toronto"

    def market_bins(self, _event):
        return [{"label": "20 C", "kind": "eq", "value": 20, "market_yes": 0.4, "market_no": 0.6}]

    def bin_probability(self, distribution, bin_data):
        return distribution.get(bin_data["value"], 0.0)

    def source_data(self, sources, name):
        item = (sources or {}).get(name) or {}
        return item.get("data") or {}

    def forecast_ensemble_metrics(self, *_args, **_kwargs):
        return {}

    def max_row_temp(self, rows):
        values = [row.get("temp_c") for row in rows or [] if row.get("temp_c") is not None]
        return max(values) if values else None


class ObservationTriggerTests(unittest.TestCase):
    def test_ensure_restarts_only_source_identity_erroring_watcher(self):
        self.assertEqual(
            ensure_decision(
                "ERRORING",
                pid_alive=True,
                last_error="RuntimeError: snapshot process code identity differs from current source tree",
            ),
            "restart",
        )
        self.assertEqual(
            ensure_decision("ERRORING", pid_alive=True, last_error="ConnectionError: upstream timeout"),
            "noop",
        )

    def test_observation_state_reads_native_aliases_first(self):
        model = TorontoHighTempModel(target_date="2026-06-13", market_id="nyc")
        captured = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        sources = {
            "wu_history": {
                "ok": True,
                "data": {
                    "max_native": 91.0,
                    "max_c": 31.0,
                    "latest": {"temp_native": 90.0, "temp_c": 30.0, "time": "12:00"},
                    "rows": [{"temp_native": 90.0, "temp_c": 30.0}],
                },
            },
            "wu_current": {
                "ok": True,
                "data": {
                    "temp_native": 89.0,
                    "temp_c": 29.0,
                    "max_since_7am_native": 92.0,
                    "max_since_7am_c": 32.0,
                },
            },
            "metar": {"ok": True, "data": {"temp_native": 88.0, "temp_c": 28.0}},
            "eccc_swob": {
                "ok": True,
                "data": {
                    "same_day_max_native": 90.0,
                    "same_day_max_c": 30.0,
                    "latest": {"air_temp_native": 87.0, "air_temp_c": 27.0},
                },
            },
        }

        state = observation_state_from_sources(model, sources, captured_at=captured)

        values = state["values"]
        self.assertEqual(state["unit"], "F")
        self.assertEqual(values["wu_history_high"], 91.0)
        self.assertEqual(values["wu_history_latest_value"], 90.0)
        self.assertEqual(values["wu_current_temp"], 89.0)
        self.assertEqual(values["wu_current_max_since_7am"], 92.0)
        self.assertEqual(values["metar_temp"], 88.0)
        self.assertEqual(values["eccc_swob_max"], 90.0)
        self.assertEqual(values["eccc_swob_latest_temp"], 87.0)

    def test_detects_material_observation_changes(self):
        previous = obs_state(high=20.0, current=20.4, metar=20.0, swob=20.0)
        current = obs_state(high=21.0, current=21.0, metar=22.0, swob=22.0, captured="2026-06-13T16:01:00+00:00")

        reasons = {trigger["reason"] for trigger in detect_observation_triggers(previous, current)}

        self.assertIn("wu_history_high_increased", reasons)
        self.assertIn("wu_current_temp_bucket_crossed", reasons)
        self.assertIn("metar_temp_above_wu_floor", reasons)
        self.assertIn("eccc_swob_max_above_wu_floor", reasons)

    def test_detects_stale_source_recovery(self):
        previous = obs_state(status={"wu_current": {"ok": True, "status": "stale_cache", "stale": True}})
        current = obs_state(status={"wu_current": {"ok": True, "status": "fresh", "stale": False}})

        reasons = {trigger["reason"] for trigger in detect_observation_triggers(previous, current)}

        self.assertIn("wu_current_became_fresh", reasons)

    def test_run_once_forces_triggered_snapshot_and_writes_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            events_path = root / "events.jsonl"
            diagnostics_path = root / "diagnostics.jsonl"
            previous = obs_state(high=20.0, current=20.2)
            current = obs_state(high=21.0, current=21.2, captured="2026-06-13T16:01:00+00:00")
            status_path.write_text(json.dumps({"markets": {"toronto": {"last_observation": previous}}}), encoding="utf-8")
            calls = {}

            def fake_fetch(market_id, now=None):
                self.assertEqual(market_id, "toronto")
                return current

            def fake_capture(**kwargs):
                calls.update(kwargs)
                return {
                    "written": True,
                    "snapshot_id": "s-trigger",
                    "path": "snapshots_long.csv",
                    "top_temp_c": 21,
                    "top_probability": 0.7,
                    "distribution": {21: 0.7},
                }

            args = SimpleNamespace(
                market="toronto",
                status_out=str(status_path),
                events_out=str(events_path),
                diagnostics_out=str(diagnostics_path),
                support_margin=0.5,
                dry_run=False,
                trigger_on_first=False,
                stale_after_seconds=180.0,
                interval_seconds=60.0,
            )

            result = run_once(args, capture_func=fake_capture, fetch_state_func=fake_fetch, now=datetime(2026, 6, 13, 16, 1, tzinfo=timezone.utc))
            event = json.loads(events_path.read_text(encoding="utf-8").strip())

        self.assertEqual(result["trigger_count"], 3)
        self.assertTrue(calls["force"])
        self.assertEqual(calls["cadence"], "triggered")
        self.assertIn("wu_history_high_increased", calls["trigger_context"]["reasons"])
        self.assertEqual(event["snapshot"]["snapshot_id"], "s-trigger")

    def test_snapshot_store_persists_trigger_metadata_to_replay_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="highest-temperature-in-toronto-on-june-13-2026")
            event = {"slug": "highest-temperature-in-toronto-on-june-13-2026", "markets": []}
            captured_at = datetime(2026, 6, 13, 16, 2, tzinfo=timezone.utc)
            model = {
                "distribution": {20: 0.8},
                "top_temp": 20,
                "sources": {
                    "wu_history": {
                        "ok": True,
                        "status": "fresh",
                        "fetched_at": captured_at.isoformat(),
                        "latency_ms": 12.3,
                        "data": {"max_c": 20.0, "rows": [{"temp_c": 20.0}], "url": "https://example.test/history"},
                    },
                    "wu_current": {
                        "ok": True,
                        "stale": True,
                        "status": "stale_cache",
                        "fetched_at": "2026-06-13T15:32:00+00:00",
                        "ttl_minutes": 30,
                        "data": {"temp_c": 20.5},
                    },
                },
            }
            context = {
                "reason": "wu_current_temp_bucket_crossed",
                "reasons": ["wu_current_temp_bucket_crossed"],
                "primary_trigger": {"source": "wu_current", "previous_value": 20.4, "current_value": 21.0},
            }

            result = store.write(event, model, FakeModelClient(), captured_at, cadence="triggered", trigger_context=context)
            replay = json.loads((Path(tmp) / "replay_inputs.jsonl").read_text(encoding="utf-8").strip())
            source_status = list(csv.DictReader((Path(tmp) / "source_status_long.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["snapshot_cadence"], "triggered")
        self.assertEqual(result["source_status_rows"], 2)
        self.assertEqual(replay["snapshot_cadence"], "triggered")
        self.assertEqual(replay["trigger_context"]["reason"], "wu_current_temp_bucket_crossed")
        by_source = {row["source"]: row for row in source_status}
        self.assertEqual(by_source["wu_history"]["status"], "fresh")
        self.assertEqual(by_source["wu_history"]["row_count"], "1")
        self.assertEqual(by_source["wu_history"]["latency_ms"], "12.3")
        self.assertTrue(by_source["wu_history"]["payload_hash"])
        self.assertEqual(by_source["wu_history"]["source_url"], "https://example.test/history")
        self.assertEqual(by_source["wu_current"]["status"], "stale_cache")
        self.assertEqual(by_source["wu_current"]["age_minutes"], "30.0")

    def test_backfill_source_status_from_replay_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots"
            folder = root / "highest-temperature-in-toronto-on-june-13-2026"
            folder.mkdir(parents=True)
            with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "snapshot_id": "snap1",
                    "captured_at_local": "2026-06-13T16:00:00+00:00",
                    "model_version": "model-v",
                    "sources": {
                        "open_meteo": {
                            "ok": True,
                            "status": "fresh",
                            "fetched_at": "2026-06-13T15:59:00+00:00",
                            "data": {"rows": [{"temp_c": 21.0}], "url": "https://example.test/open"},
                        }
                    },
                }) + "\n")

            result = backfill_source_status(root, overwrite=True)
            rows = list(csv.DictReader((folder / "source_status_long.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["written_folders"], 1)
        self.assertEqual(result["rows"], 1)
        self.assertEqual(rows[0]["snapshot_id"], "snap1")
        self.assertEqual(rows[0]["source"], "open_meteo")
        self.assertEqual(rows[0]["row_count"], "1")
        self.assertEqual(rows[0]["age_minutes"], "1.0")
        self.assertEqual(rows[0]["ttl_minutes"], "90")

    def test_snapshot_store_persists_raw_forecast_payload_and_strips_replay_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-toronto-on-june-13-2026")
            captured_at = datetime(2026, 6, 13, 16, 5, tzinfo=timezone.utc)
            event = {"slug": "highest-temperature-in-toronto-on-june-13-2026", "markets": []}
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "sources": {
                    "weather_forecast": {
                        "ok": True,
                        "fetched_at": captured_at.isoformat(),
                        "data": {
                            "url": "https://example.test/weather",
                            "provider_issue_time": "2026-06-13T15:45:00+00:00",
                            "provider_update_time": "2026-06-13T15:50:00+00:00",
                            "rows": [],
                            "raw_payload": {"provider": "weather", "values": [1, 2, 3]},
                        },
                    }
                },
            }

            result = store.write(event, model, FakeModelClient(), captured_at)
            manifest_rows = list(csv.DictReader((root / "forecast_payloads_long.csv").open(encoding="utf-8", newline="")))
            replay = json.loads((root / "replay_inputs.jsonl").read_text(encoding="utf-8").strip())
            raw_path = Path(manifest_rows[0]["raw_payload_path"])
            self.assertTrue(raw_path.exists())
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))

        self.assertEqual(result["forecast_payload_rows"], 1)
        self.assertEqual(manifest_rows[0]["source"], "weather_forecast")
        self.assertEqual(manifest_rows[0]["provider_issue_time"], "2026-06-13T15:45:00+00:00")
        self.assertEqual(raw_payload["provider"], "weather")
        self.assertNotIn("raw_payload", replay["sources"]["weather_forecast"]["data"])
        self.assertEqual(
            replay["sources"]["weather_forecast"]["data"]["provider_update_time"],
            "2026-06-13T15:50:00+00:00",
        )

    def test_run_loop_persists_iteration_before_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            args = SimpleNamespace(
                market="toronto",
                status_out=str(status_path),
                events_out=str(root / "events.jsonl"),
                diagnostics_out=str(root / "diagnostics.jsonl"),
                support_margin=0.5,
                dry_run=True,
                trigger_on_first=False,
                stale_after_seconds=180.0,
                interval_seconds=60.0,
                max_iterations=1,
            )

            def fake_fetch(_market_id, now=None):
                return obs_state()

            returned = run_loop(args, fetch_state_func=fake_fetch)
            status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(returned["iterations"], 1)
        self.assertEqual(status["iterations"], 1)
        self.assertEqual(status["last_poll_results"]["toronto"]["trigger_count"], 0)

    def test_triggered_replay_scores_wu_lag_case_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            backtest = root / "backtest"
            folder = snapshots / "highest-temperature-in-toronto-on-june-13-2026"
            folder.mkdir(parents=True)
            backtest.mkdir()

            with (backtest / "market_day_labels.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["event_slug", "settlement_bucket"])
                writer.writeheader()
                writer.writerow({"event_slug": folder.name, "settlement_bucket": "20"})
            (backtest / "disagreement_casebook.json").write_text(json.dumps({
                "cases": [{
                    "case_id": "case_1",
                    "taxonomy": "wu_lag_catchup_miss",
                    "model_result": "model_loss",
                    "event_slug": folder.name,
                    "range_label": "20 C",
                    "start_time_utc": "2026-06-13T15:59:00+00:00",
                    "end_time_utc": "2026-06-13T16:03:00+00:00",
                }]
            }), encoding="utf-8")
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                fieldnames = [
                    "snapshot_id", "captured_at_utc", "event_slug", "snapshot_cadence",
                    "trigger_reason", "range_label", "bin_kind", "bin_value_c",
                    "model_probability", "market_yes",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({"snapshot_id": "pre", "captured_at_utc": "2026-06-13T16:00:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.2", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "trig", "captured_at_utc": "2026-06-13T16:01:00+00:00", "event_slug": folder.name, "snapshot_cadence": "triggered", "trigger_reason": "wu_history_high_increased", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.8", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "next", "captured_at_utc": "2026-06-13T16:10:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.6", "market_yes": "0.5"})

            payload = build_triggered_replay_report(snapshots_root=snapshots, backtest_root=backtest)

        self.assertEqual(payload["summary"]["scored_rows"], 1)
        self.assertLess(payload["summary"]["triggered_model_brier"], payload["summary"]["pre_model_brier"])
        self.assertEqual(payload["rows"][0]["case_ids"], ["case_1"])


if __name__ == "__main__":
    unittest.main()
