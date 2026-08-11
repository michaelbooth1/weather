import hashlib
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.market.execution_tape_capture import (
    fixture_sizing,
    load_market_day_seeds,
    read_capture_status,
    run_connection_once,
    subscription_payload,
)
from weather.market.execution_tape_store import (
    EXECUTION_TAPE_GAP_SCHEMA_VERSION,
    ExecutionTapeCoordinator,
    MarketDaySeed,
    parse_execution_payload,
)
from weather.market.market_config import config_for_date
from weather.schema_registry import schema_version


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "docs" / "roadmap" / "execution-tape-pilot-2026-08-10-trades.jsonl"
PILOT_REPORT = REPO_ROOT / "docs" / "roadmap" / "execution-tape-pilot-2026-08-10-report.json"
EXPECTED_FIXTURE_SHA256 = "2710e5cf4d9438ac2c1362575344075f9a84da51481b2285170a84074b67e32a"


def fixture_rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def one_seed(row=None):
    row = row or fixture_rows()[0]
    return MarketDaySeed(
        market_id="toronto",
        target_date=date(2026, 8, 10),
        event_slug="highest-temperature-in-toronto-on-august-10-2026",
        asset_ids=(row["asset_id"],),
        condition_ids=(row["market"],),
        source="committed-test-fixture",
    )


class FakeWebsocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        if not self.frames:
            raise TimeoutError()
        return self.frames.pop(0)

    def close(self):
        self.closed = True


