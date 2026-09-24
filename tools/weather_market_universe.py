"""95d public weather-universe desk study. No credentials or exchange writes.

Collect caches immutable GET responses; rebuild is strictly offline. Run --help.
This is a research tool, not a production discovery/registration dependency.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from weather.paths import data_path, repo_path

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
FORECAST = "https://api.open-meteo.com"
TERMS = ("temperature", "rain", "precipitation", "snow", "hurricane", "storm", "heat", "climate", "drought", "flood", "tornado", "weather", "wildfire", "sea ice", "El Nino", "La Nina", "wind gust", "wind speed", "river", "lake", "hottest", "coldest", "hail", "blizzard", "monsoon", "humidity", "frost", "cyclone", "typhoon", "wave height")
TAG_SLUGS = ("weather", "climate-science", "climate", "natural-disasters", "hurricanes", "temperature", "rain", "snow")
WEATHER = re.compile(r"temperature|hottest|coldest|\brain\b|rainfall|precipitation|\bsnow\b|snowfall|hurricane|typhoon|cyclone|tornado|drought|flood|wildfire|sea ice|el ni.o|la ni.a|heatwave|heat wave|climate|weather|wind gust|wind speed|\briver\b|\blake\b|\bhail\b|blizzard|monsoon|humidity|frost|wave height|coral bleaching|natural disaster|heat warning|grid emergency|eclipse.*visible", re.I)
EXCLUDE = re.compile(r"\bvs\.?\s|Snowflake|Sophie Rain|SpaceX|pandemic|Measles|COVID|Coronavirus|Screwworm|meteor strike|moon landing|Largest IPO|West Nile|TFFF|Chinook|Ebola|Hantavirus|Blue Origin|AI data center|Flu Hospitalization|Cyclosporiasis|CDC issues|Election Winner|forces withdraw|renames Lake|quarterly earnings", re.I)

def weather_event(e):
    title = e.get("title", "")
    # Named storms can omit 'storm' from their title; their weather tag is evidence.
    tags = {str(t.get("id")) for t in e.get("tags", [])}
    return bool(WEATHER.search(title) or "84" in tags) and not EXCLUDE.search(title)

def stamp():
    return datetime.now(timezone.utc).isoformat()

def dt(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

class PublicCache:
    def __init__(self, root, online=False):
        self.root, self.online = root, online
        self.last = {}
        self.requests = 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, base, path, **params):
        if base not in (GAMMA, CLOB, FORECAST):
            raise ValueError("Non-public host")
        allowed = (r"/(tags(?:/slug/[a-z-]+)?|events(?:/keyset|/[0-9]+)?|public-search)",
                   r"/(rewards/markets/(?:current|0x[0-9a-fA-F]{64})|book)")
        pattern = r"/v1/forecast" if base == FORECAST else allowed[0 if base == GAMMA else 1]
        if not re.fullmatch(pattern, path) or any("key" in k.lower() or "token" in k.lower() and k != "token_id" for k in params):
            raise ValueError("Endpoint outside public-read allowlist")
        url = base + path + ("?" + urllib.parse.urlencode(sorted(params.items())) if params else "")
        key = hashlib.sha256(url.encode()).hexdigest()
        target = self.root / "responses" / (key + ".json.gz")
        if target.exists():
            with gzip.open(target, "rt", encoding="utf-8") as f:
                return json.load(f)
        if not self.online:
            raise FileNotFoundError(url)
        if self.requests >= 2500:
            raise RuntimeError("Request budget reached; cache preserved")
        time.sleep(max(0, 1.05 - (time.monotonic() - self.last.get(base, 0))))
        self.last[base] = time.monotonic()
        self.requests += 1
        result = {"url": url, "retrieved_at": stamp()}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "weather-universe-research/1.0", "Accept": "application/json"})
            with self.opener.open(req, timeout=40) as r:
                raw = r.read(20_000_001)
                if len(raw) > 20_000_000:
                    raise RuntimeError("Response exceeds 20 MB bound")
                result.update(status=r.status, body=json.loads(raw), body_sha256=hashlib.sha256(raw).hexdigest())
        except urllib.error.HTTPError as e:
            result.update(status=e.code, error=str(e))
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "xt", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def family(event):
    title = event.get("title", "")
    match = re.match(r"(Highest|Lowest) temperature in (.+?) on (.+?)\?", title, re.I)
    if match:
        return match[1].lower() + " temperature | " + match[2].replace("Seoul (Incheon)", "Seoul")
    # Preserve geography and thresholds for non-daily families; remove dates only.
    title = re.sub(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?!\w)(?:,?\s+20\d{2})?", "<date>", title)
    return re.sub(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", "<month>", title)

def in_scope(e, cutoff):
    if not e.get("closed"):
        return bool(e.get("active"))
    closed = dt(e.get("closedTime"))
    return closed is not None and closed >= cutoff

def collect(cache, asof):
    cutoff = dt(asof) - timedelta(days=60)
    events, routes, errors, sightings = {}, [], [], {}
    tag_ids = {"84"}
    for slug in TAG_SLUGS:
        reply = cache.get(GAMMA, "/tags/slug/" + slug)
        if reply["status"] == 200:
            tag_ids.add(str(reply["body"]["id"]))
        else:
            errors.append({"route": "tag:" + slug, "status": reply["status"]})
    def retain(items, route, observed_at, trusted=False):
        for e in items:
            if in_scope(e, cutoff) and (trusted or WEATHER.search(e.get("title", ""))):
                eid = str(e["id"])
                seen = sightings.setdefault(eid, {"first_seen": observed_at, "last_seen": observed_at})
                seen["first_seen"] = min(seen["first_seen"], observed_at)
                seen["last_seen"] = max(seen["last_seen"], observed_at)
                if eid not in events or len(e.get("markets", [])) > len(events[eid].get("markets", [])):
                    events[eid] = e
    for tag in sorted(tag_ids):
        for closed in (False, True):
            params = {"tag_id": tag, "closed": str(closed).lower(), "limit": 100}
            if closed:
                params.update(order="closedTime", ascending="false")
            seen, count, boundary = set(), 0, False
            for page in range(500):
                reply = cache.get(GAMMA, "/events/keyset", **params)
                if reply["status"] != 200:
                    errors.append({"route": params, "status": reply["status"]})
                    break
                body = reply["body"]
                items = body["events"]
                retain(items, "tag:" + tag, reply["retrieved_at"], trusted=True)
                count += len(items)
                times = [dt(e.get("closedTime")) for e in items]
                if closed and items and all(t is not None and t < cutoff for t in times):
                    boundary = True
                    break
                cursor = body.get("next_cursor")
                if not cursor:
                    boundary = True
                    break
                if cursor in seen:
                    raise RuntimeError("Repeated Gamma cursor")
                seen.add(cursor)
                params["after_cursor"] = cursor
                if page % 10 == 0:
                    print(f"tag {tag} closed={closed}: {count} scanned, {len(events)} retained", flush=True)
            routes.append({"tag": tag, "closed": closed, "pages": page + 1, "scanned": count, "terminal_or_cutoff": boundary})
    # Public search has an observed 10,000-result ceiling. Complement capped
    # broad searches with active-only and calendar-month partitions; the actual
    # closedTime-bounded tag walk remains the historical coverage backbone.
    search_routes = [(term, {}) for term in TERMS]
    for term in ("temperature", "weather"):
        search_routes.append((term, {"events_status": "active"}))
        months = { (cutoff + timedelta(days=i)).strftime("%B") for i in range(61) }
        search_routes.extend((term + " " + month, {}) for month in sorted(months))
    for term, extra in search_routes:
        seen = set()
        for page in range(1, 501):
            reply = cache.get(GAMMA, "/public-search", q=term, page=page, limit_per_type=100, keep_closed_markets=1, search_profiles="false", search_tags="false", sort="newest", **extra)
            if reply["status"] != 200:
                errors.append({"route": "search:" + term, "status": reply["status"]})
                break
            body = reply["body"]
            items = body.get("events") or []
            signature = tuple(e["id"] for e in items)
            if signature in seen and items:
                raise RuntimeError("Repeated search page")
            seen.add(signature)
            retain(items, "search:" + term, reply["retrieved_at"])
            if not body.get("pagination", {}).get("hasMore"):
                break
        routes.append({"search": term, "filters": extra, "pages": page, "http_status": reply["status"], "has_more": body.get("pagination", {}).get("hasMore")})
        print(f"search {term}: {len(events)} retained", flush=True)
    # Search can return partial event bodies. Hydrate missing markets only.
    for eid, event in list(events.items()):
        if not event.get("markets") or not event["markets"][0].get("conditionId"):
            reply = cache.get(GAMMA, "/events/" + eid)
            if reply["status"] == 200:
                events[eid] = reply["body"]
            else:
                errors.append({"event_id": eid, "status": reply["status"]})
    dump(cache.root / "discovery.json", {"asof": asof, "cutoff": cutoff.isoformat(), "routes": routes, "errors": errors, "sightings": sightings, "events": list(events.values())})
    print(f"Discovery complete: {len(events)} events", flush=True)

def array(value):
    return json.loads(value) if isinstance(value, str) else (value or [])

def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def target_date(e):
    m = re.search(r"-on-([a-z]+)-(\d{1,2})-(20\d{2})(?:-|$)", e.get("slug", ""))
    if not m:
        return None
    try:
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date()
    except ValueError:
        return None

def location_map():
    doc = json.loads(repo_path("config", "locations.json").read_text(encoding="utf-8"))
    return {row["city"]: row for row in doc["locations"]}

def viable_event(e, asof, locations):
    if e.get("closed") or not e.get("active"):
        return False
    target = target_date(e)
    city = family(e).split(" | ")[-1]
    zone = locations.get(city, {}).get("timezone", "UTC")
    if target and target < dt(asof).astimezone(ZoneInfo(zone)).date():
        return False
    return any(m.get("acceptingOrders") and not m.get("closed") for m in e.get("markets", []))

def enrich(cache):
    discovery = json.loads((cache.root / "discovery.json").read_text(encoding="utf-8"))
    rewards, routes = {}, []
    params, seen = {}, set()
    for page in range(200):
        reply = cache.get(CLOB, "/rewards/markets/current", **params)
        if reply["status"] != 200:
            raise RuntimeError(f"Reward page failed: {reply['status']}")
        body = reply["body"]
        for row in body["data"]:
            rewards[row["condition_id"]] = row
        cursor = body.get("next_cursor")
        if not cursor or cursor == "LTE=":
            break
        if cursor in seen:
            raise RuntimeError("Repeated reward cursor")
        seen.add(cursor)
        params["next_cursor"] = cursor
        if page % 10 == 0:
            print(f"current rewards: {len(rewards)}", flush=True)
    else:
        raise RuntimeError("Reward page budget reached")
    routes.append({"route": "current_rewards", "pages": page + 1, "count": len(rewards), "terminal": cursor})
    # At most one near-mid band per family and event target date. No claim of
    # temporal typicality: these are explicitly cross-sectional book samples.
    groups = defaultdict(list)
    locations = location_map()
    for e in discovery["events"]:
        if viable_event(e, discovery["asof"], locations) and weather_event(e):
            groups[family(e)].append(e)
    samples = []
    for fam, es in sorted(groups.items()):
        for e in sorted(es, key=lambda e: e.get("endDate", ""))[:3]:
            markets = [m for m in e.get("markets", []) if not m.get("closed") and m.get("conditionId")]
            if not markets:
                continue
            def rank(m):
                prices = array(m.get("outcomePrices"))
                return (m["conditionId"] not in rewards, abs((number(prices[0]) if prices else 0) - .5))
            m = min(markets, key=rank)
            cid = m["conditionId"]
            reply = cache.get(CLOB, "/rewards/markets/" + cid)
            rec = {"family": fam, "event_id": str(e["id"]), "condition_id": cid, "reward": reply, "books": []}
            tokens = array(m.get("clobTokenIds"))
            for token in tokens[:2]:
                rec["books"].append(cache.get(CLOB, "/book", token_id=token))
            samples.append(rec)
        print(f"sampled {fam}: {len(samples)} total bands", flush=True)
    dump(cache.root / "enrichment.json", {"routes": routes, "rewards": rewards, "samples": samples})

def forecast_probe(cache):
    results = []
    for city in ("Jinan", "Taipei", "Zhengzhou"):
        loc = location_map()[city]
        reply = cache.get(FORECAST, "/v1/forecast", latitude=loc["coordinates"]["lat"], longitude=loc["coordinates"]["lon"], daily="temperature_2m_max,temperature_2m_min", timezone=loc["timezone"], forecast_days=3)
        results.append({"city": city, "response": reply, "role": "Free supporting guidance, never settlement authority"})
    dump(cache.root/"forecast_probes.json", results)
    print(json.dumps(results, ensure_ascii=True))

BUILTIN_CITIES = {"Toronto", "NYC", "Atlanta", "Austin", "Chicago", "Dallas", "Denver", "Houston", "Los Angeles", "Miami", "San Francisco", "Seattle"}

def median(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None

def urls(e):
    candidates = [e.get("resolutionSource")]
    candidates += re.findall(r"https?://[^\s<>\"]+", e.get("description", ""))
    candidates += [m.get("resolutionSource") for m in e.get("markets", [])]
    return sorted({u.rstrip(".,)") for u in candidates if u})

def source_kind(e):
    text = e.get("description", "").lower()
    if "noaa" in text and "timeseries" in text:
        return "NOAA timeseries; WU fallback"
    if "hong kong observatory" in text:
        return "Hong Kong Observatory"
    if "wunderground" in text or "weather underground" in text:
        return "WU Daily Observations"
    return "; ".join(sorted({urllib.parse.urlsplit(u).netloc for u in urls(e)})) or "See exact rules; fallback/manual source"

def rule_stations(e):
    ids = set()
    for u in urls(e):
        site = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query).get("site", [])
        ids.update(s.upper() for s in site if re.fullmatch(r"[A-Za-z]{4}", s) and s.upper() != "NWS")
        m = re.search(r"/([A-Z]{4})(?:/|$)", u)
        if m:
            ids.add(m[1])
    return sorted(ids)

def units_mentioned(e):
    text = e.get("description", "")
    patterns = {"C": r"Celsius|°C|ºC", "F": r"Fahrenheit|°F|ºF", "mm": r"\bmm\b|millimeters|millimetres",
                "inches": r"\binches\b|PRECIPITATION \(IN\)", "feet": r"\bfeet\b|\bft\b",
                "meters": r"\bmeters\b|\bmetres\b", "mph": r"\bmph\b|miles per hour", "knots": r"\bknots\b",
                "km/h": r"\bkm/h\b|kilometers per hour", "percent": r"percent|percentage|%",
                "rank": r"\brank\b|ranked", "category": r"Saffir|Category [1-5]", "count": r"number of|how many"}
    return [unit for unit, pattern in patterns.items() if re.search(pattern, text, re.I)] or ["binary/event or rule-specific index"]

def book_metrics(reply, spread_cents):
    if reply.get("status") != 200:
        return {"status": reply.get("status"), "retrieved_at": reply["retrieved_at"]}
    b = reply["body"]
    bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
    asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
    bid = max((p for p, s in bids), default=None)
    ask = min((p for p, s in asks), default=None)
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    width = spread_cents / 100 if spread_cents is not None else None
    return {"status": 200, "retrieved_at": reply["retrieved_at"], "token_id": b.get("asset_id"),
            "best_bid": bid, "best_ask": ask, "spread": ask-bid if mid is not None else None,
            "bid_shares_total": sum(s for p,s in bids), "ask_shares_total": sum(s for p,s in asks),
            "bid_shares_within_reward_distance": sum(s for p,s in bids if abs(p-mid) <= width) if mid is not None and width is not None else None,
            "ask_shares_within_reward_distance": sum(s for p,s in asks if abs(p-mid) <= width) if mid is not None and width is not None else None,
            "distance_note": "Raw BBO midpoint, not venue adjusted midpoint or per-maker Q-score"}

def bucket(fam, live, source, pool):
    if not live:
        return "Not worth it", "No current tradable event in the snapshot; retain metadata and rediscover, no continuous capture.", 0, 0, 0
    if fam.startswith("highest temperature"):
        if source == "WU Daily Observations" and pool > 0:
            return "Ingest now", "Rewarded daily high, existing WU shape and free page; propose bounded evidence capture only, qualify station/cutoffs before serving.", 4, 1, 2
        return "Ingest later", "Daily high shape, but implement and validate the exact primary source, fallback, finalization and missing-data rules before adding settlement capture.", 3, 2, 3
    if fam.startswith("lowest temperature"):
        return "Ingest later", "Needs a daily-minimum contract, lower-tail bands, ceiling semantics and its named settlement adapter; do not reuse daily-high floors.", 3, 3, 3
    text = fam.lower()
    if any(x in text for x in ("earthquake", "megaquake", "volcano", "eruption", "kīlauea")):
        return "Not worth it", "Adjacent disaster-category event, not meteorological; no reuse of weather station/forecast infrastructure. Retain as taxonomy boundary, no capture proposal.", 2, 5, 4
    if any(x in text for x in ("climate clock", "natural disaster", "grid emergency", "grand prix", "weather delay", "mlb", "eclipse", "burning man")):
        return "Not worth it", "One-off or compound/manual outcome with weak reuse and extra resolution ambiguity; continuous capture not justified.", 1, 4, 5
    if "rain on" in text:
        return "Ingest later", "Implement per-city CLI liquid-equivalent 0.01-inch threshold; local STANDARD-time climate day, trace exclusion and next-day 14:00 ET cutoff.", 4, 3, 3
    if "precipitation in" in text:
        return "Ingest later", "New monthly accumulation adapter and exact station/region, precision, revision/fallback deadline; forecast is supporting evidence only.", 3, 3, 3
    if "tornado risk" in text:
        return "Ingest later", "Resolve against named SPC outlook/contour release, not observed tornado occurrence; needs spatial and issuance-time logic.", 4, 4, 4
    if any(x in text for x in ("hurricane", "typhoon", "cyclone", "storm", "nolo", "surigae")):
        return "Ingest later", "Needs agency-specific advisory/best-track, landfall, basin and intensity definitions; storm-specific fallback and revisions must be captured.", 3, 4, 4
    if any(x in text for x in ("drought", "river", "lake", "mississippi")):
        return "Ingest later", "Needs gauge/datum or published drought-index adapter, spatial scope, release lag and revision policy; sparse cadence can limit disk cost.", 3, 4, 3
    if any(x in text for x in ("hottest", "temperature increase", "niño", "nino", "ice extent", "coral")):
        return "Ingest later", "Needs index/rank/anomaly baseline, publication vintage and fallback logic; long-dated capital and slow finalization.", 3, 4, 3
    return "Ingest later", "Different weather quantity: implement exact station, unit, time window and settlement rules; first prove free source extraction and rewarded liquidity.", 2, 4, 4

def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["empty"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v for k,v in row.items()})

def rebuild(cache, output):
    discovery = json.loads((cache.root / "discovery.json").read_text(encoding="utf-8"))
    enrichment = json.loads((cache.root / "enrichment.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    locations, groups = location_map(), defaultdict(list)
    excluded = []
    for e in discovery["events"]:
        if weather_event(e):
            groups[family(e)].append(e)
        else:
            excluded.append({"event_id": e["id"], "title": e["title"], "reason": "Non-weather keyword/tag match"})
    rewards = enrichment["rewards"]
    families, events, markets, sample_rows = [], [], [], []
    for rec in enrichment["samples"]:
        rr = rec["reward"].get("body", {}).get("data", [])
        rr = next((r for r in rr if r.get("condition_id") == rec["condition_id"]), {})
        width = number(rr.get("rewards_max_spread"))
        sample_rows.append({"family": rec["family"], "event_id": rec["event_id"], "condition_id": rec["condition_id"],
                            "reward_http_status": rec["reward"]["status"], "market_competitiveness": rr.get("market_competitiveness"),
                            "rewards_min_size": rr.get("rewards_min_size"), "rewards_max_spread": width,
                            "reward_records": rr.get("rewards_config"), "books": [book_metrics(b, width) for b in rec["books"]]})
    for fam, es in sorted(groups.items()):
        live = [e for e in es if viable_event(e, discovery["asof"], locations)]
        city = fam.split(" | ")[-1] if " | " in fam else None
        loc = locations.get(city, {})
        representative = max(live or es, key=lambda e: (target_date(e).isoformat() if target_date(e) else e.get("createdAt", "")))
        live_sources = sorted({source_kind(e) for e in live})
        source = source_kind(representative)
        if len(live_sources) > 1:
            source = "Mixed active rules: " + " / ".join(live_sources)
        pool, rewarded, asset_pool, leads, bands, lead_hours = 0., 0, defaultdict(float), set(), [], []
        live_market_rows = []
        for e in sorted(es, key=lambda e: int(e["id"])):
            eligible = e in live
            target = target_date(e)
            lead = (target - dt(discovery["asof"]).astimezone(ZoneInfo(loc.get("timezone", "UTC"))).date()).days if target else None
            if eligible and lead is not None:
                leads.add(lead)
            if target and e.get("startDate"):
                start = dt(e["startDate"]).astimezone(ZoneInfo(loc.get("timezone", "UTC")))
                midnight = datetime.combine(target, datetime.min.time(), ZoneInfo(loc.get("timezone", "UTC")))
                lead_hours.append((midnight-start).total_seconds()/3600)
            bands.append(len(e.get("markets", [])))
            events.append({"event_id": str(e["id"]), "family": fam, "title": e["title"], "slug": e["slug"],
                           "active": e.get("active"), "closed": e.get("closed"), "eligible_snapshot": eligible,
                           "created_at": e.get("createdAt"), "start_date": e.get("startDate"), "end_date": e.get("endDate"), "closed_time": e.get("closedTime"),
                           "target_date": str(target) if target else None, "lead_days_snapshot": lead,
                           "bands": len(e.get("markets", [])), "volume_7d": e.get("volume1wk"), "volume_30d": e.get("volume1mo"),
                           "neg_risk": e.get("negRisk"), "source_urls": urls(e), "source_kind": source_kind(e)})
            for m in e.get("markets", []):
                cid = m.get("conditionId")
                reward = rewards.get(cid, {})
                configs = reward.get("rewards_config", []) if eligible and not m.get("closed") else []
                rate = sum(float(c.get("rate_per_day", 0)) for c in configs)
                if rate > 0:
                    rewarded += 1
                pool += rate
                for c in configs:
                    asset_pool[c.get("asset_address", "unknown")] += float(c.get("rate_per_day", 0))
                row = {"event_id": str(e["id"]), "family": fam, "market_id": m["id"], "condition_id": cid,
                       "question": m.get("question"), "band": m.get("groupItemTitle"), "closed": m.get("closed"), "accepting_orders": m.get("acceptingOrders"),
                       "reward_rate_current": rate if eligible else None, "reward_min_size": reward.get("rewards_min_size") if configs else None,
                       "reward_max_spread_cents": reward.get("rewards_max_spread") if configs else None,
                       "volume_7d": m.get("volume1wk"), "volume_30d": m.get("volume1mo"), "best_bid": m.get("bestBid"), "best_ask": m.get("bestAsk"),
                       "gamma_spread": m.get("spread"), "gamma_liquidity": m.get("liquidityNum"), "neg_risk": m.get("negRisk"),
                       "fees_enabled": m.get("feesEnabled"), "fee_type": m.get("feeType"), "fee_schedule": m.get("feeSchedule"),
                       "uma_resolution_statuses": m.get("umaResolutionStatuses"), "source_url": m.get("resolutionSource")}
                markets.append(row)
                if eligible and not m.get("closed"):
                    live_market_rows.append(row)
        disposition, reason, feasibility, build, risk = bucket(fam, live, source, pool)
        samples = [r for r in sample_rows if r["family"] == fam]
        bookrows = [b for r in samples for b in r["books"] if b.get("status") == 200]
        sample_spread = median([b.get("spread") for b in bookrows])
        if sample_spread is not None and sample_spread > .09:
            risk = max(risk, 4)
            reason += " Sampled spread exceeds 9 cents; thin-book/adverse-selection risk needs separate qualification."
        rows_for_vol = [e for e in es] # Sum distinct event rolling fields, never add nested market volume again.
        proposal = None
        if disposition == "Ingest now":
            proposal = {"location_id": loc.get("id"), "city": city, "station": loc.get("settlement", {}).get("station_id"),
                        "timezone": loc.get("timezone"), "unit": loc.get("market_unit"), "source": source,
                        "source_urls": urls(representative), "coordinates": loc.get("coordinates"),
                        "registry_action": "Location already exists in config/locations.json. Propose an explicit MarketSpec/capture selection referencing this location; do not duplicate location or hand-edit generated events.",
                        "market_type": "daily_high_temperature", "cutoff": "Local calendar date; Daily Observations maximum, first following-date print freezes revisions; next-day 23:59 ET missing-data fallback is lowest bracket."}
            proposal["proposed_external_registry_row"] = {
                "id": loc["id"], "city_label": city,
                "slug_prefix": loc["polymarket"]["event_slug_prefix"], "timezone": loc["timezone"],
                "display_unit": loc["market_unit"], "wu_history_id": loc["settlement"]["station_id"] + ":9:" + loc["country_code"],
                "icao": loc["settlement"]["station_id"], "lat": loc["coordinates"]["lat"], "lon": loc["coordinates"]["lon"],
                "sources": ["wu_history", "wu_current", "metar", "weather_forecast", "open_meteo"],
                "leading_obs": "metar", "coastal": False, "resolution_source": "wu_history"}
        families.append({"family": fam, "bucket": disposition, "reason": reason, "city": city,
                         "baseline_captured": fam.startswith("highest temperature") and city in BUILTIN_CITIES,
                         "unit": loc.get("market_unit") if city else "; ".join(units_mentioned(representative)),
                         "units_mentioned_in_rules": units_mentioned(representative),
                         "timezone": loc.get("timezone"), "station": loc.get("settlement", {}).get("station_id"),
                         "rule_station_ids": rule_stations(representative),
                         "station_name_registry": loc.get("settlement", {}).get("station_name"),
                         "precision": "one decimal C" if city == "Hong Kong" else "whole native degree" if city else "See exact rules",
                         "source": source, "source_urls": urls(representative), "recurrence": "daily" if city or " on <date>" in fam else "See family/rules",
                         "active_source_regimes": live_sources,
                         "events": len(es), "open_events": sum(not e.get("closed") for e in es), "eligible_events": len(live),
                         "bands_median": median(bands), "bands_min": min(bands), "bands_max": max(bands),
                         "lead_days_available_local": sorted(leads), "listing_hours_before_target_midnight_median": median(lead_hours),
                         "rewarded_conditions": rewarded, "pool_rate_per_day": pool, "pool_by_asset": dict(asset_pool),
                         "min_sizes": sorted({r["reward_min_size"] for r in live_market_rows if r["reward_min_size"] is not None}),
                         "max_spreads_cents": sorted({r["reward_max_spread_cents"] for r in live_market_rows if r["reward_max_spread_cents"] is not None}),
                         "volume_7d_reported_sum": sum(number(e.get("volume1wk")) or 0 for e in rows_for_vol),
                         "volume_30d_reported_sum": sum(number(e.get("volume1mo")) or 0 for e in rows_for_vol),
                         "volume_7d_missing_events": sum(e.get("volume1wk") is None for e in es),
                         "volume_30d_missing_events": sum(e.get("volume1mo") is None for e in es),
                         "volume_7d_complete": all(e.get("volume1wk") is not None for e in es),
                         "volume_30d_complete": all(e.get("volume1mo") is not None for e in es),
                         "gamma_spread_median_open": median([number(r["gamma_spread"]) for r in live_market_rows]),
                         "book_spread_median_sample": median([b.get("spread") for b in bookrows]),
                         "book_bid_depth_median_sample_shares": median([b.get("bid_shares_total") for b in bookrows]),
                         "book_ask_depth_median_sample_shares": median([b.get("ask_shares_total") for b in bookrows]),
                         "book_samples": len(bookrows), "competitiveness_median_sample": median([number(r["market_competitiveness"]) for r in samples]),
                         "plausible_reward_share": None, "share_reason": "Public aggregate depth cannot identify our per-maker Q-score share; no own-account observation.",
                         "neg_risk_values": sorted({bool(e.get("negRisk")) for e in es}),
                         "first_created_in_scope": min(e.get("createdAt", "") for e in es), "last_created_in_scope": max(e.get("createdAt", "") for e in es),
                         "first_target_in_scope": min((str(target_date(e)) for e in es if target_date(e)), default=None),
                         "last_target_in_scope": max((str(target_date(e)) for e in es if target_date(e)), default=None),
                         "reward_score_0_to_5": 0 if pool == 0 else min(5, 1 + sum(pool >= x for x in (10,50,200,500))),
                         "free_data_feasibility_0_to_5": feasibility, "build_cost_0_to_5": build, "risk_0_to_5": risk,
                         "capture_gib_per_day_planning": .1 if live else 0,
                         "free_forecast_plan": "Open-Meteo free global; METAR/SYNOP supporting observations. NBM only for US cities." if city else "National-agency free guidance or published index; adapter-specific validation required.",
                         "representative_event_id": representative["id"], "representative_url": "https://polymarket.com/event/" + representative["slug"],
                         "first_seen_this_run": min((discovery.get("sightings", {}).get(str(e["id"]), {}).get("first_seen", "") for e in es)),
                         "last_seen_this_run": max((discovery.get("sightings", {}).get(str(e["id"]), {}).get("last_seen", "") for e in es)),
                         "representative_rules_sha256": hashlib.sha256(representative.get("description", "").encode()).hexdigest(), "proposal": proposal})
    summary = {"schema": "weather_universe_desk_study_v1", "asof": discovery["asof"], "cutoff": discovery["cutoff"],
               "families": len(families), "events": len(events), "markets": len(markets), "excluded_events": len(excluded),
               "markets_without_condition_id": sum(not m["condition_id"] for m in markets),
               "buckets": dict(Counter(f["bucket"] for f in families)), "routes": discovery["routes"], "errors": discovery["errors"],
               "reward_routes": enrichment["routes"], "baseline_pool": sum(f["pool_rate_per_day"] for f in families if f["baseline_captured"]),
               "incremental_ingest_now_pool": sum(f["pool_rate_per_day"] for f in families if not f["baseline_captured"] and f["bucket"] == "Ingest now"),
               "all_weather_pool": sum(f["pool_rate_per_day"] for f in families),
               "daily_family_target_dates": len({(e["family"], e["target_date"]) for e in events if e["target_date"]}),
               "daily_target_date_clusters": len({e["target_date"] for e in events if e["target_date"]}),
               "daily_city_clusters": len({f["city"] for f in families if f["city"]}),
               "stale_open_daily_events": sum(e["active"] and not e["closed"] and e["target_date"] is not None and not e["eligible_snapshot"] for e in events),
               "incremental_ingest_now_gib_per_day": sum(f["capture_gib_per_day_planning"] for f in families if not f["baseline_captured"] and f["bucket"] == "Ingest now"),
               "interpretation": "Descriptive sequential public snapshot; pool is not income. No historical book/reward backfill, inference interval, power claim, or promotion evidence. 0.1 GiB/day/family is the handoff planning assumption, not measured.",
               "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cache.root/"discovery.json", cache.root/"enrichment.json")}}
    dump(output/"summary.json", summary)
    dump(output/"families.json", families)
    dump(output/"book_samples.json", sample_rows)
    if (cache.root/"forecast_probes.json").exists():
        dump(output/"forecast_probes.json", json.loads((cache.root/"forecast_probes.json").read_text(encoding="utf-8")))
    write_csv(output/"events.csv", events)
    write_csv(output/"markets.csv", markets)
    write_csv(output/"excluded.csv", excluded)
    proposals = [f["proposal"] for f in families if f["proposal"]]
    dump(output/"proposals.json", {"status": "PROPOSAL ONLY; no config write or runtime adoption", "proposals": proposals})
    lines = ["# 95d family buckets", "", "Generated by `tools/weather_market_universe.py rebuild`. Descriptive public snapshot; pool is shared, not earnings. Detailed fields and supporting event links are in `families.json`.", "", "| Family | Bucket | Eligible events | Pool/day | Source | Reason |", "| --- | --- | ---: | ---: | --- | --- |"]
    for f in sorted(families, key=lambda r: (r["bucket"], -r["pool_rate_per_day"], r["family"])):
        label = f["family"].replace("|", "/")
        lines.append(f"| [{label}]({f['representative_url']}) | {f['bucket']} | {f['eligible_events']} | {f['pool_rate_per_day']:.2f} | {f['source']} | {f['reason']} |")
    (output/"families.md").write_text("\n".join(lines)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("routes", "source_hashes")}, ensure_ascii=True, indent=2))

def verify_inventory(output):
    summary = json.loads((output/"summary.json").read_text(encoding="utf-8"))
    fams = json.loads((output/"families.json").read_text(encoding="utf-8"))
    with (output/"events.csv").open(encoding="utf-8", newline="") as f:
        events = list(csv.DictReader(f))
    with (output/"markets.csv").open(encoding="utf-8", newline="") as f:
        markets = list(csv.DictReader(f))
    assert len({e["event_id"] for e in events}) == len(events) == summary["events"]
    assert len(markets) == summary["markets"]
    assert len({m["market_id"] for m in markets}) == len(markets), "Duplicate Gamma market"
    identified = [m for m in markets if m["condition_id"]]
    assert len({m["condition_id"] for m in identified}) == len(identified), "Duplicate condition: pool could be double counted"
    missing = [m for m in markets if not m["condition_id"]]
    assert len(missing) == summary["markets_without_condition_id"]
    assert all(not m["reward_rate_current"] and m["accepting_orders"] != "True" for m in missing)
    assert len(fams) == summary["families"]
    assert sum(f["events"] for f in fams) == len(events)
    assert abs(sum(number(m["reward_rate_current"]) or 0 for m in markets) - summary["all_weather_pool"]) < 1e-6
    for fam in fams:
        rows = [m for m in markets if m["family"] == fam["family"]]
        assert abs(sum(number(m["reward_rate_current"]) or 0 for m in rows)-fam["pool_rate_per_day"]) < 1e-6
        if fam["bucket"] == "Ingest now":
            assert fam["pool_rate_per_day"] > 0 and fam["proposal"] and fam["source"] == "WU Daily Observations"
    print(f"PASS: {len(events)} distinct events, {len(markets)} distinct Gamma markets, {len(identified)} distinct conditions, {len(missing)} un-deployed/unidentified markets excluded from rewards; every family and pool total reconciles.")

def main():
    sys.stdout.reconfigure(errors="backslashreplace")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("collect", "enrich", "rebuild", "forecast-probe", "verify"))
    p.add_argument("--cache", type=Path, default=data_path("research", "weather-universe-20260924"))
    p.add_argument("--asof", default="2026-09-24T20:00:00+00:00")
    p.add_argument("--output", type=Path, default=repo_path("docs", "roadmap", "weather-market-universe-20260924"))
    p.add_argument("--offline", action="store_true", help="Forbid network and require all requested responses in cache")
    args = p.parse_args()
    cache = PublicCache(args.cache, online=not args.offline and args.command not in ("rebuild", "verify"))
    if args.command == "collect":
        collect(cache, args.asof)
    elif args.command == "enrich":
        enrich(cache)
    elif args.command == "forecast-probe":
        forecast_probe(cache)
    elif args.command == "verify":
        verify_inventory(args.output)
    else:
        rebuild(cache, args.output)

if __name__ == "__main__":
    main()
