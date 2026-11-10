"""T003: bounded, standard-library-only, outcome-free book-summary census.
No network or account operations. Real payload reads require heavy-wrapper admission.
"""
import argparse
import csv
import gzip
import hashlib
import heapq
import io
import itertools
import json
import math
import os
import re
import random
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections import Counter
from functools import lru_cache
from zoneinfo import ZoneInfo

OUT = Path(r'C:\t\codex\T085\out')
LEGACY_OUT = Path(r'C:\t\codex\T003\out')
PLAN_SHA = '39dcdebcb1cd67c8cb9b5a3664b07327dff3bef5e9409dbab30f1f2b0378fde3'
LEGACY_SHA = 'b42a25f7d1fe4fc708059f1e2116607360a895a63b02f65e563435147cbf26cf'
PREREG_SHA = '73e8b665437b837108f28325ad3b26dd8983c0498a4c6d7e5ae04533011df902'
MAX_CSV_CHARS = 1048576
ROOT = Path(r'C:\t\recopy-20261106')
HOLD = Path(r'C:\t\codex\HOLD_HEAVY')
ROOTS = ('tapes-toronto-0801-0929','tapes-us-0801-0929')
VERSION = 't085_v4_parser_completion'
EVENT_DIR = 'stream_events_v4_r2'
BUDGET = None
QUOTA = None
ROUTES = ('buy_yes','sell_yes','buy_no','sell_no','convert_subset','buy_yes_mixed','buy_pair','sell_pair','ANY')
SIZES = (1,5,10,100)  # requested sizes plus the captured common minimum lot
WINDOWS = (1,5,30,60)
RESULT_FIELDS = ('gross_net','fee_net_lower','fee_net_upper','selected_fee_net_upper',
                 'buy_cost','sell_proceeds','cash_from_transform','selected_fee_cost_lower','selected_fee_cost_upper','selected_leg_details',
                 'net_lower_charter_1c','source_span_s','size_available_at_best',
                 'displayed_depth_ceiling_sets','selected_legs','best_route','eligible')
FIELDS = ('event','date','city','capture_index','captured_at_utc','hour_utc','capture_day_utc','hour_local','capture_day_local','q','route',
          'complete_both_outcomes','partition_ok','unresolved_inputs','local_time_valid','missing_yes','missing_no','blocked_legs') + RESULT_FIELDS + tuple('span1_'+k for k in RESULT_FIELDS)
METRICS = ('snapshot','margin_measured','valid','positive_lower','positive_upper','positive_span1',
           'positive_span1_upper','positive_charter_span1','positive_next_sample','unresolved_inputs')

def stamp(): return datetime.now(timezone.utc).isoformat()
def peak_memory():
    if os.name!='nt':return {}
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in
             ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
              'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    c=Counters();c.cb=ctypes.sizeof(c)
    handle=ctypes.windll.kernel32.GetCurrentProcess
    handle.restype=wintypes.HANDLE
    getinfo=ctypes.windll.psapi.GetProcessMemoryInfo
    getinfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    if not getinfo(handle(),ctypes.byref(c),c.cb):raise OSError('memory receipt unavailable')
    return dict(peak_working_set_bytes=c.PeakWorkingSetSize,peak_commit_bytes=c.PeakPagefileUsage)
class BudgetExpired(RuntimeError): pass
class HoldRequested(RuntimeError): pass
class OutputLimit(RuntimeError): pass

class RunBudget:
    def __init__(self,seconds,check_hold=True):
        if not 0 < seconds <= 1000: raise ValueError('max seconds must be in (0,1000]')
        self.deadline=time.monotonic()+seconds
        self.check_hold=check_hold
        self.next_hold=0
    def check(self):
        current=time.monotonic()
        if current>=self.deadline: raise BudgetExpired('cooperative runtime deadline')
        if self.check_hold and current>=self.next_hold:
            self.next_hold=current+1
            if HOLD.exists(): raise HoldRequested('HOLD_HEAVY appeared')

def check_budget():
    if BUDGET is not None:BUDGET.check()

class OutputQuota:
    def __init__(self,remaining): self.remaining=remaining
    def consume(self,n):
        if n>self.remaining:raise OutputLimit('task output budget exhausted; no further payload written')
        self.remaining-=n

class LimitedWriter(io.RawIOBase):
    def __init__(self,raw):self.raw=raw
    def writable(self):return True
    def write(self,b):
        check_budget()
        if QUOTA is not None:QUOTA.consume(len(b))
        return self.raw.write(b)
    def flush(self):
        if not self.raw.closed:self.raw.flush()

@contextmanager
def output_text(path,compressed=False):
    with path.open('wb') as raw:
        limited=LimitedWriter(raw)
        if compressed:
            with gzip.GzipFile(filename='',mode='wb',fileobj=limited,mtime=0) as gz:
                with io.TextIOWrapper(gz,encoding='utf-8',newline='') as text:yield text
        else:
            with io.TextIOWrapper(limited,encoding='utf-8',newline='') as text:yield text

def dump(p,x,teardown=False):
    # Temporary + replace prevents a partly written completion receipt.
    tmp=p.with_name(p.name+'.tmp-'+uuid.uuid4().hex)
    payload=json.dumps(x,indent=2,allow_nan=False)+'\n'
    if teardown:tmp.write_text(payload,encoding='utf-8')  # small receipt reserve after a budget stop
    else:
        with output_text(tmp) as f:f.write(payload)
    os.replace(tmp,p)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            check_budget();h.update(b)
    return h.hexdigest()
def number(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError): return None
def epoch(s):
    d=datetime.fromisoformat(s)
    if d.utcoffset() is None:raise ValueError('timezone required in capture timestamp')
    return d.timestamp()
@lru_cache(maxsize=2048)
def date_slug(s):
    prefix='highest-temperature-in-'
    if not s.startswith(prefix) or '-on-' not in s: raise ValueError('invalid event slug')
    city,ds=s[len(prefix):].rsplit('-on-',1)
    d=datetime.strptime(ds,'%B-%d-%Y').date().isoformat()
    if not '2026-08-01' <= d <= '2026-09-29': raise ValueError('EMBARGO: '+s)
    return d,city

def load_plan():
    plan_path=LEGACY_OUT/'inventory.json'
    if sha(plan_path)!=PLAN_SHA:raise ValueError('fixed T003 inventory changed')
    planned=json.loads(plan_path.read_text(encoding='utf-8-sig'))
    # Metadata only: excluded paths are never statted or opened.
    permitted=[p for p in planned if '2026-08-01'<=p['date']<='2026-09-29']
    if len(planned)!=900 or len(permitted)!=720 or len({p['event'] for p in permitted})!=720:
        raise ValueError('fixed 720/900 permitted universe changed')
    canonical=[]
    for p in permitted:
        dt,city=date_slug(p['event'])
        expected=ROOT/ROOTS[0 if city=='toronto' else 1]/p['event']/'order_books_summary.csv'
        source=Path(p['path'])
        if source!=expected or p['date']!=dt:
            raise ValueError('input identity/path/date mismatch')
        if source.resolve()!=source.absolute():raise ValueError('reparse input path is not permitted')
        if source.stat().st_size!=p['bytes']:raise ValueError('input size changed: '+p['event'])
        # T003 loaded the raw plan only as a binding, then returned inventory()
        # records: derived city, no planning-only index. Preserve that shape.
        canonical.append(dict(event=p['event'],date=dt,city=city,path=p['path'],bytes=p['bytes']))
    return canonical
def inventory():
    return load_plan()

class CappedCSVLines:
    """Bound a logical CSV record, including quoted physical newlines."""
    def __init__(self,text):self.text=text;self.characters=0
    def __iter__(self):return self
    def start_record(self):self.characters=0
    def __next__(self):
        check_budget()
        remaining=MAX_CSV_CHARS-self.characters
        value=self.text.readline(remaining+1)
        if not value:raise StopIteration
        if len(value)>remaining:raise ValueError('logical CSV record exceeds fixed character cap')
        self.characters+=len(value)
        return value

def strict_rows(text):
    """No recovery, skipping, normalization or permissive quote handling."""
    lines=CappedCSVLines(text)
    prior_limit=csv.field_size_limit(MAX_CSV_CHARS)
    try:
        reader=csv.reader(lines,strict=True)
        fields=next(reader,[])
        yield fields
        while True:
            lines.start_record()
            row=next(reader,None)
            if row is None:return
            if len(row)!=len(fields):raise ValueError('malformed/truncated CSV row')
            yield dict(zip(fields,row))
    finally:csv.field_size_limit(prior_limit)

