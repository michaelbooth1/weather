"""Lever 5 / EXHAUSTION_REGISTER order 16: outcome-blind stage-restoration replay.

For every captured snapshot (``replay_inputs.jsonl``) of a dev target date
2026-07-31..2026-09-29, re-run the CURRENT serving pipeline once as served
("base") and once per variant, and report how far the final probability vector
moved. It reads no settlement, no label, no market price and no
``snapshots.jsonl``: only ``sources`` and ``built_at`` from replay_inputs, the
model artifacts, and the market's prior-year climatology under ``--data-root``.

Stages (the 13 of EF §10e, re-traced on origin/master 6aac6de81; detail in
docs/research/model-edge-lever5-2026-10-19.md section 2):
- live again since lockin-anchor v3/v4, NOT replayed here: S1 heuristic
  lock-in, S2 learned lock-in, S3 high-has-stood, S4 expanded, S5 standing-high
  partial, ``apply_late_day_lockin``, S7 calibration taper, S6 late-day
  continuation (cutoff hours 15-17). Their effect is already in "base".
- still no-ops, each replayed as one variant: bucket-transition blend,
  intraday tail, learned METAR live signal, WU-floor residual, trusted current
  max (Miami validated floor + live-signal member).
- fail closed as well when the market's served HGB pickle does not load
  (``folder_error`` ``hgb_artifact_unavailable``): artifacts resolve from the
  code checkout's ``artifacts/``, so run from a worktree with
  ``git lfs checkout artifacts/models/hgb`` done.
- plus the 110g afternoon centering (off by owner decision) and two NBM input
  checks (task 4).

Runs per snapshot: 1 base + 1 per selected variant (default 8 variants, so 9).

Variants:
- ``nbm_removed`` / ``nbm_perturbed``: drop ``nbm_probabilistic_tmax``, or add
  +10 native degrees to every NBM value. Expected 0 everywhere.
- ``centering_reenabled``: the 110g artifact as fitted, ``enabled`` true.
- ``trusted_current_max_repointed``: ``current_max_trust_features`` (in the
  distribution module only) validates METAR max-since-07:00 against the
  observed station high instead of the empty WU history.
- ``wu_residual_repointed`` / ``metar_live_signal_repointed`` /
  ``intraday_tail_repointed``: the stage reads the observed station high /
  bucket instead of the empty WU high.
- ``bucket_transition_repointed``: the bucket-transition prior reads the
  observed station high at the cutoff.

Twins (EDGE-1 annex, bundle B ``83ba04f96`` section 1.1; only via ``--variants``):
- ``t1_nws_hourly_only``: every forecast payload except ``nws_hourly`` emptied
  (``T1_EMPTIED``); serving's own code then yields ``forecast_high`` = the NWS
  day max and recomputes ``forecast_gap``. A row with no captured NWS day max
  falls back to base (row field ``t1_nws_filled``).
- ``t0_climatology_prior``: every forecast payload emptied, ``forecast_high``
  set to the prior-year monthly mean daily high (``monthly_climatology_high``),
  ``forecast_gap`` recomputed.

Per snapshot and variant: ``tv`` = sum|delta|/2 over native 1-degree buckets
(an exact upper bound on the absolute change of any band probability for any
banding; 0 iff no band changes) and ``max_bucket``.

Roots. ``--data-root`` (required) and ``--config-root`` (default: the repo
``config/``) replace ``weather.paths.DATA_ROOT`` / ``CONFIG_ROOT``; call through
``python -m tools.research.model_edge_lever5.run replay`` so the config root is
set before ``weather.market.market_registry`` is imported. Fail closed: a folder
whose market climatology (``<data-root>/wunderground/<icao>/daily/
daily_summary.csv`` and its prior-year cache, which is also the
bucket-transition prior) is missing or empty gets one ``folder_error`` row and
no snapshot rows; it never falls back to an empty or uniform prior. Config:
with no bound release (``artifacts/releases`` absent), the serving model reads
no ``locations.json`` field (only ``toronto_model.py:159`` does, under a bound
release); the market registry reads ``<config-root>/markets.json`` at import,
and external rows there override built-in specs. The summary records the
effective registry path, the sha256 of ``markets.json`` and
``locations.json`` under the config root, and the resolved ``weather.__file__``
and this module's ``__file__`` (which checkout served). The climatology loaders drop every
row of the target year, so no 2026 value is used.

Output. ``--out`` is an append-only JSONL with a header line (schema, variants);
re-running with the same ``--out`` resumes: folders with a ``folder_done`` row
are skipped, a header mismatch is refused. A folder that ends in a
``folder_error`` gets no ``folder_done``, so a rerun (e.g. after an LFS fix)
re-attempts it; only rows of a folder's ``folder_done`` attempt are carried
forward, so no prior row is duplicated. Each folder prints one timing line
``TIMING folder=<name> snapshots=<n> seconds=<s> cumulative=<s>`` and rewrites
``--summary-out`` (atomic replace) so a killed run leaves a valid partial
summary. ``--budget-minutes`` stops starting new folders of a market once that
market's wall clock in this invocation exceeds it. Both output paths are
refused inside the runtime ``data/`` tree.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import weather.paths

FIRST_DATE = date(2026, 7, 31)
LAST_DATE = date(2026, 9, 29)
SCHEMA = "lever5_stage_replay_v2"
CHANGE_TOL = 1e-12
HOUR_BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12),
               ("13-16", 13, 16), ("17-23", 17, 23))
VARIANTS = (
    "nbm_removed",
    "nbm_perturbed",
    "centering_reenabled",
    "trusted_current_max_repointed",
    "wu_residual_repointed",
    "metar_live_signal_repointed",
    "bucket_transition_repointed",
    "intraday_tail_repointed",
)
# EDGE-1 annex twins (bundle B, 83ba04f96, edge1-annex-DRAFT-2026-10-19.md section 1.1). Not in the
# default set: select with --variants. Vector deltas only, no scoring.
TWIN_VARIANTS = ("t1_nws_hourly_only", "t0_climatology_prior")
ALL_VARIANTS = VARIANTS + TWIN_VARIANTS
# T1 empties every forecast payload except nws_hourly; T0 empties nws_hourly as well.
T1_EMPTIED = ("open_meteo", "weather_forecast", "eccc_citypage", "global_ensemble",
              "open_meteo_global_models")
T0_EMPTIED = T1_EMPTIED + ("nws_hourly",)


class Refused(ValueError):
    pass


# --- roots -----------------------------------------------------------------

def _sha256(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def configure_roots(data_root, config_root=None):
    """Point weather.paths at the operator's data and config roots."""
    if not data_root:
        raise Refused("refused: --data-root is required")
    data = Path(data_root).resolve()
    if not (data / "wunderground").is_dir():
        raise Refused(f"refused: --data-root {data} has no wunderground/ climatology tree")
    weather.paths.DATA_ROOT = data
    if config_root:
        config = Path(config_root).resolve()
        if not config.is_dir():
            raise Refused(f"refused: --config-root {config} is not a directory")
        weather.paths.CONFIG_ROOT = config
    info = root_info()
    from weather.market import market_registry

    if (config_root and not info["registry_env_override"]
            and Path(market_registry.DEFAULT_EXTERNAL_REGISTRY_PATH).parent.resolve()
            != Path(weather.paths.CONFIG_ROOT).resolve()):
        raise Refused("refused: the market registry was imported before --config-root was applied "
                      f"({market_registry.DEFAULT_EXTERNAL_REGISTRY_PATH}); "
                      "run via python -m tools.research.model_edge_lever5.run replay")
    return info