class ExecutionTapeCaptureTests(unittest.TestCase):
    def test_committed_fixture_hash_shape_and_parser(self):
        raw = FIXTURE.read_bytes()
        rows = fixture_rows()

        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_FIXTURE_SHA256)
        self.assertEqual(len(raw), 15967)
        self.assertEqual(len(rows), 40)
        self.assertEqual(len({row["market"] for row in rows}), 11)
        self.assertTrue(all(row.get("transaction_hash") for row in rows))

        batch = parse_execution_payload(FIXTURE.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(len(batch.trades), 1)
        self.assertEqual(batch.non_trade_messages, 0)
        self.assertEqual(batch.rejected, ())
        self.assertEqual(batch.trades[0]["event_type"], "last_trade_price")
        self.assertEqual(batch.raw_payload_sha256_algorithm, "sha256-raw-utf8")

    def test_dedupes_on_transaction_hash_and_records_conflicting_redelivery(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                first = coordinator.ingest_frame(row, session_id="s1", received_at=started)
                duplicate = coordinator.ingest_frame(row, session_id="s1", received_at=started + timedelta(seconds=1))
                changed = dict(row, price="0.998")
                conflict = coordinator.ingest_frame(
                    changed,
                    session_id="s1",
                    received_at=started + timedelta(seconds=2),
                )
                status = coordinator.stores[seed.key].status_payload(now=started + timedelta(seconds=2))
                global_status = read_capture_status(tmp)
                dedupe_rows = list(coordinator.stores[seed.key].dedupe.iter_rows())
            finally:
                coordinator.close()

        self.assertEqual(first["written"], 1)
        self.assertEqual(duplicate["duplicates"], 1)
        self.assertEqual(conflict["duplicate_conflicts"], 1)
        self.assertEqual(status["trades_written"], 1)
        self.assertEqual(status["duplicates_suppressed"], 2)
        self.assertEqual(status["duplicate_conflicts"], 1)
        self.assertEqual(status["last_counted"]["dedupe_key"], "transaction_hash")
        self.assertEqual(status["last_counted"]["trade_tape"]["row_count"], 1)
        self.assertEqual(global_status["last_counted"]["trades_written"], 1)
        self.assertFalse(dedupe_rows[0]["payload_conflict"])
        self.assertEqual(dedupe_rows[1]["differing_fields"], ["price"])
        self.assertEqual(dedupe_rows[1]["action"], "suppressed_keep_first")

    def test_rotates_trade_parts_before_the_bound(self):
        base = fixture_rows()[0]
        seed = one_seed(base)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator(
                (seed,),
                snapshots_root=tmp,
                max_part_bytes=1800,
                now=started,
            )
            try:
                coordinator.begin_connecting((seed.key,), session_id="rotate", at=started)
                coordinator.mark_connected((seed.key,), session_id="rotate", at=started)
                for index in range(10):
                    row = dict(
                        base,
                        timestamp=str(int(base["timestamp"]) + index),
                        transaction_hash=f"0x{index + 1:064x}",
                    )
                    coordinator.ingest_frame(
                        row,
                        session_id="rotate",
                        received_at=started + timedelta(milliseconds=index),
                    )
                stats = coordinator.stores[seed.key].trades.stats()
                part_sizes = [path.stat().st_size for path in sorted(
                    coordinator.stores[seed.key].root.glob("trades-*.jsonl")
                )]
            finally:
                coordinator.close()

        self.assertEqual(stats["row_count"], 10)
        self.assertGreater(stats["part_count"], 1)
        self.assertTrue(all(size <= 1800 for size in part_sizes))

    def test_status_distinguishes_connected_quiet_from_disconnected_empty(self):
        seed = one_seed()
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="quiet", at=started)
                coordinator.mark_connected((seed.key,), session_id="quiet", at=started)
                quiet = coordinator.stores[seed.key].status_payload(now=started + timedelta(seconds=30))
                coordinator.mark_disconnected(
                    (seed.key,),
                    session_id="quiet",
                    at=started + timedelta(seconds=30),
                    reason="test_disconnect",
                )
                dark = coordinator.stores[seed.key].status_payload(now=started + timedelta(seconds=45))
            finally:
                coordinator.close()

        self.assertEqual(quiet["trades_written"], 0)
        self.assertEqual(quiet["seconds_dark"], 0.0)
        self.assertEqual(quiet["evidence_interpretation"], "NO_TRADES_CONNECTED_QUIET")
        self.assertEqual(dark["trades_written"], 0)
        self.assertEqual(dark["connection_state"], "DISCONNECTED")
        self.assertEqual(dark["seconds_dark"], 15.0)
        self.assertEqual(dark["evidence_interpretation"], "NO_TRADES_DISCONNECTED_NOT_QUIET")

    def test_reconnect_closes_gap_and_records_seconds_dark(self):
        seed = one_seed()
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                coordinator.mark_disconnected(
                    (seed.key,),
                    session_id="s1",
                    at=started + timedelta(seconds=10),
                    reason="socket_closed",
                )
                coordinator.begin_connecting(
                    (seed.key,),
                    session_id="s2",
                    at=started + timedelta(seconds=15),
                )
                coordinator.mark_connected(
                    (seed.key,),
                    session_id="s2",
                    at=started + timedelta(seconds=20),
                )
                status = coordinator.stores[seed.key].status_payload(now=started + timedelta(seconds=20))
                gap_rows = list(coordinator.stores[seed.key].gaps.iter_rows())
            finally:
                coordinator.close()

        self.assertEqual(status["gap_count"], 2)
        self.assertEqual(status["completed_gap_count"], 2)
        self.assertEqual(status["disconnect_count"], 1)
        self.assertEqual(status["reconnect_count"], 1)
        self.assertEqual(status["seconds_dark"], 10.0)
        self.assertEqual([row["gap_state"] for row in gap_rows], ["OPEN", "CLOSED", "OPEN", "CLOSED"])
        self.assertTrue(all(row["schema_version"] == EXECUTION_TAPE_GAP_SCHEMA_VERSION for row in gap_rows))
        self.assertEqual(gap_rows[-1]["seconds_dark"], 10.0)

    def test_restart_recounts_status_from_append_only_tapes(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            first = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            first.begin_connecting((seed.key,), session_id="s1", at=started)
            first.mark_connected((seed.key,), session_id="s1", at=started)
            first.ingest_frame(row, session_id="s1", received_at=started)
            first.ingest_frame(row, session_id="s1", received_at=started + timedelta(seconds=1))
            first.mark_disconnected(
                (seed.key,),
                session_id="s1",
                at=started + timedelta(seconds=10),
                reason="socket_closed",
            )
            first.mark_connected(
                (seed.key,),
                session_id="s2",
                at=started + timedelta(seconds=20),
            )
            first.close()

            restarted = ExecutionTapeCoordinator(
                (seed,),
                snapshots_root=tmp,
                now=started + timedelta(seconds=30),
            )
            try:
                status = restarted.stores[seed.key].status_payload(
                    now=started + timedelta(seconds=30)
                )
            finally:
                restarted.close()

        self.assertEqual(status["trades_written"], 1)
        self.assertEqual(status["duplicates_suppressed"], 1)
        self.assertEqual(status["connection_count"], 2)
        self.assertEqual(status["reconnect_count"], 1)
        self.assertEqual(status["disconnect_count"], 2)
        self.assertEqual(status["seconds_dark_completed"], 10.0)
        self.assertEqual(status["seconds_dark"], 20.0)
        self.assertEqual(status["connection_state"], "DISCONNECTED")
        self.assertEqual(status["evidence_interpretation"], "TRADES_WITH_COVERAGE_GAPS")
        self.assertEqual(
            status["last_counted"]["counter_basis"],
            "physical JSONL scan at open plus fsynced append receipts",
        )

    def test_live_session_uses_documented_public_subscription_frame(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        clock = {"now": started}

        def now_fn():
            result = clock["now"]
            clock["now"] += timedelta(milliseconds=100)
            return result

        fake = FakeWebsocket([json.dumps(row)])
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                result = run_connection_once(
                    coordinator,
                    (seed,),
                    stop_event=threading.Event(),
                    websocket_factory=lambda *_args, **_kwargs: fake,
                    now_fn=now_fn,
                    monotonic_fn=lambda: 0.0,
                    max_messages=1,
                )
            finally:
                coordinator.close()

        sent = json.loads(fake.sent[0])
        self.assertEqual(sent, {"assets_ids": [row["asset_id"]], "type": "market"})
        self.assertNotIn("operation", sent)
        self.assertEqual(result["messages"], 1)
        self.assertTrue(fake.closed)

    def test_seed_loader_is_offline_fail_closed_and_target_date_bound(self):
        target = date(2026, 8, 10)
        slug = config_for_date(target, "toronto").event_slug
        payload = {
            "schema_version": schema_version("location_market_events"),
            "generated_at_utc": "2026-08-10T21:00:00+00:00",
            "locations": [{
                "location_id": "toronto",
                "active_events": [{
                    "event_date": target.isoformat(),
                    "event_slug": slug,
                    "markets": [{
                        "condition_id": f"0x{1:064x}",
                        "active": True,
                        "closed": False,
                        "outcomes": [
                            {"name": "Yes", "token_id": "101"},
                            {"name": "No", "token_id": "102"},
                        ],
                    }],
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "location_market_events.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            seeds = load_market_day_seeds(
                path,
                markets="toronto",
                target_date=target,
                now="2026-08-10T22:00:00+00:00",
            )

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].event_slug, slug)
        self.assertEqual(seeds[0].asset_ids, ("101", "102"))
        self.assertEqual(seeds[0].condition_ids, (f"0x{1:064x}",))

    def test_fixture_sizing_states_single_window_basis(self):
        result = fixture_sizing(FIXTURE, PILOT_REPORT)

        self.assertEqual(result["fixture_sha256"], EXPECTED_FIXTURE_SHA256)
        self.assertAlmostEqual(result["bytes_per_trade"], 399.175)
        self.assertAlmostEqual(result["projected_bytes_per_market_day"], 255408.132)
        self.assertAlmostEqual(result["projected_gb_per_year_decimal"], 1.11868761816)
        self.assertAlmostEqual(
            result["as_captured_crlf_projection"]["bytes_per_trade"],
            400.175,
        )
        self.assertIn("one 30-minute evening window", result["rate_caveat"])
        self.assertIn("not a day", result["rate_caveat"])

    def test_subscription_partition_does_not_split_a_market_day(self):
        seed = one_seed()
        frame = subscription_payload((seed,))

        self.assertEqual(frame["type"], "market")
        self.assertEqual(frame["assets_ids"], list(seed.asset_ids))


if __name__ == "__main__":
    unittest.main()
