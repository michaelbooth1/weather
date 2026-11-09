"""Retained private request/ACK/terminal proof, revalidated at every finalization."""
import hashlib
from pathlib import Path

from weather.market.lfc_accounting import quantity
from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json
from weather.market.mm_account_reads import order_terminal
from weather.market.mm_official_adapter import sdk_field_value
from weather.market.mm_stage2_hold import SCHEMA_VERSION, canonical_bytes, utc, digest
from weather.operations.live_path_security import validate_regular_nonreparse_file


ANCILLARY_SAMPLES = {'scoring', 'accrual', 'final_accrual', 'final_balances'}
MONEY_READ_GAPS = {'terminal_order_unavailable', 'terminal_positions_unavailable',
                   'terminal_trades_unavailable', 'cleanup_open_orders_unavailable',
                   'cleanup_cancel_unavailable', 'cleanup_cancel_all_unavailable', 'fill_order_unavailable',
                   'f2_account_read_unavailable', 'f2_account_cancel_unavailable', 'f2_account_cleanup_pending',
                   'repost_inventory_unavailable', 'repost_peer_proof_pending'}


def journal_contract(path, prediction, *, legacy=False, owner_review=False, allow_open=False, expected_head=None, submit_limit=10):
    """Stream the exact chained journal; a gap name cannot replace core rows."""
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('private_journal_limit')
    if type(submit_limit) is not int or submit_limit not in (10, 40):
        raise ValueError('private_submit_limit')
    previous, last_time, first, terminal = None, None, None, None
    requests, responses, orders, gaps, money_gaps = [], [], {}, set(), set()
    with path.open('rb') as stream:
        for index in range(100000):
            raw = stream.readline(2_000_001)
            if not raw:
                break
            row = strict_json(raw)
            when = utc(row['recorded_at_utc'])
            if (len(raw) > 2_000_000 or not raw.endswith(b'\n') or canonical_bytes(row) != raw or
                    row.get('schema_version') != SCHEMA_VERSION or row.get('kind') != 'journal' or
                    row.get('sequence') != index or row.get('previous_sha256') != previous or
                    last_time is not None and when < last_time):
                raise ValueError('private_journal_chain')
            previous, last_time = hashlib.sha256(raw).hexdigest(), when
            event = row.get('event')
            if first is None:
                first = row
            terminal = row
            if event == 'submit_request':
                requests.append(row['request'])
                if len(requests) > submit_limit:
                    raise ValueError('private_submit_limit')
            elif event == 'submit_response':
                responses.append(row['response'])
                if len(responses) > submit_limit:
                    raise ValueError('private_submit_limit')
            elif event in {'submit_deferred', 'pre_post_abort'}:
                if (row.get('durable_intent_present') is not False or
                        len(requests) != len(responses) + 1 or
                        row.get('attempted_number') != len(responses) + 1 or
                        digest(requests[-1]) != row.get('request_sha256')):
                    raise ValueError('private_submit_deferral_binding')
                if event == 'pre_post_abort' and row.get('intent_sha256') is not None:
                    packet_path = validate_regular_nonreparse_file(path.parent / f'submit-{row["attempted_number"]}.intent.json')
                    packet = strict_json(read_bytes(packet_path, 2_000_000))
                    if (file_sha(packet_path) != row['intent_sha256'] or packet.get('request') != requests[-1] or
                            packet.get('number') != row['attempted_number'] or packet.get('scope') != prediction['scope']):
                        raise ValueError('private_abort_intent_binding')
                requests.pop()  # Exact proved pre-POST attempt; originals remain in the journal.
            elif event == 'terminal_order':
                order = row['order']
                oid = sdk_field_value(order, 'id', 'order_id', 'orderID')
                if oid:
                    orders[str(oid)] = order
                    if len(orders) > submit_limit:
                        raise ValueError('private_order_limit')
            elif event in {'scoring_missed', 'minute_missed', 'heartbeat_unavailable'}:
                # A missed send is tolerated by the independent heartbeat
                # freshness/failure checks; it is not missing money evidence.
                gaps.add(event)
            elif event == 'missing_sample' and row.get('sample') in ANCILLARY_SAMPLES:
                gaps.add('sample_' + row['sample'])
            elif event in MONEY_READ_GAPS:
                money_gaps.add(event)
            elif event == 'repost_inventory_proven':
                # Only this completed live-read phase supersedes these exact
                # retry gaps. Missing originals/ACKs and N1 faults still fail
                # their independent bindings; no owner recovery is implied.
                money_gaps.difference_update({'repost_inventory_unavailable', 'repost_peer_proof_pending'})
            elif event == 'read_unavailable' and isinstance(row.get('fact'), str):
                money_gaps.add('read_' + row['fact'])
            elif not owner_review and (row.get('exception_type') is not None or event == 'unmatched_trade_event' or
                  isinstance(event, str) and event.endswith(('_unavailable', '_missed', '_failed', '_error'))):
                raise ValueError('unclassified_private_evidence_fault')
        else:
            raise ValueError('private_journal_limit')
    if (not first or first.get('event') != 'opened' or first.get('mode') != 'live' or
            (not allow_open and terminal.get('event') != 'terminal') or
            (allow_open and (expected_head is None or previous != expected_head)) or
            any(prediction['scope'].get(key) != value for key, value in first['scope'].items())):
        raise ValueError('private_journal_scope')
    if allow_open:
        return requests, responses, orders, gaps, money_gaps
    for key in ('post_count', 'order_ids', 'unknown_submit', 'inventory_proven', 'evidence_complete',
                'failure_type', 'cleanup_ok', 'reason', 'submits', 'requotes', 'evidence_faults'):
        if legacy and key == 'evidence_faults' and key not in prediction and key not in terminal:
            continue
        if key not in prediction or terminal.get(key) != prediction[key]:
            raise ValueError('private_terminal_binding')
    return requests, responses, orders, gaps, money_gaps


