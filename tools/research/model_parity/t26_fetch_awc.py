import json, time, requests, hashlib, datetime as dt
st = ["KATL","KAUS","KBKF","KDAL","KHOU","KLAX","KLGA","KMIA","KORD","KSEA","KSFO"]
CUT = "2026-09-30T00:00:00"
END = dt.datetime(2026,9,29,23,30,tzinfo=dt.timezone.utc)
log=[]; dropped=0
for s in st:
    allrec={}
    end=END
    for k in range(20):
        p={"ids":s,"format":"json","date":end.strftime("%Y-%m-%dT%H:%M:%SZ"),"hours":"96"}
        t0=dt.datetime.now(dt.timezone.utc).isoformat()
        r=requests.get("https://aviationweather.gov/api/data/metar",params=p,timeout=60)
        if r.status_code in (204,400) or not r.text.strip(): d=[]
        else:
            r.raise_for_status(); d=r.json()
        n0=len(d)
        keep=[x for x in d if x["receiptTime"]<CUT and x["obsTime"]<1790726400]
        dropped+=n0-len(keep)
        for x in keep: allrec[(x["rawOb"],x["receiptTime"])]=x
        log.append({"station":s,"url":r.url,"requested_utc":t0,"status":r.status_code,"n":n0,"kept":len(keep)})
        print(s,end,n0,flush=True)
        time.sleep(2)
        if n0==0: break
        assert n0<400, "cap hit"
        end=end-dt.timedelta(hours=96)
    recs=sorted(allrec.values(),key=lambda x:x["obsTime"])
    b=json.dumps(recs).encode()
    open(f"raw/awc_{s}.json","wb").write(b)
    log.append({"station":s,"file":f"raw/awc_{s}.json","n":len(recs),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
json.dump({"log":log,"dropped_ge_0930":dropped},open("raw/awc_fetch_log.json","w"),indent=1)
print("dropped",dropped)
