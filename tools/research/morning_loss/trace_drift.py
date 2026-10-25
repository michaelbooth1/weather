"""L5 defect hunt: trace the served overnight cold drift (00 -> 08 h) through the serving stages for ONE
market-day, by re-running the exact recorded code (detached worktree at the record's runtime commit, with
every identity-pinned code and artifact file sha-verified) on two captured snapshots.

Run from the trace worktree with PYTHONPATH=<trace>/src:

    python tools/research/morning_loss/trace_drift.py <replay_inputs.jsonl> <target-date> <HH:MM> [<HH:MM> ...]

For each requested local (host-clock) time it takes the last line captured at or before it, verifies the
identity files, replays it, checks the final vector against ``recorded_distribution``, and prints the
centre (probability-weighted mean degree), the SD and the stage's pipeline metadata, stage by stage.
Development research only (dates <= 2026-09-29), offline.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_regimes as ex  # noqa: E402


def line_at_or_before(path, when):
    size = path.stat().st_size
    with open(path, "rb") as f:
        lo, hi = 0, size
        while hi - lo > 2_000_000:
            mid = (lo + hi) // 2
            pos = ex._next_line_start(f, mid, size)
            if pos is None or pos >= hi:
                hi = mid
                continue
            ts = ex._ts_at(f, pos)
            if ts is not None and ts <= when:
                lo = pos
            else:
                hi = mid
        best, pos = lo, lo
        while pos is not None and pos < size:
            ts = ex._ts_at(f, pos)
            if ts is None or ts > when:
                break
            best = pos
            f.seek(pos)
            f.readline()
            pos = f.tell()
        f.seek(best)
        return json.loads(f.readline())


def moments(dist):
    items = [(float(k), float(v)) for k, v in (dist or {}).items() if v is not None and math.isfinite(float(v))]
    tot = sum(v for _, v in items)
    if tot <= 0:
        return None, None
    c = sum(k * v for k, v in items) / tot
    return c, math.sqrt(max(0.0, sum(v * (k - c) ** 2 for k, v in items) / tot))


def verify(record):
    mi = record["model_identity"]
    bad = [c["path"] for c in mi["code_files"] + mi["artifact_files"]
           if not Path(c["path"]).exists() or hashlib.sha256(Path(c["path"]).read_bytes()).hexdigest() != c["sha256"]]
    return bad


def main(path, target, times):
    from weather.backtesting.replay import replay_distribution, market_id_from_slug
    from weather.model.toronto_model import TorontoHighTempModel

    path = Path(path)
    target = dt.date.fromisoformat(target)
    if target > dt.date(2026, 9, 29):
        raise SystemExit("refused: date after 2026-09-29")
    model = None
    for hhmm in times:
        probe = line_at_or_before(path, dt.datetime.fromisoformat(f"{target}T{hhmm}:59").astimezone())
        rec = probe
        bad = verify(rec)
        if model is None:
            model = TorontoHighTempModel(market_id=market_id_from_slug(rec["event_slug"]))
        dist = replay_distribution(model, rec)
        rd = {int(k): float(v) for k, v in rec["recorded_distribution"].items()}
        l1 = sum(abs(dist.get(k, 0.0) - rd.get(k, 0.0)) for k in set(dist) | set(rd))
        comp = model._last_distribution_components or {}
        print(f"=== {rec['snapshot_id']} captured {rec['captured_at_local']} identity_mismatch={bad} "
              f"replay_vs_recorded_L1={l1:.2e} active_model_kind={comp.get('active_model_kind')}")
        rc, rs = moments(rd)
        print(f"recorded final centre {rc:.3f} sd {rs:.3f}")
        for name, stage in (comp.get("components") or {}).items():
            c, s = moments(stage)
            print(f"  {name:40s} centre {c if c is None else round(c, 3)} sd {s if s is None else round(s, 3)}")
        meta = {k: v for k, v in comp.items() if k != "components"}
        print("  metadata:", json.dumps(meta, default=str)[:4000])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])


def feature_attribution(path, target, early, late):
    """Capture the HGB feature dict and cutoff at two snapshots, then at the late snapshot's cutoff model
    swap one feature at a time back to its early value and report the HGB centre change (one-at-a-time)."""
    import pandas as pd
    from weather.backtesting.replay import replay_distribution, market_id_from_slug
    from weather.model import model_features as mf
    from weather.model.toronto_model import TorontoHighTempModel

    target = dt.date.fromisoformat(target)
    recs = [line_at_or_before(Path(path), dt.datetime.fromisoformat(f"{target}T{t}:59").astimezone())
            for t in (early, late)]
    model = TorontoHighTempModel(market_id=market_id_from_slug(recs[0]["event_slug"]))
    seen = []
    orig = model._evaluate_feature_model_for_cutoff

    def spy(sources, cutoff_hour, hgb_bundle, lr_coefs, now=None):
        feats = model.extract_live_features(sources, cutoff_hour, now=now)
        seen.append({"cutoff": cutoff_hour, "feats": dict(feats), "bundle": hgb_bundle})
        return orig(sources, cutoff_hour, hgb_bundle, lr_coefs, now=now)

    model._evaluate_feature_model_for_cutoff = spy
    for r in recs:
        replay_distribution(model, r)
    e, l = seen[0], seen[-1]
    print(f"cutoff early {e['cutoff']} late {l['cutoff']}; feature columns {len(mf.FEATURE_COLUMNS)}")
    bundle = l["bundle"][str(l["cutoff"])]
    names = list(bundle["feature_names"])

    def centre_for(feats, b=bundle):
        fd = {c: feats.get(c) for c in mf.FEATURE_COLUMNS if c not in {"wind_group", "cloud_group"}}
        for g in b["all_wind_groups"]:
            fd[f"wind_{g}"] = 1.0 if feats["wind_group"] == g else 0.0
        for g in b["all_cloud_groups"]:
            fd[f"cloud_{g}"] = 1.0 if feats["cloud_group"] == g else 0.0
        X = pd.DataFrame([fd], columns=b["feature_names"])
        Xi = b["imputer"].transform(X)
        for col in mf.NATIVE_NAN_FEATURE_COLUMNS:
            if col in b["feature_names"]:
                Xi[0, list(b["feature_names"]).index(col)] = float(fd[col]) if fd[col] is not None else float("nan")
        p = b["model"].predict_proba(Xi)[0]
        cls = b["model"].classes_
        return float(sum(c * q for c, q in zip(cls, p)) / sum(p)), float(max(cls)), float(min(cls))

    base_l, cmax, cmin = centre_for(l["feats"])
    base_e_on_late_model, _, _ = centre_for(e["feats"])
    early_bundle = e["bundle"][str(e["cutoff"])]
    base_e, emax, emin = centre_for(e["feats"], early_bundle)
    print(f"raw HGB mean: early feats/early model {base_e:.3f} (classes {emin:.0f}..{emax:.0f}); "
          f"early feats/late model {base_e_on_late_model:.3f}; late feats/late model {base_l:.3f} "
          f"(classes {cmin:.0f}..{cmax:.0f})")
    rows = []
    for name in names:
        key = name
        if name.startswith("wind_") or name.startswith("cloud_"):
            continue
        ev, lv = e["feats"].get(key), l["feats"].get(key)
        if ev == lv:
            continue
        swapped = dict(l["feats"])
        swapped[key] = ev
        rows.append((centre_for(swapped)[0] - base_l, key, ev, lv))
    for grp in ("wind_group", "cloud_group"):
        if e["feats"][grp] != l["feats"][grp]:
            swapped = dict(l["feats"])
            swapped[grp] = e["feats"][grp]
            rows.append((centre_for(swapped)[0] - base_l, grp, e["feats"][grp], l["feats"][grp]))
    for d, k, ev, lv in sorted(rows, key=lambda r: -abs(r[0])):
        print(f"  restore {k:38s} early {ev!r:>22} late {lv!r:>22}  -> centre change {d:+.3f}")
