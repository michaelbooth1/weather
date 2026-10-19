"""Lever 5 / EXHAUSTION_REGISTER order 16: outcome-blind stage-restoration replay.

For every captured snapshot (``replay_inputs.jsonl``) of a dev target date
2026-07-31..2026-09-29, re-run the CURRENT serving pipeline once as served
("base") and once per variant that restores or re-points one post-processing
stage (or perturbs one input), then report how far the final probability
vector moved. It reads no settlement, no label, no market price and no
``snapshots.jsonl``: only ``sources`` and ``built_at`` from replay_inputs.

Per snapshot and variant it reports, on the native 1-degree bucket vector:
- ``tv``: total-variation distance = sum|delta|/2. It is an exact upper bound
  on the absolute change of ANY band probability for ANY banding, and 0 iff no
  band can change;
- ``max_bucket``: max |delta| over buckets.

Variants (each restores exactly one thing; the base is origin/master serving):
- ``nbm_removed`` / ``nbm_perturbed``: drop the ``nbm_probabilistic_tmax``
  source, or add +10 native degrees to every NBM value. Task-4 check: if the
  served vector reads no NBM, both are 0 on every snapshot.
- ``centering_reenabled``: the 110g afternoon residual-centering artifact as
  fitted, with ``component.enabled`` set back to true.
- ``trusted_current_max_repointed``: ``current_max_trust_features`` validates
  the METAR max-since-07:00 against the observed station high (the lock-in
  anchor) instead of the empty WU history. Restores the Miami validated hard
  floor and the current-max live-signal member. Patched in the distribution
  module only (post-processing); the HGB feature vector is untouched.
- ``wu_residual_repointed``: ``preserve_wu_floor_residual`` reads the observed
  station high instead of the empty WU history high.
- ``metar_live_signal_repointed``: ``learned_metar_live_signal`` reads the
  observed station high instead of the empty WU history high.
- ``bucket_transition_repointed``: the bucket-transition prior reads the
  observed station high at the cutoff instead of the WU cutoff-aligned high
  (its historical cache is prior-year only, by construction).
- ``intraday_tail_repointed``: the intraday tail stage gets the observed
  station bucket instead of ``None``.

Read-only contract (as ``weather.backtesting.lockin_anchor_replay``): refuses
target dates outside 2026-07-31..2026-09-29; writes one new ``--out`` file
outside ``data/``; never overwrites.

  python -m tools.research.model_edge_lever5.run replay --out <new.jsonl>
      [--snapshots-root data/snapshots] [--market M] [--variants a,b,...]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

from weather.backtesting.replay import (
    as_int_distribution,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
)
from weather.backtesting.settled_days import folder_market_id
from weather.market.market_config import date_from_event_slug
from weather.paths import data_path
import weather.model.model_distribution as md

FIRST_DATE = date(2026, 7, 31)
LAST_DATE = date(2026, 9, 29)
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


class Refused(ValueError):
    pass


# --- helpers ---------------------------------------------------------------

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
    if not isinstance(item, dict):
        return out
    data = item.get("data") if isinstance(item.get("data"), dict) else None
    if not data:
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


@contextlib.contextmanager
def variant_context(model, variant, sources, now):
    """Yield the sources to use; patch the model instance for one variant."""
    if variant == "nbm_removed":
        trimmed = {k: v for k, v in sources.items() if k != "nbm_probabilistic_tmax"}
        yield trimmed
        return
    if variant == "nbm_perturbed":
        yield _perturb_nbm(sources, 10.0)
        return
    if variant == "centering_reenabled":
        artifact = deepcopy(getattr(model, "afternoon_residual_centering", None) or {})
        artifact.setdefault("component", {})["enabled"] = True
        with _patched(model, "afternoon_residual_centering", artifact):
            yield sources
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
    result = model.estimate_distribution_result(sources, now=now)
    return as_int_distribution(result.distribution), result.component_payload or {}


def _delta(left, right):
    keys = set(left) | set(right)
    diffs = [abs(left.get(k, 0.0) - right.get(k, 0.0)) for k in keys]
    return {"tv": sum(diffs) / 2.0, "max_bucket": max(diffs, default=0.0)}


def compare_record(model, record, market_id, variants):
    if not record.get("sources"):
        return None
    target = record_target_date(record)
    if target is None or not (FIRST_DATE <= target <= LAST_DATE):
        raise Refused(f"refused: record target {target} outside {FIRST_DATE}..{LAST_DATE}")
    model.set_target_date(target)
    now = parse_built_at(record)
    sources = record["sources"]
    base, payload = _run(model, sources, now)
    row = {
        "snapshot_id": str(record.get("snapshot_id")),
        "market_id": market_id,
        "target_date": target.isoformat(),
        "hour": now.hour if now else None,
        "active_model_kind": payload.get("active_model_kind"),
        "nbm_present": bool((sources.get("nbm_probabilistic_tmax") or {}).get("data")),
        "variants": {},
    }
    for variant in variants:
        try:
            with variant_context(model, variant, sources, now) as srcs:
                alt, _ = _run(model, srcs, now)
            row["variants"][variant] = _delta(alt, base)
        except Exception as exc:  # recorded, never silently dropped
            row["variants"][variant] = {"error": f"{type(exc).__name__}: {exc}"}
    return row


def summarize(rows, variants):
    out = {}
    for variant in variants:
        per_block = {}
        for label, start, end in HOUR_BLOCKS + (("all", 0, 23),):
            vals = [r["variants"][variant] for r in rows
                    if r["hour"] is not None and start <= r["hour"] <= end
                    and "tv" in r["variants"].get(variant, {})]
            errors = sum(1 for r in rows if "error" in r["variants"].get(variant, {})
                         and r["hour"] is not None and start <= r["hour"] <= end)
            n = len(vals)
            per_block[label] = {
                "snapshots": n,
                "errors": errors,
                "changed_fraction": (sum(v["tv"] > CHANGE_TOL for v in vals) / n) if n else None,
                "mean_tv": (sum(v["tv"] for v in vals) / n) if n else None,
                "max_tv": max((v["tv"] for v in vals), default=None),
                "mean_max_bucket": (sum(v["max_bucket"] for v in vals) / n) if n else None,
                "max_max_bucket": max((v["max_bucket"] for v in vals), default=None),
            }
        out[variant] = per_block
    return out


def select_folders(snapshots_root, market=None):
    selected = []
    for folder in sorted(p for p in Path(snapshots_root).iterdir() if p.is_dir()):
        market_id = folder_market_id(folder)
        target = date_from_event_slug(folder.name)
        if market_id is None or target is None or not (FIRST_DATE <= target <= LAST_DATE):
            continue
        if market is not None and market_id != market:
            continue
        selected.append((folder, market_id))
    return selected


def check_out(path):
    out = Path(path).resolve()
    root = Path(data_path()).resolve()
    if out == root or root in out.parents:
        raise Refused(f"refused: --out {out} is inside {root}")
    if out.exists():
        raise Refused(f"refused: --out {out} exists")
    return out


def run(folders, out_path, variants, model_factory=None):
    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel
        model_factory = lambda market_id: TorontoHighTempModel(market_id=market_id)  # noqa: E731
    out = check_out(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    models, rows = {}, []
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        for folder, market_id in folders:
            records = index_records_by_snapshot(load_replay_records(folder))
            model = models.setdefault(market_id, model_factory(market_id))
            for snapshot_id in sorted(records):
                record = records[snapshot_id]
                if is_reconstructed(record):
                    continue
                row = compare_record(model, record, market_id, variants)
                if row is None:
                    continue
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                rows.append(row)
    return {"snapshots": len(rows),
            "market_days": len(folders),
            "nbm_present_snapshots": sum(r["nbm_present"] for r in rows),
            "model_kinds": sorted({str(r["active_model_kind"]) for r in rows}),
            "variants": summarize(rows, variants)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--market", default=None)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary-out", default=None)
    args = parser.parse_args(argv)
    variants = [v for v in args.variants.split(",") if v]
    unknown = sorted(set(variants) - set(VARIANTS))
    if unknown:
        print(f"unknown variants: {unknown}", file=sys.stderr)
        return 2
    try:
        folders = select_folders(args.snapshots_root, market=args.market)
        summary = run(folders, args.out, variants)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.summary_out:
        Path(args.summary_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
