"""Maker-side markouts from the PUBLIC execution tape (read-only analysis).

Question: per filled share, what did a passive maker earn or lose to later price
movement?  Pre-registered in
``docs/research/execution-tape-markout-preregistration-2026-09-19.md``; read the caveats
there before citing any number this module prints.  It measures OTHER makers' fills, not
ours, and says nothing about fill rate or queue position.

Inputs (all under one event folder ``<snapshots_root>/<event_slug>/``):

* ``execution_tape/trades-NNNNN.jsonl`` written by ``execution_tape_store`` -- streamed
  line by line.  ``side`` is read as the AGGRESSOR (taker) side per the venue's documented
  ``last_trade_price`` semantics, so the maker is the opposite side.  Rows with no usable
  ``side`` fall back to the quote rule against the last midpoint at or before the trade and
  are flagged; the report says so loudly.
* ``order_books_summary.csv`` -- THE CHOSEN MIDPOINT SOURCE.  It already carries
  ``best_bid``/``best_ask`` per token per REST capture (tens of seconds apart) and is
  roughly 50 MB per event day, against the raw ``order_books.jsonl`` full-depth tape which is
  an order of magnitude larger and has crashed this host before.  It is streamed through
  ``weather.io.iter_csv_rows`` (bounded memory, honours cold-archive markers) and only
  ``(captured_at_utc, mid)`` pairs for tokens that actually traded are retained, in packed
  ``array('d')`` columns (about 1 MB per event).  The raw book tape is never opened.
* ``settlement.json`` -- ``settlement_bucket`` for the to-settlement horizon.

Memory: one event is processed at a time; aggregates are per-date sums, never per-trade
rows.  ``--max-trades`` and ``--dates`` / ``--recent-dates`` bound the run, and open
(unclosed) event dates are refused by default so a live writer is never read.

Output: ``execution_tape_markout.json`` and ``execution_tape_markout.md`` under
``--output-dir``, which must be outside the repository ``data`` tree.  Nothing else is written.
All report values are PRICE UNITS per share (1.0 = one dollar); the markdown shows cents.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
import re
from array import array
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

from weather.cold_archive_locations import ArchivedInputRequired, CatalogIntegrityError
from weather.io import iter_csv_rows
from weather.market.market_registry import REGISTRY, spec_for_slug
from weather.paths import DATA_ROOT, data_path


REPORT_KIND = "execution_tape_markout"
REPORT_REVISION = 1
PREREGISTRATION_DOC = "docs/research/execution-tape-markout-preregistration-2026-09-19.md"

DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
TAPE_DIRNAME = "execution_tape"
TRADE_PART_RE = re.compile(r"^trades-(\d{5})\.jsonl$")
SUMMARY_FILENAME = "order_books_summary.csv"
SETTLEMENT_FILENAME = "settlement.json"
JSON_REPORT_NAME = "execution_tape_markout.json"
MARKDOWN_REPORT_NAME = "execution_tape_markout.md"

SETTLEMENT_HORIZON = "settlement"
HORIZON_SECONDS = {"1m": 60.0, "5m": 300.0, "30m": 1800.0}
HORIZONS = (*HORIZON_SECONDS, SETTLEMENT_HORIZON)
PRIMARY_HORIZON = "5m"

DEFAULT_TOLERANCE_SECONDS = 120.0
DEFAULT_MAX_TRADES = 100_000
DEFAULT_RECENT_DATES = 3
DEFAULT_BOOTSTRAP_REPLICATES = 2000
DEFAULT_SEED = 20260919
MIN_DATE_CLUSTERS = 10
INTERVAL_LEVEL = 0.90
UNDERPOWERED = "UNDERPOWERED"

MAKER_REBATE_SHARE = 0.25
TAKER_FEE_COEFFICIENT = 0.05

ONE_SIDED_POLICIES = ("skip", "bound")
MAKER_SOLD = "sold"
MAKER_BOUGHT = "bought"
SIDE_SOURCE_RECORDED = "recorded_aggressor_side"
SIDE_SOURCE_QUOTE_RULE = "quote_rule_fallback"

HOURS_TO_CLOSE_BUCKETS = (">24h", "6-24h", "1-6h", "<1h", "after_close")
PRICE_BUCKETS = ("p<0.1", "0.1-0.3", "0.3-0.7", "0.7-0.9", ">0.9")
SIZE_BUCKETS = ("<10", "10-100", "100-1000", ">=1000")

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december",
        ),
        start=1,
    )
}
_SLUG_DATE_RE = re.compile(r"-on-([a-z]+)-(\d{1,2})-(\d{4})$")


class MarkoutError(RuntimeError):
    """Raised for a refused run (unsafe output location, open date, bad argument)."""


# --------------------------------------------------------------------------- pure pieces


def maker_side_from_aggressor(side: Any) -> str | None:
    """Aggressor BUY means the maker SOLD; aggressor SELL means the maker BOUGHT."""

    text = str(side or "").strip().upper()
    if text == "BUY":
        return MAKER_SOLD
    if text == "SELL":
        return MAKER_BOUGHT
    return None


def maker_side_from_quote_rule(price: float, reference_mid: float | None) -> str | None:
    """Quote rule: a print above the midpoint was a buy aggressor, so the maker sold."""

    if reference_mid is None or price == reference_mid:
        return None
    return MAKER_SOLD if price > reference_mid else MAKER_BOUGHT


def maker_markout(maker_side: str, price: float, mark: float) -> float:
    """Signed per-share P&L of the maker when the position is marked at ``mark``."""

    if maker_side == MAKER_SOLD:
        return price - mark
    if maker_side == MAKER_BOUGHT:
        return mark - price
    raise ValueError(f"unknown maker side: {maker_side!r}")


def maker_rebate_per_share(price: float) -> float:
    """Nominal maker rebate: 25% of the taker fee ``0.05 * p * (1 - p)``."""

    return MAKER_REBATE_SHARE * TAKER_FEE_COEFFICIENT * price * (1.0 - price)


def hours_to_close_bucket(hours: float) -> str:
    if hours < 0:
        return "after_close"
    if hours < 1:
        return "<1h"
    if hours < 6:
        return "1-6h"
    if hours <= 24:
        return "6-24h"
    return ">24h"


def price_bucket(price: float) -> str:
    if price < 0.1:
        return "p<0.1"
    if price < 0.3:
        return "0.1-0.3"
    if price < 0.7:
        return "0.3-0.7"
    if price <= 0.9:
        return "0.7-0.9"
    return ">0.9"


def size_bucket(size: float) -> str:
    if size < 10:
        return "<10"
    if size < 100:
        return "10-100"
    if size < 1000:
        return "100-1000"
    return ">=1000"


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def target_date_from_slug(event_slug: str) -> date | None:
    match = _SLUG_DATE_RE.search(str(event_slug or "").lower())
    if not match or match.group(1) not in _MONTHS:
        return None
    try:
        return date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))
    except ValueError:
        return None


def market_close_utc(market_id: str, target_date: date) -> tuple[datetime, bool]:
    """End of the local measurement day; ``False`` when the market's zone is unknown (UTC used)."""

    spec = REGISTRY.get(str(market_id or ""))
    zone = ZoneInfo(spec.timezone) if spec is not None else timezone.utc
    local_end = datetime.combine(target_date + timedelta(days=1), time(0, 0), tzinfo=zone)
    return local_end.astimezone(timezone.utc), spec is not None


