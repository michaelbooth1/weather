"""T2's taker rule: one module for the WS-3 early-warning kill-only read and for T2 (same sha).

Pre-registration: ``docs/research/ws3-early-warning-prereg-2026-11-06.md`` (sha256 ``1f992edf…``), §2-§3, which
applies PT-1 §3.3 (``docs/operations/COOL_SEASON_PAPER_TEST_PREREG.md``). Pure functions (decision, fill, caps,
P&L, countability, kill statistic) plus a CLI that takes the window and the arms as arguments.

The engine reads only transferred captured files named on its command line: an arm-vector table, per-event
``order_books_summary.csv(.gz)`` files (top-of-book columns only, by allowlist) and per-event ``settlement.json``
files (``polymarket_winning_band`` only, and only for in-scope events). It never reads a settlements ledger,
imports no exchange client, SDK, credential or network library, and makes no network call (an AST test pins this).
Every input row must belong to B's 10 markets (``B10``) and to the ``--window-start``..``--window-end`` target
dates, with its local hour and target date matching ``captured_at_utc`` in the market's zone; anything else is a
refusal before the single-look marker, never a silent drop.

Order of work in one run: validate arguments and paths, then load and validate every input (prices are parsed
here but nothing reads them until step 4) -> create-only single-look marker -> (1) coverage counts from
timestamps and token ids only -> (2) winner exists / matches one band, as status strings -> (3) input manifest
with the counts and the countable set -> (4) entries, fills and caps -> (5) settle -> kill statistic -> outputs
and receipt, all create-only. A second run into the same output folder refuses.

Rulings (a)-(i), accepted by master 2026-11-06 (PT-1 §3.2-3.3):
  (a) an entry that does not fill is not an entry: the band may be tried again at a later snapshot;
  (b) if both sides of one band pass at one snapshot, the larger net edge is taken (Yes on a tie); a band
      already holding a side never takes the other;
  (c) a notional cap is never partially filled: an entry that would breach 25 per market-day or 100 per date
      is skipped and counted;
  (d) the fill window is t + L <= captured_at_utc <= t + L + 120 s with L = latency (30 s for WS-3);
  (e) a book row with book_time_utc > captured_at_utc + 15 s, or a non-finite top-of-book field, is unusable,
      counted, and never selected;
  (f) coverage denominator = the market-day's 07-16 snapshots carrying a vector for either arm; a snapshot is
      covered when every Yes and No token of every band in its vectors has a decision row (time window only);
      a vector band with no book token is a coverage gap;
  (g) bootstraps use numpy ``default_rng(seed)`` freshly per method and arm, percentile with linear
      interpolation; the moving block draws ceil(n/3) non-circular blocks of 3 consecutive countable dates;
  (h) a countable date is a local target date with >= 1 countable market-day; the date and market-day floors
      are over the shared countable set, the 30-fill floor is per arm;
  (i) caps consume across all market-days in decision-time order, countable or not; Y sums countable fills only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from weather.schema_families import schema_version

THETA = 0.03
TOL = 1e-9
SLIPPAGE = 0.01
FEE_RATE = 0.05
RECEIPT_GAP_S = 15.0
DECISION_LOOKBACK_S = 120.0
MIN_LATENCY_S = 30.0
FILL_WINDOW_S = 120.0
SHARES_REQUESTED = 10.0
MAX_ENTRIES_PER_MARKET_DAY = 3
MAX_NOTIONAL_PER_MARKET_DAY = 25.0
MAX_NOTIONAL_PER_DATE = 100.0
DECISION_HOURS = tuple(range(7, 17))
COVERAGE_MIN = 0.90
ALPHA = 0.025
BOOT_DRAWS = 2000
BOOT_SEED = 20260921
BLOCK_LEN = 3
MIN_COUNTABLE_DATES = 12
MIN_COUNTABLE_MARKET_DAYS = 100
MIN_FILLED_ENTRIES = 30
SIDES = ("Yes", "No")
# B's 10 markets (B_FORWARD_TEST_DESIGN.md §3) and their zones (weather.market.market_registry; a test pins both).
B10 = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
       "dallas": "America/Chicago", "houston": "America/Chicago", "los-angeles": "America/Los_Angeles",
       "miami": "America/New_York", "nyc": "America/New_York", "san-francisco": "America/Los_Angeles",
       "seattle": "America/Los_Angeles"}

BOOK_COLUMNS = ("event_slug", "range_label", "outcome", "clob_token_id", "captured_at_utc", "book_time_utc",
                "best_ask", "ask_size_at_best", "ask_count", "min_order_size")
VECTOR_COLUMNS = ("arm", "event_slug", "target_date", "captured_at_utc", "local_hour", "range_label", "q")
MARKER_NAME = ".single_look_marker"
OUTPUT_NAMES = ("input_manifest.json", "trades.csv", "market_days.csv", "summary.json", "receipt.json")
REPO_ROOT = Path(__file__).resolve().parents[3]
_SLUG_RE = re.compile(r"^highest-temperature-in-(?P<market>.+)-on-(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$")


class RuleError(ValueError):
    """Fail-closed input or state error (raised before the single-look marker)."""


class _Unusable(Exception):
    """A book row that may never be selected (late receipt or non-finite field)."""


# Verbatim copy of weather.backtesting.settlement_ledger.clean_temperature_label (settlement_ledger.py:592-601 at
# origin/master 22b3dd835); test_label_cleaner_is_a_verbatim_copy pins the AST equality.
def clean_temperature_label(label):
    text = str(label or "")
    text = text.replace("°", " ")
    text = text.replace("℃", " C")
    text = text.replace("℉", " F")
    text = text.replace("º", " ")
    text = text.replace("Â", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" C C", " C").replace(" F F", " F")
    return text


def fee(price: float) -> float:
    """Venue weather taker fee per share at price p: 0.05 * p * (1 - p)."""
    return FEE_RATE * price * (1.0 - price)


def net_edge(q_side: float, ask: float) -> float:
    """Expected net edge per share for buying a side at the decision ask, before theta."""
    return q_side - ask - fee(ask) - SLIPPAGE


def passes_entry(q_side: float, ask: float) -> bool:
    return net_edge(q_side, ask) >= THETA - TOL


def entry_pnl(shares: float, payout: float, fill_price: float) -> float:
    """Net P&L per entry: shares * (payout - a' - fee(a') - slippage)."""
    return shares * (payout - fill_price - fee(fill_price) - SLIPPAGE)


def parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise RuleError(f"timestamp without timezone: {text!r}")
    return value


def _finite(text: str | None) -> float | None:
    """None when blank; raises _Unusable when present but not a finite number."""
    if text is None or text.strip() == "":
        return None
    value = float(text)
    if not math.isfinite(value):
        raise _Unusable
    return value


def slug_parts(slug: str) -> tuple[str, date]:
    """(market, target date) of a B10 event slug; any other market is a refusal."""
    match = _SLUG_RE.match(slug)
    if not match:
        raise RuleError(f"unrecognised event slug: {slug!r}")
    if match.group("market") not in B10:
        raise RuleError(f"market outside B's 10: {slug!r}")
    day = datetime.strptime(f"{match.group('month')} {match.group('day')} {match.group('year')}", "%B %d %Y").date()
    return match.group("market"), day


@dataclass(frozen=True)
class Scope:
    start: date
    end: date
    excluded: frozenset[str]

    def check(self, slug: str) -> bool:
        """Refuse a non-B10 or out-of-window event; False for an excluded one (skipped, never parsed)."""
        _, day = slug_parts(slug)
        if not self.start <= day <= self.end:
            raise RuleError(f"target date {day} of {slug!r} is outside the window {self.start}..{self.end}")
        return slug not in self.excluded


@dataclass(frozen=True)
class BookRow:
    captured: datetime
    best_ask: float | None
    ask_size: float | None
    ask_count: int
    min_order_size: float | None


@dataclass
class TokenBook:
    rows: list[BookRow] = field(default_factory=list)
    times: list[datetime] = field(default_factory=list)

    def finalize(self) -> None:
        self.rows.sort(key=lambda row: row.captured)
        self.times = [row.captured for row in self.rows]


def decision_index(times: list[datetime], t: datetime) -> int | None:
    """Index of the latest time with time + G <= t and time >= t - 120 s."""
    hi = bisect.bisect_right(times, t - timedelta(seconds=RECEIPT_GAP_S))
    if hi == 0 or times[hi - 1] < t - timedelta(seconds=DECISION_LOOKBACK_S):
        return None
    return hi - 1


def fill_index(times: list[datetime], t: datetime, latency_s: float) -> int | None:
    """Index of the earliest time with t + L <= time <= t + L + 120 s."""
    lo = bisect.bisect_left(times, t + timedelta(seconds=latency_s))
    if lo == len(times) or times[lo] > t + timedelta(seconds=latency_s + FILL_WINDOW_S):
        return None
    return lo


@dataclass
class Books:
    tokens: dict[str, TokenBook] = field(default_factory=dict)
    token_of: dict[tuple[str, str, str], str] = field(default_factory=dict)
    unusable_rows: int = 0
    rows_read: int = 0
    excluded_rows: int = 0

    def times_of(self) -> dict[str, list[datetime]]:
        return {token: book.times for token, book in self.tokens.items()}

    def event_bands(self) -> dict[str, set[str]]:
        bands: dict[str, set[str]] = defaultdict(set)
        for slug, band, _side in self.token_of:
            bands[slug].add(band)
        return dict(bands)


def _open_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def load_books(paths: list[Path], scope: Scope) -> Books:
    """Load top-of-book rows; columns outside BOOK_COLUMNS are never retained, excluded events never parsed."""
    books = Books()
    for path in paths:
        if not path.name.startswith("order_books_summary.csv"):
            raise RuleError(f"not an order_books_summary file: {path}")
        with _open_text(path) as handle:
            reader = csv.reader(handle)
            header = next(reader)
            missing = [name for name in BOOK_COLUMNS if name not in header]
            if missing:
                raise RuleError(f"{path}: missing columns {missing}")
            idx = {name: header.index(name) for name in BOOK_COLUMNS}
            for raw in reader:
                rec = {name: raw[i] for name, i in idx.items()}
                if not scope.check(rec["event_slug"]):
                    books.excluded_rows += 1
                    continue
                if rec["outcome"] not in SIDES:
                    raise RuleError(f"{path}: outcome {rec['outcome']!r}")
                books.rows_read += 1
                captured = parse_utc(rec["captured_at_utc"])
                try:
                    if parse_utc(rec["book_time_utc"]) > captured + timedelta(seconds=RECEIPT_GAP_S):
                        raise _Unusable
                    row = BookRow(captured, _finite(rec["best_ask"]), _finite(rec["ask_size_at_best"]),
                                  int(_finite(rec["ask_count"]) or 0), _finite(rec["min_order_size"]))
                except _Unusable:
                    books.unusable_rows += 1
                    continue
                key = (rec["event_slug"], clean_temperature_label(rec["range_label"]), rec["outcome"])
                token = rec["clob_token_id"]
                if books.token_of.setdefault(key, token) != token:
                    raise RuleError(f"two token ids for {key}")
                books.tokens.setdefault(token, TokenBook()).rows.append(row)
    for book in books.tokens.values():
        book.finalize()
    return books


@dataclass(frozen=True)
class Snapshot:
    slug: str
    target_date: date
    t: datetime
    local_hour: int


def load_vectors(path: Path, arms: tuple[str, str], scope: Scope):
    """Return ({arm: {Snapshot: {band: q}}}, row counts). Hours and dates are recomputed and must agree."""
    out: dict[str, dict[Snapshot, dict[str, float]]] = {arm: defaultdict(dict) for arm in arms}
    counts = {"rows": 0, "other_arm": 0, "excluded_slug": 0, "outside_decision_hours": 0}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in VECTOR_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise RuleError(f"{path}: missing columns {missing}")
        for rec in reader:
            counts["rows"] += 1
            if rec["arm"] not in out:
                counts["other_arm"] += 1
                continue
            slug = rec["event_slug"]
            if not scope.check(slug):
                counts["excluded_slug"] += 1
                continue
            market, slug_day = slug_parts(slug)
            t = parse_utc(rec["captured_at_utc"])
            local = t.astimezone(ZoneInfo(B10[market]))
            day, hour = date.fromisoformat(rec["target_date"]), int(rec["local_hour"])
            if local.hour != hour or local.date() != day or day != slug_day:
                raise RuleError(f"local hour/date disagree with captured_at_utc in {B10[market]} (T+0): {rec}")
            if hour not in DECISION_HOURS:
                counts["outside_decision_hours"] += 1
                continue
            q = float(rec["q"])
            if not (math.isfinite(q) and 0.0 <= q <= 1.0):
                raise RuleError(f"q outside [0, 1]: {rec}")
            bands = out[rec["arm"]][Snapshot(slug, day, t, hour)]
            band = clean_temperature_label(rec["range_label"])
            if band in bands:
                raise RuleError(f"duplicate vector entry after label cleaning: {rec}")
            bands[band] = q
    return {arm: dict(snaps) for arm, snaps in out.items()}, counts


def snapshot_bands(vectors) -> dict[Snapshot, set[str]]:
    snaps: dict[Snapshot, set[str]] = defaultdict(set)
    for arm_snaps in vectors.values():
        for snap, bands in arm_snaps.items():
            snaps[snap] |= set(bands)
    return dict(snaps)


def coverage(snaps: dict[Snapshot, set[str]], token_of: dict[tuple[str, str, str], str],
             token_times: dict[str, list[datetime]]) -> dict[str, dict[str, int]]:
    """Step 1, timestamps and ids only: per event, 07-16 snapshots, covered ones and unmatched vector bands."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"snapshots": 0, "covered": 0, "unmatched_bands": 0})
    unmatched: dict[str, set[str]] = defaultdict(set)
    for snap, bands in snaps.items():
        counts[snap.slug]["snapshots"] += 1
        ok = True
        for band in bands:
            for side in SIDES:
                token = token_of.get((snap.slug, band, side))
                if token is None:
                    unmatched[snap.slug].add(band)
                if token is None or decision_index(token_times.get(token, []), snap.t) is None:
                    ok = False
        counts[snap.slug]["covered"] += int(ok)
    for slug, bands in unmatched.items():
        counts[slug]["unmatched_bands"] = len(bands)
    return dict(counts)