class HashRaw(io.RawIOBase):
    def __init__(self,raw): self.raw,self.digest=raw,hashlib.sha256()
    def readable(self): return True
    def readinto(self,b):
        check_budget()
        n=self.raw.readinto(b)
        if n: self.digest.update(memoryview(b)[:n])
        return n

def captures(path,hashed=None):
    with path.open('rb',buffering=0) as raw:
        tracker=HashRaw(raw)
        with io.TextIOWrapper(io.BufferedReader(tracker,65536),encoding='utf-8-sig',newline='') as text:
            reader=strict_rows(text)
            required={'captured_at_utc','event_slug','market_id','condition_id','range_label','bin_kind','bin_value','bin_value_hi',
                      'unit','outcome','clob_token_id','book_timestamp','min_order_size','tick_size','neg_risk',
                      'best_bid','best_ask','bid_size_at_best','ask_size_at_best'}
            allowed=required | {'capture_id','captured_at_local','polymarket_market_id','order_book_hash','book_time_utc',
                      'bid_count','ask_count','spread','midpoint','bid_depth_1pct','ask_depth_1pct','bid_depth_5pct','ask_depth_5pct',
                      'bid_depth_all','ask_depth_all','imbalance_1pct','imbalance_5pct','last_trade_price','gamma_best_bid','gamma_best_ask','gamma_last_trade_price'}
            allowed|={f'{d}_{f}_{q}' for q in (10,100,1000) for d in ('buy','sell') for f in ('vwap','fillable')}
            fields=next(reader)
            if len(fields)!=len(set(fields)) or not required.issubset(fields) or set(fields)-allowed:
                raise ValueError('unexpected or potentially sensitive book-summary header')
            for t,g in itertools.groupby(reader,key=lambda r:r['captured_at_utc']):
                check_budget()
                group=[]
                for row in g:
                    if None in row or any(v is None for v in row.values()):raise ValueError('malformed/truncated CSV row')
                    date_slug(row['event_slug'])  # refuse guarded local target dates per row
                    group.append(row)
                    if len(group)>256: raise ValueError('capture group exceeds 256-row safety cap')
                yield t,group
        if hashed is not None: hashed.append(tracker.digest.hexdigest())

class Distribution:
    """Bounded-resolution streaming histogram; preserve exact extrema."""
    def __init__(self): self.bins=Counter(); self.n=0; self.low=None; self.high=None
    def add(self,x):
        if x is None or not math.isfinite(x): return
        self.n+=1
        self.low=x if self.low is None else min(self.low,x)
        self.high=x if self.high is None else max(self.high,x)
        step=.001 if abs(x)<1 else .01 if abs(x)<60 else 1 if abs(x)<3600 else 60
        self.bins[round(round(x/step)*step,3)]+=1
    def report(self):
        if not self.n:return {'n':0}
        bins=sorted(self.bins.items()); ans={'n':self.n,'min':self.low,'max':self.high}
        for q in (.5,.9,.95,.99):
            total=0
            for value,count in bins:
                total+=count
                if total>=math.ceil(q*self.n):ans[str(q)]=value;break
        return ans

def meta_of(r):
    return (r['bin_kind'],number(r['bin_value']),number(r['bin_value_hi']),r['unit'],r['range_label'])
def partition(meta):
    intervals=[]
    units={v[3] for v in meta.values()}
    if len(units)!=1 or not units.issubset({'C','F'}):return False,'mixed or unknown units'
    for k,a,b,_,_ in meta.values():
        if a is None or b is None or not a.is_integer() or not b.is_integer():return False,'invalid endpoints'
        if k in ('lte','gte') and a!=b:return False,'inconsistent tail endpoint'
        if k=='lte':a=-math.inf
        elif k=='gte':b=math.inf
        elif k!='eq':return False,'unknown bin kind'
        intervals.append((a,b))
    intervals.sort()
    if not intervals or intervals[0][0]!=-math.inf or intervals[-1][1]!=math.inf:return False,'missing open tail'
    if any(a>b for a,b in intervals):return False,'reversed interval'
    if any(intervals[i+1][0]!=intervals[i][1]+1 for i in range(len(intervals)-1)):return False,'gap or overlap'
    return True,'complete integer partition'

def leg(row,buy,q,label=None,blocked=False):
    if row is None or blocked:return None
    p=number(row.get('best_ask' if buy else 'best_bid'))
    depth=number(row.get('ask_size_at_best' if buy else 'bid_size_at_best'))
    all_depth=number(row.get('ask_depth_all' if buy else 'bid_depth_all'))
    if p is None or depth is None or depth<0 or not 0<p<1:return None
    if all_depth is not None and (all_depth+1e-8<depth or all_depth+1e-8<q):return None
    if depth+1e-8>=q:v=p;exact=True
    elif q not in (10,100):return None  # unmeasured walk, not an assumed zero margin
    else:
        direction='buy' if buy else 'sell'
        filled=number(row.get(f'{direction}_fillable_{q}'))
        v=number(row.get(f'{direction}_vwap_{q}'))
        if v is None or filled is None or filled+1e-8<q or filled>q+1e-7 or not 0<v<1:return None
        if (buy and v<p-1e-8) or (not buy and v>p+1e-8):return None
        if buy and v<p:v=p
        if not buy and v>p:v=p
        exact=abs(v-p)<1e-12
    fu=.05*v*(1-v)
    fl=fu if exact else .05*p*(1-v) if buy else .05*v*(1-p)
    tick=number(row.get('tick_size'));minimum=number(row.get('min_order_size'))
    on_grid=tick in (.1,.01,.001,.0001) and abs(p/tick-round(p/tick))<1e-6
    eligible=(not blocked and on_grid and minimum is not None and minimum>0 and minimum<=q+1e-8
              and str(row.get('neg_risk')).lower()=='true')
    bt=number(row.get('book_timestamp'))
    return dict(v=v,fl=fl,fu=fu,best_depth=depth,all_depth=all_depth,
                name=(label if label is not None else row['condition_id'])+('Y' if row['outcome']=='Yes' else 'N')+('b' if buy else 's'),
                source_ms=bt if bt is not None and bt>0 else None,eligible=eligible,
                bit=1<<(2*int(label)+(0 if row['outcome']=='Yes' else 1)) if label is not None else 0)

def pnl(legs,payout,q):
    if not legs or any(x is None for x,buy in legs):return None
    g=lo=hi=payout
    for x,buy in legs:
        if buy:g-=x['v'];lo-=x['v']+x['fu'];hi-=x['v']+x['fl']
        else:g+=x['v'];lo+=x['v']-x['fu'];hi+=x['v']-x['fl']
    times=[x.get('source_ms') for x,b in legs]
    span=(max(times)-min(times))/1000 if all(t is not None for t in times) else None
    return dict(gross_net=g*q,fee_net_lower=lo*q,fee_net_upper=hi*q,selected_fee_net_upper=hi*q,
                buy_cost=q*sum(x['v'] for x,b in legs if b),sell_proceeds=q*sum(x['v'] for x,b in legs if not b),
                cash_from_transform=payout*q,selected_fee_cost_lower=q*sum(x['fl'] for x,b in legs),
                selected_fee_cost_upper=q*sum(x['fu'] for x,b in legs),
                selected_leg_details=json.dumps([[x['name'],'buy' if b else 'sell',x['v'],q*x['fl'],q*x['fu'],
                    x['best_depth'],x['all_depth'],x['source_ms']] for x,b in legs],separators=(',',':')),
                selected_legs='|'.join(x['name'] for x,b in legs),source_span_s=span,
                size_available_at_best=min(x['best_depth'] for x,b in legs),
                displayed_depth_ceiling_sets=min(x['all_depth'] for x,b in legs) if all(x.get('all_depth') is not None for x,b in legs) else None,
                net_lower_charter_1c=lo*q-.01*q*len(legs),eligible=all(x.get('eligible',True) for x,b in legs),
                _legs=legs,_upper_span=span)

def combine(candidates,route):
    candidates=[x for x in candidates if x is not None]
    if not candidates:return None
    lower=max(candidates,key=lambda x:x['fee_net_lower'])
    upper=max(candidates,key=lambda x:x['fee_net_upper'])
    return dict(lower,fee_net_upper=upper['fee_net_upper'],best_route=lower.get('best_route',route),
                _upper_span=upper['_upper_span'])

