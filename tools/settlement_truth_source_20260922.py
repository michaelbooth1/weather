"""Read-only 86a measurement. Run --help; outputs stay in this worktree's data/.

No environment-file loader, credentials, exchange writes, or production imports.
Network is opt-in, serial, cached, <=1 request/second/host, no retries/redirects.
Touch data/settlement_truth_86a/STOP to stop before the next request; interrupt
the foreground process to abort an in-flight request when RE-1 starts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import requests
from weather.paths import data_path, config_path, docs_path
from weather.market.market_registry import BUILTIN_SPECS, spec_for_id
from weather.sources.asos_one_minute import (
    IEM_ASOS_1MIN_URL, build_iem_1min_params, normalize_iem_1min_csv,
    resolve_iem_1min_station,
)
from weather.sources.metar_history import IEM_ASOS_URL, normalize_csv
from weather.units import round_half_up, to_float, c_to_native

ROOT = data_path("settlement_truth_86a")
START = date(2026, 7, 1)
END = date(2026, 9, 21)
SWITCH = "2026-08-23"
FAMILIES = ("asos", "metar", "nws")
CANDIDATES = ("wu", "asos", "metar", "metar_with_6h", "metar_hourly", "nws", "nws_hourly")


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def boundaries(spec, start, end):
    return (datetime.combine(start, dt_time(), spec.tz).astimezone(timezone.utc),
            datetime.combine(end + timedelta(days=1), dt_time(), spec.tz).astimezone(timezone.utc))


def is_hourly(spec, minute):
    return 51 <= minute <= 59 if spec.icao.startswith("K") else minute >= 56 or minute <= 4


def band_contains(band, value):
    if value is None or not band:
        return None
    text = band.replace("°", "").replace("–", "-").strip()
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    # A range hyphen is a separator, not the sign of its upper endpoint.
    match = re.match(r"^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", text)
    if match:
        lo, hi = map(float, match.groups())
        return lo <= value <= hi
    if len(nums) != 1:
        raise ValueError(f"unrecognized band: {band!r}")
    n = float(nums[0])
    if any(x in text.lower() for x in ("below", "less", "lower")):
        return value <= n
    if any(x in text.lower() for x in ("above", "higher", "more")):
        return value >= n
    return value == n


class Cache:
    def __init__(self, network=False):
        self.network = network
        self.session = requests.Session()
        self.session.trust_env = False  # no netrc, ambient credentials or proxy

    def get(self, url, params=None):
        from urllib.parse import urlparse
        request = requests.Request("GET", url, params=params).prepare()
        host = urlparse(request.url).hostname
        if host not in {"mesonet.agron.iastate.edu", "api.weather.gov", "gamma-api.polymarket.com"}:
            raise ValueError("endpoint not allowlisted")
        key = sha(request.url.encode())
        body_path = ROOT / "cache" / (key + ".body")
        meta_path = ROOT / "cache" / (key + ".json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            raw = body_path.read_bytes()
            if sha(raw) != meta["sha256"]:
                raise ValueError("cache hash mismatch")
            return raw, meta
        if not self.network:
            raise RuntimeError("uncached request; opt in with --network")
        if (ROOT / "STOP").exists():
            raise SystemExit("STOP: network prohibited")
        # Persist the previous completion time across short foreground invocations.
        stamp = ROOT / "host_times.json"
        prior = json.loads(stamp.read_text()) if stamp.exists() else {}
        interval = 15.0 if host == "mesonet.agron.iastate.edu" else 1.05
        wait = max(0, interval - (time.time() - prior.get(host, 0)))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if (ROOT / "STOP").exists():
                raise SystemExit("STOP: network prohibited")
            time.sleep(min(0.1, max(0, deadline-time.monotonic())))
        if (ROOT / "STOP").exists():
            raise SystemExit("STOP: network prohibited")
        meta = {"url": request.url, "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
        try:
            with self.session.get(request.url, headers={"User-Agent": "weather-settlement-research/86a (github.com/michaelbooth1/weather)"},
                                  timeout=(5, 20), allow_redirects=False, stream=True) as response:
                meta["status"] = response.status_code
                meta["retry_after"] = response.headers.get("Retry-After")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    if (ROOT / "STOP").exists():
                        raise SystemExit("STOP: response aborted")
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError("response exceeds 8 MiB bound")
                    chunks.append(chunk)
                raw = b"".join(chunks)
        except requests.RequestException as exc:
            raw = b""
            meta.update(status=0, error=type(exc).__name__)
        finally:
            prior[host] = time.time()
            dump(stamp, prior)
        meta.update(sha256=sha(raw), bytes=len(raw), cache_key=key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(raw)
        dump(meta_path, meta)
        print(json.dumps({k: meta[k] for k in ("url", "status", "bytes", "sha256")}), flush=True)
        if meta["status"] == 429:
            raise SystemExit("HTTP 429: stop collection; no automatic retry")
        return raw, meta


def inventory(labels):
    rows = []
    if labels.exists():
        raw = labels.read_bytes()
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
            if START.isoformat() <= row["target_date"] <= END.isoformat():
                if row["settlement_unit"] != spec_for_id(row["market_id"]).unit:
                    raise ValueError("label unit does not match MarketSpec")
                rows.append(row)
        provenance = {"path": str(labels), "sha256": sha(raw), "bytes": len(raw)}
    else:
        provenance = {"path": str(labels), "missing": True}
    keys = [(r["market_id"], r["target_date"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("projection has duplicate market-days; resolve before comparing")
    events_raw = config_path("location_market_events.json").read_bytes()
    events = json.loads(events_raw)
    configured = []
    ids = {s.id for s in BUILTIN_SPECS}
    for loc in events["locations"]:
        if loc["location_id"] in ids:
            for e in loc["active_events"]:
                configured.append({"market": loc["location_id"], **e})
    result = {"labels_provenance": provenance, "rows": rows,
              "config_sha256": sha(events_raw), "configured_events": configured,
              "date_min": min((r["target_date"] for r in rows), default=None),
              "date_max": max((r["target_date"] for r in rows), default=None),
              "market_days": len(rows), "sources": dict(Counter(r["settlement_source"] for r in rows))}
    dump(ROOT / "inventory.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "configured_events")}))


def series(family, spec, start, end, cache, batch_specs=None):
    start_utc, end_utc = boundaries(spec, start, end)
    result = {"family": family, "market": spec.id, "station": spec.icao, "unit": spec.unit,
              "start": str(start), "end": str(end), "days": {}}
    if family == "asos":
        station = resolve_iem_1min_station(spec)
        if not station["supported"]:
            result["reason"] = station["reason"]
            return result
        params = build_iem_1min_params(station["station"], start_utc, end_utc)
        params.update(vars="tmpf", sample="1min", what="download", delim="comma", gis="no")
        if batch_specs:
            params["station"] = ",".join(resolve_iem_1min_station(s)["station"] for s in batch_specs)
            # Fetch a UTC envelope, filter every row back to its own local date.
            low = min(boundaries(s, start, end)[0] for s in batch_specs)
            high = max(boundaries(s, start, end)[1] for s in batch_specs)
            params.update(sts=low.isoformat(), ets=high.isoformat())
            for name in list(params):
                if re.match(r"^(year|month|day|hour|minute)[12]$", name):
                    del params[name]
        raw, meta = cache.get(IEM_ASOS_1MIN_URL, params)
    elif family == "metar":
        # Same public adapter endpoint, with documented six-hour extrema retained.
        params = [("station", spec.icao), ("sts", start_utc.isoformat()), ("ets", end_utc.isoformat()),
                  ("data", "tmpc"), ("data", "metar"), ("tz", "Etc/UTC"),
                  ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"),
                  ("report_type", "3"), ("report_type", "4")]
        if batch_specs:
            low = min(boundaries(s, start, end)[0] for s in batch_specs)
            high = max(boundaries(s, start, end)[1] for s in batch_specs)
            params = [(k, v) for k, v in params if k not in ("station", "sts", "ets")]
            params += [("station", s.icao) for s in batch_specs]
            params += [("sts", low.isoformat()), ("ets", high.isoformat())]
        raw, meta = cache.get(IEM_ASOS_URL, params)
    else:
        raw, meta = cache.get(f"https://api.weather.gov/stations/{spec.icao}/observations",
                              {"start": start_utc.isoformat(), "end": end_utc.isoformat(), "limit": 500})
    result["response"] = meta
    if meta["status"] != 200:
        result["reason"] = f"HTTP {meta['status']}"
        return result
    samples = defaultdict(dict)
    hourly = defaultdict(list)
    six = defaultdict(list)
    excluded_six = Counter()
    if family in ("asos", "metar"):
        text = raw.decode("utf-8-sig")
        # Public one-minute service labels its timestamp column with the timezone.
        text = text.replace("valid(Etc/UTC)", "valid", 1)
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "valid" not in reader.fieldnames:
            result["reason"] = "no valid timestamp column"
            return result
        # Reuse canonical normalization in bounded batches (not whole histories).
        batch = []
        def consume(batch):
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(batch)
            normalized = (normalize_iem_1min_csv(out.getvalue(), spec) if family == "asos"
                          else normalize_csv(out.getvalue(), spec))
            for r in normalized:
                stamp = r["valid_time_utc"]
                dt = datetime.fromisoformat(stamp)
                day = dt.astimezone(spec.tz).date()
                value = r.get("temp_native")
                if start <= day <= end and value is not None:
                    samples[str(day)][stamp] = value
                    if is_hourly(spec, dt.minute):
                        hourly[str(day)].append(value)
        for r in reader:
            station = (r.get("station") or "").upper()
            expected = {spec.icao, spec.icao[1:] if spec.icao.startswith("K") else spec.icao}
            if station not in expected:
                continue
            batch.append(r)
            # FMH-1 RMK group 1snTxTxTx: 6-hour maximum in tenths Celsius.
            remarks = (r.get("metar") or "").partition(" RMK ")[2]
            group = re.search(r"(?:^|\s)1([01])(\d{3})(?:\s|$)", remarks) if spec.icao.startswith("K") else None
            value = (int(group[2]) / 10 * (-1 if group[1] == "1" else 1)) if group else None
            if value is not None:
                dt = datetime.fromisoformat(r["valid"]).replace(tzinfo=timezone.utc)
                day = dt.astimezone(spec.tz).date()
                low, high = boundaries(spec, day, day)
                if dt - timedelta(hours=6) >= low and dt < high:
                    six[str(day)].append(c_to_native(value, spec.unit))
                else:
                    excluded_six[str(day)] += 1
            if len(batch) == 1000:
                consume(batch)
                batch = []
        consume(batch)
    else:
        payload = json.loads(raw)
        features = list(payload.get("features", []))
        result["pages"] = [meta]
        seen = {meta["url"]}
        while payload.get("pagination", {}).get("next") and features:
            oldest = min(datetime.fromisoformat(f["properties"]["timestamp"].replace("Z", "+00:00")) for f in payload["features"])
            if oldest <= start_utc:
                break
            url = payload["pagination"]["next"]
            if url in seen or len(result["pages"]) >= 20:
                result["reason"] = "pagination incomplete"
                return result
            seen.add(url)
            page_raw, page_meta = cache.get(url)
            result["pages"].append(page_meta)
            if page_meta["status"] != 200:
                result["reason"] = "pagination HTTP error"
                return result
            payload = json.loads(page_raw)
            features.extend(payload.get("features", []))
            if not payload.get("features"):
                break
        for feature in features:
            p = feature["properties"]
            dt = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
            day = dt.astimezone(spec.tz).date()
            temp = p.get("temperature", {})
            value = to_float(temp.get("value"))
            if value is not None and start <= day <= end and temp.get("qualityControl") not in ("X", "Z"):
                if temp.get("unitCode") != "wmoUnit:degC":
                    raise ValueError("unexpected NWS temperature unit")
                samples[str(day)][dt.isoformat()] = c_to_native(value, spec.unit)
                if is_hourly(spec, dt.minute):
                    hourly[str(day)].append(c_to_native(value, spec.unit))
    for day, values in samples.items():
        high = max(values.values())
        hourly_stamps = [datetime.fromisoformat(t).astimezone(spec.tz) for t in values
                         if is_hourly(spec, datetime.fromisoformat(t).minute)]
        result["days"][day] = {"maximum_native": high, "degree": round_half_up(high),
            "samples": len(values), "first_utc": min(values), "last_utc": max(values),
            "hours_present": len({datetime.fromisoformat(t).astimezone(spec.tz).hour for t in values}),
            "contained_6h_max_native": max(six[day], default=None), "contained_6h_count": len(six[day]),
            "hourly_degree": round_half_up(max(hourly[day])) if hourly[day] else None,
            "hourly_samples": len(hourly_stamps), "hourly_hours": len({t.hour for t in hourly_stamps}),
            "cross_midnight_6h_excluded": excluded_six[day]}
        if six[day]:
            combined = max(high, max(six[day]))
            result["days"][day]["with_6h_degree"] = round_half_up(combined)
    return result


def fetch(args):
    spec = spec_for_id(args.market)
    cache = Cache(args.network)
    if args.family == "rules":
        inv = json.loads((ROOT / "inventory.json").read_text())
        event = next(e for e in inv["configured_events"] if e["market"] == spec.id and e["event_date"] == "2026-09-22")
        raw, meta = cache.get("https://gamma-api.polymarket.com/events/slug/" + event["event_slug"])
        result = {"response": meta}
        if meta["status"] == 200:
            payload = json.loads(raw)
            result.update(event_slug=payload["slug"], description=payload.get("description"),
                          resolutionSource=payload.get("resolutionSource"),
                          market_rules=[{k: m.get(k) for k in ("id", "description", "resolutionSource")} for m in payload.get("markets", [])])
        dump(ROOT / "rules.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "market_rules"}, indent=2))
        return
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if not START <= start <= end <= END or (args.family != "nws" and (end-start).days > 27):
        raise ValueError("use chunks of at most 28 days inside the mission interval")
    result = series(args.family, spec, start, end, cache)
    dump(ROOT / "series" / f"{args.family}_{spec.id}_{start}_{end}.json", result)
    print(json.dumps({"family": args.family, "market": spec.id, "days": len(result["days"]), "reason": result.get("reason")}))


def fetch_batch(args):
    specs = [spec_for_id(x) for x in args.markets.split(",")]
    if args.family == "asos":
        specs = [s for s in specs if resolve_iem_1min_station(s)["supported"]]
    if not specs:
        return
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if not START <= start <= end <= END or (end-start).days > 27 or len(specs) > 12:
        raise ValueError("batch outside bounded mission scope")
    cache = Cache(args.network)
    for spec in specs:
        result = series(args.family, spec, start, end, cache, specs)
        dump(ROOT / "series" / f"{args.family}_{spec.id}_{start}_{end}.json", result)
        print(json.dumps({"family": args.family, "market": spec.id, "days": len(result["days"]), "reason": result.get("reason")}), flush=True)


def analyze():
    inv = json.loads((ROOT / "inventory.json").read_text())
    known = {(r["market_id"], r["target_date"]): r for r in inv["rows"]}
    # Explicitly handed-down historical control, NOT a fresh local ledger row.
    # EF 10c and its named 2026-09-19 audit give these exact values.
    known.setdefault(("miami", "2026-09-02"), {
        "settlement_high": "89", "settlement_source": "daily_summary",
        "polymarket_winning_band": "90-91 F", "audit_only": True,
    })
    sources = defaultdict(dict)
    receipts = []
    for path in sorted((ROOT / "series").glob("*.json")):
        doc = json.loads(path.read_text())
        receipts.append({k: v for k, v in doc.items() if k != "days"})
        for day, item in doc["days"].items():
            key = (doc["market"], day)
            old = sources[doc["family"]].get(key)
            if old and old != item:
                raise ValueError("overlapping candidate series")
            sources[doc["family"]][key] = item
            if doc["family"] == "metar":
                sources["metar_with_6h"][key] = {**item, "degree": item.get("with_6h_degree", item["degree"])}
            if doc["family"] in ("metar", "nws"):
                sources[doc["family"]+"_hourly"][key] = {**item, "degree": item["hourly_degree"],
                    "samples": item.get("hourly_samples", 0), "hours_present": item.get("hourly_hours", 0)}
    rows, differences = [], []
    for spec in BUILTIN_SPECS:
        day = START
        while day <= END:
            key = (spec.id, str(day))
            label = known.get(key, {})
            high = to_float(label.get("settlement_high"))
            # Snapshot fallback is explicitly separated from WU source labels.
            wu = round_half_up(high) if label.get("settlement_source") == "daily_summary" else None
            row = {"market": spec.id, "date": str(day), "unit": spec.unit,
                   "stratum": "pre" if str(day) < SWITCH else "post", "capture_evidence": bool(label),
                   "wu": wu, "label_source": label.get("settlement_source", "unavailable"),
                   "venue_band": label.get("polymarket_winning_band") or "",
                   "venue_source": ("supplied EF10c audit control" if label.get("audit_only") else
                                    "frozen CSV reconciliation" if label.get("polymarket_winning_band") else "unavailable")}
            for family in CANDIDATES[1:]:
                item = sources[family].get(key, {})
                row[family] = item.get("degree")
                row[family+"_samples"] = item.get("samples", 0)
                row[family+"_hours"] = item.get("hours_present", 0)
            for family in CANDIDATES:
                value = row[family]
                match = band_contains(row["venue_band"], value)
                if match is False:
                    differences.append({"comparison": family+"_venue", "market": spec.id, "date": str(day), "candidate": value, "reference": row["venue_band"], "unit": spec.unit})
                if family != "wu" and value is not None and wu is not None and value != wu:
                    differences.append({"comparison": family+"_wu", "market": spec.id, "date": str(day), "candidate": value, "reference": wu, "difference": value-wu, "unit": spec.unit})
            rows.append(row)
            day += timedelta(days=1)
    tables = []
    for stratum in ("pre", "post"):
        for family in CANDIDATES:
            panel = [r for r in rows if r["stratum"] == stratum]
            pairs = [r for r in panel if r[family] is not None and r["venue_band"]]
            wp = [r for r in panel if r[family] is not None and r["wu"] is not None]
            tables.append({"stratum": stratum, "candidate": family, "potential_days": len(panel),
                "available": sum(r[family] is not None for r in panel),
                "band_matches": sum(band_contains(r["venue_band"], r[family]) for r in pairs), "band_pairs": len(pairs),
                "date_clusters": len({r["date"] for r in pairs}), "market_clusters": len({r["market"] for r in pairs}),
                "wu_exact_matches": sum(r[family] == r["wu"] for r in wp), "wu_pairs": len(wp),
                "signed_difference_counts": dict(sorted(Counter(f"{r['unit']}:{r[family]-r['wu']:+g}" for r in wp).items())),
                "paired_band_delta": crossed_delta([r for r in pairs if r["wu"] is not None], family)})
    # The same named audit lists 13 formerly missing dates uniformly over 12 markets.
    missing_dates = {f"2026-08-{n:02}" for n in range(28, 32)} | {"2026-09-01", "2026-09-13"} | {f"2026-09-{n:02}" for n in range(4,11)}
    recovery = []
    for family in CANDIDATES[1:]:
        panel = [r for r in rows if r["date"] in missing_dates]
        recovery.append({"candidate": family, "historically_missing": len(panel),
            "observed_max_available": sum(r[family] is not None for r in panel),
            "all_24_hours_represented": sum(r[family] is not None and r[family+"_hours"] == 24 for r in panel),
            "venue_pairs": sum(r[family] is not None and bool(r["venue_band"]) for r in panel),
            "verified_recovery": None})
    dump(ROOT / "analysis.json", {"tables": tables, "differences": differences, "receipts": receipts, "recovery": recovery})
    with (ROOT / "station_days.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(tables, indent=2))


def crossed_delta(rows, family):
    """Exploratory paired candidate-minus-WU band accuracy, crossed resampling.

    Bounded at 996 rows and 2,000 draws; no fitted model, hypothesis decision or
    promotion test. Degenerate all-success intervals do not prove equivalence.
    """
    if not rows:
        return None
    import numpy as np
    dates = sorted({r["date"] for r in rows})
    markets = sorted({r["market"] for r in rows})
    if len(dates) < 2 or len(markets) < 2:
        return {"pairs": len(rows), "date_clusters": len(dates), "market_clusters": len(markets),
                "reason": "insufficient crossed clusters; no uncertainty estimate"}
    values = np.zeros((len(dates), len(markets)))
    present = np.zeros_like(values)
    for r in rows:
        i, j = dates.index(r["date"]), markets.index(r["market"])
        values[i, j] = int(band_contains(r["venue_band"], r[family])) - int(band_contains(r["venue_band"], r["wu"]))
        present[i, j] = 1
    rng = np.random.default_rng(860922)
    dw = rng.multinomial(len(dates), np.full(len(dates), 1/len(dates)), size=2000)
    mw = rng.multinomial(len(markets), np.full(len(markets), 1/len(markets)), size=2000)
    denom = np.einsum("bi,ij,bj->b", dw, present, mw)
    numer = np.einsum("bi,ij,bj->b", dw, values, mw)
    draws = numer[denom > 0] / denom[denom > 0]
    return {"pairs": len(rows), "date_clusters": len(dates), "market_clusters": len(markets),
            "delta": float(values.sum()/present.sum()), "exploratory_95_ci": np.quantile(draws, [.025, .975]).tolist(),
            "draws": len(draws), "seed": 860922}


def report():
    """Publish only compact derived evidence; raw responses remain ignored."""
    import subprocess
    base = "agent-report-2026-09-86a-settlement-truth-after-the-source-switch"
    target = docs_path("roadmap", base + ".md")
    analysis = json.loads((ROOT / "analysis.json").read_text())
    inv = json.loads((ROOT / "inventory.json").read_text())
    if inv["labels_provenance"].get("sha256") != "73054e9d1f831fc3062d9a033ffb3ce0bf6e78ea19b138bd5001a0426e3fee13":
        raise ValueError("dated report prose is bound to the frozen 86a input; fresh inputs require a new report")
    rules = json.loads((ROOT / "rules.json").read_text())
    # Git's text policy is LF: hash the published bytes, not Windows CSV newlines.
    station_bytes = (ROOT / "station_days.csv").read_bytes().replace(b"\r\n", b"\n")
    station_path = target.with_name(base + "-station-days.csv")
    station_path.write_bytes(station_bytes)
    diff_path = target.with_name(base + "-disagreements.csv")
    with diff_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["comparison", "market", "date", "candidate", "reference", "difference", "unit"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(analysis["differences"])
    receipt_path = target.with_name(base + "-provenance.json")
    metas = [json.loads(p.read_text()) for p in sorted((ROOT / "cache").glob("*.json"))]
    code_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    provenance = {"instrument_commit": code_head, "script_sha256": sha(Path(__file__).read_bytes()),
        "labels": inv["labels_provenance"], "config_sha256": inv["config_sha256"],
        "station_days_sha256": sha(station_bytes), "disagreements_sha256": sha(diff_path.read_bytes()),
        "tables": analysis["tables"], "recovery": analysis["recovery"], "requests": metas}
    # Publication does not carry the workstation's absolute input path.
    provenance["labels"] = {k: v for k, v in provenance["labels"].items() if k != "path"}
    dump(receipt_path, provenance)
    lines = [
        "# 86a - Settlement truth after the source switch",
        "",
        "**UNDECIDABLE: the workstation has no post-switch WU/venue panel. Free METAR reproduces all 480 available pre-switch WU degrees and 504/504 recorded venue bands, but that does not qualify it after the source switch. Candidate observations cover all 156 historically missing station-days; verified recovery remains unknown because their winning bands were not supplied.**",
        "",
        "Historical measurement, 2026-09-22. Implements the owner's named 86a handoff from "
        "`origin/codex/reward-test-attended-handoff-20260921` at `0e47b5d1`. Nothing adopted.",
        "",
        "## Evidence boundary",
        "",
        "Requested interval: 2026-07-01 through 2026-09-21, 83 local dates x 12 built-in MarketSpecs = "
        "996 possible station-days. The appendix enumerates that superset; it does not claim all were captured. "
        "The frozen workstation CSV identifies 504 captured market-days (42 dates x 12 markets), ending August 11: "
        "480 WU daily-summary labels and 24 `local_missing` rows (August 8 and 11). All 504 have recorded venue bands. "
        "Its SHA-256 is `" + inv["labels_provenance"]["sha256"] + "`. This is a historical projection, not ledger authority or current production state.",
        "",
        "The fetched master's generated event config contains current active events, not the missing historical "
        "winner panel. No production access or ledger mutation was attempted. The only individually specified "
        "post-switch WU/venue row is the handed-down Miami September 2 control: WU 89 F versus venue band 90-91 F. "
        "It is explicitly marked `supplied EF10c audit control` in the appendix, separate from the local CSV.",
        "",
        "The [named production audit](audits/full-audit-2026-09-18/dimensions/gap-settlement-truth-source.md) "
        "supplies historical 921/921 pre-switch and 131/132 post-switch band agreement and identifies 156 missing "
        "WU labels on 13 dates. Those totals were not remeasured here. The subsequently fetched state of play "
        "reports backfills, so 156 is not asserted to be the number still missing on production today.",
        "",
        "## Method and source limits",
        "",
        "Every observation is assigned to MarketSpec's own civil calendar day and native unit; half-up whole-degree "
        "rounding uses `weather.units`. WU uses only `daily_summary` labels with a matching settlement unit. "
        "No snapshot fallback, band midpoint, or absent value becomes a degree. Observation availability is not a "
        "complete-day or promotion-countable label guarantee.",
        "",
        "- `asos`: all available IEM/NCEI one-minute temperatures, through the existing ASOS normalizer; "
        "timestamp header `valid(Etc/UTC)` is normalized explicitly. Toronto is unsupported and KBKF returned no "
        "one-minute temperature rows. Gaps can severely depress a maximum. "
        "[IEM documentation](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=) describes its NCEI origin and availability delay.",
        "- `metar`: routine and special reports from IEM (`report_type=3,4`), normalized by "
        "`weather.sources.metar_history`. `metar_with_6h` additionally admits US RMK `1snTxTxTx` maxima only "
        "when the entire six-hour window ending at the report timestamp lies inside the local date. "
        "Boundary-crossing windows and 24-hour standard-time summaries are excluded. This conservative composite "
        "can still miss the boundary part of a day's high. "
        "[NOAA decoding](https://aviationweather.gov/help/data/) defines the signed tenths-Celsius group.",
        "- `nws`: keyless station observations with bounded pagination and local-day filtering; rejected or missing "
        "temperatures are excluded. The returned history reaches only September 15-21 (84 station-days); "
        "September 15 begins partway through the day. No NWS observation is available for the historical 13-date gap set.",
        "- `metar_hourly` and `nws_hourly`: separate diagnostics implementing the WRH documented minute filter "
        "(51-59 for US NWS/FAA stations; 56-04 for other platforms including Toronto). This does not establish "
        "identical feed selection, revisions, or rounding to the binding web page. "
        "[WRH help](https://www.weather.gov/wrh/timeseries?site=klga) documents the filter and says displayed data are preliminary.",
        "",
        "The [public NWS API repository discussion](https://github.com/weather-gov/api/discussions/854) "
        "attributes the Weather and Hazards Viewer to Synoptic and the API to MADIS. This is public support "
        "correspondence, not a station-by-station equivalence specification. The WRH help itself does not establish "
        "that its entire historical Temp column equals `api.weather.gov`. No undocumented endpoint, Synoptic API, "
        "embedded page token, paid source, or access-control workaround was used.",
        "",
        "## Agreement counts",
        "",
        "Pre: July 1-August 22 (636 possible station-days). Post: August 23-September 21 (360). "
        "`Available` includes partial observed maxima. Band and exact-degree comparisons each use their own "
        "nonmissing denominator. **Post comparisons with denominator 1 are solely the supplied Miami control, "
        "not a post-switch sample.** NWS 0/0 means no comparable reference, not zero accuracy.",
        "",
        "| Period | Candidate | Available / possible | Venue matches / pairs | WU exact degrees / pairs | Venue D x M |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for t in analysis["tables"]:
        lines.append(f"| {t['stratum']} | {t['candidate']} | {t['available']}/{t['potential_days']} | {t['band_matches']}/{t['band_pairs']} | {t['wu_exact_matches']}/{t['wu_pairs']} | {t['date_clusters']} x {t['market_clusters']} |")
    lines += ["", "Exact-degree signs are candidate minus WU in the native unit; Celsius and Fahrenheit are never averaged together.", "",
              "| Period | Candidate | Signed degree differences (count) |", "| --- | --- | --- |"]
    for t in analysis["tables"]:
        if t["candidate"] != "wu":
            detail = "; ".join(f"{k} ({v})" for k, v in t["signed_difference_counts"].items()) or "No pairs"
            lines.append(f"| {t['stratum']} | {t['candidate']} | {detail} |")
    lines += ["", "## Uncertainty and interpretation", "",
        "Exploratory paired candidate-minus-WU band agreement uses independent date and market resampling, "
        "2,000 crossed-bootstrap draws, seed 860922. It is paired on available WU and candidate rows; "
        "it is not the difference between the unpaired table rates. No model was scored, no candidate fitted, "
        "no preregistered decision applied, and no alpha budget spent. Power/MDE for a confirmatory post-switch "
        "decision is not estimable from one selected control. A future qualification needs a preregistered "
        "estimand and powered panel. No model-artifact regimes are pooled.", "",
        "| Pre candidate | Paired n; D x M | Delta percentage points | Exploratory crossed 95% interval, pp |",
        "| --- | ---: | ---: | ---: |"]
    for t in analysis["tables"]:
        d = t["paired_band_delta"]
        if t["stratum"] == "pre" and t["candidate"] != "wu" and d and "delta" in d:
            lo, hi = d["exploratory_95_ci"]
            lines.append(f"| {t['candidate']} | {d['pairs']}; {d['date_clusters']} x {d['market_clusters']} | {100*d['delta']:.3f} | [{100*lo:.3f}, {100*hi:.3f}] |")
    lines += ["", "METAR's all-success paired rows produce a degenerate [0,0] empirical interval: "
        "this cannot prove population equivalence or post-switch non-inferiority. The hourly-only pre-switch "
        "difference is **not distinguishable from zero** under this exploratory resampling. Post-switch "
        "superiority/equivalence is unidentified, not an observed precise null. The Fahrenheit venue bands "
        "generally contain two degrees (or an open tail), so a winning band alone cannot identify the exact "
        "venue degree. Candidate-versus-WU degree differences do not prove venue-versus-WU degree errors.",
        "", "## Recovery count", "",
        "The handed-down gap set is August 28-September 1, September 4-10, and September 13: "
        "13 dates x 12 markets = 156. Counts below are conditional on that historical audit, not current "
        "production missingness. Best observed pre-switch agreement is the routine-plus-SPECI METAR candidate. "
        "It supplies an observed maximum on 156/156 gap days; whether those maxima match their venue winners "
        "is unknown (0 paired winners available). **Zero recoveries are verified; the true recoverable count "
        "is unknown, not zero.** No label was written.", "",
        "| Candidate | Historical missing days | Observed maximum available | All 24 hours represented | Available venue pairs |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for r in analysis["recovery"]:
        lines.append(f"| {r['candidate']} | {r['historically_missing']} | {r['observed_max_available']} | {r['all_24_hours_represented']} | {r['venue_pairs']} |")
    lines += ["", "Hourly coverage is a sampling diagnostic, not proof the physical maximum was observed. "
        "The Miami control is informative: METAR and hourly METAR give 89 F, while one-minute ASOS and the "
        "six-hour composite give 90 F and land in the supplied 90-91 F winner. One selected disagreement "
        "cannot establish a source's overall post-switch agreement.",
        "", "## Current binding Rules", "",
        "The public Gamma response for [NYC September 22](https://polymarket.com/event/"+rules["event_slug"]+") "
        "names NOAA and the LaGuardia WRH time-series page. Its description includes this exact sentence:", "",
        '> This market will resolve off of the Hourly Data provided using the "Show Hourly Data" button.', "",
        "It also specifies WU fallback if NOAA data remain unavailable by 11:59 PM ET the following day, "
        "whole-degree Fahrenheit precision, and a revision cutoff when the first following-day datapoint appears. "
        "The current sentence does not prove all past events used identical Rules.", "",
        "Response fetched `"+rules["response"]["fetched_at_utc"]+"`; raw-byte SHA-256 `"+rules["response"]["sha256"]+"`. "
        "The ignored cache retains the original response; the provenance appendix records its URL and digest.",
        "", "## Complete evidence appendices", "",
        f"- [{station_path.name}]({station_path.name}): all 996 named station-days, source degrees, sample/hour coverage, WU values, venue bands and reference origin.",
        f"- [{diff_path.name}]({diff_path.name}): all {len(analysis['differences'])} comparison disagreements, each with market, date, candidate, reference, unit and signed exact-degree difference where defined.",
        f"- [{receipt_path.name}]({receipt_path.name}): source hashes, request statuses/URLs, agreement tables, crossed intervals and recovery counts.",
        "",
        "Raw public responses and normalized series remain under ignored `data/settlement_truth_86a/`. "
        "HTTP 429 probes were retained, collection paused, then reduced to documented multi-station requests "
        "15 seconds apart. Final batch requests succeeded. Network failures are not weather missingness. "
        "No alternate host or credential was used to evade a limit.",
        "", "## Reproduction and verification", "",
        "From this branch's repository root, use the project Python interpreter. Inputs and cached responses "
        "are local runtime evidence and are not guaranteed in a clean checkout. `inventory` may read a fresh "
        "projection on the owner host, but that is a new measurement unless its hash matches the one above. "
        "`analyze` and `report` are offline; `fetch`/`fetch-batch` never access the network without `--network`.", "",
        "```powershell",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py --help",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py inventory --labels data/backtest/market_day_labels.csv",
        "# Repeat for ranges 07-01..07-28, 07-29..08-25, 08-26..09-21:",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py fetch-batch --family metar --markets atlanta,austin,chicago,dallas,denver,houston,los-angeles,miami,nyc,san-francisco,seattle,toronto --start 2026-07-01 --end 2026-07-28 --network",
        "# ASOS groups: atlanta,austin,chicago; dallas,denver,houston; los-angeles,miami,nyc; san-francisco,seattle",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py fetch-batch --family asos --markets atlanta,austin,chicago --start 2026-07-01 --end 2026-07-28 --network",
        "# Repeat NWS for each of the 12 markets:",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py fetch --family nws --market nyc --start 2026-07-01 --end 2026-09-21 --network",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py fetch --family rules --market nyc --network",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py analyze",
        ".\\venv\\Scripts\\python.exe tools/settlement_truth_source_20260922.py report",
        "```", "",
        "Only invoke network commands outside RE-1 live. Interrupt the foreground collection immediately "
        "when the owner starts live; the local STOP sentinel also prevents new requests and aborts response streaming. "
        "One serial collector per cache is required. No scheduled or unattended collection was installed.",
        "", "Verification: focused deterministic tests run through `scripts/ops/workstation_heavy.ps1`; "
        "full-suite prohibition respected. The exact final test result and roll-verdict result are recorded in the handback below.",
        "", "## Git handback and what was NOT done", "",
        "Branch: `codex/settlement-truth-source-20260922`. Base: fetched `origin/master` "
        "`3b4232ae8e337c876f5771294914122b28ea5890`. Instrument commit: `"+code_head+"`. "
        "The final branch tip is returned with this report; its own hash cannot be embedded recursively.",
        "",
        "No serving, training, model scoring, label, config, ledger, floor, gate, release, EF/digest or production "
        "change; no credentials or `.env` read; no exchange mutation; no registration, restart, merge or full suite. "
        "Neither protected RE-1 worktree was accessed or modified. Existing main-checkout changes were untouched. "
        "No current capture-health, live-readiness or promotion-countability claim is made.",
    ]
    target.write_text("\n".join(lines)+"\n", encoding="utf-8", newline="\n")
    print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--labels", type=Path, required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--family", choices=(*FAMILIES, "rules"), required=True)
    p.add_argument("--market", required=True)
    p.add_argument("--start", default=str(START))
    p.add_argument("--end", default=str(END))
    p.add_argument("--network", action="store_true")
    p = sub.add_parser("fetch-batch")
    p.add_argument("--family", choices=("asos", "metar"), required=True)
    p.add_argument("--markets", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--network", action="store_true")
    sub.add_parser("analyze")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "inventory":
        inventory(args.labels)
    elif args.command == "fetch":
        fetch(args)
    elif args.command == "fetch-batch":
        fetch_batch(args)
    elif args.command == "analyze":
        analyze()
    else:
        report()


if __name__ == "__main__":
    main()
