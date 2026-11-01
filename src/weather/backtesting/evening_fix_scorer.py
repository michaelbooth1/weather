"""Scorer for the evening lock-in fix pre-registration (draft (a), 2026-10-13).

It scores the rows written by ``weather.backtesting.lockin_anchor_replay`` (both
arms per snapshot: NEW = v0.5.12 as served, OLD = the pre-restoration legacy WU
anchor) against the settlement ledger, exactly as
``docs/research/evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md``
specifies: 17:00-23:59 local, US11, fixed-market date-clustered bootstrap,
one-sided alpha 0.025, PASS / NOT_CONFIRMED / HARM / VOID.

Read gate (checked before any input is opened; a refusal writes nothing):
- ``--prereg`` names the pre-registration text. Its raw SHA-256 must appear in
  ``--decision-log`` (the signature row). An unsigned draft is refused at any date.
- Before ``READ_DATE`` (2026-10-29, Toronto) the scorer refuses to compute or emit
  anything unless ``--read-token`` names a JSON token that:
    * names this pre-registration (``prereg`` = ``PREREG_ID``) and its signed hash
      (``prereg_sha256``);
    * carries a non-empty ``reason`` and ``issued_by``;
    * quotes a ``decision_log_row`` that is one whole line of the decision log,
      verbatim, and is not the signature row itself, so an early read is
      recorded by the owner before it happens (a fragment of a row is refused).
  A token given on or after the read date is validated the same way and recorded.
- Rows on the reserved/embargo dates 2026-09-30..2026-10-15 refuse the whole run.
  Rows outside the scoring window are skipped and counted.

Window (master ruling 2026-10-31): local target dates 2026-10-16..10-27, plus the
outcome-blind extension 10-28 only. A row on 10-29 or later refuses the run; a window
that would need 10-29 STOPS (exit 4). The window is decided from metadata only and
passed to ``evaluate``; it never depends on labels.

``--no-market`` is Stage 1 of Clarification 1
(``docs/research/evening-lockin-fix-scoring-clarification-1-2026-10-31.md``): every
band ``market_yes`` must be null, no market Brier is computed, and conditions 1-2 plus
HARM / VOID / SAFETY give ``CONDITIONS 1-2 MET, condition 3 pending`` when they hold.
``stage2_outcome`` applies condition 3 later, from MG-1's look receipt.
``--no-market`` is required in every mode (master 2026-10-31, F2). Local mode
(one ``--replay PATH``) runs the per-date B2 reproduction check before it opens any
label and stops with exit 4 when it fails.

Transfer mode (``--replay COMMIT=PATH`` repeated, ``--ledger-rows``, requires
``--no-market``) opens the host transfer in stages through
``weather.backtesting.evening_fix_transfer``: forecast fields only, B2 reproduction
stop, ledger hash chain, metadata-only window check, and only then labels.

Exit codes: 0 scored (the JSON states the outcome), 2 refused, 4 stopped before labels
(the JSON carries the per-date match table or the window stop).

CLI:
  python -m weather.backtesting.evening_fix_scorer --replay <rows.jsonl>
      --prereg <prereg.md> --out <result.json>
      [--decision-log docs/operations/DECISION_LOG.md] [--read-token <token.json>]
      [--ledger-root data/settlements] --no-market
  python -m weather.backtesting.evening_fix_scorer --no-market
      --replay <commit>=<replay.jsonl> [--replay <commit>=<replay.jsonl> ...]
      --ledger-rows <ledger_rows.jsonl> [--served-commits <served.json>]
      --prereg <prereg.md> --out <result.json> [--read-token <token.json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from weather.backtesting import evening_fix_transfer as transfer
from weather.backtesting.lockin_anchor_replay import EMBARGO_END, EMBARGO_START, in_embargo
from weather.backtesting.settlement_ledger import ledger_label_for_slug, resolve_outcome
from weather.market.market_registry import REGISTRY
from weather.model.model_constants import TORONTO_TZ
from weather.paths import data_path, docs_path

PREREG_ID = "evening-lockin-fix-scoring"
WINDOW_START = date(2026, 10, 16)
BASE_WINDOW_END = date(2026, 10, 27)
# Master 2026-10-31: the extension may add 10-28 only. 10-29 is another read's day 0; a window that would
# need it STOPS before any label is read.
EXTENSION_DATES = transfer.EXTENSION_DATES
FORBIDDEN_FROM = transfer.FORBIDDEN_FROM
READ_DATE = date(2026, 10, 29)
STAGE1_MET = "CONDITIONS 1-2 MET, condition 3 pending"
DENVER = "denver"
STOP_EXIT = 4
MIN_QUALIFYING_DATES = 9
MIN_US_MARKETS_PER_DATE = 9
PRIMARY_HOURS = range(17, 24)
H2_HOURS = range(0, 17)
BESIDE_BLOCKS = (("00-12", range(0, 13)), ("13-16", range(13, 17)), ("all", range(0, 24)))
DRAWS = 2000
SEED = 20261016
LOWER_PCT, UPPER_PCT = 2.5, 97.5
SIGN_MIN = 8
MATERIALITY_SHARE = 0.05
H2_MARGIN = 0.0005
SAFETY_ZERO = 1e-6
SAFETY_OLD_MIN = 1e-3
COVERAGE_MIN = 0.90
REPRODUCTION_L1 = 1e-9
REPRODUCTION_SHARE = 0.99
US_MARKETS = tuple(sorted(market for market in REGISTRY if market != "toronto"))
REFUSED_EXIT = 2


class ScoreRefused(ValueError):
    """A request outside the read gate or the window contract."""


class WindowStop(RuntimeError):
    """The outcome-blind window would need 2026-10-29: stop before any label is read."""

    def __init__(self, qualifying):
        super().__init__(f"the window would need {FORBIDDEN_FROM}; stopping before any label is read")
        self.qualifying = qualifying


# --- read gate -----------------------------------------------------------------

def _today(today=None):
    return today if today is not None else datetime.now(TORONTO_TZ).date()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_signed_prereg(prereg_path, decision_log_path):
    prereg = Path(prereg_path)
    if not prereg.is_file():
        raise ScoreRefused(f"refused: pre-registration {prereg} does not exist")
    log = Path(decision_log_path)
    if not log.is_file():
        raise ScoreRefused(f"refused: decision log {log} does not exist")
    digest = file_sha256(prereg)
    log_text = log.read_text(encoding="utf-8")
    if digest not in log_text:
        raise ScoreRefused(
            f"refused: pre-registration SHA-256 {digest} is not recorded in {log.name}; "
            "an unsigned draft is never scored"
        )
    return digest, log_text


def check_read_token(token_path, prereg_digest, log_text):
    path = Path(token_path)
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScoreRefused(f"refused: read token {path} is unreadable: {exc}") from exc
    if not isinstance(token, dict):
        raise ScoreRefused("refused: read token must be a JSON object")
    if token.get("prereg") != PREREG_ID:
        raise ScoreRefused(f"refused: read token names {token.get('prereg')!r}, not {PREREG_ID!r}")
    if token.get("prereg_sha256") != prereg_digest:
        raise ScoreRefused("refused: read token is bound to a different pre-registration hash")
    for field in ("reason", "issued_by", "decision_log_row"):
        if not str(token.get(field) or "").strip():
            raise ScoreRefused(f"refused: read token has no {field}")
    row = str(token["decision_log_row"]).strip()
    lines = [line.strip() for line in log_text.splitlines()]
    if row not in lines:
        raise ScoreRefused(
            "refused: the read token's decision_log_row is not recorded in the decision log "
            "as a whole row"
        )
    if prereg_digest in row and row == next(line for line in lines if prereg_digest in line):
        raise ScoreRefused(
            "refused: the read token quotes the signature row; an early read needs its own owner row"
        )
    return {
        "token_sha256": file_sha256(path),
        "reason": token["reason"],
        "issued_by": token["issued_by"],
        "decision_log_row": token["decision_log_row"],
    }


def check_read_gate(prereg_path, decision_log_path, read_token=None, today=None):
    """Raise unless scoring is allowed now. Runs before any input is opened."""
    digest, log_text = check_signed_prereg(prereg_path, decision_log_path)
    token = check_read_token(read_token, digest, log_text) if read_token else None
    now = _today(today)
    if now < READ_DATE and token is None:
        raise ScoreRefused(
            f"refused: the first read is {READ_DATE} (today is {now}); an earlier read needs "
            "--read-token with a recorded owner decision"
        )
    return {"prereg_sha256": digest, "today": now.isoformat(), "early_read": now < READ_DATE,
            "read_token": token}


def check_out_path(out_path):
    out = Path(out_path).resolve()
    data_root = Path(data_path()).resolve()
    if out == data_root or data_root in out.parents:
        raise ScoreRefused(f"refused: --out {out} is inside the runtime data tree {data_root}")
    if out.exists():
        raise ScoreRefused(f"refused: --out {out} already exists; this command never overwrites")
    return out


# --- scoring -------------------------------------------------------------------

def window_bounds():
    return WINDOW_START, EXTENSION_DATES[-1]


def snapshot_brier(probabilities, outcomes):
    pairs = [(p, o) for p, o in zip(probabilities, outcomes) if p is not None and o is not None]
    if not pairs:
        return None
    return sum((float(p) - float(o)) ** 2 for p, o in pairs) / len(pairs)


def band_outcomes(bands, settlement_bucket):
    outcomes = []
    for band in bands:
        value = band.get("value")
        value_hi = band.get("value_hi")
        outcome = resolve_outcome(
            band.get("kind"),
            None if value is None else round(value),
            settlement_bucket,
            value_hi=None if value_hi is None else round(value_hi),
        )
        outcomes.append(None if outcome is None else int(outcome))
    return outcomes


def _truthy(value):
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def load_labels(slugs, ledger_root=None):
    labels = {}
    for slug in sorted(slugs):
        label = ledger_label_for_slug(slug, ledger_root=ledger_root)
        labels[slug] = label
    return labels


def _arms(row):
    """Both replay arms present (capture and replay metadata only)."""
    return bool(row.get("bands")) and row.get("new_band_p") is not None and row.get("old_band_p") is not None


def check_no_market(rows):
    """Under --no-market every band's market_yes must be null; a price refuses the run."""
    for row in rows:
        for band in row.get("bands") or []:
            if band.get("market_yes") is not None:
                raise ScoreRefused(
                    f"refused: --no-market but replay row {row.get('snapshot_id')} carries a market price"
                )