def winner_status(winners: dict[str, str], event_bands: dict[str, set[str]]) -> dict[str, str]:
    """Step 2: 'matched', 'missing' or 'unmatched' per event; the band itself is never returned."""
    status = {}
    for slug, raw in winners.items():
        winner = clean_temperature_label(raw)
        status[slug] = "missing" if not winner else ("matched" if winner in event_bands.get(slug, set())
                                                     else "unmatched")
    return status


def countable_events(arm_events: dict[str, set[str]], cov: dict[str, dict[str, int]], outcome_blind_pass: set[str],
                     winners_ok: dict[str, str]) -> dict[str, str]:
    """Event -> '' if countable, else the first failing reason. Ids, counts and status strings only."""
    events = set().union(*arm_events.values())
    reasons = {}
    for slug in sorted(events):
        c = cov.get(slug, {"snapshots": 0, "covered": 0})
        status = winners_ok.get(slug, "missing")
        if not all(slug in found for found in arm_events.values()):
            reasons[slug] = "arm_vector_missing"
        elif slug not in outcome_blind_pass:
            reasons[slug] = "outcome_blind_check_not_passed"
        elif c["snapshots"] == 0 or c["covered"] / c["snapshots"] < COVERAGE_MIN:
            reasons[slug] = "decision_row_coverage_below_90pct"
        elif status != "matched":
            reasons[slug] = "no_venue_winner" if status == "missing" else "winner_unmatched"
        else:
            reasons[slug] = ""
    return reasons