def root_info():
    config = Path(weather.paths.CONFIG_ROOT)
    from weather.market import market_registry

    return {
        "data_root": str(weather.paths.DATA_ROOT),
        "config_root": str(config),
        "registry_path_effective": str(market_registry._external_registry_path()),
        "markets_json_sha256": _sha256(config / "markets.json"),
        "locations_json_sha256": _sha256(config / "locations.json"),
        "registry_env_override": os.environ.get(market_registry.MARKET_REGISTRY_ENV),
        "weather_module_file": str(Path(weather.__file__).resolve()),
        "stage_replay_file": str(Path(__file__).resolve()),
    }


def check_out(path, *, allow_existing=False):
    out = Path(path).resolve()
    root = Path(weather.paths.DATA_ROOT).resolve()
    repo_data = Path(weather.paths.REPO_ROOT / "data").resolve()
    for forbidden in {root, repo_data}:
        if out == forbidden or forbidden in out.parents:
            raise Refused(f"refused: {out} is inside the runtime data tree {forbidden}")
    if out.exists() and not allow_existing:
        raise Refused(f"refused: {out} exists")
    return out


# --- variants --------------------------------------------------------------

def _station_high(model, sources, now, cutoff_minute=None):
    station = model.station_observation_data(sources)
    metar = model.source_data(sources, "metar")
    rows, _ = model.lockin_observed_rows(station=station, metar=metar, now=now)
    if cutoff_minute is not None:
        rows = [row for row in rows if row[0] <= cutoff_minute]
    return max((value for _, _, value in rows), default=None)