def score_rows(rows, labels, use_market=True):
    """Per-snapshot Brier rows (NEW, OLD, v3 when present, market) with outcomes.

    With ``use_market=False`` every band price must be null and no market Brier is computed.
    """
    if not use_market:
        check_no_market(rows)
    scored = []
    for row in rows:
        label = labels.get(row.get("event_slug")) or {}
        bucket = label.get("settlement_bucket")
        bands = row.get("bands")
        if bucket in (None, "") or not _arms(row):
            scored.append({**_key(row), "scored": False, "arms": _arms(row)})
            continue
        outcomes = band_outcomes(bands, int(float(bucket)))
        market = [band.get("market_yes") for band in bands] if use_market else None
        winners = [i for i, outcome in enumerate(outcomes) if outcome == 1]
        scored.append({
            **_key(row),
            "scored": True,
            "arms": True,
            "new": snapshot_brier(row["new_band_p"], outcomes),
            "old": snapshot_brier(row["old_band_p"], outcomes),
            "v3": snapshot_brier(row["v3_band_p"], outcomes) if row.get("v3_band_p") else None,
            "market": snapshot_brier(market, outcomes)
            if market is not None and all(m is not None for m in market) else None,
            "new_winner_p": min((row["new_band_p"][i] for i in winners), default=None),
            "old_winner_p": min((row["old_band_p"][i] for i in winners), default=None),
            "observed_anchor": (row.get("lockin_anchor") or {}).get("source")
            == "observed_station_rows",
        })
    return scored