@dataclass
class Trade:
    arm: str
    slug: str
    target_date: date
    t: datetime
    band: str
    side: str
    q_side: float
    decision_ask: float
    fill_price: float
    shares: float
    payout: float | None = None
    pnl: float | None = None


def run_arm(arm: str, arm_snaps, both: set[tuple[str, datetime]], books: Books, latency_s: float):
    """Step 4: entries, fills and caps for one arm in decision-time order. Returns (trades, counts)."""
    if not (math.isfinite(latency_s) and latency_s >= MIN_LATENCY_S):
        raise RuleError(f"latency {latency_s} s must be finite and >= {MIN_LATENCY_S} s")
    skips: dict[str, int] = defaultdict(int)
    trades: list[Trade] = []
    held: dict[tuple[str, str], str] = {}
    entries: dict[str, int] = defaultdict(int)
    md_notional: dict[str, float] = defaultdict(float)
    date_notional: dict[date, float] = defaultdict(float)
    ordered = sorted((snap for snap in arm_snaps if (snap.slug, snap.t) in both), key=lambda s: (s.t, s.slug))
    skips["decision_instants"] = len(ordered)
    for snap in ordered:
        for band in sorted(arm_snaps[snap]):
            q = arm_snaps[snap][band]
            options = []
            for side in SIDES:
                token = books.token_of.get((snap.slug, band, side))
                i = decision_index(books.tokens[token].times, snap.t) if token else None
                row = books.tokens[token].rows[i] if i is not None else None
                if row is None or row.ask_count <= 0 or row.best_ask is None:
                    skips["no_decision"] += 1
                    continue
                q_side = q if side == "Yes" else 1.0 - q
                if passes_entry(q_side, row.best_ask):
                    options.append((-net_edge(q_side, row.best_ask), SIDES.index(side), side, token, q_side,
                                    row.best_ask))
            if not options:
                continue
            _, _, side, token, q_side, ask = min(options)
            skips["entry_signals"] += 1
            if (snap.slug, band) in held:
                skips["band_already_held"] += 1
                continue
            if entries[snap.slug] >= MAX_ENTRIES_PER_MARKET_DAY:
                skips["cap_entries"] += 1
                continue
            j = fill_index(books.tokens[token].times, snap.t, latency_s)
            if j is None:
                skips["no_fill_row"] += 1
                continue
            fill = books.tokens[token].rows[j]
            if fill.ask_count <= 0 or fill.best_ask is None or fill.best_ask > ask:
                skips["no_fill_price"] += 1
                continue
            if fill.min_order_size is None:
                skips["missing_min_order_size"] += 1
                continue
            shares = min(SHARES_REQUESTED, fill.ask_size or 0.0)
            if shares <= 0 or shares < fill.min_order_size:
                skips["below_min_order_size"] += 1
                continue
            notional = shares * fill.best_ask
            if (md_notional[snap.slug] + notional > MAX_NOTIONAL_PER_MARKET_DAY + TOL
                    or date_notional[snap.target_date] + notional > MAX_NOTIONAL_PER_DATE + TOL):
                skips["cap_notional"] += 1
                continue
            held[(snap.slug, band)] = side
            entries[snap.slug] += 1
            md_notional[snap.slug] += notional
            date_notional[snap.target_date] += notional
            trades.append(Trade(arm, snap.slug, snap.target_date, snap.t, band, side, q_side, ask,
                                fill.best_ask, shares))
    return trades, dict(skips)