def _perturb_nbm(sources, delta):
    out = deepcopy(sources)
    item = out.get("nbm_probabilistic_tmax")
    data = item.get("data") if isinstance(item, dict) else None
    if not isinstance(data, dict) or not data:
        return out
    pct = data.get("percentiles")
    if isinstance(pct, dict):
        data["percentiles"] = {
            k: (v + delta if isinstance(v, (int, float)) else v) for k, v in pct.items()
        }
    for key in ("mean_native", "day_max_native", "day_max_c"):
        if isinstance(data.get(key), (int, float)):
            data[key] = data[key] + delta
    return out


@contextlib.contextmanager
def _patched(obj, name, value):
    # Modules hold the name in their dict (restore it); model instances get a
    # temporary instance attribute shadowing the class method (delete it).
    had = name in vars(obj)
    old = getattr(obj, name, None)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if had:
            setattr(obj, name, old)
        else:
            delattr(obj, name)


def nws_hourly_day_max(model, sources):
    """The captured NWS hourly point forecast's day maximum, or None (T1 fallback)."""
    return model.forecast_day_max(model.source_data(sources, "nws_hourly") or {})


def monthly_climatology_high(model):
    """Mean daily high of the target's calendar month over prior years only.

    Reads ``<data_root>/daily/daily_summary.csv`` like the serving climatology
    (rows with year >= the target year are dropped before use, as
    ``model_climatology`` does; rows below ``HISTORY_MIN_ROW_COUNT`` skipped).
    """
    import csv

    from weather.model.model_constants import HISTORY_MIN_ROW_COUNT
    from weather.sources.daily_summary import native_high

    target = model.target_date
    cache = model.__dict__.setdefault("_l5_monthly_clim", {})
    key = (str(model.spec.data_root), target.year, target.month)
    if key not in cache:
        values = []
        path = model.spec.data_root / "daily" / "daily_summary.csv"
        if path.is_file():
            with path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    try:
                        local = date.fromisoformat(row["local_date"])
                    except (KeyError, ValueError):
                        continue
                    if local.year >= target.year or local.month != target.month:
                        continue
                    if int(row.get("row_count") or 0) < HISTORY_MIN_ROW_COUNT:
                        continue
                    value = native_high(row)
                    if value is not None:
                        values.append(float(value))
        cache[key] = sum(values) / len(values) if values else None
    return cache[key]


@contextlib.contextmanager
def _forecast_feature_override(model, forecast_high):
    """Set the served ``forecast_high`` feature; recompute ``forecast_gap`` as serving does."""
    original = model.extract_live_features

    def extract(*args, **kwargs):
        feats = original(*args, **kwargs)
        if feats is not None:
            high = feats.get("high_so_far")
            feats["forecast_high"] = forecast_high
            feats["forecast_gap"] = (forecast_high - high
                                     if forecast_high is not None and high is not None else None)
        return feats

    with _patched(model, "extract_live_features", extract):
        yield