def choice_route(first,second,q,kind,*,eligible_only,mask=None,optimistic=False):
    def usable(x):
        return x is not None and (not eligible_only or x['eligible']) and (mask is None or mask & x['bit'])
    fee='fl' if optimistic else 'fu'
    chosen=[]
    for a,b in zip(first,second):
        av=(a['v']-a[fee] if kind=='convert_subset' else -a['v']-a[fee]) if usable(a) else -math.inf
        bv=1-b['v']-b[fee] if kind=='convert_subset' and usable(b) else b['v']-b[fee]-1 if usable(b) else -math.inf
        if av==bv==-math.inf:return None
        chosen.append(bv>=av)
    if kind=='convert_subset' and not any(chosen):
        options=[(1-b['v']-b[fee]-(a['v']-a[fee]),i) for i,(a,b) in enumerate(zip(first,second)) if usable(b)]
        if not options:return None
        chosen[max(options)[1]]=True
    legs=[(second[i],kind=='convert_subset') if use_second else (first[i],kind!='convert_subset') for i,use_second in enumerate(chosen)]
    payoff=sum(chosen)-1 if kind=='convert_subset' else 1-sum(chosen)
    if optimistic:legs=[(dict(x,fu=x['fl']),b) for x,b in legs]
    return pnl(legs,payoff,q)

def choice_bounds(first,second,q,kind,eligible_only,mask=None):
    lower=choice_route(first,second,q,kind,eligible_only=eligible_only,mask=mask)
    if lower is None:return None
    upper=choice_route(first,second,q,kind,eligible_only=eligible_only,mask=mask,optimistic=True)
    return dict(lower,fee_net_upper=upper['fee_net_lower'],best_route=kind,_upper_span=upper['source_span_s'])

class Frame:
    def __init__(self,rows,conditions,blocked=()):
        self.rows,self.conditions,self.blocked=rows,conditions,set(blocked)
        self._masks={};self._legs={}
    def legs(self,q):
        if q not in self._legs:
            def get(side,buy):
                return [leg(self.rows.get((c,side)),buy,q,str(i),blocked=(c,side) in self.blocked) for i,c in enumerate(self.conditions)]
            self._legs[q]=(get('Yes',True),get('Yes',False),get('No',True),get('No',False))
        return self._legs[q]
    def masks(self,window):
        if window in self._masks:return self._masks[window]
        stamped=[]
        for i,c in enumerate(self.conditions):
            for side,offset in (('Yes',0),('No',1)):
                row=self.rows.get((c,side));t=number(row.get('book_timestamp')) if row else None
                if t is not None and t>0:stamped.append((t,1<<(2*i+offset)))
        even=sum(1<<(2*i) for i in range(len(self.conditions)))
        masks=set()
        for left in sorted({t for t,b in stamped}):
            mask=0
            for t,bit in stamped:
                if left<=t<=left+1000*window:mask|=bit
            if (mask | (mask>>1)) & even == even:masks.add(mask)
        self._masks[window]=tuple(sorted(masks))
        return self._masks[window]

def evaluate(frame,q,partition_ok=True,window=None,diagnostics=True):
    rows,conditions=frame.rows,frame.conditions
    yb,ys,nb,ns=frame.legs(q)
    n=len(conditions);results={}
    def within(x):return x is not None and x['eligible'] and (window is None or x['source_span_s'] is not None and x['source_span_s']<=window)
    fixed=(('buy_yes',yb,True,1),('sell_yes',ys,False,-1),('buy_no',nb,True,n-1),('sell_no',ns,False,-(n-1)))
    for name,legs,buy,payoff in fixed:
        raw=pnl([(x,buy) for x in legs],payoff,q) if partition_ok else None
        value=raw if within(raw) else dict(raw,eligible=False) if diagnostics and window is None and raw else None
        results[name]=dict(value,best_route=name) if value else None
    for name,first,second in (('convert_subset',ys,nb),('buy_yes_mixed',yb,ns)):
        value=None
        if partition_ok:
            best=choice_bounds(first,second,q,name,True)
            if window is None:value=best
            elif within(best) and best['_upper_span'] is not None and best['_upper_span']<=window:value=best
            else:value=combine([choice_bounds(first,second,q,name,True,mask) for mask in frame.masks(window)],name)
            if value is None and diagnostics and window is None:
                raw=choice_bounds(first,second,q,name,False)
                value=dict(raw,eligible=False) if raw else None
        results[name]=value
    for name,left,right,buy,payoff in (('buy_pair',yb,nb,True,1),('sell_pair',ys,ns,False,-1)):
        raw=[pnl([(a,buy),(b,buy)],payoff,q) for a,b in zip(left,right)]
        eligible=[r for r in raw if within(r)]
        value=combine(eligible,name)
        if value is None and diagnostics and window is None:
            value=combine(raw,name)
            if value:value=dict(value,eligible=False)
        results[name]=value
    valid=[x for x in results.values() if x is not None and x['eligible']]
    value=combine(valid,'ANY')
    if value is None and diagnostics and window is None:
        value=combine(results.values(),'ANY')
        if value:value=dict(value,eligible=False)
    results['ANY']=value
    return results

def local_stamp(group,cap):
    locals=[]
    for row in group:
        try:
            d=datetime.fromisoformat(row.get('captured_at_local') or '')
            if d.utcoffset() is None or abs(d.timestamp()-cap)>.001:return None
            locals.append(d)
        except (ValueError,TypeError):return None
    if not locals or len({(d.date(),d.hour,d.utcoffset()) for d in locals})!=1:return None
    return locals[0]

def unresolved_frame(frame,q):
    if frame.blocked or len(frame.rows)!=2*len(frame.conditions):return True
    for r in frame.rows.values():
        minimum=number(r.get('min_order_size'));tick=number(r.get('tick_size'));bt=number(r.get('book_timestamp'))
        if minimum is None or minimum<=0 or tick is None or tick<=0 or bt is None or bt<=0:return True
        if str(r.get('neg_risk')).lower() not in ('true','false'):return True
        for side,direction in (('ask','buy'),('bid','sell')):
            p=number(r.get('best_'+side));best=number(r.get(side+'_size_at_best'))
            total=number(r.get(side+'_depth_all'));count=number(r.get(side+'_count'))
            if p is None:
                if total!=0 and count!=0:return True
                continue
            if best is None or best<0:return True
            if total is not None and total+1e-8<best:return True
            if best+1e-8>=q:continue
            if total is not None and total+1e-8<q:continue
            if q not in (10,100):return True
            filled=number(r.get(f'{direction}_fillable_{q}'));v=number(r.get(f'{direction}_vwap_{q}'))
            if filled is None or filled>=q-1e-8 and v is None:return True
            if filled<q-1e-8 and total is not None and total>=q:return True
    return False

def write_rows(path,rows,fields):
    with output_text(path) as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def verify_event(dest,event,expected_sha=None):
    path=dest/(event+'.json')
    b=json.loads(path.read_text(encoding='utf-8'))
    wanted=expected_sha or sha(Path(__file__))
    if b.get('version')!=VERSION or b.get('script_sha256')!=wanted or not b.get('completed'):
        raise ValueError('mixed-version or incomplete event receipt: '+event)
    if set(b['artifacts'])!={event+s for s in ('.csv.gz','.hours.csv','.episodes.csv')}:
        raise ValueError('unexpected artifact manifest')
    for name,info in b['artifacts'].items():
        if Path(name).name!=name:raise ValueError('artifact path traversal')
        p=dest/name
        if not p.is_file() or p.stat().st_size!=info['bytes'] or sha(p)!=info['sha256']:
            raise ValueError('artifact hash/size mismatch: '+name)
    return b


