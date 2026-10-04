"""T19 tail lens: tables from C:\\swarm\\out\\t19\\t19_lens.json (development only; no scoring here)."""
from __future__ import annotations

import json
import re
from pathlib import Path

OUT = Path(r"C:\swarm\out\t19")
FROM, BEFORE = "from_20260823", "before_20260823"
REG = Path(r"C:\swarm\registry.jsonl")

MANUAL = {
    "t1_decided_band/t1_r2lag60_decided_band": "t1-r2lag60",
    "t2_s60/t2_r1_nowcast": "t2-r1s60",
    "t3_sens/t3_r3s_floor_plus_rise_lag60": "t3-r3s",
    "refute-stat-t3/cand_r3s": "t3-r3s",
    "t4_diag/t4_d1_r1_lag30": "t4-d1", "t4_diag/t4_d1_r3_lag30": "t4-d1",
    "t13_s60/t13_r1_served_nbr_runmax_tilt": "t13-r1s60",
    "ladder_parity/ladder_r0": "ladder-r0", "ladder_parity/ladder_r1": "ladder-r1",
    "ladder_parity/ladder_r1b": "ladder-r1b", "ladder_parity/ladder_r2": "ladder-r2",
    "ladder_parity/ladder_r2b": "ladder-r2b", "ladder_parity/mg1_c1_alone": "r-t5-inc-c1",
    "t9_extra_pairs/t9_rebuilt_r-t5-inc-c1": "r-t5-inc-c1",
    "d_defect_evening_stage/d_defect_r1": "d-defect-r1", "d_defect_evening_stage/d_defect_r2": "d-defect-r2",
    "d_defect_evening_stage/d_defect_d1": "d-defect-d1",
    "t17_info_arrival/t17_r1_metar_fast_floor": "t17-r1",
    "t17_info_arrival/t17_c0_served_floor_control": "t17-c0",
    "t18_emos/t18_r1_emos": "t18-r1", "t18_controls/t18_c0_nosource": "t18-c0",
    "t18_controls/t18_c1_rung_x_v2": "t18-c1", "t18_controls/t18_r1s_sources_lag60": "t18-r1s",
    "t18_emos/t18_c0_nosource": "t18-c0",
}


def reg_ids():
    ids = {}
    for line in REG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            ids[d["id"]] = d
    return ids


def map_id(key, ids):
    if key in MANUAL:
        return MANUAL[key]
    stem = key.split("/", 1)[1]
    m = re.match(r"^(t\d+)_(?:t\d+_)?([rcd]\d+)((?:s\d*|lag\d+)?)", stem)
    if m:
        for rid in (f"{m.group(1)}-{m.group(2)}{m.group(3)}", f"{m.group(1)}-{m.group(2)}"):
            if rid in ids:
                return rid
    return None


def kind(rid, ids):
    if rid is None:
        return "unregistered"
    t = ids[rid]["text"].upper()
    if "CONTROL" in t[:200]:
        return "control"
    if "DIAGNOSTIC" in t[:200] or "SENSITIVITY" in t[:200] or rid.endswith(("s60", "lag60", "r1s", "r3s")):
        return "diag/sens"
    return "candidate"


def f(x, n=4):
    return "-" if x is None else f"{x:+.{n}f}"


def pct(iv):
    if not isinstance(iv, dict):
        return "-"
    e, (lo, hi) = iv["estimate"], iv["ci95"]
    return f"{100*e:+.1f}% [{100*lo:+.1f}, {100*hi:+.1f}]"


def main():
    L = json.loads((OUT / "t19_lens.json").read_text(encoding="utf-8"))
    ids = reg_ids()
    rows = []
    for key, r in L["candidates"].items():
        if "error" in r:
            rows.append((key, None, r))
            continue
        rows.append((key, map_id(key, ids), r))
    covered = {rid for _, rid, _ in rows if rid}
    missing = [i for i in ids if i not in covered]
    lines = []
    for grp in ("17-23", "00-16", "all", "00-05", "06-09", "10-12", "13-16"):
        lines.append(f"\n### Tail lens, {grp}, from stratum (before-stratum share beside)\n")
        lines.append("| registry id | kind | captured key | all-row class | all-row from est | tail share removed (from) [95%] |"
                     " tail share before | markets tail improved/harmed (from) | tail & all-row same sign (markets) |"
                     " tail part of all-row gain | dup of |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for key, rid, r in sorted(rows, key=lambda x: (x[1] or "zz", x[0])):
            if "error" in r:
                continue
            tf = r["tail"].get(f"{grp}|{FROM}", {})
            tb = r["tail"].get(f"{grp}|{BEFORE}", {})
            ar = r["all_row"].get(f"{grp}|{FROM}")
            if not ar or "share_of_tail_excess_removed" not in tf:
                continue
            pm_t = tf["per_market_tail_share_removed"]
            pm_a = ar["per_market_delta"]
            agree = sum(1 for m in pm_t if m in pm_a and ((pm_t[m] > 0) == (pm_a[m] < 0)) and pm_a[m] != 0 and pm_t[m] != 0)
            part = tf.get("tail_part_of_all_row_improvement")
            lines.append(f"| {rid or '?'} | {kind(rid, ids)} | {key} | {r['classes'][grp]} | {f(ar['est'])} |"
                         f" {pct(tf['share_of_tail_excess_removed'])} |"
                         f" {pct(tb.get('share_of_tail_excess_removed')) if tb else '-'} |"
                         f" {tf['markets_tail_improved']}/{tf['markets_tail_harmed']} of {tf['markets_n']} |"
                         f" {agree}/{tf['markets_n']} | {'-' if part is None else f'{part:.2f}'} |"
                         f" {r.get('duplicate_of') or ''} |")
    txt = "\n".join(lines)
    (OUT / "t19_tables.md").write_text(txt, encoding="utf-8")
    (OUT / "t19_coverage.json").write_text(json.dumps({
        "registry_count": len(ids), "covered_ids": sorted(covered), "not_captured": missing,
        "unmapped_keys": [k for k, rid, _ in rows if rid is None],
        "errors": {k: r["error"] for k, _, r in rows if "error" in r}}, indent=1), encoding="utf-8")
    print("covered", len(covered), "of", len(ids), "missing", missing)


if __name__ == "__main__":
    main()
