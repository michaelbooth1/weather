"""Passive maker evidence: public books, reward changes, raw updates and trades.

No account, SDK, credential, dotenv or order modules are imported. A dry run
uses a new scratch directory and is forcibly bounded before 19:45 Eastern.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.market.maker_evidence_public import (
    CLOB, GAMMA, CONDITION, PublicReader, modelled_reward, reward_rate, reward_record,
    select_universe, unique_rows,
)
from weather.market.maker_evidence_store import (
    DEFAULT_STREAM_CAP, SCHEMA, EvidenceStore, WriterLock, RawFootprintLimit,
    atomic_json, disk_band, digest, encoded, utc_now,
)
from weather.market.maker_evidence_archive import compress_closed_segments
from weather.market.maker_evidence_stream import PublicStream
from weather.paths import data_path

DEFAULT_ROOT = data_path("maker_evidence")


def load_extras(path):
    if path is None or not Path(path).exists():
        return []
    if Path(path).stat().st_size > 65536:
        raise ValueError("extra_conditions file exceeds byte limit")
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload["extra_conditions"]
    if not isinstance(rows, list) or len(rows) > 32 or any(not isinstance(x, str) or not CONDITION.fullmatch(x) for x in rows):
        raise ValueError("extra_conditions must contain at most 32 condition ids")
    return list(dict.fromkeys(x.lower() for x in rows))


def token_pair(market):
    tokens = market.get("clobTokenIds")
    outcomes = market.get("outcomes")
    tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
    outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    if len(tokens or []) != 2 or len(set(tokens)) != 2 or set(outcomes or []) != {"Yes", "No"}:
        raise ValueError("market lacks exact YES/NO token mapping")
    if any(not re.fullmatch(r"[0-9]{1,100}", str(token)) for token in tokens):
        raise ValueError("invalid token id")
    return [str(tokens[outcomes.index("Yes")]), str(tokens[outcomes.index("No")])]


def update_window(path, now):
    """Extras remain minute-book coverage; raw updates require a bounded UTC window."""
    ids = load_extras(path)
    if not ids:
        return [], None
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    windows = payload.get("update_windows_utc", [])
    if not isinstance(windows, list) or len(windows) > 2:
        raise ValueError("at most two 30-minute update windows are allowed")
    active = None
    prior_end = None
    for window in sorted(windows, key=lambda row: row["start"]):
        start, end = (datetime.fromisoformat(window[key].replace("Z", "+00:00")) for key in ("start", "end"))
        if start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
            raise ValueError("update windows require explicit UTC timestamps")
        if not 0 < (end - start).total_seconds() <= 1800 or prior_end and start < prior_end:
            raise ValueError("update windows must be nonoverlapping and at most 30 minutes")
        prior_end = end
        if start <= now < end:
            active = end
    return (ids, active) if active else ([], None)


def get_books(reader, tokens, *, kind):
    books = {}
    wanted = list(dict.fromkeys(tokens))
    for start in range(0, len(wanted), 100):
        batch = wanted[start:start + 100]
        rows = reader.read(CLOB + "/books", body=[{"token_id": token} for token in batch], kind=kind)
        rows = unique_rows(rows, key="asset_id", on_duplicate=lambda token:
                           reader.store.event("duplicate", {"source": "books", "token_id": token}))
        if {str(row["asset_id"]) for row in rows} != set(batch):
            raise ValueError("book batch token coverage mismatch")
        books.update((str(row["asset_id"]), row) for row in rows)
    return books


def build_universe(reader, specs, *, now, extras_path=None):
    expected = {event_slug_for_date(now.astimezone(spec.tz).date() + timedelta(days=day), spec.id): (spec.id, day)
                for spec in specs for day in range(3)}
    all_events = []
    slugs = list(expected)
    for start in range(0, len(slugs), 12):
        for page in range(10):
            events = reader.read(GAMMA + "/events", params=[("slug", slug) for slug in slugs[start:start + 12]]
                                 + [("limit", 100), ("offset", page * 100)], kind="discovery")
            if not isinstance(events, list):
                raise ValueError("events reply is not a list")
            all_events.extend(events)
            if len(events) < 100:
                break
        else:
            raise ValueError("event pagination exceeded bound")
    events = unique_rows(all_events, key="id", on_duplicate=lambda identity:
                         reader.store.event("duplicate", {"source": "events", "id": identity}))
    discovered, missing = {}, set(expected)
    for event in events:
        slug = event["slug"]
        if slug not in expected:
            raise ValueError("event response escaped requested slugs")
        missing.discard(slug)
        city, day = expected[slug]
        for market in unique_rows(event["markets"], key="conditionId"):
            if market.get("closed") or not market.get("active") or market.get("enableOrderBook") is False:
                continue
            cid = market["conditionId"].lower()
            row = {"condition_id": cid, "city": city, "day_ahead": day,
                   "event_slug": slug, "tokens": token_pair(market),
                   "reward": {"rewards_min_size": market.get("rewardsMinSize"),
                              "rewards_max_spread": market.get("rewardsMaxSpread"),
                              "rewards_config": [{"rate_per_day": r["rewardsDailyRate"],
                                                  "start_date": r["startDate"], "end_date": r["endDate"]}
                                                 for r in market.get("clobRewards", [])]}}
            if cid in discovered and discovered[cid] != row:
                raise ValueError("condition mapped to conflicting events")
            discovered[cid] = row
    extra_ids = load_extras(extras_path)
    for cid in extra_ids:
        if cid not in discovered:
            markets = reader.read(GAMMA + "/markets", params={"condition_ids": cid})
            markets = unique_rows(markets, key="conditionId")
            if len(markets) != 1 or markets[0]["conditionId"].lower() != cid:
                raise ValueError("extra condition identity mismatch")
            discovered[cid] = {"condition_id": cid, "city": "extra", "day_ahead": None,
                               "event_slug": None, "tokens": token_pair(markets[0])}
    if len(discovered) > 1200:
        raise ValueError("condition universe exceeds memory bound")
    eligible, extras = [], []
    today = now.date().isoformat()
    for cid, row in discovered.items():
        reward = row.get("reward")
        row = {**row, "reward": reward, "modelled_reward_20": 0.}
        if cid in extra_ids:
            extras.append(row)
        if reward and reward_rate(reward, today) > 0:
            eligible.append(row)
    books = get_books(reader, [row["tokens"][0] for row in eligible], kind="ranking_books")
    for row in eligible:
        book = books[row["tokens"][0]]
        if book["market"].lower() != row["condition_id"]:
            raise ValueError("ranking book condition mismatch")
        row["modelled_reward_20"] = modelled_reward(book, row["reward"], today)
    selected, shortages = select_universe(eligible, extras=extras)
    # Gamma supplies current reward eligibility for discovery/ranking. The full
    # per-condition CLOB record is retained for every selected band each cycle.
    for row in selected:
        row["clob_reward_content_sha256"] = digest(encoded(reward_record(reader, row["condition_id"])))
        reward = row.pop("reward", None)
        row["ranking_terms"] = ({"daily_rate": reward_rate(reward, today),
                                 "min_size": reward["rewards_min_size"],
                                 "max_spread_cents": reward["rewards_max_spread"]} if reward else None)
    present = {row["city"] for row in eligible}
    for spec in specs:
        if spec.id not in present:
            shortages.extend({"city": spec.id, "day_ahead": day, "available": 0} for day in range(3))
    for city in sorted({spec.id for spec in specs} | {row["city"] for row in selected}):
        reader.store.event("universe", {"city": city, "bands": [row for row in selected if row["city"] == city],
                                      "shortages": [row for row in shortages if row["city"] == city],
                                      "missing_events": sorted(slug for slug in missing if expected[slug][0] == city),
                                      "candidate_count": sum(row["city"] == city for row in eligible),
                                      "ranking": "20 shares, 1 cent outward, size-cutoff midpoint, share_many"},
                           partition=city)
    return selected, shortages, sorted(missing)


def lowest_priority():
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x40):
            raise OSError("could not set IDLE process priority")
    else:
        os.nice(19)


def re1_active():
    """Read only process command lines; never opens a session worktree/campaign."""
    if os.name != "nt":
        raise RuntimeError("RE-1 workstation guard requires Windows")
    script = ("$ErrorActionPreference='Stop'; $p=@(Get-CimInstance Win32_Process | "
              "Where-Object { $_.Name -match '^python(w|3)?(\\.exe)?$' -and "
              "$_.CommandLine -match '(?i)(reward[_-]test|re1[_-]|re_1)' -and "
              "$_.CommandLine -match '(?i)(^|\\s)(preflight|live)(\\s|$)' }); "
              "if($p.Count -gt 0){'ACTIVE'}else{'CLEAR'}")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", script], capture_output=True, text=True, timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or result.stdout.strip() not in ("CLEAR", "ACTIVE"):
        raise RuntimeError("cannot prove RE-1 process guard")
    return result.stdout.strip() == "ACTIVE"


def capture(args):
    root = args.root.resolve()
    if args.dry_run and (root.exists() or "scratch" not in [part.lower() for part in root.parts]):
        raise ValueError("dry run requires a NEW scratch directory")
    if args.dry_run:
        latest = utc_now().astimezone(ZoneInfo("America/Toronto")).replace(hour=19, minute=45, second=0, microsecond=0)
        # Keep cleanup reserve; no late run may claim completion.
        if (latest - utc_now()).total_seconds() < args.duration_seconds + 60 or re1_active():
            raise RuntimeError("dry run conflicts with RE-1 or 19:45 Eastern cutoff")
    lowest_priority()
    root.mkdir(parents=True, exist_ok=True)
    with WriterLock(root):
        store = EvidenceStore(root, stream_cap=args.stream_cap_bytes)
        reader = PublicReader(store, timeout=args.request_timeout_seconds)
        stream, trades = PublicStream(store), PublicStream(store, trades_only=True)
        start = time.monotonic()
        deadline = start + args.duration_seconds if args.duration_seconds else float("inf")
        state = {"schema_version": SCHEMA, "started_at_utc": utc_now().isoformat(),
                 "pid": os.getpid(), "dry_run": args.dry_run, "cycles": 0, "failed_cycles": 0,
                 "state": "STARTING", "priority": "idle", "root": str(root)}
        state["source_sha256"] = {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                  for name, module in tuple(sys.modules.items())
                                  if name.startswith("weather.") and getattr(module, "__file__", None)}
        state["source_sha256"]["weather.market.maker_evidence_capture"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        compression_stop = threading.Event()
        compression_thread = None
        def compress():
            try:
                store.maintenance(compression_stop)
            except Exception as exc:
                state["compression_error"] = type(exc).__name__
                store.event("compression_error", {"error_type": type(exc).__name__})
        def status():
            state.update(updated_at_utc=utc_now().isoformat(), elapsed_seconds=time.monotonic() - start,
                         http=reader.metrics(), stream=stream.metrics(), trades=trades.metrics(),
                         stream_retained_bytes_today=store.stream_bytes, stream_capped=store.stream_capped,
                         journal_bytes_written=store.bytes_written,
                         raw_working_bytes=store.raw_bytes, peak_raw_working_bytes=store.peak_raw_bytes,
                         raw_working_limit_bytes=store.max_raw_bytes)
            atomic_json(root / "status.json", state)
        specs = all_specs()
        status()
        universe = []
        update_checked_at, prior_window_end = utc_now(), None
        def reconcile_updates(band):
            nonlocal update_checked_at, prior_window_end
            now = utc_now()
            if prior_window_end is not None and state.get("update_stream_enabled"):
                state["update_window_active_seconds"] = state.get("update_window_active_seconds", 0.) + max(
                    0., (min(now, prior_window_end) - update_checked_at).total_seconds())
            update_checked_at = now
            try:
                ids, end = update_window(args.extra_conditions, utc_now())
            except Exception:
                stream.stop()
                raise
            update_tokens = [token for row in universe if row["condition_id"] in ids for token in row["tokens"]]
            if band in ("red", "critical") or store.stream_capped:
                update_tokens, end = [], None
            stream.replace_window(update_tokens, end)
            prior_window_end = end
            state.update(update_conditions=[row["condition_id"] for row in universe if row["condition_id"] in ids],
                         update_window_end_utc=end.isoformat() if end else None,
                         update_stream_enabled=bool(update_tokens))
        try:
            while time.monotonic() < deadline:
                cycle_start = time.monotonic()
                if state["cycles"] + state["failed_cycles"] and deadline - cycle_start < 55:
                    # Do not start a knowingly incomplete final minute.
                    time.sleep(max(0, deadline - cycle_start))
                    break
                free = store.free_bytes()
                band = disk_band(free)
                state.update(free_bytes=free, disk_band=band)
                if band == "critical":
                    state["state"] = "STOPPED_CRITICAL_DISK"
                    store.event("disk_brake", {"band": band, "free_bytes": free})
                    break
                if args.dry_run and re1_active():
                    state["state"] = "STOPPED_RE1_ACTIVE"
                    break
                if store.failure:
                    state["state"] = "STOPPED_RAW_FOOTPRINT"
                    break
                if band == "red":
                    stream.stop()
                reader.deadline = min(deadline, cycle_start + 55)
                try:
                    universe, shortages, missing = build_universe(reader, specs, now=utc_now(), extras_path=args.extra_conditions)
                    tokens = [token for row in universe for token in row["tokens"]]
                    # Re-read both sides together after ranking, preserving minute snapshot identity.
                    books = get_books(reader, tokens, kind="books")
                    for row in universe:
                        if any(books[t]["market"].lower() != row["condition_id"] for t in row["tokens"]):
                            raise ValueError("selected book condition mismatch")
                    state.update(universe_size=len(universe), shortages=shortages, missing_events=missing)
                    trades.replace(tokens)
                    reconcile_updates(band)
                    state["cycles"] += 1
                    state["state"] = "CAPTURING" if universe else "NO_ELIGIBLE_BANDS"
                except Exception as exc:
                    state["failed_cycles"] += 1
                    state["state"] = "DEGRADED"
                    state["last_error"] = type(exc).__name__ + ": " + str(exc)[:300]
                    if not store.failure:
                        store.event("cycle_error", {"error": state["last_error"]})
                if compression_thread is None or not compression_thread.is_alive():
                    compression_thread = threading.Thread(target=compress, daemon=True)
                    compression_thread.start()
                state["last_cycle_seconds"] = time.monotonic() - cycle_start
                status()
                next_cycle = min(deadline, cycle_start + 60)
                while time.monotonic() < next_cycle:
                    time.sleep(min(5, next_cycle - time.monotonic()))
                    if store.failure:
                        stream.stop()
                        trades.stop()
                        break
                    reconcile_updates(band)
                    status()
            if store.failure:
                state["state"] = "STOPPED_RAW_FOOTPRINT"
            elif time.monotonic() >= deadline:
                state["state"] = "COMPLETED" if state["cycles"] else "FAILED_NO_CYCLES"
        except BaseException as exc:
            state.update(state="FAILED", last_error=type(exc).__name__)
            raise
        finally:
            compression_stop.set()
            if compression_thread is not None:
                compression_thread.join(timeout=10)
                if compression_thread.is_alive():
                    state["compression_error"] = "cleanup_timeout"
            stream.stop()
            trades.stop()
            reader.close()
            if not store.failure:
                store.event("run_summary", state)
            try:
                store.seal()
                if state.get("disk_band") != "critical":
                    compress_closed_segments(store)
            except Exception as exc:
                state.update(state="FAILED_STORAGE_FINALIZATION", last_error=type(exc).__name__ + ": " + str(exc)[:300])
            state["finished_at_utc"] = utc_now().isoformat()
            status()
        return 0 if state["state"] == "COMPLETED" and state["failed_cycles"] == 0 else 2


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--extra-conditions", type=Path)
    parser.add_argument("--duration-seconds", type=int, default=0, help="0 runs until stopped; dry run requires 1800")
    parser.add_argument("--dry-run", action="store_true", help="30-minute public capture in a NEW scratch root, before 19:45 ET")
    parser.add_argument("--stream-cap-bytes", type=int, default=DEFAULT_STREAM_CAP)
    parser.add_argument("--request-timeout-seconds", type=float, default=5.)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.duration_seconds < 0 or (args.dry_run and args.duration_seconds != 1800):
        parser.error("dry run requires exactly 1800 seconds; duration cannot be negative")
    if not 0 < args.stream_cap_bytes <= 3_000_000_000 or not 0 < args.request_timeout_seconds <= 10:
        parser.error("invalid stream cap or request timeout")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
