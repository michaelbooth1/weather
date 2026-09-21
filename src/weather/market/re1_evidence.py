"""Immutable RE-1M attempt counting, prediction replay and payout interpretation."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new
from weather.market.mm_exchange_reports import reconcile_incentive_payments
from weather.market.re1_attended import MAX_SESSIONS, LAST_DAY, observe, number
from weather.operations.live_path_security import validate_nonreparse_directory, validate_regular_nonreparse_file
from weather.paths import REPO_ROOT


def campaign_root():
    # Fixed across worktrees, tips and CLI invocations. No override for live.
    return Path.home() / '.weather-re1m-20260921'


@contextmanager
def live_mutex():
    """Share the host's heavy/live exclusion without claiming a sealed profile."""
    if os.name != 'nt': raise RuntimeError('live_requires_assigned_windows_workstation')
    command = "& { param($root) . (Join-Path $root 'scripts/ops/workload_admission.ps1'); @{host_id=(Get-WeatherExecutionHostId); principal_id=(Get-WeatherExecutionPrincipalId)} | ConvertTo-Json -Compress }"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command, str(REPO_ROOT)],
                            capture_output=True, text=True, check=True, timeout=20)
    facts = json.loads(result.stdout)
    assignment = json.loads((REPO_ROOT / 'config/international_live_execution_host.json').read_bytes())
    if (assignment['assignment_status'] != 'ASSIGNED' or facts['host_id'] == assignment['dedicated_capture_execution_host_id'] or
            facts['host_id'] != assignment['active_portable_execution_host_id'] or
            facts['principal_id'] != assignment['active_portable_execution_principal_id']):
        raise RuntimeError('wrong_workstation_or_principal')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Global\\WeatherProjectHeavyWorkloadV1')
    if not handle: raise RuntimeError('host_mutex_unavailable')
    owned = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        owned = result in (0, 0x80)
        if result != 0: raise RuntimeError('host_mutex_busy_or_abandoned')
        if (Path(os.environ.get('ProgramData', 'C:/ProgramData')) / 'WeatherProject/heavy_workload_v1.poison').exists():
            raise RuntimeError('host_workload_recovery_required')
        yield
    finally:
        if owned: kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def reserve_attempt(root, *, now, selection_sha256):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    validate_nonreparse_directory(root)
    if utc(now).date().isoformat() > LAST_DAY:
        raise RuntimeError('campaign_expired')
    markers = sorted(root.glob('session-*.attempt.json'))
    if len(markers) >= MAX_SESSIONS:
        raise RuntimeError('three_session_cap')
    for i, marker in enumerate(markers, 1):
        validate_regular_nonreparse_file(marker)
        if marker.name != f'session-{i}.attempt.json' or json.loads(marker.read_bytes())['number'] != i:
            raise RuntimeError('campaign_count_corrupt')
        result_path = root / f'session-{i}' / 'prediction.json'
        result = load_prediction(result_path, now=now, require_later_day=False)
        if not result['cleanup_ok'] or result['fill_seen'] or not result['evidence_complete']:
            raise RuntimeError('prior_attempt_needs_owner_reconciliation')
    number_ = len(markers) + 1
    row = {'number': number_, 'created_at_utc': utc(now).isoformat(), 'selection_sha256': selection_sha256}
    write_new(root / f'session-{number_}.attempt.json', row)
    directory = root / f'session-{number_}'
    directory.mkdir(exist_ok=False)
    return directory, row