def _key(row):
    return {"market_id": row.get("market_id"), "target_date": row.get("target_date"),
            "hour": row.get("hour"), "event_slug": row.get("event_slug")}


def metadata_cells(rows, countability, hours=PRIMARY_HOURS):
    """Outcome-blind countability per market-day: promotion-countable and both arms on >= 90% of snapshots.

    Reads only ``promotion_countable`` and replay arm presence, never a settlement or a score.
    """
    totals, arms, slugs = defaultdict(int), defaultdict(int), {}
    for row in rows:
        if row.get("hour") is None or row["hour"] not in hours:
            continue
        key = (row["market_id"], row["target_date"])
        totals[key] += 1
        arms[key] += bool(row.get("arms", _arms(row)))
        slugs[key] = row.get("event_slug")
    cells = {}
    for key, total in totals.items():
        coverage = arms[key] / total if total else 0.0
        meta = countability.get(slugs.get(key)) or {}
        cells[key] = {"coverage": coverage,
                      "countable": arms[key] > 0 and coverage >= COVERAGE_MIN
                      and _truthy(meta.get("promotion_countable"))}
    return cells


def build_cells(scored, labels, hours, value):
    """Market-day cells: equal snapshot weights within the cell, for ``value(row)``."""
    groups = defaultdict(list)
    for row in scored:
        if row["hour"] is None or row["hour"] not in hours:
            continue
        if row["scored"]:
            number = value(row)
            if number is not None:
                groups[(row["market_id"], row["target_date"])].append(number)
    cells = {}
    for key, meta in metadata_cells(scored, labels, hours).items():
        values = groups.get(key) or []
        cells[key] = {"mean": sum(values) / len(values) if values else None,
                      "coverage": meta["coverage"], "countable": bool(values) and meta["countable"]}
    return cells


