"""Owner-terminal preflight and reconciliation; neither creates an order."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from urllib.error import HTTPError

from weather.market.mm_stage2_hold import digest, utc, write_new
from weather.market.re1_attended import GuardedJournal, SecretGuard
from weather.market.re1_evidence import campaign_root, live_mutex, attempt_state
from weather.market.re1_rehearsal import Re1PublicBooks, WallClock
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration, validate_regular_nonreparse_file
from weather.paths import REPO_ROOT


def code_identity():
    def git(*args):
        return subprocess.run(['git', '-C', str(REPO_ROOT), *args], capture_output=True,
                              text=True, check=True, timeout=15).stdout.strip()
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise RuntimeError('preflight_requires_clean_tip')
    return git('rev-parse', 'HEAD')


def latency(values):
    values = sorted(values)
    if not values:
        return None
    return {'min': values[0], 'median': statistics.median(values),
            'p95': values[math.ceil(.95 * len(values)) - 1], 'max': values[-1], 'count': len(values)}


def failure_message(exc, guard):
    try:
        return guard.clean(str(exc))[:200]
    except RuntimeError:
        # SecretGuard refuses residual secrets; retain the failure without its text.
        return 'secret_output_refused'


def measure(name, fn, *, repeats, clock, journal, guard, failures, cadence=0):
    times, results = [], []
    for index in range(repeats):
        start = clock.monotonic()
        try:
            value = fn()
            elapsed = clock.monotonic() - start
            journal.record('preflight_read', step=name, index=index, seconds=elapsed, response=value)
            times.append(elapsed)
            results.append(value)
        except Exception as exc:
            row = {'step': name, 'index': index, 'exception_type': type(exc).__name__,
                   'message': failure_message(exc, guard)}
            failures.append(row)
            journal.record('preflight_fail', **row)
            guard.print({'status': 'FAIL', **row})
        if cadence and index + 1 < repeats:
            clock.sleep(max(0, start + cadence - clock.monotonic()))
    summary = {'step': name, 'status': 'PASS' if len(results) == repeats else 'FAIL', 'latency_seconds': latency(times)}
    if len(results) != repeats:
        summary['message'] = 'one_or_more_reads_failed'
    guard.print(summary)
    return latency(times), results


def run_preflight():
    if not sys.stdin.isatty():
        raise RuntimeError('owner_terminal_required')
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue, json_read, GEOBLOCK, RPC
    from polymarket._internal.actions.rewards import build_get_orders_scoring_request
    from polymarket.errors import UserInputError
    clock, guard = WallClock(), SecretGuard()
    directory = campaign_root() / ('preflight-' + clock.now().strftime('%Y%m%dT%H%M%S%fZ'))
    journal = GuardedJournal(directory / 'journal.jsonl', clock=clock.now, scope={'purpose': 'preflight'},
                             mode='preflight', guard=guard)
    failures, stats = [], {}
    venue, client, head, maker = None, None, None, None
    phase = 'proxy_host_tip'
    try:
        with live_mutex():
            assert_no_ambient_proxy_configuration()
            head = code_identity()
            journal.record('preflight_step', step='proxy_host_tip', status='PASS', commit=head)
            guard.print('PASS proxy_host_tip')
            phase = 'public_read_probe'
            for url, body in ((GEOBLOCK, None),
                              (RPC, {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []})):
                try:
                    json_read(url, body=body)
                except HTTPError as exc:
                    exc.close()
                    raise RuntimeError(f'public_read_blocked: {url} -> HTTP {exc.code}') from None
            journal.record('preflight_step', step=phase, status='PASS')
            guard.print('PASS public_read_probe')
            phase = 'credential_topology'
            fields, guard = load_owner_credentials('preflight')
            journal.guard = guard
            maker = fields['FUNDER_ADDRESS']
            journal.record('preflight_step', step='credential_topology', status='PASS', maker_address=maker)
            guard.print('PASS credential_topology')
            phase = 'client_bootstrap'
            client = build_client(fields, readonly=True)
            journal.record('preflight_step', step='client_bootstrap', status='PASS')
            guard.print('PASS client_bootstrap')
            phase = 'public_selection'
            table = Re1PublicBooks().selection()
            write_new(directory / 'selection.json', guard.clean(table))
            if not table['selected_condition_id']:
                best = max(table['rows'], key=lambda row: row['predicted_360_minutes']
                           if row['predicted_360_minutes'] is not None else -math.inf, default=None)
                detail = {'location': best['market_id'] if best else None,
                          'event_date': best['target_date'] if best else None,
                          'predicted_360_minutes': best['predicted_360_minutes'] if best else None,
                          'refusal': best['refusal'] if best else None}
                best_text = (f"{detail['location']} {detail['event_date']} "
                             f"predicted_360_minutes={detail['predicted_360_minutes']} ({detail['refusal']})"
                             if best else 'none')
                message = guard.clean(f"NO QUALIFYING BAND at {utc(clock.now()):%H:%M}Z — best {best_text}; "
                                      'retry at the next quarter hour')
                guard.print(message)
                journal.record('preflight_step', step='public_selection', status='NO_BAND', message=message, **detail)
                raise RuntimeError('no_qualifying_band')
            selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
            phase = 'user_stream_readiness'
            venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'],
                               directory=directory, readonly=True, preflight=True)
            venue.set_journal(journal)
            venue.start()
            journal.record('preflight_step', step='user_stream_readiness', status='PASS')
            guard.print('PASS user_stream_readiness')
            stats['user_stream'], _ = measure('user_stream', venue.events, repeats=20,
                clock=clock, journal=journal, guard=guard, failures=failures)
            reads = [('open_orders', venue.open_orders), ('positions', venue.positions),
                     ('balances', venue.balances), ('geoblock', venue.geography)]
            empty = False
            for name, fn in reads:
                phase = name
                stats[name], results = measure(name, fn, repeats=20, clock=clock, journal=journal, guard=guard, failures=failures)
                if name == 'open_orders':
                    empty = len(results) == 20 and all(rows == [] for rows in results)
                    if len(results) == 20 and not empty:
                        failures.append({'step': name, 'exception_type': 'AccountNotEmpty',
                                         'message': 'account_has_open_orders'})
                        journal.record('preflight_fail', **failures[-1])
                        guard.print({'status': 'FAIL', **failures[-1]})
                if name == 'geoblock' and any(row.get('blocked') is not False for row in results):
                    raise RuntimeError('geoblock')
            try:
                build_get_orders_scoring_request(order_ids=[])
            except UserInputError:
                journal.record('preflight_step', step='scoring_empty', status='SKIP', reason='SDK_0.6.0_requires_nonempty_ids')
                guard.print('SKIP scoring_empty: SDK 0.6.0 rejects an empty list before network access')
            else:
                stats['scoring'], _ = measure('scoring', lambda: client.get_orders_scoring(order_ids=[]), repeats=20,
                    clock=clock, journal=journal, guard=guard, failures=failures)
            stats['accrual'], _ = measure('accrual', lambda: venue.accrual(clock.now().date().isoformat()), repeats=20,
                clock=clock, journal=journal, guard=guard, failures=failures)
            if empty:
                phase = 'heartbeat'
                stats['heartbeat'], _ = measure('heartbeat', venue.heartbeat, repeats=6, cadence=5,
                    clock=clock, journal=journal, guard=guard, failures=failures)
            phase = 'final_user_stream'
            venue.events()
            if venue.journal_failed:
                raise RuntimeError('response_journal_failed')
    except Exception as exc:
        row = {'step': phase, 'exception_type': type(exc).__name__, 'message': failure_message(exc, guard)}
        failures.append(row)
        journal.record('preflight_fail', **row)
        if phase != 'public_read_probe':
            guard.print({'status': 'FAIL', **row})
    finally:
        try:
            if venue is not None:
                venue.close()
            elif client is not None:
                client.close()
        except Exception as exc:
            failures.append({'step': 'close', 'exception_type': type(exc).__name__, 'message': 'client_close_failed'})
            journal.record('preflight_fail', **failures[-1])
            guard.print({'status': 'FAIL', **failures[-1]})
        timeouts = {name: max(2, 3 * row['p95']) for name, row in stats.items() if row is not None}
        if ('heartbeat' in stats or not failures) and timeouts.get('heartbeat', 8) >= 8:
            failures.append({'step': 'heartbeat_latency_budget', 'exception_type': 'TimeoutError',
                             'message': 'heartbeat_timeout_must_be_below_8_seconds'})
            journal.record('preflight_fail', **failures[-1])
            guard.print({'status': 'FAIL', **failures[-1]})
        receipt = {'commit': head, 'maker_address': maker, 'at_utc': clock.now().isoformat(),
                   'status': 'FAIL' if failures else 'PASS', 'latency_seconds': stats,
                   'timeouts_seconds': timeouts, 'failures': failures}
        journal.record('preflight_terminal', **receipt)
        journal.close()
        receipt['journal_sha256'] = hashlib.sha256(journal.path.read_bytes()).hexdigest()
        write_new(directory / 'preflight.json', guard.clean(receipt))
        summary = {'status': receipt['status'], 'receipt': str(directory / 'preflight.json'), 'latency_seconds': stats}
        if failures:
            summary['message'] = 'preflight_failed'
            if phase == 'public_read_probe':
                # This early failure has no client to close and no measured reads.
                # Print the cause and receipt once, without a second FAIL summary.
                summary.update(failures[0])
        guard.print(summary)
    return 0 if not failures else 1


def clean_preflight(root, *, now, commit):
    paths = sorted(Path(root).glob('preflight-*'))
    if not paths:
        raise RuntimeError('clean_final_tip_preflight_required')
    # A newer failed check invalidates an older PASS.
    path = validate_regular_nonreparse_file(paths[-1] / 'preflight.json')
    row = json.loads(path.read_bytes())
    raw = validate_regular_nonreparse_file(path.parent / 'journal.jsonl').read_bytes()
    terminal = json.loads(raw.splitlines()[-1])
    if (row['status'] != 'PASS' or row['commit'] != commit or row['failures'] or
            utc(row['at_utc']).date() != utc(now).date() or utc(row['at_utc']) > utc(now) or
            hashlib.sha256(raw).hexdigest() != row['journal_sha256'] or
            terminal.get('event') != 'preflight_terminal' or
            any(terminal.get(key) != value for key, value in row.items() if key != 'journal_sha256') or
            not row['timeouts_seconds'] or any(not math.isfinite(value) or value < 2 for value in row['timeouts_seconds'].values())):
        raise RuntimeError('clean_final_tip_preflight_required')
    return row


def reconcile_receipt(marker, venue, *, clock, guard, reader=input):
    state = attempt_state(marker, now=clock.now())
    directory = marker.parent / f"session-{state['number']}"
    initial = {'open_orders': venue.open_orders(), 'positions': venue.positions(),
               'orders': [venue.order(oid) for oid in state['order_ids']]}
    guard.print({'attempt_state': state, **initial})
    if initial['open_orders'] != []:
        raise RuntimeError('reconciliation_requires_empty_account')
    phrase = 'RE1M RECONCILE ' + digest(state)[:12]
    guard.print('Inventory is held to settlement. Type exactly: ' + phrase)
    if reader() != phrase:
        raise RuntimeError('owner_confirmation_refused')
    current = venue.open_orders()
    if current != []:
        raise RuntimeError('reconciliation_requires_empty_account')
    receipt = {'state': state, **initial, 'open_orders': current, 'maker_address': venue.maker,
               'owner_confirmation': phrase, 'at_utc': clock.now().isoformat()}
    write_new(directory / 'reconciliation.json', guard.clean(receipt))
    guard.print({'receipt': str(directory / 'reconciliation.json'), 'status': 'PASS'})
    return receipt


def run_reconcile(number):
    if not sys.stdin.isatty():
        raise RuntimeError('owner_terminal_required')
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    with live_mutex():
        marker = campaign_root() / f'session-{number}.attempt.json'
        directory = campaign_root() / f'session-{number}'
        attempt = json.loads(validate_regular_nonreparse_file(marker).read_bytes())
        table = json.loads(validate_regular_nonreparse_file(directory / 'selection.json').read_bytes())
        if digest(table) != attempt['selection_sha256']:
            raise RuntimeError('reconcile_selection_binding')
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        scope = json.loads(validate_regular_nonreparse_file(directory / 'journal.jsonl').read_bytes().splitlines()[0])['scope']
        fields, guard = load_owner_credentials('reconcile')
        if fields['FUNDER_ADDRESS'] != scope['maker_address']:
            raise RuntimeError('reconciliation_account_changed')
        client = build_client(fields, readonly=True)
        venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'], readonly=True)
        try:
            reconcile_receipt(marker, venue, clock=WallClock(), guard=guard)
            return 0
        finally:
            venue.close()
