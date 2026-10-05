"""A-IEM-2: measure NBM text bulletin availability (S3 LastModified) for cycles 00/06/12/18Z.

Used as the availability basis for the IEM-archived NBS/NBE rows (IEM keeps only 00/06/12/18Z).
Anonymous ListObjectsV2 on noaa-nbm-grib2-pds, prefix blend.YYYYMMDD/HH/text/. Development data.
"""
import datetime as dt, json, os, time, re
import requests
OUT = r"C:\swarm\data\iem\mos\nbm_text_lastmodified.jsonl"
s = requests.Session()
done = set()
if os.path.exists(OUT):
    for l in open(OUT, encoding="utf-8"):
        j = json.loads(l); done.add((j["date"], j["hour"]))
d = dt.date(2026,5,1)
with open(OUT, "a", encoding="utf-8") as f:
    while d <= dt.date(2026,9,29):
        for h in (0,6,12,18):
            if os.path.exists(r"C:\swarm\STOP"): raise SystemExit("STOP")
            key = (d.isoformat(), h)
            if key in done: continue
            p = f"blend.{d:%Y%m%d}/{h:02d}/text/"
            for attempt in range(6):
                r = s.get("https://noaa-nbm-grib2-pds.s3.amazonaws.com/", params={"list-type":"2","prefix":p}, timeout=60)
                if r.status_code == 200: break
                time.sleep(5*2**attempt)
            objs = re.findall(r"<Key>([^<]+)</Key><LastModified>([^<]+)</LastModified>.*?<Size>([0-9]+)</Size>", r.text)
            rec = {"date": key[0], "hour": h, "status": r.status_code,
                   "objects": {k.split("/")[-1]: {"last_modified": lm, "size": int(sz)} for k, lm, sz in objs}}
            f.write(json.dumps(rec) + "\n"); f.flush()
            time.sleep(0.2)
        d += dt.timedelta(days=1)
print("done")
