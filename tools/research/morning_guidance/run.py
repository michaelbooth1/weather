"""Guarded offline mission driver; coverage never computes a candidate score."""
from __future__ import annotations

from weather.projection_io import projection_source

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pandas as pd

from weather.paths import repo_path
from tools.research.missing_information.extract import finite, read_csv, sha256
from tools.research.missing_information.run import scratch_path, write_json

SNAPSHOT_HASH = "249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e"
PLAN79_HASH = "024dbac70c636e42c4f514d66d79fb955c75362c6534892954c05d0bc9e33a81"
FIELDS = [f"nbm_prob_tmax_p{p}" for p in (10, 25, 50, 75, 90)] + [
    "nbm_prob_tmax_mean", "nbm_prob_tmax_stddev"]
PREREG = "docs/research/morning-guidance-candidate-preregistration-2026-09-21.md"
PREREG_HASH = "d9211fc79d2555bf90f87a42b8d02635cf0c5aeac23390bd1441e398777edc79"
FREEZE_COMMIT = "e404f7fdc56fa4e780fd2a829054751ac15b1df6"


def freeze_gate(receipt_path):
    if sha256(repo_path(PREREG)) != PREREG_HASH:
        raise ValueError("frozen pre-registration bytes changed")
    receipt = json.loads(receipt_path.read_text())
    if (receipt["remote_sha"] != FREEZE_COMMIT or receipt["preregistration_sha256"] != PREREG_HASH
            or receipt["ref"] != "refs/heads/codex/morning-guidance-candidate-20260921"):
        raise ValueError("pre-score push receipt mismatch")
    published = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:{PREREG}"],
                               check=True, capture_output=True).stdout
    import hashlib
    if hashlib.sha256(published).hexdigest() != PREREG_HASH:
        raise ValueError("freeze commit does not bind preregistration")
    subprocess.run(["git", "merge-base", "--is-ancestor", FREEZE_COMMIT, "HEAD"], check=True)
    pushed = datetime.fromisoformat(receipt["verified_at_utc"])
    if pushed >= datetime.now(timezone.utc):
        raise ValueError("push must precede scoring")
    return receipt