def run_event(item,dest):
    # Only task-owned output paths may be published or quarantined.
    if not dest.resolve().is_relative_to(OUT.resolve()):raise ValueError('output outside task root')
    source=Path(item['path'])
    date_slug(item['event'])  # before opening a payload
    final=dest/(item['event']+'.json')
    if final.exists():
        b=verify_event(dest,item['event'])
        stat=source.stat()
        if b['source_stat']!={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}:
            raise ValueError('completed input changed; retain prior result and stop')
        return b
    names=[item['event']+s for s in ('.csv.gz','.hours.csv','.episodes.csv')]
    orphans=[dest/name for name in names if (dest/name).exists()]
    if orphans:
        archive=dest/('orphan-'+uuid.uuid4().hex);archive.mkdir()
        for p in orphans:os.replace(p,archive/p.name)
        dump(archive/'retained.json',dict(recorded_utc=stamp(),reason='payload without completion receipt',
                                         files=[p.name for p in orphans]),teardown=True)
    stage=dest/('.attempt-'+uuid.uuid4().hex);stage.mkdir()
    try:
        b=_run_event(item,stage)
        check_budget()
        b['artifacts']={name:dict(bytes=(stage/name).stat().st_size,sha256=sha(stage/name)) for name in names}
        b['completed']=True
        dump(stage/(item['event']+'.json'),b)
        for name in names:os.replace(stage/name,dest/name)
        # Completion receipt is last: a partial publication is never countable.
        os.replace(stage/(item['event']+'.json'),final)
        try:stage.rmdir()
        except OSError:pass
        return b
    except BaseException as exc:
        dump(stage/'FAILED.json',dict(recorded_utc=stamp(),event=item['event'],
             error_type=type(exc).__name__,error=str(exc),countable=False),teardown=True)
        raise


def _run_event(item,dest):
    source=Path(item['path']);date,city=date_slug(item['event']);start=time.monotonic()
    stat0=source.stat();meta={};tokens={};unstable=set();bad_tokens=set()
    ordered=True;last=-math.inf;row_count=0;snaps=0;hashes=[];first_time=None;last_time=None
    for t,group in captures(source,hashes):
        check_budget();cap=epoch(t);ordered &= cap>last;last=cap
        first_time=t if first_time is None else first_time;last_time=t
        snaps+=1;row_count+=len(group)
        for r in group:
            if r['event_slug']!=item['event'] or r['market_id']!=city:raise ValueError('event identity mismatch')
            if r['outcome'] not in ('Yes','No'):raise ValueError('unexpected outcome side')
            if not r['condition_id'] or not r['clob_token_id']:raise ValueError('missing token identity')
            c=r['condition_id'];m=meta_of(r);key=(c,r['outcome']);token=r['clob_token_id']
            if c in meta and meta[c]!=m:unstable.add(c)
            else:meta[c]=m
            if key in tokens and tokens[key]!=token:bad_tokens.add(key)
            else:tokens[key]=token
    full,reason=partition(meta)
    full=full and not unstable and ordered
    if unstable:reason='metadata changed'
    if not ordered:reason='nonincreasing capture groups'
    if not ordered:raise ValueError('nonincreasing capture groups; event not interpretable')
    conditions=sorted(meta)
    if len(conditions)>128:raise ValueError('event union exceeds 128-band safety cap')
    expected={(c,s) for c in conditions for s in ('Yes','No')}
    spans=Distribution();offsets=Distribution();gaps=Distribution()
    counts=Counter();windows=Counter();hour_counts=Counter();prior={};episodes={}
    heaps={False:[],True:[]};serial=0;complete_n=0;duplicates=0;missing_n=0
    complete_yes=complete_no=0;local_invalid=0;ticks=Counter();minimums=Counter()
    lastcap=None;secondhash=[];max_group_rows=0;capture_index=-1;retained_rows=0
    output=dest/(item['event']+'.csv.gz')
    episode_fields=('event','q','route','first','last','observations','best_net_lower','sampled_span_s','continuous_duration_lower_s')
    hour_fields=('city','date','capture_day_utc','hour_utc','capture_day_local','hour_local','q','route')+METRICS
    with output_text(output,compressed=True) as text, output_text(dest/(item['event']+'.episodes.csv')) as episode_text, output_text(dest/(item['event']+'.hours.csv')) as hour_text:
        writer=csv.DictWriter(text,fieldnames=FIELDS);writer.writeheader()
        episode_writer=csv.DictWriter(episode_text,fieldnames=episode_fields);episode_writer.writeheader()
        hour_writer=csv.DictWriter(hour_text,fieldnames=hour_fields);hour_writer.writeheader()
        active_hour=None
        def emit_episode(e):
            e=dict(e);e['sampled_span_s']=e.pop('last_epoch')-e.pop('first_epoch');e['continuous_duration_lower_s']=0
            episode_writer.writerow(e)
        def flush_hours(keep=None):
            keys={k[:-1] for k in hour_counts if (k[2],k[3])!=keep}
            for hk in sorted(keys):
                record=dict(zip(hour_fields[:8],hk))
                record.update({m:hour_counts.pop(hk+(m,),0) for m in METRICS});hour_writer.writerow(record)
        for t,group in captures(source,secondhash):
            check_budget();capture_index+=1
            cap=epoch(t);dt=datetime.fromisoformat(t).astimezone(timezone.utc)
            local=local_stamp(group,cap);local_invalid+=local is None
            max_group_rows=max(max_group_rows,len(group))
            keycounts=Counter((r['condition_id'],r['outcome']) for r in group)
            duplicate_keys={k for k,v in keycounts.items() if v>1}
            tokenkeys={}
            for r in group:tokenkeys.setdefault(r['clob_token_id'],set()).add((r['condition_id'],r['outcome']))
            duplicate_keys|={k for keys in tokenkeys.values() if len(keys)>1 for k in keys}
            rows={(r['condition_id'],r['outcome']):r for r in group}
            blocked=duplicate_keys|bad_tokens
            dupe=bool(duplicate_keys);duplicates+=dupe
            complete=set(rows)==expected and not dupe
            complete_n+=full and complete;missing_n+=set(rows)!=expected
            complete_yes+=full and all((c,'Yes') in rows and (c,'Yes') not in blocked for c in conditions)
            complete_no+=full and all((c,'No') in rows and (c,'No') not in blocked for c in conditions)
            bt=[number(r['book_timestamp']) for r in group]
            span=(max(bt)-min(bt))/1000 if bt and all(x is not None and x>0 for x in bt) else None
            spans.add(span)
            for x in bt:
                if x is not None and x>0:offsets.add(x/1000-cap)
            if lastcap is not None:gaps.add(cap-lastcap)
            lastcap=cap
            for r in group:ticks[r['tick_size']]+=1;minimums[r['min_order_size']]+=1
            frame=Frame(rows,conditions,blocked)
            for q in SIZES:
                results=evaluate(frame,q,full)
                by_window={w:evaluate(frame,q,full,window=w,diagnostics=False) for w in WINDOWS}
                # This flags unresolved cost data; it is never counted as a zero margin.
                unresolved=unresolved_frame(frame,q)
                for route in ROUTES:
                    result=results[route];primary=by_window[1][route]
                    valid=result is not None and result['eligible']
                    low=valid and result['fee_net_lower']>1e-8
                    high=valid and result['fee_net_upper']>1e-8
                    positive=primary is not None and primary['fee_net_lower']>1e-8
                    rec=dict(event=item['event'],date=date,city=city,capture_index=capture_index,captured_at_utc=t,
                        hour_utc=dt.hour,capture_day_utc=dt.date().isoformat(),
                        hour_local=local.hour if local else '',capture_day_local=local.date().isoformat() if local else '',
                        q=q,route=route,complete_both_outcomes=complete,partition_ok=full,
                        unresolved_inputs=unresolved,local_time_valid=local is not None,
                        missing_yes='|'.join(str(i) for i,c in enumerate(conditions) if (c,'Yes') not in rows),
                        missing_no='|'.join(str(i) for i,c in enumerate(conditions) if (c,'No') not in rows),
                        blocked_legs='|'.join(str(i)+side[0] for i,c in enumerate(conditions) for side in ('Yes','No') if (c,side) in blocked))
                    rec.update({k:result.get(k) if result else None for k in RESULT_FIELDS})
                    rec.update({'span1_'+k:primary.get(k) if primary else None for k in RESULT_FIELDS})
                    # Preserve all counters below; retain only potentially positive rows.
                    # Ordinals preserve negative/absent-capture breaks for light episode joins.
                    if high or (primary is not None and primary['fee_net_upper']>1e-8):
                        writer.writerow({k:format(v,'.17g') if isinstance(v,float) else v for k,v in rec.items()})
                        retained_rows+=1
                    key=(q,route);hk=(city,date,dt.date().isoformat(),dt.hour,
                          local.date().isoformat() if local else '',local.hour if local else '',q,route)
                    vals=dict(snapshot=1,margin_measured=int(result is not None),valid=int(valid),
                        positive_lower=int(low),positive_upper=int(high),positive_span1=int(positive),
                        positive_span1_upper=int(primary is not None and primary['fee_net_upper']>1e-8),
                        positive_charter_span1=int(positive and primary['net_lower_charter_1c']>1e-8),
                        positive_next_sample=0,unresolved_inputs=int(unresolved))
                    for metric,value in vals.items():counts[(q,route,metric)]+=value;hour_counts[hk+(metric,)]+=value
                    for w in WINDOWS:
                        value=by_window[w][route]
                        windows[(q,route,w,'tested')]+=valid
                        windows[(q,route,w,'within_window')]+=value is not None
                        windows[(q,route,w,'positive_lower')]+=value is not None and value['fee_net_lower']>1e-8
                        windows[(q,route,w,'positive_upper')]+=value is not None and value['fee_net_upper']>1e-8
                    if key in prior:
                        pt,pp,phk=prior[key]
                        if positive and pp and 0<cap-pt<=120:
                            counts[(q,route,'positive_next_sample')]+=1;hour_counts[phk+('positive_next_sample',)]+=1
                    prior[key]=(cap,positive,hk)
                    if key in episodes and (not positive or cap-episodes[key]['last_epoch']>120):
                        emit_episode(episodes.pop(key))
                    if positive:
                        if key not in episodes:episodes[key]=dict(event=item['event'],q=q,route=route,first=t,last=t,
                              first_epoch=cap,last_epoch=cap,observations=0,best_net_lower=primary['fee_net_lower'])
                        e=episodes[key];e['last']=t;e['last_epoch']=cap;e['observations']+=1
                        e['best_net_lower']=max(e['best_net_lower'],primary['fee_net_lower'])
                    if q>=5 and route!='ANY':
                        for strict,value in ((False,result if valid else None),(True,primary)):
                            if value is None:continue
                            serial+=1
                            case={k:rec[k] for k in ('event','date','city','captured_at_utc','q','route')}
                            case.update({k:value.get(k) for k in RESULT_FIELDS});case['source_window_s']=1 if strict else None
                            heap=heaps[strict];entry=(value['fee_net_lower'],serial,case)
                            if len(heap)<8:heapq.heappush(heap,entry)
                            elif entry[:2]>heap[0][:2]:heapq.heapreplace(heap,entry)
            hour_tag=(dt.date().isoformat(),dt.hour)
            if active_hour!=hour_tag:flush_hours(keep=hour_tag);active_hour=hour_tag
        for e in episodes.values():emit_episode(e)
        flush_hours()
    stat1=source.stat()
    if hashes!=secondhash or stat0.st_size!=stat1.st_size or stat0.st_mtime_ns!=stat1.st_mtime_ns:
        raise ValueError('input changed between passes')
    return dict(item,retained_rows=retained_rows,omitted_rows=snaps*len(SIZES)*len(ROUTES)-retained_rows,
        row_policy='eligible unwindowed upper fee bound positive OR one-second-window upper fee bound positive; all counters retained',
        rows=row_count,snapshots=snaps,bands=len(conditions),partition=full,partition_reason=reason,
        complete_snapshots=complete_n,complete_yes_snapshots=complete_yes,complete_no_snapshots=complete_no,
        duplicate_snapshots=duplicates,missing_leg_snapshots=missing_n,invalid_local_time_snapshots=local_invalid,
        first_capture_utc=first_time,last_capture_utc=last_time,metadata=meta,condition_order=conditions,
        tick_size_row_counts=dict(ticks),minimum_size_row_counts=dict(minimums),
        timing=dict(source_span_s=spans.report(),source_minus_capture_s=offsets.report(),capture_gap_s=gaps.report(),
                    quantile_resolution='nearest 1ms below 1s, 10ms below 60s, 1s below 1h, 60s thereafter'),
        counts=[dict(q=q,route=r,**{m:counts[(q,r,m)] for m in METRICS}) for q in SIZES for r in ROUTES],
        source_windows=[dict(q=q,route=r,window_s=w,**{m:windows[(q,r,w,m)] for m in ('tested','within_window','positive_lower','positive_upper')})
                        for q in SIZES for r in ROUTES for w in WINDOWS],
        best_cases_unrestricted=[x[2] for x in sorted(heaps[False],reverse=True)],
        best_cases_span1=[x[2] for x in sorted(heaps[True],reverse=True)],
        seconds=time.monotonic()-start,input_sha256=hashes[0],
        source_stat=dict(bytes=stat1.st_size,mtime_ns=stat1.st_mtime_ns),
        max_group_rows=max_group_rows,version=VERSION,script_sha256=sha(Path(__file__)))

