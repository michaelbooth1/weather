"""Light output-only diagnosis; no source book reads and no 393-day PASS."""
from pathlib import Path
import hashlib,json
from datetime import datetime,timezone

out=Path(r'C:\t\codex\T085\out')
old_root=Path(r'C:\t\codex\T003\out\stream_events_v4')
new_root=out/'stream_events_v4'
plan=json.loads(Path(r'C:\t\codex\T003\out\inventory.json').read_text(encoding='utf-8-sig'))[:30]
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
ignore={'index','city','version','script_sha256','seconds','artifacts'}
checks=[]
for item in plan:
    name=item['event']+'.json';old=read(old_root/name);new=read(new_root/name)
    assert set(old)-set(new)=={'city'} and set(new)-set(old)=={'index'}
    assert {k:v for k,v in old.items() if k not in ignore}=={k:v for k,v in new.items() if k not in ignore}
    assert old['artifacts']==new['artifacts']
    for artifact,binding in old['artifacts'].items():
        assert sha(old_root/artifact)==sha(new_root/artifact)==binding['sha256']
    checks.append(dict(event=item['event'],old_json_sha256=sha(old_root/name),r1_json_sha256=sha(new_root/name)))
result=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),status='METADATA_MISMATCH; not a registered reproduction PASS',
    events=30,only_schema_differences=['city missing','index added'],
    all_other_deterministic_json_equal=True,all_artifacts_byte_identical=True,source_book_reads=0,
    checks=checks,script_sha256=sha(Path(__file__)))
(out/'r1_first30_diagnosis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'}))
