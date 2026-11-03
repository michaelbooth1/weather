"""Row 28 r4: compute the paired deciding-date list by code, outcome-blind.

Reads metadata only:
- PIT forecast corpus manifests and the status rows of coverage.jsonl (via the
  B-bound pooled_residual_model.covered_years / window_days / nearest_centre,
  imported read-only);
- the 07Z NBP listing TSV (date, LastModified or ABSENT, bytes);
- market timezones from config/locations.json.

No label, observation, settlement or score is read. Writes the date list and a
small JSON receipt, and asserts the frozen r4 sha when --expect-sha is given.

Run (WS, light): venv python -I this_file --repo <worktree> --corpora <dir> --listing <tsv>
    --out <txt> --expect-sha 6913484a6abb1c7f0f2083eef919699cb2f05670c52306b2ab96998e0d84bcfb
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

US10 = ("atlanta", "austin", "chicago", "dallas", "houston", "los-angeles",
        "miami", "nyc", "san-francisco", "seattle")
SCORED_HOURS = (13, 14, 15, 16)
SEALED = (date(2026, 5, 27), date(2026, 7, 30))
HARD_FROM = date(2026, 9, 30)


def spring_dst(year: int) -> date:
    d = date(year, 3, 8)
    while d.weekday() != 6:
        d += timedelta(1)
    return d


def season_year(d: date) -> int:
    return d.year + 1 if d.month == 12 else d.year


def candidate_dates():
    """Deciding tier before structural drops: Dec 17-May 31, folds 2021-2025, spring-DST day excluded."""
    out, d = [], date(2021, 1, 1)
    while d <= date(2025, 5, 31):
        dec = d.month == 12 and d.day >= 17 and d.year <= 2024
        if (d.month <= 5 or dec) and d != spring_dst(d.year):
            out.append(d)
        d += timedelta(1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--corpora", required=True,
                    help="directory of PIT corpora (<checkout>/data/training/pit_forecast_corpus/corpora)")
    ap.add_argument("--listing", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-sha", default="")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "src"))
    from weather.calibration import pooled_residual_model as prm  # read-only use

    # data/ is ignored local state; --corpora names the checkout that holds the PIT corpora.
    manifests = sorted(glob.glob(os.path.join(a.corpora, "*", "manifest.json")))
    if not manifests:
        raise SystemExit("no PIT corpus manifests under --corpora")
    centres = tuple(prm.FORWARD_CENTRES) + tuple(prm.JAN_JUL_CENTRES) + ("2026-12-24",)

    cands = candidate_dates()
    for d in cands:
        assert not (SEALED[0] <= d <= SEALED[1]) and d < HARD_FROM

    # 1. Record-window coverage: a date has a record only inside a (centre, year) window that
    #    covered_years accepts (all 11 markets x hours 7-20 complete). Windows of arm A's centre
    #    set partition the year at 15-day spacing (no overlaps), so membership equals "the
    #    nearest-centre window is covered". nearest_centre itself is not called here because it
    #    raises on Feb 29 (date(2001, 2, 29)); see prereg section 3.2.
    covered_days = set()
    seen = Counter()
    for c in centres:
        for y in prm.covered_years(c, manifests):
            for d in prm.window_days(c, y):
                covered_days.add(d)
                seen[d] += 1
    assert max(seen.values()) == 1, "record windows overlap"

    def covered(d: date) -> bool:
        return d in covered_days

    # 2. 07Z posted by every scored US10 cutoff (served MG-1 reads only 07Z).
    posted = {}
    with open(a.listing, encoding="utf-8") as h:
        for line in h:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) >= 2:
                posted[parts[0]] = None if parts[1] == "ABSENT" else datetime.fromisoformat(
                    parts[1].replace("Z", "+00:00"))
    with open(os.path.join(a.repo, "config", "locations.json"), encoding="utf-8") as h:
        tz = {x["id"]: ZoneInfo(x["timezone"]) for x in json.load(h)["locations"] if x["id"] in US10}
    assert set(tz) == set(US10)

    def late07(d: date) -> bool:
        lm = posted.get(d.isoformat(), "MISSING")
        if lm == "MISSING":
            raise SystemExit(f"listing has no row for {d}")
        if lm is None:
            return True
        return any(lm > datetime(d.year, d.month, d.day, hr, tzinfo=tz[m]).astimezone(timezone.utc)
                   for m in US10 for hr in SCORED_HOURS)

    nocov = [d for d in cands if not covered(d)]
    late = [d for d in cands if late07(d)]
    keep = [d for d in cands if d not in set(nocov) | set(late)]

    def ranges(ds):
        out, s, p = [], None, None
        for d in ds:
            if s is None:
                s = p = d
            elif (d - p).days == 1:
                p = d
            else:
                out.append((s.isoformat(), p.isoformat())); s = p = d
        if s is not None:
            out.append((s.isoformat(), p.isoformat()))
        return out

    # CRLF line ends: the frozen r4 list (sha 6913484a...) was first written on Windows in text mode.
    text = "\r\n".join(d.isoformat() for d in keep) + "\r\n"
    with open(a.out, "w", encoding="utf-8", newline="") as h:
        h.write(text)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    receipt = {
        "candidates": len(cands), "no_record_window": len(nocov),
        "no_record_window_ranges": ranges(nocov),
        "late_or_absent_07z": [d.isoformat() for d in late],
        "late_extra": [d.isoformat() for d in late if d not in set(nocov)],
        "kept": len(keep), "folds": dict(sorted(Counter(season_year(d) for d in keep).items())),
        "look_n": sum(1 for d in keep if season_year(d) <= 2023),
        "manifests": len(manifests), "out_sha256": sha,
    }
    print(json.dumps(receipt, indent=1))
    if a.expect_sha and sha != a.expect_sha.lower():
        print(f"SHA MISMATCH: {sha} != {a.expect_sha}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