def selftest():
    import random
    from unittest.mock import patch
    meta={'0':('lte',10.,10.,'C','below'),'1':('eq',11.,11.,'C','middle'),'2':('gte',12.,12.,'C','above')}
    assert partition(meta)[0]
    assert not partition({k:v for k,v in meta.items() if k!='1'})[0]
    assert not partition(dict(meta,**{'0':('lte',9.,10.,'C','bad tail')}))[0]
    def rejects(fn,exc=ValueError):
        try:fn()
        except exc:return
        raise AssertionError('expected rejection')
    rejects(lambda:date_slug('highest-temperature-in-toronto-on-october-15-2026'))
    rejects(lambda:epoch('2026-08-01T12:00:00'))
    rejects(lambda:reviewed_commit(None));rejects(lambda:reviewed_commit('g'*40))
    rejects(lambda:bounded('0',1,30));rejects(lambda:bounded('1001',1,1000))
    quota=OutputQuota(5);quota.consume(4);rejects(lambda:quota.consume(2),OutputLimit);assert quota.remaining==1
    timer=RunBudget(1,False);timer.deadline=0;rejects(timer.check,BudgetExpired)
    fixture=[];slug='highest-temperature-in-toronto-on-august-1-2026'
    for sec in (0,30):
      t=f'2026-08-01T12:00:{sec:02d}+00:00'
      for c,m in meta.items():
       for side in ('Yes','No'):
        row=dict(captured_at_utc=t,captured_at_local=f'2026-08-01T08:00:{sec:02d}-04:00',event_slug=slug,market_id='toronto',condition_id=c,outcome=side,
          clob_token_id=c+side,bin_kind=m[0],bin_value=m[1],bin_value_hi=m[2],unit=m[3],range_label=m[4],
          book_timestamp=epoch(t)*1000,min_order_size=5,tick_size=.01,neg_risk=True,
          best_ask=.2 if side=='Yes' else .8,best_bid=.19 if side=='Yes' else .79,
          ask_size_at_best=200,bid_size_at_best=200,ask_depth_all=200,bid_depth_all=200)
        for q in (10,100):row.update({f'buy_vwap_{q}':row['best_ask'],f'sell_vwap_{q}':row['best_bid'],f'buy_fillable_{q}':q,f'sell_fillable_{q}':q})
        fixture.append(row)
    saved_out=globals()['OUT']
    with tempfile.TemporaryDirectory(prefix='selftest-v3-',dir=OUT) as tmp:
      td=Path(tmp);globals()['OUT']=td
      try:
        def case(rows,name):
            root=td/name;root.mkdir();dest=root/EVENT_DIR;dest.mkdir();f=root/'fixture.csv'
            write_rows(f,rows,tuple(fixture[0]))
            item=dict(event=slug,date='2026-08-01',city='toronto',path=str(f),bytes=f.stat().st_size)
            return run_event(item,dest),dest,item
        def metric(b,q,route,key):return next(x for x in b['counts'] if x['q']==q and x['route']==route)[key]
        b,dest,item=case(fixture,'base')
        assert b['complete_snapshots']==2 and metric(b,10,'buy_yes','positive_span1')==2
        with gzip.open(dest/(slug+'.csv.gz'),'rt',encoding='utf-8',newline='') as f:
            kept=list(csv.DictReader(f))
        assert len(kept)==b['retained_rows'] and b['omitted_rows']>0
        assert all(int(r['capture_index']) in (0,1) and ((r['eligible']=='True' and float(r['fee_net_upper'])>1e-8) or (r['span1_fee_net_upper'] and float(r['span1_fee_net_upper'])>1e-8)) for r in kept)
        assert metric(b,10,'buy_yes','positive_next_sample')==1
        assert abs(evaluate(Frame({(r['condition_id'],r['outcome']):r for r in fixture[:6]},list(meta)),10)['buy_yes']['fee_net_lower']-3.76)<1e-8
        assert all(x['valid']==0 for x in b['counts'] if x['q']==1)
        globals()['OUT']=dest.parent
        summary=aggregate([item],quiet=True)
        assert summary['completed'] and summary['events']==1 and summary['snapshots']==2
        assert summary['verified_executable_opportunities'] is None
        globals()['OUT']=td
        # Completed payloads are immutable and hash-verified, including before aggregation.
        hp=dest/(slug+'.hours.csv');hp.write_bytes(hp.read_bytes()+b'corrupt')
        rejects(lambda:verify_event(dest,slug))
        globals()['OUT']=dest.parent;rejects(lambda:aggregate([item],quiet=True));globals()['OUT']=td
        missing=[dict(r) for r in fixture if r['condition_id']!='1']
        b,_,_=case(missing,'missing-band')
        assert not b['partition'] and metric(b,10,'buy_yes','valid')==0 and metric(b,10,'buy_pair','valid')==2
        b,_,_=case([dict(r) for r in fixture if not(r['outcome']=='No' and r['condition_id']=='1')],'missing-no')
        assert metric(b,10,'buy_yes','positive_span1')==2 and b['complete_snapshots']==0
        unrelated=[dict(r) for r in fixture]
        for r in unrelated:
            if r['outcome']=='No':r.update(min_order_size=1000,tick_size=.1,book_timestamp=r['book_timestamp']+5000)
        b,_,_=case(unrelated,'unselected-constraints');assert metric(b,10,'buy_yes','positive_span1')==2
        b,_,_=case([fixture[0]]+fixture,'duplicate');assert b['duplicate_snapshots']==1 and metric(b,10,'buy_yes','positive_span1')==1
        badlocal=[dict(r,captured_at_local='2026-08-01T12:00:00') for r in fixture]
        b,_,_=case(badlocal,'local-naive');assert b['invalid_local_time_snapshots']==2
        walked=[dict(r) for r in fixture]
        for r in walked:
            if r['outcome']=='Yes':r.update(ask_size_at_best=40,buy_vwap_100=.26)
        b,d,_=case(walked,'walked')
        with gzip.open(d/(slug+'.csv.gz'),'rt',encoding='utf-8',newline='') as f:
            r=next(r for r in csv.DictReader(f) if r['q']=='100' and r['route']=='buy_yes')
            assert float(r['fee_net_lower'])<19.15<float(r['fee_net_upper'])
        for r in walked:
            if r['outcome']=='Yes':r['buy_fillable_100']=95
        b,_,_=case(walked,'partial');assert metric(b,100,'buy_yes','valid')==0
        small=[dict(r) for r in fixture]
        for r in small:
            if r['outcome']=='Yes':r.update(ask_size_at_best=5,buy_vwap_10=.4)
            else:r.update(bid_size_at_best=5,sell_vwap_10=.65)
        b,_,_=case(small,'min-lot');assert metric(b,5,'ANY','positive_span1')==2 and metric(b,10,'ANY','positive_span1')==0
        # Inject a publication interruption: no completion JSON; retry retains orphan payload.
        root=td/'interrupt';root.mkdir();dest=root/EVENT_DIR;dest.mkdir();f=root/'fixture.csv';write_rows(f,fixture,tuple(fixture[0]))
        item=dict(event=slug,date='2026-08-01',city='toronto',path=str(f),bytes=f.stat().st_size)
        real_replace=os.replace
        def fail_replace(src,dst):
            if Path(dst)==dest/(slug+'.hours.csv'):raise OSError('injected publish failure')
            return real_replace(src,dst)
        with patch.object(os,'replace',fail_replace):rejects(lambda:run_event(item,dest),OSError)
        assert not (dest/(slug+'.json')).exists()
        run_event(item,dest);assert list(dest.glob('orphan-*'))
        rejects(lambda:verify_event(dest,slug,'0'*64))
        # Two-pass identity check rejects changed input bytes before publication.
        root=td/'changed';root.mkdir();dest=root/EVENT_DIR;dest.mkdir();f=root/'fixture.csv';write_rows(f,fixture,tuple(fixture[0]));item=dict(item,path=str(f))
        real_captures=captures;calls=[0]
        def changed_capture(path,hashed=None):
            calls[0]+=1
            yield from real_captures(path,hashed)
            if calls[0]==2:hashed[-1]='changed'
        with patch.dict(globals(),captures=changed_capture):rejects(lambda:run_event(item,dest))
        assert not (dest/(slug+'.json')).exists()
        root=td/'header';root.mkdir();bad=root/'bad.csv';bad.write_text('winner,outcome'+chr(10)+'Yes,Yes'+chr(10))
        rejects(lambda:list(captures(bad)))
      finally:globals()['OUT']=saved_out
    # Independently enumerate all subsets inside each window, for both fee bounds.
    rng=random.Random(30010);checks=0
    for n in range(2,6):
      for trial in range(24):
        rows={}
        for i in range(n):
          for side in ('Yes','No'):
            r=dict(fixture[0],condition_id=str(i),outcome=side,clob_token_id=str(i)+side,
                best_ask=rng.randint(20,90)/100,best_bid=rng.randint(10,19)/100,
                book_timestamp=100000+rng.choice((0,500,1500,5000)),min_order_size=rng.choice((5,5,20)))
            r.update(ask_size_at_best=5,bid_size_at_best=5,buy_fillable_10=10,sell_fillable_10=10,
                buy_vwap_10=min(.99,r['best_ask']+.03),sell_vwap_10=max(.01,r['best_bid']-.03))
            rows[(str(i),side)]=r
        frame=Frame(rows,[str(i) for i in range(n)])
        yb,ys,nb,ns=frame.legs(10)
        for window in (None,1,5):
          got=evaluate(frame,10,True,window=window,diagnostics=False)
          for kind,first,second in (('convert_subset',ys,nb),('buy_yes_mixed',yb,ns)):
            brute=[]
            for choose in itertools.product((False,True),repeat=n):
                if kind=='convert_subset' and not any(choose):continue
                legs=[(second[i],kind=='convert_subset') if c else (first[i],kind!='convert_subset') for i,c in enumerate(choose)]
                value=pnl(legs,sum(choose)-1 if kind=='convert_subset' else 1-sum(choose),10)
                if value and value['eligible'] and (window is None or value['source_span_s']<=window):brute.append(value)
            value=got[kind]
            assert bool(value)==bool(brute),(n,trial,window,kind)
            if brute:
                assert abs(value['fee_net_lower']-max(v['fee_net_lower'] for v in brute))<1e-9
                assert abs(value['fee_net_upper']-max(v['fee_net_upper'] for v in brute))<1e-9
            checks+=1
    # A better unconstrained conversion must not hide a profitable timely alternative.
    rows={(r['condition_id'],r['outcome']):dict(r) for r in fixture[:6]}
    for (c,side),r in rows.items():
        if side=='Yes':r['best_bid']=.41
        else:r['best_ask']={'0':.05,'1':.6,'2':.8}[c]
        if c=='0' and side=='No':r['book_timestamp']+=5000
    frame=Frame(rows,list(meta));raw=evaluate(frame,10)['convert_subset'];timely=evaluate(frame,10,window=1)['convert_subset']
    assert raw['source_span_s']>1 and timely['source_span_s']<=1 and timely['fee_net_lower']>0
    for buy in (False,True):
        p1,p2,w=.2,.7,.3;v=w*p1+(1-w)*p2;actual=.05*(w*p1*(1-p1)+(1-w)*p2*(1-p2))
        lower=.05*p1*(1-v) if buy else .05*v*(1-p2)
        assert lower<=actual<=.05*v*(1-v)
    memory=peak_memory()
    if memory:assert max(memory.values())<500*1024**2,'light selftest exceeds memory bound'
    print('PASS v4 light synthetic pipeline, integrity/interruption, embargo/header, selected-leg eligibility, constrained subset enumeration checks='+str(checks)+' '+json.dumps(memory),flush=True)


