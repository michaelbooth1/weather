"""Fixed-sample observation clock diagnostics with bounded quote staleness.

Top two YES bands are fixed using the last snapshot at/before 10:00 (age <=1h).
All study events are 10:00 <= local time <18:00. IEM valid times are observation
times, NOT publication receipts: these results cannot identify private feeds.
"""
from collections import Counter
from datetime import datetime
import math

import numpy as np
import pandas as pd

from weather.market.market_registry import REGISTRY
from weather.market.execution_tape_markout import iter_tape_lines, parse_trade_line
from tools.research.missing_information.extract import read_csv, finite
from tools.research.missing_information.methods import summary


def epoch_seconds(values):
    return pd.to_datetime(values, utc=True, format="mixed").dt.as_unit("ns").astype("int64").to_numpy()/1e9


def asof(times, values, query, max_age=120):
    times, values, query = np.asarray(times), np.asarray(values), np.asarray(query)
    idx = np.searchsorted(times, query, side="right") - 1
    safe = np.maximum(idx, 0)
    if not len(times):
        return np.full(query.shape, np.nan)
    return np.where((idx >= 0) & (query-times[safe] <= max_age), values[safe], np.nan)


def book_series(path, keys):
    series, tokens = {k: [] for k in keys}, set()
    columns = ["captured_at_utc", "outcome", "bin_kind", "bin_value", "bin_value_hi", "midpoint", "best_bid", "best_ask", "clob_token_id"]
    # Reading selected columns in chunks keeps the 4.75 GB sample bounded.
    for chunk in pd.read_csv(path, usecols=columns, chunksize=100_000, dtype={"clob_token_id": str}, low_memory=False):
        chunk = chunk[chunk.outcome == "Yes"]
        for key in keys:
            kind, low, high = key
            selected = chunk[(chunk.bin_kind == kind) & (chunk.bin_value == low)
                             & (chunk.bin_value_hi.fillna(chunk.bin_value) == high)]
            selected = selected[(selected.best_bid >= 0) & (selected.best_ask <= 1)
                                & (selected.best_ask >= selected.best_bid) & selected.midpoint.between(0,1)]
            if len(selected):
                times = epoch_seconds(selected.captured_at_utc)
                series[key].extend(zip(times, selected.midpoint.to_numpy(float)))
                tokens.update(selected.clob_token_id.dropna().tolist())
    out = {}
    for key, values in series.items():
        # Last captured row at a duplicate timestamp wins, without using future quotes.
        ordered = sorted(dict(values).items())
        out[key] = (np.array([t for t,v in ordered]), np.array([v for t,v in ordered]))
    return out, tokens


def stamp(value):
    try:
        t = datetime.fromisoformat(value)
        return t.timestamp() if t.tzinfo else None
    except (ValueError, TypeError):
        return None