def date_is_closed(target_date: date, now: datetime) -> bool:
    """Closed once UTC midnight two days on has passed (covers every US zone's local day end)."""

    boundary = datetime.combine(target_date + timedelta(days=2), time(0, 0), tzinfo=timezone.utc)
    return now >= boundary


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def ensure_output_dir_allowed(output_dir: str | Path, *, data_root: str | Path = DATA_ROOT) -> Path:
    """Refuse the repository data tree and any path with a literal ``data`` component."""

    path = Path(output_dir)
    if is_under(path, Path(data_root)) or any(part.lower() == "data" for part in path.resolve().parts):
        raise MarkoutError(f"refusing to write under a data tree: {path}")
    return path


# --------------------------------------------------------------------------- midpoints


class MidpointSeries:
    """Packed per-token ``(epoch_seconds, mid)`` columns with at-or-after / at-or-before lookup."""

    def __init__(self) -> None:
        self._times: dict[str, array] = {}
        self._mids: dict[str, array] = {}
        self._sorted: set[str] = set()

    def add(self, token: str, epoch_seconds: float, mid: float) -> None:
        self._times.setdefault(token, array("d")).append(epoch_seconds)
        self._mids.setdefault(token, array("d")).append(mid)
        self._sorted.discard(token)

    def _ensure_sorted(self, token: str) -> None:
        if token in self._sorted or token not in self._times:
            return
        times, mids = self._times[token], self._mids[token]
        if any(times[i] > times[i + 1] for i in range(len(times) - 1)):
            order = sorted(range(len(times)), key=times.__getitem__)
            self._times[token] = array("d", (times[i] for i in order))
            self._mids[token] = array("d", (mids[i] for i in order))
        self._sorted.add(token)

    def point_count(self, token: str | None = None) -> int:
        if token is not None:
            return len(self._times.get(token, ()))
        return sum(len(values) for values in self._times.values())

    def at_or_after(self, token: str, epoch_seconds: float, tolerance: float) -> float | None:
        self._ensure_sorted(token)
        times = self._times.get(token)
        if not times:
            return None
        index = bisect.bisect_left(times, epoch_seconds)
        if index < len(times) and times[index] - epoch_seconds <= tolerance:
            return self._mids[token][index]
        return None

    def at_or_before(self, token: str, epoch_seconds: float, tolerance: float) -> float | None:
        self._ensure_sorted(token)
        times = self._times.get(token)
        if not times:
            return None
        index = bisect.bisect_right(times, epoch_seconds) - 1
        if index >= 0 and epoch_seconds - times[index] <= tolerance:
            return self._mids[token][index]
        return None