def load_prediction(path, *, now, require_later_day=True):
    path = validate_regular_nonreparse_file(path)
    prediction = json.loads(path.read_bytes())
    raw = validate_regular_nonreparse_file(path.parent / 'journal.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest() != prediction['journal_sha256']:
        raise ValueError('journal_hash')
    if (utc(prediction['frozen_at_utc']) > utc(now) or prediction['payout_read'] is not False or
            require_later_day and utc(now).date().isoformat() <= prediction['reward_day']):
        raise ValueError('prediction_not_frozen_on_prior_day')
    previous, rows, latest, samples = None, [], None, 0
    totals = dict(P_many=0.0, P_single=0.0, P_many_plain_mid=0.0, visible_two_sided_minutes=0)
    for i, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        at = utc(row['recorded_at_utc'])
        if (canonical_bytes(row) != line or row['sequence'] != i or row['previous_sha256'] != previous or
                latest is not None and at < latest):
            raise ValueError('journal_chain')
        previous, latest = hashlib.sha256(line).hexdigest(), at
        rows.append(row)
        if row['event'] == 'minute':
            samples += 1
            observed = observe(row['snapshot'], row['prices'])
            if observed != row['observation']: raise ValueError('minute_replay')
            if observed['visible_two_sided']:
                totals['visible_two_sided_minutes'] += 1
                for suffix in ('many', 'single', 'many_plain_mid'):
                    totals['P_' + suffix] += observed['per_minute_' + suffix]
            if any(not math.isclose(float(row[k]), v, abs_tol=1e-8) for k, v in totals.items()):
                raise ValueError('minute_totals')
    if (not rows or rows[0]['event'] != 'opened' or rows[-1]['event'] != 'terminal' or
            rows[0]['scope'] != prediction['scope'] or rows[0]['mode'] != prediction['mode'] or
            prediction['scope']['condition_id'] != prediction['condition_id'] or
            prediction['reward_day'] != utc(rows[0]['recorded_at_utc']).date().isoformat() or
            utc(prediction['frozen_at_utc']) < latest or prediction['minute_samples'] != samples or
            prediction['visible_two_sided_minutes'] > 360):
        raise ValueError('prediction_scope')
    for key in ('cleanup_ok', 'fill_seen', 'submits', 'requotes', 'reason', 'failure_type',
                'evidence_complete', 'reward_terms_changed', 'scoring_seen'):
        if prediction[key] != rows[-1][key]: raise ValueError('prediction_terminal')
    if any(not math.isclose(float(prediction[k]), v, abs_tol=1e-8) for k, v in totals.items()):
        raise ValueError('prediction_totals')
    return prediction


def payout_verdict(prediction, accrual, payment_evidence=None):
    """Frozen thresholds; missing cash provenance is INCONCLUSIVE, never paid."""
    p = number(prediction['P_many'])
    condition = prediction['condition_id']
    maker = prediction['scope']['maker_address'].lower()
    from weather.market.re1_transport import ASSETS
    accrued, by_asset, seen = number(0), {}, set()
    for row in accrual['rows']:
        if row['condition_id'] == condition:
            if row['maker_address'].lower() != maker or utc(row['date']).date().isoformat() != prediction['reward_day']:
                raise ValueError('earnings_scope')
            asset = row['asset_address'].lower()
            amount, rate = number(row['earnings']), number(row['asset_rate'])
            if asset not in {a.lower() for a in ASSETS} or asset in seen or amount < 0 or rate <= 0:
                raise ValueError('earnings_asset_or_duplicate')
            seen.add(asset)
            by_asset[asset] = {'earnings': str(amount), 'asset_rate': str(rate)}
            accrued += amount * rate
    paid, payment = None, None
    if payment_evidence is not None:
        payment = reconcile_incentive_payments(payment_evidence)
        scope = payment.get('scope') or {}
        start = utc(prediction['reward_day'] + 'T00:00:00Z')
        if (payment['valid'] and payment['complete'] and scope.get('condition_id') == condition and
                scope.get('maker_address', '').lower() == maker and
                utc(scope['accrual_start_utc']) == start and utc(scope['accrual_end_utc']) == start + timedelta(days=1)):
            paid = number(payment['actual_liquidity_reward_usdc'])
    k = paid / p if paid is not None and p > 0 else None
    adequate = (prediction['mode'] == 'live' and prediction['evidence_complete'] and prediction['cleanup_ok'] and
                prediction['scoring_seen'] and not prediction['reward_terms_changed'] and
                prediction['visible_two_sided_minutes'] >= 180)
    decision = 'INCONCLUSIVE'
    if adequate and k is not None:
        if k >= number('.5'): decision = 'PAID_AS_MODELLED'
        elif number('.1') <= k < number('.5'): decision = 'PAID_DILUTED'
        elif paid == 0 and p >= 2: decision = 'NOT_PAID'
    return {'verdict': decision, 'paid': None if paid is None else str(paid), 'k': None if k is None else str(k),
            'accrued': str(accrued), 'k_accrued': str(accrued / p) if p > 0 else None,
            'earnings_by_asset': by_asset, 'accrued_basis': 'venue_reported_asset_rate',
            'payment_reconciliation': payment, 'prediction_sha256': digest(prediction)}
