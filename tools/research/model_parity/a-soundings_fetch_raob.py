"""A-Soundings acquisition: IEM RAOB archive, 2026-05-01..2026-09-29 (UTC), one connection, polite."""
import requests, time, gzip, hashlib, json, os, sys, datetime as dt
OUT = r'C:\swarm\data\soundings\raw'
STATIONS = sys.argv[1].split(',')
MONTHS = [('2026-05-01T00:00Z','2026-05-31T23:59Z','202605'),('2026-06-01T00:00Z','2026-06-30T23:59Z','202606'),
          ('2026-07-01T00:00Z','2026-07-31T23:59Z','202607'),('2026-08-01T00:00Z','2026-08-31T23:59Z','202608'),
          ('2026-09-01T00:00Z','2026-09-29T23:59Z','202609')]
BASE = 'https://mesonet.agron.iastate.edu/cgi-bin/request/raob.py'
log = open(r'C:\swarm\data\soundings\fetch_log.jsonl', 'a')
s = requests.Session()
for stn in STATIONS:
    for sts, ets, tag in MONTHS:
        if os.path.exists(r'C:\swarm\STOP'):
            print('STOP present'); sys.exit(2)
        fn = os.path.join(OUT, f'{stn}_{tag}.csv.gz')
        if os.path.exists(fn):
            continue
        url = f'{BASE}?station={stn}&sts={sts}&ets={ets}'
        wait = 60
        for attempt in range(6):
            t0 = dt.datetime.now(dt.timezone.utc)
            try:
                r = s.get(url, timeout=180)
                body = r.content
                bad = r.status_code != 200 or b'Too many requests' in body[:500] or not body.startswith(b'station,validUTC')
            except Exception as e:
                bad, body, r = True, str(e).encode(), None
            if not bad:
                break
            print('retry', stn, tag, r.status_code if r is not None else None, body[:120]); time.sleep(wait); wait *= 2
        else:
            log.write(json.dumps({'station': stn, 'month': tag, 'url': url, 'status': 'FAILED'}) + '\n'); log.flush(); continue
        # guard: no rows dated >= 2026-09-30 UTC
        lines = body.decode().splitlines()
        late = [l for l in lines[1:] if l.split(',')[1] >= '2026-09-30']
        assert not late, (stn, tag, late[:2])
        with gzip.open(fn, 'wb') as f:
            f.write(body)
        rec = {'station': stn, 'month': tag, 'url': url, 'request_utc': t0.isoformat(), 'status': 'OK',
               'raw_bytes': len(body), 'rows': len(lines) - 1, 'raw_sha256': hashlib.sha256(body).hexdigest()}
        log.write(json.dumps(rec) + '\n'); log.flush(); print(rec['station'], tag, rec['rows'], rec['raw_bytes'])
        time.sleep(3)
