"""Development scorecard inputs: date guard, layout reader, walk-forward folds, candidates.

Development evidence only. The scorecard scores model variants against captured market prices and
WU settlement labels on target dates 2026-07-31..2026-09-29. It reads a HARNESS v3 layout directory
(``manifest.json`` schema ``harness_v3_layout/1`` written by ``tools/research/model_parity/v3_outcomes``
on branch ``claude/harness-v3-20261019``): ``inputs_snapshots.parquet`` and ``inputs_bands.parquet``
(outcome-free), ``labels.parquet`` and ``market.parquet``.

Date guard (fail closed, before any outcome file is opened):

- a requested range ending after ``DEV_LAST`` (2026-09-29) is refused;
- a requested range starting before ``DEV_FIRST`` (2026-07-31, the artifact-provenance boundary of
  EF section 5; never pooled across) is refused;
- a layout whose manifest declares any date after ``DEV_LAST`` for any file is refused before that
  file is opened; every file is sha256-checked against the manifest and filtered to the range at
  read time, and the filtered rows are re-checked.

Walk-forward (fold scheme): target dates are cut into consecutive calendar folds of ``fold_days``
starting at the range start. A fold's training pool is every layout date ``<= fold_start -
(gap_days + 1)`` (with the default ``gap_days=1`` a fold starting on D trains on dates up to D-2,
because D-1's settlement is finalised during D). A fold is scored only when its pool has at least
``min_train_dates`` dates; the scored population is set by the scheme alone, so every candidate type
(served, market, module, vectors) is scored on the same rows.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DEV_FIRST = date(2026, 7, 31)
DEV_LAST = date(2026, 9, 29)
LAYOUT_SCHEMA = "harness_v3_layout/1"
MANIFEST = "manifest.json"
SNAPSHOTS_FILE = "inputs_snapshots.parquet"
BANDS_FILE = "inputs_bands.parquet"
LABELS_FILE = "labels.parquet"
MARKET_FILE = "market.parquet"
LAYOUT_FILES = (SNAPSHOTS_FILE, BANDS_FILE, LABELS_FILE, MARKET_FILE)
# Labels and market prices: never handed to candidate code.
LABELISH = frozenset({"winner", "settlement_high", "settlement_bucket", "settlement_source", "is_winner",
                      "p_market_yes", "best_bid", "best_ask", "market_mid", "promotion_countable",
                      "label_source"})
CANDIDATE_COLUMNS = ("row_key", "band_index", "p")
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
# Settlement-label rule: Weather Underground history before 2026-10-23 (no later date is in scope).
WU_LABEL_RULE_LAST = date(2026, 10, 22)
DEFAULT_LABEL_SOURCE = ("data/settlements/<market>/ledger.jsonl (Weather Underground daily history; "
                        "settlement_authority=ledger_authority), via the layout labels file")


class Refused(ValueError):
    """A date, file or candidate the development scorecard must not read or score."""

    exit_code = 2


class LayoutError(RuntimeError):
    exit_code = 3


class LeakageError(AssertionError):
    exit_code = 4


class WalkForwardError(ValueError):
    exit_code = 6


def parse_date(text):
    try:
        return date.fromisoformat(str(text))
    except ValueError as exc:
        raise Refused(f"refused: not an ISO date: {text!r}") from exc


def check_range(start, end):
    """Refuse any range outside DEV_FIRST..DEV_LAST. Returns (start, end) as dates."""
    start, end = parse_date(start), parse_date(end)
    if end > DEV_LAST:
        raise Refused(f"refused: --to {end} is after {DEV_LAST}; dates after 2026-09-29 are not "
                      "development evidence and are never read")
    if start < DEV_FIRST:
        raise Refused(f"refused: --from {start} is before {DEV_FIRST} (artifact-provenance boundary, "
                      "EF section 5: never pooled across)")
    if start > end:
        raise Refused(f"refused: --from {start} is after --to {end}")
    return start, end


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as stream:
        return sha256_bytes(stream.read())


# ----------------------------------------------------------------------------- layout

@dataclass
class Layout:
    snaps: pd.DataFrame
    bands: pd.DataFrame
    labels: pd.DataFrame
    market: pd.DataFrame
    manifest_sha256: str
    file_sha256: dict
    label_source: str
    dates: list = field(default_factory=list)


def _read_manifest(root):
    path = Path(root) / MANIFEST
    if not path.is_file():
        raise LayoutError(f"layout manifest missing: {path}")
    data = path.read_bytes()
    manifest = json.loads(data.decode("utf-8"))
    if manifest.get("schema") != LAYOUT_SCHEMA:
        raise LayoutError(f"layout manifest schema {manifest.get('schema')!r} != {LAYOUT_SCHEMA!r}")
    return manifest, sha256_bytes(data)


def _guard_manifest_dates(manifest):
    for name in LAYOUT_FILES:
        entry = manifest.get("files", {}).get(name)
        if entry is None:
            raise LayoutError(f"{name} is not in the layout manifest")
        dates = entry.get("dates")
        if not isinstance(dates, list) or not dates:
            raise LayoutError(f"{name}: manifest carries no date list (cannot gate before opening)")
        late = sorted(d for d in dates if parse_date(d) > DEV_LAST)
        if late:
            raise Refused(f"refused: layout file {name} declares {len(late)} date(s) after {DEV_LAST} "
                          f"(first {late[0]}); it is not opened")


def _read_verified(root, name, manifest):
    with open(Path(root) / name, "rb") as stream:
        data = stream.read()
    sha = sha256_bytes(data)
    if sha != manifest["files"][name]["sha256"]:
        raise LayoutError(f"{name} does not match its manifest sha256")
    return pd.read_parquet(io.BytesIO(data)), sha


def _in_range(frame, start, end, name):
    days = pd.to_datetime(frame["date"].astype(str), format="%Y-%m-%d").dt.date
    if (days > DEV_LAST).any():
        raise Refused(f"refused: {name} holds a row after {DEV_LAST} despite its manifest")
    keep = (days >= start) & (days <= end)
    return frame.loc[keep.to_numpy()].reset_index(drop=True)


def load_layout(root, start, end):
    """Read a v3 layout restricted to [start, end] (dates already passed ``check_range``)."""
    manifest, manifest_sha = _read_manifest(root)
    _guard_manifest_dates(manifest)
    frames, shas = {}, {}
    for name in LAYOUT_FILES:
        frame, shas[name] = _read_verified(root, name, manifest)
        frames[name] = _in_range(frame, start, end, name)
    snaps, bands = frames[SNAPSHOTS_FILE], frames[BANDS_FILE]
    leaked = LABELISH & (set(snaps.columns) | set(bands.columns))
    if leaked:
        raise LeakageError(f"layout inputs carry label/market columns {sorted(leaked)}")
    if snaps.row_key.duplicated().any():
        raise LayoutError("duplicate row_key in inputs_snapshots")
    n = snaps.n_bands.to_numpy(int)
    offsets = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
    if len(bands) != int(n.sum()) or (len(snaps) and not (
            bands.row_key.to_numpy()[offsets] == snaps.row_key.to_numpy()).all()):
        raise LayoutError("inputs_bands is not contiguous per snapshot in snapshot order")
    labels = frames[LABELS_FILE]
    label_source = DEFAULT_LABEL_SOURCE
    if "label_source" in labels.columns:
        sources = sorted(labels.label_source.astype(str).unique())
        label_source = "; ".join(sources)
    lab_dates = pd.to_datetime(labels.date.astype(str)).dt.date
    if len(labels) and lab_dates.max() > WU_LABEL_RULE_LAST:
        raise Refused("refused: a label dated 2026-10-23 or later is outside the WU label rule")
    return Layout(snaps=snaps, bands=bands, labels=labels, market=frames[MARKET_FILE],
                  manifest_sha256=manifest_sha, file_sha256=shas, label_source=label_source,
                  dates=sorted(snaps.date.astype(str).unique()))


# ----------------------------------------------------------------------------- folds

@dataclass(frozen=True)
class Fold:
    index: int
    start: str
    end: str
    train_last: str
    train_dates: tuple
    dates: tuple
    scored: bool
    reason: str

    def as_dict(self):
        return {"index": self.index, "start": self.start, "end": self.end, "train_last": self.train_last,
                "n_train_dates": len(self.train_dates), "n_dates": len(self.dates),
                "scored": self.scored, "reason": self.reason}


def make_folds(available_dates, start, end, fold_days=7, gap_days=1, min_train_dates=7):
    """Consecutive calendar folds over [start, end]; see the module docstring."""
    if fold_days < 1 or gap_days < 0 or min_train_dates < 0:
        raise Refused("refused: fold_days >= 1, gap_days >= 0, min_train_dates >= 0")
    avail = sorted({parse_date(d) for d in available_dates})
    folds, k, cursor = [], 0, start
    while cursor <= end:
        fold_end = min(end, cursor + timedelta(days=fold_days - 1))
        train_last = cursor - timedelta(days=gap_days + 1)
        train = tuple(d.isoformat() for d in avail if d <= train_last)
        days = tuple(d.isoformat() for d in avail if cursor <= d <= fold_end)
        if not days:
            scored, reason = False, "no_dates"
        elif len(train) < min_train_dates:
            scored, reason = False, f"train_pool_{len(train)}_lt_{min_train_dates}"
        else:
            scored, reason = True, "scored"
        folds.append(Fold(k, cursor.isoformat(), fold_end.isoformat(), train_last.isoformat(), train, days,
                          scored, reason))
        k += 1
        cursor = fold_end + timedelta(days=1)
    return folds


# ----------------------------------------------------------------------------- candidates

@dataclass
class CandidateSpec:
    kind: str                 # served | market | module | vectors | distributions
    path: str | None = None
    trained_through: str | None = None
    no_training: bool = False

    def identity(self):
        out = {"kind": self.kind}
        if self.path:
            out["sha256"] = sha256_file(self.path)
            out["name"] = Path(self.path).name
        if self.kind in ("vectors", "distributions"):
            out["trained_through"] = self.trained_through
            out["no_training"] = self.no_training
        return out


def screen_inputs(snaps, bands):
    leaked = LABELISH & (set(snaps.columns) | set(bands.columns))
    if leaked:
        raise LeakageError(f"candidate inputs carry label/market columns {sorted(leaked)}")


def load_module(path):
    path = Path(path)
    code = path.read_bytes()
    spec = importlib.util.spec_from_file_location(f"dev_scorecard_candidate_{sha256_bytes(code)[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(code, str(path), "exec"), module.__dict__)
    for name in ("NAME", "fit", "predict"):
        if not hasattr(module, name):
            raise Refused(f"refused: candidate module {path.name} lacks {name}")
    return module


def _check_frame(frame, allowed_keys, label):
    if not isinstance(frame, pd.DataFrame) or set(frame.columns) != set(CANDIDATE_COLUMNS):
        raise Refused(f"refused: {label} must return exactly columns {CANDIDATE_COLUMNS}")
    stray = ~frame.row_key.isin(allowed_keys)
    if stray.any():
        raise WalkForwardError(f"{label} returned {int(stray.sum())} rows outside its fold")
    return frame[list(CANDIDATE_COLUMNS)]


def module_predictions(spec, layout, folds):
    """Fit on each scored fold's training pool, predict that fold. Labels never reach predict."""
    module = load_module(spec.path)
    snaps, bands, labels = layout.snaps, layout.bands, layout.labels
    lab_cols = [c for c in ("row_key", "date", "market", "winner", "settlement_bucket") if c in labels.columns]
    out, fits, state = [], [], None
    for fold in folds:
        if not fold.scored:
            continue
        train_mask = snaps.date.astype(str).isin(fold.train_dates)
        if train_mask.any() and snaps.loc[train_mask, "date"].astype(str).max() > fold.train_last:
            raise WalkForwardError("training pool reaches past the fold's train_last")
        tr_keys = set(snaps.row_key[train_mask])
        train = {"snapshots": snaps[train_mask].reset_index(drop=True),
                 "bands": bands[bands.row_key.isin(tr_keys)].reset_index(drop=True),
                 "labels": labels.loc[labels.row_key.isin(tr_keys), lab_cols].reset_index(drop=True)}
        screen_inputs(train["snapshots"], train["bands"])
        state = module.fit(train)
        fold_mask = snaps.date.astype(str).isin(fold.dates)
        fs = snaps[fold_mask].reset_index(drop=True)
        fb = bands[bands.row_key.isin(set(fs.row_key))].reset_index(drop=True)
        screen_inputs(fs, fb)
        pred = module.predict(state, fs.copy(), fb.copy())
        out.append(_check_frame(pred, set(fs.row_key), f"candidate {module.NAME} fold {fold.index}"))
        fits.append({"fold": fold.index, "train_dates": len(fold.train_dates), "train_last": fold.train_last,
                     "max_train_label_date": train["labels"].date.astype(str).max() if len(train["labels"])
                     else None})
    frame = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=list(CANDIDATE_COLUMNS))
    meta = {"name": str(module.NAME), "fits": fits}
    # A state may declare its inputs (file hashes, fixed tables); recorded once, from the last fold.
    if isinstance(state, dict) and isinstance(state.get("provenance"), dict):
        meta["state_provenance"] = state["provenance"]
    return frame, meta


