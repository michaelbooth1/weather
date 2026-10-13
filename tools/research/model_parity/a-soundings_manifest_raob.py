import json,hashlib,os,glob,math,datetime as dt
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
log={}
for l in open('fetch_log.jsonl'):
    r=json.loads(l); log[(r['station'],r['month'])]=r
g=json.load(open('RAOB_network.geojson')); st=json.load(open('C:/swarm/stations.json'))['stations']
geo={f['id']:f for f in g['features']}
def dist(a,b,c,e):
    R=6371;p1,p2=math.radians(a),math.radians(c);dl=math.radians(e-b);dp=p2-p1
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2;return round(2*R*math.asin(math.sqrt(h)),1)
MAP={'KATL':['KFFC','KBMX'],'KAUS':['KCRP','KFWD'],'KBKF':['KGJT','KLBF'],'KDAL':['KFWD'],'KHOU':['KLCH','KCRP'],'KLAX':['KNKX','KVBG','KEDW'],'KLGA':['KOKX'],'KMIA':['KMFL'],'KORD':['KILX','KDVN'],'KSEA':['KUIL','KSLE'],'KSFO':['KOAK']}
mapping={mk:[{'raob':c,'name':geo[c]['properties']['sname'],'lon':geo[c]['geometry']['coordinates'][0],'lat':geo[c]['geometry']['coordinates'][1],'elev_m':geo[c]['properties']['elevation'],'distance_km':dist(st[mk]['lat'],st[mk]['lon'],geo[c]['geometry']['coordinates'][1],geo[c]['geometry']['coordinates'][0])} for c in cs] for mk,cs in MAP.items()}
files=[]
for p in sorted(glob.glob('raw/*.csv.gz')):
    stn,mon=os.path.basename(p)[:-7].split('_'); r=log[(stn,mon)]
    files.append({'path':'raw/'+os.path.basename(p),'bytes':os.path.getsize(p),'sha256':sha(p),'url':r['url'],'request_utc':r['request_utc'],'decompressed_bytes':r['raw_bytes'],'decompressed_sha256':r['raw_sha256'],'rows':r['rows']})
for p,desc in [('soundings_summary.csv.gz','one row per sounding: surface, mandatory levels, dry-adiabatic 850/925 to surface, max theta in lowest 300 hPa at surface pressure; C and F; available_utc_basis = nominal valid + 60 min'),
               ('coverage_market_day.csv','market x date (2026-05-01..09-29) flags for 00Z (prior evening), 12Z, 18Z per candidate RAOB'),
               ('coverage_summary.csv','coverage counts per market, full window and 07-25..09-29'),
               ('RAOB_network.geojson','IEM RAOB station metadata used for nearest-station selection (https://mesonet.agron.iastate.edu/geojson/network/RAOB.geojson)'),
               ('fetch_raob.py','acquisition script'),('process_raob.py','summary/coverage script'),('manifest_raob.py','this manifest writer'),('fetch_log.jsonl','per-request log')]:
    files.append({'path':p,'bytes':os.path.getsize(p),'sha256':sha(p),'description':desc})
tot=sum(f['bytes'] for f in files)
M={'source':'Iowa Environmental Mesonet RAOB archive (cgi-bin/request/raob.py), anonymous, no key',
 'agent':'a-soundings','status':'COMPLETE','created_local':dt.datetime.now().isoformat(timespec='seconds'),
 'window_utc':'2026-05-01T00:00Z..2026-09-29T23:59Z (asserted: 0 rows dated >= 2026-09-30)',
 'request_pattern':'https://mesonet.agron.iastate.edu/cgi-bin/request/raob.py?station=<KXXX>&sts=<month start>Z&ets=<month end>Z',
 'politeness':'single connection, 3 s between requests, 85 requests, 0 retries, 0 failures',
 'availability_basis':{'rule':'STATED BASIS, not measured: IEM gives no per-object receipt time. available_utc = nominal synoptic valid time + 60 min (12Z -> 13:00Z, 18Z -> 19:00Z, 00Z -> 01:00Z). NWS balloons launch ~1 h before nominal time; mandatory-level TEMP parts are normally transmitted within ~60-90 min of launch.',
   'recommended_sensitivity':'refuters re-run at +2 h (12Z -> 14:00Z, 18Z -> 20:00Z)',
   'caveat':'IEM values may include post-receipt reprocessing (BUFR high-res vs TEMP); treat as near-real-time-equivalent, not bit-identical to what was on the wire at 13Z.'},
 'schedule_finding':'KCRP, KLCH, KDVN, KGJT, KLBF launch 00Z+18Z (not 12Z) for nearly the whole window; KMFL mixes 12Z and 18Z (12Z on 83/152 days). The 18Z sounding (available ~19Z = 13-14 local central) is the only same-day sounding for AUS(primary)/HOU/BKF and often MIA.',
 'denver_gap':'No Denver RAOB (72469 DNR) in IEM after 2022-07-08 or in UWyo (wsgi 404 for 2026-09-20 12Z, all src variants). BKF candidates are KGJT (328 km, west of the Divide) and KLBF (386 km): weak proxies, recommend BKF be excluded or flagged in T11.',
 'market_to_raob':mapping,
 'coverage_per_station_day':'coverage_market_day.csv; summary in coverage_summary.csv',
 'total_bytes':tot,'files':files}
json.dump(M,open('MANIFEST.json','w'),indent=1)
print(tot, len(files))
