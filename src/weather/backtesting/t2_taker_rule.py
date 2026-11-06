"""T2's taker rule: one module for the WS-3 early-warning kill-only read and for T2 (same sha).

Pre-registration: ``docs/research/ws3-early-warning-prereg-2026-11-06.md`` (sha256 ``1f992edf…``), §2-§3, which
applies PT-1 §3.3 (``docs/operations/COOL_SEASON_PAPER_TEST_PREREG.md``). Pure functions (decision, fill, caps,
P&L, countability, kill statistic) plus a CLI that takes the window and the arms as arguments.

The engine reads only transferred captured files named on its command line: an arm-vector table, per-event
``order_books_summary.csv(.gz)`` files (top-of-book columns only, by allowlist) and per-event ``settlement.json``
files (``polymarket_winning_band`` only). It never reads a settlements ledger, imports no exchange client, SDK,
credential or network library, and makes no network call (an AST test pins this).

Order of work in one run: single-look marker (create-only) -> load vectors and book timestamps -> countability
counts written to the input manifest -> entries, fills and caps -> settlement read -> P&L and kill statistic ->
create-only outputs and receipt. A second run into the same output folder refuses.

Implementation choices not spelled out in the prereg (flagged for master's review before the pin):
  (a) an entry that does not fill is not an entry: the band may be tried again at a later snapshot;
  (b) if both sides of one band pass the entry test at the same snapshot, the side with the larger net edge is
      taken (Yes on a tie); a band already holding a side never takes the other;
  (c) a notional cap is never partially filled: an entry that would breach 25 per market-day or 100 per date
      is skipped and counted;
  (d) the fill window is t + L <= captured_at_utc <= t + L + 120 s with L = latency (30 s for WS-3, so 30..150 s);
  (e) a book row with book_time_utc > captured_at_utc + G is unusable, counted, and never selected;
  (f) coverage denominator = the market-day's 07-16 snapshots carrying a vector for either arm; a snapshot is
      covered when every Yes and No token of every band in its vectors has a decision row (time window only);
  (g) bootstraps use numpy ``default_rng(seed)`` freshly per method and arm, percentile with linear interpolation;
      the moving block draws ceil(n/3) non-circular blocks of 3 consecutive countable dates, truncated to n dates.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from weather.schema_families import schema_version

THETA = 0.03
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

BOOK_COLUMNS = ("event_slug", "range_label", "outcome", "clob_token_id", "captured_at_utc", "book_time_utc",
                "best_ask", "ask_size_at_best", "ask_count", "min_order_size")
VECTOR_COLUMNS = ("arm", "event_slug", "target_date", "captured_at_utc", "local_hour", "range_label", "q")
SETTLEMENT_KEYS = ("event_slug", "target_date", "polymarket_winning_band")
MARKER_NAME = ".single_look_marker"
OUTPUT_NAMES = ("input_manifest.json", "trades.csv", "market_days.csv", "summary.json", "receipt.json")
_SLUG_RE = re.compile(r"^highest-temperature-in-(?P<market>.+)-on-[a-z]+-\d{1,2}-\d{4}$")


class RuleError(ValueError):
    """Fail-closed input or state error."""


def fee(price: float) -> float:
    """Venue weather taker fee per share at price p: 0.05 * p * (1 - p)."""
    return FEE_RATE * price * (1.0 - price)


def net_edge(q_side: float, ask: float) -> float:
    """Expected net edge per share for buying a side at the decision ask, before theta."""
    return q_side - ask - fee(ask) - SLIPPAGE


def entry_pnl(shares: float, payout: float, fill_price: float) -> float:
    """Net P&L per entry: shares * (payout - a' - fee(a') - slippage)."""
    return shares * (payout - fill_price - fee(fill_price) - SLIPPAGE)


def parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise RuleError(f"timestamp without timezone: {text!r}")
    return value


def _num(text: str | None) -> float | None:
    if text is None or text.strip() == "":
        return None
    return float(text)


def market_of(slug: str) -> str:
    match = _SLUG_RE.match(slug)
    if not match:
        raise RuleError(f"unrecognised event slug: {slug!r}")
    return match.group("market")


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

    def decision_row(self, t: datetime) -> BookRow | None:
        """Latest row with captured + G <= t and captured >= t - 120 s."""
        hi = bisect.bisect_right(self.times, t - timedelta(seconds=RECEIPT_GAP_S))
        if hi == 0:
            return None
        row = self.rows[hi - 1]
        return row if row.captured >= t - timedelta(seconds=DECISION_LOOKBACK_S) else None

    def fill_row(self, t: datetime, latency_s: float) -> BookRow | None:
        """Earliest row with t + L <= captured <= t + L + 120 s."""
        lo = bisect.bisect_left(self.times, t + timedelta(seconds=latency_s))
        if lo == len(self.rows):
            return None
        row = self.rows[lo]
        return row if row.captured <= t + timedelta(seconds=latency_s + FILL_WINDOW_S) else None


@dataclass
class Books:
    tokens: dict[str, TokenBook] = field(default_factory=dict)
    token_of: dict[tuple[str, str, str], str] = field(default_factory=dict)
    unusable_rows: int = 0
    rows_read: int = 0


def _open_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def load_books(paths: list[Path], slugs: set[str]) -> Books:
    """Load top-of-book rows for the given events; columns outside BOOK_COLUMNS are never retained."""
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
                if rec["event_slug"] not in slugs:
                    continue
                books.rows_read += 1
                captured = parse_utc(rec["captured_at_utc"])
                if parse_utc(rec["book_time_utc"]) > captured + timedelta(seconds=RECEIPT_GAP_S):
                    books.unusable_rows += 1
                    continue
                key = (rec["event_slug"], rec["range_label"], rec["outcome"])
                token = rec["clob_token_id"]
                if books.token_of.setdefault(key, token) != token:
                    raise RuleError(f"two token ids for {key}")
                books.tokens.setdefault(token, TokenBook()).rows.append(BookRow(
                    captured, _num(rec["best_ask"]), _num(rec["ask_size_at_best"]),
                    int(float(rec["ask_count"] or 0)), _num(rec["min_order_size"])))
    for book in books.tokens.values():
        book.finalize()
    return books


@dataclass(frozen=True)
class Snapshot:
    slug: str
    target_date: date
    t: datetime
    local_hour: int


def load_vectors(path: Path, arms: tuple[str, str], start: date, end: date, excluded: set[str]):
    """Return {arm: {Snapshot: {range_label: q}}} for the window, decision hours and non-excluded events."""
    out: dict[str, dict[Snapshot, dict[str, float]]] = {arm: defaultdict(dict) for arm in arms}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in VECTOR_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise RuleError(f"{path}: missing columns {missing}")
        for rec in reader:
            if rec["arm"] not in out:
                continue
            day = date.fromisoformat(rec["target_date"])
            hour = int(rec["local_hour"])
            if not (start <= day <= end) or rec["event_slug"] in excluded or hour not in DECISION_HOURS:
                continue
            market_of(rec["event_slug"])
            q = float(rec["q"])
            if not 0.0 <= q <= 1.0:
                raise RuleError(f"q outside [0, 1]: {rec}")
            snap = Snapshot(rec["event_slug"], day, parse_utc(rec["captured_at_utc"]), hour)
            bands = out[rec["arm"]][snap]
            if rec["range_label"] in bands:
                raise RuleError(f"duplicate vector entry: {rec}")
            bands[rec["range_label"]] = q
    return {arm: dict(snaps) for arm, snaps in out.items()}


def coverage(vectors, books: Books) -> dict[str, dict[str, int]]:
    """Per event: 07-16 snapshots with a vector for either arm, and those whose every token has a decision row."""
    snaps: dict[Snapshot, set[str]] = defaultdict(set)
    for arm_snaps in vectors.values():
        for snap, bands in arm_snaps.items():
            snaps[snap] |= set(bands)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"snapshots": 0, "covered": 0})
    for snap, bands in snaps.items():
        counts[snap.slug]["snapshots"] += 1
        ok = True
        for band in bands:
            for side in SIDES:
                token = books.token_of.get((snap.slug, band, side))
                if token is None or books.tokens[token].decision_row(snap.t) is None:
                    ok = False
        counts[snap.slug]["covered"] += int(ok)
    return dict(counts)


def countable_events(vectors, cov, outcome_blind_pass: set[str]) -> dict[str, str]:
    """Event -> '' if countable before settlement, else the first failing reason."""
    arms = list(vectors)
    events = {snap.slug for arm_snaps in vectors.values() for snap in arm_snaps}
    reasons = {}
    for slug in sorted(events):
        has = [any(s.slug == slug for s in vectors[arm]) for arm in arms]
        c = cov.get(slug, {"snapshots": 0, "covered": 0})
        if not all(has):
            reasons[slug] = "arm_vector_missing"
        elif slug not in outcome_blind_pass:
            reasons[slug] = "outcome_blind_check_not_passed"
        elif c["snapshots"] == 0 or c["covered"] / c["snapshots"] < COVERAGE_MIN:
            reasons[slug] = "decision_row_coverage_below_90pct"
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
    """Entries, fills and caps for one arm, in decision-time order. Returns (trades, skip counts)."""
    if latency_s < MIN_LATENCY_S:
        raise RuleError(f"latency {latency_s} s below the {MIN_LATENCY_S} s floor")
    skips: dict[str, int] = defaultdict(int)
    trades: list[Trade] = []
    held: dict[tuple[str, str], str] = {}
    entries: dict[str, int] = defaultdict(int)
    md_notional: dict[str, float] = defaultdict(float)
    date_notional: dict[date, float] = defaultdict(float)
    ordered = sorted((snap for snap in arm_snaps if (snap.slug, snap.t) in both), key=lambda s: (s.t, s.slug))
    for snap in ordered:
        for band in sorted(arm_snaps[snap]):
            q = arm_snaps[snap][band]
            options = []
            for side in SIDES:
                token = books.token_of.get((snap.slug, band, side))
                row = books.tokens[token].decision_row(snap.t) if token else None
                if row is None or row.ask_count <= 0 or row.best_ask is None:
                    skips["no_decision_row"] += 1
                    continue
                q_side = q if side == "Yes" else 1.0 - q
                edge = net_edge(q_side, row.best_ask)
                if edge >= THETA:
                    options.append((-edge, SIDES.index(side), side, token, q_side, row.best_ask))
            if not options:
                continue
            _, _, side, token, q_side, ask = min(options)
            if (snap.slug, band) in held:
                skips["band_already_held"] += 1
                continue
            if entries[snap.slug] >= MAX_ENTRIES_PER_MARKET_DAY:
                skips["cap_entries"] += 1
                continue
            fill = books.tokens[token].fill_row(snap.t, latency_s)
            if fill is None:
                skips["no_fill_row"] += 1
                continue
            if fill.ask_count <= 0 or fill.best_ask is None or fill.best_ask > ask:
                skips["no_fill_price"] += 1
                continue
            shares = min(SHARES_REQUESTED, fill.ask_size or 0.0)
            if shares <= 0 or (fill.min_order_size is not None and shares < fill.min_order_size):
                skips["below_min_order_size"] += 1
                continue
            notional = shares * fill.best_ask
            if (md_notional[snap.slug] + notional > MAX_NOTIONAL_PER_MARKET_DAY + 1e-9
                    or date_notional[snap.target_date] + notional > MAX_NOTIONAL_PER_DATE + 1e-9):
                skips["cap_notional"] += 1
                continue
            held[(snap.slug, band)] = side
            entries[snap.slug] += 1
            md_notional[snap.slug] += notional
            date_notional[snap.target_date] += notional
            trades.append(Trade(arm, snap.slug, snap.target_date, snap.t, band, side, q_side, ask,
                                fill.best_ask, shares))
    return trades, dict(skips)


def load_winners(paths: list[Path], slugs: set[str]) -> dict[str, str]:
    """Event -> polymarket_winning_band ('' when the venue has no winner). Never reads a settlements ledger."""
    winners = {}
    for path in paths:
        if path.name != "settlement.json":
            raise RuleError(f"not a per-event settlement.json: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        slug = str(data.get("event_slug") or path.parent.name)
        if slug in slugs:
            winners[slug] = str(data.get("polymarket_winning_band") or "")
    return winners


def settle(trades: list[Trade], winners: dict[str, str]) -> None:
    for trade in trades:
        winner = winners.get(trade.slug, "")
        if not winner:
            continue
        won = trade.band == winner
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
        vals = [v for p in picks for v in groups[p]]
        out[i] = float(np.mean(vals))
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


def evaluate(arms, trades_by_arm, countable: dict[str, str], winners: dict[str, str], day_of: dict[str, date]):
    """Per-arm M, U (wider of the two bootstraps), counts and outcome; paired difference descriptive."""
    final = [slug for slug, reason in countable.items() if not reason and winners.get(slug)]
    y = {arm: {slug: 0.0 for slug in final} for arm in arms}
    filled = {arm: 0 for arm in arms}
    for arm in arms:
        for trade in trades_by_arm[arm]:
            if trade.slug in y[arm] and trade.pnl is not None:
                y[arm][trade.slug] += trade.pnl
                filled[arm] += 1
    n_dates = len({day_of[slug] for slug in final})
    summary = {"arms": {}, "countable_market_days": len(final), "countable_dates": n_dates}
    for arm in arms:
        bounds = bootstrap_bounds(y[arm], day_of)
        upper = max(b["upper"] for b in bounds.values()) if bounds else None
        values = list(y[arm].values())
        summary["arms"][arm] = {
            "M": float(np.mean(values)) if values else None, "U": upper, "bounds": bounds,
            "filled_entries": filled[arm], "sd_market_day": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "outcome": kill_outcome(n_dates, len(final), filled[arm], upper)}
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


def _guard_inputs(paths: list[Path]) -> None:
    for path in paths:
        text = str(path).replace("\\", "/").lower()
        if text.endswith("ledger.jsonl") or "/data/settlements/" in text or "config/local" in text:
            raise RuleError(f"forbidden input path: {path}")


def _read_list(path: Path) -> list[Path]:
    return [Path(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _csv_text(header: list[str], rows: list[list[object]]) -> str:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join('"' + str(v).replace('"', '""') + '"' if "," in str(v) else str(v) for v in row))
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    arms = tuple(args.arms)
    if arms[0] == arms[1] or args.window_end < args.window_start or args.latency_s < MIN_LATENCY_S:
        print("refused: arms must differ, window ordered, latency >= 30 s", file=sys.stderr)
        return 2
    book_paths, settlement_paths = _read_list(args.books_list), _read_list(args.settlements_list)
    inputs = [args.vectors, args.books_list, args.settlements_list, args.outcome_blind_pass, *book_paths,
              *settlement_paths]
    _guard_inputs(inputs)
    args.out.mkdir(parents=True, exist_ok=True)
    marker = args.out / MARKER_NAME
    if marker.exists() or any((args.out / name).exists() for name in OUTPUT_NAMES):
        print(f"refused: single look already taken in {args.out}", file=sys.stderr)
        return 3
    started = datetime.now().astimezone().isoformat()
    _write_new(marker, json.dumps({"started": started, "argv": sys.argv[1:] if argv is None else argv}) + "\n")
    module_sha = _sha256(Path(__file__))
    vectors = load_vectors(args.vectors, arms, args.window_start, args.window_end, set(args.exclude_slug))
    slugs = {snap.slug for snaps in vectors.values() for snap in snaps}
    day_of = {snap.slug: snap.target_date for snaps in vectors.values() for snap in snaps}
    books = load_books(book_paths, slugs)
    cov = coverage(vectors, books)
    passed = {line.strip() for line in args.outcome_blind_pass.read_text(encoding="utf-8").splitlines() if line.strip()}
    countable = countable_events(vectors, cov, passed)
    manifest = {"schema_version": schema_version("t2_taker_rule_input_manifest"), "module_sha256": module_sha,
                "arms": list(arms), "window": [args.window_start.isoformat(), args.window_end.isoformat()],
                "excluded_slugs": sorted(args.exclude_slug), "latency_s": args.latency_s,
                "inputs": {str(p): _sha256(p) for p in inputs}, "book_rows_read": books.rows_read,
                "book_rows_unusable": books.unusable_rows, "coverage": cov, "countable_before_settlement": countable}
    _write_new(args.out / "input_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    both = set.intersection(*({(s.slug, s.t) for s in vectors[arm]} for arm in arms))
    trades_by_arm, skips = {}, {}
    for arm in arms:
        trades_by_arm[arm], skips[arm] = run_arm(arm, vectors[arm], both, books, args.latency_s)
    winners = load_winners(settlement_paths, slugs)
    for arm in arms:
        settle(trades_by_arm[arm], winners)
    summary, y = evaluate(arms, trades_by_arm, countable, winners, day_of)
    summary.update({"schema_version": schema_version("t2_taker_rule_summary"), "module_sha256": module_sha,
                    "skips": skips, "no_venue_winner": sorted(s for s in slugs if not winners.get(s))})
    trade_rows = [[t.arm, t.slug, t.target_date, t.t.isoformat(), t.band, t.side, t.q_side, t.decision_ask,
                   t.fill_price, t.shares, "" if t.payout is None else t.payout, "" if t.pnl is None else t.pnl,
                   int(not countable.get(t.slug) and bool(winners.get(t.slug)))]
                  for arm in arms for t in trades_by_arm[arm]]
    _write_new(args.out / "trades.csv", _csv_text(
        ["arm", "event_slug", "target_date", "decision_utc", "range_label", "side", "q_side", "decision_ask",
         "fill_price", "shares", "payout", "pnl", "countable"], trade_rows))
    md_rows = [[slug, day_of[slug], countable[slug] or ("no_venue_winner" if not winners.get(slug) else ""),
                *[y[arm].get(slug, "") for arm in arms]] for slug in sorted(countable)]
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
