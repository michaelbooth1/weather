"""Staged loader for the evening-fix read on transferred host outputs (no market prices).

The host replays the window and transfers two things to the workstation: the
``lockin_anchor_replay --no-market`` JSONL (one file per replay commit) and the
whole settlement-ledger rows of the window's slugs. This module opens them in
stages, so that no label is reachable before the outcome-blind checks pass:

1. **Pass 1, forecast fields only.** Each replay row is projected onto
   ``FORECAST_FIELDS`` (band descriptors keep only kind, value, value_hi and
   label), and every price-like key is dropped before anything is computed. A
   row whose band still carries a non-null ``market_yes`` refuses the load.
2. **Window.** Local target dates 2026-10-16..2026-10-27, plus the outcome-blind
   extension date 2026-10-28. Any row or ledger row on 2026-10-29 or later
   refuses: 10-29 is another read's day 0, and any label-proxy read for it voids
   that read. Embargo and earlier dates refuse too.
3. **Reproduction (B2 stop rule).** Per replay commit and per date, the share of
   rows whose NEW arm reproduces the recorded served vector (L1 <= 1e-9). If no
   single commit reaches 99% of rows, the load STOPS before any label is opened
   and the per-date match table is the output.
4. **Ledger.** The hash chain of every slug's whole rows is verified first. The
   countability projection (``promotion_countable``) is available before labels.
   The label projection (``settlement_bucket``) opens only with the receipt that
   step 3 returns.

All functions are pure over the given paths; nothing here writes.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from weather.backtesting.settlement_ledger import current_ledger_label, verify_ledger_history

WINDOW_START = date(2026, 10, 16)
BASE_WINDOW_END = date(2026, 10, 27)
EXTENSION_DATES = (date(2026, 10, 28),)
FORBIDDEN_FROM = date(2026, 10, 29)   # another read's D0: never loaded, never labelled
REPRODUCTION_L1 = 1e-9
REPRODUCTION_SHARE = 0.99

FORECAST_FIELDS = (
    "snapshot_id", "market_id", "event_slug", "target_date", "built_at", "hour", "reconstructed",
    "model_version", "lockin_anchor", "old_lockin_strength", "new_lockin_strength",
    "old_mass_above_anchor", "new_mass_above_anchor", "old_mass_below_anchor", "new_mass_below_anchor",
    "l1_new_vs_old", "l1_old_vs_recorded", "l1_new_vs_recorded", "old_final", "new_final",
    "bands", "old_band_p", "new_band_p", "v3_final", "v3_band_p",
)
BAND_FIELDS = ("label", "kind", "value", "value_hi")
COUNTABILITY_FIELDS = ("promotion_countable", "promotion_countable_reason")
LABEL_FIELDS = ("settlement_bucket",)
PRICE_KEY = re.compile(
    r"(?:^|_)(?:market_yes|market_no|yes_price|no_price|price|prices|bid|bids|ask|asks|mid|quote|quotes|"
    r"book|books|spread|last_trade)(?:_|$)",
    re.IGNORECASE,
)


class TransferRefused(ValueError):
    """The transferred inputs break the window, projection or integrity contract."""


class ReproductionStop(RuntimeError):
    """No single replay commit reproduces the served vectors: stop before any label."""

    def __init__(self, table):
        super().__init__("no single replay commit reproduces >= 99% of rows; stopping before labels")
        self.table = table


def is_price_key(key):
    return bool(PRICE_KEY.search(str(key)))


def drop_price_keys(value):
    """Recursively remove every price-like key (dicts inside lists included)."""
    if isinstance(value, dict):
        return {k: drop_price_keys(v) for k, v in value.items() if not is_price_key(k)}
    if isinstance(value, list):
        return [drop_price_keys(v) for v in value]
    return value


def window_dates(extended=True):
    days = [date.fromordinal(d) for d in range(WINDOW_START.toordinal(), BASE_WINDOW_END.toordinal() + 1)]
    return days + list(EXTENSION_DATES) if extended else days


def check_target(target, what):
    day = date.fromisoformat(str(target)) if target else None
    if day is None:
        raise TransferRefused(f"refused: {what} has no target date")
    if day >= FORBIDDEN_FROM:
        raise TransferRefused(
            f"refused: {what} targets {day}; {FORBIDDEN_FROM} and later are another read's day 0 and "
            "must never be transferred or labelled"
        )
    if not WINDOW_START <= day <= EXTENSION_DATES[-1]:
        raise TransferRefused(f"refused: {what} targets {day}, outside {WINDOW_START}..{EXTENSION_DATES[-1]}")
    return day


def project_replay_row(row):
    """Pass 1: forecast fields only; bands keep their outcome-free, price-free descriptor."""
    for band in row.get("bands") or []:
        if band.get("market_yes") is not None:
            raise TransferRefused(
                f"refused: replay row {row.get('snapshot_id')} carries a market price; "
                "the replay must run with --no-market"
            )
    projected = {key: row.get(key) for key in FORECAST_FIELDS if key in row}
    if projected.get("bands") is not None:
        projected["bands"] = [{key: band.get(key) for key in BAND_FIELDS} for band in projected["bands"]]
    return drop_price_keys(projected)


def load_replay(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            check_target(row.get("target_date"), f"replay row {number} ({row.get('snapshot_id')})")
            rows.append(project_replay_row(row))
    return rows


def load_replays(paths_by_commit):
    if not paths_by_commit:
        raise TransferRefused("refused: no replay file given")
    return {commit: load_replay(path) for commit, path in paths_by_commit.items()}


def reproduction_table(rows_by_commit, served_commits=None):
    """Per date x commit: rows with a recorded vector, rows within L1 1e-9, share; plus served versions.

    Receipt only (master 2026-10-31): each date and each commit summary also shows ``all_rows``,
    ``rows_with_vector`` and ``vector_coverage`` (= rows_with_vector / all_rows), so a pass on a thin
    vector subset is visible. The pass rule is unchanged.
    """
    dates = sorted({row["target_date"] for rows in rows_by_commit.values() for row in rows})
    table = {"threshold_l1": REPRODUCTION_L1, "threshold_share": REPRODUCTION_SHARE, "commits": {}, "dates": {}}
    for commit, rows in rows_by_commit.items():
        per_date = defaultdict(lambda: [0, 0])
        all_per_date = defaultdict(int)
        for row in rows:
            all_per_date[row["target_date"]] += 1
            value = row.get("l1_new_vs_recorded")
            if value is None:
                continue
            per_date[row["target_date"]][0] += 1
            per_date[row["target_date"]][1] += value <= REPRODUCTION_L1
        total = sum(n for n, _ in per_date.values())
        within = sum(k for _, k in per_date.values())
        all_rows = sum(all_per_date.values())
        table["commits"][commit] = {
            "rows": total, "within": within, "share": within / total if total else None,
            "pass": bool(total) and within / total >= REPRODUCTION_SHARE,
            "all_rows": all_rows, "rows_with_vector": total,
            "vector_coverage": total / all_rows if all_rows else None,
            "per_date": {d: {"rows": per_date[d][0], "within": per_date[d][1],
                             "share": per_date[d][1] / per_date[d][0] if per_date[d][0] else None,
                             "all_rows": all_per_date[d], "rows_with_vector": per_date[d][0],
                             "vector_coverage": per_date[d][0] / all_per_date[d] if all_per_date[d] else None}
                         for d in dates},
        }
    for d in dates:
        versions = Counter(str(row.get("model_version")) for rows in rows_by_commit.values()
                           for row in rows if row["target_date"] == d)
        table["dates"][d] = {"served_model_versions": dict(sorted(versions.items())),
                             "served_commits": list((served_commits or {}).get(d, []))}
    return table


def select_reproducing_commit(rows_by_commit, served_commits=None):
    """The B2 stop rule: the commit with the highest overall share >= 99%, or ReproductionStop."""
    table = reproduction_table(rows_by_commit, served_commits)
    passing = [(info["share"], -order, commit) for order, (commit, info) in enumerate(table["commits"].items())
               if info["pass"]]
    if not passing:
        raise ReproductionStop(table)
    commit = max(passing)[2]
    return ReproductionReceipt(commit, table)


class ReproductionReceipt:
    """Proof that step 3 passed; the only key that opens the label projection."""

    def __init__(self, commit, table):
        self.commit, self.table = commit, table


class TransferredLedger:
    """Whole transferred ledger rows: chain verified first, countability before labels, labels last."""

    def __init__(self, path, slugs):
        self.slugs = set(slugs)
        rows = []
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        by_slug = defaultdict(list)
        for row in rows:
            slug = row.get("event_slug")
            check_target(row.get("target_date"), f"ledger row for {slug}")
            if slug not in self.slugs:
                raise TransferRefused(f"refused: ledger row for {slug}, which has no replay row")
            by_slug[slug].append(row)
        self.verification = {}
        for slug, history in sorted(by_slug.items()):
            result = verify_ledger_history(history, event_slug=slug)
            if result["status"] != "PASS":
                codes = ",".join(item["code"] for item in result["blockers"])
                raise TransferRefused(f"refused: ledger hash chain fails for {slug}: {codes}")
            self.verification[slug] = result["record_count"]
        # Price keys are dropped right after verification, before any field is read.
        self._current = {slug: drop_price_keys(current_ledger_label(history, slug))
                         for slug, history in by_slug.items()}

    def countability(self):
        return {slug: {key: label.get(key) for key in COUNTABILITY_FIELDS}
                for slug, label in sorted(self._current.items())}

    def labels(self, receipt):
        if not isinstance(receipt, ReproductionReceipt):
            raise TransferRefused("refused: labels open only after the reproduction check passes")
        return {slug: {key: label.get(key) for key in (*LABEL_FIELDS, *COUNTABILITY_FIELDS)}
                for slug, label in sorted(self._current.items())}