def final_window(primary_cells):
    """Outcome-blind window: base dates plus 10-28 while fewer than 9 qualify.

    Returns (dates, qualifying, needs_forbidden): ``needs_forbidden`` is True when even 10-28
    leaves fewer than 9 qualifying dates, so the old rule would have needed 10-29 (a STOP).
    """
    def qualifying(dates):
        return _qualifying(primary_cells, dates)

    dates = [WINDOW_START + timedelta(days=i)
             for i in range((BASE_WINDOW_END - WINDOW_START).days + 1)]
    for extra in EXTENSION_DATES:
        if len(qualifying(dates)) >= MIN_QUALIFYING_DATES:
            break
        dates.append(extra)
    found = qualifying(dates)
    return dates, found, len(found) < MIN_QUALIFYING_DATES


def _qualifying(cells, dates):
    per_date = defaultdict(int)
    for (market, day), cell in cells.items():
        if market in US_MARKETS and cell["countable"]:
            per_date[day] += 1
    return [d for d in dates if per_date.get(d.isoformat(), 0) >= MIN_US_MARKETS_PER_DATE]


def check_window_before_labels(rows, countability):
    """Decide the window from metadata only; raise WindowStop if it would need 10-29."""
    dates, found, needs_forbidden = final_window(metadata_cells(rows, countability))
    if needs_forbidden:
        raise WindowStop([d.isoformat() for d in found])
    return [d.isoformat() for d in dates]


def _percentiles(draws):
    if not draws:
        return None, None
    return (float(np.percentile(draws, LOWER_PCT)), float(np.percentile(draws, UPPER_PCT)))


def fixed_market_interval(cells, draws=DRAWS, seed=SEED):
    """Markets fixed; dates resampled as clusters (multinomial)."""
    by_date = defaultdict(list)
    for (_, day), value in cells.items():
        by_date[day].append(value)
    dates = sorted(by_date)
    if not dates:
        return None, (None, None)
    estimate = float(np.mean([v for values in by_date.values() for v in values]))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        picks = rng.integers(0, len(dates), size=len(dates))
        values = [v for i in picks for v in by_date[dates[i]]]
        out.append(float(np.mean(values)))
    return estimate, _percentiles(out)


