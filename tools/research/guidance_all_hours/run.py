"""Guarded 111h Part 2 driver: control, census, then frozen v2 scoring."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from weather.paths import repo_path
from tools.research.missing_information.extract import finite, sha256
from tools.research.missing_information.run import write_json
from tools.research.morning_guidance.candidate import candidates
from tools.research.morning_guidance.statistics import planning, summarize
from tools.research.guidance_all_hours.features import V2_FIELDS, v2_features

PREREG = "docs/research/guidance-all-hours-preregistration-2026-09-29.md"
PREREG_HASH = "ffc0491c68dc6fecb8294bbb914941d2602bdffaf5c581ca542b2eff1ea8a382"
FREEZE_COMMIT = "ee10a75ac9901b75b8809678561d581fcd70e8c7"
FREEZE_REF = "refs/heads/codex/guidance-all-hours-20260930"
FREEZE_DATE = "2026-09-29"
PARSER_HEAD = "2e17ce0eb"
EXAM_FIRST_DATE = "2026-09-30"
CONTROL_LAST_DATE = "2026-09-19"
CONTROL_INTERVAL = (-0.011525, -0.002373)
TWICE_81A = -0.013344
BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))
STRATA = ("before_20260823", "from_20260823", "pooled")
INPUTS = ("guidance_rows.jsonl.gz", "market_days.jsonl.gz", "manifest.json")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, cwd=repo_path()).stdout


def freeze_gate():
    """Refuse unless the frozen bytes are bound, an ancestor of HEAD and on the remote branch."""
    if sha256(repo_path(PREREG)) != PREREG_HASH:
        raise ValueError("frozen pre-registration bytes changed")
    if hashlib.sha256(git("show", f"{FREEZE_COMMIT}:{PREREG}")).hexdigest() != PREREG_HASH:
        raise ValueError("freeze commit does not bind the pre-registration")
    git("merge-base", "--is-ancestor", FREEZE_COMMIT, "HEAD")
    remote = git("ls-remote", "origin", FREEZE_REF).decode().split()
    if not remote:
        raise ValueError("freeze branch is absent on the remote")
    git("merge-base", "--is-ancestor", FREEZE_COMMIT, remote[0])
    return {"preregistration": PREREG, "preregistration_sha256": PREREG_HASH,
            "freeze_commit": FREEZE_COMMIT, "freeze_ref": FREEZE_REF, "remote_ref_sha": remote[0],
            "head": git("rev-parse", "HEAD").decode().strip(),
            "verified_at_utc": datetime.now(timezone.utc).isoformat()}


def verify_input(root):
    """Verify every file against SHA256SUMS, then COMPLETE status and the pinned parser."""
    sums = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.lstrip("*")] = digest
    if set(sums) != set(INPUTS):
        raise ValueError(f"SHA256SUMS names {sorted(sums)}")
    actual = {name: sha256(root / name) for name in INPUTS}
    if actual != sums:
        raise ValueError("input bytes do not match SHA256SUMS")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "COMPLETE" or not manifest["parser"]["head"].startswith(PARSER_HEAD):
        raise ValueError("extract is not COMPLETE at the pinned parser head; report, do not score")
    return {"input_path": str(root), "sha256": actual, "status": manifest["status"],
            "parser_head": manifest["parser"]["head"], "rows": manifest["row_counts"]["rows"],
            "market_days_admitted": manifest["row_counts"]["market_days_admitted"],
            "started_at_utc": manifest["started_at_utc"], "finished_at_utc": manifest["finished_at_utc"],
            "arguments": manifest["arguments"]}


def load_rows(root):
    rows, excluded = [], Counter()
    with gzip.open(root / "guidance_rows.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["target_date"] >= EXAM_FIRST_DATE:
                excluded[row["target_date"]] += 1   # replay-exam panel: counted, never scored
                continue
            if row["unit"] != "F":
                raise ValueError("111h population is the US settlement markets only")
            rows.append(row)
    return rows, {"rows_with_target_on_or_after_2026_09_30": sum(excluded.values()),
                  "by_target_date": dict(excluded)}


def block(hour):
    return next(name for name, low, high in BLOCKS if low <= hour <= high)


def score_row(row, features):
    bands = [{k: b[k] for k in ("kind", "low", "high")} for b in row["bands"]]   # labels are display only
    c1, c2, reason = candidates(bands, row["p_served"], features)
    p, market = np.asarray(row["p_served"], float), np.asarray(row["p_market_yes"], float)
    y = np.eye(len(p))[row["winner"]]
    out = {"date": row["target_date"], "market": row["market"], "stratum": row["stratum"],
           "block": block(row["local_hour"]), "reason": reason, "eligible": int(reason == "eligible"),
           "served": float(np.mean((p - y) ** 2)), "market_loss": float(np.mean((market - y) ** 2))}
    for name, candidate in (("C1", c1), ("C2", c2)):
        out[name] = float(np.mean((candidate - y) ** 2))
        out[name + "_delta"] = out[name] - out["served"]
        out[name + "_changed"] = int(not np.array_equal(candidate, p))
    out["C2_minus_C1"] = out["C2"] - out["C1"]
    return out


COLUMNS = ["served", "market_loss", "C1", "C2", "C1_delta", "C2_delta",
           "C1_changed", "C2_changed", "eligible", "C2_minus_C1"]


def table(f, label, with_planning=True):
    """81a's per-table summary, unchanged: equal snapshots within day, equal days."""
    cells = f.groupby(["date", "market"])[COLUMNS].mean().reset_index()
    result = {**label, "snapshots": len(f), "market_days": len(cells),
              "date_clusters": cells.date.nunique(), "market_clusters": cells.market.nunique(),
              "reason_counts": dict(Counter(f.reason)),
              "served": summarize(cells, "served"), "market": summarize(cells, "market_loss"),
              "C2_minus_C1": summarize(cells, "C2_minus_C1")}
    for name in ("C1", "C2"):
        changed = f[f[name + "_changed"] == 1]
        result[name] = {"brier": summarize(cells, name), "delta": summarize(cells, name + "_delta"),
                        "ratio_to_market": summarize(cells, name, "market_loss", effect=-.1),
                        "changed_snapshots": int(f[name + "_changed"].sum()),
                        "changed_snapshot_share": float(f[name + "_changed"].mean()),
                        "changed_date_clusters": changed.date.nunique(),
                        "changed_market_clusters": changed.market.nunique(),
                        "changed_market_days": len(changed[["date", "market"]].drop_duplicates()),
                        "changed_market_day_share": summarize(cells, name + "_changed", effect=.1)}
        if with_planning:
            result[name]["planning"] = planning(cells, name + "_delta", FREEZE_DATE)
    return result