def _check_trained_through(spec, folds):
    if spec.no_training:
        return {"walk_forward": "not_applicable_no_fitted_parameters"}
    if not spec.trained_through:
        raise WalkForwardError("a vectors/distributions candidate needs --trained-through DATE or --no-training")
    trained = parse_date(spec.trained_through)
    bad = [f.index for f in folds if f.scored and trained > parse_date(f.train_last)]
    if bad:
        raise WalkForwardError(f"candidate trained through {trained} overlaps scored folds {bad}: not walk-forward")
    return {"walk_forward": "declared", "trained_through": trained.isoformat()}


def _read_table(path):
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def vector_predictions(spec, layout, folds):
    meta = _check_trained_through(spec, folds)
    frame = _read_table(spec.path)
    if "date" in frame.columns:
        days = pd.to_datetime(frame.date.astype(str)).dt.date
        if (days > DEV_LAST).any():
            raise Refused(f"refused: candidate vectors hold rows after {DEV_LAST}")
        frame = frame.drop(columns=["date"])
    keys = set(layout.snaps.row_key)
    frame = frame[frame.row_key.isin(keys)]
    return _check_frame(frame, keys, "candidate vectors"), meta


def _open_text(path):
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8")


def distribution_predictions(spec, layout, folds):
    """JSONL rows ``{market, snapshot_id, distribution: {native integer degree: p}}`` mapped onto bands."""
    meta = _check_trained_through(spec, folds)
    snaps = layout.snaps.set_index("row_key")
    dists, unknown = {}, 0
    with _open_text(spec.path) as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if "target_date" in row and parse_date(row["target_date"]) > DEV_LAST:
                raise Refused(f"refused: candidate distributions hold rows after {DEV_LAST}")
            key = f"{row['market']}|{row['snapshot_id']}"
            if key not in snaps.index:
                unknown += 1
                continue
            dists[key] = {int(float(k)): float(v) for k, v in (row.get("distribution") or {}).items()}
    b = layout.bands[layout.bands.row_key.isin(set(dists))]
    probs = []
    for rk, kind, low, high in zip(b.row_key, b.kind, b.low, b.high):
        d = dists[rk]
        if kind == "lte":
            probs.append(sum(p for k, p in d.items() if k <= high))
        elif kind == "gte":
            probs.append(sum(p for k, p in d.items() if k >= low))
        else:
            probs.append(sum(p for k, p in d.items() if low <= k <= high))
    frame = pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                          "p": np.asarray(probs, float)})
    meta["unknown_snapshots"] = unknown
    return frame, meta