def aggregate(expected_items=None,quiet=False):
    items=load_plan() if expected_items is None else expected_items
    dest=OUT/EVENT_DIR
    paths=sorted(dest.glob('*.json'))
    if {p.stem for p in paths}!={x['event'] for x in items}:
        raise ValueError('incomplete or unexpected event set; no aggregate verdict')
    wanted=sha(Path(__file__))
    # Verify every input result before creating any countable aggregate.
    for p in paths:
        check_budget();verify_event(dest,p.stem,wanted)
    stage=OUT/('.aggregate-'+uuid.uuid4().hex);stage.mkdir()
    try:
        summary=_aggregate(paths,dest,stage,wanted)
        check_budget()
        payloads=sorted(p for p in stage.iterdir() if p.is_file())
        summary['artifacts']={p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in payloads}
        summary['completed']=True
        dump(stage/'summary.json',summary)
        old=[OUT/p.name for p in payloads if (OUT/p.name).exists()]
        if (OUT/'summary.json').exists():old.append(OUT/'summary.json')
        if old:
            archive=OUT/('aggregate-prior-'+uuid.uuid4().hex);archive.mkdir()
            for p in old:os.replace(p,archive/p.name)
        for p in payloads:os.replace(p,OUT/p.name)
        os.replace(stage/'summary.json',OUT/'summary.json')
        try:stage.rmdir()
        except OSError:pass
        if not quiet:print(json.dumps({k:v for k,v in summary.items() if k not in
            ('timing_by_event','counts','best_span1','best_unrestricted','duration_by_route','artifacts')}),flush=True)
        return summary
    except BaseException as exc:
        dump(stage/'FAILED.json',dict(recorded_utc=stamp(),error_type=type(exc).__name__,error=str(exc),countable=False),teardown=True)
        raise