def midpoint_from_summary_row(row: dict[str, Any], one_sided_policy: str) -> tuple[float | None, str]:
    """Return ``(mid, status)``; status is ``two_sided``, ``one_sided``, ``empty`` or ``crossed``."""

    bid = _finite(row.get("best_bid"))
    ask = _finite(row.get("best_ask"))
    bid = bid if bid is not None and 0.0 <= bid <= 1.0 else None
    ask = ask if ask is not None and 0.0 <= ask <= 1.0 else None
    if bid is None and ask is None:
        return None, "empty"
    if bid is None or ask is None:
        if one_sided_policy != "bound":
            return None, "one_sided"
        # Sensitivity only: an absent ask means nobody sells below 1, an absent bid nobody bids above 0.
        return ((bid if bid is not None else 0.0) + (ask if ask is not None else 1.0)) / 2.0, "one_sided"
    if ask < bid:
        return None, "crossed"
    return (bid + ask) / 2.0, "two_sided"


def load_midpoints(
    event_folder: Path,
    tokens: set[str],
    *,
    one_sided_policy: str,
) -> tuple[MidpointSeries, dict[str, dict[str, Any]], dict[str, Any]]:
    """Stream the summary CSV once, keeping midpoints and band metadata for traded tokens only."""

    series = MidpointSeries()
    token_meta: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {
        "source": SUMMARY_FILENAME,
        "source_status": "ok",
        "rows_for_traded_tokens": 0,
        "two_sided_rows": 0,
        "one_sided_rows": 0,
        "one_sided_rows_used": 0,
        "empty_or_crossed_rows": 0,
        "rows_without_capture_time": 0,
    }
    path = event_folder / SUMMARY_FILENAME
    if not tokens:
        return series, token_meta, stats
    try:
        rows: Iterable[dict[str, Any]] = iter_csv_rows(path)
        for row in rows:
            token = str(row.get("clob_token_id") or "").strip()
            if token not in tokens:
                continue
            stats["rows_for_traded_tokens"] += 1
            if token not in token_meta:
                token_meta[token] = {
                    "bin_kind": str(row.get("bin_kind") or "").strip().lower(),
                    "bin_value": row.get("bin_value"),
                    "bin_value_hi": row.get("bin_value_hi"),
                    "outcome": str(row.get("outcome") or "").strip().lower(),
                }
            captured = parse_utc(row.get("captured_at_utc"))
            if captured is None:
                stats["rows_without_capture_time"] += 1
                continue
            mid, status = midpoint_from_summary_row(row, one_sided_policy)
            if status == "two_sided":
                stats["two_sided_rows"] += 1
            elif status == "one_sided":
                stats["one_sided_rows"] += 1
                if mid is not None:
                    stats["one_sided_rows_used"] += 1
            else:
                stats["empty_or_crossed_rows"] += 1
            if mid is not None:
                series.add(token, captured.timestamp(), mid)
    except ArchivedInputRequired:
        stats["source_status"] = "archived_restore_required"
    except (OSError, UnicodeError, csv.Error, CatalogIntegrityError) as exc:
        # One unreadable summary must not kill the other events; its trades become unmarkable
        # and the status is carried into the report.  Points read before the failure are kept.
        stats["source_status"] = f"unreadable:{type(exc).__name__}"
    if stats["source_status"] == "ok" and not path.exists():
        stats["source_status"] = "missing"
    return series, token_meta, stats


def token_settlement_payoff(meta: dict[str, Any] | None, settlement_bucket: Any) -> float | None:
    """Payoff (0.0 or 1.0) of one outcome token given the settled whole-degree bucket."""

    bucket = _finite(settlement_bucket)
    if not meta or bucket is None:
        return None
    value = _finite(meta.get("bin_value"))
    value_hi = _finite(meta.get("bin_value_hi"))
    kind = str(meta.get("bin_kind") or "").strip().lower()
    outcome = str(meta.get("outcome") or "").strip().lower()
    if value is None or kind not in {"eq", "lte", "gte"} or outcome not in {"yes", "no"}:
        return None
    from weather.backtesting.settlement_ledger import resolve_outcome

    band_true = resolve_outcome(kind, int(value), int(bucket), int(value_hi) if value_hi is not None else None)
    if band_true is None:
        return None
    return 1.0 if bool(band_true) == (outcome == "yes") else 0.0


def read_settlement_bucket(event_folder: Path) -> Any:
    path = event_folder / SETTLEMENT_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return payload.get("settlement_bucket") if isinstance(payload, dict) else None


# --------------------------------------------------------------------------- tape reading


def trade_part_paths(event_folder: Path) -> list[Path]:
    tape = event_folder / TAPE_DIRNAME
    if not tape.is_dir():
        return []
    parts = []
    for child in tape.iterdir():
        match = TRADE_PART_RE.fullmatch(child.name)
        if match and child.is_file():
            parts.append((int(match.group(1)), child))
    return [path for _, path in sorted(parts)]


def iter_tape_lines(event_folder: Path) -> Iterator[str]:
    """Yield raw tape lines one at a time across rotation parts, in part order."""

    for path in trade_part_paths(event_folder):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    yield line