def owner_originals(directory, *, ledger, session_id, attempt_id, outcome):
    """Bind originals for an EXPLICIT owner decision; this is not money proof.

    Failed flags and missing ACKs may explain the original incident. They are
    never relabelled complete. Missing/changed original files or broken journal
    structure cannot be waived by this reader or by an owner confirmation.
    """
    directory = Path(directory).absolute()
    if outcome.get('f2_session') is True:
        from weather.market.lfc_f2_evidence import money_proof
        return money_proof(directory, ledger=ledger, session_id=session_id, attempt_id=attempt_id,
                           outcome=outcome, owner=True)
    session = ledger.sessions[session_id]
    if session['end'] is None or session['start'].get('autostart_attempt_id') != attempt_id:
        raise ValueError('owner_original_session_binding')
    hashes = dict(outcome['evidence_sha256'])
    if not {'journal.jsonl', 'prediction.json', 'session_end.json'} <= hashes.keys():
        raise ValueError('owner_original_core_missing')
    for name, sha in hashes.items():
        if Path(name).name != name or file_sha(validate_regular_nonreparse_file(directory / name)) != sha:
            raise ValueError('owner_original_core_changed')
    prediction = strict_json(read_bytes(directory / 'prediction.json', 2_000_000))
    ending = strict_json(read_bytes(directory / 'session_end.json', 2_000_000))
    count = prediction.get('post_count')
    from weather.market.lfc_f2_pinb import session_limits
    submit_limit, _ = session_limits(ledger, session_id)
    known = prediction.get('order_ids')
    legs = [ledger.legs[key] for key in session['legs']]
    if (prediction.get('mode') != 'live' or prediction.get('scope', {}).get('session_id') != session_id or
            prediction.get('journal_sha256') != hashes['journal.jsonl'] or
            ending.get('session_id') != session_id or type(count) is not int or not 0 <= count <= submit_limit or
            count != len(legs) or not isinstance(known, list) or len(known) > count or
            any(not isinstance(oid, str) or not oid for oid in known) or
            any(leg['order_id'] is None or leg['status'] != 'terminal' for leg in legs)):
        raise ValueError('owner_original_identity_unresolved')
    requests, _, _, _, _ = journal_contract(directory / 'journal.jsonl', prediction, owner_review=True, submit_limit=submit_limit)
    if len(requests) < count:
        raise ValueError('owner_original_requests_missing')
    for number, leg in enumerate(legs, 1):
        name = f'submit-{number}.intent.json'
        path = validate_regular_nonreparse_file(directory / name)
        intent = strict_json(read_bytes(path, 2_000_000))
        request = intent['request']
        if (intent.get('number') != number or intent.get('scope') != prediction['scope'] or
                request != requests[number - 1] or request.get('token_id') != leg['token_id'] or
                request.get('side') != 'BUY' or request.get('post_only') is not True or
                quantity(request['size']) != quantity(leg['size']) or quantity(request['price']) != quantity(leg['price'])):
            raise ValueError('owner_original_intent_binding')
        hashes[name] = file_sha(path)
        ack_name = f'submit-{number}.ack.json'
        if number <= len(known) or (directory / ack_name).exists():
            ack_path = validate_regular_nonreparse_file(directory / ack_name)
            ack = strict_json(read_bytes(ack_path, 65536))
            if (ack.get('order_id') != leg['order_id'] or
                    number <= len(known) and known[number - 1] != leg['order_id']):
                raise ValueError('owner_original_ack_binding')
            hashes[ack_name] = file_sha(ack_path)
    return {'session_id': session_id, 'original_private_files': hashes,
            'raw_flags': evidence_flags(prediction), 'resolved_legs_sha256': hashlib.sha256(canonical_bytes(legs)).hexdigest()}


