"""VR-5 trade reconciliation and prices-history backfill (journal only, public GETs only).

Conditions come from the VR-3 Gamma journal (``vr3_gamma``, read with ``capture_check``), limited to
``location_ids`` (the 12 built-ins first; pilots are added by config) and to events dated
``lookback_days_from``..``lookback_days_to`` days back. Each event date passes the fetch guard in
``capture`` mode first: a ``full`` embargo day is refused and never fetched.

- ``trades``: data-api ``/trades?market=<conditionId>`` paged by ``offset``; one row per trade keyed
  by ``transactionHash`` plus asset, side, wallet and a content hash. **Wallet addresses are kept**
  (``proxyWallet``, public on-chain identifiers; owner Q3 = A, DECISION_LOG 2026-10-15). Profile
  fields (name, pseudonym, bio, images) are dropped. No ``user`` filter is ever sent.
- ``prices_history``: CLOB ``/prices-history`` at 1-minute fidelity, **closed markets only**, once per
  token; the raw reply goes to the CAS (deduplicated by hash) and the row keeps a summary.

Bounds: ``max_requests_per_run``, the family's hourly request budget, and a byte rate of at most
``max_bytes_per_second`` (4 MiB/s). Only ``data-api.polymarket.com`` and ``clob.polymarket.com``
(International Polymarket) are requested; no order, account, credential or wallet-reader route.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from maker_core.venue.public_feed import ASSET, CONDITION
from weather.evidence.embargo import EmbargoRefused
from weather.evidence.envelope import ARCHIVE_PROXY, epoch_utc_text, utc_text
from weather.evidence.families.common import item, json_body, short_hash

PARSER_VERSION = "vr5-trades-1"
DATA_HOST, CLOB_HOST = "data-api.polymarket.com", "clob.polymarket.com"
VR3_FAMILY = "vr3_gamma"
TRADES, HISTORY = "trades", "prices_history"
TRADE_FIELDS = ("proxyWallet", "side", "asset", "conditionId", "size", "price", "timestamp", "outcome",
                "outcomeIndex", "transactionHash", "slug", "eventSlug")
DROPPED_PROFILE_FIELDS = ("name", "pseudonym", "bio", "profileImage", "profileImageOptimized", "icon", "title")
TRADES_LIMIT = 500
MAX_BYTES_PER_SECOND = 4 * 1024**2


class RunRequestCap(RuntimeError):
    pass


def trades_url(condition_id, offset) -> str:
    if not CONDITION.fullmatch(str(condition_id)):
        raise ValueError("not a condition id")
    return f"https://{DATA_HOST}/trades?" + urlencode(
        [("market", condition_id), ("limit", TRADES_LIMIT), ("offset", int(offset))])


def history_url(token_id, start_ts, end_ts) -> str:
    if not ASSET.fullmatch(str(token_id)):
        raise ValueError("not a token id")
    return f"https://{CLOB_HOST}/prices-history?" + urlencode(
        [("market", token_id), ("startTs", int(start_ts)), ("endTs", int(end_ts)), ("fidelity", 1)])


def allowed(url) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in (DATA_HOST, CLOB_HOST) and "user=" not in parts.query


def _tokens(value) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [str(t) for t in value or [] if ASSET.fullmatch(str(t))]


def conditions_from_vr3(rows, *, location_ids=None, event_days=None) -> list[dict]:
    """Latest VR-3 state per event → ``[{event_id, event_date, location, condition, tokens, closed}]``."""
    latest = {}
    for row in rows:
        key = row.get("key")
        if key is None:
            continue
        if key not in latest or str(row.get("first_seen_utc")) >= str(latest[key].get("first_seen_utc")):
            latest[key] = row
    out = []
    for key, row in sorted(latest.items()):
        body = row.get("body") or {}
        event_date = row.get("event_date")
        if location_ids and body.get("location") not in location_ids:
            continue
        if event_days is not None and event_date not in event_days:
            continue
        for market in body.get("markets") or []:
            condition = str(market.get("conditionId") or "")
            if not CONDITION.fullmatch(condition):
                continue
            out.append({"event_id": key, "event_date": event_date, "location": body.get("location"),
                        "condition": condition, "tokens": _tokens(market.get("clobTokenIds")),
                        "closed": bool(market.get("closed") or body.get("closed"))})
    return out


def trade_items(trades, *, condition) -> list[dict]:
    out = []
    for trade in trades if isinstance(trades, list) else []:
        if not isinstance(trade, dict) or not trade.get("transactionHash"):
            continue
        body = {k: trade.get(k) for k in TRADE_FIELDS}
        body["conditionId"] = body["conditionId"] or condition["condition"]
        body.update(event_id=condition["event_id"], location=condition["location"])
        key = "|".join([str(trade["transactionHash"]), str(trade.get("asset")), str(trade.get("side")),
                        str(trade.get("proxyWallet")), short_hash(json.dumps(body, sort_keys=True))])
        out.append(item(key, body, parser_version=PARSER_VERSION, basis=ARCHIVE_PROXY,
                        provider_time=epoch_utc_text(trade.get("timestamp")), event_date=condition["event_date"]))
    return out


def history_summary(payload) -> dict:
    points = payload.get("history") if isinstance(payload, dict) else None
    points = [p for p in points or [] if isinstance(p, dict) and "t" in p]
    times = [int(p["t"]) for p in points]
    return {"points": len(points), "first_t": epoch_utc_text(min(times)) if times else None,
            "last_t": epoch_utc_text(max(times)) if times else None}


class Bounded:
    """Per-run request cap and byte-rate pacing around ``ctx.fetch``."""

    def __init__(self, ctx, cfg):
        self.ctx, self.cap = ctx, int(cfg.get("max_requests_per_run", 600))
        self.rate = min(float(cfg.get("max_bytes_per_second", MAX_BYTES_PER_SECOND)), MAX_BYTES_PER_SECOND)
        self.spacing = float(cfg.get("spacing_seconds", 0.25))
        self.requests = 0

    def get(self, url):
        if not allowed(url):
            raise ValueError("not an allowlisted VR-5 read")
        if self.requests >= self.cap:
            raise RunRequestCap(f"{self.cap} requests this run")
        self.requests += 1
        response = self.ctx.fetch(url)
        self.ctx.sleep(max(self.spacing, len(response.body) / self.rate))
        return response


def read_vr3(ctx, capture_days) -> tuple[list[dict], list[str]]:
    from weather.evidence.reader import read
    rows, refused = [], []
    for day in capture_days:
        try:
            rows += read(VR3_FAMILY, utc_text(ctx.now()), "capture_check", days=[day], root=ctx.journal.root).rows
        except EmbargoRefused:
            refused.append(day)
    return rows, refused


def fetch_trades(ctx, bounded, condition, max_pages) -> int:
    changed = 0
    for page in range(int(max_pages)):
        response = bounded.get(trades_url(condition["condition"], page * TRADES_LIMIT))
        if response.status != 200:
            ctx.gap("http_status", status=response.status, condition=condition["condition"], page=page)
            break
        trades = json_body(response)
        trades = trades if isinstance(trades, list) else []
        changed += ctx.record(trade_items(trades, condition=condition), channel=TRADES,
                              meta={"condition": condition["condition"], "page": page,
                                    "trades_returned": len(trades)})["changed"]
        if len(trades) < TRADES_LIMIT:
            break
    return changed


def fetch_history(ctx, bounded, condition, cfg) -> int:
    event_day = date.fromisoformat(condition["event_date"])
    start = datetime.combine(event_day - timedelta(days=int(cfg.get("history_days_before", 2))), dtime.min,
                             tzinfo=timezone.utc)
    end = min(ctx.now(), datetime.combine(event_day + timedelta(days=int(cfg.get("history_days_after", 2)) + 1),
                                          dtime.min, tzinfo=timezone.utc))
    items = []
    for token in condition["tokens"]:
        if ctx.journal.seen(HISTORY, token):
            continue  # once per token
        response = bounded.get(history_url(token, start.timestamp(), end.timestamp()))
        if response.status != 200:
            ctx.gap("http_status", status=response.status, token=token)
            continue
        ref = ctx.journal.put_raw(response.body, channel=HISTORY)
        body = {"token": token, "condition": condition["condition"], "event_id": condition["event_id"],
                "location": condition["location"], "start_utc": utc_text(start), "end_utc": utc_text(end),
                "fidelity_minutes": 1, **history_summary(json_body(response))}
        items.append(item(token, body, parser_version=PARSER_VERSION, basis=ARCHIVE_PROXY, raw_ref=ref,
                          event_date=condition["event_date"]))
    return ctx.record(items, channel=HISTORY, meta={"condition": condition["condition"]})["changed"] if items else 0


def run(ctx, days=None) -> dict:
    cfg = ctx.cfg
    today = ctx.now().date()
    if days:
        event_days = sorted({d.isoformat() for d in days})
    else:
        event_days = [(today - timedelta(days=b)).isoformat()
                      for b in range(int(cfg.get("lookback_days_from", 1)), int(cfg.get("lookback_days_to", 3)) + 1)]
    first = min(date.fromisoformat(d) for d in event_days) - timedelta(days=int(cfg.get("vr3_capture_days_before", 4)))
    capture_days = [(first + timedelta(days=i)).isoformat() for i in range((today - first).days + 1)]
    rows, refused_capture = read_vr3(ctx, capture_days)
    allowed_days = []
    for day in event_days:
        try:
            ctx.guard(day, mode="capture")
            allowed_days.append(day)
        except EmbargoRefused:
            continue
    conditions = conditions_from_vr3(rows, location_ids=set(cfg.get("location_ids") or []) or None,
                                     event_days=set(allowed_days))
    bounded = Bounded(ctx, cfg)
    summary = {"event_days": allowed_days, "refused_event_days": sorted(set(event_days) - set(allowed_days)),
               "refused_capture_days": refused_capture, "conditions": len(conditions), "trade_rows": 0,
               "history_rows": 0}
    try:
        for condition in conditions:
            ctx.check_deadline()
            summary["trade_rows"] += fetch_trades(ctx, bounded, condition, cfg.get("max_pages", 20))
            if condition["closed"]:
                summary["history_rows"] += fetch_history(ctx, bounded, condition, cfg)
    except RunRequestCap as exc:
        ctx.journal.event("cap", {"reason": "max_requests_per_run", "detail": str(exc)}, channel=ctx.channel)
    summary["requests"] = bounded.requests
    return summary