@contextlib.contextmanager
def variant_context(model, variant, sources, now):
    """Yield the sources to use; patch the model instance for one variant."""
    import weather.model.model_distribution as md

    if variant == "nbm_removed":
        yield {k: v for k, v in sources.items() if k != "nbm_probabilistic_tmax"}
        return
    if variant == "nbm_perturbed":
        yield _perturb_nbm(sources, 10.0)
        return
    if variant == "centering_reenabled":
        artifact = deepcopy(getattr(model, "afternoon_residual_centering", None) or {})
        if not artifact.get("contexts"):
            raise RuntimeError("centering artifact missing or empty")
        artifact.setdefault("component", {})["enabled"] = True
        with _patched(model, "afternoon_residual_centering", artifact):
            yield sources
        return
    if variant == "t1_nws_hourly_only":
        # Annex T1: a captured-input replay with every forecast payload except nws_hourly
        # emptied; forecast_high / forecast_gap then come from serving's own code. A row
        # with no captured nws_hourly day max takes A0's own vector (the annex fallback).
        if nws_hourly_day_max(model, sources) is None:
            yield sources
        else:
            yield {k: v for k, v in sources.items() if k not in T1_EMPTIED}
        return
    if variant == "t0_climatology_prior":
        # Annex T0: every forecast payload emptied (nws_hourly too) and the forecast_high
        # feature set to the prior-year monthly climatological high, gap recomputed.
        clim = monthly_climatology_high(model)
        if clim is None:
            raise RuntimeError("no prior-year monthly climatology")
        with _forecast_feature_override(model, clim):
            yield {k: v for k, v in sources.items() if k not in T0_EMPTIED}
        return
    high = _station_high(model, sources, now)
    if variant == "trusted_current_max_repointed":
        original = md.current_max_trust_features

        def repointed(current_max, *, history_max=None, **kwargs):
            if history_max is None:
                history_max = high
            return original(current_max, history_max=history_max, **kwargs)

        with _patched(md, "current_max_trust_features", repointed):
            yield sources
        return
    if variant == "wu_residual_repointed":
        bound = model.preserve_wu_floor_residual

        def residual(scores, history_max, observed_support_bucket):
            return bound(scores, history_max if history_max is not None else high,
                         observed_support_bucket)

        with _patched(model, "preserve_wu_floor_residual", residual):
            yield sources
        return
    if variant == "metar_live_signal_repointed":
        bound = model.learned_metar_live_signal

        def signal(metar_temp, history_max, hour=None):
            return bound(metar_temp, history_max if history_max is not None else high, hour=hour)

        with _patched(model, "learned_metar_live_signal", signal):
            yield sources
        return
    if variant == "bucket_transition_repointed":
        bound_cutoff = model.cutoff_aligned_wu_history_max_native
        bound_model = model.bucket_transition_model

        def transition(srcs, when, min_sample_size=5):
            def cutoff_high(history, cutoff_hour):
                value = bound_cutoff(history, cutoff_hour)
                if value is None:
                    value = _station_high(model, srcs, when, cutoff_minute=cutoff_hour * 60)
                return value

            with _patched(model, "cutoff_aligned_wu_history_max_native", cutoff_high):
                return bound_model(srcs, when, min_sample_size=min_sample_size)

        with _patched(model, "bucket_transition_model", transition):
            yield sources
        return
    if variant == "intraday_tail_repointed":
        bound = model.distribution_intraday_tail_stage

        def tail(scores, *, observed_bucket, **kwargs):
            if observed_bucket is None:
                observed_bucket = model.round_half_up(high)
            return bound(scores, observed_bucket=observed_bucket, **kwargs)

        with _patched(model, "distribution_intraday_tail_stage", tail):
            yield sources
        return
    raise ValueError(f"unknown variant {variant}")


def _run(model, sources, now):
    from weather.backtesting.replay import as_int_distribution

    result = model.estimate_distribution_result(sources, now=now)
    return as_int_distribution(result.distribution), result.component_payload or {}


def _delta(left, right):
    keys = set(left) | set(right)
    diffs = [abs(left.get(k, 0.0) - right.get(k, 0.0)) for k in keys]
    return {"tv": sum(diffs) / 2.0, "max_bucket": max(diffs, default=0.0)}


# --- per snapshot / per folder ----------------------------------------------

def hgb_error(model):
    """None when the served HGB bundle loads, else why (an LFS pointer or a missing
    pickle would silently fall back to LR/empirical, so base would not be served)."""
    try:
        bundle = model.load_feature_model_hgb()
    except Exception as exc:  # pragma: no cover - defensive
        return f"hgb_load_error:{type(exc).__name__}"
    if not bundle or not any(str(k).isdigit() for k in bundle):
        return "hgb_artifact_unavailable"
    return None


def climatology_error(model):
    """None when the market's prior-year climatology loads non-empty, else why."""
    summary = model.spec.data_root / "daily" / "daily_summary.csv"
    if not summary.is_file():
        return f"missing_climatology_summary:{summary}"
    cache = model.historical_target_cache()
    if not cache.get("daily"):
        return "empty_climatology_cache"
    if not cache.get("by_date"):
        return "empty_bucket_transition_prior_hourly_cache"
    return None