def load_winners(paths: list[Path], scope: Scope, slugs: set[str]) -> dict[str, str]:
    """Event -> raw polymarket_winning_band ('' if none). The event is read from the folder name and filtered
    BEFORE the file is opened; out-of-scope settlement files are never parsed. Never reads a ledger."""
    winners = {}
    for path in paths:
        if path.name != "settlement.json":
            raise RuleError(f"not a per-event settlement.json: {path}")
        slug = path.parent.name
        if not scope.check(slug) or slug not in slugs:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("event_slug") or slug) != slug:
            raise RuleError(f"{path}: event_slug does not match its folder")
        if slug in winners:
            raise RuleError(f"two settlement files for {slug}")
        winners[slug] = str(data.get("polymarket_winning_band") or "")
    return winners


def settle(trades: list[Trade], winners: dict[str, str], status: dict[str, str]) -> None:
    """Step 5: payout only where the cleaned winner matched exactly one band of the event."""
    for trade in trades:
        if status.get(trade.slug) != "matched":
            continue
        won = trade.band == clean_temperature_label(winners[trade.slug])
        trade.payout = 1.0 if (won if trade.side == "Yes" else not won) else 0.0
        trade.pnl = entry_pnl(trade.shares, trade.payout, trade.fill_price)


def _by_date(values: dict[str, float], day_of: dict[str, date]) -> list[list[float]]:
    grouped: dict[date, list[float]] = defaultdict(list)
    for slug, value in values.items():
        grouped[day_of[slug]].append(value)
    return [grouped[d] for d in sorted(grouped)]