def crossed_interval(cells, draws=DRAWS, seed=SEED):
    """Dates and markets resampled independently (reported beside, no alpha)."""
    markets = sorted({m for m, _ in cells})
    dates = sorted({d for _, d in cells})
    if not cells:
        return None, (None, None)
    estimate = float(np.mean(list(cells.values())))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        m_pick = rng.integers(0, len(markets), size=len(markets))
        d_pick = rng.integers(0, len(dates), size=len(dates))
        values = [cells[(markets[m], dates[d])] for m in m_pick for d in d_pick
                  if (markets[m], dates[d]) in cells]
        if values:
            out.append(float(np.mean(values)))
    return estimate, _percentiles(out)


def per_market(cells):
    groups = defaultdict(list)
    for (market, _), value in cells.items():
        groups[market].append(value)
    return {market: float(np.mean(values)) for market, values in sorted(groups.items())}


def safety_count(scored, window_dates):
    """Market-days whose settled band got NEW < 1e-6 while OLD >= 1e-3 at 17-23."""
    days = {d.isoformat() for d in window_dates}
    hits = {"observed_anchor": set(), "no_observed_anchor": set()}
    for row in scored:
        if not row["scored"] or row["hour"] not in PRIMARY_HOURS or row["target_date"] not in days:
            continue
        new_p, old_p = row["new_winner_p"], row["old_winner_p"]
        if new_p is None or old_p is None:
            continue
        if new_p < SAFETY_ZERO and old_p >= SAFETY_OLD_MIN:
            kind = "observed_anchor" if row["observed_anchor"] else "no_observed_anchor"
            hits[kind].add(f"{row['market_id']}|{row['target_date']}")
    return {kind: sorted(values) for kind, values in hits.items()}


def reproduction_check(rows):
    values = [row.get("l1_new_vs_recorded") for row in rows
              if row.get("l1_new_vs_recorded") is not None]
    if not values:
        return {"rows": 0, "share_within": None, "pass": False}
    share = sum(1 for v in values if v <= REPRODUCTION_L1) / len(values)
    return {"rows": len(values), "share_within": share, "pass": share >= REPRODUCTION_SHARE}


def _select(cells, dates, markets):
    days = {d.isoformat() for d in dates}
    return {key: cell["mean"] for key, cell in cells.items()
            if cell["countable"] and key[1] in days and key[0] in markets}


def _delta(r):
    return None if r["new"] is None or r["old"] is None else r["new"] - r["old"]


def primary_block(primary, dates, markets):
    """Conditions 1-2 statistics on the given market set (fixed-market date bootstrap)."""
    cells = _select(primary, dates, markets)
    estimate, (lower, upper) = fixed_market_interval(cells)
    by_market = per_market(cells)
    return cells, {
        "estimate": estimate, "ci95": [lower, upper],
        "markets_negative": sum(1 for value in by_market.values() if value < 0),
        "markets_n": len(by_market), "per_market": by_market, "market_days": len(cells),
    }