def compare_record(model, record, market_id, variants):
    from weather.backtesting.replay import parse_built_at, record_target_date

    if not record.get("sources"):
        return None
    target = record_target_date(record)
    if target is None or not (FIRST_DATE <= target <= LAST_DATE):
        raise Refused(f"refused: record target {target} outside {FIRST_DATE}..{LAST_DATE}")
    model.set_target_date(target)
    now = parse_built_at(record)
    sources = record["sources"]
    row = {
        "kind": "snapshot",
        "snapshot_id": str(record.get("snapshot_id")),
        "market_id": market_id,
        "target_date": target.isoformat(),
        "hour": now.hour if now else None,
        "nbm_present": bool((sources.get("nbm_probabilistic_tmax") or {}).get("data")),
        "variants": {},
    }
    if "t1_nws_hourly_only" in variants:
        row["t1_nws_filled"] = nws_hourly_day_max(model, sources) is not None
    try:
        base, payload = _run(model, sources, now)
    except Exception as exc:  # error row, the run continues
        row["error"] = f"base: {type(exc).__name__}: {exc}"
        return row
    row["active_model_kind"] = payload.get("active_model_kind")
    for variant in variants:
        try:
            with variant_context(model, variant, sources, now) as srcs:
                alt, _ = _run(model, srcs, now)
            row["variants"][variant] = _delta(alt, base)
        except Exception as exc:
            row["variants"][variant] = {"error": f"{type(exc).__name__}: {exc}"}
    return row


def summarize(rows, variants):
    snaps = [r for r in rows if r.get("kind") == "snapshot"]
    ok = [r for r in snaps if "error" not in r]
    out = {
        "snapshots": len(snaps),
        "snapshot_base_errors": len(snaps) - len(ok),
        "folder_errors": sum(1 for r in rows if r.get("kind") == "folder_error"),
        "nbm_present_snapshots": sum(1 for r in ok if r.get("nbm_present")),
        "model_kinds": sorted({str(r.get("active_model_kind")) for r in ok}),
        "variants": {},
    }
    if "t1_nws_hourly_only" in variants:
        out["t1_nws_filled"] = sum(1 for r in ok if r.get("t1_nws_filled"))
        out["t1_fallback_to_base"] = sum(1 for r in ok if r.get("t1_nws_filled") is False)
    for variant in variants:
        per_block = {}
        for label, start, end in HOUR_BLOCKS + (("all", 0, 23),):
            group = [r for r in ok if r["hour"] is not None and start <= r["hour"] <= end]
            vals = [r["variants"][variant] for r in group if "tv" in r["variants"].get(variant, {})]
            n = len(vals)
            per_block[label] = {
                "snapshots": n,
                "errors": len(group) - n,
                "changed_fraction": (sum(v["tv"] > CHANGE_TOL for v in vals) / n) if n else None,
                "mean_tv": (sum(v["tv"] for v in vals) / n) if n else None,
                "max_tv": max((v["tv"] for v in vals), default=None),
                "mean_max_bucket": (sum(v["max_bucket"] for v in vals) / n) if n else None,
                "max_max_bucket": max((v["max_bucket"] for v in vals), default=None),
            }
        out["variants"][variant] = per_block
    return out


def select_folders(snapshots_root, market=None, max_folders=None):
    from weather.backtesting.settled_days import folder_market_id
    from weather.market.market_config import date_from_event_slug

    selected = []
    for folder in sorted(p for p in Path(snapshots_root).iterdir() if p.is_dir()):
        market_id = folder_market_id(folder)
        target = date_from_event_slug(folder.name)
        if market_id is None or target is None or not (FIRST_DATE <= target <= LAST_DATE):
            continue
        if market is not None and market_id != market:
            continue
        selected.append((folder, market_id))
    if max_folders is not None:
        selected = selected[: max(0, int(max_folders))]
    return selected


# --- output file (append-only, resumable) ------------------------------------

def _header(variants):
    return {"kind": "header", "schema": SCHEMA, "variants": list(variants)}


def open_out(out, variants):
    """Return (handle, prior_rows, done_folders); refuse a mismatched file."""
    header = _header(variants)
    prior, done = [], {}
    if out.exists() and out.stat().st_size > 0:
        lines = out.read_text(encoding="utf-8").splitlines()
        try:
            first = json.loads(lines[0])
        except (IndexError, json.JSONDecodeError):
            raise Refused(f"refused: {out} has no readable header; not a resumable lever5 file")
        if first != header:
            raise Refused(f"refused: {out} header {first} does not match {header}")
        parsed = []
        for line in lines[1:]:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a killed run
        for row in parsed:
            if row.get("kind") == "folder_done":
                done[row["folder"]] = row["attempt"]
        prior = [r for r in parsed if r.get("folder") in done and r.get("attempt") == done[r["folder"]]]
        handle = out.open("a", encoding="utf-8", newline="\n")
        if lines and not out.read_bytes().endswith(b"\n"):
            handle.write("\n")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        handle = out.open("w", encoding="utf-8", newline="\n")
        handle.write(json.dumps(header, sort_keys=True) + "\n")
    return handle, prior, set(done)


