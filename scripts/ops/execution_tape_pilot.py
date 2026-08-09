"""Bounded pilot for execution-tape capture. Measures; does not install anything.

Authorized by the operator 2026-08-09 (ESTABLISHED_FINDINGS.md 8c). This answers the three
questions that must NOT be assumed before a continuous producer is built:

  1. Does the CURRENT documented subscription frame {"type": "market"} work? The existing
     collector sends the legacy {"operation": "subscribe"} frame, which was accepted
     historically. -09-47a flagged inheriting that compatibility assumption silently.
  2. What is the REAL last_trade_price rate? The "order 10^2 per market-day" figure is 411
     observed trades scaled by a 2.222% duty cycle. Message limits truncate sessions, so the
     truth is >= that, not ~= that. Nothing may be sized from an extrapolation.
  3. Does execution identity survive END TO END -- transaction_hash and the vendor exchange
     timestamp, in a row we actually wrote?

DELIBERATE NON-GOALS. This writes nothing under data/, registers no task, starts no loop, and
places no order. It is read-only with respect to production state.

DO NOT RUN INSIDE 12:00-18:00 local. That is the graded capture window; this opens a network
connection on the capture host, and capture already died once on 2026-08-09. The script refuses.

Usage (from the repo root, after 18:00):
    venv\\Scripts\\python.exe scripts\\ops\\execution_tape_pilot.py --seconds 1800
"""

from __future__ import annotations

import argparse
import collections
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.market.market_microstructure_constants import CLOB_WS_URL

# The graded window the Toronto streak verdict is computed over. Mirrors
# collection_health.AFTERNOON_START_HOUR / AFTERNOON_END_HOUR rather than restating a number
# that could drift away from it.
from weather.collection.collection_health import (
    AFTERNOON_END_HOUR,
    AFTERNOON_START_HOUR,
)

TRADE_EVENT = "last_trade_price"

# Fields the venue documents on the trade event. Any that arrive empty are a finding, because
# a continuous producer cannot reconstruct them later.
IDENTITY_FIELDS = ("transaction_hash", "timestamp", "price", "size", "side", "asset_id", "market")


def _refuse_inside_graded_window(now: datetime, *, force: bool) -> None:
    if force:
        print("WARNING: --i-know-capture-is-at-risk given; graded-window refusal bypassed")
        return
    if AFTERNOON_START_HOUR <= now.hour < AFTERNOON_END_HOUR:
        raise SystemExit(
            f"refusing to run at {now:%H:%M}: inside the graded capture window "
            f"({AFTERNOON_START_HOUR:02d}:00-{AFTERNOON_END_HOUR:02d}:00). "
            "Run after 18:00. This is the window the streak verdict is computed over."
        )


def _token_ids(limit_markets: int) -> list[str]:
    """Discover live CLOB token ids exactly the way capture_market_enrichment does.

    Resolved against the real capture path rather than invented: PolymarketClient(market_id)
    -> get_event() -> token_rows_from_event -> filter_token_rows. An earlier draft of this
    script imported a `weather.market.event_discovery.active_events` that does not exist.
    """
    from weather.market.market_microstructure_capture import (
        filter_token_rows,
        token_rows_from_event,
    )
    from weather.market.market_registry import all_specs
    from weather.market.polymarket_client import PolymarketClient

    token_ids: list[str] = []
    for spec in list(all_specs())[:limit_markets]:
        try:
            event = PolymarketClient(market_id=spec.id).get_event()
            rows = filter_token_rows(
                token_rows_from_event(event, market_id=spec.id, captured_at=datetime.now(timezone.utc)),
                outcomes="all",
            )
        except Exception as exc:  # noqa: BLE001 - a market that cannot resolve is not fatal here
            print(f"  {spec.id}: token discovery failed ({type(exc).__name__}: {exc})")
            continue
        ids = [row["clob_token_id"] for row in rows]
        print(f"  {spec.id}: {len(ids)} token id(s)")
        token_ids.extend(ids)
    return token_ids


def run(seconds: float, token_ids: list[str], out_dir: Path) -> dict:
    import websocket  # type: ignore

    results = {}
    for frame_name, frame in (
        ("documented", {"assets_ids": token_ids, "type": "market"}),
        ("legacy", {"operation": "subscribe", "assets_ids": token_ids}),
    ):
        counts: collections.Counter = collections.Counter()
        trades: list[dict] = []
        started = time.time()
        raw_bytes = 0
        try:
            ws = websocket.create_connection(CLOB_WS_URL, timeout=30)
            ws.settimeout(10.0)
            ws.send(json.dumps(frame))
            next_ping = time.time() + 10.0
            while time.time() - started < seconds:
                try:
                    raw = ws.recv()
                except Exception:
                    if time.time() >= next_ping:
                        try:
                            ws.send("PING")
                            next_ping = time.time() + 10.0
                        except Exception:
                            break
                    continue
                if not raw:
                    continue
                raw_bytes += len(raw) if isinstance(raw, (bytes, str)) else 0
                try:
                    payload = json.loads(raw)
                except Exception:
                    counts["<unparseable>"] += 1
                    continue
                for item in payload if isinstance(payload, list) else [payload]:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get("event_type") or "<none>"
                    counts[kind] += 1
                    if kind == TRADE_EVENT:
                        trades.append(item)
                if time.time() >= next_ping:
                    try:
                        ws.send("PING")
                        next_ping = time.time() + 10.0
                    except Exception:
                        break
            ws.close()
            accepted = sum(counts.values()) > 0
        except Exception as exc:  # noqa: BLE001 - the failure mode IS the measurement
            accepted = False
            counts["<connect_error>"] += 1
            results[frame_name] = {"error": repr(exc)}

        elapsed = max(1e-9, time.time() - started)
        missing = {
            field: sum(1 for t in trades if not t.get(field))
            for field in IDENTITY_FIELDS
        }
        results.setdefault(frame_name, {}).update({
            "accepted": accepted,
            "elapsed_seconds": round(elapsed, 1),
            "event_counts": dict(counts),
            "trades_seen": len(trades),
            "trades_per_hour": round(len(trades) * 3600.0 / elapsed, 2),
            "raw_bytes": raw_bytes,
            "identity_fields_missing": missing,
            "identity_survives": bool(trades) and not any(missing.values()),
        })
        if trades:
            path = out_dir / f"pilot_trades_{frame_name}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for row in trades:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
            results[frame_name]["trade_sample_path"] = str(path)
            results[frame_name]["execution_only_bytes"] = path.stat().st_size
        # Only fall through to the legacy frame if the documented one did not work.
        if frame_name == "documented" and results[frame_name].get("accepted"):
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=1800.0)
    parser.add_argument("--markets", type=int, default=3)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--i-know-capture-is-at-risk", action="store_true")
    args = parser.parse_args()

    _refuse_inside_graded_window(datetime.now(), force=args.i_know_capture_is_at_risk)

    out_dir = Path(args.out_dir) if args.out_dir else Path("C:/tmp/execution_tape_pilot")
    out_dir.mkdir(parents=True, exist_ok=True)

    token_ids = _token_ids(args.markets)
    if not token_ids:
        raise SystemExit("no live CLOB token ids discovered; nothing to subscribe to")
    print(f"subscribing to {len(token_ids)} token id(s) for {args.seconds:.0f}s")

    results = run(args.seconds, token_ids, out_dir)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ws_url": CLOB_WS_URL,
        "token_id_count": len(token_ids),
        "requested_seconds": args.seconds,
        "results": results,
    }
    report = out_dir / "pilot_report.json"
    report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"\nwrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
