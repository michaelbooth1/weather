"""R-T5-INC: stratified HEAD re-verification of NBH S3 LastModified vs the A-NBH ledger (development)."""
import json, random, time
from email.utils import parsedate_to_datetime
import requests
L = r"C:\swarm\data\nbh\ledger.jsonl"
recs = [json.loads(l) for l in open(L, encoding="utf-8")]
nbh = {}
for r in recs:
    if r.get("product") == "nbh" and r.get("status") == "ok":
        nbh[(r["date"], int(r["cycle"]))] = r  # last write wins
rng = random.Random(20261004)
sample = set()
for hr in range(24):
    dates = sorted(d for d, c in nbh if c == hr and d != "2026-09-24")
    for d in rng.sample(dates, 3):
        sample.add((d, hr))
for hr in range(13):
    sample.add(("2026-09-24", hr))
out = []
s = requests.Session()
for d, hr in sorted(sample):
    r = nbh[(d, hr)]
    resp = s.head(r["url"], timeout=30)
    lm = parsedate_to_datetime(resp.headers["Last-Modified"])
    led = parsedate_to_datetime(r["http_last_modified"])
    from datetime import datetime
    s3 = datetime.fromisoformat(r["s3_last_modified"].replace("Z", "+00:00"))
    out.append({"date": d, "cycle": hr, "status": resp.status_code, "head_last_modified": lm.isoformat(),
                "ledger_s3_last_modified": s3.isoformat(), "diff_s": (lm - s3).total_seconds(),
                "etag_match": resp.headers.get("ETag", "").strip('"') == r["etag"],
                "lag_min": (s3.timestamp() - datetime.fromisoformat(d + f"T{hr:02d}:00:00+00:00").timestamp()) / 60})
    time.sleep(0.3)
json.dump(out, open(r"C:\swarm\out\r-t5-inc\head_verify.json", "w"), indent=1)
bad = [o for o in out if o["diff_s"] != 0 or not o["etag_match"] or o["status"] != 200]
print(len(out), "checked;", len(bad), "mismatches"); [print(b) for b in bad]
for o in out:
    if o["date"] == "2026-09-24": print(o["cycle"], o["head_last_modified"], round(o["lag_min"], 1))