def _draw_means(groups: list[list[float]], method: str, rng: np.random.Generator) -> np.ndarray:
    n = len(groups)
    out = np.empty(BOOT_DRAWS)
    block = min(BLOCK_LEN, n)
    for i in range(BOOT_DRAWS):
        if method == "date_cluster":
            picks = rng.integers(0, n, n)
        else:
            starts = rng.integers(0, n - block + 1, math.ceil(n / block))
            picks = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        out[i] = float(np.mean([v for p in picks for v in groups[p]]))
    return out


def bootstrap_bounds(values: dict[str, float], day_of: dict[str, date]) -> dict[str, dict[str, float]]:
    """Percentile bounds by date-clustered and moving block-3 bootstraps (2,000 draws, seed 20260921 each)."""
    groups = _by_date(values, day_of)
    if not groups:
        return {}
    result = {}
    for method in ("date_cluster", "block3"):
        means = _draw_means(groups, method, np.random.default_rng(BOOT_SEED))
        result[method] = {"lower": float(np.percentile(means, 100 * ALPHA)),
                          "upper": float(np.percentile(means, 100 * (1 - ALPHA)))}
    return result


def kill_outcome(n_dates: int, n_market_days: int, n_filled: int, upper: float | None) -> str:
    if n_dates < MIN_COUNTABLE_DATES or n_market_days < MIN_COUNTABLE_MARKET_DAYS or n_filled < MIN_FILLED_ENTRIES:
        return "UNTESTABLE"
    if upper is None:
        return "UNTESTABLE"
    return "KILL" if upper < 0 else "NOT_KILLED"


