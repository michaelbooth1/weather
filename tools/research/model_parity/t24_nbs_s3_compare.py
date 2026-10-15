"""T24 (spare): compare T24's independent S3 re-measurement of blend_nbstx with the NBS MANIFEST basis.

Development only; no scoring. Reads C:\\swarm\\out\\t24\\s3_remeasure.jsonl and s3_fullcycle.jsonl
(written by t24_nbs_s3_remeasure.py) and C:\\swarm\\data\\nbs\\MANIFEST.json; writes s3_compare.json.
"""
import json
from pathlib import Path

import pandas as pd

OUT = Path(r"C:\swarm\out\t24")
man = json.loads(Path(r"C:\swarm\data\nbs\MANIFEST.json").read_text(encoding="utf-8"))
mo = {o["key"]: o for o in man["objects"]}
rows, sib = [], []
for line in (OUT / "s3_remeasure.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    k = r["nbs_key"]
    cyc = pd.Timestamp(r["date"], tz="UTC") + pd.Timedelta(hours=r["cycle"])
    lst = {x["key"].split("/")[-1].split(".")[0]: x for x in r["text_listing"]}
    nbs_l = lst.get("blend_nbstx")
    hd = r["head"]
    m = mo.get(k, {})
    lm_head = pd.Timestamp(hd["last_modified"]) if hd.get("status") == 200 else pd.NaT
    lm_man = pd.Timestamp(m["s3_last_modified"]) if m.get("s3_last_modified") else pd.NaT
    lm_list = pd.Timestamp(nbs_l["lm"]) if nbs_l else pd.NaT
    others = [pd.Timestamp(v["lm"]) for kk, v in lst.items() if kk != "blend_nbstx"]
    rows.append({
        "key": k, "date": r["date"], "cycle": r["cycle"], "cycle_utc": cyc,
        "lm_head": lm_head, "lm_list": lm_list, "lm_manifest": lm_man,
        "etag_head": hd.get("etag"), "etag_manifest": m.get("etag"),
        "bytes_head": hd.get("bytes"), "bytes_manifest": m.get("bytes"),
        "multipart_etag": "-" in (hd.get("etag") or ""),
        "n_text_products": len(lst),
        "sib_min_lm": min(others) if others else pd.NaT, "sib_max_lm": max(others) if others else pd.NaT,
    })
d = pd.DataFrame(rows)
d["lag_min"] = (d.lm_head - d.cycle_utc).dt.total_seconds() / 60
d["nbs_minus_sib_min_s"] = (d.lm_head - d.sib_min_lm).dt.total_seconds()
d["sib_spread_s"] = (d.sib_max_lm - d.sib_min_lm).dt.total_seconds()
med = d.groupby("cycle").lag_min.median()
d["excess_min"] = d.lag_min - d.cycle.map(med)
late = d[d.excess_min > 30].sort_values("cycle_utc")

full = {}
fp = OUT / "s3_fullcycle.jsonl"
if fp.exists():
    for line in fp.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        full[(r["date"], r["cycle"])] = r

late_rows = []
for _, x in late.iterrows():
    f = full.get((x.date, int(x.cycle)))
    core = f["by_dir"].get("core") if f else None
    late_rows.append({"key": x.key, "lag_min": round(x.lag_min, 1), "excess_over_cycle_median_min": round(x.excess_min, 1),
                      "sibling_text_lm_min": str(x.sib_min_lm), "sibling_text_lm_max": str(x.sib_max_lm),
                      "core_lm_min": core["min_lm"] if core else None, "core_lm_max": core["max_lm"] if core else None})

full_summary = []
for (ds, hh), f in sorted(full.items()):
    cyc = pd.Timestamp(ds, tz="UTC") + pd.Timedelta(hours=hh)
    o = {"date": ds, "cycle": hh}
    for sub in ("core", "qmd", "text"):
        b = f["by_dir"].get(sub)
        if b:
            o[f"{sub}_first_lag_min"] = round((pd.Timestamp(b["min_lm"]) - cyc).total_seconds() / 60, 1)
            o[f"{sub}_last_lag_min"] = round((pd.Timestamp(b["max_lm"]) - cyc).total_seconds() / 60, 1)
            o[f"{sub}_n"] = b["n"]
    full_summary.append(o)

res = {
    "n_objects": len(d),
    "head_status_200": int((d.lm_head.notna()).sum()),
    "head_eq_manifest": int((d.lm_head == d.lm_manifest).sum()),
    "list_eq_head": int((d.lm_list == d.lm_head).sum()),
    "etag_eq_manifest": int((d.etag_head == d.etag_manifest).sum()),
    "bytes_eq_manifest": int((d.bytes_head == d.bytes_manifest).sum()),
    "multipart_etags": int(d.multipart_etag.sum()),
    "lag_min_quantiles": d.lag_min.quantile([0, .01, .05, .5, .95, .99, 1]).round(1).to_dict(),
    "negative_or_under_30min": int((d.lag_min < 30).sum()),
    "median_lag_by_cycle": med.round(1).to_dict(),
    "nbs_minus_first_sibling_text_s_quantiles": d.nbs_minus_sib_min_s.quantile([0, .05, .5, .95, 1]).to_dict(),
    "text_set_spread_s_quantiles": d.sib_spread_s.quantile([0, .5, .95, 1]).to_dict(),
    "n_late_gt30min_over_cycle_median": len(late),
    "late_objects": late_rows,
    "fullcycle_lags": full_summary,
}
(OUT / "s3_compare.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in res.items() if k not in ("late_objects", "fullcycle_lags")}, indent=1, default=str))
print("late objects:")
for x in late_rows:
    print(x)
print("full cycle:")
for x in full_summary:
    print(x)
