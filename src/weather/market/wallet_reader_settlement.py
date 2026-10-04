"""Read-only settlement watcher behind the wallet reader's ``/settlement`` route.

Joins venue resolution state for held and recently filled markets with the local
WU settlement-proxy ledger, and flags disagreements, unredeemed winners and
resolved-but-unreconciled positions. Uses only the reader transport's existing
GET allow-list, minute budget, cache and journal; reads the ledger files directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re

from weather.market.wallet_reader_security import CONDITION, GAMMA, ReaderError

LEDGER_LINE_MAX_BYTES = 1024 * 1024
SLUG = re.compile(r"[a-z0-9-]{1,256}")


def band_key(label):
    """Compare band labels by their characters that carry meaning."""
    return re.sub(r"[^0-9a-z<>=.-]", "", str(label).lower().replace("°", "")) if label else None


def event_location(event_slug, events_config):
    for location in events_config.get("locations", []) if isinstance(events_config, dict) else []:
        prefix = location.get("event_slug_prefix")
        if isinstance(prefix, str) and prefix and isinstance(event_slug, str) and event_slug.startswith(prefix + "-"):
            return location.get("location_id")
    return None


def configured_bands(events_config):
    found = {}
    for location in events_config.get("locations", []) if isinstance(events_config, dict) else []:
        for event in location.get("active_events", []):
            for market in event.get("markets", []):
                if CONDITION.fullmatch(str(market.get("condition_id", ""))):
                    found[market["condition_id"].lower()] = market.get("range_label")
    return found


def ledger_labels(root, location_id, event_slugs):
    """Latest revision per event from ``<root>/<location>/ledger.jsonl`` in one streaming pass.

    Memory is bounded by ``LEDGER_LINE_MAX_BYTES`` plus one row per requested slug, whatever the
    file size. Lines longer than the limit are skipped; no pandas import.
    Returns ``({slug: row}, status)``; ``status`` is ``None`` when the file was read.
    """
    if not location_id or not re.fullmatch(r"[a-z0-9-]{1,64}", location_id):
        return {}, "proxy_not_applicable"
    wanted = {s for s in event_slugs if isinstance(s, str) and s}
    path = Path(root) / location_id / "ledger.jsonl"
    # Venue slugs are [a-z0-9-], which JSON never escapes, so a raw byte search safely skips the
    # parse of rows for other events; any other slug falls back to parsing every row.
    needles = [json.dumps(s).encode("ascii") for s in wanted] if all(SLUG.fullmatch(s) for s in wanted) else None
    best = {}
    try:
        if not path.is_file() or path.is_symlink():
            return {}, "proxy_ledger_absent"
        if not wanted:
            return {}, None
        with path.open("rb") as handle:
            index = 0
            while line := handle.readline(LEDGER_LINE_MAX_BYTES + 1):
                index += 1
                if len(line) > LEDGER_LINE_MAX_BYTES and not line.endswith(b"\n"):
                    while line and not line.endswith(b"\n"):
                        line = handle.readline(LEDGER_LINE_MAX_BYTES)
                    continue
                if needles is not None and not any(n in line for n in needles):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                slug = row.get("event_slug") if isinstance(row, dict) else None
                if isinstance(slug, str) and slug in wanted:
                    revision = row.get("revision_number")
                    key = (revision if isinstance(revision, int) and not isinstance(revision, bool) else 0, index)
                    if slug not in best or key >= best[slug][0]:
                        best[slug] = (key, row)
    except OSError:
        return {}, "proxy_ledger_unreadable"
    return {slug: row for slug, (_, row) in best.items()}, None


def ledger_label(root, location_id, event_slug):
    """Latest revision for one event; see ``ledger_labels``."""
    found, status = ledger_labels(root, location_id, [event_slug])
    if status:
        return None, status
    return (found[event_slug], None) if event_slug in found else (None, "proxy_label_absent")

def _terminal(prices):
    return [p if p in (0, 1) else None for p in prices]


def _market_outcomes(market, number):
    try:
        tokens, outcomes, prices = (json.loads(v) if isinstance(v, str) else v for v in (
            market.get("clobTokenIds"), market.get("outcomes"), market.get("outcomePrices")))
        if not (isinstance(tokens, list) and isinstance(outcomes, list) and isinstance(prices, list)
                and len(tokens) == len(outcomes) == len(prices) >= 2):
            raise ValueError
        return [str(t) for t in tokens], [str(o) for o in outcomes], _terminal([number(p) for p in prices])
    except (ReaderError, TypeError, ValueError):
        return None, None, None


def resolution_state(market, prices):
    if not market:
        return "metadata_unavailable"
    if market.get("closed") is True:
        return "resolved" if prices and all(p is not None for p in prices) and sum(prices) == 1 else "closed_awaiting_terminal_price"
    if market.get("closed") is False:
        return "open"
    return "unknown"


def _event_slug(held_rows, market):
    slug = next((r.get("eventSlug") for r in held_rows if r.get("eventSlug")), None)
    events = market.get("events")
    if not slug and isinstance(events, list) and events and isinstance(events[0], dict):
        slug = events[0].get("slug")
    return slug


def venue_basis(source):
    source = str(source or "").lower()
    if "weather.gov" in source:
        return "weather_gov"
    if "wunderground" in source:
        return "wunderground"
    return "other" if source else None


def settlement(reader, since, *, ledger_root, events_config, now=None):
    """Held plus recently filled markets; ``reader`` is a WalletReader."""
    from weather.market.wallet_reader import GAMMA_CHUNK_SIZE, number, rows
    now = now or datetime.now(timezone.utc)
    errors, held, filled = {}, {}, {}
    try:
        for row in reader._position_rows():
            held[row["asset"]] = row
    except ReaderError:
        errors["positions"] = "positions_unavailable"
    try:
        for row in reader.pages("/data/trades", maker_address=reader.funder, after=since):
            condition, token = str(row.get("market", "")), str(row.get("asset_id", ""))
            if CONDITION.fullmatch(condition) and re.fullmatch(r"[0-9]{1,78}", token):
                entry = filled.setdefault(condition.lower(), {"tokens": set(), "fills": 0, "last_fill": None})
                entry["tokens"].add(token)
                entry["fills"] += 1
                stamp = str(row.get("match_time", ""))
                entry["last_fill"] = max(filter(None, (entry["last_fill"], stamp)), default=None)
    except ReaderError:
        errors["fills"] = "fills_unavailable"
    conditions = sorted({r["conditionId"].lower() for r in held.values()} | set(filled))
    metadata = {}
    for start in range(0, len(conditions), GAMMA_CHUNK_SIZE):
        chunk = conditions[start:start + GAMMA_CHUNK_SIZE]
        try:
            batch = {}
            for market in rows(reader.get(GAMMA, "/markets", condition_ids=chunk, limit=len(chunk))):
                key = str(market.get("conditionId", "")).lower()
                if key not in chunk or key in batch:
                    raise ReaderError("metadata_identity_unreadable")
                batch[key] = market
            metadata.update(batch)
        except ReaderError:
            errors["metadata"] = "resolution_metadata_unavailable"
    bands = configured_bands(events_config)
    markets, flags = [], {"disagreements": [], "unredeemed_winners": [], "resolved_unreconciled": []}
    slugs = {c: _event_slug([r for r in held.values() if r["conditionId"].lower() == c], metadata.get(c, {}))
             for c in conditions}
    by_location = {}
    for slug in slugs.values():
        by_location.setdefault(event_location(slug, events_config), set()).add(slug)
    # One streaming pass per location ledger, however many of its events are held or filled.
    ledgers = {location: ledger_labels(ledger_root, location, wanted) for location, wanted in by_location.items()}
    for condition in conditions:
        market = metadata.get(condition, {})
        tokens, outcomes, prices = _market_outcomes(market, number)
        state = resolution_state(market, prices)
        held_rows = [r for r in held.values() if r["conditionId"].lower() == condition]
        event_slug = slugs[condition]
        events = market.get("events")
        source = market.get("resolutionSource") or (events[0].get("resolutionSource")
                                                    if isinstance(events, list) and events and isinstance(events[0], dict) else None)
        winner = outcomes[prices.index(1)] if state == "resolved" else None
        band = bands.get(condition) or market.get("groupItemTitle")
        found, proxy_status = ledgers[event_location(event_slug, events_config)]
        label = found.get(event_slug)
        if label is None and proxy_status is None:
            proxy_status = "proxy_label_absent"
        proxy = None
        if label is not None:
            proxy_status = "observed"
            proxy = dict(settlement_high=label.get("settlement_high"), settlement_unit=label.get("settlement_unit"),
                         winning_band=label.get("winning_band"), settlement_source=label.get("settlement_source"),
                         ledger_reconciliation_status=label.get("reconciliation_status"),
                         polymarket_winning_band=label.get("polymarket_winning_band"),
                         revision_number=label.get("revision_number"))
        proxy_says_yes = (band_key(proxy["winning_band"]) == band_key(band)
                          if proxy and proxy.get("winning_band") and band else None)
        venue_says_yes = (winner == outcomes[0]) if winner is not None and outcomes else None
        disagreement = proxy_says_yes is not None and venue_says_yes is not None and proxy_says_yes != venue_says_yes
        positions = []
        for row in held_rows:
            index = tokens.index(row["asset"]) if tokens and row["asset"] in tokens else None
            terminal = prices[index] if index is not None and state == "resolved" else None
            size = number(row.get("size"))
            positions.append(dict(token_id=row["asset"], outcome=row.get("outcome"), size=str(size),
                                  redeemable=row.get("redeemable") is True, terminal_price=None if terminal is None else str(terminal),
                                  unredeemed_winner=terminal == 1 and size > 0))
        entry = dict(condition_id=condition, title=market.get("question") or next((r.get("title") for r in held_rows), None),
                     event_slug=event_slug, band_label=band, resolution_state=state,
                     uma_resolution_status=market.get("umaResolutionStatus"), venue_resolution_source=source,
                     venue_outcome_basis=venue_basis(source), venue_winning_outcome=winner,
                     settlement_proxy=proxy, settlement_proxy_status=proxy_status,
                     proxy_says_this_band_won=proxy_says_yes, venue_says_this_band_won=venue_says_yes,
                     disagreement=disagreement, held_positions=positions,
                     recent_fills=filled.get(condition, {}).get("fills", 0),
                     last_fill_time=filled.get(condition, {}).get("last_fill"))
        markets.append(entry)
        if disagreement:
            flags["disagreements"].append(condition)
        if any(p["unredeemed_winner"] for p in positions):
            flags["unredeemed_winners"].append(condition)
        if state == "resolved" and positions and any(number(p["size"]) > 0 for p in positions) and (
                proxy is None or proxy.get("ledger_reconciliation_status") != "match"):
            flags["resolved_unreconciled"].append(condition)
    complete = not errors and all(m["resolution_state"] != "metadata_unavailable" for m in markets)
    return dict(since=since, captured_at_utc=now.isoformat(), markets=markets, flags=flags, errors=errors,
                status="OBSERVED" if complete else "PARTIAL", counts=dict(
                    held_markets=len({r["conditionId"].lower() for r in held.values()}),
                    recently_filled_markets=len(filled), markets=len(markets),
                    **{k: len(v) for k, v in flags.items()}),
                notes=["read_only", "proxy_is_local_wu_ledger_latest_revision", "venue_outcome_from_gamma_terminal_prices",
                       "weather_gov_page_not_fetched_venue_outcome_is_the_weather_gov_resolution_where_basis_says_so",
                       "band_match_by_label_text"], cache_seconds=30)

