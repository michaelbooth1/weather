"""95e bounded public fee desk study; no account, order or credential endpoints."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from weather.paths import data_path

OUT = Path(__file__).resolve().parent
CITIES = {"Toronto", "NYC", "Atlanta", "Austin", "Chicago", "Dallas", "Denver", "Houston", "Los Angeles", "Miami", "San Francisco", "Seattle", "Taipei"}
START = "2026-09-20T00:00:00+00:00"

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Public:
    def __init__(self, cache, offline=False):
        self.cache, self.offline, self.last, self.count = cache, offline, 0., 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, url):
        u = urllib.parse.urlsplit(url)
        allowed = {
            "gamma-api.polymarket.com": r"/events(?:/keyset|/slug/[a-z0-9-]+)?",
            "clob.polymarket.com": r"/(?:fee-rate|markets/0x[0-9a-fA-F]{64}|last-trade-price)",
            "data-api.polymarket.com": r"/(?:trades|v2/(?:trades|markets/trades|openapi.json))",
            "polygon.blockscout.com": r"/api/v2/transactions/0x[0-9a-fA-F]{64}/logs",
            "docs.polymarket.com": r"/(?:api-spec/(?:clob|data)-openapi.yaml|changelog/predictions.md|migrate/data-api-v1-to-v2.md|market-data/market-details.md)",
        }
        if u.scheme != "https" or u.hostname not in allowed or not re.fullmatch(allowed[u.hostname], u.path) or u.username or u.password:
            raise ValueError("Outside public GET allowlist")
        if any(re.search(r"key|auth|secret|signature|user|wallet", k, re.I) for k in urllib.parse.parse_qs(u.query)):
            raise ValueError("Account/credential parameter refused")
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / "responses" / (key + ".json.gz")
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        if self.offline:
            raise FileNotFoundError(url)
        if self.count >= 2000:
            raise RuntimeError("Request budget reached")
        # One global request start per 1.05 s: stricter than per-host throttling.
        self.cache.mkdir(parents=True, exist_ok=True)
        throttle = self.cache / "last_request_start.txt"
        prior = float(throttle.read_text()) if throttle.exists() else 0.
        time.sleep(max(0, 1.05 - (time.monotonic() - self.last), 1.05 - (time.time() - prior)))
        self.last = time.monotonic()
        throttle.write_text(str(time.time()))
        self.count += 1
        reply = {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat()}
        req = urllib.request.Request(url, headers={"User-Agent": "weather-fee-check/95e-public-research", "Accept": "application/json, text/plain"})
        try:
            with self.opener.open(req, timeout=40) as r:
                raw = r.read(20_000_001)
                if len(raw) > 20_000_000:
                    raise ValueError("Response size bound exceeded")
                reply.update(status=r.status, sha256=hashlib.sha256(raw).hexdigest())
                try:
                    reply["body"] = json.loads(raw)
                except ValueError:
                    reply["text"] = raw.decode("utf-8")
        except urllib.error.HTTPError as e:
            reply.update(status=e.code, error=str(e))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "xt", encoding="utf-8") as f:
            json.dump(reply, f, ensure_ascii=False)
        return reply

def url(host, path, **params):
    return "https://" + host + path + ("?" + urllib.parse.urlencode(sorted(params.items())) if params else "")

def probe(client, target):
    r = client.get(target)
    print(json.dumps({k:v for k,v in r.items() if k not in ("body", "text")}, indent=2))
    body = r.get("body")
    if isinstance(body, dict) and "items" in body and "blockscout" in target:
        print(json.dumps([{"address":x["address"]["hash"], "index":x["index"], "timestamp":x.get("block_timestamp"), "decoded":x.get("decoded")} for x in body["items"]], indent=2))
        print("next_page_params:", body.get("next_page_params"))
    elif isinstance(body, dict) and "paths" in body:
        print(json.dumps({k:v for k,v in body["paths"].items() if "trade" in k}, indent=2)[:35000])
        print(json.dumps({k:v for k,v in body.get("components", {}).get("schemas", {}).items() if "trade" in k.lower()}, indent=2)[:20000])
    elif body is not None:
        print(json.dumps(body[:1] if isinstance(body, list) else body, indent=2)[:15000])
    else:
        text = r.get("text", "")
        if "openapi.yaml" in target:
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if re.match(r"  /.*(?:builder|fee)", line):
                    print("\n".join(lines[i:i+90]))
        else:
            print(text[:45000])

def discover(client):
    events, routes = {}, []
    for closed in (False, True):
        params = dict(tag_id=84, closed=str(closed).lower(), limit=100)
        if closed:
            params.update(order="closedTime", ascending="false")
        seen = set()
        for page in range(100):
            r = client.get(url("gamma-api.polymarket.com", "/events/keyset", **params))
            if r["status"] != 200:
                raise RuntimeError(r)
            body = r["body"]
            items = body["events"]
            for e in items:
                m = re.match(r"Highest temperature in (.+?) on ", e["title"])
                if m and m[1] in CITIES:
                    # Recent closed events only; retain current open drafts for audit.
                    if not closed or (e.get("closedTime", "")[:10] >= "2026-09-20"):
                        events[str(e["id"])] = e
            old = closed and items and all(e.get("closedTime") and e["closedTime"][:10] < "2026-09-20" for e in items)
            cursor = body.get("next_cursor")
            if old or not cursor:
                routes.append({"closed": closed, "pages": page+1, "terminal_or_cutoff": True})
                break
            if cursor in seen:
                raise RuntimeError("Repeated cursor")
            seen.add(cursor)
            params["after_cursor"] = cursor
        else:
            raise RuntimeError("Discovery page bound reached")
    dump(client.cache/"discovery.json", {"since": START, "routes": routes, "events": list(events.values())})
    print(f"Retained {len(events)} event bodies across {len(CITIES)} requested families", flush=True)

def city(e):
    return re.match(r"Highest temperature in (.+?) on ", e["title"])[1]

def array(x):
    return json.loads(x) if isinstance(x, str) else x or []

def fee_fields(row):
    return {k:v for k,v in row.items() if "fee" in k.lower() or "rebate" in k.lower()}

def fees(client):
    d = json.loads((client.cache/"discovery.json").read_text(encoding="utf-8"))
    rows, samples = [], []
    sampled = set()
    for e in sorted(d["events"], key=lambda e:(city(e), e["slug"])):
        for m in e.get("markets", []):
            active = bool(e.get("active") and not e.get("closed") and m.get("active") and not m.get("closed") and m.get("acceptingOrders"))
            tokens = array(m.get("clobTokenIds"))
            rec = {"city": city(e), "event_id": str(e["id"]), "event_slug": e["slug"],
                   "market_id": str(m["id"]), "condition_id": m.get("conditionId"), "question": m.get("question"),
                   "created_at": m.get("createdAt"), "updated_at": m.get("updatedAt"), "closed_time": e.get("closedTime"),
                   "active_band": active, "tokens": tokens, "gamma_fee_fields": fee_fields(m)}
            if active and tokens:
                rec["clob_yes_fee_rate"] = client.get(url("clob.polymarket.com", "/fee-rate", token_id=tokens[0]))
                if city(e) not in sampled:
                    sampled.add(city(e))
                    rec["clob_no_fee_rate_control"] = client.get(url("clob.polymarket.com", "/fee-rate", token_id=tokens[1]))
                    r = client.get(url("clob.polymarket.com", "/markets/"+m["conditionId"]))
                    b = r.pop("body", {})
                    r["body"] = {k:b.get(k) for k in ("condition_id", "maker_base_fee", "taker_base_fee", "active", "closed", "accepting_orders")}
                    rec["clob_market_control"] = r
            rows.append(rec)
            if len([x for x in rows if x["active_band"]]) % 50 == 0 and active:
                print(f"Fee-rate reads: {sum(x['active_band'] for x in rows)} active bands", flush=True)
    dump(OUT/"fee_fields.json", rows)
    print(f"Fee phase complete: {sum(x['active_band'] for x in rows)} active of {len(rows)} bands", flush=True)

def trade_row(row):
    # Retain public execution identity and fees, omit trader profiles/wallets.
    keys = ("condition_id", "conditionId", "token_id", "asset", "side", "size", "price", "timestamp", "event_slug", "eventSlug", "transaction_hash", "transactionHash")
    return {**{k:row[k] for k in keys if k in row}, "fee_fields": fee_fields(row), "raw_field_names": sorted(row)}

def trades(client):
    d = json.loads((client.cache/"discovery.json").read_text(encoding="utf-8"))
    cutoff = datetime.fromisoformat(START).timestamp()
    pages, rows, controls = [], [], []
    controlled = set()
    for e in sorted(d["events"], key=lambda e:(city(e), e["slug"])):
        # Deliberate field-presence sample, not a full execution census. Date
        # bounds are ignored on the API's event shape, so filter locally.
        r = client.get(url("data-api.polymarket.com", "/v2/trades", event_id=e["id"], limit=100, taker_only="true"))
        data = r.get("body", {}).get("data", [])
        kept = [t for t in data if t.get("timestamp", 0) >= cutoff]
        pages.append({"city": city(e), "event_id": e["id"], "event_slug": e["slug"], "url": r["url"],
                      "retrieved_at": r["retrieved_at"], "status": r["status"], "sha256": r.get("sha256"),
                      "returned_rows": len(data), "rows_since_cutoff": len(kept), "pagination": r.get("body", {}).get("pagination")})
        rows.extend({"city": city(e), "event_id": str(e["id"]), **trade_row(t)} for t in kept)
        if kept and city(e) not in controlled:
            controlled.add(city(e))
            for hostpath, params in (("/v2/trades", {"event_id":e["id"], "limit":10, "taker_only":"false"}),
                                     ("/trades", {"market": kept[0]["condition_id"], "limit":10, "takerOnly":"true"})):
                c = client.get(url("data-api.polymarket.com", hostpath, **params))
                b = c.pop("body", {})
                c["city"] = city(e)
                c["rows"] = [trade_row(t) for t in (b if isinstance(b, list) else b.get("data", []))]
                controls.append(c)
        print(f"Trade-field sample: {len(pages)}/{len(d['events'])} events, {len(rows)} recent rows", flush=True)
    dump(OUT/"trade_pages.json", pages)
    dump(OUT/"trade_samples.json", rows)
    dump(OUT/"trade_controls.json", controls)

EXCHANGES = {"0xe111180000d2663c0091e4f400237545b87b996b", "0xe2222d279d744050d28e00520010520000310f59"}

def decoded_log(item):
    decoded = item.get("decoded") or {}
    return {"address":item["address"]["hash"], "index":item["index"], "timestamp":item.get("block_timestamp"),
            "method": decoded.get("method_call", "").split("(")[0],
            "parameters": {p["name"]:p["value"] for p in decoded.get("parameters", [])}}

def chain(client):
    rows = json.loads((OUT/"trade_samples.json").read_text(encoding="utf-8"))
    selected = {}
    for row in rows:
        day = datetime.fromtimestamp(row["timestamp"], timezone.utc).date().isoformat()
        if not "2026-09-20" <= day <= "2026-09-24" or not 0 < row["price"] < 1:
            continue
        key = (row["city"], day)
        if key not in selected or abs(row["price"]-.5) < abs(selected[key]["price"]-.5):
            selected[key] = row
    results = []
    for key, trade in sorted(selected.items()):
        path = "/api/v2/transactions/"+trade["transaction_hash"]+"/logs"
        r = client.get(url("polygon.blockscout.com", path))
        body = r.pop("body", {})
        items = list(body.get("items", []))
        next_params, page_proofs, cursors = body.get("next_page_params"), [], set()
        for _ in range(10):
            if not next_params:
                break
            marker = json.dumps(next_params, sort_keys=True)
            if marker in cursors:
                raise RuntimeError("Repeated chain-log cursor")
            cursors.add(marker)
            more = client.get(url("polygon.blockscout.com", path, **next_params))
            more_body = more.pop("body", {})
            page_proofs.append(more)
            if more["status"] != 200:
                break
            items.extend(more_body.get("items", []))
            next_params = more_body.get("next_page_params")
        all_logs = [decoded_log(x) for x in items]
        logs = [x for x in all_logs if x["address"].lower() in EXCHANGES]
        matches = {x["parameters"]["takerOrderHash"] for x in logs if x["method"] == "OrdersMatched"}
        fills = []
        for log in logs:
            if log["method"] != "OrderFilled":
                continue
            v = log["parameters"]
            side = int(v["side"])
            share_raw = Decimal(v["takerAmountFilled"] if side == 0 else v["makerAmountFilled"])
            cash_raw = Decimal(v["makerAmountFilled"] if side == 0 else v["takerAmountFilled"])
            shares = share_raw / 1_000_000
            price = cash_raw / share_raw if share_raw else Decimal(0)
            paid = Decimal(v["fee"]) / 1_000_000
            taker = v["orderHash"] in matches
            expected = shares * Decimal(".05") * price * (1-price) if taker else Decimal(0)
            fills.append({"index":log["index"], "order_hash":v["orderHash"], "role":"taker" if taker else "maker",
                          "token_id":v["tokenId"], "side":side, "shares":str(shares), "price":str(price),
                          "builder":v.get("builder"), "notional_pusd":str(cash_raw / 1_000_000),
                          "fee_raw":v["fee"], "fee_pusd":str(paid), "formula_unrounded_pusd":str(expected),
                          "fee_curve_equivalent_pusd":str(shares * Decimal(".05") * price * (1-price)),
                          "difference_pusd":str(paid-expected), "matches_selected_token":v["tokenId"]==trade["token_id"]})
        taker_total = sum((Decimal(x["fee_pusd"]) for x in fills if x["role"]=="taker"), Decimal(0))
        leg_formula = sum((Decimal(x["fee_curve_equivalent_pusd"]) for x in fills if x["role"]=="maker"), Decimal(0))
        charged = sum((Decimal(x["parameters"]["amount"])/1_000_000 for x in logs if x["method"]=="FeeCharged"), Decimal(0))
        results.append({**r, "city":key[0], "trade_day":key[1], "selected_public_trade":trade,
                        "complete_log_page":not next_params, "additional_page_proofs":page_proofs, "fills":fills,
                        "taker_order_count":len(matches), "fee_charged_events_total_pusd":str(charged),
                        "taker_fee_total_pusd":str(taker_total), "sum_maker_leg_curve_pusd":str(leg_formula),
                        "maker_leg_formula_difference_pusd":str(taker_total-leg_formula),
                        "exchange_logs":logs,
                        "collateral_transfers":[x for x in all_logs if x["address"].lower()=="0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"]})
        print(f"Chain check {len(results)}/{len(selected)}: {key}; fees {[x['fee_pusd'] for x in fills]}", flush=True)
    dump(OUT/"chain_fee_evidence.json", results)

def verify():
    fee_rows = json.loads((OUT/"fee_fields.json").read_text(encoding="utf-8"))
    trade_rows = json.loads((OUT/"trade_samples.json").read_text(encoding="utf-8"))
    pages = json.loads((OUT/"trade_pages.json").read_text(encoding="utf-8"))
    controls = json.loads((OUT/"trade_controls.json").read_text(encoding="utf-8"))
    chain_rows = json.loads((OUT/"chain_fee_evidence.json").read_text(encoding="utf-8"))
    active = [x for x in fee_rows if x["active_band"]]
    assert {x["city"] for x in active} == CITIES
    assert len({x["condition_id"] for x in active}) == len(active)
    assert all(x["clob_yes_fee_rate"]["status"] == 200 for x in active)
    assert all(x["tokens"][0] in x["clob_yes_fee_rate"]["url"] for x in active)
    assert all(x["timestamp"] >= datetime.fromisoformat(START).timestamp() for x in trade_rows)
    assert len(trade_rows) == sum(p["rows_since_cutoff"] for p in pages)
    assert {x["city"] for x in trade_rows} == CITIES
    fills = [f for r in chain_rows for f in r["fills"]]
    takers = [f for f in fills if f["role"] == "taker"]
    makers = [f for f in fills if f["role"] == "maker"]
    assert all(r["status"] == 200 and r["complete_log_page"] for r in chain_rows)
    assert len({r["selected_public_trade"]["transaction_hash"] for r in chain_rows}) == len(chain_rows)
    assert all(datetime.fromisoformat(log["timestamp"].replace("Z", "+00:00")).timestamp()
               == r["selected_public_trade"]["timestamp"]
               for r in chain_rows for log in r["exchange_logs"])
    assert all(any(f["matches_selected_token"] and f["role"]=="taker" for f in r["fills"]) for r in chain_rows)
    assert all(Decimal(r["fee_charged_events_total_pusd"]) == Decimal(r["taker_fee_total_pusd"]) for r in chain_rows)
    # A compatibility calculation, not a fetched historical builder fee profile.
    # Tiny notionals may admit several whole-bps rates at five-decimal precision.
    quantum = Decimal(".00001")
    floor5 = lambda value: value.quantize(quantum, rounding=ROUND_DOWN)
    excess = []
    for r in chain_rows:
        for f in r["fills"]:
            if f["role"] != "taker" or abs(Decimal(f["difference_pusd"])) <= quantum:
                continue
            compatible = [bps for bps in range(101)
                          if floor5(Decimal(f["formula_unrounded_pusd"]))
                          + floor5(Decimal(f["notional_pusd"]) * bps / 10000)
                          == Decimal(f["fee_pusd"])]
            excess.append({"city":r["city"], "trade_day":r["trade_day"],
                           "transaction_hash":r["selected_public_trade"]["transaction_hash"],
                           "builder":f["builder"], "fee_pusd":f["fee_pusd"],
                           "platform_formula_unrounded_pusd":f["formula_unrounded_pusd"],
                           "notional_pusd":f["notional_pusd"],
                           "compatible_builder_bps_under_separate_floor5":compatible})
    dump(OUT/"builder_reconciliation.json", {
        "interpretation":"Inferred compatibility with documented additive builder fees, assuming separate truncation to five decimals. Historical builder fee profiles were not fetched; these are not verified profile rates.",
        "outliers":excess})
    groups = []
    for name in sorted(CITIES):
        a = [x for x in active if x["city"]==name]
        t = [x for x in trade_rows if x["city"]==name]
        c = [x for x in chain_rows if x["city"]==name]
        groups.append({"city":name, "active_events":len({x["event_id"] for x in a}), "active_bands":len(a),
                       "gamma_fee_fields":sorted({json.dumps(x["gamma_fee_fields"], sort_keys=True) for x in a}),
                       "clob_base_fees":sorted({x["clob_yes_fee_rate"]["body"].get("base_fee") for x in a}),
                       "public_trade_sample_rows":len(t), "trade_days":sorted({datetime.fromtimestamp(x["timestamp"], timezone.utc).date().isoformat() for x in t}),
                       "rows_with_any_fee_field":sum(bool(x["fee_fields"]) for x in t), "chain_transactions":len(c)})
    summary = {"families":groups, "active_events":len({x["event_id"] for x in active}), "active_bands":len(active),
               "clob_no_controls":sum("clob_no_fee_rate_control" in x for x in active),
               "trade_control_pages":len(controls), "trade_control_rows":sum(len(x["rows"]) for x in controls),
               "trade_control_rows_with_fee_fields":sum(bool(r["fee_fields"]) for x in controls for r in x["rows"]),
               "historical_and_open_gamma_markets":len(fee_rows), "public_trade_sample_rows":len(trade_rows),
               "trade_pages":len(pages), "trade_pages_with_more":sum(bool((p["pagination"] or {}).get("has_more")) for p in pages),
               "public_trade_field_names":sorted({k for x in trade_rows for k in x["raw_field_names"]}),
               "trade_rows_with_fee_fields":sum(bool(x["fee_fields"]) for x in trade_rows),
               "trade_first_utc":datetime.fromtimestamp(min(x["timestamp"] for x in trade_rows),timezone.utc).isoformat(),
               "trade_last_utc":datetime.fromtimestamp(max(x["timestamp"] for x in trade_rows),timezone.utc).isoformat(),
               "chain_transactions":len(chain_rows), "chain_taker_fills":len(takers), "chain_maker_fills":len(makers),
               "chain_condition_clusters":len({r["selected_public_trade"]["condition_id"] for r in chain_rows}),
               "chain_utc_date_clusters":len({r["trade_day"] for r in chain_rows}),
               "chain_condition_utc_date_cells":len({(r["selected_public_trade"]["condition_id"],r["trade_day"]) for r in chain_rows}),
               "chain_positive_taker_fees":sum(Decimal(f["fee_pusd"])>0 for f in takers),
               "chain_positive_maker_fees":sum(Decimal(f["fee_pusd"])>0 for f in makers),
               "chain_takers_within_00001_of_platform_curve":sum(abs(Decimal(f["difference_pusd"]))<=quantum for f in takers),
               "chain_takers_exact_floor5_platform_curve":sum(floor5(Decimal(f["formula_unrounded_pusd"]))==Decimal(f["fee_pusd"]) for f in takers),
               "chain_excess_fee_orders":len(excess),
               "chain_excess_orders_with_nonzero_builder":sum(bool(f["builder"]) and int(f["builder"],16)!=0 for f in excess),
               "chain_fee_total_pusd":str(sum((Decimal(f["fee_pusd"]) for f in takers),Decimal(0))),
               "chain_first_utc":min(x["selected_public_trade"]["timestamp"] for x in chain_rows),
               "chain_last_utc":max(x["selected_public_trade"]["timestamp"] for x in chain_rows),
               "max_absolute_aggregate_formula_difference":str(max(abs(Decimal(f["difference_pusd"])) for f in takers)),
               "max_absolute_maker_leg_formula_difference":str(max(abs(Decimal(r["maker_leg_formula_difference_pusd"])) for r in chain_rows)),
               "fee_fetch_first":min(x["clob_yes_fee_rate"]["retrieved_at"] for x in active),
               "fee_fetch_last":max(x["clob_yes_fee_rate"]["retrieved_at"] for x in active)}
    dump(OUT/"summary.json", summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="families"}, indent=2))

def manifest(client):
    rows = []
    for path in sorted((client.cache/"responses").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            r = json.load(f)
        rows.append({k:r.get(k) for k in ("url", "retrieved_at", "status", "sha256")})
    rows.sort(key=lambda r:r["retrieved_at"])
    last, deviations = {}, []
    for row in rows:
        host = urllib.parse.urlsplit(row["url"]).hostname
        if host in last:
            gap = (datetime.fromisoformat(row["retrieved_at"])-datetime.fromisoformat(last[host]["retrieved_at"])).total_seconds()
            if gap < 1:
                deviations.append({"host":host, "gap_seconds":gap, "previous":last[host]["url"], "current":row["url"], "at":row["retrieved_at"]})
        last[host] = row
    value = {"requests":rows, "count":len(rows), "status_counts":dict(Counter(r["status"] for r in rows)),
             "subsecond_same_host_pairs":deviations,
             "note":"Two initial standalone CLOB shape probes preceded the cross-process throttle repair; main batch uses persistent 1.05-second spacing. Web documentation reader calls are outside this manifest."}
    dump(OUT/"request_manifest.json", value)
    print(json.dumps({k:v for k,v in value.items() if k!="requests"}, indent=2))

def main():
    sys.stdout.reconfigure(errors="backslashreplace")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("probe", "discover", "fees", "trades", "chain", "verify", "manifest"))
    p.add_argument("--url")
    p.add_argument("--cache", type=Path, default=data_path("research", "weather-fee-check-20260924"))
    p.add_argument("--offline", action="store_true")
    a = p.parse_args()
    c = Public(a.cache, a.offline)
    if a.command == "probe":
        probe(c, a.url)
    elif a.command == "discover":
        discover(c)
    elif a.command == "fees":
        fees(c)
    elif a.command == "trades":
        trades(c)
    elif a.command == "chain":
        chain(c)
    elif a.command == "verify":
        verify()
    elif a.command == "manifest":
        manifest(c)

if __name__ == "__main__":
    main()
