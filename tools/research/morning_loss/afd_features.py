"""L5 item 2: parse the fetched IEM AFOS Area Forecast Discussion text into per-product features.

Reads only the files written by afd_fetch.py (plain text, parsed with regular expressions, never executed).
Per product: WFO, UTC issuance from the WMO header (``FXUS6x Kxxx DDHHMM`` within the file's UTC month), and
four pre-declared text features:

- ``marine_depth_ft``: first "marine layer ... N[,NNN][ - M] feet|ft" (or "N feet deep") in the product,
  range midpoint; NaN when absent;
- ``stratus_rate``: mentions of stratus | marine layer | low cloud(s) | fog | drizzle | marine push per 1,000
  words;
- ``late_clear``: 1 if "(slow|struggl*|late|reluctant) to (clear|burn|mix|scatter)" or "linger*/persist*"
  within 60 characters of stratus|cloud|fog|marine, else 0;
- ``warm_minus_cool``: count of warmer|warming|heat|hot|hotter minus cooler|cooling.

    python tools/research/morning_loss/afd_features.py --raw C:\\t\\l5\\afd\\raw --out C:\\t\\l5\\inputs\\afd_products.parquet
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

import pandas as pd

HEADER = re.compile(r"^FX\w{4}\s+K(\w{3})\s+(\d{2})(\d{2})(\d{2})", re.M)
NUM = r"(\d{1,2},\d{3}|\d{3,4})"
DEPTH = [re.compile(r"marine layer[^.]{0,80}?" + NUM + r"(?:\s*(?:-|to)\s*" + NUM + r")?\s*(?:feet|ft)\b"),
         re.compile(NUM + r"(?:\s*(?:-|to)\s*" + NUM + r")?\s*(?:feet|ft)\s+deep")]
STRATUS = re.compile(r"\bstratus\b|\bmarine layer\b|\blow clouds?\b|\bfog\b|\bdrizzle\b|\bmarine push\b")
LATE = re.compile(r"(?:slow|struggl\w*|late|reluctant)\s+to\s+(?:clear|burn|mix|scatter)|\blinger\w*|\bpersist\w*")
NEAR = re.compile(r"stratus|cloud|fog|marine")
WARM = re.compile(r"\bwarm(?:er|ing)\b|\bheat\b|\bhot(?:ter)?\b")
COOL = re.compile(r"\bcool(?:er|ing)\b")
LAST = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)


def _n(s):
    return float(s.replace(",", "")) if s else None


def features(text):
    low = text.lower()
    depth = float("nan")
    for pat in DEPTH:
        m = pat.search(low)
        if m:
            a, b = _n(m.group(1)), _n(m.group(2))
            depth = (a + b) / 2 if b else a
            break
    words = max(1, len(low.split()))
    late = 0
    for m in LATE.finditer(low):
        if NEAR.search(low[max(0, m.start() - 60):m.end() + 60]):
            late = 1
            break
    return {"marine_depth_ft": depth, "stratus_rate": 1000.0 * len(STRATUS.findall(low)) / words,
            "late_clear": late, "warm_minus_cool": len(WARM.findall(low)) - len(COOL.findall(low)),
            "n_words": words}


def parse_file(path):
    wfo_file, ym = path.stem.split("_")
    year, month = int(ym[:4]), int(ym[5:7])
    text = path.read_text(encoding="latin-1")
    out = []
    for chunk in text.split("\x01"):
        h = HEADER.search(chunk)
        if not h:
            continue
        day, hh, mm = int(h.group(2)), int(h.group(3)), int(h.group(4))
        try:
            issued = dt.datetime(year, month, day, hh, mm, tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if issued >= LAST:
            continue
        out.append({"wfo": h.group(1), "issued_utc": issued, **features(chunk)})
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--raw", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    rows = []
    for path in sorted(Path(a.raw).glob("AFD*_*.txt")):
        rows += parse_file(path)
    df = pd.DataFrame(rows).drop_duplicates(["wfo", "issued_utc"]).sort_values(["wfo", "issued_utc"])
    df.to_parquet(a.out, index=False)
    print(df.groupby("wfo").agg(n=("issued_utc", "size"), first=("issued_utc", "min"), last=("issued_utc", "max"),
                                depth_fill=("marine_depth_ft", lambda s: s.notna().mean()),
                                stratus=("stratus_rate", "mean"), late=("late_clear", "mean")).to_string())


if __name__ == "__main__":
    main()