def check3(frame, raw, observations, output):
    event_rows, histogram_rows, trade_rows, latency_rows, move_lags, audit = [], [], [], [], [], []
    obs_groups = {(d,m): g for (d,m), g in observations.groupby(["date", "market"])}
    lat_counts = Counter()
    day_groups = list(frame.groupby(["date", "market"], observed=True))
    for number, ((date, market), day) in enumerate(day_groups, 1):
        spec = REGISTRY[market]
        first = day.iloc[0]
        stratum = first.stratum
        label = dict(date=date, market=market, stratum=stratum)
        folder_name = f"{spec.slug_prefix}-{datetime.fromisoformat(date).strftime('%B').lower()}-{int(date[-2:])}-{date[:4]}"
        folder = raw / folder_name
        # Resolve exact supplied event slug from the fixed source naming convention.
        if not folder.exists():
            candidates = [p for p in raw.glob(f"*{market}*") if p.is_dir()]
            raise ValueError(f"event path not found: {folder_name}; candidates={len(candidates)}")
        path = folder / "observation_payloads_long.csv"
        seen_obs = set()
        for row in read_csv(path):
            if row.get("source") not in {"metar", "wu_current", "wu_history"}:
                continue
            observed, seen = stamp(row.get("provider_observed_at")), stamp(row.get("first_seen_at"))
            lat_counts["observation_rows"] += 1
            if observed is None or seen is None:
                lat_counts["missing_provider_or_seen"] += 1
                continue
            key = (row["source"], observed, seen)
            if key in seen_obs:
                continue
            seen_obs.add(key)
            local = datetime.fromtimestamp(seen, spec.tz)
            if local.date().isoformat() == date and 10 <= local.hour < 18:
                latency_rows.append({**label, "source": row["source"], "minutes": (seen-observed)/60})
        start = datetime.fromisoformat(date+"T10:00:00").replace(tzinfo=spec.tz).timestamp()
        stop = start+8*3600
        before = day[(day.decimal_hour <= 10) & (day.decimal_hour >= 9)].sort_values("captured_at_utc")
        if before.empty:
            audit.append({**label, "status": "NO_PRE10_SNAPSHOT"})
            continue
        anchor = before.iloc[-1]
        indices = sorted(np.argsort(-np.asarray(anchor.p_market), kind="stable")[:2])
        keys = [tuple(anchor.bands[i][k] for k in ("kind", "low", "high")) for i in indices]
        token_ids = {anchor.tokens[i] for i in indices if anchor.tokens[i]}
        # Trade histograms use all supplied tape dates, not only book-sample dates.
        trades = np.zeros(60)
        identities = set()
        for line in iter_tape_lines(folder):
            trade, reason = parse_trade_line(line)
            if trade is None or trade["identity"] in identities:
                continue
            identities.add(trade["identity"])
            t = trade["epoch_seconds"]
            if start <= t < stop and trade["token"] in token_ids:
                trades[int(t//60)%60] += 1
        if trades.sum():
            for minute, count in enumerate(trades):
                trade_rows.append({**label, "minute": minute, "count": count, "fraction": count/trades.sum(),
                                   "vs_uniform": count/trades.sum()-1/60})
        book = folder / "order_books_summary.csv"
        if not book.exists():
            continue
        series, book_tokens = book_series(book, keys)
        if any(not len(series[k][0]) for k in keys):
            audit.append({**label, "status": "MISSING_SELECTED_BOOK_BAND"})
            continue
        def prices(query):
            return np.array([asof(*series[k], query) for k in keys])
        signs = np.array([1 if i == first.winner else -1 for i in indices])
        grid = np.arange(start, stop+1, 60)
        ps = prices(grid)
        valid = np.isfinite(ps).all(axis=0)
        changes = np.diff(ps, axis=1)
        valid_change = valid[1:] & valid[:-1]
        absolute = np.abs(changes).mean(axis=0)
        signed = (changes*signs[:,None]).mean(axis=0)
        minutes = ((grid[1:]//60)%60).astype(int)
        for minute in range(60):
            mask = valid_change & (minutes == minute)
            denom = np.nansum(absolute[valid_change])
            fraction = float(np.nansum(absolute[mask])/denom) if denom > 0 else np.nan
            histogram_rows.append({**label, "minute": minute, "fraction": fraction,
                                   "vs_uniform": fraction-1/60, "valid_minutes": int(mask.sum())})
        obs = obs_groups.get((date, market), pd.DataFrame()).copy()
        if len(obs):
            obs = obs.sort_values("utc").drop_duplicates(["utc", "report_type"])
            obs["epoch"] = epoch_seconds(obs.utc)
            obs["previous_tmpf"] = pd.to_numeric(obs.tmpf, errors="coerce").shift(1)
            obs["tmpf"] = pd.to_numeric(obs.tmpf, errors="coerce")
            active = obs[(obs.epoch >= start) & (obs.epoch < stop)]
            for r in active.itertuples():
                offsets = np.arange(-15, 16)
                pp = prices(r.epoch+offsets*60)
                if not np.isfinite(pp[:,[0,15,30]]).all():
                    continue
                pre = float(((pp[:,15]-pp[:,0])*signs).mean())
                post = float(((pp[:,30]-pp[:,15])*signs).mean())
                event_rows.append({**label, "type": int(r.report_type), "metric": "pre15_signed", "value": pre})
                event_rows.append({**label, "type": int(r.report_type), "metric": "post15_signed", "value": post})
                event_rows.append({**label, "type": int(r.report_type), "metric": "post_minus_pre", "value": post-pre})
                for offset, vector in zip(offsets, pp.T):
                    value = float(((vector-pp[:,0])*signs).mean())
                    event_rows.append({**label, "type": int(r.report_type), "metric": f"curve_{offset:+03}", "value": value})
                if r.report_type == 3 and np.isfinite(r.tmpf) and np.isfinite(r.previous_tmpf) and r.tmpf != r.previous_tmpf:
                    at = prices(np.array([r.epoch-600, r.epoch]))
                    if np.isfinite(at).all():
                        tilt_change = ((at[1,1]-at[0,1])-(at[1,0]-at[0,0]))/2
                        event_rows.append({**label, "type": 3, "metric": "pre10_temperature_aligned",
                                           "value": float(np.sign(r.tmpf-r.previous_tmpf)*tilt_change)})
            # Continuous-time exposure of [t_obs,t_obs+3m] at one-minute resolution.
            in_window = np.zeros(len(grid)-1, bool)
            for t in active.epoch:
                in_window |= (grid[:-1] >= t) & (grid[1:] <= t+180)
            positive = np.maximum(signed, 0)
            denom = np.nansum(positive[valid_change])
            if denom > 0 and valid_change.any():
                event_rows.append({**label, "type": 0, "metric": "post_observation_move_share_minus_exposure",
                                   "value": float(np.nansum(positive[valid_change & in_window])/denom
                                                  - in_window[valid_change].mean())})
        snapshot_times = epoch_seconds(day.captured_at_utc)
        snapshot_times.sort()
        jump_times = set()
        for times, values in series.values():
            selected = (np.diff(times) <= 120) & (np.abs(np.diff(values)) >= .03)
            jump_times.update(t for t in times[1:][selected] if start <= t < stop)
        for t in sorted(jump_times):
            j = np.searchsorted(snapshot_times, t, side="left")
            move_lags.append({**label, "minutes": float((snapshot_times[j]-t)/60) if j<len(snapshot_times) else np.nan,
                              "censored": float(j == len(snapshot_times))})
        audit.append({**label, "status": "SCORED", "valid_minute_changes": int(valid_change.sum()),
                      "selected_band_indices": indices, "top2_tokens_in_snapshot": len(token_ids),
                      "top2_tokens_in_books": len(book_tokens)})
        print(f"clock books {date} {market}: {valid_change.sum()} valid minutes", flush=True)
    result = {"audit": audit, "latency_audit": dict(lat_counts), "strata": {},
              "limits": ["IEM observation valid times are not publication receipts; leads cannot identify a private feed.",
                         "Top two bands fixed as-of 10:00; zero/unchanged minutes retained; missing/stale quotes excluded.",
                         "Clock event selection uses eventual winner only for retrospective signing; no trading edge.",
                         "Minute histograms have per-bin crossed descriptive intervals, no familywise significance claim."]}
    tables = dict(events=pd.DataFrame(event_rows), book_histograms=pd.DataFrame(histogram_rows),
                  trade_histograms=pd.DataFrame(trade_rows), observation_latency=pd.DataFrame(latency_rows),
                  move_latency=pd.DataFrame(move_lags))
    for name, df in tables.items():
        df.to_csv(output/f"clock_{name}.csv", index=False)
    for stratum in frame.stratum.unique():
        s = {}
        for name in ("book_histograms", "trade_histograms"):
            df = tables[name]
            subset = df[df.stratum == stratum] if len(df) else df
            s[name] = {int(k): summary(g, "vs_uniform", alternative=.01) for k,g in subset.groupby("minute")} if len(subset) else {}
            s[name+"_total_variation"] = float(sum(abs(v["estimate"]) for v in s[name].values() if v.get("estimate") is not None)/2)
        df = tables["events"]
        subset = df[df.stratum == stratum] if len(df) else df
        s["events"] = {f"{kind}:{metric}": {**summary(g, "value", alternative=.01), "events": len(g)}
                       for (kind, metric),g in subset.groupby(["type", "metric"])} if len(subset) else {}
        for name in ("observation_latency", "move_latency"):
            df = tables[name]
            subset = df[df.stratum == stratum] if len(df) else df
            s[name] = summary(subset, "minutes", alternative=1.) if len(subset) else {"status": "NO_DATA"}
            if name == "move_latency" and len(subset):
                s[name+"_censoring"] = summary(subset, "censored", alternative=.1)
        result["strata"][stratum] = s
    return result