def evaluate(arms, trades_by_arm, countable: dict[str, str], day_of: dict[str, date], counts: dict[str, dict]):
    """Per-arm M, U (wider of the two bootstraps), costs, realised population and outcome; paired descriptive."""
    final = sorted(slug for slug, reason in countable.items() if not reason)
    y = {arm: {slug: 0.0 for slug in final} for arm in arms}
    n_dates = len({day_of[slug] for slug in final})
    summary = {"arms": {}, "countable_market_days": len(final), "countable_dates": n_dates}
    for arm in arms:
        fills = [t for t in trades_by_arm[arm] if t.slug in y[arm] and t.pnl is not None]
        for trade in fills:
            y[arm][trade.slug] += trade.pnl
        bounds = bootstrap_bounds(y[arm], day_of)
        upper = max(b["upper"] for b in bounds.values()) if bounds else None
        values = list(y[arm].values())
        summary["arms"][arm] = {
            "M": float(np.mean(values)) if values else None, "U": upper, "bounds": bounds,
            "filled_entries": len(fills), "sd_market_day": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "fee_total": sum(t.shares * fee(t.fill_price) for t in fills),
            "slippage_total": sum(t.shares * SLIPPAGE for t in fills),
            "filled_shares": sum(t.shares for t in fills),
            "realised_population": {"countable_market_days": len(final), "countable_dates": n_dates,
                                    "fills_all_market_days": len(trades_by_arm[arm]), "fills_countable": len(fills),
                                    **counts[arm]},
            "outcome": kill_outcome(n_dates, len(final), len(fills), upper)}
    first, second = arms
    diff = {slug: y[first][slug] - y[second][slug] for slug in final}
    summary["paired_difference"] = {"definition": f"{first} - {second} per market-day, descriptive, no alpha",
                                    "mean": float(np.mean(list(diff.values()))) if diff else None,
                                    "bounds": bootstrap_bounds(diff, day_of)}
    return summary, y


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def forbidden_reason(path: Path) -> str | None:
    """Why a resolved path may never be read (ledger, settlements store, local config, sealed panel)."""
    parts = [part.lower() for part in path.resolve().parts]
    pairs = set(zip(parts, parts[1:]))
    if parts and parts[-1].startswith("ledger.jsonl"):
        return "a settlements ledger"
    if ("data", "settlements") in pairs:
        return "the data/settlements store"
    if ("config", "local") in pairs:
        return "config/local"
    if ("l2", "p2") in pairs or any("panel" in part for part in parts):
        return "the sealed panel or a panel store"
    return None


