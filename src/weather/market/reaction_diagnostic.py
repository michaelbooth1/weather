"""Competitor-reaction and decidedness-latency diagnostic (mission 111f).

Secondary, pre-registered diagnostic for the maker replay (Clarification 2).
It changes no hurdle, estimator or policy and never reads a quote-panel date.

``reaction``: from RE-1 attended-session journals (our postings, prices, sizes
and reward terms) and 88a sealed books of the same YES token, our modelled
reward share over time since posting, share(t), with its support, and the
implied reward multiplier k = (mean share over the quoting hour) / (share at
posting). The replay's accrual assumes no competitor reaction, i.e. k = 1.
The RE-1 journals' own per-minute ``share_many`` is reported beside it as a
labelled second series; it does not substitute for the 88a overlap.

``latency``: from calibration dates only, the lag from each
``wu_history_high_increased`` trigger capture to the first 88a mid move of at
least one tick on the affected band, and how often that band's mid was already
outside [0.10, 0.90] before the trigger.

Both write one JSON and one Markdown file into a new output directory.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import statistics

from weather.io import rotated_sidecar_paths
from weather.market.live_observation_normalization import band_contains_value
from weather.market.reaction_diagnostic_io import (
    CALIBRATION_DATES, MAX_INPUT_BYTES, MAX_SECONDS, Budget, InputRefused, StopRun, allow_list,
    CAMPAIGN_ROOT, parse_utc, read_bands, read_books, read_journal, read_prediction_hash, read_selection,
    read_triggers, read_universe, session_folders,
)
from weather.market.reward_share_estimate import order_score, parse_levels, q_min, share_of, side_score
from weather.paths import data_path
from weather.schema_registry import schema_version
from weather.units import round_half_up

SCHEMA = schema_version("competitor_reaction_diagnostic")
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20260930
EPISODE_GAP_SECONDS = 60
PRE_WINDOW_SECONDS = 900
NO_REACTION_NOTE = ("The replay credits reward from captured books that never contained our quote: its accrual "
                    "assumes no competitor reaction (k = 1). Quote this measured decay next to any reward result.")


# --------------------------------------------------------------------------
# Shared statistics
# --------------------------------------------------------------------------

def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def weighted_median(pairs):
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= total / 2:
            return value
    return pairs[-1][0]


def crossed_bootstrap(observations, statistic, *, reps=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED):
    """Crossed date x market bootstrap: resample both cluster sets independently.

    ``observations`` are dicts with ``date`` and ``market``; ``statistic`` takes
    ``[(observation, weight)]`` and returns a float or None.
    """
    dates = sorted({o["date"] for o in observations})
    markets = sorted({o["market"] for o in observations})
    support = {"dates": len(dates), "markets": len(markets), "observations": len(observations),
               "method": "crossed date x market bootstrap, weight = date multiplicity x market multiplicity",
               "reps": reps, "seed": seed}
    if len(dates) < 2 or len(markets) < 2:
        return {**support, "ci95": None, "reason": "fewer than two date or market clusters"}
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        wd = defaultdict(int)
        wm = defaultdict(int)
        for _ in dates:
            wd[rng.choice(dates)] += 1
        for _ in markets:
            wm[rng.choice(markets)] += 1
        value = statistic([(o, wd[o["date"]] * wm[o["market"]]) for o in observations])
        if value is not None:
            draws.append(value)
    if len(draws) < reps // 2:
        return {**support, "ci95": None, "reason": "statistic undefined in most resamples"}
    return {**support, "ci95": [quantile(draws, 0.025), quantile(draws, 0.975)], "defined_draws": len(draws)}


# --------------------------------------------------------------------------
# reaction
# --------------------------------------------------------------------------

def _order_id(response):
    if not isinstance(response, dict):
        return ""
    return str(response.get("id") or response.get("order_id") or response.get("orderID") or "")


def parse_session(rows):
    """Postings, cancellations, reward terms and journal shares of one RE-1 session."""
    opened = next((r for r in rows if r.get("event") == "opened"), None)
    scope = (opened or {}).get("scope") or {}
    tokens = [str(t) for t in scope.get("token_ids") or []]
    if not opened or len(tokens) != 2 or not scope.get("condition_id"):
        raise InputRefused("session_scope_missing")
    orders, terms, journal = {}, [], []
    pending = None
    end = parse_utc(rows[-1]["recorded_at_utc"])
    for row in rows:
        when, event = parse_utc(row["recorded_at_utc"]), row.get("event")
        if event == "submit_request":
            pending = row.get("request") or {}
        elif event == "submit_response" and pending is not None:
            response = row.get("response") or {}
            oid = _order_id(response)
            token = str(pending.get("token_id"))
            if oid and response.get("status") == "live" and token in tokens:
                orders[oid] = {"leg": tokens.index(token), "price": float(pending["price"]),
                               "size": float(pending["size"]), "start": when, "end": end}
            pending = None
        elif event in ("cancel_request", "cleanup_cancel_request"):
            oid = str((row.get("request") or {}).get("order_id") or row.get("order_id") or "")
            if oid in orders:
                orders[oid]["end"] = min(orders[oid]["end"], when)
        elif event in ("cleanup_cancel_all_request", "terminal"):
            for order in orders.values():
                order["end"] = min(order["end"], when)
        snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else None
        inputs = (snapshot or {}).get("quote_inputs") or {}
        if "reward_min_size" in inputs and "reward_max_spread_cents" in inputs:
            terms.append((when, float(inputs["reward_min_size"]), float(inputs["reward_max_spread_cents"])))
        if event == "minute" and isinstance(row.get("observation"), dict):
            single = row["observation"].get("share_single")
            journal.append((when, float(row["observation"]["share_many"]),
                            None if single is None else float(single)))
    starts = sorted(o["start"] for o in orders.values())
    episodes = []
    for start in starts:
        if not episodes or (start - episodes[-1]["last_submit"]).total_seconds() > EPISODE_GAP_SECONDS:
            episodes.append({"start": start, "last_submit": start})
        else:
            episodes[-1]["last_submit"] = start
    for index, episode in enumerate(episodes):
        following = episodes[index + 1]["start"] if index + 1 < len(episodes) else end
        live_end = max((o["end"] for o in orders.values() if episode["start"] <= o["start"] < following),
                       default=episode["start"])
        episode["end"] = min(following, live_end)
    return {"condition_id": str(scope["condition_id"]).lower(), "yes_token": tokens[0], "no_token": tokens[1],
            "mode": str(opened.get("mode") or "unknown"),
            "orders": list(orders.values()), "terms": terms, "journal": journal, "episodes": episodes,
            "first": parse_utc(rows[0]["recorded_at_utc"]), "end": end}


def live_quote(session, when):
    """Our live YES bid and NO bid at ``when`` as {leg: (price, size)}."""
    quote = {}
    for order in session["orders"]:
        if order["start"] <= when < order["end"]:
            price, size = quote.get(order["leg"], (order["price"], 0.0))
            quote[order["leg"]] = (order["price"], size + order["size"])
    return quote


def terms_at(session, when):
    current = None
    for moment, minimum, maximum in session["terms"]:
        if moment > when:
            break
        current = (minimum, maximum)
    return current or (session["terms"][0][1:] if session["terms"] else None)


def book_share(book, quote, minimum, maximum):
    """Our modelled share of one displayed YES book, with our own size removed (84b scoring)."""
    bids, _ = parse_levels(book.get("bids"))
    asks, _ = parse_levels(book.get("asks"))
    qualifying_bids = [p for p, s in bids if s >= minimum]
    qualifying_asks = [p for p, s in asks if s >= minimum]
    if not qualifying_bids or not qualifying_asks:
        return None
    mid = (max(qualifying_bids) + min(qualifying_asks)) / 2
    own_levels = {0: None, 1: None}
    visible = True
    sides = []
    for leg, levels in ((0, bids), (1, asks)):
        aggregate = defaultdict(float)
        for price, size in levels:
            aggregate[round(price, 6)] += size
        if leg in quote:
            price, size = quote[leg]
            at = round(price if leg == 0 else 1 - price, 6)
            visible &= aggregate.get(at, 0.0) >= size - 1e-9
            aggregate[at] = max(0.0, aggregate.get(at, 0.0) - size)
            distance = (mid - price) * 100 if leg == 0 else (1 - mid - price) * 100
            own_levels[leg] = order_score(size, distance, maximum, minimum)
        sides.append(side_score([(p, s) for p, s in aggregate.items() if s > 0], mid, maximum, minimum)[0])
    own = q_min(own_levels[0] or 0.0, own_levels[1] or 0.0, mid)
    return {"mid": mid, "share_many": share_of(own, sum(sides) / 2),
            "share_single": share_of(own, q_min(sides[0], sides[1], mid)), "visible": visible}


def episode_samples(session, episode, books, horizon):
    samples = []
    for when, book in books:
        if not episode["start"] <= when < episode["end"]:
            continue
        seconds = (when - episode["start"]).total_seconds()
        if seconds >= horizon * 60 or str(book.get("market", "")).lower() != session["condition_id"]:
            continue
        quote, terms = live_quote(session, when), terms_at(session, when)
        if not quote or terms is None:
            continue
        value = book_share(book, quote, *terms)
        if value is not None:
            samples.append({"seconds": seconds, "share_many": value["share_many"],
                            "share_single": value["share_single"], "visible": value["visible"]})
    return samples


def journal_samples(session, episode, horizon):
    return [{"seconds": (when - episode["start"]).total_seconds(), "share_many": many, "share_single": single,
             "visible": None}
            for when, many, single in session["journal"]
            if episode["start"] <= when < episode["end"]
            and (when - episode["start"]).total_seconds() < horizon * 60]


def summarize_series(episodes, horizon, baseline_seconds):
    """share(t) by whole minute since posting, and the implied multiplier k."""
    bins = defaultdict(list)
    per_episode = []
    for ep in episodes:
        by_minute = defaultdict(list)
        for sample in ep["samples"]:
            minute = int(sample["seconds"] // 60)
            by_minute[minute].append(sample["share_many"])
            bins[minute].append((ep, sample))
        baseline = next((s["share_many"] for s in sorted(ep["samples"], key=lambda s: s["seconds"])
                         if s["seconds"] < baseline_seconds), None)
        hour = [statistics.fmean(v) for v in by_minute.values()]
        row = {"session": ep["session"], "episode": ep["index"], "date": ep["date"], "market": ep["market"],
               "condition_id": ep["condition_id"], "samples": len(ep["samples"]),
               "minutes_covered": len(by_minute), "share_at_posting": baseline,
               "mean_share_over_horizon": statistics.fmean(hour) if hour else None}
        row["k"] = (row["mean_share_over_horizon"] / baseline if baseline and hour else None)
        per_episode.append(row)
    curve = []
    for minute in range(horizon):
        items = bins.get(minute, [])
        values = [s["share_many"] for _, s in items]
        singles = [s["share_single"] for _, s in items if s["share_single"] is not None]
        visible = [s["visible"] for _, s in items if s["visible"] is not None]
        curve.append({"minute": minute, "samples": len(items),
                      "episodes": len({(e["session"], e["index"]) for e, _ in items}),
                      "sessions": len({e["session"] for e, _ in items}),
                      "bands": len({e["condition_id"] for e, _ in items}),
                      "mean_share_many": statistics.fmean(values) if values else None,
                      "median_share_many": statistics.median(values) if values else None,
                      "mean_share_single": statistics.fmean(singles) if singles else None,
                      "own_quote_visible_fraction": (sum(visible) / len(visible) if visible else None)})
    usable = [r for r in per_episode if r["k"] is not None]

    def pooled(weighted):
        top = sum(w * r["mean_share_over_horizon"] for r, w in weighted)
        bottom = sum(w * r["share_at_posting"] for r, w in weighted)
        return top / bottom if bottom else None

    k = pooled([(r, 1) for r in usable]) if usable else None
    return {"curve": curve, "episodes": per_episode,
            "k_pooled": k, "k_median_episode": statistics.median([r["k"] for r in usable]) if usable else None,
            "episodes_with_k": len(usable),
            "k_interval": crossed_bootstrap(usable, pooled) if usable else None,
            "k_definition": ("sum over episodes of mean share over the horizon's covered minutes / sum of share "
                             f"at posting (first sample within {baseline_seconds} s); 1 = no reaction")}


def load_sessions(re1_root, days, budget, *, allow_campaign_root=False):
    """Hash-checked RE-1 sessions; each flagged by whether its UTC span is inside the allow-list."""
    name = Path(re1_root).name
    if "analysis-copy" not in name and not (allow_campaign_root and CAMPAIGN_ROOT.fullmatch(name)):
        raise InputRefused("re1_root_must_be_an_analysis_copy")
    sessions, refused = [], []
    for folder in session_folders(re1_root):
        try:
            rows, digest = read_journal(folder / "journal.jsonl", budget)
            expected = read_prediction_hash(folder, budget)
            if expected is not None and expected != digest:
                raise InputRefused("prediction_journal_hash_mismatch")
            if not rows:
                raise InputRefused("empty_journal")
            session = parse_session(rows)
        except (InputRefused, ValueError, KeyError, TypeError, OSError) as exc:
            refused.append({"session": folder.name, "reason": str(exc) or type(exc).__name__})
            continue
        session["name"] = folder.name
        span = {session["first"].date().isoformat(), session["end"].date().isoformat()}
        session["in_allow_list"] = span <= set(days)
        session["folder"] = folder
        sessions.append(session)
    return sessions, refused


def run_reaction(re1_root, maker_root, days, *, horizon=60, baseline_seconds=120, budget=None):
    budget = budget or Budget()
    sessions, refused = load_sessions(re1_root, days, budget)
    allowed = [s for s in sessions if s["in_allow_list"]]
    universe = read_universe(maker_root, days, budget)
    books = read_books(maker_root, days, [s["yes_token"] for s in allowed], budget)
    maker_eps, journal_eps, overlap = [], [], []
    for session in allowed:
        market = (universe.get(session["condition_id"]) or {}).get("city") or session["condition_id"]
        session_books = books.get(session["yes_token"], [])
        with_books = 0
        for index, episode in enumerate(session["episodes"]):
            base = {"session": session["name"], "index": index, "date": episode["start"].date().isoformat(),
                    "market": market, "condition_id": session["condition_id"]}
            samples = episode_samples(session, episode, session_books, horizon)
            with_books += bool(samples)
            if samples:
                maker_eps.append({**base, "samples": samples})
            journal = journal_samples(session, episode, horizon)
            if journal:
                journal_eps.append({**base, "samples": journal})
        overlap.append({"session": session["name"], "condition_id": session["condition_id"],
                        "first_utc": session["first"].isoformat(), "end_utc": session["end"].isoformat(),
                        "episodes": len(session["episodes"]), "episodes_with_88a_books": with_books,
                        "88a_book_samples_for_token": len(session_books)})
    verdict = "ESTIMATED" if maker_eps else "NO_OVERLAP"
    return {"schema_version": SCHEMA, "command": "reaction", "verdict": verdict, "dates": list(days),
            "note": NO_REACTION_NOTE,
            "falsifier": ("NO_OVERLAP means the RE-1 journals and 88a books do not overlap on the same band and "
                          "time: share(t) is not estimable from 88a and no other source is substituted."),
            "sessions_found": len(sessions) + len(refused), "sessions_refused": refused,
            "sessions_outside_allow_list": [s["name"] for s in sessions if not s["in_allow_list"]],
            "overlap": overlap, "horizon_minutes": horizon, "baseline_seconds": baseline_seconds,
            "series_88a_books": summarize_series(maker_eps, horizon, baseline_seconds),
            "series_re1_journal_books": summarize_series(journal_eps, horizon, baseline_seconds),
            "input": {"bytes": budget.bytes, "coverage": dict(budget.coverage)}}


def run_reaction_re1_only(re1_root, days, *, horizon=60, baseline_seconds=120, budget=None,
                          allow_campaign_root=False):
    """share(t) from the RE-1 journals' own per-minute ``share_many`` samples; no 88a input.

    The output is aggregate only: bands are relabelled ``band-N`` and no
    condition, token, order or wallet identifier is emitted.
    """
    budget = budget or Budget()
    sessions, refused = load_sessions(re1_root, days, budget, allow_campaign_root=allow_campaign_root)
    labels, episodes, listed, modes = {}, [], [], defaultdict(int)
    for session in sessions:
        modes[session["mode"]] += 1
        if not session["in_allow_list"] or session["mode"] != "live":
            continue
        band = labels.setdefault(session["condition_id"], f"band-{len(labels) + 1}")
        market, selected = read_selection(session["folder"], session["condition_id"], budget)
        market = market or band
        count = 0
        for index, episode in enumerate(session["episodes"]):
            samples = journal_samples(session, episode, horizon)
            count += len(samples)
            if samples:
                episodes.append({"session": session["name"], "index": index, "kind": "opening" if index == 0
                                 else "requote", "date": episode["start"].date().isoformat(), "market": market,
                                 "condition_id": band, "samples": samples,
                                 "share_at_selection": selected if index == 0 else None})
        listed.append({"session": session["name"], "band": band, "market": market,
                       "date": session["first"].date().isoformat(), "episodes": len(session["episodes"]),
                       "minute_samples_in_horizon": count,
                       "duration_minutes": round((session["end"] - session["first"]).total_seconds() / 60, 1)})
    series = summarize_series(episodes, horizon, baseline_seconds)
    extra = {(e["session"], e["index"]): e for e in episodes}
    for row in series["episodes"]:
        row["band"] = row.pop("condition_id")
        source = extra[(row["session"], row["episode"])]
        row["kind"], row["share_at_selection"] = source["kind"], source["share_at_selection"]
    opening = summarize_series([e for e in episodes if e["kind"] == "opening"], horizon, baseline_seconds)
    selected = [r for r in series["episodes"] if r["share_at_selection"] and r["mean_share_over_horizon"] is not None]

    def pooled_selection(weighted):
        bottom = sum(w * r["share_at_selection"] for r, w in weighted)
        return sum(w * r["mean_share_over_horizon"] for r, w in weighted) / bottom if bottom else None

    versus_selection = {
        "k_pooled": pooled_selection([(r, 1) for r in selected]) if selected else None,
        "k_median_episode": (statistics.median([r["mean_share_over_horizon"] / r["share_at_selection"]
                                                for r in selected]) if selected else None),
        "episodes_with_k": len(selected),
        "k_interval": crossed_bootstrap(selected, pooled_selection) if selected else None,
        "k_definition": ("opening episodes: sum of mean share over the horizon / sum of the selection-time modelled "
                         "share (selection.json quote.share_many, the book before our quote was posted)")}
    return {"schema_version": SCHEMA, "command": "reaction", "source": "re1-only",
            "verdict": "ESTIMATED" if series["episodes_with_k"] else "NO_JOURNAL_SAMPLES", "dates": list(days),
            "note": NO_REACTION_NOTE,
            "basis": ("RE-1 per-minute modelled share_many (84b scoring of the public book with our own size "
                      "removed, size-cutoff midpoint), sampled by the attended runner about every 60 s; "
                      "not a venue share and not an 88a measurement"),
            "sessions_found": len(sessions) + len(refused),
            "sessions_refused": [r["reason"] for r in refused],
            "sessions_by_mode": dict(sorted(modes.items())),
            "sessions_outside_allow_list": sum(not s["in_allow_list"] for s in sessions),
            "sessions": listed, "horizon_minutes": horizon, "baseline_seconds": baseline_seconds,
            "series_re1_journal_books": series,
            "opening_episodes_only": {k: opening[k] for k in ("k_pooled", "k_median_episode", "episodes_with_k",
                                                              "k_interval")},
            "versus_selection_share": versus_selection,
            "input": {"bytes": budget.bytes, "coverage": dict(budget.coverage)}}


# --------------------------------------------------------------------------
# latency
# --------------------------------------------------------------------------

def plain_mid(book):
    bids, _ = parse_levels(book.get("bids"))
    asks, _ = parse_levels(book.get("asks"))
    if not bids or not asks:
        return None
    return (max(p for p, _ in bids) + min(p for p, _ in asks)) / 2


def affected_bands(trigger, bands):
    """(role, condition_id) for the band holding the new high and the one holding the old high."""
    result = []
    for role, value in (("new_high_band", trigger["current_value"]), ("previous_high_band", trigger["previous_value"])):
        bucket = round_half_up(value) if value is not None else None
        if bucket is None:
            continue
        matches = sorted(cid for cid, row in bands.items() if band_contains_value(row, bucket))
        if len(matches) == 1 and all(matches[0] != c for _, c in result):
            result.append((role, matches[0]))
    return result


def measure_trigger(t0, series, *, horizon, max_pre_age, allowed_until):
    points = [(when, plain_mid(book), float(book.get("tick_size") or 0.01)) for when, book in series]
    points = [p for p in points if p[1] is not None]
    before = [p for p in points if p[0] <= t0]
    if not before or (t0 - before[-1][0]).total_seconds() > max_pre_age:
        return {"status": "no_pre_trigger_book"}
    _, pre_mid, tick = before[-1]
    window = [p for p in before if (t0 - p[0]).total_seconds() <= PRE_WINDOW_SECONDS]
    result = {"pre_mid": pre_mid, "tick": tick, "pre_outside_0_10_0_90": not 0.10 <= pre_mid <= 0.90,
              "pre_book_age_seconds": (t0 - before[-1][0]).total_seconds(),
              "moved_in_prior_15_min": max(p[1] for p in window) - min(p[1] for p in window) >= tick - 1e-9}
    deadline = t0 + timedelta(minutes=horizon)
    after = [p for p in points if t0 < p[0] <= deadline]
    if after:
        result["first_post_book_seconds"] = (after[0][0] - t0).total_seconds()
    for when, mid, _ in after:
        if abs(mid - pre_mid) >= tick - 1e-9:
            return {**result, "status": "moved", "lag_seconds": (when - t0).total_seconds(),
                    "direction": "up" if mid > pre_mid else "down", "move": mid - pre_mid}
    if deadline > allowed_until:
        return {**result, "status": "censored_by_allow_list"}
    return {**result, "status": "no_post_trigger_book" if not after else "no_move_within_horizon"}


def allowed_until(t0, days):
    day = t0.date()
    while (day + timedelta(days=1)).isoformat() in days:
        day += timedelta(days=1)
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc)


def summarize_latency(rows, role):
    rows = [r for r in rows if r["role"] == role]
    moved = [r for r in rows if r["status"] == "moved"]
    with_pre = [r for r in rows if "pre_mid" in r]
    obs = [{**r, "market": r["market_id"]} for r in rows]

    def median_lag(weighted):
        return weighted_median([(r["lag_seconds"], w) for r, w in weighted if r["status"] == "moved"])

    def outside(weighted):
        pairs = [(r["pre_outside_0_10_0_90"], w) for r, w in weighted if "pre_mid" in r]
        total = sum(w for _, w in pairs)
        return sum(w for v, w in pairs if v) / total if total else None

    lags = [r["lag_seconds"] for r in moved]
    statuses = defaultdict(int)
    for r in rows:
        statuses[r["status"]] += 1
    return {"role": role, "triggers": len(rows), "status_counts": dict(sorted(statuses.items())),
            "moved": len(moved),
            "lag_seconds": {"p25": quantile(lags, 0.25), "median": quantile(lags, 0.5),
                            "p75": quantile(lags, 0.75), "p90": quantile(lags, 0.9)},
            "median_lag_interval": crossed_bootstrap(obs, median_lag) if moved else None,
            "moved_up_fraction": (sum(r["direction"] == "up" for r in moved) / len(moved)) if moved else None,
            "pre_mid_available": len(with_pre),
            "pre_outside_fraction": (sum(r["pre_outside_0_10_0_90"] for r in with_pre) / len(with_pre)
                                     if with_pre else None),
            "pre_outside_interval": crossed_bootstrap(obs, outside) if with_pre else None,
            "moved_in_prior_15_min_fraction": (sum(r["moved_in_prior_15_min"] for r in with_pre) / len(with_pre)
                                               if with_pre else None),
            "clusters": sorted({(r["date"], r["market_id"]) for r in rows})}


def run_latency(maker_root, snapshots_root, trigger_paths, days, *, horizon=120, max_pre_age=300, budget=None):
    budget = budget or Budget()
    triggers = read_triggers(trigger_paths, days, budget)
    universe = read_universe(maker_root, days, budget)
    band_cache, plans, unmapped = {}, [], defaultdict(int)
    for trigger in triggers:
        slug = trigger["event_slug"]
        if slug not in band_cache:
            band_cache[slug] = read_bands(snapshots_root, slug, budget)
        bands, status = band_cache[slug]
        roles = affected_bands(trigger, bands)
        if not roles:
            unmapped["band_not_found:" + status] += 1
        for role, cid in roles:
            entry = universe.get(cid)
            if entry is None:
                unmapped["band_not_in_88a_universe"] += 1
                continue
            plans.append((trigger, role, cid, entry["yes_token"]))
    books = read_books(maker_root, days, sorted({p[3] for p in plans}), budget)
    rows = []
    for trigger, role, cid, token in plans:
        t0 = trigger["captured_at"]
        series = [(w, b) for w, b in books.get(token, []) if str(b.get("market", "")).lower() == cid]
        measured = measure_trigger(t0, series, horizon=horizon, max_pre_age=max_pre_age,
                                   allowed_until=allowed_until(t0, days))
        rows.append({"role": role, "market_id": trigger["market_id"], "event_slug": trigger["event_slug"],
                     "date": t0.date().isoformat(), "trigger_captured_at_utc": t0.isoformat(),
                     "previous_value": trigger["previous_value"], "current_value": trigger["current_value"],
                     "unit": trigger["unit"], "condition_id": cid, **measured})
    band_status = defaultdict(int)
    for _, status in band_cache.values():
        band_status[status] += 1
    return {"schema_version": SCHEMA, "command": "latency", "dates": list(days),
            "verdict": "MEASURED" if any(r["status"] == "moved" for r in rows) else "NO_MEASURED_MOVE",
            "definition": ("lag = first sealed 88a YES-book plain mid at least one tick from the last pre-trigger mid, "
                           "measured from the trigger's current_captured_at_utc; 88a book cadence bounds resolution"),
            "horizon_minutes": horizon, "max_pre_book_age_seconds": max_pre_age,
            "triggers": len(triggers), "unmapped": dict(unmapped), "band_sources": dict(band_status),
            "summary": [summarize_latency(rows, role) for role in ("new_high_band", "previous_high_band")],
            "rows": rows, "input": {"bytes": budget.bytes, "coverage": dict(budget.coverage)}}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _fmt(value, digits=3):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_reaction(report):
    lines = [f"# Competitor-reaction diagnostic ({', '.join(report['dates'])})", "",
             f"**Verdict: {report['verdict']}.** {report['note']}", ""]
    for key, label in (("series_88a_books", "88a books (primary)"),
                       ("series_re1_journal_books", "RE-1 journal books (labelled second series)")):
        series = report[key]
        interval = (series["k_interval"] or {}).get("ci95")
        lines += [f"## {label}", "",
                  f"k pooled {_fmt(series['k_pooled'])}, median episode k {_fmt(series['k_median_episode'])}, "
                  f"episodes {series['episodes_with_k']}, 95% interval {_fmt(interval)}.", "",
                  "| minute | samples | episodes | sessions | bands | mean share_many | median | mean share_single |",
                  "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        lines += [f"| {r['minute']} | {r['samples']} | {r['episodes']} | {r['sessions']} | {r['bands']} | "
                  f"{_fmt(r['mean_share_many'])} | {_fmt(r['median_share_many'])} | {_fmt(r['mean_share_single'])} |"
                  for r in series["curve"] if r["samples"]]
        lines.append("")
    lines += ["## Overlap", "", "| session | episodes | with 88a books | 88a samples |", "| --- | ---: | ---: | ---: |"]
    lines += [f"| {o['session']} | {o['episodes']} | {o['episodes_with_88a_books']} | "
              f"{o['88a_book_samples_for_token']} |" for o in report["overlap"]]
    lines += ["", f"Refused sessions: {len(report['sessions_refused'])}; outside allow-list: "
              f"{len(report['sessions_outside_allow_list'])}.", ""]
    return "\n".join(lines)


def render_reaction_re1_only(report):
    series = report["series_re1_journal_books"]
    opening = report["opening_episodes_only"]
    lines = [f"# Competitor-reaction diagnostic, RE-1 journals only ({', '.join(report['dates'])})", "",
             f"**Verdict: {report['verdict']}.** {report['note']}", "", f"Basis: {report['basis']}.", "",
             f"Sessions found {report['sessions_found']}, by mode {json.dumps(report['sessions_by_mode'])}, "
             f"refused {len(report['sessions_refused'])}, outside allow-list {report['sessions_outside_allow_list']}.",
             ""]
    for label, block in (("All postings (opening and requote)", series), ("Opening postings only", opening),
                         ("Opening postings vs selection-time share", report["versus_selection_share"])):
        interval = (block["k_interval"] or {}).get("ci95")
        lines.append(f"- {label}: k pooled {_fmt(block['k_pooled'])}, median episode k "
                     f"{_fmt(block['k_median_episode'])}, episodes {block['episodes_with_k']}, "
                     f"95% interval {_fmt(interval)}.")
    lines += ["", "## share(t) after posting", "",
              "| minute | samples | episodes | sessions | bands | mean share_many | median | mean share_single |",
              "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    lines += [f"| {r['minute']} | {r['samples']} | {r['episodes']} | {r['sessions']} | {r['bands']} | "
              f"{_fmt(r['mean_share_many'])} | {_fmt(r['median_share_many'])} | {_fmt(r['mean_share_single'])} |"
              for r in series["curve"] if r["samples"]]
    lines += ["", "## Episodes", "",
              "| session | episode | kind | band | market | date | samples | share at selection | share at posting | "
              "mean share | k |",
              "| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    lines += [f"| {e['session']} | {e['episode']} | {e['kind']} | {e['band']} | {e['market']} | {e['date']} | "
              f"{e['samples']} | {_fmt(e['share_at_selection'])} | {_fmt(e['share_at_posting'])} | "
              f"{_fmt(e['mean_share_over_horizon'])} | {_fmt(e['k'])} |" for e in series["episodes"]]
    lines.append("")
    return "\n".join(lines)


def render_latency(report):
    lines = [f"# Decidedness-latency diagnostic ({', '.join(report['dates'])})", "",
             f"**Verdict: {report['verdict']}.** {report['definition']}.", "",
             f"Triggers {report['triggers']}; unmapped {json.dumps(report['unmapped'], sort_keys=True)}.", "",
             "| band | triggers | moved | median lag s | p25 | p75 | 95% interval | pre mid outside [0.10, 0.90] |",
             "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |"]
    for s in report["summary"]:
        interval = (s["median_lag_interval"] or {}).get("ci95")
        lines.append(f"| {s['role']} | {s['triggers']} | {s['moved']} | {_fmt(s['lag_seconds']['median'], 0)} | "
                     f"{_fmt(s['lag_seconds']['p25'], 0)} | {_fmt(s['lag_seconds']['p75'], 0)} | {_fmt(interval)} | "
                     f"{_fmt(s['pre_outside_fraction'])} of {s['pre_mid_available']} |")
    lines += ["", "Status counts: " + "; ".join(f"{s['role']} {json.dumps(s['status_counts'], sort_keys=True)}"
                                                for s in report["summary"]), ""]
    return "\n".join(lines)


def write_outputs(report, out_dir, protected):
    out_dir = Path(out_dir).resolve()
    for root in protected:
        root = Path(root).resolve()
        if out_dir == root or root in out_dir.parents:
            raise ValueError("output directory is inside an input root")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = report["command"]
    renderer = render_reaction if name == "reaction" else render_latency
    if report.get("source") == "re1-only":
        name, renderer = "reaction-re1-only", render_reaction_re1_only
    with (out_dir / f"{name}.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    with (out_dir / f"{name}.md").open("x", encoding="utf-8") as handle:
        handle.write(renderer(report))
    return out_dir / f"{name}.json", out_dir / f"{name}.md"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("reaction", "latency"):
        p = sub.add_parser(name)
        p.add_argument("--date", action="append", required=True, help="allowed UTC date (repeatable)")
        p.add_argument("--maker-evidence-root", type=Path, default=data_path("maker_evidence"))
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--max-input-bytes", type=int, default=MAX_INPUT_BYTES)
        p.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    reaction = sub.choices["reaction"]
    reaction.add_argument("--re1-root", type=Path, required=True, help="read-only RE-1 analysis copy")
    reaction.add_argument("--source", choices=("88a-overlap", "re1-only"), default="88a-overlap",
                          help="88a-overlap joins 88a books; re1-only uses the journals' per-minute share alone")
    reaction.add_argument("--read-live-campaign-root", action="store_true",
                          help="re1-only: also accept the live campaign root (.weather-re1m-YYYYMMDD), read-only")
    reaction.add_argument("--horizon-minutes", type=int, default=60)
    reaction.add_argument("--baseline-seconds", type=int, default=120)
    latency = sub.choices["latency"]
    latency.add_argument("--snapshots-root", type=Path, default=data_path("snapshots"))
    latency.add_argument("--trigger-path", type=Path, action="append",
                         help="observation-trigger journal (repeatable); default: live file plus rotated siblings")
    latency.add_argument("--horizon-minutes", type=int, default=120)
    latency.add_argument("--max-pre-age-seconds", type=int, default=300)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        days = allow_list(args.date, calibration_only=args.command == "latency")
        budget = Budget(args.max_input_bytes, args.max_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.command == "reaction" and args.source == "re1-only":
            report = run_reaction_re1_only(args.re1_root, days, horizon=args.horizon_minutes,
                                           baseline_seconds=args.baseline_seconds, budget=budget,
                                           allow_campaign_root=args.read_live_campaign_root)
            protected = (args.re1_root,)
        elif args.command == "reaction":
            if args.read_live_campaign_root:
                parser.error("--read-live-campaign-root applies to --source re1-only only")
            report = run_reaction(args.re1_root, args.maker_evidence_root, days, horizon=args.horizon_minutes,
                                  baseline_seconds=args.baseline_seconds, budget=budget)
            protected = (args.re1_root, args.maker_evidence_root)
        else:
            live = args.snapshots_root / "observation_triggers.jsonl"
            paths = args.trigger_path or [live, *rotated_sidecar_paths(live)]
            report = run_latency(args.maker_evidence_root, args.snapshots_root, paths, days,
                                 horizon=args.horizon_minutes, max_pre_age=args.max_pre_age_seconds, budget=budget)
            protected = (args.maker_evidence_root, args.snapshots_root)
    except (StopRun, InputRefused) as exc:
        print(json.dumps({"command": args.command, "refused": str(exc)}))
        return 2
    json_path, md_path = write_outputs(report, args.out_dir, protected)
    print(json.dumps({"command": args.command, "verdict": report["verdict"], "json": str(json_path),
                      "markdown": str(md_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
