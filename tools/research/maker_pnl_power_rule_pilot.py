"""Desk-study power rule (N_req) on the 88a variance pilot; read-only, never trades.

Authority: the maker P&L adverse-selection pre-registration
``docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md`` frozen at
574f8369b4620ac32e360a2207cdda4acd9d947a, with Clarification 1 at
67e44273bd64bad7935d5015c218f110f55fd645 (branch ``codex/maker-pnl-adverse-selection-20261001``;
file sha256 18bbee6c5b1a26c824573a8a5e38702cfa8a6913103e8557b72ce57aaa9ea893). Owner approval to run it
now: DECISION_LOG 2026-10-07 18:02, "run the desk-study power rule now, and if N_req <= 14 move the
embargo end 11-13 -> 10-31 by dated clarification".

Pre-registered text this script implements (quoted, lines 118-133 of the frozen file)::

    Power rule (fixed now; run on the pilot before any panel read):
      - sigma_up = the upper 90% chi-square bound on the pilot's sigma_d;
      - delta = 1.0 pUSD per band-day, the minimum effect that matters for the sign question.
        It is fixed here, not taken from the pilot.
      - N_req = ceil(((1.645 + 0.842) * sigma_up / delta)^2), which is 80% power for the 90%
        two-sided interval to exclude zero when |theta| = delta.
    The branch is fixed by N_req:
      <= 14  the panel stays 14 dates
      15-28  extended to N_req consecutive event dates from 2026-10-17, recorded as a dated
             clarification before any panel read
      > 28   declared UNDECIDABLE_AT_DELTA; run descriptive only, with the achieved MDE reported
    If the pilot has fewer than 2 surviving dates, sigma_d is undefined and the panel runs at 28 dates.

Clarification 1 point 3 (quoted)::

    sigma_d is the sample standard deviation (denominator n - 1) of the pilot's date-mean NP_S
    under the primary (continuous stratum, strictly-through, k_share 0.3), over the n surviving
    pilot dates. sigma_up is its one-sided 90% upper confidence bound:
        sigma_up = sigma_d * sqrt((n - 1) / c),  c = the 0.10 lower-tail quantile of chi-square
        with n - 1 degrees of freedom
    ... N_req keeps its frozen formula, with z values 1.645 and 0.842 and no t-correction. The
    report states n, sigma_d, c, sigma_up and N_req.

Part 1 (quoted): "Dates: quote-minutes on local dates 2026-09-24..2026-09-28 (88a starts 2026-09-25
06:34Z) for bands whose event date is 2026-09-26..2026-09-29. That gives at most 4 date clusters.
Never read: any 88a UTC day from 2026-09-30 on, and any band whose event date is 2026-09-30 or
later." Its only function "is sigma_d: the across-date standard deviation of the date-mean NP_S".

NP_S per band-day, as frozen: ``NP_S(b) = Rew(b) + Spread(b) - AS_S(b)``;
``Spread(b) = sum q*|m_t - p|``; ``AS_S(b) = -sum q*s*(m_S - m_t)`` (s = +1 YES bid, -1 NO bid, YES-price
terms); ``Rew(b) = sum over admissible minutes of rate/1440 * share_many * k_share`` with k_share 0.3 and
``share_many`` from ``weather.market.reward_share_estimate``. Quote: two-sided, 75 shares per leg, 1.5 c
target distance from the size-adjusted midpoint, snapped outward to the tick, re-placed at full size at
each selected book sample (first capture per UTC minute, >= 30 s spacing, 5-minute maximum rest:
89a Clarifications 2-3). Admissible quote-minute: both sides displayed, not crossed; size-adjusted mid
in [0.10, 0.90]; displayed depth >= max(75, min size) on each side within the max spread; reward terms
captured at or before the minute and <= 60 minutes old; min size <= 75 and 1.5 c within the max spread.
Band-day: condition x local quote date, T+1/T+2 only, >= 60 admissible minutes, and >= 90% of its local
quote-day minutes with a book capture. Markout mid: two-sided top-of-book mid, last sample at or before
the fill within 120 s. Settlement mark: 1/0 from the ledger's venue resolution. Date cluster = event date.

Implementation defaults ("take the option that lowers Rew or raises AS", prereg :152-153) and the
choices the text leaves open are listed in ``IMPLEMENTATION_CHOICES`` and ``OWNER_QUESTIONS`` and are
copied into every output.

Guards (hard refusals, before any content is decoded): any requested or encountered input date after
2026-09-29 (which covers the 2026-09-30..2026-10-15 embargo); any 88a day folder outside
2026-09-25..2026-09-29; any band whose event date is not 2026-09-26..2026-09-29 (its book files are
never opened; its prints are dropped on parse); any ledger row is decoded only when every
``target_date`` it carries is 2026-09-26..2026-09-29 (others are skipped undecoded and counted);
unsealed segments are never read; a sealed file whose bytes disagree with its manifest refuses the run;
output under any ``data`` directory or onto an existing path refuses.

``--dry-run`` reads directory metadata only (names and sizes), applies every date guard and prints the
plan; no file content is opened. Output JSON is deterministic (sorted keys); ``result_sha256`` covers
everything except the ``envelope`` (``generated_at``, ``master_sha``, peak memory, elapsed time).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
from array import array
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from weather.market import reward_share_estimate as rse  # noqa: E402
from weather.market.maker_evidence_public import reward_rate  # noqa: E402
from weather.market.market_config import event_slug_for_date  # noqa: E402
from weather.market.market_registry import all_specs  # noqa: E402

SCHEMA = "maker_pnl_power_rule_pilot.v1"
PREREG = {
    "file": "docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md",
    "branch": "codex/maker-pnl-adverse-selection-20261001",
    "freeze_commit": "574f8369b4620ac32e360a2207cdda4acd9d947a",
    "clarification_1_commit": "67e44273bd64bad7935d5015c218f110f55fd645",
    "file_sha256_at_clarification_1": "18bbee6c5b1a26c824573a8a5e38702cfa8a6913103e8557b72ce57aaa9ea893",
    "power_rule_lines": "118-133; Clarification 1 point 3 lines 202-212",
    "owner_approval": "DECISION_LOG 2026-10-07 18:02 (row 140)",
}

LAST_ALLOWED_DATE = date(2026, 9, 29)
EMBARGO = (date(2026, 9, 30), date(2026, 10, 15))
UTC_DAYS = tuple(date(2026, 9, d) for d in range(25, 30))
EVENT_DATES = tuple(date(2026, 9, d) for d in range(26, 30))
QUOTE_DATES = tuple(date(2026, 9, d) for d in range(24, 29))
DTE_ALLOWED = (1, 2)
CUTOFF_EPOCH = datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()

QUOTE_SIZE = 75.0
DISTANCE_CENTS = 1.5
MID_RANGE = (0.10, 0.90)
TERMS_MAX_AGE = 3600.0
MAX_REST = 300.0
MIN_SPACING = 30.0
MARK_TOLERANCE = 120.0
K_SHARE = 0.3
MIN_ADMISSIBLE_MINUTES = 60
MIN_BOOK_COVERAGE = 0.90
Z_ALPHA, Z_BETA = 1.645, 0.842
DELTA = 1.0
CHI2_LOWER_TAIL = 0.10
BASE_PANEL, MAX_PANEL = 14, 28
EMBARGO_END_NOW, EMBARGO_END_IF_14 = "2026-11-13", "2026-10-31"
MAX_LINE = 16 * 1024 ** 2
SEGMENT_RE = re.compile(r"(\d{2})-[0-9a-f]{12}")
LEDGER_DATE_RE = re.compile(rb'"target_date": ?"(\d{4}-\d{2}-\d{2})"')

IMPLEMENTATION_CHOICES = (
    "N_req = ceil of the frozen expression after rounding it to 9 decimals, so float noise cannot add a date; the "
    "unrounded value is reported.",
    "Date cluster = event date (prereg: 'at most 4 date clusters' from event dates 09-26..09-29; panel N counts event dates).",
    "Each leg fills only from prints on its own token (YES bid: YES print strictly below p_bid; NO bid: NO print strictly "
    "below 1 - p_ask). Opposite-token prints that would also qualify in YES terms are counted in diagnostics, never filled.",
    "Prints are ordered by venue timestamp, ties by capture order; prints at a book-sample instant hit the expiring quote "
    "first (89a model tie rule).",
    "Reward rate = sum of rewards_config rate_per_day whose start/end dates contain the minute's UTC date "
    "(maker_evidence_public.reward_rate); 89a summed every config (higher Rew).",
    "Admissibility is re-checked at every minute boundary of a resting quote against that minute's terms; failure withdraws "
    "both legs until the next sample (lowers Rew).",
    "'Within the maximum spread' uses distance strictly below max spread from the size-adjusted midpoint (order_score "
    "scores 0 at the limit); '1.5 c within the max spread' is 1.5 < max spread.",
    "Each band-day is simulated alone over its local day; legs start withdrawn until the day's first selected sample "
    "(lowers Rew by at most one sample interval).",
    "Markout mid m_t = last two-sided, uncrossed YES-book sample at or before the fill, within 120 s; a fill without one "
    "removes its band-day from the settlement panel (prereg: missing mark leaves the panel with the band-day's whole value).",
    "Settlement mark keyed by the winning condition_id stored beside polymarket_winning_band in the same ledger "
    "reconciliation (88a stores no band label); missing/ambiguous winner = no ledger mark.",
    "Only 'books' captures (post-selection minute read) are book samples; 'ranking_books' are not used.",
    "Universe membership rows (one JSON per city) are decoded to find pilot bands; entries whose event slug is not a "
    "09-26..09-29 pilot event are discarded by slug before any book, print or reward file is opened.",
)
OWNER_QUESTIONS = (
    "Q1 (prints): should a NO-bid leg also fill from YES-token prints above p_ask (and the YES bid from NO prints), i.e. one "
    "YES-terms print stream? The prereg says 'a public print strictly through the leg price' without naming the token; the "
    "default here is own-token only. Diagnostics report how many opposite-token prints would have qualified.",
    "Q2 (power branch 15-28 vs embargo): DECISION_LOG row 140 only rules N_req <= 14. For 15-28 the panel extends to N_req "
    "event dates; the embargo end then is not ruled (reported as UNCHANGED here).",
)


class Refused(RuntimeError):
    """A frozen guard refused the run; nothing after the refusal is computed."""


def guard_date(value, what):
    value = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    if EMBARGO[0] <= value <= EMBARGO[1]:
        raise Refused(f"{what} {value} is inside the 2026-09-30..2026-10-15 embargo")
    if value > LAST_ALLOWED_DATE:
        raise Refused(f"{what} {value} is after 2026-09-29")
    return value


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def epoch(text):
    try:
        parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp() if parsed.tzinfo else None


# --------------------------------------------------------------------------- power rule (pure)

def chi2_lower_quantile(p, df):
    from scipy.stats import chi2
    return float(chi2.ppf(p, df))


def power_rule(date_means):
    """Frozen power rule over {event_date: date-mean NP_S}; returns every reported number."""
    dates = sorted(date_means)
    n = len(dates)
    result = {"n": n, "dates": dates, "date_mean_np_s": {d: date_means[d] for d in dates},
              "delta_pusd_per_band_day": DELTA, "z_alpha": Z_ALPHA, "z_beta": Z_BETA,
              "chi2_lower_tail": CHI2_LOWER_TAIL}
    if n < 2:
        return {**result, "sigma_d": None, "c": None, "sigma_up": None, "n_req": None,
                "branch": "SIGMA_D_UNDEFINED_PANEL_28", "panel_event_dates": MAX_PANEL}
    values = [date_means[d] for d in dates]
    mean = math.fsum(values) / n
    sigma_d = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (n - 1))
    c = chi2_lower_quantile(CHI2_LOWER_TAIL, n - 1)
    sigma_up = sigma_d * math.sqrt((n - 1) / c)
    raw = ((Z_ALPHA + Z_BETA) * sigma_up / DELTA) ** 2
    n_req = math.ceil(round(raw, 9))
    if n_req <= BASE_PANEL:
        branch, panel = "PANEL_STAYS_14", BASE_PANEL
    elif n_req <= MAX_PANEL:
        branch, panel = "PANEL_EXTENDED_TO_N_REQ", n_req
    else:
        branch, panel = "UNDECIDABLE_AT_DELTA", BASE_PANEL
    return {**result, "sigma_d": sigma_d, "c": c, "sigma_up": sigma_up, "n_req_unrounded": raw,
            "n_req": n_req, "branch": branch, "panel_event_dates": panel}


def decision(rule):
    """Owner approval 2026-10-07: N_req <= 14 moves the embargo end 11-13 -> 10-31 by dated clarification."""
    n_req = rule.get("n_req")
    if n_req is not None and n_req <= BASE_PANEL:
        return {"action": "WRITE_DATED_CLARIFICATION_MOVE_EMBARGO_END",
                "embargo_end_from": EMBARGO_END_NOW, "embargo_end_to": EMBARGO_END_IF_14,
                "basis": "N_req <= 14 (DECISION_LOG 2026-10-07 18:02)"}
    return {"action": "EMBARGO_END_UNCHANGED", "embargo_end_from": EMBARGO_END_NOW,
            "embargo_end_to": EMBARGO_END_NOW,
            "basis": "sigma_d undefined (panel 28)" if n_req is None else f"N_req = {n_req} > 14"}


# --------------------------------------------------------------------------- simulation (pure)

@dataclass(frozen=True)
class Terms:
    captured: float
    configs: tuple  # ((rate_per_day, start_date, end_date), ...)
    min_size: float
    max_spread: float

    def rate(self, minute):
        today = datetime.fromtimestamp(minute, timezone.utc).date().isoformat()
        return reward_rate({"rewards_config": [{"rate_per_day": r, "start_date": s, "end_date": e}
                                               for r, s, e in self.configs]}, today)


@dataclass
class Sample:
    at: float
    bids: array
    asks: array
    tick: float

    def levels(self, side):
        flat = self.bids if side == 0 else self.asks
        return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def make_sample(at, bids, asks, tick):
    flat_b, flat_a = array("d"), array("d")
    for price, size in bids:
        flat_b.extend((price, size))
    for price, size in asks:
        flat_a.extend((price, size))
    return Sample(at, flat_b, flat_a, tick if tick and tick > 0 else rse.DEFAULT_TICK)


def terms_at(terms_list, minute):
    """Latest terms captured at or before the minute and at most 60 minutes old (else None)."""
    keys = [t.captured for t in terms_list]
    index = bisect_right(keys, minute) - 1
    if index < 0:
        return None
    terms = terms_list[index]
    return terms if 0 <= minute - terms.captured <= TERMS_MAX_AGE else None


def admissible(sample, terms):
    """(reason or None, size-adjusted mid) for one book under one minute's terms."""
    if terms is None:
        return "terms_missing_or_stale", None
    if not (terms.min_size <= QUOTE_SIZE):
        return "min_size_above_75", None
    if not (DISTANCE_CENTS < terms.max_spread):
        return "distance_outside_max_spread", None
    bids, asks = sample.levels(0), sample.levels(1)
    raw_bid, raw_ask = rse.best_prices(bids, asks)
    if raw_bid is None or raw_ask is None:
        return "one_sided", None
    if raw_bid >= raw_ask:
        return "crossed", None
    bid, ask = rse.best_prices(bids, asks, terms.min_size)
    if bid is None or ask is None:
        return "one_sided_after_size_cutoff", None
    if bid >= ask:
        return "crossed_after_size_cutoff", None
    mid = (bid + ask) / 2.0
    if not (MID_RANGE[0] <= mid <= MID_RANGE[1]):
        return "mid_outside_range", None
    need = max(QUOTE_SIZE, terms.min_size)
    depth_bid = sum(s for p, s in bids if (mid - p) * 100.0 < terms.max_spread)
    depth_ask = sum(s for p, s in asks if (p - mid) * 100.0 < terms.max_spread)
    if depth_bid < need or depth_ask < need:
        return "depth_below_requirement", None
    return None, mid


