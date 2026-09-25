"""Credential-free bounded public reads and deterministic universe selection.

Uses the RE-1 bounded reader pattern (User-Agent, finite replies/timeouts),
without importing its authenticated transport, SDK, account or order modules.
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import time
from urllib.parse import urlparse

import requests

from weather.market.maker_evidence_store import encoded
from weather.market.reward_share_estimate import evaluate_sample, parse_levels

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
CONDITION = re.compile(r"0x[0-9a-fA-F]{64}\Z")


def discovery_projection(payload):
    """Keep all selection inputs, excluding unrelated volatile Gamma analytics."""
    fields = ("id", "conditionId", "active", "closed", "enableOrderBook", "clobTokenIds", "outcomes",
              "rewardsMinSize", "rewardsMaxSpread", "clobRewards")
    def market(row):
        return {key: row[key] for key in fields if key in row}
    if not isinstance(payload, list):
        raise ValueError("discovery response must be a list")
    return [{"id": row["id"], "slug": row["slug"], "markets": [market(m) for m in row["markets"]]}
            if "markets" in row else market(row) for row in payload]


class PublicReader:
    def __init__(self, store, *, timeout=5.0):
        self.store, self.timeout = store, timeout
        self.session = requests.Session()
        self.session.trust_env = False  # No netrc, environment auth or ambient proxy.
        self.session.headers.update({"User-Agent": "Mozilla/5.0 weather-passive-maker-evidence/1",
                                     "Accept": "application/json", "Accept-Encoding": "identity"})
        self.count, self.errors, self.bytes = 0, 0, 0
        self.latency_sum, self.latency_max = 0.0, 0.0
        self.latency_buckets = [0] * 7
        self.deadline = float("inf")

    def close(self):
        self.session.close()

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None):
        for attempt in range(2):
            try:
                return self._read_once(url, params=params, body=body, kind=kind, change_key=change_key)
            except (requests.ConnectionError, requests.Timeout, TimeoutError):
                if attempt or self.deadline - time.monotonic() <= .25:
                    raise
                time.sleep(.25)

    def _read_once(self, url, *, params=None, body=None, kind="discovery", change_key=None):
        parsed = urlparse(url)
        allowed = (
            (parsed.netloc == "gamma-api.polymarket.com" and parsed.path in ("/events", "/markets") and body is None)
            or (parsed.netloc == "clob.polymarket.com" and parsed.path == "/books" and isinstance(body, list))
            or (parsed.netloc == "clob.polymarket.com" and parsed.path.startswith("/rewards/markets/")
                and CONDITION.fullmatch(parsed.path.rsplit("/", 1)[1]) and body is None)
        )
        if not allowed or parsed.scheme != "https" or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("not an allowlisted public read")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("capture deadline reached")
        start = time.monotonic()
        self.count += 1
        timeout = min(self.timeout, remaining)
        try:
            with self.session.request("POST" if body is not None else "GET", url, params=params,
                                      json=body, timeout=timeout, stream=True, allow_redirects=False) as response:
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ValueError("public reply exceeds byte bound")
                    if time.monotonic() - start > timeout or time.monotonic() >= self.deadline:
                        raise TimeoutError("public reply exceeded wall deadline")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                self.bytes += len(raw)
                stored_body = None
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError):
                    payload = None
                    change_key = None  # Still journal the malformed wire reply.
                if response.status_code == 200 and kind == "discovery" and parsed.netloc == "gamma-api.polymarket.com":
                    try:
                        stored_body = encoded(discovery_projection(payload))
                        change_key = "discovery:" + hashlib.sha256(response.url.encode()).hexdigest()
                    except (ValueError, KeyError, TypeError):
                        stored_body = None
                        change_key = None
                self.store.record(kind, raw, metadata={"url": response.url,
                                  "http_status": response.status_code,
                                  "request_sha256": hashlib.sha256(encoded(body)).hexdigest(),
                                  "latency_seconds": time.monotonic() - start},
                                  change_key=change_key if response.status_code == 200 else None,
                                  stored_body=stored_body)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("unexpected public response status")
                return json.loads(raw)
        except Exception as exc:
            self.errors += 1
            self.store.event("request_error", {"url": url, "error_type": type(exc).__name__})
            raise
        finally:
            latency = time.monotonic() - start
            self.latency_sum += latency
            self.latency_max = max(self.latency_max, latency)
            index = next((i for i, edge in enumerate((.05, .1, .25, .5, 1., 2.)) if latency <= edge), 6)
            self.latency_buckets[index] += 1

    def metrics(self):
        return {"requests": self.count, "errors": self.errors, "response_bytes": self.bytes,
                "latency_mean_seconds": self.latency_sum / max(1, self.count),
                "latency_max_seconds": self.latency_max,
                "latency_bucket_upper_seconds": [.05, .1, .25, .5, 1., 2., None],
                "latency_bucket_counts": self.latency_buckets[:]}


def unique_rows(rows, *, key, on_duplicate=lambda value: None):
    seen = {}
    for row in rows:
        identity = str(row[key])
        if identity in seen:
            if encoded(row) != encoded(seen[identity]):
                raise ValueError(f"conflicting duplicate {key}: {identity}")
            on_duplicate(identity)
        else:
            seen[identity] = row
    return list(seen.values())


def reward_record(reader, condition):
    if not CONDITION.fullmatch(condition):
        raise ValueError("invalid condition id")
    rows, cursors, cursor = [], set(), None
    for _ in range(10):
        page = reader.read(CLOB + "/rewards/markets/" + condition,
                           params={"next_cursor": cursor} if cursor else None,
                           kind="rewards", change_key=f"reward:{condition}:{cursor or 'first'}")
        rows.extend(page["data"])
        cursor = page.get("next_cursor")
        if not cursor or cursor in ("LTE=", "-1"):
            break
        if cursor in cursors:
            raise ValueError("repeated reward cursor")
        cursors.add(cursor)
    else:
        raise ValueError("reward pagination exceeded bound")
    rows = unique_rows(rows, key="condition_id", on_duplicate=lambda cid:
                       reader.store.event("duplicate", {"source": "rewards", "condition_id": cid}))
    if any(row["condition_id"].lower() != condition.lower() for row in rows) or len(rows) > 1:
        raise ValueError("reward condition mismatch")
    return rows[0] if rows else None


def reward_rate(record, today):
    rates = []
    for row in record.get("rewards_config", []):
        if str(row["start_date"])[:10] <= today <= str(row["end_date"])[:10]:
            rate = float(row["rate_per_day"])
            if not math.isfinite(rate) or rate < 0:
                raise ValueError("invalid reward rate")
            rates.append(rate)
    return sum(rates)


def modelled_reward(book, reward, today):
    bids, bad_bids = parse_levels(book.get("bids"))
    asks, bad_asks = parse_levels(book.get("asks"))
    if bad_bids or bad_asks:
        raise ValueError("malformed book levels")
    result = evaluate_sample(bids, asks, max_spread_cents=float(reward["rewards_max_spread"]),
                             min_size=float(reward["rewards_min_size"]),
                             tick=float(book["tick_size"]), sizes=(20.,), distances_cents=(1.,),
                             min_size_for_mid=True)
    quote = result.get("quotes", {}).get((20., 1.), {})
    return reward_rate(reward, today) * quote.get("share_many", 0.)


def select_universe(candidates, *, extras=()):
    """Top ten PER CITY, reserve three per DTE when available, then best remainder."""
    selected, shortages = {}, []
    for city in sorted({row["city"] for row in candidates}):
        ranked = sorted((row for row in candidates if row["city"] == city),
                        key=lambda row: (-row["modelled_reward_20"], row["condition_id"]))
        chosen = {}
        for day in range(3):
            group = [row for row in ranked if row["day_ahead"] == day]
            if len(group) < 3:
                shortages.append({"city": city, "day_ahead": day, "available": len(group)})
            chosen.update((row["condition_id"], row) for row in group[:3])
        for row in ranked:
            if len(chosen) >= 10:
                break
            chosen[row["condition_id"]] = row
        selected.update(chosen)
    selected.update((row["condition_id"], row) for row in extras)
    return list(selected.values()), shortages