def morning_control_rows(rows):
    return [r for r in rows if 6 <= r["local_hour"] <= 9 and r["target_date"] <= CONTROL_LAST_DATE]


def control(rows):
    """81a's exact rule on captured (v1) features, 06-09 local, targets through 09-19."""
    frame = pd.DataFrame([score_row(r, r.get("features") or {}) for r in morning_control_rows(rows)])
    tables = [table(frame if s == "pooled" else frame[frame.stratum == s], {"stratum": s}, False)
              for s in STRATA]
    pooled = tables[-1]["C1"]["delta"]["estimate"]
    passed = CONTROL_INTERVAL[0] <= pooled <= CONTROL_INTERVAL[1]
    return {"rule": "C1 on captured features, local 06-09, target 2026-08-01..2026-09-19, pooled US",
            "reference_interval_81a": CONTROL_INTERVAL, "pooled_C1_minus_served": pooled,
            "verdict": "PASS" if passed else "FAIL",
            "label_for_v2_tables": None if passed else "stack not reconciled with 81a",
            "tables": tables}


def census(rows):
    """EF 10k: 81a-eligible captured NBM sets whose manifest token says 'minimum'."""
    population = morning_control_rows(rows)
    eligible = []
    for r in population:
        f = r.get("features") or {}
        q = [finite(f.get(k)) for k in V2_FIELDS]
        floors = [finite(f.get(k)) for k in ("guidance_physical_floor", "high_so_far", "trusted_current_max")]
        if (all(v is not None for v in q) and q[6] > 0 and all(a <= b for a, b in zip(q[:5], q[1:5]))
                and f.get("nbm_prob_tmax_physical_valid_flag") == 1
                and f.get("nbm_prob_tmax_impossible_flag") != 1
                and any(v is not None for v in floors)):
            eligible.append(r)

    def support(group):
        return {"rows": len(group), "share_of_eligible": len(group) / len(eligible) if eligible else None,
                "market_days": len({(r["market"], r["target_date"]) for r in group}),
                "dates": sorted({r["target_date"] for r in group}),
                "markets": dict(Counter(r["market"] for r in group))}
    by_period = {period: support([r for r in eligible if r["v1_period"] == period])
                 for period in ("minimum", "maximum", "unknown", "no_manifest_row")}
    candidate_eligible = sum(score_row(r, r.get("features") or {})["eligible"] for r in eligible)
    return {"population_rows": len(population), "eligible_rows": len(eligible),
            "eligible_rows_with_candidate_reason_eligible": candidate_eligible,
            "wrong_period_minimum": by_period["minimum"], "by_v1_period": by_period,
            "unavailable_note": "rows with v1_period unknown or no_manifest_row are unavailable, not zero"}


