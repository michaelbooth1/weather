"""Bounded, offline input staging for the frozen fill-toxicity desk study.

Only caller-named files are read. SQLite sorts venue timestamps and collapses
the existing markout identity without retaining a date's trades/depth in RAM.
Unsupported evidence is an error, never a silently invented observation.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from weather.market import execution_tape_markout as markout
from weather.market import reward_share_estimate as rewards
from weather.market.fill_toxicity_model import Book, Print, StudyError, Terms, event_window, placebo_windows
from weather.units import c_to_native, f_to_native, round_half_up


MAX_LINE_BYTES = 16 * 1024 * 1024


def epoch(value):
    parsed = markout.parse_utc(value)
    return parsed.timestamp() if parsed else None


def json_lines(path):
    """Bound individual records, including decompressed records; never truncate."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        while line := handle.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                raise StudyError(f"record exceeds {MAX_LINE_BYTES} bytes: {path}")
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise StudyError(f"expected JSON object: {path}")
                yield row


def open_store(path):
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA cache_size=-4096;
        PRAGMA temp_store=FILE;
        PRAGMA mmap_size=0;
        CREATE TABLE trades (seq INTEGER PRIMARY KEY, identity TEXT UNIQUE,
            token TEXT, at REAL, price REAL, size REAL, side TEXT);
        CREATE INDEX trades_order ON trades(token, at, seq);
        CREATE TABLE books (seq INTEGER PRIMARY KEY, condition_id TEXT, token TEXT,
            at REAL, bids TEXT, asks TEXT, tick REAL, mid REAL, adjusted REAL);
        CREATE INDEX books_order ON books(condition_id, at, seq);
        CREATE INDEX midpoint_order ON books(token, at, seq);
        CREATE TABLE midpoints (seq INTEGER PRIMARY KEY,token TEXT,at REAL,mid REAL,adjusted REAL);
        CREATE INDEX all_midpoint_order ON midpoints(token,at,seq);
        CREATE TABLE terms (condition_id TEXT, at REAL, rate REAL, minimum REAL,
            spread REAL, priority INTEGER, source TEXT);
        CREATE INDEX terms_order ON terms(condition_id, priority, at);
        CREATE TABLE bands (condition_id TEXT PRIMARY KEY, token TEXT, no_token TEXT,
            label TEXT, kind TEXT, lo REAL, hi REAL);
        CREATE TABLE observations (at REAL, detected REAL, value REAL, routine INTEGER,
            UNIQUE(at, value));
        CREATE TABLE triggers (at REAL, detected REAL, UNIQUE(at, detected));
        CREATE TABLE iem (at REAL PRIMARY KEY, value REAL, routine INTEGER);
        CREATE TABLE bulletins (cycle TEXT PRIMARY KEY, at REAL);
    """)
    return db


def terms_at(db, condition, minute):
    # Source precedence is frozen: per-condition record, else embedded config.
    for priority in (0, 1):
        row = db.execute("""SELECT at,rate,minimum,spread,source FROM terms
            WHERE condition_id=? AND priority=? AND at<=? ORDER BY at DESC LIMIT 1""",
                         (condition, priority, minute)).fetchone()
        if row is not None:
            terms = Terms(*row)
            return terms if terms.usable(minute) else None
    return None


def term_rows(row, captured=None, priority=0):
    """Captured per-condition records, economics snapshots, or embedded configs."""
    own_capture = epoch(row.get("captured_at_utc") or row.get("verified_at_utc"))
    captured = own_capture if own_capture is not None else captured
    for key in ("markets", "bands"):
        if isinstance(row.get(key), list):
            for child in row[key]:
                yield from term_rows(child, captured, priority)
    condition = row.get("condition_id") or row.get("conditionId")
    reward = row.get("liquidity_rewards") or row.get("rewards") or row
    if not condition or captured is None or not isinstance(reward, dict):
        return
    if not any(key in row for key in ("liquidity_rewards", "rewards", "rewardsMinSize", "rewardsMaxSpread",
                                     "rewards_min_size", "min_size", "rate_per_day", "rate")):
        return
    minimum = markout._finite(reward.get("rewards_min_size", reward.get("min_size", row.get("rewardsMinSize"))))
    spread = markout._finite(reward.get("rewards_max_spread_cents", reward.get("rewards_max_spread",
        reward.get("max_spread", row.get("rewardsMaxSpread")))))
    rate = markout._finite(reward.get("current_daily_rate_usdc", reward.get("total_daily_rate",
        reward.get("rate_per_day", reward.get("rate")))))
    configs = reward.get("rates", reward.get("rewards_config"))
    if rate is None and isinstance(configs, list):
        rates = [markout._finite(x.get("rate_per_day")) for x in configs]
        if rates and all(x is not None for x in rates):
            rate = sum(rates)
    # Do not turn absent terms into zero. Only complete, captured terms are usable.
    yield (str(condition).lower(), captured, rate, minimum, spread, priority,
           "condition_record" if priority == 0 else "embedded_config")


def stage_terms(db, paths, start, end):
    for path in paths:
        if Path(path).suffix == ".json":
            if Path(path).stat().st_size > MAX_LINE_BYTES:
                raise StudyError("reward JSON exceeds bounded record size")
            with open(path, encoding="utf-8-sig") as handle:
                rows = [json.load(handle)]
        else:
            rows = json_lines(path)
        for row in rows:
            for terms in term_rows(row):
                if start - 3600 <= terms[1] < end:
                    db.execute("INSERT INTO terms VALUES (?,?,?,?,?,?,?)", terms)
    db.commit()


def stage_books(db, path, counters):
    for raw in json_lines(path):
        malformed_before = counters.get("malformed_levels", 0)
        sample = rewards.sample_from_raw_record(raw, counters)
        if sample is None:
            raise StudyError("unrecognized full-depth book record")
        if counters.get("malformed_levels", 0) != malformed_before:
            raise StudyError("malformed depth levels cannot be silently removed")
        token = raw.get("token") or {}
        condition = sample["condition_id"]
        token_id = str(raw.get("clob_token_id") or raw.get("book", {}).get("asset_id") or "")
        if not token_id:
            raise StudyError("book token identity missing")
        if sample["outcome"] not in ("yes", "no"):
            raise StudyError("book outcome missing")
        at = epoch(sample["captured_at_utc"])
        if at is None or sample["tick"] is None or sample["tick"] <= 0:
            raise StudyError("book capture time or venue tick missing")
        bid, ask = rewards.best_prices(sample["bids"], sample["asks"])
        mid = (bid + ask) / 2 if bid is not None and ask is not None and bid <= ask else None
        terms = terms_at(db, condition, math.floor(at / 60) * 60)
        adjusted = None
        if terms:
            b, a = rewards.best_prices(sample["bids"], sample["asks"], terms.minimum)
            if b is not None and a is not None and b < a:
                adjusted = (b + a) / 2
        db.execute("INSERT INTO midpoints(token,at,mid,adjusted) VALUES (?,?,?,?)", (token_id, at, mid, adjusted))
        if sample["outcome"] == "no":
            db.execute("INSERT INTO bands(condition_id,no_token) VALUES (?,?) ON CONFLICT(condition_id) DO UPDATE SET no_token=excluded.no_token",
                       (condition, token_id))
            continue
        lo = markout._finite(token.get("bin_value"))
        hi = markout._finite(token.get("bin_value_hi"))
        if lo is None or token.get("bin_kind") not in ("eq", "lte", "gte"):
            raise StudyError("band edges missing from captured token metadata")
        hi = lo if hi is None else hi
        db.execute("""INSERT INTO bands(condition_id,token,label,kind,lo,hi) VALUES (?,?,?,?,?,?)
            ON CONFLICT(condition_id) DO UPDATE SET token=excluded.token,label=excluded.label,
            kind=excluded.kind,lo=excluded.lo,hi=excluded.hi""",
                   (condition, token_id, token.get("range_label"), token["bin_kind"], lo, hi))
        db.execute("INSERT INTO books(condition_id,token,at,bids,asks,tick,mid,adjusted) VALUES (?,?,?,?,?,?,?,?)",
                   (condition, token_id, at, json.dumps(sample["bids"]), json.dumps(sample["asks"]),
                    sample["tick"], mid, adjusted))
        counters["book_records"] = counters.get("book_records", 0) + 1
    db.commit()


def stage_trades(db, paths, start, end, counters):
    for path in paths:
        for raw in json_lines(path):
            trade, reason = markout.parse_trade_line(json.dumps(raw))
            if trade is None:
                raise StudyError(f"invalid execution record: {reason}")
            if not start <= trade["epoch_seconds"] < end:
                counters["trades_outside_local_day"] = counters.get("trades_outside_local_day", 0) + 1
                continue
            identity = json.dumps(trade["identity"]) if trade["has_transaction_hash"] else None
            cur = db.execute("INSERT OR IGNORE INTO trades(identity,token,at,price,size,side) VALUES (?,?,?,?,?,?)",
                             (identity, trade["token"], trade["epoch_seconds"], trade["price"],
                              trade["size"], trade["recorded_side"]))
            if cur.rowcount == 0:
                counters["duplicate_identities"] = counters.get("duplicate_identities", 0) + 1
    db.commit()


def iter_books(db, condition):
    for at, bids, asks, tick in db.execute(
            "SELECT at,bids,asks,tick FROM books WHERE condition_id=? ORDER BY at,seq", (condition,)):
        yield Book(at, tuple(map(tuple, json.loads(bids))), tuple(map(tuple, json.loads(asks))), tick)


def iter_prints(db, token, no_token=None):
    for outcome, at, price, size in db.execute("SELECT token,at,price,size FROM trades WHERE token IN (?,?) ORDER BY at,seq", (token, no_token)):
        yield Print(at, price if outcome == token else 1 - price, size)


def midpoint(db, token, at, *, adjusted=False, before=False):
    column = "adjusted" if adjusted else "mid"
    relation, order = ("<=", "DESC") if before else (">=", "ASC")
    row = db.execute(f"SELECT at,{column} FROM midpoints WHERE token=? AND at{relation}? AND {column} IS NOT NULL ORDER BY at {order},seq LIMIT 1",
                     (token, at)).fetchone()
    return row[1] if row and abs(row[0] - at) <= markout.DEFAULT_TOLERANCE_SECONDS else None


def coverage(summary, gaps, status, start, end, *, target_date=None):
    expected = int(math.ceil((end - start) / 60))
    covered = bytearray(expected)
    opener = gzip.open if Path(summary).suffix == ".gz" else open
    with opener(summary, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            at = epoch(row.get("captured_at_utc"))
            if at is not None and start <= at < end:
                covered[int((at - start) // 60)] = 1
    intervals, has_record = {}, False
    for path in gaps:
        for row in json_lines(path):
            a = epoch(row.get("disconnected_at_utc"))
            b = epoch(row.get("reconnected_at_utc"))
            if a is None:
                raise StudyError("gap record has no disconnection time")
            key = row.get("gap_id")
            if not key:
                raise StudyError("gap record has no identity")
            old = intervals.get(key)
            if old is None or b is not None:
                intervals[key] = (a, end if b is None else b)
            if a < end and (b is None or b >= start):
                has_record = True
    if status and Path(status).is_file():
        with open(status, encoding="utf-8-sig") as handle:
            row = json.load(handle)
        date = target_date or datetime.fromtimestamp(start, timezone.utc).date().isoformat()
        # Status identity is checked by the caller's event date as well.
        has_record = has_record or bool(row.get("target_date") == date)
        if row.get("open_gap"):
            gap = row["open_gap"]
            a = epoch(gap.get("disconnected_at_utc"))
            if a is not None:
                intervals.setdefault(gap.get("gap_id"), (a, end))
    dark = bytearray(expected)
    for a, b in intervals.values():
        if b > start and a < end:
            # Any overlap makes a minute dark: conservative sub-minute convention.
            lo = max(0, math.floor((a - start) / 60))
            hi = min(expected, math.ceil((b - start) / 60))
            dark[lo:hi] = b"\1" * (hi - lo)
    reasons = []
    if not has_record:
        reasons.append("no_execution_gap_or_status_record")
    if sum(dark) / expected > .05:
        reasons.append("tape_gap_minutes_above_5_percent")
    if sum(covered) / expected < .90:
        reasons.append("book_coverage_below_90_percent")
    return {"expected_minutes": expected, "book_minutes": sum(covered),
            "tape_gap_minutes": sum(dark), "exclusions": reasons}


def _temperature(row, native_unit):
    # These are the normalized captured fields, including legacy native *_c names.
    for key in ("temp_native", "temperature_native", "target_temp_native", "temp_c", "target_temp_c"):
        if markout._finite(row.get(key)) is not None:
            return float(row[key])
    for key in ("temp", "temperature"):
        if markout._finite(row.get(key)) is not None:
            unit = str(row.get("unit") or native_unit).upper()
            value = float(row[key])
            return f_to_native(value, native_unit) if unit == "F" else c_to_native(value, native_unit)
    if markout._finite(row.get("temp_f")) is not None:
        return f_to_native(row["temp_f"], native_unit)
    return None


def stage_weather(db, paths, triggers, spec, start, end):
    """Normalized sources in native captured replay inputs; never model replay."""
    for path in paths:
        for row in json_lines(path):
            captured = epoch(row.get("captured_at_utc"))
            if captured is None:
                raise StudyError("snapshot capture time missing")
            sources = row.get("sources") or {}
            source = "wu_history" if spec.id == "toronto" else "metar"
            item = sources.get(source) or {}
            data = item.get("data") or {}
            observations = data.get("rows") or data.get("reports") or ([data] if source == "metar" else [])
            for observation in observations:
                if observation.get("station_id") not in (None, spec.icao):
                    raise StudyError("captured station identity does not match the named market")
                at = epoch(observation.get("report_time") or observation.get("datetime") or observation.get("time"))
                value = _temperature(observation, spec.unit)
                if at is None or value is None or not start <= at < end:
                    continue
                minute = datetime.fromtimestamp(at, timezone.utc).minute
                routine = source == "wu_history" or (51 <= minute <= 59 and
                    not str(observation.get("raw") or observation.get("raw_ob") or observation.get("raw_metar") or "").startswith("SPECI"))
                db.execute("""INSERT INTO observations VALUES (?,?,?,?) ON CONFLICT(at,value)
                    DO UPDATE SET detected=min(detected,excluded.detected)""",
                           (at, captured, round_half_up(value), int(routine)))
            for name, item in sources.items():
                if "nbm" not in name:
                    continue
                data = item.get("data") or {}
                at = epoch(data.get("provider_update_time")) or epoch(item.get("fetched_at")) or epoch(data.get("fetched_at"))
                if at is not None and start - 86400 <= at < end:
                    issue = epoch(data.get("provider_issue_time") or data.get("issued_at"))
                    utc = datetime.fromtimestamp(issue if issue is not None else at, timezone.utc)
                    if utc.hour in (1, 7, 13, 19):
                        cycle = utc.replace(minute=0, second=0, microsecond=0).isoformat()
                        db.execute("INSERT INTO bulletins VALUES (?,?) ON CONFLICT(cycle) DO UPDATE SET at=min(at,excluded.at)", (cycle, at))
            for terms in term_rows(row, priority=1):
                if start - 3600 <= terms[1] < end:
                    db.execute("INSERT INTO terms VALUES (?,?,?,?,?,?,?)", terms)
    for path in triggers:
        for row in json_lines(path):
            nested = (row.get("trigger_context") or {}).get("triggers") or row.get("triggers") or [row]
            for trigger in nested:
                if trigger.get("market_id") not in (None, spec.id):
                    continue
                if trigger.get("reason") not in ("wu_history_high_increased", "metar_temp_bucket_crossed"):
                    continue
                at, detected = epoch(trigger.get("observed_at")), epoch(trigger.get("current_captured_at_utc"))
                if at is not None and start <= at < end:
                    db.execute("INSERT OR IGNORE INTO triggers VALUES (?,?)", (at, detected))
    db.commit()


def stage_iem(db, paths, spec, start, end):
    """Offline IEM CSV fallback only; never relabel it as captured E3 evidence.

    Accept the repository adapter's UTC `valid` and Celsius `tmpc` columns.
    No detection timestamp is manufactured for an external reconstruction.
    """
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                station = str(row.get("station") or "").upper()
                if station not in (spec.icao, spec.icao.removeprefix("K")):
                    raise StudyError("IEM station identity does not match the named market")
                try:
                    valid = datetime.fromisoformat(str(row.get("valid") or "").replace("Z", "+00:00"))
                    if valid.tzinfo is None:
                        valid = valid.replace(tzinfo=timezone.utc)
                    at = valid.timestamp()
                except ValueError:
                    at = None
                temp = markout._finite(row.get("tmpc"))
                if at is None or temp is None:
                    continue
                if start <= at < end:
                    value = c_to_native(temp, spec.unit)
                    minute = datetime.fromtimestamp(at, timezone.utc).minute
                    routine = 51 <= minute <= 59 and not str(row.get("metar") or "").startswith("SPECI")
                    old = db.execute("SELECT value FROM iem WHERE at=?", (at,)).fetchone()
                    if old is not None and old[0] != value:
                        raise StudyError("conflicting IEM temperatures at the same report time")
                    db.execute("INSERT OR IGNORE INTO iem VALUES (?,?,?)", (at, value, int(routine)))
    db.commit()


def reconstruct_e2(db):
    """Declared IEM proxy: running-high increases or native rounded bucket changes."""
    db.execute("DELETE FROM triggers")
    previous, maximum, count = None, -math.inf, 0
    for at, value in db.execute("SELECT at,value FROM iem ORDER BY at"):
        if previous is not None and (value > maximum or round_half_up(value) != round_half_up(previous)):
            db.execute("INSERT OR IGNORE INTO triggers VALUES (?,NULL)", (at,))
            count += 1
        previous, maximum = value, max(maximum, value)
    if previous is None:
        raise StudyError("lost E2 retention requires a named offline IEM CSV reconstruction")
    return count


def windows_for_event(db, spec, start, end, *, station_minute=None, reconstruct_triggers=False):
    if db.execute("SELECT count(*) FROM observations").fetchone()[0] > 100_000:
        raise StudyError("observation cardinality exceeds bounded event budget; no partial result")
    observations = list(db.execute("SELECT at,min(detected),value,routine FROM observations GROUP BY at,value ORDER BY at"))
    if not observations:
        raise StudyError("E3 requires the own-snapshot stream under Clarification 6; IEM cannot replace it")
    windows = []
    if spec.id == "toronto":
        routine_minute = None
        windows.extend(event_window("E1", row[0], row[1]) for row in observations)
    else:
        counts = Counter(datetime.fromtimestamp(row[0], timezone.utc).minute for row in observations if row[3])
        if not counts:
            raise StudyError("routine station report minute is unmeasured")
        maximum = max(counts.values())
        modes = [minute for minute, count in counts.items() if count == maximum]
        if len(modes) != 1 and station_minute is None:
            raise StudyError("routine station report minute has tied modes; window choice requires clarification")
        routine_minute = station_minute if station_minute is not None else modes[0]
        # Measured modal minute in every local hour of this closed event day.
        for hour in range(int(math.ceil((end - start) / 3600))):
            windows.append(event_window("E1", start + hour * 3600 + routine_minute * 60))
    reconstructed_count = reconstruct_e2(db) if reconstruct_triggers else None
    for at, detected in db.execute("SELECT at,detected FROM triggers ORDER BY at,detected"):
        windows.append(event_window("E2", at, detected))
    for condition, kind, upper in db.execute("SELECT condition_id,kind,hi FROM bands ORDER BY condition_id"):
        if kind == "gte":
            continue
        for at, detected, value, routine in observations:
            if routine and value > upper:
                windows.append(event_window("E3", at, detected, condition))
                break
    windows.extend(w for row in db.execute("SELECT at FROM bulletins ORDER BY at")
                   if (w := event_window("E4", row[0])).end > start and w.start < end)
    day = math.floor(start / 86400) * 86400
    for offset in (-86400, 0, 86400):
        for hour in (0, 6, 12, 18):
            at = day + offset + hour * 3600 + 210 * 60
            if start <= at < end:
                windows.append(event_window("E5", at))
    placebo, dropped = placebo_windows(windows, spec.tz)
    detected = [replace(event_window("E2", w.detected), kind="E2_DETECTED")
                for w in windows if w.kind == "E2" and w.detected is not None]
    return windows + placebo + detected, {"routine_metar_minute": routine_minute, "dropped_placebos": dropped,
        "E2_source": "IEM_RECONSTRUCTION" if reconstruct_triggers else "captured_observation_triggers",
        "E2_reconstructed_events": reconstructed_count}