def selected(samples):
    """First capture per UTC minute, then the 30-second spacing filter (89a Clarification 3)."""
    out, minute_seen, last = [], None, -math.inf
    for sample in samples:
        minute = int(sample.at // 60)
        if minute == minute_seen:
            continue
        minute_seen = minute
        if sample.at - last < MIN_SPACING:
            continue
        last = sample.at
        out.append(sample)
    return out


def markout_series(samples):
    times, mids = [], []
    for sample in samples:
        bid, ask = rse.best_prices(sample.levels(0), sample.levels(1))
        if bid is not None and ask is not None and bid < ask:
            times.append(sample.at)
            mids.append((bid + ask) / 2.0)
    return times, mids


def markout_mid(series, at):
    times, mids = series
    index = bisect_right(times, at) - 1
    if index < 0 or at - times[index] > MARK_TOLERANCE:
        return None
    return mids[index]


def simulate_band_day(samples, prints, terms_list, start, end, *, k_share=K_SHARE):
    """Continuous stratum, strictly-through fills, one band-day [start, end).

    samples: chronological YES-book Samples (all captures); prints: (at, leg, price, size, order) with
    leg 0 = YES-token print, 1 = NO-token print, price in that token's terms. Returns components plus
    fills [(at, shares, yes_price, s)].
    """
    picks = [s for s in selected(samples) if start <= s.at < end]
    trades = sorted((p for p in prints if start <= p[0] < end), key=lambda p: (p[0], p[4]))
    diag = Counter()
    fills, minutes = [], set()
    reward = 0.0
    prices = [None, None]
    remaining = [0.0, 0.0]
    live, book, expiry = False, None, start
    bi = ti = 0
    at = start
    while at < end:
        minute = math.floor(at / 60) * 60
        terms = terms_at(terms_list, minute)
        if live and (at >= expiry or admissible(book, terms)[0] is not None):
            live, remaining = False, [0.0, 0.0]
        while ti < len(trades) and trades[ti][0] == at:
            _, leg, price, size, _ = trades[ti]
            if live and remaining[leg] > 0:
                limit = prices[0] if leg == 0 else round(1.0 - prices[1], 9)
                if price < limit:
                    shares = min(size, remaining[leg])
                    remaining[leg] -= shares
                    fills.append((at, shares, prices[leg], 1 if leg == 0 else -1))
            elif live:
                diag["prints_on_exhausted_leg"] += 1
            if live:
                other = 1 - leg
                yes_terms = price if leg == 0 else 1.0 - price
                if remaining[other] > 0 and (yes_terms > prices[1] if other == 1 else yes_terms < prices[0]):
                    diag["opposite_token_prints_that_would_qualify"] += 1
            ti += 1
        if bi < len(picks) and picks[bi].at == at:
            book, expiry = picks[bi], min(end, at + MAX_REST)
            reason, mid = admissible(book, terms)
            if reason is None:
                quote = rse.hypothetical_quote(mid, DISTANCE_CENTS, book.tick)
                prices = [quote["bid_price"], quote["ask_price"]]
                live = None not in prices
                remaining = [QUOTE_SIZE, QUOTE_SIZE] if live else [0.0, 0.0]
                diag["samples_admissible" if live else "samples_unpriceable"] += 1
            else:
                live, remaining = False, [0.0, 0.0]
                diag["samples_inadmissible_" + reason] += 1
            bi += 1
        next_at = min(end, minute + 60,
                      picks[bi].at if bi < len(picks) else end,
                      trades[ti][0] if ti < len(trades) else end,
                      expiry if live and expiry > at else end)
        if next_at <= at:
            raise Refused("non-advancing simulation clock")
        if live:
            minutes.add(minute)
            _, mid = admissible(book, terms)
            bids, asks = book.levels(0), book.levels(1)
            comp_one, _ = rse.side_score(bids, mid, terms.max_spread, terms.min_size)
            comp_two, _ = rse.side_score(asks, mid, terms.max_spread, terms.min_size)
            own_one = rse.order_score(remaining[0], (mid - prices[0]) * 100.0, terms.max_spread, terms.min_size)
            own_two = rse.order_score(remaining[1], (prices[1] - mid) * 100.0, terms.max_spread, terms.min_size)
            share = rse.share_of(rse.q_min(own_one, own_two, mid), (comp_one + comp_two) / 2.0)
            reward += terms.rate(minute) / 1440.0 * share * k_share * (next_at - at) / 60.0
        at = next_at
    return {"reward": reward, "fills": fills, "admissible_minutes": len(minutes), "diagnostics": dict(diag)}


def score_band_day(sim, series, mark):
    """Spread, AS_S and NP_S; None with a reason when the settlement panel loses the band-day."""
    spread = adverse = 0.0
    for at, shares, price, side in sim["fills"]:
        mid = markout_mid(series, at)
        if mid is None:
            return None, "fill_missing_markout_mid"
        if mark is None:
            return None, "fill_without_settlement_mark"
        spread += shares * abs(mid - price)
        adverse += -shares * side * (mark - mid)
    return {"rew": sim["reward"], "spread": spread, "as_s": adverse,
            "np_s": sim["reward"] + spread - adverse}, None


def date_means(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row.get("np_s") is not None:
            grouped[row["event_date"]].append(row["np_s"])
    return {d: math.fsum(v) / len(v) for d, v in sorted(grouped.items())}


# --------------------------------------------------------------------------- sealed 88a reading

class Segment:
    def __init__(self, folder):
        self.folder = folder
        seal = next((folder / n for n in ("manifest.json", "manifest.json.gz") if (folder / n).is_file()), None)
        self.seal = seal
        self.files = {}
        self.manifest_sha256 = None
        if seal is not None:
            raw = (gzip.open if seal.suffix == ".gz" else open)(seal, "rb").read(2 * 1024 ** 2 + 1)
            self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
            info = json.loads(raw)
            self.files = info.get("files") or {}

    def path(self, name):
        for candidate in (self.folder / name, self.folder / (name + ".gz")):
            if candidate.is_file():
                return candidate
        return None

    def rows(self, name, hashes):
        """Yield (offset, row) from a manifest-listed file; verify bytes, records and sha256."""
        expected = self.files.get(name)
        path = self.path(name)
        if expected is None or path is None:
            return
        digest, size, count = hashlib.sha256(), 0, 0
        with (gzip.open if path.suffix == ".gz" else open)(path, "rb") as handle:
            while line := handle.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise Refused(f"oversized or torn record: {path}")
                digest.update(line)
                offset, size, count = size, size + len(line), count + 1
                yield offset, json.loads(line)
        if (digest.hexdigest(), size, count) != (expected.get("sha256"), expected.get("bytes"), expected.get("records")):
            raise Refused(f"sealed file integrity mismatch: {path}")
        hashes[str(path)] = expected["sha256"]


def segments_for(root, days, diag):
    out = []
    for day in days:
        guard_date(day, "88a UTC day")
        folder = Path(root) / day.isoformat()
        if not folder.is_dir():
            diag["missing_88a_days"].append(day.isoformat())
            continue
        for seg in sorted(folder.iterdir()):
            if not seg.is_dir() or not SEGMENT_RE.fullmatch(seg.name):
                continue
            segment = Segment(seg)
            if segment.seal is None:
                diag["unsealed_segments_skipped"].append(f"{day.isoformat()}/{seg.name}")
                continue
            segment.start = datetime.combine(day, dtime(int(seg.name[:2])), timezone.utc).timestamp()
            out.append(segment)
    return out


def body_of(row):
    if "body_utf8" in row:
        return row["body_utf8"]
    if "body_base64" in row:
        return base64.b64decode(row["body_base64"], validate=True).decode("utf-8")
    raise Refused("88a record without an inline body")


def pilot_slugs():
    return {event_slug_for_date(d, spec.id): (spec, d) for spec in all_specs() for d in EVENT_DATES}


def scan_universe(segments, hashes, diag):
    slugs, bands = pilot_slugs(), {}
    for seg in segments:
        for name in sorted(n for n in seg.files if n.startswith("universe-")):
            for _, row in seg.rows(name, hashes):
                if row.get("kind") != "universe":
                    continue
                for band in json.loads(body_of(row)).get("bands", []):
                    slug = band.get("event_slug")
                    if slug not in slugs:
                        diag["universe_band_rows_outside_pilot_events"] += 1
                        continue
                    spec, event_date = slugs[slug]
                    cid = str(band["condition_id"]).lower()
                    entry = {"condition_id": cid, "market": spec.id, "event_slug": slug,
                             "event_date": event_date.isoformat(), "yes": str(band["tokens"][0]),
                             "no": str(band["tokens"][1])}
                    if cid in bands and bands[cid] != entry:
                        raise Refused(f"condition {cid} mapped to conflicting universe rows")
                    bands[cid] = entry
    return bands


def read_event_inputs(segments, bands, hashes, diag):
    """Books (YES token), prints (both tokens) and reward terms for the given pilot bands only."""
    tokens = {}
    for cid, band in bands.items():
        tokens[band["yes"]] = (cid, 0)
        tokens[band["no"]] = (cid, 1)
    samples = defaultdict(list)
    prints = defaultdict(list)
    terms = defaultdict(list)
    order = 0
    reward_files = {"reward-" + hashlib.sha256(f"reward:{cid}:first".encode()).hexdigest()[:24] + ".jsonl": cid
                    for cid in bands}
    for seg in segments:
        index = {}
        if "books.jsonl" in seg.files:
            for _, row in seg.rows("books.jsonl", hashes):
                if row.get("kind") != "books" or row.get("http_status") != 200:
                    continue
                at = epoch(row.get("captured_at_utc"))
                if "parts" in row:
                    for part in row["parts"]:
                        if "file" in part:
                            index[(part["file"], part["offset"])] = (at, row["sequence"])
                else:
                    for book in json.loads(body_of(row)):
                        if str(book.get("asset_id")) in tokens and tokens[str(book["asset_id"])][1] == 0:
                            add_book(samples, tokens, book, at, diag)
        for token, (cid, leg) in sorted(tokens.items()):
            name = f"book-{token}.jsonl"
            if leg != 0 or name not in seg.files:
                continue
            for offset, row in seg.rows(name, hashes):
                hit = index.get((name, offset))
                if hit is None:
                    continue  # ranking_books constituent
                if row.get("sequence") != hit[1]:
                    raise Refused(f"book constituent sequence mismatch: {seg.folder}/{name}")
                add_book(samples, tokens, json.loads(row["body_utf8"]), hit[0], diag)
        if "trades.jsonl" in seg.files:
            for _, row in seg.rows("trades.jsonl", hashes):
                body = body_of(row)
                if not any(token in body for token in tokens):
                    continue
                payload = json.loads(body)
                for event in payload if isinstance(payload, list) else [payload]:
                    asset = str(event.get("asset_id"))
                    if event.get("event_type") != "last_trade_price" or asset not in tokens:
                        continue
                    try:
                        at = float(event["timestamp"]) / 1000.0
                        price, size = float(event["price"]), float(event["size"])
                    except (KeyError, TypeError, ValueError):
                        diag["prints_undecodable_skipped"] += 1
                        continue
                    order += 1
                    cid, leg = tokens[asset]
                    prints[cid].append((at, leg, price, size, order))
        for name, cid in sorted(reward_files.items()):
            if name not in seg.files:
                continue
            stored = {}
            for offset, row in seg.rows(name, hashes):
                if row.get("kind") != "rewards" or row.get("http_status") != 200:
                    continue
                if row.get("body_stored"):
                    stored[offset] = row
                    source = row
                else:
                    ref = row.get("payload_ref") or {}
                    if ref.get("file") != name or ref.get("offset") not in stored:
                        raise Refused(f"unresolvable reward payload reference: {seg.folder}/{name}")
                    source = stored[ref["offset"]]
                at = epoch(row.get("captured_at_utc"))
                for item in json.loads(body_of(source)).get("data", []):
                    if str(item.get("condition_id", "")).lower() != cid:
                        raise Refused(f"reward record condition mismatch: {seg.folder}/{name}")
                    parsed = parse_terms(item, at)
                    if parsed is None:
                        diag["reward_records_incomplete_skipped"] += 1
                    else:
                        terms[cid].append(parsed)
    for cid in samples:
        samples[cid].sort(key=lambda s: s.at)
    for cid in terms:
        terms[cid].sort(key=lambda t: t.captured)
    return samples, prints, terms


def add_book(samples, tokens, book, at, diag):
    cid, _ = tokens[str(book.get("asset_id"))]
    bids, bad_b = rse.parse_levels(book.get("bids"))
    asks, bad_a = rse.parse_levels(book.get("asks"))
    if at is None:
        diag["books_without_capture_time_skipped"] += 1
        return
    diag["malformed_levels"] += bad_b + bad_a
    try:
        tick = float(book.get("tick_size"))
    except (TypeError, ValueError):
        tick = rse.DEFAULT_TICK
    samples[cid].append(make_sample(at, bids, asks, tick))


def parse_terms(item, at):
    try:
        min_size = float(item["rewards_min_size"])
        spread = float(item["rewards_max_spread"])
        configs = tuple((float(c["rate_per_day"]), str(c["start_date"]), str(c["end_date"]))
                        for c in item.get("rewards_config") or [])
    except (KeyError, TypeError, ValueError):
        return None
    if at is None or not all(math.isfinite(x) for x in (min_size, spread)):
        return None
    return Terms(at, configs, min_size, spread)


# --------------------------------------------------------------------------- ledger

def ledger_marks(settlement_root, diag, hashes):
    """{event_slug: winning condition_id or None}; rows outside the pilot are never decoded."""
    marks = {}
    slugs = pilot_slugs()
    allowed = {d.isoformat().encode() for d in EVENT_DATES}
    for spec in all_specs():
        folder = Path(settlement_root) / spec.id
        path = next((folder / n for n in ("ledger.2026-09-26_2026-09-29.jsonl", "ledger.jsonl")
                     if (folder / n).is_file()), None)
        if path is None:
            diag["ledger_missing_markets"].append(spec.id)
            continue
        rows = defaultdict(list)
        decoded = hashlib.sha256()
        with open(path, "rb") as handle:
            for line in handle:
                found = LEDGER_DATE_RE.findall(line)
                if not found:
                    if line.strip():
                        diag["ledger_rows_without_target_date_skipped"] += 1
                    continue
                if not all(d in allowed for d in found):
                    diag["ledger_rows_outside_pilot_skipped_undecoded"] += 1
                    continue
                decoded.update(line)
                row = json.loads(line)
                guard_date(row["target_date"], "ledger target_date")
                if row.get("event_slug") in slugs:
                    rows[row["event_slug"]].append(row)
        # Only the decoded pilot rows are hashed: rows outside 09-26..09-29 are never read past the prefilter.
        hashes[str(path) + "#pilot-rows"] = decoded.hexdigest()
        for slug, candidates in rows.items():
            from weather.backtesting.settlement_ledger import clean_temperature_label, current_ledger_label
            label = current_ledger_label(candidates, slug)
            winners = ((label.get("polymarket_reconciliation") or {}).get("winning_markets") or [])
            band = label.get("polymarket_winning_band")
            if (not band or len(winners) != 1 or not winners[0].get("condition_id")
                    or clean_temperature_label(winners[0].get("label")) != clean_temperature_label(band)):
                marks[slug] = None
                diag["ledger_rows_without_unique_venue_winner"] += 1
            else:
                marks[slug] = str(winners[0]["condition_id"]).lower()
    return marks


# --------------------------------------------------------------------------- driver

def local_day(spec, day):
    start = datetime.combine(day, dtime(), spec.tz).timestamp()
    end = datetime.combine(day + timedelta(days=1), dtime(), spec.tz).timestamp()
    return start, end


def utc_days_for(event_date):
    first = min(local_day(s, event_date - timedelta(days=2))[0] for s in all_specs()) - TERMS_MAX_AGE - MAX_REST
    last = max(local_day(s, event_date - timedelta(days=1))[1] for s in all_specs())
    days, day = [], datetime.fromtimestamp(first, timezone.utc).date()
    while datetime.combine(day, dtime(), timezone.utc).timestamp() < last:
        if day in UTC_DAYS:
            days.append(day)
        day += timedelta(days=1)
    return days


def run(args):
    started = time.monotonic()
    root, settle = Path(args.maker_evidence_root), Path(args.settlement_root)
    diag = defaultdict(int)
    for key in ("missing_88a_days", "unsealed_segments_skipped", "ledger_missing_markets"):
        diag[key] = []
    hashes = {}
    specs = {spec.id: spec for spec in all_specs()}
    for spec in specs.values():
        for quote_day in QUOTE_DATES:
            if local_day(spec, quote_day)[1] > CUTOFF_EPOCH:
                raise Refused(f"{spec.id} local {quote_day} ends after 2026-09-29 UTC")
    all_segments = segments_for(root, UTC_DAYS, diag)
    bands = scan_universe(all_segments, hashes, diag)
    marks = ledger_marks(settle, diag, hashes)
    rows = []
    for event_date in EVENT_DATES:
        guard_date(event_date, "event date")
        event_bands = {c: b for c, b in bands.items() if b["event_date"] == event_date.isoformat()}
        days = utc_days_for(event_date)
        segments = [s for s in all_segments if datetime.fromtimestamp(s.start, timezone.utc).date() in days]
        samples, prints, terms = read_event_inputs(segments, event_bands, hashes, diag)
        for cid, band in sorted(event_bands.items()):
            spec = specs[band["market"]]
            series = markout_series(samples.get(cid, []))
            slug = band["event_slug"]
            mark = None
            if slug in marks and marks[slug] is not None:
                mark = 1.0 if marks[slug] == cid else 0.0
            for dte in DTE_ALLOWED:
                quote_day = event_date - timedelta(days=dte)
                start, end = local_day(spec, quote_day)
                expected = round((end - start) / 60)
                covered = {int((s.at - start) // 60) for s in samples.get(cid, []) if start <= s.at < end}
                row = {"condition_id": cid, "market": spec.id, "event_date": event_date.isoformat(),
                       "quote_date": quote_day.isoformat(), "dte": dte, "book_coverage": len(covered) / expected,
                       "settlement_mark": mark, "np_s": None}
                if len(covered) / expected < MIN_BOOK_COVERAGE:
                    rows.append({**row, "excluded": "book_coverage_below_90pct"})
                    continue
                sim = simulate_band_day(samples.get(cid, []), prints.get(cid, []), terms.get(cid, []), start, end)
                row.update(admissible_minutes=sim["admissible_minutes"], fills=len(sim["fills"]),
                           filled_shares=math.fsum(f[1] for f in sim["fills"]), diagnostics=sim["diagnostics"])
                if sim["admissible_minutes"] < MIN_ADMISSIBLE_MINUTES:
                    rows.append({**row, "excluded": "fewer_than_60_admissible_minutes"})
                    continue
                scored, reason = score_band_day(sim, series, mark)
                if scored is None:
                    rows.append({**row, "excluded": reason})
                    continue
                per60 = scored["np_s"] * 60.0 / sim["admissible_minutes"]
                rows.append({**row, **scored, "np_s_per_60_quote_minutes": per60, "excluded": None})
        del samples, prints, terms
    means = date_means(rows)
    rule = power_rule(means)
    payload = {
        "schema_version": SCHEMA, "preregistration": PREREG,
        "frozen_constants": {"utc_days": [d.isoformat() for d in UTC_DAYS],
                             "event_dates": [d.isoformat() for d in EVENT_DATES],
                             "quote_size": QUOTE_SIZE, "distance_cents": DISTANCE_CENTS, "k_share": K_SHARE,
                             "fill_rule": "strictly-through", "stratum": "continuous", "horizon": "S"},
        "power_rule": rule, "decision": decision(rule), "band_days": rows,
        "band_day_counts": dict(Counter(r["excluded"] or "included" for r in rows)),
        "diagnostics": {k: v for k, v in sorted(diag.items())},
        "input_sha256": dict(sorted(hashes.items())),
        "input_set_sha256": hashlib.sha256(json.dumps(sorted(hashes.items())).encode()).hexdigest(),
        "implementation_choices": list(IMPLEMENTATION_CHOICES), "owner_questions": list(OWNER_QUESTIONS),
        "label": "PILOT_INCONCLUSIVE_BY_CONSTRUCTION (power rule only; no pilot number is the maker's P&L sign)",
    }
    return payload, time.monotonic() - started


def dry_run(args):
    diag = defaultdict(int)
    for key in ("missing_88a_days", "unsealed_segments_skipped", "ledger_missing_markets"):
        diag[key] = []
    families, sealed = Counter(), 0
    for day in UTC_DAYS:
        guard_date(day, "88a UTC day")
        folder = Path(args.maker_evidence_root) / day.isoformat()
        if not folder.is_dir():
            diag["missing_88a_days"].append(day.isoformat())
            continue
        for seg in sorted(folder.iterdir()):
            if not seg.is_dir() or not SEGMENT_RE.fullmatch(seg.name):
                continue
            if not any((seg / n).is_file() for n in ("manifest.json", "manifest.json.gz")):
                diag["unsealed_segments_skipped"].append(f"{day.isoformat()}/{seg.name}")
                continue
            sealed += 1
            for path in seg.iterdir():
                name = path.name
                family = ("book" if name.startswith("book-") else "reward" if name.startswith("reward-") else
                          "universe" if name.startswith("universe-") else "updates(never read)"
                          if name.startswith("updates-") else name.split(".")[0])
                families[family] += path.stat().st_size
    ledgers = {}
    for spec in all_specs():
        folder = Path(args.settlement_root) / spec.id
        path = next((folder / n for n in ("ledger.2026-09-26_2026-09-29.jsonl", "ledger.jsonl")
                     if (folder / n).is_file()), None)
        ledgers[spec.id] = {"path": str(path), "bytes": path.stat().st_size} if path else None
    read_bytes = sum(v for k, v in families.items() if k in ("books", "book", "trades", "reward", "universe"))
    return {"schema_version": SCHEMA + ".dry_run", "sealed_segments": sealed,
            "on_disk_bytes_by_family": dict(sorted(families.items())),
            "upper_bound_on_disk_bytes_read": read_bytes, "ledgers": ledgers,
            "diagnostics": {k: v for k, v in sorted(diag.items())},
            "note": "metadata only; no file content opened; book bytes are an upper bound (only pilot YES tokens are read)"}


def peak_memory_bytes():
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
            return int(counters.PeakWorkingSetSize)
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        return None


def check_output(path):
    path = Path(path).resolve()
    if any(part.lower() == "data" for part in path.parts):
        raise Refused(f"refusing to write under a data directory: {path}")
    if path.exists():
        raise Refused(f"output already exists: {path}")
    return path


def write_json(path, payload, envelope):
    body = json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":"))
    document = {**payload, "result_sha256": hashlib.sha256(body.encode()).hexdigest(), "envelope": envelope}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return document


def build_parser():
    parser = argparse.ArgumentParser(description="Desk-study power rule (N_req) on the 09-24..09-28 88a pilot.")
    parser.add_argument("--maker-evidence-root", required=True, help="88a root holding <UTC-day>/<HH>-<seg>/")
    parser.add_argument("--settlement-root", required=True, help="settlements root holding <market>/ledger*.jsonl")
    parser.add_argument("--output", required=True, help="new JSON path outside any data directory")
    parser.add_argument("--master-sha", default=None, help="origin/master sha recorded in the envelope")
    parser.add_argument("--dry-run", action="store_true", help="metadata only; open no file content")
    parser.add_argument("--date", action="append", default=[],
                        help="optional guard probe: any date given is checked and refused if after 2026-09-29")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for value in args.date:
            guard_date(value, "requested date")
        output = check_output(args.output)
        envelope = {"generated_at": datetime.now(timezone.utc).isoformat(), "master_sha": args.master_sha,
                    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        if args.dry_run:
            document = write_json(output, dry_run(args), envelope)
            print(json.dumps({k: document[k] for k in ("upper_bound_on_disk_bytes_read", "sealed_segments")}))
            return 0
        payload, elapsed = run(args)
        envelope.update(elapsed_seconds=round(elapsed, 1), peak_working_set_bytes=peak_memory_bytes())
        document = write_json(output, payload, envelope)
        rule = document["power_rule"]
        print(json.dumps({"n": rule["n"], "sigma_d": rule["sigma_d"], "c": rule["c"], "sigma_up": rule["sigma_up"],
                          "n_req": rule["n_req"], "branch": rule["branch"],
                          "decision": document["decision"]["action"], "result_sha256": document["result_sha256"]}))
        return 0
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
