"""Compatibility runner for T003's unchanged output-only reporting methods.

No original book payloads, network, new arm, threshold or economic calculation.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import types

OUT=Path(r'C:\t\codex\T085\out')
LEGACY=Path(r'C:\t\codex\T003\out')
SCAN_PIN='3174d1cac7f6da3229804b6d8e414fe4a437d3f380a07d5f05e2b673c3f7f70d'
PREREG_PIN='73e8b665437b837108f28325ad3b26dd8983c0498a4c6d7e5ae04533011df902'
POST_PIN='97dbc2864ba3aa1196cb57737729b0aaeed434834940042bfa3c8dd7f5715c91'
CROSS_PIN='0213c07aabde6da6dcd2293e25d1edf0a545cbc82b1d3d8f66367356b896e54d'

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1048576),b''):digest.update(block)
    return digest.hexdigest()

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def load_method(name,path,pin,replace_event_guard=False):
    if sha(path)!=pin:raise ValueError('frozen method source changed: '+str(path))
    source=path.read_text(encoding='utf-8')
    if replace_event_guard:
        # Only a task-output directory identity check changes; inspect(),
        # legs(), and every economic/episode computation stay byte-identical.
        before="(OUT/'stream_events_v4')"
        if source.count(before)!=1:raise ValueError('unexpected legacy path guard')
        source=source.replace(before,"(OUT/'stream_events_v4_r2')")
    module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(source,str(path),'exec'),module.__dict__)
    module.OUT=OUT
    return module

def methods():
    post=load_method('t003_post',LEGACY/'postprocess_b012.py',POST_PIN)
    cross=load_method('t003_cross',LEGACY/'retained_crossing_diagnostic.py',CROSS_PIN,True)
    cross.PIN=SCAN_PIN
    return post,cross

def prefix_control(post,source,plan):
    positive=0;joins=Counter()
    def emit(rule,event):joins[rule]+=1
    def observe(row,net,relative,is_positive):
        nonlocal positive
        positive+=is_positive
    for item in plan[:393]:
        with gzip.open(source/(item['event']+'.csv.gz'),'rt',encoding='utf-8',newline='') as handle:
            post.episodes(csv.DictReader(handle),emit,observe)
    expected={'120s':10,'consecutive_captures':10}
    if positive!=16 or dict(joins)!=expected:raise ValueError('original first-393 reporting numbers differ')
    return dict(events=393,positive_captures=positive,episodes=dict(joins),status='PASS')

def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--selftest',action='store_true')
    args=parser.parse_args()
    post,cross=methods()
    if args.selftest:
        post.selftest();cross.selftest()
        print('PASS frozen legacy source pins and output-root compatibility')
        return 0
    if os.environ.get('WEATHER_WORKSTATION_WRAPPER_ACTIVE')!='1':raise RuntimeError('canonical wrapper required')
    if (OUT.parent.parent/'HOLD_HEAVY').exists():raise RuntimeError('HOLD_HEAVY')
    if sha(OUT.parent/'PREREG.md')!=PREREG_PIN:raise ValueError('prereg changed')
    scanner=load_method('t085_scanner',OUT/'scan.py',SCAN_PIN)
    if scanner.execution_seconds()<=0:raise RuntimeError('execution reserve reached')
    scanner.require_reproduction()
    plan=scanner.load_plan();source=OUT/scanner.EVENT_DIR
    summary=read(OUT/'summary.json');stats=read(OUT/'completion_statistics.json')
    if len(plan)!=720 or summary.get('events')!=720 or not summary.get('completed'):
        raise ValueError('complete 720-event aggregate required')
    if summary.get('script_sha256')!=SCAN_PIN or stats.get('event_days')!=720:
        raise ValueError('aggregate script or scope mismatch')
    if {p.stem for p in source.glob('*.json')}!={item['event'] for item in plan}:
        raise ValueError('unexpected event universe')
    for item in plan:
        meta=scanner.verify_event(source,item['event'],SCAN_PIN)
        if not '2026-08-01'<=meta['date']<='2026-09-29':raise ValueError('EMBARGO before output valuation')
    control=prefix_control(post,source,plan)
    before=set(OUT.glob('B012-report-*'))
    saved=sys.argv
    try:
        sys.argv=[str(LEGACY/'postprocess_b012.py'),'--event-dir',scanner.EVENT_DIR]
        post.main()
        created=set(OUT.glob('B012-report-*'))-before
        if len(created)!=1:raise ValueError('report publication ambiguous')
        report=created.pop()
        sys.argv=[str(LEGACY/'retained_crossing_diagnostic.py'),'--report-dir',report.name]
        cross.main()
    finally:sys.argv=saved
    result=read(report/'summary.json')
    if result['headline']['snapshot_coincident_screen_positives']!=stats['q10_any_positive_captures']:
        raise ValueError('headline mismatch against registered statistic')
    if result['episodes']['120s']['episodes']!=stats['consecutive_episodes']:
        raise ValueError('legacy inline 120-second episode mismatch')
    receipt=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),status='PASS',
        adapter_sha256=sha(Path(__file__)),scan_sha256=SCAN_PIN,prereg_sha256=PREREG_PIN,
        original_postprocess_sha256=POST_PIN,original_crossing_sha256=CROSS_PIN,
        compatibility_changes=['task output root','diagnostic scan pin','diagnostic output-directory guard'],
        first393_reporting_control=control,report_dir=str(report),
        report_sha256=sha(report/'summary.json'),crossing_receipt_sha256=sha(report/'retained_crossing_receipt.json'),
        original_book_payload_reads=0,method='unchanged T003 eight-route q10 ANY headline, two episode joins and crossed-quote diagnostic')
    (OUT/'final_reporting_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))
    return 0

if __name__=='__main__':raise SystemExit(main())