def _aggregate(paths,source,dest,wanted):
    totals=Counter();windows=Counter();bycity=Counter();bydate=Counter();byhour=Counter();bylocal=Counter()
    coverage=[];best={False:[],True:[]};serial=0;timing=[]
    hdr=('city','date','capture_day_utc','hour_utc','capture_day_local','hour_local','q','route')+METRICS
    with output_text(dest/'counts_city_date_hour.csv') as detail:
        writer=csv.DictWriter(detail,fieldnames=hdr);writer.writeheader()
        for p in paths:
            check_budget();b=verify_event(source,p.stem,wanted)
            stat=Path(b['path']).stat()
            if b['source_stat']!={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}:
                raise ValueError('input metadata changed since capture scan: '+b['event'])
            keys=('event','date','city','rows','snapshots','bands','partition','partition_reason','complete_snapshots',
                  'complete_yes_snapshots','complete_no_snapshots','missing_leg_snapshots','duplicate_snapshots',
                  'invalid_local_time_snapshots','first_capture_utc','last_capture_utc')
            coverage.append({k:b[k] for k in keys});timing.append(dict(event=b['event'],**b['timing']))
            for x in b['counts']:
                for m in METRICS:totals[(x['q'],x['route'],m)]+=x[m]
            for x in b['source_windows']:
                for m in ('tested','within_window','positive_lower','positive_upper'):
                    windows[(x['q'],x['route'],x['window_s'],m)]+=x[m]
            with (source/(b['event']+'.hours.csv')).open(newline='',encoding='utf-8') as f:
                for record in csv.DictReader(f):
                    writer.writerow(record)
                    for m in METRICS:
                        for key,counter in ((record['city'],bycity),(record['date'],bydate),(record['hour_utc'],byhour)):
                            counter[(key,int(record['q']),record['route'],m)]+=int(record[m])
                        bylocal[(record['city'],record['hour_local'],int(record['q']),record['route'],m)]+=int(record[m])
            for strict,key in ((False,'best_cases_unrestricted'),(True,'best_cases_span1')):
                for record in b[key]:
                    serial+=1;entry=(record['fee_net_lower'],serial,record);heap=best[strict]
                    if len(heap)<100:heapq.heappush(heap,entry)
                    elif entry[:2]>heap[0][:2]:heapq.heapreplace(heap,entry)
    def counter_rows(counter,dimensions,metrics):
        return [dict(zip(dimensions,key),**{m:counter[key+(m,)] for m in metrics}) for key in sorted({x[:-1] for x in counter})]
    totalrows=counter_rows(totals,('q','route'),METRICS)
    write_rows(dest/'counts_routes.csv',totalrows,('q','route')+METRICS)
    ws=('tested','within_window','positive_lower','positive_upper')
    write_rows(dest/'counts_source_windows.csv',counter_rows(windows,('q','route','window_s'),ws),('q','route','window_s')+ws)
    for name,counter in (('city',bycity),('date',bydate),('hour_utc',byhour)):
        write_rows(dest/('counts_'+name+'.csv'),counter_rows(counter,(name,'q','route'),METRICS),(name,'q','route')+METRICS)
    write_rows(dest/'counts_city_hour_local.csv',counter_rows(bylocal,('city','hour_local','q','route'),METRICS),('city','hour_local','q','route')+METRICS)
    write_rows(dest/'event_coverage.csv',coverage,tuple(coverage[0]))
    case_fields=('event','date','city','captured_at_utc','q','route','source_window_s')+RESULT_FIELDS
    for strict,name in ((False,'best_unrestricted'),(True,'best_source_span_1s')):
        write_rows(dest/(name+'.csv'),[x[2] for x in sorted(best[strict],reverse=True)],case_fields)
    duration_stats={};locations={r['event']:(r['date'],r['city']) for r in coverage}
    episode_fields=('event','date','city','q','route','first','last','observations','best_net_lower','sampled_span_s','continuous_duration_lower_s')
    with output_text(dest/'sampled_episodes.csv.gz',compressed=True) as text:
        writer=csv.DictWriter(text,fieldnames=episode_fields);writer.writeheader()
        for path in sorted(source.glob('*.episodes.csv')):
            check_budget()
            with path.open(newline='',encoding='utf-8') as f:
                for record in csv.DictReader(f):
                    record['date'],record['city']=locations[record['event']];writer.writerow(record)
                    key=(int(record['q']),record['route'])
                    if key not in duration_stats:duration_stats[key]=dict(episodes=0,multi_sample_episodes=0,spans=Distribution())
                    s=duration_stats[key];s['episodes']+=1;s['multi_sample_episodes']+=int(record['observations'])>1
                    s['spans'].add(float(record['sampled_span_s']))
    duration_rows=[dict(q=q,route=route,episodes=s['episodes'],multi_sample_episodes=s['multi_sample_episodes'],
                   sampled_span_s=s['spans'].report(),continuous_duration_lower_s=0) for (q,route),s in sorted(duration_stats.items())]
    return dict(recorded_utc=stamp(),script_sha256=wanted,version=VERSION,events=len(coverage),
        rows=sum(c['rows'] for c in coverage),snapshots=sum(c['snapshots'] for c in coverage),
        complete_snapshots=sum(c['complete_snapshots'] for c in coverage),partition_valid_event_days=sum(c['partition'] for c in coverage),
        cities=sorted({c['city'] for c in coverage}),dates=sorted({c['date'] for c in coverage}),counts=totalrows,
        best_span1=[x[2] for x in sorted(best[True],reverse=True)[:8]],
        best_unrestricted=[x[2] for x in sorted(best[False],reverse=True)[:8]],
        fee_convention='Task-specified continuous 0.05*p*(1-p), collateral fees, no maker fees; adapter fee=0 optimistic screen',
        measured_end_to_end_latency_s=None,true_simultaneity_window_s=None,verified_executable_opportunities=None,
        g2='No executable G2 verdict from these summaries alone: receipt timing, measured latency and historical terms require verification',
        timing_by_event=timing,duration_by_route=duration_rows)

def reviewed_commit(value):
    if value is None or not re.fullmatch(r'[0-9a-f]{40}',value):
        raise ValueError('master GO required; supply its reviewed 40-hex commit explicitly')
    return value

