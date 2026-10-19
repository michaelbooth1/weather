"""HARNESS v3 outcome side: the ONLY module that names, writes or opens label and market files.

- ``write_layout`` writes a v3 layout (outcome-free inputs + labels + market + manifest).
- ``split_v2_cache`` derives a layout from the swarm v2 cache (dates <= 2026-09-29 only).
- ``load_outcomes`` opens labels and market prices, and only with a gate ``Ticket`` whose
  purpose is a join and whose dates cover every date each file holds (re-checked against the gate).
- ``LabelLedger`` (H6) records which labels a scoring pass consumed: labels only, a
  ``promotion_countable`` flag, deduplicated by (family, date, market).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

from tools.research.model_parity import v3_gate, v3_inputs

LABEL_FILE = "labels.parquet"
MARKET_FILE = "market.parquet"
LABEL_COLUMNS = ("row_key", "date", "market", "winner", "settlement_high", "settlement_bucket",
                 "promotion_countable")
MARKET_COLUMNS = ("row_key", "band_index", "date", "market", "p_market_yes")
LEDGER_SCHEMA = "harness_v3_label_ledger/1"
DEV_LAST_DATE = "2026-09-29"


class OutcomeError(RuntimeError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _parquet_bytes(frame):
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return buf.getvalue()


def write_layout(root, snaps, bands, labels, market, source=None):
    """Write a v3 layout. ``snaps``/``bands`` must already be outcome-free (checked by name)."""
    from tools.research.model_parity.harness import FORBIDDEN
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, frame in (("snapshots", snaps), ("bands", bands)):
        leaked = FORBIDDEN & set(frame.columns)
        if leaked:
            raise OutcomeError(f"input {name} carries forbidden columns {sorted(leaked)}")
    files = {v3_inputs.INPUT_FILES["snapshots"]: snaps, v3_inputs.INPUT_FILES["bands"]: bands,
             LABEL_FILE: labels[list(LABEL_COLUMNS)], MARKET_FILE: market[list(MARKET_COLUMNS)]}
    manifest = {"schema": v3_inputs.LAYOUT_SCHEMA, "built_utc": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "source": source or {}, "files": {}}
    for name, frame in files.items():
        data = _parquet_bytes(frame)
        (root / name).write_bytes(data)
        manifest["files"][name] = {"sha256": _sha(data), "rows": int(len(frame)),
                                   "dates": sorted(frame["date"].astype(str).unique().tolist())}
    (root / v3_inputs.MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def split_v2_cache(out_root, cache=None):
    """Split the swarm v2 cache into a v3 layout. Development only: refuses any date > 09-29."""
    from tools.research.model_parity import harness as h
    d = h.data(cache or h.CACHE)
    if d.snaps.date.max() > DEV_LAST_DATE:
        raise OutcomeError("v2 cache holds a date after 2026-09-29")
    snaps = d.snaps[list(h.SNAPSHOT_ALLOWED)].copy()
    bands = d.bands[list(h.BAND_ALLOWED) + ["date", "market", "local_hour", "block", "stratum"]].copy()
    labels = d.snaps[["row_key", "date", "market", "winner", "settlement_high", "settlement_bucket"]].copy()
    labels["promotion_countable"] = False          # development evidence is never promotion-countable
    market = d.bands[["row_key", "band_index", "date", "market", "p_market_yes"]].copy()
    source = {"v2_cache_receipt_files": d.receipt["files"], "v2_input_sha256": d.receipt["input"]["sha256"],
              "harness_sha256": h.harness_sha256()}
    return write_layout(out_root, snaps, bands, labels, market, source=source)


def load_outcomes(root, gate, ticket):
    """Labels per snapshot and market prices per band, for the ticket's dates only."""
    if not isinstance(ticket, v3_gate.Ticket) or ticket.purpose not in v3_gate.JOIN_PURPOSES:
        raise v3_gate.GateRefused([{"family": getattr(ticket, "family", "?"), "date": "*",
                                    "purpose": getattr(ticket, "purpose", "?"),
                                    "reasons": ["outcomes need a join ticket from the gate"]}])
    manifest = v3_inputs.read_manifest(root)
    out = {}
    for name in (LABEL_FILE, MARKET_FILE):
        # every date in the file must be one the gate allows for this family and purpose
        v3_inputs.gate_file(gate, manifest, name, ticket.family, ticket.purpose, ticket.reads_nbm_guidance)
        frame = pd.read_parquet(io.BytesIO(v3_inputs.read_verified(root, name, manifest)))
        out[name] = frame[frame.date.astype(str).isin(ticket.dates)].reset_index(drop=True)
    labels, market = out[LABEL_FILE], out[MARKET_FILE]
    ticket.check(labels.date.astype(str).unique())
    return labels, market


# ----------------------------------------------------------------------------- H6 label ledger

class LabelLedger:
    """Append-only jsonl of consumed labels; one row per (family, date, market)."""

    def __init__(self, path):
        self.path = Path(path)
        self.rows = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.rows[(row["family"], row["date"], row["market"])] = row

    @staticmethod
    def _label_part(row):
        return {k: row[k] for k in ("settlement_bucket", "promotion_countable")}

    def record(self, family, labels, prereg_sha256):
        """Write one row per (family, date, market) in ``labels``; returns (written, skipped).

        The row is the settled bucket (the market-day label; band indices differ by ladder) and the
        promotion_countable flag. No forecast, price or score is ever written here."""
        days = labels.groupby(["date", "market"], sort=True, dropna=False).agg(
            settlement_bucket=("settlement_bucket", "first"),
            bucket_n=("settlement_bucket", "nunique"),
            promotion_countable=("promotion_countable", "all")).reset_index()
        if (days.bucket_n > 1).any():
            raise OutcomeError("a market-day carries more than one settlement bucket")
        new, skipped = [], 0
        for r in days.itertuples(index=False):
            row = {"schema": LEDGER_SCHEMA, "family": family, "date": str(r.date), "market": str(r.market),
                   "settlement_bucket": None if pd.isna(r.settlement_bucket)
                   else int(r.settlement_bucket), "promotion_countable": bool(r.promotion_countable),
                   "prereg_sha256": prereg_sha256}
            key = (family, row["date"], row["market"])
            if key in self.rows:
                if self._label_part(self.rows[key]) != self._label_part(row):
                    raise OutcomeError(f"label ledger conflict for {key}")
                skipped += 1
                continue
            row["written_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.rows[key] = row
            new.append(row)
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as stream:
                stream.writelines(json.dumps(x, sort_keys=True) + "\n" for x in new)
        return len(new), skipped