def parse_trade_line(line: str) -> tuple[dict[str, Any] | None, str]:
    """Return ``(trade, reason)``; ``trade`` is ``None`` when the line is skipped for ``reason``."""

    try:
        row = json.loads(line)
    except ValueError:
        return None, "malformed_json"
    if not isinstance(row, dict):
        return None, "malformed_not_object"
    token = str(row.get("asset_id") or "").strip()
    price = _finite(row.get("price"))
    if not token or price is None or not 0.0 <= price <= 1.0:
        return None, "invalid_price_or_token"
    size = _finite(row.get("size"))
    if size is None or size <= 0:
        return None, "missing_size"
    timestamp_ms = _finite(row.get("timestamp"))
    if timestamp_ms is not None and timestamp_ms > 0:
        epoch_seconds = timestamp_ms / 1000.0
    else:
        traded = parse_utc(row.get("trade_time_utc"))
        if traded is None:
            return None, "missing_timestamp"
        epoch_seconds = traded.timestamp()
    return {
        "token": token,
        "price": price,
        "size": size,
        "epoch_seconds": epoch_seconds,
        "recorded_side": maker_side_from_aggressor(row.get("side")),
        "market_id": str(row.get("market_id") or "").strip(),
        "target_date": str(row.get("target_date") or "").strip(),
        "fee_rate_bps": str(row.get("fee_rate_bps") if row.get("fee_rate_bps") is not None else "absent"),
        "identity": (
            token,
            str(row.get("price")),
            str(row.get("side")),
            str(row.get("size")),
            str(row.get("timestamp")),
            str(row.get("transaction_hash") or ""),
        ),
        "has_transaction_hash": bool(str(row.get("transaction_hash") or "").strip()),
    }, "ok"


# --------------------------------------------------------------------------- aggregation