def compare_reproduction(items=None):
    """Compare a real rerun; the original event artifacts are never reused."""
    items=load_plan() if items is None else items
    old_root=LEGACY_OUT/'stream_events_v4'
    new_root=OUT/EVENT_DIR
    prior=json.loads((LEGACY_OUT/'B012-report-20261107T044205124951Z'/'summary.json').read_text(encoding='utf-8-sig'))
    inputs={Path(x['path']).stem:x for x in prior['inputs']}
    if prior['events']!=393 or set(inputs)!={p['event'] for p in items[:393]}:
        raise ValueError('original 393-event report identity mismatch')
    skipped={'version','script_sha256','seconds','artifacts'}
    totals=Counter();matches=[];wanted=sha(Path(__file__))
    for item in items[:393]:
        check_budget();event=item['event'];date_slug(event)
        old_path=old_root/(event+'.json')
        if Path(inputs[event]['path'])!=old_path or sha(old_path)!=inputs[event]['sha256']:
            raise ValueError('original report input hash mismatch: '+event)
        old=json.loads(old_path.read_text(encoding='utf-8'))
        new=verify_event(new_root,event,wanted)
        if old['script_sha256']!=LEGACY_SHA or old['version']!='stream_v4_b012' or not old['completed']:
            raise ValueError('original scan pin mismatch')
        if {k:v for k,v in old.items() if k not in skipped}!={k:v for k,v in new.items() if k not in skipped}:
            raise ValueError('deterministic event results differ: '+event)
        if old['artifacts']!=new['artifacts']:raise ValueError('artifact manifests differ: '+event)
        for name,info in old['artifacts'].items():
            if Path(name).name!=name or sha(old_root/name)!=info['sha256']:
                raise ValueError('original artifact changed: '+event)
        totals['rows']+=new['rows'];totals['captures']+=new['snapshots']
        q=next(r for r in new['counts'] if r['q']==10 and r['route']=='ANY')
        totals['positive_captures']+=q['positive_span1']
        with (new_root/(event+'.episodes.csv')).open(encoding='utf-8',newline='') as handle:
            totals['consecutive_episodes']+=sum(r['q']=='10' and r['route']=='ANY' for r in csv.DictReader(handle))
        matches.append(dict(event=event,old_json_sha256=sha(old_path),new_json_sha256=sha(new_root/(event+'.json'))))
    expected=dict(rows=32267972,captures=1466726,positive_captures=16,consecutive_episodes=10)
    if dict(totals)!=expected:raise ValueError('original headline mismatch')
    receipt=dict(status='PASS',recorded_utc=stamp(),script_sha256=wanted,events=393,
                 exact_deterministic_json=True,byte_identical_artifacts=True,totals=dict(totals),matches=matches)
    dump(OUT/'reproduction.json',receipt)
    return receipt

def require_reproduction():
    p=OUT/'reproduction.json'
    receipt=json.loads(p.read_text(encoding='utf-8'))
    if receipt.get('status')!='PASS' or receipt.get('script_sha256')!=sha(Path(__file__)) or receipt.get('events')!=393:
        raise ValueError('exact-script 393-event reproduction required before remaining days')
    expected={item['event'] for item in load_plan()[:393]}
    if len(receipt['matches'])!=393 or {m['event'] for m in receipt['matches']}!=expected:
        raise ValueError('reproduction must cover the original 393 distinct events')
    for match in receipt['matches']:
        if sha(OUT/EVENT_DIR/(match['event']+'.json'))!=match['new_json_sha256']:
            raise ValueError('reproduced event changed')

def completion_statistics(summary):
    daily={};positives=0;episodes=0
    for item in load_plan():
        b=verify_event(OUT/EVENT_DIR,item['event'])
        q=next(r for r in b['counts'] if r['q']==10 and r['route']=='ANY')
        day=daily.setdefault(item['date'],dict(events=0,positive_events=0,positive_captures=0))
        day['events']+=1;day['positive_events']+=int(q['positive_span1']>0)
        day['positive_captures']+=q['positive_span1'];positives+=q['positive_span1']
        with (OUT/EVENT_DIR/(item['event']+'.episodes.csv')).open(encoding='utf-8',newline='') as handle:
            episodes+=sum(r['q']=='10' and r['route']=='ANY' for r in csv.DictReader(handle))
    fractions=[v['positive_events']/v['events'] for _,v in sorted(daily.items())]
    rng=random.Random(20261110);n=len(fractions)
    draws=sorted(sum(rng.choices(fractions,k=n))/n for _ in range(2000))
    def quantile(p):
        index=(len(draws)-1)*p;left=math.floor(index);right=math.ceil(index)
        return draws[left]+(index-left)*(draws[right]-draws[left])
    result=dict(status='MEASURED',effective_dates=n,event_days=summary['events'],
        q10_any_positive_captures=positives,consecutive_episodes=episodes,by_date=daily,
        mean_daily_positive_event_fraction=sum(fractions)/n,
        descriptive_date_clustered_95_interval=[quantile(.025),quantile(.975)],draws=2000,seed=20261110,
        verdict='KILL' if positives==0 else 'DESCRIBE',
        scope='finite q10 one-second summary screen only; execution and latency unverified; no edge claim',
        excluded_guarded_event_days=180,prereg_sha256=sha(OUT.parent/'PREREG.md'))
    dump(OUT/'completion_statistics.json',result)
    return result


def bounded(value,low,high):
    v=int(value)
    if not low<=v<=high:raise ValueError(f'argument must be in [{low},{high}]')
    return v

def execution_seconds(now=None):
    """Master continuation: morning cutoff, or after 19:00 on Nov 10 only."""
    current=datetime.now(timezone.utc) if now is None else now
    local=current.astimezone(ZoneInfo('America/Toronto'))
    if local.date().isoformat()!='2026-11-10':
        raise ValueError('T085 continuation is authorized for November 10 only')
    if (local.hour,local.minute)<(8,30):
        deadline=datetime(2026,11,10,13,25,tzinfo=timezone.utc)
    elif local.hour>=19:
        deadline=datetime(2026,11,11,5,0,tzinfo=timezone.utc)
    else:
        raise ValueError('no heavy starts 08:30..19:00 Toronto')
    return math.floor((deadline-current).total_seconds())-120


def main():
    global BUDGET,QUOTA
    p=argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument('mode',choices=('selftest','inventory','scan','compare','aggregate'))
    p.add_argument('--start',type=lambda s:bounded(s,0,10000),default=0)
    p.add_argument('--count',type=lambda s:bounded(s,1,30),default=30)
    p.add_argument('--max-seconds',type=lambda s:bounded(s,1,1000),default=1000)
    p.add_argument('--reviewed-commit')
    args=p.parse_args()
    if args.mode=='selftest':selftest();return 0
    if args.mode=='inventory':dump(OUT/'inventory_v4.json',load_plan());return 0
    go=reviewed_commit(args.reviewed_commit)  # assertion is passed only after the master's explicit GO
    if os.environ.get('WEATHER_WORKSTATION_WRAPPER_ACTIVE')!='1':raise RuntimeError('heavy wrapper admission required')
    if sha(OUT.parent/'PREREG.md')!=PREREG_SHA:raise ValueError('frozen preregistration changed')
    if HOLD.exists():print('HOLD_HEAVY: no payload read',flush=True);return 76
    remaining=execution_seconds()
    if remaining<=0:print('task deadline reserve: no further payload read',flush=True);return 77
    BUDGET=RunBudget(min(args.max_seconds,remaining))
    existing=sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    QUOTA=OutputQuota(2*1024**3-64*1024**2-existing)
    if QUOTA.remaining<=0:raise OutputLimit('task quota is already exhausted')
    receipt=dict(started_utc=stamp(),script_sha256=sha(Path(__file__)),version=VERSION,
                 reviewed_commit=go,argv=sys.argv,slot=os.environ.get('WEATHER_WORKSTATION_WRAPPER_SLOT'),events=[])
    rp=OUT/f"v4-receipt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{args.mode}-{args.start:04d}.json"
    code=0
    try:
        if args.mode=='compare':
            compare_reproduction()
        elif args.mode=='aggregate':
            require_reproduction()
            summary=aggregate()
            completion_statistics(summary)
            receipt['aggregate_completed']=summary['completed']
        else:
            items=load_plan()
            if args.start>=len(items):raise ValueError('start is outside the fixed input plan')
            if args.start+args.count>393:require_reproduction()
            dest=OUT/EVENT_DIR;dest.mkdir(exist_ok=True)
            for item in items[args.start:args.start+args.count]:
                check_budget()
                b=run_event(item,dest)
                receipt['events'].append(dict(event=item['event'],input_sha256=b['input_sha256'],artifacts=b['artifacts']))
                receipt['updated_utc']=stamp();dump(rp,receipt,teardown=True)
                print(f"{item['event']} rows={b['rows']} snapshots={b['snapshots']} complete={b['complete_snapshots']} sec={b['seconds']:.2f}",flush=True)
    except HoldRequested as exc:
        receipt['stop_reason']=str(exc);code=76
    except BudgetExpired as exc:
        receipt['stop_reason']=str(exc);code=78  # bounded partial chunk; published events remain verified
    except BaseException as exc:
        receipt['error_type']=type(exc).__name__;receipt['error']=str(exc);receipt['failed']=True
        code=65
        print(f"T003 NOT INTERPRETABLE: {type(exc).__name__}: {exc}",file=sys.stderr,flush=True)
    finally:
        receipt['finished_utc']=stamp();receipt['memory']=peak_memory()
        dump(rp,receipt,teardown=True)
    return code


if __name__=='__main__':
    raise SystemExit(main())
