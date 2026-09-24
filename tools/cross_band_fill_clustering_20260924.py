"""Mission 94a: public-flow clustering, NOT identified hypothetical maker fills.

Public GET-only event/trade collection, public S3 object-list publication proxies,
and deterministic offline tables. No account/order/credential/environment loader.
Use the workstation-heavy wrapper for collect/analyze; selftest is network-free.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.paths import data_path

UTC = timezone.utc
START, END = date(2026, 8, 15), date(2026, 9, 23)
DEFAULT_ROOT = data_path("fill_clustering_94a")
GAMMA = "https://gamma-api.polymarket.com/events"
TRADES = "https://data-api.polymarket.com/v2/trades"
S3 = {m: f"https://noaa-{m}-bdp-pds.s3.amazonaws.com/" for m in ("gfs", "hrrr")}
STATION_MINUTES = {"atlanta": 52, "austin": 53, "chicago": 51, "dallas": 53,
                   "denver": 58, "houston": 53, "los-angeles": 53, "miami": 53,
                   "nyc": 51, "san-francisco": 56, "seattle": 53, "toronto": 0}
STATION_SOURCE = "d059cc78753757cec6cc1a6ba34cbe03a28f508c"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


class PublicCache:
    """One serial request per second per host; immutable keyed raw responses."""
    def __init__(self, root, *, online=False):
        self.root, self.online = Path(root), online
        self.session = requests.Session()
        self.session.trust_env = False  # no .netrc, proxy credentials, or env auth
        self.session.headers["User-Agent"] = "weather-public-research-94a/1"
        self.last = {}
        self.reads = 0

    def get(self, base, params):
        if base not in {GAMMA, TRADES, *S3.values()}:
            raise ValueError("outside exact public endpoint allowlist")
        url = base + "?" + urlencode(params, doseq=True)
        key = digest(url.encode())
        raw_path = self.root / "http" / (key + ".body")
        meta_path = raw_path.with_suffix(".json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            raw = raw_path.read_bytes()
            if meta["url"] != url or digest(raw) != meta["sha256"] or meta["status"] != 200:
                raise ValueError("cache identity/hash mismatch")
            return raw
        if not self.online:
            raise FileNotFoundError("uncached public request: " + url)
        host = urlsplit(url).netloc
        for attempt in range(3):
            time.sleep(max(0., self.last.get(host, 0.) + 1.05 - time.monotonic()))
            self.last[host] = time.monotonic()
            try:
                with self.session.get(url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
                    status = response.status_code
                    raw = bytearray()
                    for chunk in response.iter_content(65536):
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("public reply exceeds 8 MiB bound")
                    if status != 200:
                        raise RuntimeError(f"public HTTP {status}: {url}")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(raw)
                write_json(meta_path, {"url": url, "status": status, "sha256": digest(raw),
                                      "retrieved_at_utc": datetime.now(UTC).isoformat(), "bytes": len(raw)})
                self.reads += 1
                return bytes(raw)
            except (requests.RequestException, RuntimeError):
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")


def universe():
    rows = []
    for spec in sorted(all_specs(), key=lambda s: s.id):
        for ordinal in range((END - START).days + 1):
            day = START + timedelta(days=ordinal)
            rows.append({"city": spec.id, "timezone": spec.timezone, "station": spec.icao,
                         "target_date": day.isoformat(), "slug": event_slug_for_date(day, spec.id)})
    return rows


def collect(root):
    cache = PublicCache(root, online=True)
    expected = universe()
    events, coverage = {}, []
    for offset in range(0, len(expected), 20):
        batch = expected[offset:offset + 20]
        payload = json.loads(cache.get(GAMMA, {"slug": [r["slug"] for r in batch], "limit": 100}))
        requested = {r["slug"] for r in batch}
        if not isinstance(payload, list) or any(e["slug"] not in requested for e in payload):
            raise ValueError("Gamma returned an unrequested event")
        for event in payload:
            if event["slug"] in events:
                raise ValueError("duplicate Gamma event")
            events[event["slug"]] = event
    write_json(root / "universe.json", {"requested": expected, "events": events,
                                       "start": START.isoformat(), "end": END.isoformat()})
    for number, spec in enumerate(expected):
        event = events.get(spec["slug"])
        row = {**spec, "event_id": event["id"] if event else None, "api_rows": 0, "pages": 0,
               "pagination_exhausted": False, "error": None}
        if event is None:
            row["error"] = "Gamma event unavailable"
        else:
            path = root / "events" / (str(event["id"]) + ".json")
            if path.exists() and json.loads(path.read_text())["coverage"]["pagination_exhausted"]:
                saved = json.loads(path.read_text())
                row.update(saved["coverage"])
            else:
                pages, cursor, seen = [], None, set()
                try:
                    for _ in range(2000):
                        params = {"event_id": str(event["id"]), "taker_only": "true", "limit": 1000}
                        if cursor:
                            params["cursor"] = cursor
                        payload = json.loads(cache.get(TRADES, params))
                        trades = payload["data"]
                        if not isinstance(trades, list) or any(t["event_slug"] != spec["slug"] for t in trades):
                            raise ValueError("trade feed not bound to requested event")
                        # Retain page references; offline rebuild verifies raw HTTP bytes again.
                        url = TRADES + "?" + urlencode(params)
                        pages.append(digest(url.encode()))
                        row["api_rows"] += len(trades)
                        row["pages"] += 1
                        pagination = payload["pagination"]
                        cursor = pagination.get("next_cursor")
                        if not cursor:
                            if pagination.get("has_more"):
                                raise ValueError("has_more without cursor")
                            row["pagination_exhausted"] = True
                            break
                        if cursor in seen or not trades:
                            raise ValueError("non-progressing trade pagination")
                        seen.add(cursor)
                    else:
                        raise ValueError("event exceeds 2,000-page bound")
                except (ValueError, KeyError, RuntimeError, requests.RequestException) as exc:
                    row["error"] = str(exc)
                write_json(path, {"coverage": row, "pages": pages})
        coverage.append(row)
        write_json(root / "coverage.json", coverage)
        print(f"events {number+1}/{len(expected)}: {spec['slug']}: {row['api_rows']} rows, {row['error'] or 'OK'}", flush=True)


def collect_publications(root, *, online=True):
    cache = PublicCache(root, online=online)
    rows = []
    objects=set()
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    # Include two preceding trade days, plus following publication day.
    for ordinal in range((END - START).days + 4):
        day = START - timedelta(days=2) + timedelta(days=ordinal)
        compact = day.strftime("%Y%m%d")
        prefixes = [("gfs", f"gfs.{compact}/{hour:02d}/atmos/gfs.t{hour:02d}z.pgrb2.0p25.f000")
                    for hour in (0, 6, 12, 18)]
        prefixes.append(("hrrr", f"hrrr.{compact}/conus/"))
        # Last eligible trade ends by 07Z on END+1 (configured western cities).
        # Through 11Z supplies subsequent publication anchors, without future cycles.
        if day == END + timedelta(days=1):
            prefixes=[(model,prefix) for model,prefix in prefixes
                      if model=="hrrr" or int(prefix.split(".t")[-1][:2])<12]
        for model, prefix in prefixes:
            token,seen_tokens = None,set()
            for _ in range(50):
                params = {"list-type": "2", "prefix": prefix, "max-keys": 1000}
                if token:
                    params["continuation-token"] = token
                doc = ET.fromstring(cache.get(S3[model], params))
                for item in doc.findall("s:Contents", ns):
                    key = item.findtext("s:Key", namespaces=ns)
                    if model=="gfs" and key != prefix:
                        continue
                    if model=="hrrr" and not key.endswith("z.wrfsfcf00.grib2"):
                        continue
                    hour = int(key.split(".t")[-1][:2])
                    if day==END+timedelta(days=1) and hour>=12:
                        continue
                    if (model,key) in objects:
                        raise ValueError("repeated publication object")
                    objects.add((model,key))
                    rows.append({"model": model, "cycle_utc": datetime.combine(day, datetime.min.time(), UTC).replace(hour=hour).isoformat(),
                                 "published_utc": item.findtext("s:LastModified", namespaces=ns), "object": S3[model] + key})
                token = doc.findtext("s:NextContinuationToken", namespaces=ns)
                if doc.findtext("s:IsTruncated", namespaces=ns) != "true":
                    break
                if not token:
                    raise ValueError("truncated S3 listing without continuation")
                if token in seen_tokens:
                    raise ValueError("non-progressing S3 pagination")
                seen_tokens.add(token)
            else:
                raise ValueError("S3 listing exceeds 50-page bound")
        write_json(root / "publications.json", rows)
        if online:
            print(f"publication day {day}: {len(rows)} representative f000 object records", flush=True)
    return rows


def cached_json(root, key):
    raw = (root / "http" / (key + ".body")).read_bytes()
    meta = json.loads((root / "http" / (key + ".json")).read_text())
    if digest(raw) != meta["sha256"] or digest(meta["url"].encode()) != key or meta["status"] != 200:
        raise ValueError("raw cache identity/hash mismatch")
    return json.loads(raw)


def load_trades(root):
    """Validate raw pages and normalize only locally dated T+0/1/2 trades."""
    saved = json.loads((root / "universe.json").read_text())
    coverage = json.loads((root / "coverage.json").read_text())
    if saved["requested"] != universe() or len(coverage) != len(universe()):
        raise ValueError("requested-universe coverage is incomplete")
    cache=PublicCache(root)
    verified_events={}
    for offset in range(0,len(saved["requested"]),20):
        batch=saved["requested"][offset:offset+20]
        payload=json.loads(cache.get(GAMMA,{"slug":[r["slug"] for r in batch],"limit":100}))
        verified_events.update({e["slug"]:e for e in payload})
    if verified_events != saved["events"]:
        raise ValueError("derived Gamma universe differs from raw cache")
    if [c["slug"] for c in coverage] != [r["slug"] for r in saved["requested"]]:
        raise ValueError("coverage is not the ordered requested universe")
    rows, bands, rejected = [], [], Counter()
    for c in coverage:
        if not c["pagination_exhausted"] or c["error"]:
            continue
        e = saved["events"][c["slug"]]
        zone = ZoneInfo(c["timezone"])
        target = date.fromisoformat(c["target_date"])
        lo = int(datetime.combine(target - timedelta(days=2), datetime.min.time(), zone).timestamp())
        hi = int(datetime.combine(target + timedelta(days=1), datetime.min.time(), zone).timestamp())
        created = pd.Timestamp(e["createdAt"]).timestamp()
        lo = max(lo, int(np.ceil(created)))
        markets = sorted(e["markets"], key=lambda m: float(m["groupItemThreshold"]))
        lookup = {}
        for rank, m in enumerate(markets):
            outcomes = json.loads(m["outcomes"])
            prices = list(map(float, json.loads(m["outcomePrices"])))
            tokens = json.loads(m["clobTokenIds"])
            if sorted(outcomes)!=["No","Yes"] or len(prices)!=2 or len(set(tokens))!=2:
                raise ValueError("event market is not an exact binary token pair")
            yi = outcomes.index("Yes")
            settled = m.get("umaResolutionStatus") == "resolved" and m.get("closed") and sorted(prices)==[0.,1.]
            band_start = max(lo, int(np.ceil(pd.Timestamp(m.get("createdAt", e["createdAt"])).timestamp())))
            band = {"condition": m["conditionId"], "event": str(e["id"]), "city": c["city"],
                    "target_date": c["target_date"], "timezone": c["timezone"], "rank": rank,
                    "label": m["groupItemTitle"], "start": band_start, "end": hi,
                    "yes_won": int(prices[yi]) if settled else -1}
            bands.append(band)
            lookup[m["conditionId"]] = (band, dict(zip(tokens, outcomes)))
        manifest = json.loads((root / "events" / (str(e["id"]) + ".json")).read_text())
        if manifest["coverage"] != c:
            raise ValueError("event coverage manifest mismatch")
        seen, count, cursor = set(), 0, None
        for page_number,key in enumerate(manifest["pages"]):
            params={"event_id":str(e["id"]),"taker_only":"true","limit":1000}
            if cursor:
                params["cursor"]=cursor
            if digest((TRADES+"?"+urlencode(params)).encode())!=key:
                raise ValueError("trade cursor-chain identity mismatch")
            payload = cached_json(root, key)
            cursor=payload["pagination"].get("next_cursor")
            if (page_number==len(manifest["pages"])-1) != (not cursor):
                raise ValueError("trade cursor chain does not terminate exactly")
            if not cursor and payload["pagination"].get("has_more"):
                raise ValueError("terminal page still advertises more rows")
            for t in payload["data"]:
                count += 1
                if t["event_slug"] != c["slug"] or t["condition_id"] not in lookup:
                    raise ValueError("trade event/condition mismatch")
                band, tokens = lookup[t["condition_id"]]
                if tokens.get(t["token_id"]) != t["outcome"]:
                    raise ValueError("trade token/outcome mismatch")
                stamp, price, size = int(t["timestamp"]), float(t["price"]), float(t["size"])
                if not (np.isfinite(price) and np.isfinite(size) and 0 <= price <= 1 and size > 0
                        and t["side"] in ("BUY", "SELL") and t["outcome"] in ("Yes", "No")):
                    raise ValueError("invalid public trade fields")
                local = datetime.fromtimestamp(stamp, zone)
                ahead = (target - local.date()).days
                if ahead not in (0, 1, 2):
                    rejected["outside_T0_T2"] += 1
                    continue
                if stamp < band["start"] or stamp >= hi:
                    raise ValueError("trade outside event creation/exposure interval")
                identity = (t["transaction_hash"], t["token_id"], stamp, t["side"], price, size, t["proxy_wallet"])
                if identity in seen:
                    rejected["indistinguishable_duplicate_rows"] += 1
                    continue
                seen.add(identity)
                rows.append({"t": stamp, "minute": stamp // 60, "city": c["city"], "event": str(e["id"]),
                             "condition": band["condition"], "target_date": c["target_date"],
                             "ahead": ahead, "hour": local.hour, "local_date": local.date().isoformat(),
                             "side": t["side"], "outcome": t["outcome"], "price": price, "size": size,
                             "yes_direction": 1 if (t["side"] == "BUY") == (t["outcome"] == "Yes") else -1})
        if count != c["api_rows"]:
            raise ValueError("manifest row count mismatch")
    if not rows:
        raise ValueError("no validated T0/T1/T2 public rows")
    frame = pd.DataFrame(rows).sort_values(["t", "condition"]).reset_index(drop=True)
    return frame, pd.DataFrame(bands), coverage, dict(rejected)


def rolling_band_counts(frame, start, stop, width):
    """Minute starts [start,stop), forward half-open window of width minutes."""
    count = np.zeros(stop - start, dtype=np.int16)
    for _, b in frame.groupby("condition", sort=False):
        times = np.unique(b["minute"].to_numpy())
        # Union intervals of minute starts that include at least one occurrence.
        left, right = None, None
        for minute in times:
            a, z = max(start, int(minute) - width + 1), min(stop, int(minute) + 1)
            if a >= z:
                continue
            if right is not None and a <= right:
                right = max(right, z)
            else:
                if right is not None:
                    count[left-start:right-start] += 1
                left, right = a, z
        if right is not None:
            count[left-start:right-start] += 1
    return count


def cooccurrence(frame, bands, out):
    distributions, summaries, maxima, daily = [], [], [], []
    for scope in ("event", "city", "global"):
        grouped = [("all", bands)] if scope == "global" else bands.groupby(scope, sort=True)
        for name, meta in grouped:
            f = frame if scope == "global" else frame[frame[scope] == name]
            if f.empty:
                continue  # public empty histories are not evidence of no activity
            zone = UTC if scope == "global" else ZoneInfo(meta.iloc[0]["timezone"])
            for ahead in ("all", 0, 1, 2):
                selected = f if ahead == "all" else f[f["ahead"] == ahead]
                intervals = []
                event_meta=meta.groupby("event",sort=True).agg(
                    start=("start","min"),end=("end","max"),target_date=("target_date","first"),
                    timezone=("timezone","first"))
                for _, b in event_meta.iterrows():
                    if ahead == "all":
                        a, z = b["start"], b["end"]
                    else:
                        day = date.fromisoformat(b["target_date"]) - timedelta(days=ahead)
                        tz = ZoneInfo(b["timezone"])
                        a = max(b["start"], int(datetime.combine(day, datetime.min.time(), tz).timestamp()))
                        z = min(b["end"], int(datetime.combine(day + timedelta(days=1), datetime.min.time(), tz).timestamp()))
                    if a < z:
                        intervals.append((int(np.ceil(a / 60)), int(z // 60)))
                if not intervals:
                    continue
                start, stop = min(a for a,z in intervals), max(z for a,z in intervals)
                for width in (1, 5):
                    eligible = np.zeros(stop-start, dtype=bool)
                    for a, z in intervals:
                        eligible[a-start:max(a-start,z-width+1-start)] = True
                    counts = rolling_band_counts(selected, start, stop, width)
                    stamps = pd.to_datetime(np.arange(start,stop)*60, unit="s", utc=True).tz_convert(zone)
                    periods = (stamps.hour.to_numpy() // 6) * 6
                    for period in ("all", 0, 6, 12, 18):
                        take = eligible if period == "all" else eligible & (periods == period)
                        v = counts[take]
                        if not len(v):
                            continue
                        identity = {"scope": scope, "group": str(name), "ahead": str(ahead),
                                    "hour6": str(period), "window_seconds": width*60}
                        for k, n in zip(*np.unique(v, return_counts=True)):
                            distributions.append({**identity, "k": int(k), "windows": int(n)})
                        summaries.append({**identity, "windows": len(v), "nonzero": int((v>0).sum()),
                                          "k_ge2": int((v>=2).sum()), "k_ge3": int((v>=3).sum()), "max_k": int(v.max())})
                    if ahead == "all":
                        at = np.flatnonzero(eligible & (counts == counts[eligible].max()))[0]
                        maxima.append({"scope": scope, "group": str(name), "window_seconds": width*60,
                                       "max_k": int(counts[at]), "start_utc": stamps[at].tz_convert(UTC).isoformat()})
                        days=stamps.strftime("%Y-%m-%d").to_numpy()
                        for day in np.unique(days):
                            take=eligible & (days==day)
                            if take.any():
                                daily.append({"scope":scope,"group":str(name),"anchor_date":day,
                                              "window_seconds":width*60,"max_k":int(counts[take].max())})
            print("cooccurrence", scope, name, flush=True)
    pd.DataFrame(distributions).to_csv(out / "cooccurrence_distribution.csv", index=False)
    summary = pd.DataFrame(summaries)
    summary.to_csv(out / "cooccurrence_summary.csv", index=False)
    maxima = pd.DataFrame(maxima)
    maxima.to_csv(out / "cooccurrence_maxima.csv", index=False)
    pd.DataFrame(daily).to_csv(out / "cooccurrence_daily_maxima.csv", index=False)
    return summary, maxima


def hazards(frame, bands, out):
    """Exact source-band-second / eligible-target-band pair denominators.

    Target must exist and be T0..T2 throughout the future window; same-second
    unordered prints are excluded. Each target can contribute at most one hit.
    """
    anchors = frame.drop_duplicates(["condition", "t"]).sort_values("t").reset_index(drop=True)
    t = anchors.t.to_numpy()
    source_event, source_city = anchors.event.to_numpy(), anchors.city.to_numpy()
    source_band = anchors.condition.to_numpy()
    band_times = {name: np.unique(group.t.to_numpy()) for name, group in frame.groupby("condition", sort=False)}
    relation_names = ("same_event_other_band", "same_city_other_date", "other_city")
    rows = []
    for delta in (60, 300, 1800):
        den = np.zeros((len(anchors),3), dtype=np.int32)
        hit = np.zeros_like(den)
        for _, band in bands.iterrows():
            left, right = np.searchsorted(t, [band.start, band.end-delta], side="left")
            if left >= right:
                continue
            idx = np.arange(left,right)
            valid = source_band[idx] != band.condition
            idx = idx[valid]
            times = band_times.get(band.condition, np.array([], dtype=np.int64))
            relation = np.where(source_event[idx] == band.event, 0, np.where(source_city[idx] == band.city, 1, 2))
            den[idx,relation] += 1
            if len(times):
                nxt = np.searchsorted(times,t[idx],side="right")
                success = (nxt < len(times)) & (times[np.minimum(nxt,len(times)-1)] <= t[idx]+delta)
                hit[idx[success],relation[success]] += 1
        for ahead in ("all",0,1,2):
            for hour in ("all",0,6,12,18):
                take = np.ones(len(t),dtype=bool)
                if ahead != "all":
                    take &= anchors.ahead.to_numpy() == ahead
                if hour != "all":
                    take &= (anchors.hour.to_numpy()//6)*6 == hour
                for r,name in enumerate(relation_names):
                    ok = take & (den[:,r]>0)
                    d,h = int(den[ok,r].sum()),int(hit[ok,r].sum())
                    rows.append({"relation":name,"window_seconds":delta,"ahead":str(ahead),"hour6":str(hour),
                                 "source_anchors":int(ok.sum()),"eligible_pairs":d,"hit_pairs":h,
                                 "p_pair":h/d if d else None,
                                 "anchors_any_hit":int((hit[ok,r]>0).sum()),
                                 "p_any":float((hit[ok,r]>0).mean()) if ok.any() else None})
        print("hazard seconds",delta,flush=True)
    result = pd.DataFrame(rows)
    result.to_csv(out / "conditional_hazard.csv",index=False)
    return result


def nearest_lag(t,seconds):
    idx=np.searchsorted(seconds,t)
    before=seconds[np.maximum(idx-1,0)]
    after=seconds[np.minimum(idx,len(seconds)-1)]
    nearest=np.where(abs(t-before)<=abs(after-t),before,after)
    lag=(t-nearest)/60
    lag[(t<seconds[0])|(t>seconds[-1])]=np.nan
    return lag


def clock_alignment(frame, bands, root, out):
    anchors = frame.drop_duplicates(["condition","t"]).copy()
    minute = (anchors.t.to_numpy()/60)%60
    routine = anchors.city.map(STATION_MINUTES).to_numpy()
    clocks = {"METAR_routine":((minute-routine+30)%60)-30,
              "NBM_cycle":(((anchors.t.to_numpy()/60)-60+180)%360)-180}
    publications = collect_publications(root,online=False)
    publication_frame = pd.DataFrame(publications)
    publication_times={}
    for model in ("gfs","hrrr"):
        values = publication_frame.loc[publication_frame.model==model,"published_utc"]
        seconds = np.sort(np.array([pd.Timestamp(value).timestamp() for value in values]))
        if not len(seconds):
            raise ValueError("missing publication clock")
        publication_times[model]=seconds
        lag=nearest_lag(anchors.t.to_numpy(),seconds)
        clocks[model+"_object_publication"] = lag
    rows = []
    for name,lag in clocks.items():
        for ahead in ("all",0,1,2):
            take = np.ones(len(anchors),dtype=bool) if ahead=="all" else anchors.ahead.to_numpy()==ahead
            x = lag[take]
            rows.append({"clock":name,"ahead":str(ahead),"anchors":len(x),"clock_available":int(np.isfinite(x).sum()),
                         "before_5m":int(((x>=-5)&(x<0)).sum()),"after_5m":int(((x>=0)&(x<5)).sum()),
                         "outside_5m":int(((x < -5)|(x >= 5)).sum())})
    result=pd.DataFrame(rows)
    result.to_csv(out/"information_clock.csv",index=False)
    publication_frame.to_csv(out/"publication_proxies.csv",index=False)
    pd.DataFrame([{"model":m,"expected_objects":((END-START).days+3)*n+n//2,
                   "observed_objects":int((publication_frame.model==m).sum())}
                  for m,n in (("gfs",4),("hrrr",24))]).to_csv(out/"publication_coverage.csv",index=False)
    clusters=[]
    for name,meta in [*bands.groupby("city",sort=True),("global",bands)]:
        f=frame if name=="global" else frame[frame.city==name]
        intervals=[(int(np.ceil(m.start.min()/60)),int(m.end.max()//60))
                   for _,m in meta.groupby("event")]
        start,stop=min(a for a,z in intervals),max(z for a,z in intervals)
        minutes=np.arange(start,stop)
        lags=({"NBM_cycle":((minutes-60+180)%360)-180,
               **{m+"_object_publication":nearest_lag(minutes*60,s)
                  for m,s in publication_times.items()}}
              if name=="global" else {"METAR_routine":((minutes-STATION_MINUTES[name]+30)%60)-30})
        for width in (1,5):
            eligible=np.zeros(stop-start,dtype=bool)
            for a,z in intervals:
                eligible[a-start:max(a-start,z-width+1-start)]=True
            counts=rolling_band_counts(f,start,stop,width)
            for clock,lag in lags.items():
                for phase,mask in (("before_5m",(lag>=-5)&(lag<0)),
                                   ("after_5m",(lag>=0)&(lag<5)),
                                   ("outside_5m",(lag < -5)|(lag >= 5))):
                    v=counts[eligible&mask]
                    clusters.append({"clock":clock,"group":name,"window_seconds":width*60,"phase":phase,
                                     "windows":len(v),"k_ge2":int((v>=2).sum()),"sum_k":int(v.sum()),
                                     "max_k":int(v.max()) if len(v) else 0})
    pd.DataFrame(clusters).to_csv(out/"information_clock_clustering.csv",index=False)
    return result


def basket_bounds(meta,k,width):
    ordered=meta.sort_values("rank")
    return [(int(np.ceil(ordered.start.iloc[offset:offset+k].max()/60)),
             int(ordered.end.iloc[offset:offset+k].min()//60)-width+1)
            for offset in range(len(meta)-k+1)]


def no_basket_cost_and_loss(quantities,prices):
    if not quantities or len(quantities)!=len(prices):
        raise ValueError("basket legs must pair quantities and prices")
    cost=sum(q*p for q,p in zip(quantities,prices))
    return cost,cost-sum(quantities)+max(quantities)


def direction_and_baskets(frame, bands, out):
    """Minute-anchored observed-flow scenarios; never queue or touch inference."""
    directions, baskets = Counter(), []
    for event,f in frame.groupby("event",sort=True):
        meta=bands[bands.event==event].sort_values("rank")
        ranks=dict(zip(meta.condition,meta["rank"]))
        ordered=list(meta.condition)
        f=f.sort_values(["t","price"],ascending=[True,False])
        seconds=f.t.to_numpy()
        records=list(f[["condition","yes_direction","side","outcome","price"]].itertuples(index=False,name=None))
        winners=meta[meta.yes_won==1]
        resolved=len(winners)==1 and (meta.yes_won>=0).all()
        winner=winners.iloc[0].condition if resolved else None
        for width in (1,5):
            bounds={k:basket_bounds(meta,k,width) for k in (2,3)}
            # Only starts capable of a nonempty window; empty basket windows counted below.
            starts=sorted({int(m)-offset for m in f.minute.unique() for offset in range(width)})
            start_bound=int(np.ceil(meta.start.min()/60))
            end_bound=int(meta.end.min()//60)-width+1
            starts=[m for m in starts if start_bound<=m<end_bound]
            for minute in starts:
                lo,hi=np.searchsorted(seconds,[minute*60,(minute+width)*60],side="left")
                signed,offers={},{}
                for condition,sign,side,outcome,price in records[lo:hi]:
                    signed.setdefault(condition,set()).add(sign)
                    if side=="SELL" and outcome=="No":
                        offers.setdefault(condition,price)
                if len(signed)>=2:
                    directions[(width,"multi_band_windows")]+=1
                    if any(len(signs)>1 for signs in signed.values()):
                        directions[(width,"mixed_within_band")]+=1
                    else:
                        seq=[next(iter(signed[c])) for c in sorted(signed,key=ranks.get)]
                        changes=sum(a!=b for a,b in zip(seq,seq[1:]))
                        directions[(width,"one_crossing_mixed_sign" if changes==1 else
                                    "same_sign_only" if changes==0 else "multiple_crossings")]+=1
                # Earliest NO-sale second; highest price if that second is tied.
                # Equal size assumed, regardless of available size or our queue.
                if len(offers)<2:
                    continue
                for k in (2,3):
                    for offset in range(len(meta)-k+1):
                        a,z=bounds[k][offset]
                        if not a<=minute<z:
                            continue
                        legs=ordered[offset:offset+k]
                        filled=[c for c in legs if c in offers]
                        if len(filled)<2:
                            continue
                        cost,worst=no_basket_cost_and_loss([1]*len(filled),[offers[c] for c in filled])
                        payout=sum(c!=winner for c in filled) if resolved else None
                        baskets.append({"event":event,"city":meta.iloc[0].city,"target_date":meta.iloc[0].target_date,
                                        "window_seconds":width*60,"start_minute":minute,"basket_k":k,
                                        "first_rank":offset,"proxy_hit_legs":len(filled),"unit_reserve":cost,
                                        "unit_max_loss":worst,
                                        "unit_realized_loss":cost-payout if resolved else None})
        print("direction/basket event",event,flush=True)
    direction=pd.DataFrame([{"window_seconds":w*60,"classification":c,"windows":n} for (w,c),n in sorted(directions.items())])
    basket=pd.DataFrame(baskets)
    direction.to_csv(out/"direction_compatibility.csv",index=False)
    basket.to_csv(out/"basket_flow_scenarios.csv",index=False)
    # Denominator = every eligible minute x adjacent basket, including no sale.
    summary=[]
    for width in (1,5):
        for k in (2,3):
            denominator=sum(max(0,z-a) for _,m in bands.groupby("event")
                            for a,z in basket_bounds(m,k,width))
            chosen=basket[(basket.window_seconds==width*60)&(basket.basket_k==k)] if len(basket) else basket
            summary.append({"window_seconds":width*60,"basket_k":k,"eligible_basket_windows":denominator,
                            "multiple_NO_sale_windows":len(chosen),
                            "rate":len(chosen)/denominator if denominator else None,
                            "resolved_scenarios":int(chosen.unit_realized_loss.notna().sum()) if len(chosen) else 0,
                            "max_unit_realized_loss":float(chosen.unit_realized_loss.max()) if len(chosen) else None,
                            "max_unit_reserve":float(chosen.unit_reserve.max()) if len(chosen) else None,
                            "max_unit_basket_loss":float(chosen.unit_max_loss.max()) if len(chosen) else None})
    result=pd.DataFrame(summary)
    result.to_csv(out/"basket_summary.csv",index=False)
    return direction,result


def markdown_table(frame):
    def cell(x):
        if pd.isna(x):
            return "unavailable"
        if isinstance(x,float):
            return f"{x:.6g}"
        return str(x).replace("|","/").replace("\n"," ")
    lines=["| "+" | ".join(map(str,frame.columns))+" |",
           "| "+" | ".join("---" for _ in frame.columns)+" |"]
    lines.extend("| "+" | ".join(cell(x) for x in row)+" |" for row in frame.itertuples(index=False,name=None))
    return "\n".join(lines)


def report_tables(out):
    c=pd.read_csv(out/"cooccurrence_summary.csv",dtype={"ahead":str,"hour6":str})
    strata=c[c.hour6=="all"].groupby(["scope","ahead","window_seconds"],sort=True).agg(
        windows=("windows","sum"),k_ge2=("k_ge2","sum"),max_k=("max_k","max")).reset_index()
    strata["percent_ge2"]=100*strata.k_ge2/strata.windows
    strata.to_csv(out/"cooccurrence_by_day_ahead.csv",index=False)
    c=c[(c.ahead=="all")&(c.hour6=="all")]
    c=c.groupby(["scope","window_seconds"],sort=True).agg(
        windows=("windows","sum"),k_ge2=("k_ge2","sum"),k_ge3=("k_ge3","sum"),max_k=("max_k","max")).reset_index()
    c["percent_ge2"]=100*c.k_ge2/c.windows
    c["percent_ge3"]=100*c.k_ge3/c.windows
    h=pd.read_csv(out/"conditional_hazard.csv",dtype={"ahead":str,"hour6":str})
    h=h[(h.ahead=="all")&(h.hour6=="all")].drop(columns=["ahead","hour6"])
    k=pd.read_csv(out/"information_clock.csv",dtype={"ahead":str})
    k=k[k.ahead=="all"].drop(columns="ahead")
    cash=c[["scope","window_seconds","max_k"]].copy()
    cash["20_share_full_pair_funding_scenario"]=cash.max_k*20*.97
    cash["75_share_full_pair_funding_scenario"]=cash.max_k*75*.97
    cash.to_csv(out/"cash_funding_scenarios.csv",index=False)
    b=pd.read_csv(out/"basket_summary.csv")
    b["20_share_max_realized_scenario_loss"]=b.max_unit_realized_loss*20
    b["75_share_max_realized_scenario_loss"]=b.max_unit_realized_loss*75
    b.to_csv(out/"basket_summary_scaled.csv",index=False)
    d=pd.read_csv(out/"direction_compatibility.csv")
    ic=pd.read_csv(out/"information_clock_clustering.csv").groupby(
        ["clock","window_seconds","phase"],sort=True).agg(
            windows=("windows","sum"),k_ge2=("k_ge2","sum"),sum_k=("sum_k","sum"),max_k=("max_k","max")).reset_index()
    ic["percent_ge2"]=100*ic.k_ge2/ic.windows
    ic["mean_k"]=ic.sum_k/ic.windows
    panels=[("Co-occurrence (all trades, no touch identification)",c),
            ("Co-occurrence by local day-ahead",strata[strata.ahead!="all"]),
            ("Conditional hazard (strictly later, band-second anchors)",h),
            ("Information clock (anchor counts, no causal baseline)",k),
            ("Publication clock coverage",pd.read_csv(out/"publication_coverage.csv")),
            ("Clock-aligned clustering; phase refers to window start",ic.drop(columns="sum_k")),
            ("Funding scenario on max observed hit-band count; NOT would-fill notional",cash),
            ("Adjacent NO direct-sale flow scenarios; NOT maker fill probability",b),
            ("Same-event direction compatibility",d)]
    (out/"report_tables.md").write_text("\n\n".join("### "+name+"\n\n"+markdown_table(table) for name,table in panels)+"\n",encoding="utf-8")


def analyze(root):
    frame,bands,coverage,rejected=load_trades(root)
    out=root/"tables"
    out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(coverage).to_csv(out/"coverage.csv",index=False)
    bands.to_csv(out/"bands.csv",index=False)
    # Exclude an empty event feed from all exposure denominators.
    bands=bands[bands.event.isin(frame.event.unique())].copy()
    summary={"requested_events":len(coverage),"complete_event_feeds":sum(c["pagination_exhausted"] for c in coverage),
             "nonempty_T0_T2_events":frame.event.nunique(),"bands_in_nonempty_events":len(bands),
             "traded_bands":frame.condition.nunique(),"target_dates":frame.target_date.nunique(),
             "cities":frame.city.nunique(),"public_rows":sum(c["api_rows"] for c in coverage),
             "retained_rows":len(frame),"band_second_anchors":len(frame.drop_duplicates(["condition","t"])),
             "rejected":rejected,"station_source":STATION_SOURCE,
             "first_trade_utc":datetime.fromtimestamp(int(frame.t.min()),UTC).isoformat(),
             "last_trade_utc":datetime.fromtimestamp(int(frame.t.max()),UTC).isoformat(),
             "tool_sha256":digest(Path(__file__).read_bytes())}
    write_json(out/"support.json",summary)
    cache_inventory={}
    for meta_path in sorted((root/"http").glob("*.json")):
        meta=json.loads(meta_path.read_text())
        raw=meta_path.with_suffix(".body").read_bytes()
        if digest(raw)!=meta["sha256"] or digest(meta["url"].encode())!=meta_path.stem:
            raise ValueError("HTTP inventory digest mismatch")
        cache_inventory[meta_path.stem]={"sha256":meta["sha256"],"bytes":len(raw)}
    write_json(out/"cache_inventory.json",cache_inventory)
    frame.groupby(["city","target_date","ahead"],sort=True).size().rename("rows").reset_index().to_csv(out/"trade_support.csv",index=False)
    print(json.dumps(summary),flush=True)
    cooccurrence(frame,bands,out)
    hazards(frame,bands,out)
    clock_alignment(frame,bands,root,out)
    direction_and_baskets(frame,bands,out)
    report_tables(out)
    manifest={p.name:digest(p.read_bytes()) for p in sorted(out.glob("*")) if p.is_file() and p.name!="manifest.json"}
    write_json(out/"manifest.json",manifest)
    print("OFFLINE_TABLES_COMPLETE",flush=True)


def selftest():
    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="94a-selftest-") as temp:
        root=Path(temp)
        f=pd.DataFrame({"condition":["a","a","b","b"],"minute":[2,2,3,8]})
        assert rolling_band_counts(f,0,10,1).tolist()==[0,0,1,1,0,0,0,0,1,0]
        assert rolling_band_counts(f,0,10,5).tolist()==[2,2,2,1,1,1,1,1,1,0]
        rng=np.random.default_rng(94)
        random_frame=pd.DataFrame({"condition":rng.choice(["a","b","c"],100),
                                   "minute":rng.integers(0,30,100)})
        for width in (1,5):
            brute=[random_frame[(random_frame.minute>=m)&(random_frame.minute<m+width)].condition.nunique()
                   for m in range(30)]
            assert rolling_band_counts(random_frame,0,30,width).tolist()==brute
        lag=nearest_lag(np.array([0,100,130,160,200,201]),np.array([100.,200.]))
        assert np.isnan(lag[0]) and np.isnan(lag[-1])
        assert lag[1:5].tolist()==[0.,.5,-2/3,0.]
        c=PublicCache(root)
        try:
            c.get("https://example.com",{})
        except ValueError:
            pass
        else:
            raise AssertionError("endpoint allowlist did not reject")
        try:
            c.get(TRADES,{"event_id":"1"})
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("offline cache attempted network")
        url=TRADES+"?"+urlencode({"event_id":"1"})
        key=digest(url.encode())
        raw=b'{"test":true}'
        (root/"http").mkdir()
        (root/"http"/(key+".body")).write_bytes(raw)
        write_json(root/"http"/(key+".json"),{"url":url,"status":200,"sha256":digest(raw)})
        assert c.get(TRADES,{"event_id":"1"})==raw
        (root/"http"/(key+".body")).write_bytes(b"changed")
        try:
            c.get(TRADES,{"event_id":"1"})
        except ValueError:
            pass
        else:
            raise AssertionError("corrupted raw cache accepted")
        # Timestamps at the same second are unordered and cannot be a future hit.
        f=pd.DataFrame([{"t":t,"condition":b,"event":e,"city":city,"ahead":0,"hour":0}
                        for t,b,e,city in [(10,"a","e1","c1"),(10,"b","e1","c1"),
                                           (70,"b","e1","c1"),(71,"c","e2","c1"),(311,"d","e3","c2")]])
        b=pd.DataFrame([{"condition":band,"event":e,"city":city,"start":0,"end":10000}
                        for band,e,city in [("a","e1","c1"),("b","e1","c1"),("c","e2","c1"),("d","e3","c2")]])
        h=hazards(f,b,root)
        h=h[(h.ahead=="all")&(h.hour6=="all")&(h.window_seconds==60)].set_index("relation")
        assert h.loc["same_event_other_band","eligible_pairs"]==3
        assert h.loc["same_event_other_band","hit_pairs"]==1
        assert h.loc["same_city_other_date","hit_pairs"]==1
        assert h.loc["other_city","hit_pairs"]==0
        # Enumerate every exclusive outcome, including winner outside the basket.
        for quantities,prices in [([20],[.4]),([20,75],[.4,.7]),([20,0,75],[.3,.9,.8])]:
            cost,worst=no_basket_cost_and_loss(quantities,prices)
            payouts=[sum(q for j,q in enumerate(quantities) if j!=winner)
                     for winner in range(len(quantities)+1)]
            assert abs(worst-max(cost-payout for payout in payouts))<1e-12
        # Exercise raw-cache lineage and local midnight normalization end to end.
        fixture=root/"normalization"
        def reply(base,params,payload):
            url=base+"?"+urlencode(params,doseq=True)
            key=digest(url.encode())
            raw=json.dumps(payload).encode()
            (fixture/"http").mkdir(parents=True,exist_ok=True)
            (fixture/"http"/(key+".body")).write_bytes(raw)
            write_json(fixture/"http"/(key+".json"),{"url":url,"sha256":digest(raw),"status":200})
            return key
        spec={"city":"nyc","timezone":"America/New_York","station":"KLGA",
              "target_date":"2026-09-23","slug":"fixture-event"}
        event={"id":"fixture","slug":spec["slug"],"createdAt":"2026-09-21T01:00:00Z",
               "markets":[{"conditionId":"c1","groupItemThreshold":"0","groupItemTitle":"fixture band",
                           "outcomes":'["Yes","No"]',"outcomePrices":'["0","1"]',"clobTokenIds":'["yes1","no1"]',
                           "closed":True,"umaResolutionStatus":"resolved"}]}
        trades=[{"event_slug":spec["slug"],"condition_id":"c1","token_id":"yes1","outcome":"Yes",
                 "side":"BUY","price":.5,"size":2,"proxy_wallet":"public-fixture","transaction_hash":str(i),
                 "timestamp":int(pd.Timestamp(stamp).timestamp())} for i,stamp in enumerate(
                     ["2026-09-22T03:59:59Z","2026-09-22T04:00:00Z","2026-09-24T04:00:00Z"])]
        payload={"data":trades,"pagination":{"next_cursor":None,"has_more":False}}
        reply(GAMMA,{"slug":[spec["slug"]],"limit":100},[event])
        key=reply(TRADES,{"event_id":"fixture","taker_only":"true","limit":1000},payload)
        coverage={**spec,"event_id":"fixture","api_rows":3,"pages":1,"pagination_exhausted":True,"error":None}
        write_json(fixture/"universe.json",{"requested":[spec],"events":{spec["slug"]:event}})
        write_json(fixture/"coverage.json",[coverage])
        write_json(fixture/"events"/"fixture.json",{"coverage":coverage,"pages":[key]})
        with patch(__name__+".universe",return_value=[spec]):
            normalized,_,_,rejected=load_trades(fixture)
            assert normalized.ahead.tolist()==[2,1]
            assert rejected=={"outside_T0_T2":1}
            trades[0]["token_id"]="wrong"
            reply(TRADES,{"event_id":"fixture","taker_only":"true","limit":1000},payload)
            try:
                load_trades(fixture)
            except ValueError as exc:
                assert "token/outcome mismatch" in str(exc)
            else:
                raise AssertionError("unbound token accepted")
    print("SELFTEST_PASS",flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "publications", "analyze", "selftest"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    if args.command == "collect":
        collect(args.root)
    elif args.command == "publications":
        collect_publications(args.root)
    elif args.command == "analyze":
        analyze(args.root)
    else:
        selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