def local_money_proof(directory, *, ledger, session_id, attempt_id, outcome, legacy=False):
    """Later complete account reads may resolve supported GET gaps, never file loss.

    Raw flags survive unchanged. A failure_type, or one scoring gap beside an
    unclassified core fault, cannot be used as a blanket evidence exemption.
    """
    # Evidence completeness and placement uncertainty are independent. Losing a
    # journal never invents an order, and never makes the evidence complete.
    result = {'complete': False, 'unknown_submit': bool(ledger.unacknowledged_intents()),
              'failure': 'private_evidence_unbound'}
    try:
        directory = Path(directory).absolute()
        if outcome.get('f2_session') is True:
            from weather.market.lfc_f2_evidence import money_proof
            return money_proof(directory, ledger=ledger, session_id=session_id, attempt_id=attempt_id, outcome=outcome)
        session = ledger.sessions[session_id]
        if (session['end'] is None or session['start'].get('autostart_attempt_id') != attempt_id or
                legacy and (attempt_id is not None or session['start'].get('autostart_attempt_id'))):
            return result
        hashes = dict(outcome['evidence_sha256'])
        if not {'journal.jsonl', 'prediction.json', 'session_end.json'} <= hashes.keys():
            return result
        for name, sha in hashes.items():
            if Path(name).name != name or file_sha(validate_regular_nonreparse_file(directory / name)) != sha:
                return result
        prediction = strict_json(read_bytes(directory / 'prediction.json', 2_000_000))
        ending = strict_json(read_bytes(directory / 'session_end.json', 2_000_000))
        flags = evidence_flags(prediction)
        legs = [ledger.legs[key] for key in session['legs']]
        ids = [leg['order_id'] for leg in legs]
        from weather.market.lfc_f2_pinb import session_limits
        submit_limit, _ = session_limits(ledger, session_id)
        if (prediction.get('mode') != 'live' or flags['unknown_submit'] or any(oid is None for oid in ids) or
                prediction.get('post_count') != len(ids) or prediction.get('order_ids') != ids or len(ids) > submit_limit or
                prediction.get('journal_sha256') != hashes['journal.jsonl'] or
                prediction.get('scope', {}).get('session_id') != session_id or ending.get('session_id') != session_id or
                evidence_flags(ending) != flags or evidence_flags(session['end']) != flags or
                prediction.get('failure_type') is not None):
            return result
        requests, responses, orders, gaps, money_gaps = journal_contract(directory / 'journal.jsonl', prediction, legacy=legacy, submit_limit=submit_limit)
        # Pre-enrollment producers did not emit typed faults. Only their explicit
        # complete proof is automatically supported; failed legacy proof requires
        # the separate recorded owner review, never an inferred scoring exemption.
        if legacy and (not flags['evidence_complete'] or not flags['inventory_proven']):
            return result
        faults = prediction.get('evidence_faults', [] if legacy else None)
        if (not isinstance(faults, list) or any(not isinstance(code, str) for code in faults) or
                len(faults) != len(set(faults)) or
                any(code not in gaps and code not in money_gaps for code in faults) or
                flags['evidence_complete'] != (faults == [])):
            return dict(result, failure='unclassified_private_evidence_fault', raw_flags=flags)
        if len(requests) != len(legs) or len(responses) != len(legs):
            return result
        for number, (leg, request, response) in enumerate(zip(legs, requests, responses), 1):
            intent_name, ack_name = f'submit-{number}.intent.json', f'submit-{number}.ack.json'
            intent_path = validate_regular_nonreparse_file(directory / intent_name)
            ack_path = validate_regular_nonreparse_file(directory / ack_name)
            intent = strict_json(read_bytes(intent_path, 2_000_000))
            ack = strict_json(read_bytes(ack_path, 65536))
            if (intent.get('number') != number or intent.get('request') != request or
                    intent.get('scope') != prediction['scope'] or request.get('token_id') != leg['token_id'] or
                    request.get('side') != 'BUY' or request.get('post_only') is not True or
                    quantity(request['size']) != quantity(leg['size']) or quantity(request['price']) != quantity(leg['price']) or
                    ack.get('order_id') != leg['order_id'] or
                    str(sdk_field_value(response, 'id', 'order_id', 'orderID')) != leg['order_id']):
                return result
            hashes[intent_name], hashes[ack_name] = file_sha(intent_path), file_sha(ack_path)
            order = orders.get(leg['order_id'])
            if order is None and not money_gaps:
                return result
            if order is not None and not order_terminal(order, order_id=leg['order_id'], size=leg['size']):
                return result
            if order is not None and leg['status'] == 'terminal' and quantity(order['size_matched']) != quantity(leg['size_matched']):
                return result
        if not flags['evidence_complete'] and not gaps and not money_gaps:
            return dict(result, failure='unexplained_false_evidence_flag', raw_flags=flags)
        return {'complete': True, 'unknown_submit': False, 'raw_flags': flags,
                'explained_gaps': sorted(gaps), 'money_read_gaps': sorted(money_gaps),
                'failure_type': prediction.get('failure_type'), 'evidence_sha256': hashes}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return result