class CellAccumulator:
    """Per-date sums for one (split, bucket, horizon) cell; never retains trade rows."""

    __slots__ = ("by_date",)

    def __init__(self) -> None:
        # date -> [n, shares, sum_markout, sum_shares*markout, sum_rebate, sum_shares*rebate]
        self.by_date: dict[str, list[float]] = {}

    def add(self, cluster: str, shares: float, markout: float, rebate: float) -> None:
        sums = self.by_date.setdefault(cluster, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sums[0] += 1.0
        sums[1] += shares
        sums[2] += markout
        sums[3] += shares * markout
        sums[4] += rebate
        sums[5] += shares * rebate


def _cell_point(rows: list[list[float]]) -> dict[str, float | None]:
    n = sum(row[0] for row in rows)
    shares = sum(row[1] for row in rows)

    def ratio(numerator: float, denominator: float) -> float | None:
        return numerator / denominator if denominator > 0 else None

    trade_markout = ratio(sum(row[2] for row in rows), n)
    trade_rebate = ratio(sum(row[4] for row in rows), n)
    share_markout = ratio(sum(row[3] for row in rows), shares)
    share_rebate = ratio(sum(row[5] for row in rows), shares)
    return {
        "trade_markout": trade_markout,
        "trade_rebate": trade_rebate,
        "trade_net": None if trade_markout is None else trade_markout + trade_rebate,
        "share_markout": share_markout,
        "share_rebate": share_rebate,
        "share_net": None if share_markout is None else share_markout + share_rebate,
    }


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already sorted, non-empty list."""

    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def cluster_bootstrap_intervals(
    by_date: dict[str, list[float]],
    *,
    seed: int,
    cell_key: str,
    replicates: int,
    level: float = INTERVAL_LEVEL,
) -> dict[str, list[float] | None]:
    """Resample whole event dates with replacement; recompute each ratio estimator per replicate.

    The generator is seeded from ``(seed, cell_key)`` so a cell's interval does not depend on
    which other cells exist or the order they are summarised in.
    """

    names = ("trade_markout", "trade_net", "share_markout", "share_net")
    clusters = [by_date[key] for key in sorted(by_date)]
    if len(clusters) < 2 or replicates <= 0:
        return {name: None for name in names}
    rng = random.Random(f"{int(seed)}:{cell_key}")
    count = len(clusters)
    draws: dict[str, list[float]] = {name: [] for name in names}
    for _ in range(replicates):
        sample = [clusters[rng.randrange(count)] for _ in range(count)]
        point = _cell_point(sample)
        for name in names:
            if point[name] is not None:
                draws[name].append(point[name])
    tail = (1.0 - level) / 2.0
    result: dict[str, list[float] | None] = {}
    for name in names:
        values = sorted(draws[name])
        result[name] = [percentile(values, tail), percentile(values, 1.0 - tail)] if values else None
    return result


def summarize_cell(
    cell: CellAccumulator,
    *,
    seed: int,
    cell_key: str,
    replicates: int,
) -> dict[str, Any]:
    rows = list(cell.by_date.values())
    point = _cell_point(rows)
    intervals = cluster_bootstrap_intervals(
        cell.by_date, seed=seed, cell_key=cell_key, replicates=replicates
    )
    clusters = len(cell.by_date)
    underpowered = clusters < MIN_DATE_CLUSTERS

    def block(prefix: str) -> dict[str, Any]:
        return {
            "mean_markout": point[f"{prefix}_markout"],
            "mean_rebate": point[f"{prefix}_rebate"],
            "mean_net": point[f"{prefix}_net"],
            "markout_interval_90": intervals[f"{prefix}_markout"],
            "net_interval_90": intervals[f"{prefix}_net"],
        }

    return {
        "markable_trades": int(sum(row[0] for row in rows)),
        "markable_shares": sum(row[1] for row in rows),
        "date_clusters": clusters,
        "underpowered": underpowered,
        "interval_flag": UNDERPOWERED if underpowered else "",
        "share_weighted": block("share"),
        "trade_weighted": block("trade"),
    }


def decision_verdict(primary: dict[str, Any] | None, reward_per_share: float | None) -> dict[str, Any]:
    """Apply the pre-registered rule to the primary cell."""

    interval = (primary or {}).get("share_weighted", {}).get("net_interval_90")
    base = {
        "rule": "KILL-SIGNAL if upper < -R; SUPPORTIVE if lower > -R; otherwise INCONCLUSIVE",
        "reward_per_share_R": reward_per_share,
        "interval_90": interval,
        "date_clusters": (primary or {}).get("date_clusters", 0),
    }
    if reward_per_share is None:
        return {**base, "verdict": "R_NOT_SUPPLIED", "reason": "pass --reward-per-share once R is frozen"}
    if not interval:
        return {**base, "verdict": "INCONCLUSIVE", "reason": "no interval (fewer than 2 date clusters)"}
    if (primary or {}).get("underpowered"):
        return {**base, "verdict": "INCONCLUSIVE", "reason": UNDERPOWERED}
    lower, upper = interval
    if upper < -reward_per_share:
        return {**base, "verdict": "KILL-SIGNAL", "reason": "upper bound below -R"}
    if lower > -reward_per_share:
        return {**base, "verdict": "SUPPORTIVE", "reason": "lower bound above -R"}
    return {**base, "verdict": "INCONCLUSIVE", "reason": "interval straddles -R"}


# --------------------------------------------------------------------------- orchestration


def discover_events(snapshots_root: Path) -> list[tuple[str, date, Path]]:
    """Non-recursive listing of event folders that hold an execution tape and a parseable date."""

    events = []
    if not snapshots_root.is_dir():
        return events
    for child in sorted(snapshots_root.iterdir(), key=lambda item: item.name):
        target = target_date_from_slug(child.name)
        if target is None or not (child / TAPE_DIRNAME).is_dir():
            continue
        events.append((child.name, target, child))
    return events


def select_events(
    events: list[tuple[str, date, Path]],
    *,
    dates: list[date] | None,
    recent_dates: int,
    markets: set[str] | None,
    now: datetime,
    allow_open_dates: bool,
) -> tuple[list[tuple[str, date, Path]], list[str]]:
    if dates:
        open_dates = sorted({d.isoformat() for d in dates if not date_is_closed(d, now)})
        if open_dates and not allow_open_dates:
            raise MarkoutError(
                f"refusing open (unclosed) event dates {open_dates}; pass --allow-open-dates to override"
            )
        wanted = set(dates)
    else:
        closed = sorted({target for _, target, _ in events if date_is_closed(target, now)})
        wanted = set(closed[-recent_dates:]) if recent_dates > 0 else set()
    selected = []
    for slug, target, folder in events:
        if target not in wanted:
            continue
        if markets is not None:
            spec = spec_for_slug(slug)
            if spec is None or spec.id not in markets:
                continue
        selected.append((slug, target, folder))
    return selected, sorted(d.isoformat() for d in wanted)


def build_markout_report(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    dates: list[date] | None = None,
    recent_dates: int = DEFAULT_RECENT_DATES,
    markets: set[str] | None = None,
    max_trades: int = DEFAULT_MAX_TRADES,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
    one_sided_policy: str = "skip",
    collapse_repeated_identities: bool = True,
    seed: int = DEFAULT_SEED,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    reward_per_share: float | None = None,
    allow_open_dates: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if one_sided_policy not in ONE_SIDED_POLICIES:
        raise MarkoutError(f"unknown one-sided policy: {one_sided_policy!r}")
    if max_trades <= 0:
        raise MarkoutError("--max-trades must be positive")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshots_root = Path(snapshots_root)
    selected, wanted_dates = select_events(
        discover_events(snapshots_root),
        dates=dates,
        recent_dates=recent_dates,
        markets=markets,
        now=now,
        allow_open_dates=allow_open_dates,
    )

    counts: dict[str, int] = {
        "tape_lines_read": 0,
        "malformed_lines_skipped": 0,
        "invalid_price_or_token_skipped": 0,
        "missing_size_skipped": 0,
        "missing_timestamp_skipped": 0,
        "missing_target_date_skipped": 0,
        "repeated_identity_observations_collapsed": 0,
        "trades_accepted": 0,
        "maker_side_recorded": 0,
        "maker_side_quote_rule_fallback": 0,
        "side_undetermined_skipped": 0,
        "trades_analysed": 0,
        "unknown_market_timezone_trades": 0,
        "quote_rule_checkable": 0,
        "quote_rule_agrees_with_recorded_side": 0,
    }
    unmarkable = {horizon: 0 for horizon in HORIZONS}
    unmarkable_reasons = {horizon: {} for horizon in HORIZONS}
    fee_rate_counts: dict[str, int] = {}
    cells: dict[tuple[str, str, str], CellAccumulator] = {}
    event_rows = []
    truncated_events: list[str] = []
    skipped_events: list[str] = []
    remaining = int(max_trades)

    def note_unmarkable(horizon: str, reason: str) -> None:
        unmarkable[horizon] += 1
        reasons = unmarkable_reasons[horizon]
        reasons[reason] = reasons.get(reason, 0) + 1

    for slug, slug_date, folder in selected:
        if remaining <= 0:
            skipped_events.append(slug)
            continue
        trades: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        truncated = False
        for line in iter_tape_lines(folder):
            if len(trades) >= remaining:
                truncated = True
                break
            counts["tape_lines_read"] += 1
            trade, reason = parse_trade_line(line)
            if trade is None:
                key = "malformed_lines_skipped" if reason.startswith("malformed") else f"{reason}_skipped"
                counts[key] += 1
                continue
            if collapse_repeated_identities and trade["has_transaction_hash"]:
                if trade["identity"] in seen:
                    counts["repeated_identity_observations_collapsed"] += 1
                    continue
                seen.add(trade["identity"])
            trades.append(trade)
        seen.clear()
        remaining -= len(trades)
        if truncated:
            truncated_events.append(slug)
        counts["trades_accepted"] += len(trades)

        series, token_meta, mid_stats = load_midpoints(
            folder, {trade["token"] for trade in trades}, one_sided_policy=one_sided_policy
        )
        settlement_bucket = read_settlement_bucket(folder)
        event_rows.append({
            "event_slug": slug,
            "target_date": slug_date.isoformat(),
            "trades_accepted": len(trades),
            "truncated_by_max_trades": truncated,
            "midpoint_points_retained": series.point_count(),
            "midpoint_source": mid_stats,
            "settlement_known": _finite(settlement_bucket) is not None,
        })

        for trade in trades:
            cluster = trade["target_date"] or slug_date.isoformat()
            try:
                cluster_date = date.fromisoformat(cluster)
            except ValueError:
                counts["missing_target_date_skipped"] += 1
                continue
            price, size, at = trade["price"], trade["size"], trade["epoch_seconds"]
            reference_mid = series.at_or_before(trade["token"], at, tolerance_seconds)
            quote_rule_side = maker_side_from_quote_rule(price, reference_mid)
            maker_side = trade["recorded_side"]
            if maker_side is not None:
                counts["maker_side_recorded"] += 1
                if quote_rule_side is not None:
                    counts["quote_rule_checkable"] += 1
                    if quote_rule_side == maker_side:
                        counts["quote_rule_agrees_with_recorded_side"] += 1
            else:
                maker_side = quote_rule_side
                if maker_side is None:
                    counts["side_undetermined_skipped"] += 1
                    continue
                counts["maker_side_quote_rule_fallback"] += 1
            counts["trades_analysed"] += 1
            fee_rate_counts[trade["fee_rate_bps"]] = fee_rate_counts.get(trade["fee_rate_bps"], 0) + 1

            market_id = trade["market_id"] or "unknown"
            close_utc, zone_known = market_close_utc(market_id, cluster_date)
            if not zone_known:
                counts["unknown_market_timezone_trades"] += 1
            hours = (close_utc.timestamp() - at) / 3600.0
            splits = (
                ("overall", "all"),
                ("market", market_id),
                ("hours_to_close", hours_to_close_bucket(hours)),
                ("price", price_bucket(price)),
                ("size", size_bucket(size)),
                ("maker_side", maker_side),
                (
                    "maker_side_source",
                    SIDE_SOURCE_RECORDED if trade["recorded_side"] is not None else SIDE_SOURCE_QUOTE_RULE,
                ),
            )
            rebate = maker_rebate_per_share(price)
            for horizon in HORIZONS:
                if horizon == SETTLEMENT_HORIZON:
                    mark = token_settlement_payoff(token_meta.get(trade["token"]), settlement_bucket)
                    if mark is None:
                        note_unmarkable(
                            horizon,
                            "settlement_unknown" if _finite(settlement_bucket) is None else "token_band_unknown",
                        )
                        continue
                else:
                    mark = series.at_or_after(
                        trade["token"], at + HORIZON_SECONDS[horizon], tolerance_seconds
                    )
                    if mark is None:
                        note_unmarkable(
                            horizon,
                            "no_midpoints_for_token"
                            if series.point_count(trade["token"]) == 0
                            else "no_midpoint_within_tolerance",
                        )
                        continue
                markout = maker_markout(maker_side, price, mark)
                for split, bucket in splits:
                    cells.setdefault((split, bucket, horizon), CellAccumulator()).add(
                        cluster, size, markout, rebate
                    )
        del trades, series, token_meta

    results: dict[str, dict[str, dict[str, Any]]] = {}
    for (split, bucket, horizon) in sorted(cells):
        results.setdefault(split, {}).setdefault(bucket, {})[horizon] = summarize_cell(
            cells[(split, bucket, horizon)],
            seed=seed,
            cell_key=f"{split}|{bucket}|{horizon}",
            replicates=bootstrap_replicates,
        )
    primary = results.get("overall", {}).get("all", {}).get(PRIMARY_HORIZON)

    warnings = []
    if counts["maker_side_quote_rule_fallback"] or counts["side_undetermined_skipped"]:
        warnings.append(
            "AGGRESSOR SIDE NOT RECORDED on {missing} trade(s): {fallback} used the quote-rule fallback "
            "(flagged under split maker_side_source) and {dropped} had no decidable side and were skipped."
            .format(
                missing=counts["maker_side_quote_rule_fallback"] + counts["side_undetermined_skipped"],
                fallback=counts["maker_side_quote_rule_fallback"],
                dropped=counts["side_undetermined_skipped"],
            )
        )
    zero_fee = sum(n for key, n in fee_rate_counts.items() if _finite(key) == 0.0)
    if zero_fee:
        warnings.append(
            f"REBATE IS NOMINAL: the tape records fee_rate_bps=0 on {zero_fee} of "
            f"{counts['trades_analysed']} analysed trades; if no taker fee is charged the true rebate is "
            "zero, so read mean_markout, not mean_net, as the conservative figure."
        )
    if truncated_events or skipped_events:
        warnings.append(
            f"--max-trades={max_trades} TRUNCATED the sample: {len(truncated_events)} event(s) cut short and "
            f"{len(skipped_events)} not read at all; events are read in slug order, so this is not a random sample."
        )
    if counts["malformed_lines_skipped"]:
        warnings.append(f"{counts['malformed_lines_skipped']} malformed tape line(s) were counted and skipped.")
    if one_sided_policy != "skip":
        warnings.append("one-sided books were BOUNDED (0/1) into midpoints: this is the sensitivity run, not the primary.")
    if primary is None:
        warnings.append("no markable trade at the primary horizon: the primary metric is empty.")

    checkable = counts["quote_rule_checkable"]
    return {
        "report_kind": REPORT_KIND,
        "report_revision": REPORT_REVISION,
        "generated_at_utc": now.isoformat(),
        "preregistration": PREREGISTRATION_DOC,
        "unit": "price units per share (1.0 = one dollar; multiply by 100 for cents)",
        "sign_convention": "positive = the passive maker gained; maker sold: p - mark; maker bought: mark - p",
        "scope_caveat": (
            "public tape: other makers' fills, not ours; queue position and cancelled quotes are invisible; "
            "P&L per FILLED share only, no fill-rate estimate"
        ),
        "parameters": {
            "snapshots_root": str(snapshots_root),
            "dates_selected": wanted_dates,
            "markets": sorted(markets) if markets is not None else "all",
            "max_trades": max_trades,
            "tolerance_seconds": tolerance_seconds,
            "one_sided_policy": one_sided_policy,
            "collapse_repeated_identities": collapse_repeated_identities,
            "seed": seed,
            "bootstrap_replicates": bootstrap_replicates,
            "interval_level": INTERVAL_LEVEL,
            "cluster": "event target_date",
            "min_date_clusters": MIN_DATE_CLUSTERS,
            "horizons": list(HORIZONS),
            "midpoint_source": SUMMARY_FILENAME,
            "rebate_formula": "0.25 * 0.05 * p * (1 - p)",
        },
        "aggressor_side": {
            "recorded_on_every_analysed_trade": (
                counts["trades_analysed"] > 0 and counts["maker_side_quote_rule_fallback"] == 0
                and counts["side_undetermined_skipped"] == 0
            ),
            "semantics_assumed": "tape `side` = taker/aggressor side (venue-documented, not chain-verified)",
            "quote_rule_checkable_trades": checkable,
            "quote_rule_agreement_rate": (
                counts["quote_rule_agrees_with_recorded_side"] / checkable if checkable else None
            ),
        },
        "counts": counts,
        "unmarkable": unmarkable,
        "unmarkable_reasons": unmarkable_reasons,
        "fee_rate_bps_counts": dict(sorted(fee_rate_counts.items())),
        "events_read": len(event_rows),
        "events_truncated_by_max_trades": truncated_events,
        "events_not_read_after_max_trades": skipped_events,
        "events": event_rows,
        "primary_metric": {
            "definition": "share-weighted net maker P&L per share, 5m horizon, all markets pooled",
            "cell": primary,
        },
        "decision": decision_verdict(primary, reward_per_share),
        "results": results,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- rendering


def _cents(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100.0:+.3f}"


def _interval_text(cell: dict[str, Any], weighting: str) -> str:
    interval = cell[weighting]["net_interval_90"]
    text = "n/a" if not interval else f"[{_cents(interval[0])}, {_cents(interval[1])}]"
    return f"{text} {cell['interval_flag']}".strip()


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Execution-tape maker markout",
        "",
        f"Generated {report['generated_at_utc']}. Cents per filled share; positive = the maker gained.",
        f"Pre-registration: `{report['preregistration']}`. {report['scope_caveat']}.",
        "",
    ]
    for warning in report["warnings"]:
        lines.append(f"- WARNING: {warning}")
    decision = report["decision"]
    side = report["aggressor_side"]
    agreement = side["quote_rule_agreement_rate"]
    lines += [
        "",
        f"Verdict: **{decision['verdict']}** ({decision['reason']}); R = {decision['reward_per_share_R']}.",
        f"Trades analysed: {report['counts']['trades_analysed']}; "
        f"unmarkable by horizon: {report['unmarkable']}.",
        "Aggressor side recorded on every analysed trade: "
        f"{side['recorded_on_every_analysed_trade']}; quote-rule agreement: "
        f"{'n/a' if agreement is None else f'{agreement:.1%}'} of {side['quote_rule_checkable_trades']}.",
        "",
        "| split | bucket | horizon | trades | dates | sw markout | sw rebate | sw net | sw net 90% | tw net | tw net 90% |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for split, buckets in report["results"].items():
        for bucket, horizons in buckets.items():
            for horizon in HORIZONS:
                cell = horizons.get(horizon)
                if cell is None:
                    continue
                share, trade = cell["share_weighted"], cell["trade_weighted"]
                lines.append(
                    f"| {split} | {bucket} | {horizon} | {cell['markable_trades']} | {cell['date_clusters']} | "
                    f"{_cents(share['mean_markout'])} | {_cents(share['mean_rebate'])} | "
                    f"{_cents(share['mean_net'])} | {_interval_text(cell, 'share_weighted')} | "
                    f"{_cents(trade['mean_net'])} | {_interval_text(cell, 'trade_weighted')} |"
                )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], output_dir: str | Path, *, data_root: str | Path = DATA_ROOT) -> dict[str, str]:
    target = ensure_output_dir_allowed(output_dir, data_root=data_root)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / JSON_REPORT_NAME
    markdown_path = target / MARKDOWN_REPORT_NAME
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


# --------------------------------------------------------------------------- CLI


def _parse_dates(value: str | None) -> list[date] | None:
    if not value:
        return None
    try:
        return [date.fromisoformat(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise MarkoutError(f"--dates expects comma-separated YYYY-MM-DD values: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maker-side markouts from the public execution tape (read-only; bounded by default)."
    )
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--output-dir", required=True, help="Must be outside the repository data tree.")
    parser.add_argument("--dates", default=None, help="Comma-separated closed event dates (YYYY-MM-DD).")
    parser.add_argument(
        "--recent-dates", type=int, default=DEFAULT_RECENT_DATES,
        help="Without --dates: the N most recent CLOSED event dates (default %(default)s).",
    )
    parser.add_argument("--markets", default="all", help="Comma-separated market ids, or 'all'.")
    parser.add_argument("--max-trades", type=int, default=DEFAULT_MAX_TRADES)
    parser.add_argument("--tolerance-seconds", type=float, default=DEFAULT_TOLERANCE_SECONDS)
    parser.add_argument("--one-sided-policy", choices=ONE_SIDED_POLICIES, default="skip")
    parser.add_argument("--keep-repeated-identities", action="store_true")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument(
        "--reward-per-share", type=float, default=None,
        help="R of the pre-registered rule, price units per filled share. Omit until R is frozen.",
    )
    parser.add_argument("--allow-open-dates", action="store_true")
    args = parser.parse_args(argv)
    try:
        ensure_output_dir_allowed(args.output_dir)
        markets = (
            None if args.markets.strip().lower() == "all"
            else {item.strip() for item in args.markets.split(",") if item.strip()}
        )
        report = build_markout_report(
            args.snapshots_root,
            dates=_parse_dates(args.dates),
            recent_dates=args.recent_dates,
            markets=markets,
            max_trades=args.max_trades,
            tolerance_seconds=args.tolerance_seconds,
            one_sided_policy=args.one_sided_policy,
            collapse_repeated_identities=not args.keep_repeated_identities,
            seed=args.seed,
            bootstrap_replicates=args.bootstrap_replicates,
            reward_per_share=args.reward_per_share,
            allow_open_dates=args.allow_open_dates,
        )
        paths = write_outputs(report, args.output_dir)
    except MarkoutError as exc:
        print(f"REFUSED: {exc}")
        return 2
    for warning in report["warnings"]:
        print(f"WARNING: {warning}")
    primary = report["primary_metric"]["cell"]
    if primary is not None:
        print(
            "primary (5m, share-weighted net, cents/share): "
            f"{_cents(primary['share_weighted']['mean_net'])} "
            f"90% {_interval_text(primary, 'share_weighted')} over {primary['date_clusters']} date cluster(s)"
        )
    print(f"verdict: {report['decision']['verdict']} ({report['decision']['reason']})")
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
