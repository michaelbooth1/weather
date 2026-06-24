import csv
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import weather.operations.observation_trigger as observation_trigger
from weather.operations.observation_trigger import (  # noqa: E402
    build_triggered_replay_report,
    detect_observation_triggers,
    ensure_decision,
    latest_trade_permission,
    observation_state_from_sources,
    run_loop,
    run_once,
    watcher_health,
)
from weather.operations.supervisor import writer_lock_path
from weather.market.live_observation_normalization import (
    current_high_probability_summary,
    update_monotonic_high_ledger,
)
from weather.collection.snapshot_tracker import (  # noqa: E402
    SnapshotStore,
    backfill_forecast_payloads,
    backfill_source_status,
)
from weather.model.toronto_model import TorontoHighTempModel  # noqa: E402


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


class FakeProcess:
    pid = 2468


class ObservationTriggerTests(unittest.TestCase):
    def test_ensure_restarts_source_identity_watcher_before_erroring(self):
        self.assertEqual(
            ensure_decision(
                "DEGRADED",
                pid_alive=True,
                last_error="RuntimeError: snapshot process code identity differs from current source tree",
            ),
            "restart",
        )
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

    def test_ensure_watcher_loop_backoff_blocks_repeated_source_identity_restart(self):
        now = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            diagnostics_path = root / "diagnostics.jsonl"
            console_path = root / "console.log"
            status_path.write_text(
                json.dumps({
                    "pid": 2468,
                    "last_heartbeat": now.isoformat(),
                    "interval_seconds": 60,
                    "consecutive_errors": 1,
                    "last_error": "RuntimeError: snapshot process code identity differs from current source tree",
                }),
                encoding="utf-8",
            )
            diagnostics_path.write_text(
                json.dumps({
                    "time": (now - timedelta(seconds=30)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "DEGRADED",
                }) + "\n",
                encoding="utf-8",
            )
            console_path.write_text("", encoding="utf-8")

            with patch.object(observation_trigger, "STATUS_PATH", status_path), \
                    patch.object(observation_trigger, "DIAGNOSTICS_PATH", diagnostics_path), \
                    patch.object(observation_trigger, "CONSOLE_LOG_PATH", console_path), \
                    patch.object(observation_trigger, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(observation_trigger, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(observation_trigger, "acquire_supervisor_lock", return_value=object()), \
                    patch.object(observation_trigger, "release_supervisor_lock"), \
                    patch.object(observation_trigger, "pid_is_python", return_value=True), \
                    patch.object(observation_trigger, "stop_watcher_loop") as stop_loop, \
                    patch.object(observation_trigger, "start_watcher_detached") as start_loop:
                result = observation_trigger.ensure_watcher_loop(now=now)

        self.assertEqual(result["action"], "backoff")
        self.assertEqual(result["intended_action"], "restart")
        self.assertEqual(result["restart_cause"], "source_identity_error")
        stop_loop.assert_not_called()
        start_loop.assert_not_called()

    def test_fresh_provisional_heartbeat_with_dead_pid_is_dead(self):
        now = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        health = watcher_health(
            {
                "pid": 2468,
                "last_heartbeat": now.isoformat(),
                "interval_seconds": 60,
                "consecutive_errors": 0,
                "iterations": 0,
            },
            now=now,
            pid_alive=False,
        )

        self.assertEqual(health["state"], "DEAD")
        self.assertFalse(health["pid_alive"])
        self.assertEqual(ensure_decision(health["state"], pid_alive=False), "start")

    def test_start_watcher_detached_writes_supervisor_status(self):
        now = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {}

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                calls["command"] = command
                calls["cwd"] = cwd
                calls["stdout_closed_during_call"] = stdout.closed
                calls["stderr_is_stdout"] = stderr is stdout
                return FakeProcess()

            with patch.object(observation_trigger, "STATUS_PATH", root / "status.json"), \
                    patch.object(observation_trigger, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(observation_trigger, "CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(observation_trigger, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(observation_trigger.subprocess, "Popen", fake_popen):
                result = observation_trigger.start_watcher_detached(
                    market="toronto",
                    interval_seconds=30,
                    stale_after_seconds=90,
                    now=now,
                )
                payload = json.loads((root / "status.json").read_text(encoding="utf-8"))

        self.assertTrue(result["started"])
        self.assertEqual(payload["pid"], 2468)
        self.assertEqual(payload["market"], "toronto")
        self.assertEqual(payload["interval_seconds"], 30)
        self.assertEqual(payload["stale_after_seconds"], 90)
        self.assertEqual(payload["started_by"], "supervisor")
        self.assertIn("weather.operations.observation_trigger", calls["command"])
        self.assertIn("--stale-after-seconds", calls["command"])
        self.assertFalse(calls["stdout_closed_during_call"])
        self.assertTrue(calls["stderr_is_stdout"])

    def test_start_watcher_detached_blocks_live_writer_lock(self):
        now = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            writer_lock_path(status_path).write_text(json.dumps({"pid": 2468}), encoding="utf-8")

            with patch.object(observation_trigger, "STATUS_PATH", status_path), \
                    patch.object(observation_trigger, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(observation_trigger, "CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(observation_trigger, "pid_is_python", return_value=True), \
                    patch.object(observation_trigger.subprocess, "Popen") as popen:
                result = observation_trigger.start_watcher_detached(now=now)

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer lock owner is still live")
        popen.assert_not_called()

    def test_stop_watcher_loop_removes_stopped_writer_lock(self):
        now = datetime(2026, 6, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "status.json"
            status_path.write_text(json.dumps({"pid": 2468}), encoding="utf-8")
            lock_path = writer_lock_path(status_path)
            lock_path.write_text(json.dumps({"pid": 2468}), encoding="utf-8")

            with patch.object(observation_trigger, "STATUS_PATH", status_path), \
                    patch.object(observation_trigger, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(observation_trigger, "pid_is_python", return_value=True), \
                    patch.object(observation_trigger, "terminate_python_pid", return_value={"pid": 2468, "stopped": True}):
                result = observation_trigger.stop_watcher_loop(now=now, status_path=status_path)

            lock_exists = lock_path.exists()

        self.assertTrue(result["stopped"])
        self.assertEqual(result["writer_lock"]["reason"], "stopped writer pid")
        self.assertFalse(lock_exists)

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

    def test_observation_fetch_eccc_swob_supervisor_path_uses_threadpool_import(self):
        model = TorontoHighTempModel(target_date="2026-06-16", market_id="toronto")
        captured = "2026-06-16T15:00:00+00:00"
        model.fetch_wu_history = lambda: {
            "rows": [{"temp_native": 23.0, "temp_c": 23.0}],
            "max_native": 23.0,
            "latest": {"temp_native": 23.0, "time": "11:00"},
        }
        model.fetch_wu_current = lambda: {
            "temp_native": 23.5,
            "temp_c": 23.5,
            "max_since_7am_native": 23.5,
        }
        model.fetch_metar = lambda: {"temp_native": 23.0, "temp_c": 23.0}

        class Response:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        index = '<html><a href="20260616T150000Z-CYYZ-MAN-swob.xml">swob</a></html>'
        xml = """
        <root>
          <element name="date_tm" value="2026-06-16T15:00:00Z" />
          <element name="air_temp" value="24.1" />
          <element name="dwpt_temp" value="12.0" />
          <element name="rel_hum" value="50" />
          <element name="max_air_temp_pst1hr" value="24.1" />
          <element name="max_air_temp_pst6hrs" value="24.1" />
          <element name="max_air_temp_pst24hrs" value="24.1" />
        </root>
        """

        def fake_get(url, timeout=None):
            if url.endswith("/"):
                return Response(index)
            return Response(xml)

        with patch("weather.model.model_sources.requests.get", fake_get):
            sources = observation_trigger.fetch_observation_sources(model)
            state = observation_state_from_sources(
                model,
                sources,
                captured_at=datetime.fromisoformat(captured),
            )

        self.assertTrue(sources["eccc_swob"]["ok"])
        self.assertEqual(sources["eccc_swob"]["data"]["same_day_max_native"], 24.1)
        self.assertEqual(state["values"]["eccc_swob_max"], 24.1)

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

    def test_downward_wu_max_since_7am_is_source_revision_not_lower_high(self):
        previous = obs_state(high=87.0, current=87.0)
        current = obs_state(high=87.0, current=86.0, captured="2026-06-13T16:01:00+00:00")

        reasons = {trigger["reason"] for trigger in detect_observation_triggers(previous, current)}

        self.assertIn("wu_current_max_since_7am_source_revision_down", reasons)
        self.assertNotIn("wu_current_max_since_7am_bucket_crossed", reasons)

    def test_settlement_normalization_handles_raw_decimal_boundary(self):
        observation = obs_state(high=88.0, current=87.08, metar=87.08)
        ledger = update_monotonic_high_ledger(current_observation=observation)
        snapshot_rows = [
            {"range_label": "86-87 F", "bin_kind": "eq", "bin_value": "86", "bin_value_hi": "87", "model_probability": "0.1"},
            {"range_label": "88-89 F", "bin_kind": "eq", "bin_value": "88", "bin_value_hi": "89", "model_probability": "0.8"},
        ]

        summary = current_high_probability_summary(snapshot_rows, ledger)

        self.assertEqual(ledger["raw_current_high"], 87.08)
        self.assertEqual(ledger["settlement_current_high"], 88)
        self.assertEqual(ledger["high_source"], "wu_history")
        self.assertEqual(summary["probability_on_raw_current_high"], 0.0)
        self.assertEqual(summary["probability_on_settlement_current_high"], 0.8)

    def test_current_max_guard_nulls_pre_reset_unvalidated_high_and_resets_prior_day(self):
        previous = {
            "market_id": "toronto",
            "target_date": "2026-06-13",
            "event_slug": "highest-temperature-in-toronto-on-june-13-2026",
            "settlement_current_high": 99,
            "raw_current_high": 99,
            "monotonic_raw_high": 99,
            "high_source": "wu_current",
        }
        current = obs_state(
            high=70.0,
            current=90.0,
            captured="2026-06-14T06:15:00+00:00",
        )
        current["target_date"] = "2026-06-14"
        current["event_slug"] = "highest-temperature-in-toronto-on-june-14-2026"
        current["values"]["wu_current_temp"] = 68.0
        current["values"]["wu_current_max_since_7am"] = 90.0

        ledger = update_monotonic_high_ledger(previous_ledger=previous, current_observation=current)

        self.assertEqual(ledger["current_max_state"], "pre_reset_current_max_null")
        self.assertEqual(ledger["current_max_disposition"], "null_before_reset")
        self.assertFalse(ledger["current_high_trusted"])
        self.assertEqual(ledger["raw_current_high"], 68.0)
        self.assertEqual(ledger["settlement_current_high"], 70)
        self.assertEqual(ledger["high_source"], "wu_history")
        self.assertNotEqual(ledger["settlement_current_high"], 99)

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

    def test_backfill_source_status_from_reconstructed_replay_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots"
            folder = root / "highest-temperature-in-toronto-on-june-13-2026"
            folder.mkdir(parents=True)
            with (folder / "replay_inputs_reconstructed.jsonl").open("w", encoding="utf-8") as handle:
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

    def test_backfill_forecast_payloads_from_replay_inputs(self):
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
                            "fetched_at": "2026-06-13T15:52:00+00:00",
                            "data": {
                                "rows": [{"temp_c": 21.0}],
                                "url": "https://example.test/open",
                            },
                        }
                    },
                }) + "\n")

            result = backfill_forecast_payloads(root, overwrite=True)
            rows = list(csv.DictReader((folder / "forecast_payloads_long.csv").open(encoding="utf-8", newline="")))
            payload_path = Path(rows[0]["raw_payload_path"])
            payload = json.loads(payload_path.read_text(encoding="utf-8"))

        self.assertEqual(result["written_folders"], 1)
        self.assertEqual(result["rows"], 1)
        self.assertEqual(rows[0]["snapshot_id"], "snap1")
        self.assertEqual(rows[0]["source"], "open_meteo")
        self.assertEqual(rows[0]["status"], "fresh")
        self.assertEqual(rows[0]["age_minutes"], "8.0")
        self.assertEqual(rows[0]["ttl_minutes"], "90")
        self.assertIn("reconstructed", payload_path.name)
        self.assertEqual(payload["rows"][0]["temp_c"], 21.0)

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

    def test_snapshot_store_persists_source_degradation_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-toronto-on-june-13-2026")
            captured_at = datetime(2026, 6, 13, 16, 5, tzinfo=timezone.utc)
            event = {"slug": "highest-temperature-in-toronto-on-june-13-2026", "markets": []}
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "sources": {
                    "open_meteo": {
                        "ok": True,
                        "stale": True,
                        "status": "rate_limited_cache",
                        "source_family": "open_meteo",
                        "http_status": 429,
                        "retry_after_seconds": 60.0,
                        "degradation_state": "rate_limited_fallback",
                        "cache_status": "fallback",
                        "fetched_at": "2026-06-13T15:50:00+00:00",
                        "ttl_minutes": 90,
                        "cache_age_minutes": 15.0,
                        "data": {
                            "url": "https://api.open-meteo.com/v1/forecast",
                            "rows": [{"temp_c": 20.0}],
                            "raw_payload": {"provider": "open_meteo", "values": [20]},
                        },
                    }
                },
            }

            store.write(event, model, FakeModelClient(), captured_at)
            source_status = list(csv.DictReader((root / "source_status_long.csv").open(encoding="utf-8", newline="")))
            payload_rows = list(csv.DictReader((root / "forecast_payloads_long.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(source_status[0]["status"], "rate_limited_cache")
        self.assertEqual(source_status[0]["source_family"], "open_meteo")
        self.assertEqual(source_status[0]["http_status"], "429")
        self.assertEqual(source_status[0]["retry_after_seconds"], "60.0")
        self.assertEqual(source_status[0]["degradation_state"], "rate_limited_fallback")
        self.assertEqual(source_status[0]["cache_status"], "fallback")
        self.assertEqual(source_status[0]["age_minutes"], "15.0")
        self.assertEqual(payload_rows[0]["status"], "rate_limited_cache")
        self.assertEqual(payload_rows[0]["source_family"], "open_meteo")
        self.assertEqual(payload_rows[0]["degradation_state"], "rate_limited_fallback")

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
            daily_root = root / "sources" / "asos_1min" / "toronto" / "daily"
            daily_root.mkdir(parents=True)
            with (daily_root / "daily_summary.csv").open("w", encoding="utf-8", newline="") as handle:
                fieldnames = [
                    "schema_version", "source", "market", "station", "iem_station",
                    "local_date", "row_count", "temp_row_count", "expected_minutes",
                    "coverage_ratio", "max_temp_native", "first_reached_minute",
                    "high_duration_minutes", "spike_persistence_minutes",
                    "first_valid_utc", "last_valid_utc", "source_lag_minutes",
                    "payload_hashes",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({
                    "schema_version": "asos_1min_v0.1",
                    "source": "asos_1min",
                    "market": "toronto",
                    "station": "CYYZ",
                    "iem_station": "CYYZ",
                    "local_date": "2026-06-13",
                    "row_count": "4",
                    "temp_row_count": "4",
                    "expected_minutes": "1440",
                    "coverage_ratio": "0.9",
                    "max_temp_native": "21",
                    "first_reached_minute": "720",
                    "high_duration_minutes": "2",
                    "spike_persistence_minutes": "2",
                    "first_valid_utc": "2026-06-13T16:00:00+00:00",
                    "last_valid_utc": "2026-06-13T16:03:00+00:00",
                    "source_lag_minutes": "15",
                    "payload_hashes": "abc",
                })

            payload = build_triggered_replay_report(
                snapshots_root=snapshots,
                backtest_root=backtest,
                asos_1min_root=root / "sources" / "asos_1min",
            )

        self.assertEqual(payload["summary"]["scored_rows"], 1)
        self.assertLess(payload["summary"]["triggered_model_brier"], payload["summary"]["pre_model_brier"])
        self.assertEqual(payload["rows"][0]["case_ids"], ["case_1"])
        self.assertEqual(payload["summary"]["asos_1min_rows_with_evidence"], 1)
        self.assertTrue(payload["rows"][0]["asos_1min_available"])
        self.assertEqual(payload["rows"][0]["asos_1min_max_so_far"], 21.0)
        self.assertEqual(payload["rows"][0]["asos_1min_minus_settlement_bucket"], 1.0)
        self.assertEqual(payload["rows"][0]["asos_1min_minutes_from_first_high_to_wu_print"], 1.0)

    def test_triggered_replay_matches_normalized_fahrenheit_band_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            backtest = root / "backtest"
            folder = snapshots / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            backtest.mkdir()

            with (backtest / "market_day_labels.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["event_slug", "settlement_bucket"])
                writer.writeheader()
                writer.writerow({"event_slug": folder.name, "settlement_bucket": "89"})
            (backtest / "disagreement_casebook.json").write_text(json.dumps({
                "cases": [{
                    "case_id": "case_f",
                    "taxonomy": "wu_lag_catchup_miss",
                    "model_result": "model_loss",
                    "event_slug": folder.name,
                    "range_label": "88-89 F",
                    "band_key": "eq:88-89",
                    "start_time_utc": "2026-06-14T16:00:00+00:00",
                    "end_time_utc": "2026-06-14T16:03:00+00:00",
                }]
            }), encoding="utf-8")
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                fieldnames = [
                    "snapshot_id", "captured_at_utc", "event_slug", "snapshot_cadence",
                    "trigger_reason", "range_label", "bin_kind", "bin_value_c",
                    "bin_value_hi_c", "model_probability", "market_yes",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({"snapshot_id": "pre", "captured_at_utc": "2026-06-14T16:00:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "88-89\u00b0F", "bin_kind": "eq", "bin_value_c": "88", "bin_value_hi_c": "", "model_probability": "0.2", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "trig", "captured_at_utc": "2026-06-14T16:01:00+00:00", "event_slug": folder.name, "snapshot_cadence": "triggered", "trigger_reason": "wu_current_temp_bucket_crossed", "range_label": "88-89\u00b0F", "bin_kind": "eq", "bin_value_c": "88", "bin_value_hi_c": "", "model_probability": "0.8", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "next", "captured_at_utc": "2026-06-14T16:10:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "88-89\u00b0F", "bin_kind": "eq", "bin_value_c": "88", "bin_value_hi_c": "", "model_probability": "0.6", "market_yes": "0.5"})

            payload = build_triggered_replay_report(
                snapshots_root=snapshots,
                backtest_root=backtest,
                asos_1min_root=root / "sources" / "asos_1min",
            )

        self.assertEqual(payload["summary"]["scored_rows"], 1)
        self.assertEqual(payload["rows"][0]["case_ids"], ["case_f"])
        self.assertLess(payload["summary"]["triggered_model_brier"], payload["summary"]["pre_model_brier"])

    def test_triggered_replay_builds_permission_policy_by_reason_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            backtest = root / "backtest"
            folder = snapshots / "highest-temperature-in-toronto-on-june-15-2026"
            folder.mkdir(parents=True)
            backtest.mkdir()

            with (backtest / "market_day_labels.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["event_slug", "settlement_bucket"])
                writer.writeheader()
                writer.writerow({"event_slug": folder.name, "settlement_bucket": "20"})
            (backtest / "disagreement_casebook.json").write_text(json.dumps({
                "cases": [
                    {
                        "case_id": "case_down",
                        "taxonomy": "wu_lag_catchup_miss",
                        "model_result": "model_loss",
                        "event_slug": folder.name,
                        "range_label": "20 C",
                        "start_time_utc": "2026-06-15T16:00:00+00:00",
                        "end_time_utc": "2026-06-15T16:40:00+00:00",
                    },
                    {
                        "case_id": "case_up",
                        "taxonomy": "wu_lag_catchup_miss",
                        "model_result": "model_loss",
                        "event_slug": folder.name,
                        "range_label": "21 C",
                        "start_time_utc": "2026-06-15T16:00:00+00:00",
                        "end_time_utc": "2026-06-15T16:40:00+00:00",
                    },
                ]
            }), encoding="utf-8")
            with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                fieldnames = [
                    "snapshot_id", "captured_at_utc", "event_slug", "snapshot_cadence",
                    "trigger_reason", "trigger_previous_value", "trigger_current_value",
                    "range_label", "bin_kind", "bin_value_c", "model_probability", "market_yes",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({"snapshot_id": "pre_down", "captured_at_utc": "2026-06-15T15:59:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.2", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "next_down", "captured_at_utc": "2026-06-15T17:00:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.7", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "pre_up", "captured_at_utc": "2026-06-15T15:59:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "21 C", "bin_kind": "eq", "bin_value_c": "21", "model_probability": "0.1", "market_yes": "0.5"})
                writer.writerow({"snapshot_id": "next_up", "captured_at_utc": "2026-06-15T17:00:00+00:00", "event_slug": folder.name, "snapshot_cadence": "scheduled", "range_label": "21 C", "bin_kind": "eq", "bin_value_c": "21", "model_probability": "0.1", "market_yes": "0.5"})
                for index in range(30):
                    minute = f"{index + 1:02d}"
                    writer.writerow({"snapshot_id": f"trig_down_{index}", "captured_at_utc": f"2026-06-15T16:{minute}:00+00:00", "event_slug": folder.name, "snapshot_cadence": "triggered", "trigger_reason": "wu_current_temp_bucket_crossed", "trigger_previous_value": "21", "trigger_current_value": "20", "range_label": "20 C", "bin_kind": "eq", "bin_value_c": "20", "model_probability": "0.8", "market_yes": "0.5"})
                    writer.writerow({"snapshot_id": f"trig_up_{index}", "captured_at_utc": f"2026-06-15T16:{minute}:30+00:00", "event_slug": folder.name, "snapshot_cadence": "triggered", "trigger_reason": "wu_current_temp_bucket_crossed", "trigger_previous_value": "20", "trigger_current_value": "21", "range_label": "21 C", "bin_kind": "eq", "bin_value_c": "21", "model_probability": "0.9", "market_yes": "0.5"})

            payload = build_triggered_replay_report(
                snapshots_root=snapshots,
                backtest_root=backtest,
                asos_1min_root=root / "sources" / "asos_1min",
            )

        summary = payload["summary"]
        policy = summary["trigger_permission_policy"]
        self.assertEqual(summary["trigger_acceptance_status"], "PASS_WITH_PERMISSION_POLICY")
        self.assertGreater(summary["delta_triggered_vs_pre"], 0)
        self.assertEqual(summary["trigger_permissioned_rows"], 30)
        self.assertLess(summary["trigger_permissioned_delta_triggered_vs_pre"], 0)
        self.assertIn("wu_current_temp_bucket_crossed|down", policy["allowed_reason_directions"])
        self.assertNotIn("wu_current_temp_bucket_crossed|up", policy["allowed_reason_directions"])

    def test_latest_trade_permission_requires_allowed_fresh_policy_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "observation_trigger_replay.json"
            policy_path.write_text(json.dumps({
                "summary": {
                    "trigger_permission_policy": {
                        "acceptance_status": "PASS_WITH_PERMISSION_POLICY",
                        "allowed_reason_directions": ["wu_current_temp_bucket_crossed|down"],
                    }
                }
            }), encoding="utf-8")
            now = datetime(2026, 6, 15, 16, 10, tzinfo=timezone.utc)
            status = {
                "pid": os.getpid(),
                "last_heartbeat": now.isoformat(),
                "interval_seconds": 60,
                "consecutive_errors": 0,
                "latest_triggered": {
                    "toronto": {
                        "trigger_context": {
                            "reason": "wu_current_temp_bucket_crossed",
                            "created_at_utc": now.isoformat(),
                            "primary_trigger": {"previous_value": 21, "current_value": 20},
                        }
                    },
                    "nyc": {
                        "trigger_context": {
                            "reason": "wu_current_temp_bucket_crossed",
                            "created_at_utc": now.isoformat(),
                            "primary_trigger": {"previous_value": 20, "current_value": 21},
                        }
                    },
                },
            }

            permission = latest_trade_permission(status, now=now, policy_path=policy_path)

        self.assertTrue(permission["permissioned_markets"]["toronto"])
        self.assertFalse(permission["permissioned_markets"]["nyc"])
        self.assertTrue(permission["trade_permissioned"])
        self.assertEqual(permission["blocked_reasons"]["nyc"], "wu_current_temp_bucket_crossed|up")


if __name__ == "__main__":
    unittest.main()