def evaluate(rows, labels, *, use_market=True, window_dates=None):
    """Score the window. Under ``use_market=False`` this is Stage 1 of Clarification 1.

    Stage 1 decides conditions 1-2 plus HARM, VOID and SAFETY with no market price; when they hold the
    outcome is ``STAGE1_MET`` and ``stage2_outcome`` gives the final PASS / NOT_CONFIRMED later.

    ``window_dates`` (iso strings or dates) is the window decided from metadata before any label
    opened (``check_window_before_labels``); ``main`` always passes it (master 2026-10-31, F3), so the
    window can never depend on labels. Without it the window is decided from ``metadata_cells`` only,
    never from the label-dependent ``build_cells`` countable.
    """
    scored = score_rows(rows, labels, use_market=use_market)
    primary = build_cells(scored, labels, PRIMARY_HOURS, _delta)
    if window_dates is None:
        dates, _, needs_forbidden = final_window(metadata_cells(rows, labels))
    else:
        dates = [d if isinstance(d, date) else date.fromisoformat(str(d)) for d in window_dates]
        needs_forbidden = False   # already a WindowStop before labels
    qualifying = _qualifying(primary, dates)   # report only; decides nothing about the window
    us_cells, block = primary_block(primary, dates, US_MARKETS)
    result = {
        "mode": "market" if use_market else "no_market_stage1",
        "window_dates": [d.isoformat() for d in dates],
        "qualifying_dates": [d.isoformat() for d in qualifying],
        "countable_us_market_days": len(us_cells),
        "reproduction": reproduction_check(rows),
        "safety": safety_count(scored, dates),
    }
    void = []
    if needs_forbidden:
        void.append(f"fewer than {MIN_QUALIFYING_DATES} qualifying dates through "
                    f"{EXTENSION_DATES[-1]}; {FORBIDDEN_FROM} is never added (STOP)")
    if not result["reproduction"]["pass"]:
        void.append("replay does not reproduce the stored served vectors")
    estimate, (lower, upper) = block["estimate"], block["ci95"]
    gap = None
    if use_market:
        gap_cells = _select(build_cells(
            scored, labels, PRIMARY_HOURS,
            lambda r: None if r["old"] is None or r["market"] is None else r["old"] - r["market"],
        ), dates, US_MARKETS)
        gap = float(np.mean(list(gap_cells.values()))) if gap_cells else None
    material = None if gap is None or estimate is None else estimate <= -MATERIALITY_SHARE * gap
    crossed_est, crossed_ci = crossed_interval(us_cells)
    result["primary"] = {**block, "old_minus_market_gap": gap, "material": material}
    result["crossed"] = {"estimate": crossed_est, "ci95": list(crossed_ci)}
    # Denver stays in the signed primary; this sensitivity drops it and decides nothing.
    _, denver_out = primary_block(primary, dates, tuple(m for m in US_MARKETS if m != DENVER))
    result["denver_excluded_sensitivity"] = {
        **denver_out,
        "conditions_1_2": denver_out["ci95"][1] is not None and denver_out["ci95"][1] < 0
        and denver_out["markets_negative"] >= SIGN_MIN,
        "decides_nothing": True,
    }
    beside = {}
    for label, hours in BESIDE_BLOCKS:
        cells = _select(build_cells(scored, labels, hours, _delta), dates, US_MARKETS)
        est, ci = fixed_market_interval(cells)
        beside[label] = {"estimate": est, "ci95": list(ci), "market_days": len(cells)}
    toronto = _select(primary, dates, ("toronto",))
    beside["toronto_17_23"] = {"estimate": float(np.mean(list(toronto.values())))
                               if toronto else None, "market_days": len(toronto)}
    result["beside"] = beside
    conditions_1_2 = upper is not None and upper < 0 and block["markets_negative"] >= SIGN_MIN
    if void:
        outcome = "VOID"
    elif estimate is None:
        outcome = "VOID"
        void.append("no countable cells")
    elif lower is not None and lower > 0:
        outcome = "HARM"
    elif conditions_1_2 and not use_market:
        outcome = STAGE1_MET
    elif conditions_1_2 and material:
        outcome = "PASS"
    else:
        outcome = "NOT_CONFIRMED"
    result["conditions_1_2"] = conditions_1_2
    result["void_reasons"] = void
    result["outcome"] = outcome
    result["final"] = outcome != STAGE1_MET
    result["safety_fail"] = bool(result["safety"]["observed_anchor"])
    result["crossed_disagrees"] = (crossed_est is not None and estimate is not None
                                   and (crossed_est < 0) != (estimate < 0))
    h2 = {"tested": False}
    if outcome in ("PASS", STAGE1_MET) and any(row.get("v3") is not None for row in scored if row["scored"]):
        cells = _select(build_cells(scored, labels, H2_HOURS,
                                    lambda r: None if r["new"] is None or r["v3"] is None
                                    else r["new"] - r["v3"]), dates, US_MARKETS)
        est, (lo, up) = fixed_market_interval(cells)
        h2 = {"tested": True, "estimate": est, "ci95": [lo, up], "margin": H2_MARGIN,
              "non_inferior": up is not None and up < H2_MARGIN,
              "conditional_on_stage2": outcome == STAGE1_MET}
    result["h2_pre_lockin_floor_non_inferiority_00_16"] = h2
    return result


