"""A-IEM-2 (model-parity swarm v2): fetch IEM MOS archive (mos.py) for 11 stations.

Acquisition only (development). One connection, sequential, >=2 s between requests,
back off 60 s then doubling on 429/503 or 'Too many requests' body text.
Runtime window 2026-05-01T00Z .. 2026-09-29T23:59Z (rows with runtime >= 2026-09-30 are dropped).
"""
import datetime as dt, hashlib, json, os, sys, time
import requests

OUT = r"C:\swarm\data\iem\mos\raw"
LOG = r"C:\swarm\data\iem\mos\fetch.log"
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
STATIONS = ["KATL","KAUS","KBKF","KDAL","KHOU","KLAX","KLGA","KMIA","KORD","KSEA","KSFO"]
MODELS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["NBS","NBE","GFS","MEX","NAM","LAV"]
# priority: evaluation window months first, then fitting history
CHUNKS = [("2026-07-25T00:00Z","2026-08-25T00:00Z"),("2026-08-25T00:00Z","2026-09-29T23:59Z"),
          ("2026-07-01T00:00Z","2026-07-25T00:00Z"),("2026-06-01T00:00Z","2026-07-01T00:00Z"),
          ("2026-05-01T00:00Z","2026-06-01T00:00Z")]
FREEZE = dt.datetime(2026,10,4,4,30)
SPACING = 2.0

def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG,"a",encoding="utf-8") as f: f.write(line+"\n")

def main():
    s = requests.Session()
    s.headers["User-Agent"] = "weather-research-model-parity/1.0 (single connection, 1 req/2s)"
    last = 0.0
    jobs = [(m,st,c) for m in MODELS for c in CHUNKS for st in STATIONS]
    for i,(m,st,(a,b)) in enumerate(jobs,1):
        if os.path.exists(r"C:\swarm\STOP"): log("STOP file present; exiting"); return
        if dt.datetime.now() >= FREEZE: log("freeze 04:30 reached; exiting"); return
        fn = os.path.join(OUT, f"{st}_{m}_{a[:10]}_{b[:10]}.csv")
        if os.path.exists(fn): continue
        backoff = 60
        while True:
            wait = SPACING - (time.time()-last)
            if wait > 0: time.sleep(wait)
            t0 = time.time(); last = t0
            try:
                r = s.get(URL, params=dict(station=st,model=m,sts=a,ets=b,format="csv"), timeout=300)
                body = r.text
            except Exception as e:
                log(f"[{i}/{len(jobs)}] {st} {m} {a} ERR {e!r}; sleep {backoff}")
                time.sleep(backoff); backoff = min(backoff*2, 960); continue
            if r.status_code in (429,503) or "Too many requests" in body[:500]:
                log(f"[{i}/{len(jobs)}] {st} {m} {a} throttled {r.status_code}; sleep {backoff}")
                time.sleep(backoff); backoff = min(backoff*2, 960); continue
            if r.status_code != 200 or not body.startswith("runtime"):
                log(f"[{i}/{len(jobs)}] {st} {m} {a} BAD status={r.status_code} head={body[:120]!r}")
                with open(fn+".bad","w",encoding="utf-8") as f: f.write(body[:2000])
                break
            tmp = fn+".part"
            with open(tmp,"w",encoding="utf-8",newline="") as f: f.write(body)
            os.replace(tmp, fn)
            log(f"[{i}/{len(jobs)}] {st} {m} {a}..{b} rows={body.count(chr(10))-1} bytes={len(r.content)} {time.time()-t0:.1f}s url={r.url}")
            break
    log("all requests done")

if __name__ == "__main__":
    main()
