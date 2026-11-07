"""Small chained private evidence fixtures; no venue or credentials.

Guards: B032 R2 evidence continuity and explicit failure classification.
"""
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.mm_stage2_hold import HoldJournal


def private_result(runtime, claim, *, faults=('scoring_missed',), extra_rows=(), failure_type=None,
                   terminal_read_gap=False, legacy=False, unknown_submit=False):
    ledger = runtime.state.ledger
    directory = runtime.pilot_root / 'private-session'
    directory.mkdir()
    ledger.record('session_start', session_id='s', counted=True,
                  owner_local_date='2026-11-09' if legacy else '2026-11-11',
                  directory='private-session', **({} if legacy else {'autostart_attempt_id': claim['attempt_id']}))
    ledger.intent(session_id='s', intent_key='s:1', token_id='t', condition_id='c', size='20', price='.5', fee_rate_bps='0')
    if not unknown_submit:
        ledger.ack('s:1', 'o')
    order = {'id': 'o', 'status': 'CANCELED', 'size_matched': '0'}
    if not terminal_read_gap and not unknown_submit:
        ledger.terminal('o', order, source='fixture')
    scope = {'session_id': 's', 'condition_id': 'c', 'token_ids': ['t', 'n'],
             'maker_address': runtime.state.maker, 'protocol': 'lfc_autostart_v1'}
    request = {'token_id': 't', 'side': 'BUY', 'size': '20', 'price': '.5', 'post_only': True,
               'expiration': int(runtime.clock.now().timestamp()) + 21660}
    write_new(directory / 'submit-1.intent.json', {'number': 1, 'request': request, 'scope': scope})
    if not unknown_submit:
        write_new(directory / 'submit-1.ack.json', {'order_id': 'o'})
    journal = HoldJournal(directory / 'journal.jsonl', clock=runtime.clock.now, scope=scope, mode='live')
    journal.record('submit_request', request=request)
    if not unknown_submit:
        journal.record('submit_response', response={'id': 'o', 'ok': True, 'status': 'live'})
    if not terminal_read_gap and not unknown_submit:
        journal.record('terminal_order', order=order)
    for code in faults:
        journal.record(code, exception_type='TimeoutError')
    for row in extra_rows:
        row = dict(row)
        journal.record(row.pop('event'), **row)
    flags = {'unknown_submit': unknown_submit, 'inventory_proven': not terminal_read_gap, 'evidence_complete': not faults}
    terminal = {**flags, 'post_count': 1, 'order_ids': [] if unknown_submit else ['o'], 'failure_type': failure_type,
                'cleanup_ok': not faults, 'reason': 'fixed_end', 'submits': 1, 'requotes': 0,
                'evidence_faults': sorted(faults)}
    if legacy:
        terminal.pop('evidence_faults')
    journal.record('terminal', **terminal)
    journal.close()
    prediction = {'mode': 'live', 'scope': scope, **terminal, 'journal_sha256': file_sha(journal.path)}
    write_new(directory / 'prediction.json', prediction)
    write_new(directory / 'session_end.json', {'session_id': 's', **flags})
    ledger.record('session_end', session_id='s', **flags)
    outcome = {'evidence_sha256': {name: file_sha(directory / name) for name in
                                  ('journal.jsonl', 'prediction.json', 'session_end.json')}}
    local = local_money_proof(directory, ledger=ledger, session_id='s', attempt_id=None if legacy else claim['attempt_id'],
                              outcome=outcome, legacy=legacy)
    return directory, {'session_id': 's', 'outcome': outcome, **flags, 'local_money_proof': local,
                       'private_evidence_directory': 'private-session',
                       'public_coverage': {'configured': False, 'gap': 'not_configured'}}
