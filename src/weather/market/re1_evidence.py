"""Immutable RE-1M attempt counting, prediction replay and payout interpretation."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new, _order_id
from weather.market.re1_attended import MAX_SESSIONS, LAST_DAY, observe, number
from weather.operations.live_path_security import validate_nonreparse_directory, validate_regular_nonreparse_file
from weather.paths import REPO_ROOT


def campaign_root():
    # Fixed across worktrees, tips and CLI invocations. No override for live.
    if os.name != 'nt': raise RuntimeError('campaign_requires_windows_token')
    from weather.market.live_sdk_overlay import _windows_token_profile_root
    return _windows_token_profile_root() / '.weather-re1m-20260921'


@contextmanager
def live_mutex():
    """Share the host's heavy/live exclusion without claiming a sealed profile."""
    if os.name != 'nt': raise RuntimeError('live_requires_assigned_windows_workstation')
    command = "& { param($root) . (Join-Path $root 'scripts/ops/workload_admission.ps1'); @{host_id=(Get-WeatherExecutionHostId); principal_id=(Get-WeatherExecutionPrincipalId)} | ConvertTo-Json -Compress }"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command, str(REPO_ROOT)],
                            capture_output=True, text=True, timeout=20)
    try:
        facts = json.loads(result.stdout)
    except ValueError:
        facts = None
    if result.returncode != 0 or not isinstance(facts, dict) or not {'host_id', 'principal_id'} <= facts.keys():
        raise RuntimeError(f'host_identity_query_failed: rc={result.returncode} stderr={result.stderr[:200]}')
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


def attempt_state(marker, *, now):
    """Keep crashes/ambiguous posts conservative without charging proven no-post work."""
    marker = validate_regular_nonreparse_file(marker)
    attempt = json.loads(marker.read_bytes())
    directory = marker.parent / f"session-{attempt['number']}"
    intents = sorted(directory.glob('submit-*.intent.json'))
    known = [json.loads(validate_regular_nonreparse_file(p).read_bytes())['order_id']
             for p in sorted(directory.glob('submit-*.ack.json'))]
    result = None
    try:
        result = load_prediction(directory / 'prediction.json', now=now, require_later_day=False)
    except (OSError, ValueError, RuntimeError, KeyError):
        pass
    if result:
        known = result.get('order_ids', known)
        if result['scope'].get('protocol') != 'RE-1M-attended-84c':
            rows = [json.loads(line) for line in (directory / 'journal.jsonl').read_bytes().splitlines()]
            known = [_order_id(row['response']) for row in rows if row['event'] == 'submit_response' and _order_id(row['response'])]
    submitted = bool(intents) or bool(result and result.get('post_count', result['submits']))
    legacy_unknown = attempt.get('protocol') != 'RE-1M-attended-84c' and result is None
    blocked = legacy_unknown or submitted and (result is None or not result['cleanup_ok'] or result['fill_seen'] or
        result.get('unknown_submit', result['submits'] != len(known)) or not result.get('inventory_proven', True))
    return {'submitted': submitted or legacy_unknown, 'blocked': bool(blocked), 'order_ids': known,
            'attempt_sha256': digest(attempt), 'number': attempt['number'],
            'prediction_sha256': digest(result) if result else None,
            'intent_sha256': [hashlib.sha256(validate_regular_nonreparse_file(p).read_bytes()).hexdigest() for p in intents]}


ATTEMPT_CAP = 20  # owner 2026-09-23 22:40 ET


