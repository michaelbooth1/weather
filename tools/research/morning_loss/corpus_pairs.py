"""L5 arm B: (market, date, gfs_seamless day-1 high, WU settled high) pairs from L1's full-year PIT corpus union.

Reads the seven season corpora by date, the way ``weather.calibration.r0_full_year.SeasonCorpusUnion`` does:
each manifest's file sha256 is verified, each date must be planned by exactly one corpus (overlap fails
closed), and the union id is sha256 of canonical JSON of the [corpus_id, manifest_sha256] pairs sorted by
(first planned date, corpus id). Labels: ``max_temp_bucket_native`` of the station's WU daily summary
(the settlement proxy, AGENT_CONTEXT), dates <= 2025-12-31 only. Offline; writes one parquet.

    python tools/research/morning_loss/corpus_pairs.py --corpora <...\\corpora> --wu <...\\data\\wunderground> \\
        --out C:\\t\\l5\\inputs\\corpus_pairs.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

CORPORA = ("3a7034d2cb37f3425748bd4eeca048af85d8fd9bb0ef7a25519982b94ec8a6ba",
           "672a1f57632534076cba99ae2adebcbeb229decb58276d52fda79bd3946f18d2",
           "ece9d1c28454aa41113b022b92ff6600dcb4a5dab44a6851af5d895feea9281e",
           "b455bd53d8f9aab47f57d1fd97250945d687cdf7167d3a3a33738687c902f017",
           "cd0ba2bb004dc89f070ec9b1406e77f38cd2396dedd93ce1b377e727baefe9be",
           "23ac87fa5f058f8eeb7f49f0268f483939d4070f7f65e38063727c6749aa2a8d",
           "74807fbef1ba33ce8cd9c697b839369b1e3f3b7bbca7ebc3ac9f27edf84498cd")
EXPECTED_UNION = "621bcd8ea82ceed397bcfbdfae1c80664d1cb73adba3e71b240fae34db529cdc"
LAST = "2025-12-31"
CUTOFF = 7


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--corpora", required=True)
    p.add_argument("--wu", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    owner, rows, records = {}, [], []
    for cid in CORPORA:
        d = Path(a.corpora) / cid
        man = json.loads((d / "manifest.json").read_text())
        if man["corpus_id"] != cid:
            raise SystemExit(f"manifest id mismatch {cid}")
        got = sha(d / "forecast_daily.jsonl")
        if got != man["files"]["forecast_daily.jsonl"]["sha256"]:
            raise SystemExit(f"forecast_daily sha mismatch in {cid}")
        plan = json.loads((d / "plan.json").read_text())
        planned = sorted({str(x) for v in plan["expected_dates_by_year"].values() for x in v})
        for day in planned:
            if day in owner:
                raise SystemExit(f"date {day} planned by {owner[day]} and {cid}")
            owner[day] = cid
        records.append({"corpus_id": cid, "manifest_sha256": man["manifest_sha256"], "first_date": planned[0]})
        with open(d / "forecast_daily.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("row_kind") != "daily_high" or int(r["cutoff_hour_local"]) != CUTOFF:
                    continue
                if r["target_date"] > LAST or owner.get(r["target_date"]) != cid:
                    continue
                if r["source_model"] != "gfs_seamless" or int(r["lead_days"]) != 1:
                    raise SystemExit("unexpected corpus row contract")
                rows.append({"market": r["market_id"], "station": r["station"], "date": r["target_date"],
                             "gfs_d1": float(r["forecast_high_native"]), "corpus_id": cid})
    records.sort(key=lambda r: (r["first_date"], r["corpus_id"]))
    body = json.dumps([[r["corpus_id"], r["manifest_sha256"]] for r in records], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)
    union = hashlib.sha256(body.encode()).hexdigest()
    print("union_sha256", union, "matches L1:", union == EXPECTED_UNION)
    df = pd.DataFrame(rows).drop_duplicates(["market", "date"])
    labels = []
    for st in sorted(df.station.unique()):
        s = pd.read_csv(Path(a.wu) / st.lower() / "daily" / "daily_summary.csv",
                        usecols=["local_date", "max_temp_bucket_native"])
        s = s[s.local_date <= LAST].assign(station=st)
        labels.append(s)
    lab = pd.concat(labels).rename(columns={"local_date": "date", "max_temp_bucket_native": "y"})
    df = df.merge(lab, on=["station", "date"], how="inner")
    df["month"] = df.date.str[5:7].astype(int)
    df.attrs = {}
    df.to_parquet(a.out, index=False)
    (Path(a.out).with_suffix(".json")).write_text(json.dumps({"union_sha256": union, "corpora": records,
                                                              "rows": len(df), "sha256": sha(a.out)}, indent=1))
    print(df.groupby("market").agg(n=("date", "size"), first=("date", "min"), last=("date", "max")).to_string())


if __name__ == "__main__":
    main()