def coverage(snapshots, raw):
    # Preserve nonnumeric drop reasons that 79a's numeric-only extraction omitted.
    reasons = {}
    source_hashes = {}
    inventory = Counter()
    for folder in sorted(raw.iterdir()):
        if not folder.is_dir() or not (folder / "settlement.json").exists():
            continue
        inventory.update(p.name for p in folder.iterdir() if p.is_file())
        path = projection_source(folder / "features_long.csv")
        source_hashes[str(path.relative_to(raw))] = sha256(path)
        for r in read_csv(path):
            reasons[(r["event_slug"], r["snapshot_id"])] = r.get("guidance_impossible_features", "")
    # Use folder-to-market mapping already bound by 79a's extraction audit.
    audit = json.loads((snapshots.parent / "extraction_audit.json").read_text())
    folders = {(r.get("market"), r.get("date")): r["folder"] for r in audit if r.get("promotion_countable")}
    rows = []
    patterns = Counter()
    secondary_inputs = []
    with snapshots.open() as stream:
        for line in stream:
            s = json.loads(line)
            f = s["features"]
            missing = [k for k in FIELDS if finite(f.get(k)) is None]
            drop = reasons.get((folders[(s["market"], s["date"])], s["snapshot_id"]), "")
            drop_nbm = "nbm_prob_tmax_" in drop
            complete = not missing and f.get("nbm_prob_tmax_stddev", 0) > 0
            valid = complete and f.get("nbm_prob_tmax_physical_valid_flag") == 1
            status = ("complete_valid" if valid else "floor_dropped_confirmed" if drop_nbm
                      else "source_present_incomplete" if any(k.startswith("nbm_prob_tmax_") for k in f)
                      else "no_feature_evidence")
            floor = f.get("guidance_physical_floor")
            rows.append({"date": s["date"], "market": s["market"], "hour": s["hour"],
                         "stratum": s["stratum"], "complete": int(complete), "valid": int(valid),
                         "status": status, "floor_present": int(floor is not None),
                         "p50": f.get("nbm_prob_tmax_p50"), "floor": floor,
                         "p50_minus_floor": f.get("nbm_prob_tmax_p50", float("nan")) - floor if floor is not None else None})
            if 10 <= s["hour"] < 13:
                patterns[(status, ",".join(missing))] += 1
                if valid:
                    secondary_inputs.append({"date": s["date"], "market": s["market"],
                        "captured_at_local": s["captured_at_local"], "floor": floor,
                        **{k: f[k] for k in FIELDS}})
    frame = pd.DataFrame(rows)
    def table(keys):
        result = []
        for key, g in frame.groupby(keys, observed=True):
            key = key if isinstance(key, tuple) else (key,)
            result.append({**dict(zip(keys, key)), "snapshots": len(g),
                           "date_clusters": g.date.nunique(), "market_clusters": g.market.nunique(),
                           "market_days": len(g[["date", "market"]].drop_duplicates()),
                           "complete": int(g.complete.sum()), "valid": int(g.valid.sum()),
                           "valid_with_guidance_floor": int(((g.valid == 1) & (g.floor_present == 1)).sum()),
                           "fill": float(g.valid.mean()), "status_counts": g.status.value_counts().to_dict()})
        return result
    result = {"inventory": dict(inventory), "secondary_complete_inputs": secondary_inputs,
              "feature_source_sha256": source_hashes,
              "by_hour": table(["stratum", "hour"]), "by_market": table(["stratum", "market"]),
              "by_date": table(["date"]), "afternoon_missing_patterns": [
                  {"status": k[0], "missing": k[1], "snapshots": v} for k, v in patterns.items()]}
    for window, mask in (("morning", frame.hour.between(6, 9)), ("secondary", frame.hour.between(10, 12)),
                         ("all_hours", frame.hour >= 0)):
        result[window] = {}
        for name, region in (("US11", frame.market != "toronto"), ("all12", frame.market.notna())):
            g = frame[mask & region]
            result[window][name] = {"snapshots": len(g), "valid": int(g.valid.sum()),
                "fill": float(g.valid.mean()), "status_counts": g.status.value_counts().to_dict(),
                "date_clusters": g.date.nunique(), "market_clusters": g.market.nunique(),
                "market_days": len(g[["date", "market"]].drop_duplicates()),
                "valid_market_days": len(g[g.valid == 1][["date", "market"]].drop_duplicates()),
                "valid_with_guidance_floor": int(((g.valid == 1) & (g.floor_present == 1)).sum()),
                "complete_p50_minus_floor_range": [g[g.valid == 1].p50_minus_floor.min(), g[g.valid == 1].p50_minus_floor.max()]}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["coverage", "score", "publish"])
    parser.add_argument("--input", type=scratch_path, required=True)
    parser.add_argument("--raw", type=scratch_path)
    parser.add_argument("--output", type=scratch_path, required=True)
    parser.add_argument("--push-receipt", type=scratch_path)
    args = parser.parse_args(argv)
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("use scripts/ops/workstation_heavy.ps1")
    args.output.mkdir(parents=True, exist_ok=False)
    header = {"mission": "2026-09-81a", "stage": args.stage,
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": {p.name: sha256(p) for p in Path(__file__).parent.glob("*.py")},
              "preregistration_sha256": None, "preregistration_status": "P0 precedes preregistration; no score"}
    header["dependency_sha256"] = {name: sha256(repo_path(name)) for name in (
        "tools/research/missing_information/methods.py", "tools/research/missing_information/extract.py",
        "tools/research/missing_information/run.py")}
    if args.stage == "score":
        if args.push_receipt is None:
            parser.error("--push-receipt required before scoring")
        receipt = freeze_gate(args.push_receipt)
        header.update(preregistration_sha256=PREREG_HASH, freeze_commit=FREEZE_COMMIT,
                      preregistration_status="FROZEN_AND_PUSHED_DEVELOPMENT_ONLY", push_receipt=receipt)
    elif repo_path(PREREG).exists():
        header.update(preregistration_sha256=sha256(repo_path(PREREG)), freeze_commit=FREEZE_COMMIT)
    write_json(args.output / "run_header.json", header)
    if args.stage == "publish":
        from tools.research.morning_guidance.publish import publish
        publish(args.input, args.output, header)
        return
    if args.raw is None:
        parser.error("--raw required for coverage/score")
    receipt = json.loads((args.input / "extraction_receipt.json").read_text())
    if receipt["plan_sha256"] != PLAN79_HASH or receipt["output_sha256"] != SNAPSHOT_HASH:
        raise ValueError("unexpected 79a extraction provenance")
    if sha256(args.input / "snapshots.jsonl") != SNAPSHOT_HASH:
        raise ValueError("79a snapshot bytes changed")
    if json.loads((args.raw / "verification.json").read_text()) != receipt["verification"]:
        raise ValueError("raw export receipt mismatch")
    if args.stage == "coverage":
        result = coverage(args.input / "snapshots.jsonl", args.raw)
        write_json(args.output / "coverage.json", {"header": header, **result})
        print(json.dumps({k: result[k] for k in ("morning", "secondary", "all_hours")}), flush=True)
    else:
        from tools.research.morning_guidance.score import score
        result, frame = score(args.input / "snapshots.jsonl", "2026-09-21")
        write_json(args.output / "development.json", {"header": header, **result})
        write_json(args.output / "row_deltas.json", {"header": header, "rows": frame.to_dict(orient="records")})


if __name__ == "__main__":
    main()