def stage2_outcome(stage1, old_minus_market_gap):
    """Stage 2 of Clarification 1: condition 3 from the OLD-minus-market gap of MG-1's look receipt.

    Only a ``STAGE1_MET`` result moves; HARM, VOID and NOT_CONFIRMED from Stage 1 are already final.
    """
    if stage1.get("outcome") != STAGE1_MET:
        return {"outcome": stage1.get("outcome"), "final": True, "stage2_applied": False}
    if old_minus_market_gap is None:
        raise ScoreRefused("refused: stage 2 needs the OLD-minus-market gap from MG-1's look receipt")
    gap = float(old_minus_market_gap)
    estimate = stage1["primary"]["estimate"]
    material = estimate <= -MATERIALITY_SHARE * gap
    return {"outcome": "PASS" if material else "NOT_CONFIRMED", "final": True, "stage2_applied": True,
            "old_minus_market_gap": gap, "estimate": estimate, "material": material,
            "threshold": -MATERIALITY_SHARE * gap}


def load_replay_rows(path):
    """Replay rows inside the window. A reserved/embargo row, or one on 10-29 or later, refuses the run."""
    start, end = window_bounds()
    rows, skipped = [], 0
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            target = date.fromisoformat(row["target_date"]) if row.get("target_date") else None
            if in_embargo(target):
                raise ScoreRefused(
                    f"refused: replay row {row.get('snapshot_id')} targets {target}, inside the "
                    f"reserved/embargo window {EMBARGO_START}..{EMBARGO_END}"
                )
            if target is not None and target >= FORBIDDEN_FROM:
                raise ScoreRefused(
                    f"refused: replay row {row.get('snapshot_id')} targets {target}; {FORBIDDEN_FROM} "
                    "and later are another read's day 0"
                )
            if target is None or target < start or target > end:
                skipped += 1
                continue
            rows.append(row)
    return rows, skipped


def _parse_replays(values):
    """``--replay PATH`` (single, local mode) or repeated ``--replay COMMIT=PATH`` (transfer mode)."""
    pairs = {}
    for value in values:
        commit, sep, path = value.partition("=")
        if not sep:
            return None
        if commit in pairs:
            raise ScoreRefused(f"refused: --replay names commit {commit} twice")
        pairs[commit] = path
    return pairs


def build_parser():
    parser = argparse.ArgumentParser(
        description="Score the evening lock-in fix pre-registration (one look; read-gated).",
    )
    parser.add_argument("--replay", required=True, action="append",
                        help="lockin_anchor_replay JSONL output. Transfer mode: repeat as COMMIT=PATH, "
                             "one per replay commit.")
    parser.add_argument("--prereg", required=True, help="The signed pre-registration text.")
    parser.add_argument("--decision-log", default=str(docs_path("operations", "DECISION_LOG.md")))
    parser.add_argument("--read-token", default=None,
                        help="JSON read token; required before the read date.")
    parser.add_argument("--ledger-root", default=None)
    parser.add_argument("--ledger-rows", default=None,
                        help="Transfer mode: the whole transferred settlement-ledger rows (JSONL).")
    parser.add_argument("--served-commits", default=None,
                        help="Transfer mode: JSON {target_date: [served commits]} for the stop table.")
    parser.add_argument("--no-market", action="store_true",
                        help="Do not use captured market prices; every band market_yes must be null "
                             "(Clarification 1 Stage 1).")
    parser.add_argument("--out", required=True, help="New JSON file outside data/.")
    return parser


