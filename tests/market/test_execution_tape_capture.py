import hashlib
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.market.execution_tape_capture import (
    confirmed_subscription_assets,
    confirmed_subscription_routes,
    frame_proves_subscription,
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

    def test_admits_repeated_identity_and_distinct_event_with_same_transaction_hash(self):
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
                reused_hash = coordinator.ingest_frame(
                    changed,
                    session_id="s1",
                    received_at=started + timedelta(seconds=2),
                )
                status = coordinator.stores[seed.key].status_payload(now=started + timedelta(seconds=2))
                global_status = read_capture_status(tmp)
                trade_rows = list(coordinator.stores[seed.key].trades.iter_rows())
                dedupe_rows = list(coordinator.stores[seed.key].dedupe.iter_rows())
            finally:
                coordinator.close()

        self.assertEqual(first["written"], 1)
        self.assertEqual(duplicate["written"], 1)
        self.assertEqual(duplicate["duplicates"], 0)
        self.assertEqual(duplicate["repeated_execution_identities_admitted"], 1)
        self.assertEqual(reused_hash["written"], 1)
        self.assertEqual(reused_hash["transaction_hash_reuses_admitted"], 1)
        self.assertEqual(status["trades_written"], 3)
        self.assertEqual(status["duplicates_suppressed"], 0)
        self.assertEqual(status["duplicate_conflicts"], 0)
        self.assertEqual(status["transaction_hash_reuses_admitted"], 1)
        self.assertEqual(status["repeated_execution_identities_admitted"], 1)
        self.assertEqual(status["nonunique_execution_observations_admitted"], 3)
        self.assertTrue(
            all(
                item["execution_identity_strength"]
                == "transaction_hash_plus_economics_not_proven_unique"
                for item in trade_rows
            )
        )
        self.assertEqual(
            status["last_counted"]["dedupe_key"],
            "none_public_stream_has_no_documented_unique_execution_id",
        )
        self.assertEqual(status["last_counted"]["trade_tape"]["row_count"], 3)
        self.assertEqual(global_status["last_counted"]["trades_written"], 3)
        self.assertEqual(
            global_status["last_counted"]["transaction_hash_reuses_admitted"],
            1,
        )
        self.assertFalse(dedupe_rows[0]["payload_conflict"])
        self.assertEqual(dedupe_rows[0]["differing_fields"], [])
        self.assertEqual(
            dedupe_rows[0]["action"],
            "admitted_repeated_identity_not_proven_duplicate",
        )
        self.assertEqual(dedupe_rows[0]["prior_observation_count"], 1)

    def test_hashless_events_are_preserved_without_claiming_unique_execution_counts(self):
        row = dict(fixture_rows()[0])
        row.pop("transaction_hash")
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
            coordinator.mark_connected((seed.key,), session_id="s1", at=started)
            first = coordinator.ingest_frame(row, session_id="s1", received_at=started)
            second = coordinator.ingest_frame(
                row,
                session_id="s1",
                received_at=started + timedelta(seconds=1),
            )
            status = coordinator.status_payload(now=started + timedelta(seconds=1))
            market_status = coordinator.stores[seed.key].status_payload(
                now=started + timedelta(seconds=1)
            )
            tape_rows = list(coordinator.stores[seed.key].trades.iter_rows())
            coordinator.close()

            restarted = ExecutionTapeCoordinator(
                (seed,),
                snapshots_root=tmp,
                now=started + timedelta(seconds=2),
            )
            try:
                restarted_status = restarted.status_payload(
                    now=started + timedelta(seconds=2)
                )
            finally:
                restarted.close()

        self.assertEqual(first["written"], 1)
        self.assertEqual(second["written"], 1)
        self.assertEqual(first["weak_execution_identities_admitted"], 1)
        self.assertEqual(second["weak_execution_identities_admitted"], 1)
        self.assertEqual(len(tape_rows), 2)
        self.assertTrue(all(item["transaction_hash"] is None for item in tape_rows))
        self.assertTrue(
            all(
                item["execution_identity_strength"]
                == "economics_timestamp_only_not_unique"
                for item in tape_rows
            )
        )
        self.assertEqual(market_status["duplicates_suppressed"], 0)
        self.assertEqual(market_status["weak_execution_identities_admitted"], 2)
        self.assertEqual(market_status["repeated_execution_identities_admitted"], 1)
        self.assertEqual(market_status["nonunique_execution_observations_admitted"], 2)
        self.assertEqual(
            market_status["last_written_execution_identity_strength"],
            "economics_timestamp_only_not_unique",
        )
        self.assertEqual(status["evidence_integrity"], "PASS")
        self.assertEqual(status["identity_integrity"], "BLOCKED_UNIQUE_EXECUTION_COUNTS")
        self.assertEqual(
            status["identity_integrity_blockers"],
            ["public_stream_has_no_documented_unique_execution_id"],
        )
        self.assertTrue(status["price_path_evidence_usable"])
        self.assertEqual(
            restarted_status["identity_integrity"],
            "BLOCKED_UNIQUE_EXECUTION_COUNTS",
        )
        self.assertEqual(
            restarted_status["weak_execution_identities_admitted"],
            2,
        )
        self.assertEqual(
            restarted_status["repeated_execution_identities_admitted"],
            1,
        )
        self.assertEqual(
            restarted_status["nonunique_execution_observations_admitted"],
            2,
        )

    def test_batched_identical_observations_retain_distinct_raw_message_indexes(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                result = coordinator.ingest_frame(
                    [row, row],
                    session_id="s1",
                    received_at=started,
                )
                written = list(coordinator.stores[seed.key].trades.iter_rows())
            finally:
                coordinator.close()

        self.assertEqual(result["written"], 2)
        self.assertEqual(result["repeated_execution_identities_admitted"], 1)
        self.assertEqual([item["raw_message_index"] for item in written], [0, 1])
        self.assertEqual(written[0]["raw_payload_sha256"], written[1]["raw_payload_sha256"])

    def test_documented_optional_fields_can_be_absent_without_losing_price_path(self):
        row = dict(fixture_rows()[0])
        for field in ("fee_rate_bps", "size", "timestamp", "transaction_hash"):
            row.pop(field)
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                result = coordinator.ingest_frame(
                    row,
                    session_id="s1",
                    received_at=started,
                )
                status = coordinator.status_payload(now=started)
                written = list(coordinator.stores[seed.key].trades.iter_rows())
            finally:
                coordinator.close()

        self.assertEqual(result["written"], 1)
        self.assertEqual(result["partial_execution_observations_admitted"], 1)
        self.assertEqual(len(written), 1)
        self.assertIsNone(written[0]["fee_rate_bps"])
        self.assertIsNone(written[0]["size"])
        self.assertIsNone(written[0]["timestamp"])
        self.assertIsNone(written[0]["transaction_hash"])
        self.assertIsNone(written[0]["trade_time_utc"])
        self.assertEqual(
            written[0]["execution_observation_missing_optional_fields"],
            ["fee_rate_bps", "size", "timestamp", "transaction_hash"],
        )
        self.assertEqual(
            written[0]["execution_economics_completeness"],
            "partial_missing_optional_fields",
        )
        self.assertEqual(status["evidence_integrity"], "PASS")
        self.assertEqual(status["partial_execution_observations_admitted"], 1)
        self.assertTrue(status["price_path_evidence_usable"])

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
                quiet_global = coordinator.status_payload(now=started + timedelta(seconds=30))
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
        self.assertEqual(
            quiet_global["identity_integrity"],
            "BLOCKED_UNIQUE_EXECUTION_COUNTS",
        )
        self.assertTrue(quiet_global["price_path_evidence_usable"])
        self.assertEqual(
            quiet_global["price_path_basis"],
            "received_at_state_observations_only_no_row_weighting",
        )
        self.assertEqual(dark["trades_written"], 0)
        self.assertEqual(dark["connection_state"], "DISCONNECTED")
        self.assertEqual(dark["seconds_dark"], 15.0)
        self.assertEqual(dark["evidence_interpretation"], "NO_TRADES_DISCONNECTED_NOT_QUIET")

    def test_any_invalid_execution_blocks_global_evidence_integrity(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        invalid = dict(row, size="not-a-number")
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                result = coordinator.ingest_frame(
                    invalid,
                    session_id="s1",
                    received_at=started,
                )
                status = coordinator.status_payload(now=started)
            finally:
                coordinator.close()

        self.assertEqual(result["rejected"], 1)
        self.assertEqual(status["state"], "DEGRADED_EVIDENCE_LOSS")
        self.assertEqual(status["evidence_integrity"], "BLOCKED_EVIDENCE_LOSS")
        self.assertEqual(status["evidence_integrity_blockers"], ["parse_rejections"])

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

        self.assertEqual(status["trades_written"], 2)
        self.assertEqual(status["duplicates_suppressed"], 0)
        self.assertEqual(status["repeated_execution_identities_admitted"], 1)
        self.assertEqual(status["nonunique_execution_observations_admitted"], 2)
        self.assertEqual(status["partial_execution_observations_admitted"], 0)
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

        fake = FakeWebsocket(["PONG", json.dumps(row)])
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
                status = coordinator.stores[seed.key].status_payload(now=clock["now"])
            finally:
                coordinator.close()

        sent = json.loads(fake.sent[0])
        self.assertEqual(sent, {"assets_ids": [row["asset_id"]], "type": "market"})
        self.assertNotIn("operation", sent)
        self.assertEqual(result["messages"], 1)
        self.assertEqual(status["connection_count"], 1)
        self.assertEqual(status["messages_seen"], 1)
        self.assertEqual(status["parse_rejections"], 0)
        self.assertTrue(fake.closed)

    def test_only_a_routed_market_event_proves_subscription_coverage(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        other_row = next(item for item in fixture_rows() if item["market"] != row["market"])
        other_seed = MarketDaySeed(
            market_id="montreal",
            target_date=seed.target_date,
            event_slug="highest-temperature-in-montreal-on-august-10-2026",
            asset_ids=(other_row["asset_id"],),
            condition_ids=(other_row["market"],),
            source="committed-test-fixture",
        )

        self.assertFalse(frame_proves_subscription("PONG", (seed,)))
        self.assertFalse(frame_proves_subscription({"error": "invalid subscription"}, (seed,)))
        self.assertFalse(
            frame_proves_subscription(
                dict(row, asset_id=str(int(row["asset_id"]) + 1)),
                (seed,),
            )
        )
        self.assertTrue(frame_proves_subscription(row, (seed,)))
        self.assertEqual(confirmed_subscription_routes(row, (seed, other_seed)), (seed.key,))
        self.assertEqual(
            confirmed_subscription_routes(
                dict(row, asset_id=other_row["asset_id"]),
                (seed, other_seed),
            ),
            (),
        )

        two_asset_seed = MarketDaySeed(
            market_id=seed.market_id,
            target_date=seed.target_date,
            event_slug=seed.event_slug,
            asset_ids=(row["asset_id"], str(int(row["asset_id"]) + 1)),
            condition_ids=seed.condition_ids,
            source=seed.source,
        )
        self.assertEqual(
            confirmed_subscription_assets(row, (two_asset_seed,)),
            {two_asset_seed.key: (row["asset_id"],)},
        )
        self.assertFalse(frame_proves_subscription(row, (two_asset_seed,)))
        self.assertEqual(
            confirmed_subscription_routes(
                {
                    "event_type": "new_market",
                    "market": row["market"],
                    "assets_ids": list(two_asset_seed.asset_ids),
                },
                (two_asset_seed,),
            ),
            (two_asset_seed.key,),
        )

    def test_exact_asset_condition_pair_is_required_within_one_market_day(self):
        first = fixture_rows()[0]
        second = next(item for item in fixture_rows() if item["market"] != first["market"])
        seed = MarketDaySeed(
            market_id="toronto",
            target_date=date(2026, 8, 10),
            event_slug="highest-temperature-in-toronto-on-august-10-2026",
            asset_ids=(first["asset_id"], second["asset_id"]),
            condition_ids=(first["market"], second["market"]),
            asset_condition_pairs=(
                (first["asset_id"], first["market"]),
                (second["asset_id"], second["market"]),
            ),
            source="committed-test-fixture",
        )
        mismatched = dict(first, market=second["market"])
        self.assertEqual(confirmed_subscription_assets(mismatched, (seed,)), {})

        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                coordinator.begin_connecting((seed.key,), session_id="s1", at=started)
                coordinator.mark_connected((seed.key,), session_id="s1", at=started)
                result = coordinator.ingest_frame(
                    mismatched,
                    session_id="s1",
                    received_at=started,
                )
                status = coordinator.status_payload(now=started)
            finally:
                coordinator.close()

        self.assertEqual(result["written"], 0)
        self.assertEqual(result["ambiguous"], 1)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(status["ambiguous_routes"], 1)
        self.assertEqual(status["evidence_integrity"], "BLOCKED_EVIDENCE_LOSS")

    def test_live_session_disconnects_when_server_goes_silent_after_confirmation(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        fake = FakeWebsocket([json.dumps(row)])
        monotonic = {"value": 0.0}

        def monotonic_fn():
            monotonic["value"] += 0.5
            return monotonic["value"]

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=started)
            try:
                with self.assertRaisesRegex(TimeoutError, "inbound server heartbeat"):
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        heartbeat_seconds=1.0,
                        inbound_silence_timeout_seconds=3.0,
                        connect_timeout_seconds=10.0,
                        now_fn=lambda: started,
                        monotonic_fn=monotonic_fn,
                    )
                status = coordinator.stores[seed.key].status_payload(now=started)
            finally:
                coordinator.close()

        self.assertEqual(status["connection_state"], "DISCONNECTED")
        self.assertGreaterEqual(status["disconnect_count"], 1)
        self.assertTrue(fake.closed)

    def test_live_session_accumulates_every_asset_before_marking_route_connected(self):
        first = fixture_rows()[0]
        second = dict(first, asset_id=str(int(first["asset_id"]) + 1))
        seed = MarketDaySeed(
            market_id="toronto",
            target_date=date(2026, 8, 10),
            event_slug="highest-temperature-in-toronto-on-august-10-2026",
            asset_ids=(first["asset_id"], second["asset_id"]),
            condition_ids=(first["market"],),
            source="committed-test-fixture",
        )
        started = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)
        fake = FakeWebsocket([json.dumps(first), json.dumps(second)])
        clock = {"now": started}

        def now_fn():
            clock["now"] += timedelta(milliseconds=100)
            return clock["now"]

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
                    max_messages=2,
                )
                status = coordinator.stores[seed.key].status_payload(now=clock["now"])
            finally:
                coordinator.close()

        self.assertEqual(result["messages"], 2)
        self.assertEqual(status["connection_count"], 1)
        self.assertEqual(status["trades_written"], 2)
        self.assertEqual(status["messages_seen"], 2)

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
