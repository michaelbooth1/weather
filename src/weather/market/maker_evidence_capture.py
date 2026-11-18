"""Passive maker evidence: public books, reward changes, raw updates and trades.

No account, SDK, credential, dotenv or order modules are imported. A dry run
uses a new scratch directory and is forcibly bounded before 19:45 Eastern.

Data layer v2 S2+S9: per-condition reward records are read on change
(``weather.market.maker_evidence_rewards``), journals fsync in one-second groups,
and the recorder-only rows of ``config/capture_families.json``
(``weather.market.maker_evidence_pilot``) are captured in their own ``pilot``
partitions after the built-ins, which stay on ``all_specs()``. Built-in bands keep the
pre-S9 every-minute reward read (``read_every_cycle``) unless the config selects
``event_driven`` and the 88a panel hold has ended (UTC 2026-10-31); pilot and sweep land off.
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
import shutil
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
    DEFAULT_STREAM_CAP, GROUP_FSYNC_SECONDS, SCHEMA, EvidenceStore, JournalSyncFailure, WriterLock,
    RawFootprintLimit, atomic_json, disk_band, digest, encoded, utc_now, write_status,
)
from weather.market.maker_evidence_archive import compress_closed_segments
from weather.market.maker_evidence_family import family_universe, load_family
from weather.market.maker_evidence_pilot import (
    FAMILY_CONFIG, PILOT_PARTITION, STRATUM, built_ins_event_driven, load_recorder_only, pilot_slug,
    universe_partition,
)
from weather.market.maker_evidence_rewards import RewardSweep, RewardTrigger
from weather.market.maker_evidence_stream import PublicStream
from weather.paths import data_path

DEFAULT_ROOT = data_path("maker_evidence")
# Default path only (plan addendum 3): no task-argument change; re-read every cycle.
RECORDER_ONLY_CONFIG = FAMILY_CONFIG
# The raw-footprint latch stops the writer at MAX_RAW_BYTES; status warns from this fraction.
LATCH_WARN_FRACTION = 0.5


def read_every_cycle(reader, rows, today):
    """Pre-S9 reward retention: the full per-condition record for every selected band, every call."""
    for row in rows:
        row["clob_reward_content_sha256"] = digest(encoded(reward_record(reader, row["condition_id"])))


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


def get_books(reader, tokens, *, kind, partition=None):
    books = {}
    wanted = list(dict.fromkeys(tokens))
    for start in range(0, len(wanted), 100):
        batch = wanted[start:start + 100]
        rows = reader.read(CLOB + "/books", body=[{"token_id": token} for token in batch], kind=kind,
                           partition=partition)
        rows = unique_rows(rows, key="asset_id", on_duplicate=lambda token:
                           reader.store.event("duplicate", {"source": "books", "token_id": token}))
        if {str(row["asset_id"]) for row in rows} != set(batch):
            raise ValueError("book batch token coverage mismatch")
        books.update((str(row["asset_id"]), row) for row in rows)
    return books


def discover_events(reader, expected, *, partition=None):
    """Active YES/NO conditions of the requested event slugs ({slug: (city, day_ahead)})."""
    all_events = []
    slugs = list(expected)
    for start in range(0, len(slugs), 12):
        for page in range(10):
            events = reader.read(GAMMA + "/events", params=[("slug", slug) for slug in slugs[start:start + 12]]
                                 + [("limit", 100), ("offset", page * 100)], kind="discovery",
                                 partition=partition)
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
    return discovered, missing


def build_universe(reader, specs, *, now, extras_path=None, rewards=read_every_cycle, pilot=None):
    """Rank and select one lane: the built-ins (``pilot=None``) or the recorder-only rows.

    ``pilot`` is a ``RecorderOnlyConfig``: its markets replace ``specs`` and every read and
    universe event lands in a ``pilot`` partition. ``rewards(reader, rows, today)`` sets each
    selected row's retained CLOB reward record identity.
    """
    partition = PILOT_PARTITION if pilot is not None else None
    if pilot is not None:
        specs = pilot.markets
        expected = {pilot_slug(market, now.astimezone(market.tz).date() + timedelta(days=day)): (market.id, day)
                    for market in specs for day in range(3)}
    else:
        expected = {event_slug_for_date(now.astimezone(spec.tz).date() + timedelta(days=day), spec.id): (spec.id, day)
                    for spec in specs for day in range(3)}
    discovered, missing = discover_events(reader, expected, partition=partition)
    extra_ids = load_extras(extras_path) if pilot is None else []
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
    books = get_books(reader, [row["tokens"][0] for row in eligible], kind="ranking_books", partition=partition)
    for row in eligible:
        book = books[row["tokens"][0]]
        if book["market"].lower() != row["condition_id"]:
            raise ValueError("ranking book condition mismatch")
        row["modelled_reward_20"] = modelled_reward(book, row["reward"], today)
    selected, shortages = select_universe(eligible, extras=extras)
    # Gamma supplies current reward eligibility for discovery/ranking. The full
    # per-condition CLOB record is retained by ``rewards`` (S9: on change, not every cycle).
    rewards(reader, selected, today)
    for row in selected:
        reward = row.pop("reward", None)
        row["ranking_terms"] = ({"daily_rate": reward_rate(reward, today),
                                 "min_size": reward["rewards_min_size"],
                                 "max_spread_cents": reward["rewards_max_spread"]} if reward else None)
    present = {row["city"] for row in eligible}
    for spec in specs:
        if spec.id not in present:
            shortages.extend({"city": spec.id, "day_ahead": day, "available": 0} for day in range(3))
    tag = {"lane": PILOT_PARTITION, "stratum": STRATUM, "config_sha256": pilot.config_sha256} if pilot else {}
    for row in selected:
        row.update(tag)
    for city in sorted({spec.id for spec in specs} | {row["city"] for row in selected}):
        reader.store.event("universe", {"city": city, "bands": [row for row in selected if row["city"] == city],
                                      "shortages": [row for row in shortages if row["city"] == city],
                                      "missing_events": sorted(slug for slug in missing if expected[slug][0] == city),
                                      "candidate_count": sum(row["city"] == city for row in eligible),
                                      "ranking": "20 shares, 1 cent outward, size-cutoff midpoint, share_many", **tag},
                           partition=universe_partition(city) if pilot else city)
    return selected, shortages, sorted(missing)


def lane_rewards(trigger, sweep, sweep_enabled, partition):
    """The S9 ``rewards`` hook for one lane: change-triggered reads within the shared cycle budget."""
    def annotate(reader, rows, today):
        fresh = sweep_enabled and sweep.fresh()
        trigger.refresh([(partition, rows)], sweep.state if fresh else {}, fresh, today=today)
    return annotate


def retain_sweep_rows(store, sweep, sweep_enabled, rows, partition):
    """Change-only ``rewards_current`` rows for selected bands (a full baseline in every segment)."""
    if sweep_enabled and sweep.fresh():
        store.record_changed("rewards_current", {row["condition_id"]: sweep.rows[row["condition_id"]]
                                                 for row in rows if row["condition_id"] in sweep.rows},
                             partition=partition)


def load_recorder_only_safely(store, pilot_state, path=None):
    """Re-read the block every cycle; an error turns the pilot off and never touches the built-ins."""
    try:
        config = load_recorder_only(RECORDER_ONLY_CONFIG if path is None else path)
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)[:300]
        if pilot_state.get("config_error") != error:
            store.event("recorder_only_config_error", {"error": error})
        pilot_state.update(state="CONFIG_ERROR", config_error=error, markets=[], universe_size=0)
        return None
    if pilot_state.get("config_sha256") != config.config_sha256:
        store.event("recorder_only_config", {"config_sha256": config.config_sha256,
                                             "markets": [market.id for market in config.markets],
                                             "pilot": config.pilot, "rewards_sweep": config.rewards_sweep,
                                             "built_in_reward_cadence": config.built_in_reward_cadence})
    pilot_state.update(config_sha256=config.config_sha256, config_error=None,
                       markets=[market.id for market in config.active_markets], pilot=config.pilot,
                       rewards_sweep=config.rewards_sweep)
    return config


def built_in_reward_hook(config, trigger, sweep, sweep_enabled, now, *, dry_run=False):
    """Legacy every-minute reads for built-ins unless event-driven is configured and allowed."""
    if built_ins_event_driven(config, now, dry_run=dry_run):
        return lane_rewards(trigger, sweep, sweep_enabled, None), True
    return read_every_cycle, False


def capture_recorder_only(reader, store, config, trigger, sweep, sweep_enabled, trades, pilot_state):
    """One pilot cycle: ranking, books, change-triggered rewards and public trades, all in ``pilot``.

    Pilot tokens never join the raw update stream (extras only), so the daily stream cap is
    not diluted. Errors are the pilot's own: counted, journaled, and the built-ins continue.
    """
    if config is None or not config.active_markets:
        trades.stop()
        if config is not None:
            pilot_state.update(state="OFF", universe_size=0)
        return []
    try:
        universe, shortages, missing = build_universe(
            reader, (), now=utc_now(), pilot=config,
            rewards=lane_rewards(trigger, sweep, sweep_enabled, PILOT_PARTITION))
        retain_sweep_rows(store, sweep, sweep_enabled, universe, PILOT_PARTITION)
        tokens = [token for row in universe for token in row["tokens"]]
        books = get_books(reader, tokens, kind="books", partition=PILOT_PARTITION)
        for row in universe:
            if any(books[t]["market"].lower() != row["condition_id"] for t in row["tokens"]):
                raise ValueError("selected pilot book condition mismatch")
        trades.replace(tokens)
        pilot_state["cycles"] += 1
        pilot_state.update(state="CAPTURING" if universe else "NO_ELIGIBLE_BANDS", universe_size=len(universe),
                           shortages=shortages, missing_events=missing, last_error=None)
        return universe
    except Exception as exc:  # A latched store limit is seen by the main loop's failure check.
        pilot_state["failed_cycles"] += 1
        pilot_state.update(state="DEGRADED", last_error=type(exc).__name__ + ": " + str(exc)[:300])
        if not store.failure:
            store.event("recorder_only_cycle_error", {"error": pilot_state["last_error"]})
        return []


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
    family = load_family(args.family) if args.family else None
    root = (args.root or (family.root if family else DEFAULT_ROOT)).resolve()
    core = DEFAULT_ROOT.resolve()
    if family and (root == core or core in root.parents or root in core.parents):
        raise ValueError("a capture family never writes inside or above the 88a root")
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
        if family and shutil.disk_usage(root).free < family.floor_bytes:
            # Below its floor a family opens no journal; each one-minute retry only refreshes status.
            atomic_json(root / "status.json", {"schema_version": SCHEMA, "family": family.id,
                        "state": "STOPPED_FAMILY_DISK_FLOOR", "free_bytes": shutil.disk_usage(root).free,
                        "family_floor_bytes": family.floor_bytes, "updated_at_utc": utc_now().isoformat()})
            return 2
        # Grouped fsync is the core recorder's (S2); capture families keep per-record fsync.
        store = EvidenceStore(root, stream_cap=args.stream_cap_bytes, group_fsync=family is None)
        reader = PublicReader(store, timeout=args.request_timeout_seconds)
        stream, trades = PublicStream(store), PublicStream(store, trades_only=True)
        pilot_trades = PublicStream(store, trades_only=True, partition=PILOT_PARTITION)
        sweep, trigger = RewardSweep(reader), RewardTrigger(reader)
        pilot_state = {"state": "OFF", "stratum": STRATUM, "cycles": 0, "failed_cycles": 0, "markets": [], "universe_size": 0}
        sweep_switch = {"enabled": False, "built_in_cadence": "legacy"}
        recorder_only_path = getattr(args, "recorder_only_config", None)
        start = time.monotonic()
        deadline = start + args.duration_seconds if args.duration_seconds else float("inf")
        state = {"schema_version": SCHEMA, "started_at_utc": utc_now().isoformat(),
                 "pid": os.getpid(), "dry_run": args.dry_run, "cycles": 0, "failed_cycles": 0,
                 "state": "STARTING", "priority": "idle", "root": str(root)}
        if family:
            state.update(family=family.id, family_config_sha256=family.config_sha256,
                         family_floor_bytes=family.floor_bytes, websocket="none")
        reward_state = {}
        state["source_sha256"] = {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                  for name, module in tuple(sys.modules.items())
                                  if name.startswith("weather.") and getattr(module, "__file__", None)}
        state["source_sha256"]["weather.market.maker_evidence_capture"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        compression_stop = threading.Event()
        compression_thread = None
        flush_stop = threading.Event()
        def flush():
            while not flush_stop.wait(GROUP_FSYNC_SECONDS):
                try:
                    store.sync()
                except JournalSyncFailure:
                    return  # The store latched its failure; the main loop stops on it.
        flush_thread = None
        if store.group_fsync:
            flush_thread = threading.Thread(target=flush, daemon=True)
            flush_thread.start()
        def stopped_state():
            return "STOPPED_STORAGE_FAILURE" if store.failure == "journal fsync failed" else "STOPPED_RAW_FOOTPRINT"
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
                         raw_working_limit_bytes=store.max_raw_bytes,
                         raw_working_fraction=store.peak_raw_bytes / store.max_raw_bytes,
                         raw_working_warn_fraction=LATCH_WARN_FRACTION, storage=store.sync_metrics())
            if family is None:
                state.update(pilot_trades=pilot_trades.metrics(), recorder_only=dict(pilot_state),
                             rewards={"sweep_enabled": sweep_switch["enabled"],
                                      "built_in_cadence": sweep_switch["built_in_cadence"],
                                      "sweep": sweep.metrics(), "trigger": trigger.metrics()})
            write_status(store, root / "status.json", state)
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
                if family and free < family.floor_bytes:
                    state["state"] = "STOPPED_FAMILY_DISK_FLOOR"
                    store.event("disk_brake", {"band": band, "free_bytes": free, "family_floor_bytes": family.floor_bytes})
                    break
                if args.dry_run and re1_active():
                    state["state"] = "STOPPED_RE1_ACTIVE"
                    break
                if store.failure:
                    state["state"] = stopped_state()
                    break
                if band == "red":
                    stream.stop()
                reader.deadline = min(deadline, cycle_start + 55)
                recorder_only = None
                if family is None:
                    trigger.begin_cycle()
                    try:
                        recorder_only = load_recorder_only_safely(store, pilot_state, path=recorder_only_path)
                        sweep_switch["enabled"] = bool(recorder_only and recorder_only.sweep_enabled)
                        if sweep_switch["enabled"]:
                            sweep.step()  # Isolated: a sweep failure is journaled and never fails the cycle.
                    except Exception as exc:  # Only a latched store limit reaches here.
                        state["last_error"] = type(exc).__name__ + ": " + str(exc)[:300]
                try:
                    if family:
                        universe, shortages, missing = family_universe(reader, family, now=utc_now(),
                                                                       reward_state=reward_state, discover=discover_events)
                    else:
                        built_in_rewards, event_driven = built_in_reward_hook(
                            recorder_only, trigger, sweep, sweep_switch["enabled"], utc_now(), dry_run=args.dry_run)
                        sweep_switch["built_in_cadence"] = "event_driven" if event_driven else "legacy"
                        universe, shortages, missing = build_universe(
                            reader, specs, now=utc_now(), extras_path=args.extra_conditions, rewards=built_in_rewards)
                        if event_driven:
                            retain_sweep_rows(store, sweep, sweep_switch["enabled"], universe, None)
                    tokens = [token for row in universe for token in row["tokens"]]
                    # Re-read both sides together after ranking, preserving minute snapshot identity.
                    books = get_books(reader, tokens, kind="books")
                    for row in universe:
                        if any(books[t]["market"].lower() != row["condition_id"] for t in row["tokens"]):
                            raise ValueError("selected book condition mismatch")
                    state.update(universe_size=len(universe), shortages=shortages, missing_events=missing)
                    if family is None:  # Families are books and reward terms only: no websocket.
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
                if family is None and not store.failure:
                    # After the built-ins, in its own error scope: the pilot never fails a core cycle.
                    capture_recorder_only(reader, store, None if band == "red" else recorder_only, trigger, sweep,
                                          sweep_switch["enabled"], pilot_trades, pilot_state)
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
                        pilot_trades.stop()
                        break
                    if family is None:
                        reconcile_updates(band)
                    status()
            if store.failure:
                state["state"] = stopped_state()
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
            pilot_trades.stop()
            flush_stop.set()
            if flush_thread is not None:
                flush_thread.join(timeout=10)
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
    parser.add_argument("--root", type=Path, help="default data/maker_evidence, or the family's own root")
    parser.add_argument("--extra-conditions", type=Path)
    parser.add_argument("--family", help="capture a config/capture_families.json family in its own root")
    parser.add_argument("--duration-seconds", type=int, default=0, help="0 runs until stopped; dry run requires 1800")
    parser.add_argument("--dry-run", action="store_true",
                        help="30-90 minute public capture in a NEW scratch root, before 19:45 ET")
    parser.add_argument("--recorder-only-config", type=Path,
                        help="dry run only: a capture_families.json copy to read instead of the default path")
    parser.add_argument("--stream-cap-bytes", type=int, default=DEFAULT_STREAM_CAP)
    parser.add_argument("--request-timeout-seconds", type=float, default=5.)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.duration_seconds < 0 or (args.dry_run and not 1800 <= args.duration_seconds <= 5400):
        parser.error("dry run requires 1800-5400 seconds; duration cannot be negative")
    if args.recorder_only_config and not args.dry_run:
        parser.error("--recorder-only-config is for dry runs; production reads the default path only")
    if not 0 < args.stream_cap_bytes <= 3_000_000_000 or not 0 < args.request_timeout_seconds <= 10:
        parser.error("invalid stream cap or request timeout")
    if args.family and args.extra_conditions:
        parser.error("--extra-conditions belongs to the core recorder, not a capture family")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
