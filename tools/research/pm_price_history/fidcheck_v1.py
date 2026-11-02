"""Step 2 fidelity check: sampled /prices-history points vs our captured mid and last trade.

Prices only, no labels: compares each captured per-token book snapshot (88a maker evidence,
``book-<token>.jsonl.gz``: bids, asks, last_trade_price, timestamp) with the fetched history point
nearest before and nearest after the snapshot time. Prints and writes only distance summaries
(absolute differences and exact-match shares), never a price level, outcome or label.

Guards: tokens are taken only from a sealed fetch run's ``tokens.jsonl`` (admitted events), each
event date is re-checked with ``guards.require_admitted``, and capture partitions dated after
``LAST_PARTITION`` = 2026-09-27 are refused, because a UTC partition holds horizons 0-2 and so
events up to two days later (09-27 + 2 = 09-29, the last admitted date). The capture root is a
parameter.

    python -m tools.research.pm_price_history.fidcheck_v1 --run C:\\t\\l52\\history\\run-... \\
        --evidence-root C:\\archive\\inputs\\export2-batch1-c3\\data\\maker_evidence --out C:\\t\\l52\\fidcheck
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

from tools.research.pm_price_history import guards

LAST_PARTITION = date(2026, 9, 27)
DEFAULT_PARTITIONS = ("2026-09-25", "2026-09-26", "2026-09-27")
MAX_MATCH_GAP_S = 120
EXACT_TOL = 0.0005
DISPLAY_SPREAD_LIMIT = 0.10  # venue display rule as commonly documented (UNVERIFIED-EXTERNAL)


def require_partition(day: str) -> str:
    d = date.fromisoformat(day)
    if d > LAST_PARTITION:
        raise guards.GuardRefusal(f"capture partition refused (after {LAST_PARTITION}): {day}")
    return day


def load_tokens(run_dir: Path) -> dict:
    """token -> (event_date, raw path) for tokens saved by a fetch run; every date re-guarded."""
    out = {}
    with open(Path(run_dir) / "tokens.jsonl", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            guards.require_admitted(row["event_date"])
            out[str(row["yes_token"])] = (row["event_date"], row["path"])
    return out


def load_history(path: Path) -> tuple[list, list]:
    body = json.loads(gzip.decompress(Path(path).read_bytes()))
    points = sorted((int(p["t"]), float(p["p"])) for p in body.get("history") or [] if "t" in p and "p" in p)
    return [t for t, _ in points], [p for _, p in points]


def book_view(book: dict) -> dict | None:
    """Best bid/ask, mid, spread, last trade and the venue display price from one book snapshot."""
    try:
        bids = [float(level["price"]) for level in book.get("bids") or []]
        asks = [float(level["price"]) for level in book.get("asks") or []]
        ts = int(book["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    ts = ts // 1000 if ts > 10 ** 11 else ts
    ltp = book.get("last_trade_price")
    ltp = float(ltp) if ltp not in (None, "") else None
    if not bids or not asks:
        return {"ts": ts, "mid": None, "spread": None, "ltp": ltp, "display": ltp}
    bid, ask = max(bids), min(asks)
    mid, spread = (bid + ask) / 2, ask - bid
    display = mid if spread <= DISPLAY_SPREAD_LIMIT or ltp is None else ltp
    return {"ts": ts, "mid": mid, "spread": spread, "ltp": ltp, "display": display}


def nearest(stamps: list, prices: list, ts: int, side: str):
    if side == "before":
        i = bisect.bisect_right(stamps, ts) - 1
        ok = i >= 0 and ts - stamps[i] <= MAX_MATCH_GAP_S
    else:
        i = bisect.bisect_left(stamps, ts)
        ok = i < len(stamps) and stamps[i] - ts <= MAX_MATCH_GAP_S
    return prices[i] if ok else None


def summarize(diffs: list) -> dict:
    if not diffs:
        return {"n": 0}
    absd = [abs(d) for d in diffs]
    return {"n": len(absd), "median_abs": round(statistics.median(absd), 4), "mean_abs": round(statistics.fmean(absd), 4),
            "p90_abs": round(sorted(absd)[int(0.9 * (len(absd) - 1))], 4),
            "share_exact": round(sum(a <= EXACT_TOL for a in absd) / len(absd), 3),
            "share_within_0_01": round(sum(a <= 0.01 + 1e-9 for a in absd) / len(absd), 3)}


def compare(run_dir: Path, evidence_root: Path, partitions=DEFAULT_PARTITIONS) -> dict:
    tokens = load_tokens(run_dir)
    diffs = {f"{ref}_{side}": [] for ref in ("mid", "ltp", "display") for side in ("before", "after")}
    wide = {"mid_before": [], "ltp_before": []}
    matched_tokens, snapshots, unmatched = set(), 0, 0
    history_cache: dict = {}
    for day in partitions:
        require_partition(day)
        for path in sorted(Path(evidence_root, day).glob("*/book-*.jsonl.gz")):
            token = path.name[len("book-"):-len(".jsonl.gz")]
            if token not in tokens:
                continue  # not an admitted saved Yes token: never parsed
            if token not in history_cache:
                history_cache[token] = load_history(Path(run_dir) / tokens[token][1])
            stamps, prices = history_cache[token]
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    view = book_view(json.loads(json.loads(line)["body_utf8"]))
                    if view is None:
                        continue
                    snapshots += 1
                    got = False
                    for side in ("before", "after"):
                        hp = nearest(stamps, prices, view["ts"], side)
                        if hp is None:
                            continue
                        got = True
                        for ref in ("mid", "ltp", "display"):
                            if view[ref] is not None:
                                diffs[f"{ref}_{side}"].append(hp - view[ref])
                        if side == "before" and view["spread"] is not None and view["spread"] > DISPLAY_SPREAD_LIMIT:
                            if view["mid"] is not None:
                                wide["mid_before"].append(hp - view["mid"])
                            if view["ltp"] is not None:
                                wide["ltp_before"].append(hp - view["ltp"])
                    if got:
                        matched_tokens.add(token)
                    else:
                        unmatched += 1
    return {
        "partitions": list(partitions), "tokens_matched": len(matched_tokens), "book_snapshots": snapshots,
        "snapshots_without_history_within_120s": unmatched,
        "history_minus_reference": {k: summarize(v) for k, v in diffs.items()},
        "wide_spread_gt_0_10": {k: summarize(v) for k, v in wide.items()},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--partitions", default=",".join(DEFAULT_PARTITIONS))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    partitions = [require_partition(p) for p in args.partitions.split(",") if p]
    result = compare(Path(args.run), Path(args.evidence_root), partitions)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"fidcheck-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    print(json.dumps(result, indent=1))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