def write_summary(path, summary):
    if path is None:
        return
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run(folders, out_path, variants, *, summary_path=None, budget_minutes=None,
        model_factory=None, roots=None, clock=time.monotonic, emit=print):
    from weather.backtesting.replay import index_records_by_snapshot, is_reconstructed, load_replay_records

    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel
        model_factory = lambda market_id: TorontoHighTempModel(market_id=market_id)  # noqa: E731
    out = check_out(out_path, allow_existing=True)
    summary_file = check_out(summary_path, allow_existing=True) if summary_path else None
    handle, rows, done = open_out(out, variants)
    attempt = datetime.now(timezone.utc).isoformat()
    models, market_seconds = {}, {}
    started = clock()
    status = {"folders_selected": len(folders), "folders_done_before": 0, "folders_run": 0,
              "folders_skipped_budget": 0}
    roots = roots or root_info()

    def summary():
        return {"schema": SCHEMA, "roots": roots, "status": dict(status),
                "budget_minutes": budget_minutes, **summarize(rows, variants)}

    try:
        for folder, market_id in folders:
            if folder.name in done:
                status["folders_done_before"] += 1
                continue
            spent = market_seconds.get(market_id, 0.0)
            if budget_minutes is not None and spent >= budget_minutes * 60:
                status["folders_skipped_budget"] += 1
                continue
            t0 = clock()
            model = models.setdefault(market_id, model_factory(market_id))
            folder_rows = []
            records = index_records_by_snapshot(load_replay_records(folder))
            first = next(iter(records.values()), None)
            error = None
            if first is not None:
                from weather.backtesting.replay import record_target_date

                target = record_target_date(first)
                if target is not None:
                    model.set_target_date(target)
                error = hgb_error(model) or climatology_error(model)
            if error:
                folder_rows.append({"kind": "folder_error", "error": error})
            else:
                for snapshot_id in sorted(records):
                    record = records[snapshot_id]
                    if is_reconstructed(record):
                        continue
                    row = compare_record(model, record, market_id, variants)
                    if row is not None:
                        folder_rows.append(row)
            seconds = clock() - t0
            market_seconds[market_id] = spent + seconds
            for row in folder_rows:
                row.update({"folder": folder.name, "attempt": attempt})
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            snaps = sum(1 for r in folder_rows if r.get("kind") == "snapshot")
            if not error:  # an errored folder stays not-done, so a resume re-attempts it
                handle.write(json.dumps({"kind": "folder_done", "folder": folder.name,
                                         "attempt": attempt, "market_id": market_id,
                                         "snapshots": snaps, "seconds": round(seconds, 3)},
                                        sort_keys=True) + "\n")
            handle.flush()
            rows.extend(folder_rows)
            status["folders_run"] += 1
            emit(f"TIMING folder={folder.name} snapshots={snaps} seconds={seconds:.1f} "
                 f"cumulative={clock() - started:.1f}")
            write_summary(summary_file, summary())
    finally:
        handle.close()
    result = summary()
    write_summary(summary_file, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--config-root", default=None)
    parser.add_argument("--snapshots-root", default=None,
                        help="default: <data-root>/snapshots")
    parser.add_argument("--market", default=None)
    parser.add_argument("--max-folders", type=int, default=None)
    parser.add_argument("--budget-minutes", type=float, default=None)
    parser.add_argument("--variants", default=",".join(VARIANTS),
                        help=f"default: the 8 stage variants; twins: {','.join(TWIN_VARIANTS)}")
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-out", default=None)
    args = parser.parse_args(argv)
    variants = [v for v in args.variants.split(",") if v]
    unknown = sorted(set(variants) - set(ALL_VARIANTS))
    if unknown:
        print(f"unknown variants: {unknown}", file=sys.stderr)
        return 2
    try:
        roots = configure_roots(args.data_root, args.config_root)
        check_out(args.out, allow_existing=True)
        if args.summary_out:
            check_out(args.summary_out, allow_existing=True)
        snapshots_root = args.snapshots_root or str(Path(args.data_root) / "snapshots")
        folders = select_folders(snapshots_root, market=args.market, max_folders=args.max_folders)
        result = run(folders, args.out, variants, summary_path=args.summary_out,
                     budget_minutes=args.budget_minutes, roots=roots)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({k: result[k] for k in ("roots", "status", "snapshots", "snapshot_base_errors",
                                             "folder_errors")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
