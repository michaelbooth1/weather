"""Exercise the external qualification boundary with complete synthetic evidence.

Guards: B018/T024 F1 requires exit zero AND a fresh exact-head PASS receipt,
matching full chunk logs/JUnit hashes and completed teardown.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.spawns, pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell boundary')]
HELPER = Path(__file__).resolve().parents[2] / 'scripts' / 'ops' / 'workstation_pregate_receipt.ps1'
HEAD = 'a' * 40
HARNESS = r'''
$ErrorActionPreference='Stop'
. $env:PG_HELPER
try {
    $receipt=[IO.File]::ReadAllText($env:PG_RECEIPT) | ConvertFrom-Json
    Assert-WeatherPregateReceipt -Receipt $receipt -ExpectedHead $env:PG_HEAD -ProcessExitCode ([int]$env:PG_EXIT) -NotBefore ([DateTimeOffset]$env:PG_NOT_BEFORE) | Out-Null
    [Console]::Out.WriteLine('QUALIFIED')
    exit 0
} catch { [Console]::Out.WriteLine('REFUSED'); exit 1 }
'''


@pytest.mark.parametrize('fault', [None, 'exit', 'head', 'stale', 'fail', 'missing_junit', 'junit_hash',
    'log_hash', 'no_verdict', 'chunk_exit', 'missing_chunk', 'junit_failed', 'junit_empty', 'string_cleanup'])
def test_receipt_qualification_requires_all_proofs(tmp_path, fault):
    now = datetime.now(timezone.utc)
    xml = tmp_path / 'suite.chunk-001.xml'
    xml.write_text('<testsuites><testsuite tests="1" errors="0" failures="0"><testcase name="closed"/></testsuite></testsuites>')
    log = tmp_path / 'suite.log'
    messages = ['planned chunks=1 files=1 max_files=25', f'chunk 1/1 starting files=1 junit={xml}',
                'chunk 1/1 exit=0', 'VERDICT: ALL CHUNKS PASSED (1/1); exact tip eligible for separate reviewed merge']
    receipt = dict(schema='weather.workstation_pregate_receipt.v1', head=HEAD, verdict='PASS', failure_reasons=[],
        driver_exit_code=0, worktree_removed=True, basetemp_removed=True,
        started_at=(now-timedelta(seconds=30)).isoformat(), finished_at=(now-timedelta(seconds=1)).isoformat(),
        chunk_plan=[['tests/test_closed.py']], chunks=[dict(ordinal=1, files=1, logged_files=1, exit_code=0)],
        inventory_files=1, max_files_per_chunk=25, skipped_host_checks=['replaced']*5,
        log_path=str(log), junit_paths=[str(xml)], junit_files=[dict(path=str(xml), sha256='')])
    code, expected = 0, HEAD
    if fault == 'exit': code = 1
    elif fault == 'head': expected = 'b'*40
    elif fault == 'stale': receipt['started_at'] = (now-timedelta(days=1)).isoformat()
    elif fault == 'fail': receipt['verdict'] = 'FAIL'
    elif fault == 'missing_junit': xml.unlink()
    elif fault == 'no_verdict': messages.pop()
    elif fault == 'chunk_exit': receipt['chunks'][0]['exit_code'] = 1
    elif fault == 'missing_chunk': receipt['chunks'] = []
    elif fault == 'junit_failed': xml.write_text('<testsuite tests="1" errors="0" failures="1"/>')
    elif fault == 'junit_empty': xml.write_text('<testsuite tests="0" errors="0" failures="0"/>')
    elif fault == 'string_cleanup': receipt['worktree_removed'] = 'True'
    log.write_text(''.join('0'*21+message+'\n' for message in messages))
    receipt['log_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest() if fault != 'log_hash' else '0'*64
    receipt['junit_files'][0]['sha256'] = hashlib.sha256(xml.read_bytes()).hexdigest() if xml.exists() else '0'*64
    if fault == 'junit_hash': receipt['junit_files'][0]['sha256'] = '0'*64
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(receipt))
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',HARNESS],
        env={**os.environ, 'PG_HELPER':str(HELPER), 'PG_RECEIPT':str(path), 'PG_HEAD':expected,
             'PG_EXIT':str(code), 'PG_NOT_BEFORE':(now-timedelta(minutes=1)).isoformat()},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == (0 if fault is None else 1), result.stdout+result.stderr
    assert result.stdout.strip() == ('QUALIFIED' if fault is None else 'REFUSED')