def reserve_attempt(root, *, now, selection_sha256, open_orders=None, maker=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    validate_nonreparse_directory(root)
    if utc(now).date().isoformat() > LAST_DAY:
        raise RuntimeError('campaign_expired')
    # Numeric order: session-10 must follow session-9 (plain name order put it after session-1).
    markers = sorted(root.glob('session-*.attempt.json'), key=lambda p: (len(p.name), p.name))
    if len(markers) >= ATTEMPT_CAP:
        raise RuntimeError('attempt_cap')
    sessions = 0
    for i, marker in enumerate(markers, 1):
        validate_regular_nonreparse_file(marker)
        if marker.name != f'session-{i}.attempt.json' or json.loads(marker.read_bytes())['number'] != i:
            raise RuntimeError('campaign_count_corrupt')
        state = attempt_state(marker, now=now)
        sessions += int(state['submitted'])
        if state['blocked']:
            path = root / f'session-{i}' / 'reconciliation.json'
            try:
                receipt = json.loads(validate_regular_nonreparse_file(path).read_bytes())
                valid = (receipt['state'] == state and receipt['open_orders'] == [] and
                         receipt['maker_address'] == maker and bool(receipt['owner_confirmation']) and
                         receipt['owner_confirmation'] == 'RE1M RECONCILE ' + digest(state)[:12] and
                         utc(receipt['at_utc']) <= utc(now))
            except (OSError, ValueError, RuntimeError, KeyError):
                valid = False
            if not valid or open_orders is None or open_orders() != []:
                raise RuntimeError('prior_attempt_needs_owner_reconciliation')
    if sessions >= MAX_SESSIONS:
        raise RuntimeError('session_cap')
    number_ = len(markers) + 1
    row = {'number': number_, 'session_number': sessions + 1, 'protocol': 'RE-1M-attended-84c',
           'created_at_utc': utc(now).isoformat(), 'selection_sha256': selection_sha256}
    write_new(root / f'session-{number_}.attempt.json', row)
    directory = root / f'session-{number_}'
    directory.mkdir(exist_ok=False)
    return directory, row


class ReplayedPrediction(dict):
    """Original immutable prediction mapping with journal-derived interpretation."""


def journal_adequacy(rows):
    start = utc(rows[0]['recorded_at_utc'])
    stop = next((utc(r['recorded_at_utc']) for r in rows if r['event'].startswith('cleanup_')), utc(rows[-1]['recorded_at_utc']))
    elapsed = max(1, math.ceil((stop - start).total_seconds() / 60))
    samples, terms, scoring_minutes, scoring = set(), set(), 0, False
    for row in rows:
        if row['event'] == 'scoring_response':
            values = row['response']
            scoring = isinstance(values, dict) and len(values) == 2 and all(v is True for v in values.values())
        if row['event'] in {'market_snapshot', 'submit_market_snapshot', 'minute'}:
            inputs = row['snapshot']['quote_inputs']
            terms.add(tuple(number(inputs[k]) for k in ('reward_min_size', 'reward_max_spread_cents')))
        if row['event'] in {'market_snapshot', 'minute'}:
            slot = int((utc(row['recorded_at_utc']) - start).total_seconds() // 60)
            if 0 <= slot < elapsed: samples.add(slot)
        if row['event'] == 'minute' and row['observation']['visible_two_sided'] and scoring:
            scoring_minutes += 1
    return dict(elapsed_minutes=elapsed, public_book_minutes=len(samples),
                size_spread_unchanged=len(terms) == 1, two_sided_scoring_minutes=scoring_minutes)


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
            observed = observe(row['snapshot'], row['prices'], prediction['scope'].get('size', 20))
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
    if prediction['scope'].get('protocol') == 'RE-1M-attended-84c':
        for key in ('order_ids', 'unknown_submit', 'post_count', 'inventory_proven'):
            if prediction[key] != rows[-1][key]: raise ValueError('prediction_terminal')
    if any(not math.isclose(float(prediction[k]), v, abs_tol=1e-8) for k, v in totals.items()):
        raise ValueError('prediction_totals')
    result = ReplayedPrediction(prediction)
    result.adequacy = journal_adequacy(rows)
    return result


def payout_verdict(prediction, accrual, payment_evidence=None):
    """Report frozen and owner-amended interpretations without rewriting inputs."""
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
    frozen_paid = None
    if payment_evidence is not None:
        from weather.market.re1_payout_evidence import reconcile_reward_payment
        payment = reconcile_reward_payment(payment_evidence)
        frozen_payment = reconcile_reward_payment(payment_evidence, frozen=True)
        scope = payment.get('scope') or {}
        start = utc(prediction['reward_day'] + 'T00:00:00Z')
        if (payment['valid'] and payment['complete'] and scope.get('condition_id') == condition and
                scope.get('maker_address', '').lower() == maker and
                utc(scope['accrual_start_utc']) == start and utc(scope['accrual_end_utc']) == start + timedelta(days=1)):
            paid = number(payment['actual_liquidity_reward_usdc'])
        if (frozen_payment['valid'] and frozen_payment['complete'] and
                frozen_payment.get('scope', {}).get('condition_id') == condition and
                frozen_payment['scope'].get('maker_address', '').lower() == maker and
                utc(frozen_payment['scope']['accrual_start_utc']) == start and
                utc(frozen_payment['scope']['accrual_end_utc']) == start + timedelta(days=1)):
            frozen_paid = number(frozen_payment['actual_liquidity_reward_usdc'])
    k = paid / p if paid is not None and p > 0 else None
    adequate = (prediction['mode'] == 'live' and prediction['evidence_complete'] and prediction['cleanup_ok'] and
                prediction.get('failure_type') is None and
                prediction['scoring_seen'] and not prediction['reward_terms_changed'] and
                prediction['visible_two_sided_minutes'] >= 180)
    decision = 'INCONCLUSIVE'
    frozen_k = frozen_paid / p if frozen_paid is not None and p > 0 else None
    if adequate and frozen_k is not None:
        if frozen_k >= number('.5'): decision = 'PAID_AS_MODELLED'
        elif number('.1') <= frozen_k < number('.5'): decision = 'PAID_DILUTED'
        elif frozen_paid == 0 and p >= 2: decision = 'NOT_PAID'
    facts = getattr(prediction, 'adequacy', prediction.get('adequacy', {}))
    coverage = (number(facts['public_book_minutes']) / number(facts['elapsed_minutes'])
                if facts.get('elapsed_minutes', 0) > 0 else None)
    amended_adequate = (prediction['mode'] == 'live' and prediction['cleanup_ok'] and
        coverage is not None and number('.95') <= coverage <= 1 and facts.get('size_spread_unchanged') is True)
    short = prediction['visible_two_sided_minutes'] < 180
    day_total = payment.get('day_earnings') if payment else None
    day_total = number(day_total) if day_total is not None else None
    # The collection's complete, account-wide earnings are authoritative for
    # both the daily minimum and the selected condition's accrued ratio.
    if payment and payment.get('condition_earnings') is not None:
        accrued = number(payment['condition_earnings'])
    k_accrued = accrued / p if p > 0 else None
    amended, cause, accrued_verdict = 'INCONCLUSIVE', None, None
    if not amended_adequate: cause = 'session_inadequate_or_missing_replay'
    elif p <= 0: cause = 'prediction_nonpositive'
    elif paid is None: cause = 'payment_evidence_incomplete'
    elif k >= number('.5'): amended = 'PAID_AS_MODELLED'
    elif k >= number('.1'): amended = 'PAID_DILUTED'
    elif paid == 0 and day_total is not None:
        if not short and prediction['scoring_seen'] and (
                day_total >= 1 and payment.get('cash_window_closed') is True or
                day_total == 0 and facts.get('two_sided_scoring_minutes', 0) >= 180):
            amended = 'NOT_PAID'
        elif day_total < 1:
            amended = 'BELOW_PAYOUT_MINIMUM'
            accrued_verdict = ('ACCRUED_AS_MODELLED' if k_accrued >= number('.5') else
                               'ACCRUED_DILUTED' if k_accrued >= number('.1') else 'ACCRUED_LOW')
        else: cause = 'short_or_scoring_unproved'
    else: cause = 'day_earnings_missing' if paid == 0 else 'paid_below_interpretation_band'
    return {'verdict': amended, 'verdict_frozen': decision, 'verdict_amended': amended,
            'accrued_verdict': accrued_verdict, 'flags': ['SHORT'] if short else [],
            'adequate': amended_adequate, 'sample_coverage': None if coverage is None else str(coverage),
            'adequacy_evidence': facts,
            'inconclusive_cause': cause, 'day_earnings': None if day_total is None else str(day_total),
            'close_track': amended == 'NOT_PAID' and amended_adequate,
            'counts_as_low_accrual_session': bool(amended_adequate and day_total is not None and
                                                 paid is not None and k_accrued is not None and k_accrued < number('.1')),
            'paid_frozen': None if frozen_paid is None else str(frozen_paid),
            'paid': None if paid is None else str(paid), 'k': None if k is None else str(k),
            'accrued': str(accrued), 'k_accrued': str(accrued / p) if p > 0 else None,
            'earnings_by_asset': by_asset, 'accrued_basis': 'venue_reported_asset_rate',
            'payment_reconciliation': payment, 'prediction_sha256': digest(prediction)}
