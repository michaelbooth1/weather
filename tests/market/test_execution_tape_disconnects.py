import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from weather.market.execution_tape_disconnects import classify_disconnects, classify_reason, main
from weather.market.execution_tape_store import ExecutionTapeCoordinator, MarketDaySeed


def seed(market_id, condition, assets):
    return MarketDaySeed(
        market_id=market_id,
        target_date=date(2026, 9, 29),
        event_slug=f"highest-temperature-in-{market_id}-on-september-29-2026",
        asset_ids=assets,
        condition_ids=(condition,),
        source="test",
    )


TORONTO = seed("toronto", f"0x{1:064x}", ("101", "102"))
CHICAGO = seed("chicago", f"0x{2:064x}", ("201", "202"))
ROUTES = (TORONTO.key, CHICAGO.key)


class DisconnectClassifierTests(unittest.TestCase):
    def write_day(self, root):
        """Write a production gap ledger: two routes share one connection."""

        start = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)  # 00:00 Toronto
        coordinator = ExecutionTapeCoordinator((TORONTO, CHICAGO), snapshots_root=root, now=start)
        script = [
            # (local hour offset, connected seconds, reason)
            (2, 600, "TimeoutError: no inbound server heartbeat or market frame before silence deadline"),
            (13, 120, "WebSocketConnectionClosedException: Connection to remote host was lost."),
            (13.5, 90, "ConnectionError: websocket returned an empty frame"),
            (14, 60, "VenueCloseError: venue closed the websocket: code=1011 reason='overloaded'"),
            (15, 30, "TimeoutError: no inbound server heartbeat or market frame before silence deadline"),
        ]
        try:
            for index, (hour, connected_seconds, reason) in enumerate(script):
                session = f"s{index}"
                at = start + timedelta(hours=hour)
                coordinator.begin_connecting(ROUTES, session_id=session, at=at)
                coordinator.mark_connected(ROUTES, session_id=session, at=at + timedelta(seconds=5))
                coordinator.mark_disconnected(
                    ROUTES,
                    session_id=session,
                    at=at + timedelta(seconds=5 + connected_seconds),
                    reason=reason,
                )
            # A failed reconnect that never proved its routes.
            at = start + timedelta(hours=16)
            coordinator.begin_connecting(ROUTES, session_id="s-fail", at=at)
            coordinator.mark_disconnected(
                ROUTES,
                session_id="s-fail",
                at=at + timedelta(seconds=30),
                reason="TimeoutError: subscription was not confirmed by a routed market frame",
            )
            coordinator.begin_connecting(ROUTES, session_id="s-last", at=at + timedelta(seconds=60))
            coordinator.mark_connected(ROUTES, session_id="s-last", at=at + timedelta(seconds=62))
        finally:
            coordinator.close()

    def test_rows_group_into_socket_events_with_causes_hours_and_lifetimes(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_day(root)
            report = classify_disconnects(root, local_date="2026-09-29")

        self.assertEqual(len(report["inputs"]), 2)
        # Five drops after proof, each one row per route on the connection.
        self.assertEqual(report["socket_disconnects_total"], 5)
        self.assertEqual(report["socket_disconnects_by_cause"], {
            "silence_timeout": 2,
            "connection_lost": 1,
            "empty_frame": 1,
            "venue_close": 1,
        })
        self.assertEqual(report["lifecycle_rows_by_cause"]["silence_timeout"], 4)
        self.assertEqual(report["lifecycle_rows_by_cause"]["startup"], 2)
        self.assertEqual(report["venue_close_codes"], {"1011": 1})
        self.assertEqual(report["hourly_socket_disconnects"]["02"], {"silence_timeout": 1})
        self.assertEqual(report["hourly_socket_disconnects"]["13"], {"connection_lost": 1, "empty_frame": 1})
        self.assertEqual(report["daytime_vs_overnight"]["daytime"]["socket_disconnects"], 4)
        self.assertEqual(report["daytime_vs_overnight"]["overnight"]["socket_disconnects"], 1)
        self.assertEqual(report["session_lifetime_seconds_by_cause"]["silence_timeout"]["n"], 2)
        self.assertEqual(report["session_lifetime_seconds_by_cause"]["silence_timeout"]["max"], 600.0)
        self.assertEqual(report["session_lifetime_seconds_by_cause"]["venue_close"]["median"], 60.0)
        # Silence gaps per route: 02:10:05 -> 13:00:05 (39,000 s), and 15:00:35
        # through the unconfirmed retry to 16:01:02 (3,627 s).
        dark = report["route_dark_seconds_by_cause"]["silence_timeout"]
        self.assertEqual(dark["n"], 4)
        self.assertEqual(dark["sum"], 2 * 39000.0 + 2 * 3627.0)

    def test_other_dates_are_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_day(root)
            report = classify_disconnects(root, local_date="2026-09-28")
        self.assertEqual(report["socket_disconnects_total"], 0)
        self.assertEqual(report["lifecycle_rows_total"], 0)

    def test_cli_prints_json(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_day(root)
            out = f"{root}/report.json"
            self.assertEqual(main(["--snapshots-root", root, "--date", "2026-09-29", "--output", out]), 0)
            with open(out, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["socket_disconnects_total"], 5)

    def test_reason_classes_cover_known_messages(self):
        cases = {
            "TimeoutError: subscription was not confirmed by a routed market frame": "confirmation_timeout",
            "ConnectionResetError: [WinError 10054] An existing connection was forcibly closed": "connection_reset",
            "WebSocketBadStatusException: Handshake status 429 Too Many Requests": "handshake_rejected",
            "SSLEOFError: EOF occurred in violation of protocol": "tls_error",
            "TimeoutError: timed out": "socket_timeout",
            "OSError: [Errno 5] Input/output error": "tape_writer_error",
            "stop_requested": "orderly_stop",
            "unclean_process_restart_from_connected": "process_restart",
            "seed_error: ExecutionTapeSeedError: stale": "seed_error",
            "new_session_replaced_connected_session": "session_replaced",
            "something new": "other",
        }
        for reason, cause in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify_reason(reason), cause)


if __name__ == "__main__":
    unittest.main()