def _write(out, payload):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _transfer_inputs(args, replays):
    """Staged transfer load. Returns (rows, labels, window, extra) or raises WindowStop / ReproductionStop."""
    if not args.no_market:
        raise ScoreRefused("refused: transfer mode requires --no-market")
    if not args.ledger_rows:
        raise ScoreRefused("refused: transfer mode requires --ledger-rows")
    served = None
    if args.served_commits:
        served = json.loads(Path(args.served_commits).read_text(encoding="utf-8"))
    rows_by_commit = transfer.load_replays(replays)          # pass 1: forecast fields only
    receipt = transfer.select_reproducing_commit(rows_by_commit, served)   # B2 stop rule
    rows = rows_by_commit[receipt.commit]
    ledger = transfer.TransferredLedger(args.ledger_rows, {r["event_slug"] for r in rows if r.get("event_slug")})
    window = check_window_before_labels(rows, ledger.countability())   # metadata only
    labels = ledger.labels(receipt)
    return rows, labels, window, {"replay_commit": receipt.commit, "reproduction_table": receipt.table,
                                  "ledger_records_verified": ledger.verification}


def _local_inputs(args):
    """Local mode, same order as transfer (master 2026-10-31, F2): --no-market and no price, then the
    per-date L1 reproduction check, and only then labels. Returns (rows, skipped, labels, window, extra)
    or raises ReproductionStop / WindowStop; no label is opened when reproduction fails.
    """
    if not args.no_market:
        raise ScoreRefused("refused: local mode requires --no-market")
    rows, skipped = load_replay_rows(args.replay[0])
    check_no_market(rows)
    receipt = transfer.select_reproducing_commit({"local": rows})   # B2 stop rule, per-date table
    labels = load_labels({row.get("event_slug") for row in rows if row.get("event_slug")},
                         ledger_root=args.ledger_root)
    # Local labels carry the countability metadata; the window still never uses settlement buckets.
    window = check_window_before_labels(rows, labels)
    return rows, skipped, labels, window, {"reproduction_table": receipt.table}


def main(argv=None, today=None):
    args = build_parser().parse_args(argv)
    extra = {}
    try:
        gate = check_read_gate(args.prereg, args.decision_log, args.read_token, today=today)
        out = check_out_path(args.out)
        replays = _parse_replays(args.replay)
        try:
            if replays is None:
                if len(args.replay) != 1:
                    raise ScoreRefused("refused: give one --replay PATH, or COMMIT=PATH for every replay")
                rows, skipped, labels, window, extra = _local_inputs(args)
            else:
                rows, labels, window, extra = _transfer_inputs(args, replays)
                skipped = 0
        except transfer.ReproductionStop as stop:
            _write(out, {"prereg_id": PREREG_ID, "gate": gate, "stop": "B2_REPRODUCTION",
                         "message": str(stop), "reproduction_table": stop.table})
            print(str(stop), file=sys.stderr)
            return STOP_EXIT
        except WindowStop as stop:
            _write(out, {"prereg_id": PREREG_ID, "gate": gate, "stop": "WINDOW_NEEDS_FORBIDDEN_DATE",
                         "message": str(stop), "qualifying_dates": stop.qualifying})
            print(str(stop), file=sys.stderr)
            return STOP_EXIT
        result = evaluate(rows, labels, use_market=not args.no_market, window_dates=window)
    except (ScoreRefused, transfer.TransferRefused) as exc:
        print(str(exc), file=sys.stderr)
        return REFUSED_EXIT
    payload = {"prereg_id": PREREG_ID, "gate": gate, "replay_rows": len(rows),
               "rows_outside_window": skipped, "seed": SEED, "draws": DRAWS, **extra, **result}
    _write(out, payload)
    print(json.dumps({"outcome": payload["outcome"], "out": str(out),
                      "primary": payload["primary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
