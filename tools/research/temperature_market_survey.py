"""L3 S1 survey: which Polymarket daily temperature markets exist now, how much they trade, how wide their books are.

Public read-only International Polymarket reads only, through a URL allowlist:
  GET  https://gamma-api.polymarket.com/events?tag_slug=daily-temperature&closed=false&limit=..&offset=..
  POST https://clob.polymarket.com/books  (body: at most 50 {"token_id": ...} items)
No credentials, cookies or auth headers; stdlib only; no repository imports. Current prices only: events whose
eventDate is before today (UTC) are dropped before any book read, and no settlement or resolution field is kept.

Output (--out): events.json (Gamma snapshot, trimmed), books_<n>.json per snapshot, summary.csv, receipt.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import re
import statistics
import sys
import time
import urllib.parse
from pathlib import Path

GAMMA = "gamma-api.polymarket.com"
CLOB = "clob.polymarket.com"
UA = "weather-l3-survey/1 (research, read-only)"


def check(method: str, url: str, body) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.fragment or u.port:
        raise PermissionError(url)
    if method == "GET" and u.hostname == GAMMA and u.path == "/events":
        q = urllib.parse.parse_qs(u.query, strict_parsing=True)
        if set(q) <= {"tag_slug", "closed", "limit", "offset"} and q.get("closed") == ["false"]:
            return
    if method == "POST" and u.hostname == CLOB and u.path == "/books" and not u.query:
        if isinstance(body, list) and 0 < len(body) <= 50 and all(set(x) == {"token_id"} for x in body):
            return
    raise PermissionError(f"{method} {url}")


class Net:
    def __init__(self) -> None:
        self.requests = 0
        self.bytes = 0
        self.last = 0.0

    def call(self, method: str, url: str, body=None):
        check(method, url, body)
        wait = 0.25 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        u = urllib.parse.urlsplit(url)
        conn = http.client.HTTPSConnection(u.hostname, timeout=30)
        data = None if body is None else json.dumps(body).encode()
        headers = {"User-Agent": UA, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, u.path + (("?" + u.query) if u.query else ""), body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        self.last = time.monotonic()
        self.requests += 1
        self.bytes += len(raw)
        if resp.status != 200:
            raise RuntimeError(f"{method} {url} -> {resp.status}")
        return json.loads(raw.decode("utf-8"))


TITLE = re.compile(r"^(Highest|Lowest) temperature in (.+?) on ", re.I)


def fnum(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def trim_event(e: dict) -> dict | None:
    m = TITLE.match(e.get("title") or "")
    if not m:
        return None
    bands = []
    for mk in e.get("markets") or []:
        try:
            outcomes = json.loads(mk.get("outcomes") or "[]")
            tokens = json.loads(mk.get("clobTokenIds") or "[]")
        except ValueError:
            continue
        yes_token = tokens[outcomes.index("Yes")] if "Yes" in outcomes and len(tokens) == len(outcomes) else None
        bands.append({
            "label": mk.get("groupItemTitle"), "yes_token": yes_token,
            "active": mk.get("active"), "closed": mk.get("closed"), "accepting": mk.get("acceptingOrders"),
            "volume": fnum(mk.get("volumeNum")), "volume24hr": fnum(mk.get("volume24hr")),
            "liquidity": fnum(mk.get("liquidityNum")),
        })
    return {
        "family": m.group(1).lower(), "city": m.group(2).strip(), "slug": e.get("slug"), "event_id": e.get("id"),
        "event_date": e.get("eventDate"), "end_date": e.get("endDate"),
        "resolution_source": e.get("resolutionSource"),
        "description_station": _station_sentence(e.get("description") or ""),
        "event_volume": fnum(e.get("volume")), "event_volume24hr": fnum(e.get("volume24hr")),
        "event_liquidity": fnum(e.get("liquidity")), "bands": bands,
    }


def _station_sentence(text: str) -> str:
    m = re.search(r"recorded at (?:the )?(.+?) in degrees (Celsius|Fahrenheit)", text)
    return f"{m.group(1)} | {m.group(2)}" if m else ""


def best(levels, side):
    px = [fnum(l.get("price")) for l in levels or [] if (fnum(l.get("size")) or 0) > 0]
    px = [p for p in px if p is not None]
    if not px:
        return None
    return max(px) if side == "bid" else min(px)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--snapshots", type=int, default=3)
    ap.add_argument("--interval-seconds", type=int, default=300)
    ap.add_argument("--max-days-ahead", type=int, default=3)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    net = Net()
    started = dt.datetime.now(dt.timezone.utc)
    today = started.date()
    raw_events, offset = [], 0
    while True:
        page = net.call("GET", f"https://{GAMMA}/events?tag_slug=daily-temperature&closed=false&limit=100&offset={offset}")
        if not page:
            break
        raw_events.extend(page)
        offset += len(page)
        if offset > 20000:
            raise RuntimeError("runaway pagination")
    gamma_read = dt.datetime.now(dt.timezone.utc)
    events = []
    for e in raw_events:
        t = trim_event(e)
        if t is None or not t["event_date"]:
            continue
        d = dt.date.fromisoformat(t["event_date"])
        if not (today <= d <= today + dt.timedelta(days=a.max_days_ahead)):
            continue  # past events never get a book read (outcome-free); far-future ones are out of scope
        events.append(t)
    (out / "events.json").write_text(json.dumps({"gamma_read_utc": gamma_read.isoformat(), "n_raw": len(raw_events),
                                                  "events": events}, indent=1), encoding="utf-8")
    tokens = sorted({b["yes_token"] for e in events for b in e["bands"] if b["yes_token"]})
    snaps = []
    for n in range(a.snapshots):
        if n:
            time.sleep(a.interval_seconds)
        books = {}
        for i in range(0, len(tokens), 50):
            for bk in net.call("POST", f"https://{CLOB}/books", [{"token_id": t} for t in tokens[i:i + 50]]) or []:
                books[bk.get("asset_id")] = {"bid": best(bk.get("bids"), "bid"), "ask": best(bk.get("asks"), "ask")}
        snaps.append({"read_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "books": books})
        (out / f"books_{n}.json").write_text(json.dumps(snaps[-1]), encoding="utf-8")
    # Per (family, city): event-level medians over the events in range, spread medians over bands x snapshots.
    groups: dict = {}
    for e in events:
        groups.setdefault((e["family"], e["city"]), []).append(e)
    rows = []
    for (fam, city), evs in sorted(groups.items()):
        spreads, two_sided, n_band_obs = [], 0, 0
        for e in evs:
            for b in e["bands"]:
                for s in snaps:
                    bk = s["books"].get(b["yes_token"])
                    n_band_obs += 1
                    if bk and bk["bid"] is not None and bk["ask"] is not None:
                        two_sided += 1
                        spreads.append(bk["ask"] - bk["bid"])
        vol = [sum(b["volume"] or 0 for b in e["bands"]) for e in evs]
        v24 = [sum(b["volume24hr"] or 0 for b in e["bands"]) for e in evs]
        liq = [sum(b["liquidity"] or 0 for b in e["bands"]) for e in evs]
        rows.append({
            "family": fam, "city": city, "n_events": len(evs),
            "dates": ",".join(sorted(e["event_date"] for e in evs)),
            "median_event_volume": round(statistics.median(vol), 1),
            "median_event_volume24hr": round(statistics.median(v24), 1),
            "median_event_liquidity": round(statistics.median(liq), 1),
            "median_spread": round(statistics.median(spreads), 4) if spreads else "",
            "two_sided_share": round(two_sided / n_band_obs, 3) if n_band_obs else "",
            "resolution_source": evs[0]["resolution_source"], "station": evs[0]["description_station"],
        })
    import csv
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    receipt = {
        "started_utc": started.isoformat(), "gamma_read_utc": gamma_read.isoformat(),
        "book_reads_utc": [s["read_utc"] for s in snaps], "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoints": [f"GET https://{GAMMA}/events?tag_slug=daily-temperature&closed=false&limit=100&offset=<n>",
                      f"POST https://{CLOB}/books"],
        "requests": net.requests, "bytes": net.bytes, "n_raw_events": len(raw_events), "n_events_in_range": len(events),
        "n_tokens": len(tokens), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(json.dumps(receipt, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