def guard_paths(inputs: list[Path], out: Path) -> None:
    for path in inputs:
        reason = forbidden_reason(path)
        if reason:
            raise RuleError(f"forbidden input path ({reason}): {path}")
        if not path.resolve().is_file():
            raise RuleError(f"input is not a file: {path}")
    resolved = out.resolve()
    if forbidden_reason(resolved / "x") or resolved == REPO_ROOT or REPO_ROOT in resolved.parents or any(
            part.lower() == "data" for part in resolved.parts):
        raise RuleError(f"--out must be outside the repository and any data folder: {out}")


def _read_list(path: Path) -> list[Path]:
    return [Path(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _csv_text(header: list[str], rows: list[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m weather.backtesting.t2_taker_rule", description=__doc__.split("\n")[0])
    parser.add_argument("--vectors", type=Path, required=True, help="arm-vector CSV: " + ",".join(VECTOR_COLUMNS))
    parser.add_argument("--books-list", type=Path, required=True, help="text file: one order_books_summary path per line")
    parser.add_argument("--settlements-list", type=Path, required=True, help="text file: one settlement.json per line")
    parser.add_argument("--outcome-blind-pass", type=Path, required=True, help="text file: event slugs that passed")
    parser.add_argument("--window-start", type=date.fromisoformat, required=True)
    parser.add_argument("--window-end", type=date.fromisoformat, required=True)
    parser.add_argument("--arms", nargs=2, required=True, metavar=("ARM", "ARM"), help="kill arm first, e.g. mg2 served")
    parser.add_argument("--exclude-slug", action="append", default=[], help="event slug to exclude (repeatable)")
    parser.add_argument("--latency-s", type=float, default=MIN_LATENCY_S)
    parser.add_argument("--projection-receipt", type=Path, help="dev projection receipt JSON (sha recorded)")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    arms = tuple(args.arms)
    try:
        if arms[0] == arms[1] or args.window_end < args.window_start:
            raise RuleError("arms must differ and the window must be ordered")
        if not (math.isfinite(args.latency_s) and args.latency_s >= MIN_LATENCY_S):
            raise RuleError("--latency-s must be finite and >= 30")
        scope = Scope(args.window_start, args.window_end, frozenset(args.exclude_slug))
        for slug in args.exclude_slug:
            slug_parts(slug)
        lists = [args.vectors, args.books_list, args.settlements_list, args.outcome_blind_pass]
        lists += [args.projection_receipt] if args.projection_receipt else []
        guard_paths(lists, args.out)
        book_paths, settlement_paths = _read_list(args.books_list), _read_list(args.settlements_list)
        inputs = [*lists, *book_paths, *settlement_paths]
        guard_paths(inputs, args.out)
        if (args.out / MARKER_NAME).exists() or any((args.out / name).exists() for name in OUTPUT_NAMES):
            print(f"refused: single look already taken in {args.out}", file=sys.stderr)
            return 3
        vectors, vector_counts = load_vectors(args.vectors, arms, scope)
        slugs = {snap.slug for snaps in vectors.values() for snap in snaps}
        day_of = {snap.slug: snap.target_date for snaps in vectors.values() for snap in snaps}
        books = load_books(book_paths, scope)
        winners = load_winners(settlement_paths, scope, slugs)
        passed = {line.strip() for line in args.outcome_blind_pass.read_text(encoding="utf-8").splitlines()
                  if line.strip()}
        projection = None
        if args.projection_receipt:
            projection = {"path": str(args.projection_receipt), "sha256": _sha256(args.projection_receipt),
                          "projected": json.loads(args.projection_receipt.read_text(encoding="utf-8")).get("projected")}
        hashes = {str(p): _sha256(p) for p in inputs}
    except (ValueError, OSError, KeyError, IndexError, StopIteration, csv.Error) as exc:
        print(f"refused before the single look: {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone().isoformat()
    _write_new(args.out / MARKER_NAME, json.dumps({"started": started, "argv": sys.argv[1:] if argv is None else argv})
               + "\n")
    module_sha = _sha256(Path(__file__))
    cov = coverage(snapshot_bands(vectors), books.token_of, books.times_of())  # step 1
    status = winner_status(winners, books.event_bands())  # step 2
    countable = countable_events({arm: {s.slug for s in vectors[arm]} for arm in arms}, cov, passed, status)
    manifest = {"schema_version": schema_version("t2_taker_rule_input_manifest"), "module_sha256": module_sha,
                "arms": list(arms), "window": [args.window_start.isoformat(), args.window_end.isoformat()],
                "excluded_slugs": sorted(args.exclude_slug), "latency_s": args.latency_s, "inputs": hashes,
                "vector_rows": vector_counts, "book_rows_read": books.rows_read,
                "book_rows_unusable": books.unusable_rows, "book_rows_excluded": books.excluded_rows,
                "coverage": cov, "unmatched_vector_bands_total": sum(c["unmatched_bands"] for c in cov.values()),
                "winner_unmatched_total": sum(v == "unmatched" for v in status.values()),
                "no_venue_winner_total": sum(status.get(s, "missing") == "missing" for s in slugs),
                "countable": countable}
    _write_new(args.out / "input_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")  # step 3
    both = set.intersection(*({(s.slug, s.t) for s in vectors[arm]} for arm in arms))
    trades_by_arm, counts = {}, {}
    for arm in arms:
        trades_by_arm[arm], counts[arm] = run_arm(arm, vectors[arm], both, books, args.latency_s)  # step 4
        settle(trades_by_arm[arm], winners, status)  # step 5
    summary, y = evaluate(arms, trades_by_arm, countable, day_of, counts)
    summary.update({"schema_version": schema_version("t2_taker_rule_summary"), "module_sha256": module_sha,
                    "projection_receipt": projection, "winner_unmatched_total": manifest["winner_unmatched_total"],
                    "unmatched_vector_bands_total": manifest["unmatched_vector_bands_total"]})
    trade_rows = [[t.arm, t.slug, t.target_date, t.t.isoformat(), t.band, t.side, t.q_side, t.decision_ask,
                   t.fill_price, t.shares, "" if t.payout is None else t.payout, "" if t.pnl is None else t.pnl,
                   int(not countable.get(t.slug))] for arm in arms for t in trades_by_arm[arm]]
    _write_new(args.out / "trades.csv", _csv_text(
        ["arm", "event_slug", "target_date", "decision_utc", "range_label", "side", "q_side", "decision_ask",
         "fill_price", "shares", "payout", "pnl", "countable"], trade_rows))
    md_rows = [[slug, day_of[slug], countable[slug], *[y[arm].get(slug, "") for arm in arms]]
               for slug in sorted(countable)]
    _write_new(args.out / "market_days.csv", _csv_text(["event_slug", "target_date", "noncountable_reason",
                                                        *[f"Y_{arm}" for arm in arms]], md_rows))
    _write_new(args.out / "summary.json", json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    receipt = {"schema_version": schema_version("t2_taker_rule_receipt"), "module_sha256": module_sha,
               "started": started, "finished": datetime.now().astimezone().isoformat(), "single_look": True,
               "outputs": {name: _sha256(args.out / name) for name in OUTPUT_NAMES[:-1]},
               "outcomes": {arm: summary["arms"][arm]["outcome"] for arm in arms}}
    _write_new(args.out / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt["outcomes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
