"""Validate a recorded account/day earnings walk from paired wire receipts.

Completeness, row membership and per-row provenance are reconstructed; persisted
summary flags alone never qualify an accrual observation.
"""
from datetime import timedelta
from weather.market.lfc_recording_io import response_bytes, strict_json
from weather.market.mm_stage2_hold import utc
from weather.market.re1_payout_evidence import normalize_earnings


def validate_accrual(entry, journal, *, maker, day, start, decode_rows, allow_partial_assets=False):
    walk_id = entry.get('walk_id')
    if not isinstance(walk_id, str):
        raise ValueError('recording_accrual_walk_missing')
    starts = [(i, row) for i, row in enumerate(journal)
              if row.get('event') == 'accrual_walk_start' and row.get('walk_id') == walk_id]
    ends = [(i, row) for i, row in enumerate(journal)
            if row.get('event') == 'accrual_walk_end' and row.get('walk_id') == walk_id]
    if len(starts) != 1 or len(ends) != 1 or starts[0][0] >= ends[0][0]:
        raise ValueError('recording_accrual_walk_scope')
    begin, metadata = starts[0]
    finish, ending = ends[0]
    signature = metadata.get('signature_type')
    if (metadata.get('maker') != maker or metadata.get('day') != day or
            metadata.get('condition_id') != entry['condition_id'] or type(signature) is not int or signature not in (2, 3)):
        raise ValueError('recording_accrual_walk_scope')
    requests = [(i, row) for i, row in enumerate(journal) if begin < i < finish and
                row.get('event') == 'accrual_request' and row.get('walk_id') == walk_id]
    responses = [(i, row) for i, row in enumerate(journal) if begin < i < finish and
                 row.get('event') == 'accrual_response' and row.get('walk_id') == walk_id]
    if not 2 <= len(requests) <= 51 or len(responses) != len(requests):
        raise ValueError('recording_accrual_receipts_missing')
    cursor, terminal, rows, totals, seen = None, False, [], None, set()
    previous = begin
    for ordinal, ((request_index, request), (response_index, response)) in enumerate(zip(requests, responses)):
        if (request.get('read_id') != ordinal or response.get('read_id') != ordinal or
                not previous < request_index < response_index < finish):
            raise ValueError('recording_accrual_pairing')
        raw_index = response.get('response_index')
        if type(raw_index) is not int or not request_index < raw_index < response_index:
            raise ValueError('recording_accrual_pairing')
        receipt = journal[raw_index]
        path = request.get('path')
        expected = {'date': day, 'signature_type': signature}
        if not terminal and cursor is not None:
            expected['next_cursor'] = cursor
        if (request.get('method') != 'GET' or request.get('params') != expected or
                receipt.get('event') != 'sdk_response' or receipt.get('path') != path or
                receipt.get('status') != 200 or response.get('response_sha256') != receipt.get('sha256')):
            raise ValueError('recording_accrual_pairing')
        payload = strict_json(response_bytes(receipt))
        if not terminal:
            if path != '/rewards/user' or not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                raise ValueError('recording_accrual_walk_scope')
            rows.extend((row, receipt['sha256']) for row in decode_rows(payload['data']))
            cursor = payload.get('next_cursor')
            if cursor == 'LTE=':
                terminal = True
            elif not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError('recording_accrual_terminal_missing')
            seen.add(cursor)
        else:
            if path != '/rewards/user/total' or totals is not None or ordinal != len(requests) - 1:
                raise ValueError('recording_accrual_walk_scope')
            totals = [(row, receipt['sha256']) for row in decode_rows(payload, total=True)]
        if len(rows) > 2048:
            raise ValueError('recording_accrual_row_budget')
        previous = response_index
    if not terminal or totals is None:
        raise ValueError('recording_accrual_terminal_missing')
    saved = entry['retained']
    if saved.get('rows') != [row for row, _ in rows] or saved.get('total_earnings') != [row for row, _ in totals]:
        raise ValueError('recording_accrual_receipts_missing')
    source = entry['source']
    observed = utc(entry['accruals'][0]['observed_at_utc'] if entry['accruals'] else source['observed_at_utc'])
    if not utc(metadata['observed_at_utc']) <= observed <= utc(source['observed_at_utc']) <= utc(ending['observed_at_utc']):
        raise ValueError('recording_accrual_observation_time')
    scope = dict(maker_address=maker, condition_id=entry['condition_id'], accrual_start_utc=start.isoformat(),
                 accrual_end_utc=(start + timedelta(days=1)).isoformat())
    expected, complete_assets = normalize_earnings(rows, totals, scope, observed)
    partial_assets = (allow_partial_assets and not complete_assets and
                      source.get('complete') is False and source.get('reason') == 'asset_total_missing')
    if (not (complete_assets or partial_assets) or observed < utc(scope['accrual_end_utc']) or expected != entry['accruals'] or
            source.get('status') != 'OBSERVED' or source.get('pagination_complete') is not True or
            source['request_scope'].get('maker_address') != maker or
            source['request_scope'].get('period_start_utc') != start.isoformat() or
            source['request_scope'].get('period_end_utc') != scope['accrual_end_utc'] or
            source.get('coverage_through_utc') != scope['accrual_end_utc']):
        raise ValueError('recording_accrual_mismatch')
