"""A-NBH acquisition loop (model-parity swarm v2). Development data only.

Downloads NBM NBH and NBS text bulletins one object at a time from the public
noaa-nbm-grib2-pds bucket (anonymous HTTPS), records S3 LastModified
(availability basis), sha256, extracts 11 station blocks into tidy long rows,
deletes the raw object. Resumable via ledger.jsonl. Stops at FREEZE or STOP file.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
STATIONS = ["KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"]
PRODUCTS = {"nbh": "blend_nbhtx", "nbs": "blend_nbstx"}
ROOT = r"C:\swarm\data"
STAGE = os.path.join(ROOT, "nbh", "_stage")
LEDGER = os.path.join(ROOT, "nbh", "ledger.jsonl")
STOPFILE = r"C:\swarm\STOP"
START, END = dt.date(2026, 7, 25), dt.date(2026, 9, 29)
FREEZE = dt.datetime(2026, 10, 4, 4, 30)
CYCLES = list(range(9, 24)) + list(range(0, 9))
HDR = re.compile(r"^\s*(K[A-Z0-9]{3})\s+NBM V([\d.]+) (NBH|NBS) GUIDANCE\s+(\d+)/(\d+)/(\d{4})\s+(\d{4}) UTC")
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

sess = requests.Session()


def log(msg):
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


def ledger_done():
    done = set()
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("status") in ("ok", "missing"):
                    done.add((r["product"], r["date"], r["cycle"]))
    return done


def ledger_write(rec):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def get(url, stream=False, tries=6):
    wait = 5
    for i in range(tries):
        try:
            r = sess.get(url, stream=stream, timeout=60)
            if r.status_code in (200, 404):
                return r
            log(f"HTTP {r.status_code} {url}; retry in {wait}s")
        except requests.RequestException as e:
            log(f"ERR {e!r} {url}; retry in {wait}s")
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise RuntimeError(f"giving up {url}")


def listing(date, cyc):
    prefix = f"blend.{date:%Y%m%d}/{cyc:02d}/text/"
    r = get(f"{BUCKET}/?list-type=2&prefix={prefix}&delimiter=/")
    root = ET.fromstring(r.content)
    out = {}
    for c in root.findall("s3:Contents", NS):
        out[c.find("s3:Key", NS).text] = {
            "last_modified": c.find("s3:LastModified", NS).text,
            "size": int(c.find("s3:Size", NS).text),
            "etag": c.find("s3:ETag", NS).text.strip('"'),
        }
    return out


def fields(line, n):
    vals = []
    for k in range(n):
        s = line[5 + 3 * k: 8 + 3 * k].strip()
        if s == "":
            vals.append(None)
        else:
            try:
                vals.append(int(s))
            except ValueError:
                vals.append(None)
    return vals


def parse(text, product, cycle_dt):
    lines = text.splitlines()
    want = set(STATIONS)
    rows, found, bad = [], set(), []
    i = 0
    while i < len(lines):
        m = HDR.match(lines[i])
        if not m or m.group(1) not in want:
            i += 1
            continue
        st, ver, prod, mo, dy, yr, hhmm = m.groups()
        issued = dt.datetime(int(yr), int(mo), int(dy), int(hhmm[:2]), int(hhmm[2:]))
        if issued != cycle_dt or prod.lower() != product:
            bad.append(f"{st}: header {issued} {prod} != {cycle_dt} {product}")
        j = i + 1
        block = []
        while j < len(lines) and lines[j].strip() and not HDR.match(lines[j]):
            block.append(lines[j])
            j += 1
        i = j
        found.add(st)
        # hour axis
        if product == "nbh":
            utc_line = next(l for l in block if l[1:4] == "UTC")
            n = (len(utc_line.rstrip()) - 5 + 2) // 3
            hrs = fields(utc_line, n)
            fhr = [k + 1 for k in range(n)]
            for k, h in enumerate(hrs):
                if h is not None and (cycle_dt.hour + fhr[k]) % 24 != h:
                    bad.append(f"{st}: UTC col {k} = {h} vs fhr {fhr[k]}")
                    break
        else:
            fhr_line = next(l for l in block if l[1:4] == "FHR")
            n = (len(fhr_line.rstrip()) - 5 + 2) // 3
            fhr = fields(fhr_line, n)
        for l in block:
            lab = l[1:4].strip()
            if lab in ("UTC", "FHR", "DT") or l.startswith(" DT"):
                continue
            vals = fields(l, n)
            for k, v in enumerate(vals):
                if v is None or fhr[k] is None:
                    continue
                rows.append((st, ver, lab, fhr[k], v))
    df = pd.DataFrame(rows, columns=["station", "nbm_version", "field", "fhr", "value"])
    df["fhr"] = df["fhr"].astype("int16")
    df["value"] = df["value"].astype("int32")
    df["cycle_utc"] = pd.Timestamp(cycle_dt, tz="UTC")
    df["valid_utc"] = df["cycle_utc"] + pd.to_timedelta(df["fhr"].astype("int64"), unit="h")
    return df, sorted(found), bad


def main():
    os.makedirs(STAGE, exist_ok=True)
    for p in PRODUCTS:
        os.makedirs(os.path.join(ROOT, p, "parts"), exist_ok=True)
    done = ledger_done()
    dates = [START + dt.timedelta(days=d) for d in range((END - START).days + 1)]
    log(f"start; already done {len(done)}")
    for cyc in CYCLES:
        for date in dates:
            if os.path.exists(STOPFILE):
                log("STOP file present; exiting")
                return
            if dt.datetime.now() >= FREEZE:
                log("freeze time reached; exiting")
                return
            todo = [p for p in PRODUCTS if (p, str(date), cyc) not in done]
            if not todo:
                continue
            lst = listing(date, cyc)
            cycle_dt = dt.datetime(date.year, date.month, date.day, cyc)
            for p in todo:
                key = f"blend.{date:%Y%m%d}/{cyc:02d}/text/{PRODUCTS[p]}.t{cyc:02d}z"
                url = f"{BUCKET}/{key}"
                rec = {"product": p, "date": str(date), "cycle": cyc, "key": key, "url": url}
                if key not in lst:
                    rec.update(status="missing", listing_keys=sorted(lst))
                    ledger_write(rec)
                    log(f"missing {key}")
                    continue
                meta = lst[key]
                t0 = time.time()
                raw = os.path.join(STAGE, f"{p}.raw")
                h = hashlib.sha256()
                nbytes = 0
                r = get(url, stream=True)
                if r.status_code != 200:
                    rec.update(status="error", http=r.status_code)
                    ledger_write(rec)
                    continue
                with open(raw, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        h.update(chunk)
                        nbytes += len(chunk)
                http_lm = r.headers.get("Last-Modified")
                if nbytes != meta["size"]:
                    rec.update(status="error", reason=f"size {nbytes} != {meta['size']}")
                    ledger_write(rec)
                    os.remove(raw)
                    log(rec["reason"])
                    continue
                dl_s = time.time() - t0
                with open(raw, "r", encoding="ascii", errors="replace") as f:
                    text = f.read()
                df, found, bad = parse(text, p, cycle_dt)
                os.remove(raw)
                part = os.path.join(ROOT, p, "parts", f"{p}_{date:%Y%m%d}_{cyc:02d}.parquet")
                df.to_parquet(part, index=False)
                rec.update(
                    status="ok", s3_last_modified=meta["last_modified"], http_last_modified=http_lm,
                    etag=meta["etag"], bytes=nbytes, sha256=h.hexdigest(), stations_found=found,
                    stations_missing=sorted(set(STATIONS) - set(found)), rows=len(df), anomalies=bad[:20],
                    download_s=round(dl_s, 2), fetched_local=f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
                    part=os.path.relpath(part, ROOT),
                )
                ledger_write(rec)
                log(f"ok {key} {nbytes/1e6:.1f}MB {dl_s:.1f}s st={len(found)} rows={len(df)} bad={len(bad)}")
    log("all done")


if __name__ == "__main__":
    main()
