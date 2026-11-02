"""L50 outcome-free coverage count of NBM / L6 input artifacts on the WS closed-market-day archive.

Reads ONLY: forecast_payloads_long (input metadata columns), features_long (null-ness of high_so_far,
cutoff_hour), and WS CAS file existence. Never opens replay_inputs (mixed JSON incl. recorded_distribution
and station surfaces), snapshots_long, clob_features_long, components_long, forecasts_long, labels, settlement.
"""
import sys, json, re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pyarrow.parquet as pq

ARCH = Path(sys.argv[1]); CAS = Path(sys.argv[2]); OUT = Path(sys.argv[3])
FIRST, LAST = date(2026, 6, 3), date(2026, 7, 30)
FORBID = {"winner","settlement_high","settlement_bucket","settlement_source","is_winner","p_market_yes",
          "best_bid","best_ask","market_mid","promotion_countable","label_source","settlement","market_yes",
          "market_no","recorded_distribution","sources"}
PAY_COLS = ["snapshot_id","captured_at_utc","source","status","payload_hash","payload_bytes","source_url",
            "raw_payload_path","fetched_at"]
FEAT_COLS = ["snapshot_id","cutoff_hour","high_so_far"]
URL_RE = re.compile(r"blend\.(\d{8})/(\d{2})/text/blend_nbptx")

def ts(v):
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception: return None

def read(path, cols):
    names = set(pq.read_schema(path).names)
    bad = names & FORBID - ({"sources"} if "replay" in str(path) else set())
    if bad & set(cols): raise SystemExit(f"STOP: forbidden column requested {bad} in {path}")
    return pq.ParquetFile(path).read(columns=[c for c in cols if c in names]).to_pylist(), names

folders = {}
for d in sorted(ARCH.glob("local_date=*")):
    day = date.fromisoformat(d.name.split("=")[1])
    for m in d.glob("market_id=*"):
        for e in m.glob("event_slug=*"):
            folders[(day, m.name.split("=")[1])] = e

schemas = Counter(); sources = Counter()
nbm_by_folder = {}
for (day, mk), e in folders.items():
    p = e / "artifact_family=forecast_payloads_long" / "data.parquet"
    if not p.is_file(): nbm_by_folder[(day, mk)] = None; continue
    rows, names = read(p, PAY_COLS); schemas[tuple(sorted(names))] += 1
    for r in rows: sources[r["source"]] += 1
    nbm_by_folder[(day, mk)] = rows

blob_cache = {}
def blob_present(h):
    if not h: return False
    if h not in blob_cache:
        blob_cache[h] = (CAS / "sha256" / h[:2] / f"{h}.blob").is_file()
    return blob_cache[h]

table = []
markets = sorted({mk for _, mk in folders})
d = FIRST
while d <= LAST:
    for mk in markets:
        e = folders.get((d, mk))
        row = {"date": d.isoformat(), "market": mk, "folder": e is not None}
        if e is None: table.append(row); continue
        pay = nbm_by_folder.get((d, mk)) or []
        snaps = {}
        for r in pay:
            snaps.setdefault(r["snapshot_id"], ts(r["captured_at_utc"]))
        fp = e / "artifact_family=features_long" / "data.parquet"
        feat = read(fp, FEAT_COLS)[0] if fp.is_file() else []
        for r in feat: snaps.setdefault(r["snapshot_id"], None)
        # NBM rows from D-1, D, D+1 folders (bulletins are market-invariant)
        bulletins = {}
        for k in (-1, 0, 1):
            for r in (nbm_by_folder.get((d + timedelta(days=k), mk)) or []):
                if r["source"] != "nbm_probabilistic_tmax": continue
                m = URL_RE.search(str(r.get("source_url") or ""))
                if not m: continue
                cyc = datetime.strptime(m.group(1)+m.group(2), "%Y%m%d%H").replace(tzinfo=timezone.utc)
                seen = ts(r.get("fetched_at")) or ts(r.get("captured_at_utc"))
                h = r.get("payload_hash") or ""
                b = bulletins.setdefault(cyc, {"seen": seen, "hashes": set(), "ok": False})
                if seen and (b["seen"] is None or seen < b["seen"]): b["seen"] = seen
                if h: b["hashes"].add(h)
                if str(r.get("status")) in ("ok", "success", "fresh", "cached", "True"): b["ok"] = True
        def holds_max(cyc):
            cd = cyc.date()
            return cd == d - timedelta(days=1) or (cd == d and cyc.hour in (0, 1, 7))
        nbm_rows = [r for r in pay if r["source"] == "nbm_probabilistic_tmax"]
        n_struct = n_bytes = 0
        hours = Counter()
        for sid, cap in snaps.items():
            if cap is None: continue
            cands = [c for c, b in bulletins.items() if holds_max(c) and b["seen"] and b["seen"] <= cap
                     and cap - c <= timedelta(hours=30)]
            if cands: n_struct += 1
            if any(any(blob_present(h) for h in bulletins[c]["hashes"]) for c in cands): n_bytes += 1
        row.update({
            "snapshots": len(snaps),
            "nbm_rows": len(nbm_rows),
            "nbm_status": dict(Counter(str(r["status"]) for r in nbm_rows)),
            "nbm_distinct_hashes": len({r["payload_hash"] for r in nbm_rows if r["payload_hash"]}),
            "nbm_url_parsed": sum(1 for r in nbm_rows if URL_RE.search(str(r.get("source_url") or ""))),
            "snap_v2_struct": n_struct,
            "snap_v2_bytes_on_ws": n_bytes,
            "feat_rows": len(feat),
            "feat_high_so_far_nonnull": sum(1 for r in feat if r.get("high_so_far") is not None),
        })
        table.append(row)
    d += timedelta(days=1)

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "coverage_rows.json").write_text(json.dumps(table, indent=1, default=str))
(OUT / "meta.json").write_text(json.dumps({
    "archive_dates": [min(k[0] for k in folders).isoformat(), max(k[0] for k in folders).isoformat()],
    "folders": len(folders), "markets": markets,
    "payload_schemas": [list(s) + [n] for s, n in schemas.items()],
    "sources_all_folders": dict(sources), "cas_blobs_checked": len(blob_cache),
    "cas_blobs_present": sum(blob_cache.values())}, indent=1))
print("done", len(table))