def score(rows):
    frame = pd.DataFrame([score_row(r, v2_features(r)) for r in rows])
    tables = []
    for name, low, high in (*BLOCKS, ("all_hours", 0, 23)):
        region = frame if name == "all_hours" else frame[frame.block == name]
        for stratum in STRATA:
            f = region if stratum == "pooled" else region[region.stratum == stratum]
            t = table(f, {"block": name, "stratum": stratum})
            tables.append(t)
            print(f"{name}/{stratum}: C1={t['C1']['delta']['estimate']:.7f} "
                  f"C2={t['C2']['delta']['estimate']:.7f}", flush=True)
    return tables, frame


def decision(tables, control_result):
    get = {(t["block"], t["stratum"]): t for t in tables}
    out = {"label": control_result["label_for_v2_tables"], "line": TWICE_81A}
    for c in ("C1", "C2"):
        d = get[("all_hours", "pooled")][c]["delta"]
        strata = {s: get[("all_hours", s)][c]["delta"]["estimate"] for s in STRATA[:2]}
        out[c] = {"estimate": d["estimate"], "ci95": d["ci95"],
                  "reaches_twice_descriptive": d["estimate"] <= TWICE_81A,
                  "reaches_twice_interval": d["ci95"][1] <= TWICE_81A,
                  "strata_estimates": strata,
                  "strata_opposite_sign": (strata[STRATA[0]] < 0) != (strata[STRATA[1]] < 0)}
    falsifier1 = {}
    for b in ("13-16", "17-23"):
        d = get[(b, "pooled")]["C1"]["delta"]
        falsified = d["estimate"] >= 0 or d["ci95"][0] <= 0 <= d["ci95"][1]
        falsifier1[b] = {"estimate": d["estimate"], "ci95": d["ci95"], "afternoon_route_falsified": falsified}
    out["falsifier_1_stale_07z_adds_nothing"] = falsifier1
    out["falsifier_2_pooled_near_81a"] = {"estimate": out["C1"]["estimate"],
                                          "all_hours_route_closed": out["C1"]["estimate"] > TWICE_81A}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["control", "census", "score"])
    parser.add_argument("--input", type=Path, required=True, help="absolute extract directory")
    parser.add_argument("--output", type=Path, required=True, help="absolute create-only directory")
    parser.add_argument("--control", type=Path, help="control.json from the control stage (score only)")
    args = parser.parse_args(argv)
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("use scripts/ops/workstation_heavy.ps1")
    for path in (args.input, args.output):
        if not path.is_absolute() or path.resolve().is_relative_to(repo_path().resolve()):
            parser.error("--input/--output must be absolute and outside the repository")
    if args.stage == "score" and args.control is None:
        parser.error("--control required: the positive control is reported before any v2 table")
    header = {"mission": "2026-09-111h", "part": 2, "stage": args.stage,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "freeze": freeze_gate(),
              "source_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
              "dependency_sha256": {name: sha256(repo_path(name)) for name in (
                  "tools/research/morning_guidance/candidate.py",
                  "tools/research/morning_guidance/statistics.py",
                  "tools/research/missing_information/methods.py",
                  "tools/research/missing_information/extract.py")},
              "input": verify_input(args.input)}
    args.output.mkdir(parents=True, exist_ok=False)
    rows, exam = load_rows(args.input)
    header["exam_panel_exclusion"] = exam
    header["rows_loaded"] = len(rows)
    write_json(args.output / "run_header.json", header)
    if args.stage == "control":
        write_json(args.output / "control.json", {"header": header, **control(rows)})
    elif args.stage == "census":
        write_json(args.output / "census.json", {"header": header, **census(rows)})
    else:
        control_result = json.loads(args.control.read_text(encoding="utf-8"))
        if control_result["header"]["freeze"]["preregistration_sha256"] != PREREG_HASH:
            raise ValueError("control output is not bound to this pre-registration")
        header["control_sha256"] = sha256(args.control)
        header["first_score_at_utc"] = datetime.now(timezone.utc).isoformat()
        tables, frame = score(rows)
        result = {"header": header, "tables": tables, "decision": decision(tables, control_result)}
        write_json(args.output / "development.json", result)
        write_json(args.output / "row_deltas.json",
                   {"header": header, "rows": frame.to_dict(orient="records")})
        print(json.dumps(result["decision"], indent=1), flush=True)


if __name__ == "__main__":
    main()
