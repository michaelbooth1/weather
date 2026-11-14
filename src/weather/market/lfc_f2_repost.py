"""Private proof and cooperative fill continuation for the B057 owner lane.

No alternate submit/sign/cancel capability exists here. The existing band owns
cleanup and the normal guarded submit path owns every subsequent order.
"""
from contextlib import contextmanager
import threading
import time

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalRefused
from weather.market.lfc_recording_io import read_bytes, strict_json
from weather.market.mm_account_reads import order_terminal
from weather.market.mm_stage2_hold import HoldEnd, _order_id, canonical_bytes
from weather.operations.live_path_security import validate_regular_nonreparse_file


def private_fill_proof(band, *, require_terminal=True):
    from weather.market.lfc_campaign_proof import journal_contract
    from weather.market.lfc_f2_pinb import session_limits
    submit_limit, _ = session_limits(band.ledger, band.session_id)
    requests, responses, orders, _, _ = journal_contract(band.journal.path, {'scope': band.scope},
        allow_open=True, expected_head=band.journal.previous, submit_limit=submit_limit)
    legs = [band.ledger.legs[key] for key in band.ledger.sessions[band.session_id]['legs']]
    if (band.posts != len(band.known) or len(legs) != band.posts or
            len(requests) != band.posts or len(responses) != band.posts):
        raise ValueError('repost_private_identity_unproven')
    hashes = {}
    from weather.market.lfc_recording_io import file_sha
    for number, leg in enumerate(legs, 1):
        oid = leg['order_id']
        if oid not in band.known or require_terminal and leg['status'] != 'terminal':
            raise ValueError('repost_terminal_unproven')
        intent_path = validate_regular_nonreparse_file(band.directory / f'submit-{number}.intent.json')
        ack_path = validate_regular_nonreparse_file(band.directory / f'submit-{number}.ack.json')
        intent = strict_json(read_bytes(intent_path, 65536))
        ack = strict_json(read_bytes(ack_path, 65536))
        request = intent['request']
        if (intent.get('number') != number or intent.get('scope') != band.scope or
                request != requests[number - 1] or request.get('token_id') != leg['token_id'] or
                request.get('side') != 'BUY' or request.get('post_only') is not True or
                quantity(request['price']) != quantity(leg['price']) or quantity(request['size']) != quantity(leg['size']) or
                ack.get('order_id') != oid or _order_id(responses[number - 1]) != oid or
                (leg['status'] == 'terminal' and (not order_terminal(orders.get(oid), order_id=oid, size=leg['size']) or
                 quantity(orders[oid]['size_matched']) != quantity(leg['size_matched'])))):
            raise ValueError('repost_private_binding')
        hashes[intent_path.name], hashes[ack_path.name] = file_sha(intent_path), file_sha(ack_path)
    return {'complete': True, 'unknown_submit': False, 'private_file_hashes': hashes,
            'journal_head_sha256': band.journal.previous}


@contextmanager
def bounded_read_progress(band):
    """A bounded GET phase keeps heartbeat progress, without touching orders.

    STOP is still observed by the driver's independent one-second observer.
    Only the main thread validates money or appends the ledger. The observer
    stops feeding progress after120s; it cannot keep a hung read alive forever.
    """
    stop = threading.Event()
    status = getattr(band, 'outcome_status', None)
    previous = getattr(status, 'phase', None)
    if status is not None:
        status.phase = 'VERIFY'
    began = time.monotonic()
    def observe():
        while not stop.wait(1) and time.monotonic() - began < 120:
            band.progress()
    thread = threading.Thread(target=observe, name='lfc-repost-read-progress', daemon=True)
    thread.start()
    try:
        band.progress()
        yield
    finally:
        stop.set(); thread.join(timeout=2)
        if thread.is_alive():
            raise RuntimeError('repost_read_observer_uncontained')
        if status is not None:
            status.phase = previous
            if status.resync_hook is not None:
                status.resync_hook()
        band.progress()


def trade_identity(event):
    """Normalized matched rows use trade_id; unmatched rows retain raw payload.id.

    A normalized order's id is never a trade identity. Conflicting aliases do
    not authorize a replay exemption, even if one alias was already proved.
    """
    payload = event.get('payload')
    values = [event.get('trade_id')]
    if isinstance(payload, dict):
        values.append(payload.get('id'))
    values = [value for value in values if value is not None]
    if (not values or any(not isinstance(value, str) or not value.strip() or len(value) > 256
                          for value in values) or len(set(values)) != 1):
        raise ValueError('repost_trade_identity_unproven')
    return values[0]


def observe_trade_ids(band, rows):
    for event in rows:
        if event.get('official_event_type') != 'trade':
            continue
        try:
            tid = trade_identity(event)
        except ValueError:
            band.note_evidence_fault('repost_trade_identity_unproven')
            band.journal.record('repost_trade_identity_unproven',
                                raw_event_sha256=event.get('raw_event_sha256'))
            raise HoldEnd('repost_trade_identity_unproven') from None
        band.observed_trade_ids.add(tid)
        if len(band.observed_trade_ids) > 4096:
            raise HoldEnd('repost_user_event_budget')


def filtered_events(band, rows):
    """Ignore only proved old identities; a new or unmatched trade still stops."""
    observe_trade_ids(band, rows or [])
    result = []
    for event in rows or []:
        if event.get('official_event_type') == 'trade':
            tid = trade_identity(event)
            if tid and tid in getattr(band, 'proven_trade_ids', set()):
                band.journal.record('proved_trade_replay', trade_id=tid,
                                    raw_event_sha256=event.get('raw_event_sha256'))
                continue
        else:
            oid = _order_id(event)
            key = band.ledger.by_order.get(oid)
            leg = band.ledger.legs.get(key)
            if leg is not None and leg['session_id'] == band.session_id and leg['status'] == 'terminal':
                matched = event.get('size_matched')
                ids = {str(event[k]) for k in ('id', 'order_id', 'orderID') if event.get(k) is not None}
                try:
                    covered = matched is not None and 0 <= quantity(matched) <= quantity(leg['size_matched'])
                except (ValueError, TypeError, ArithmeticError):
                    covered = False
                if ids == {oid} and covered:
                    # The ledger's earlier terminal identity/quantity proof
                    # owns reserve release. A delayed LIVE/UPDATE or status-less
                    # cancellation cannot reopen it or add unproved inventory.
                    from weather.market.mm_stage2_hold import digest
                    band.journal.record('proved_order_replay', order_id=oid, size_matched=str(matched),
                        observed_status=event.get('status', event.get('official_order_status')),
                        event_sha256=digest(event))
                    continue
                raise HoldEnd('repost_terminal_event_unproven')
        result.append(event)
    return result


def poll_waiting_stream(band):
    """Read and retain during cooldown; accept no event as fill/ACK proof.

    No order in this band may still be nonterminal. A new successful stream
    read after the nonquoting GET phase supplies freshness; elapsed wall time
    alone never refreshes it. Buffered events pass the ordinary fill checks
    against the next fresh inventory proof before any new POST.
    """
    if band.active or any(band.ledger.legs[key]['status'] != 'terminal'
                          for key in band.ledger.sessions[band.session_id]['legs']):
        raise HoldEnd('repost_terminal_unproven')
    rows = band.required('repost_user_stream', band.venue.raw.events, checkpoint=False)
    if not isinstance(rows, list):
        raise HoldEnd('repost_user_stream_unreadable')
    now = band.clock.monotonic()
    alive = getattr(band.venue, 'stream_last_alive', now)
    if alive is None or not 0 <= alive <= now or now - alive >= 30:
        raise HoldEnd('user_stream_stale')
    band.freshness.success['user_stream'] = alive
    if rows:
        observe_trade_ids(band, rows)
        from weather.market.lfc_f2_reward_estimate import capture_stream_context
        capture_stream_context(band, rows)
        band.project_trades(rows, source='stream')
        size = len(canonical_bytes(rows))
        if (len(rows) + len(band.pending_repost_events) > 4096 or size > 1_000_000 or
                band.pending_repost_bytes + size > 4_000_000):
            raise HoldEnd('repost_user_event_budget')
        band.journal.record('repost_user_events', rows=rows)
        band.pending_repost_events.extend(rows)
        band.pending_repost_bytes += size


def continue_quotes(band, base_steps, *, rehearsal_seconds=None):
    from weather.market.lfc_f2_breadth import CONTINUE, enabled, daily_gate
    if not enabled(band.campaign_policy):
        yield from base_steps(rehearsal_seconds=rehearsal_seconds)
        return
    continue_fills = band.campaign_policy.raw['on_first_band_fill'] == CONTINUE
    while True:
        try:
            yield from base_steps(rehearsal_seconds=rehearsal_seconds)
            return
        except HoldEnd as exc:
            if exc.reason == 'fill':
                band.record_post_books('fill')
            if exc.reason != 'thin_book_depth' and not (exc.reason == 'fill' and continue_fills):
                raise
            depth_paused = exc.reason == 'thin_book_depth'
        next_depth = band.clock.monotonic() + 60 if depth_paused else None
        before = {key: band.ledger.legs[key]['size_matched']
                  for key in band.ledger.sessions[band.session_id]['legs']}
        if depth_paused:
            band.journal.record('depth_paused', reason='thin_book_depth', recheck_seconds=60)
        band._repost_terminal_reads = True
        try:
            band.cleanup()
        finally:
            band._repost_terminal_reads = False
        if band.outcome_status.resync_hook is not None:
            band.outcome_status.resync_hook()
        try:
            private = private_fill_proof(band)
        except Exception as exc:
            if str(exc) == 'repost_terminal_unproven' and 'terminal_order_unavailable' in band._evidence_faults:
                raise HoldEnd('repost_terminal_unreadable') from None
            band.note_evidence_fault('repost_private_evidence_fault')
            raise HoldEnd('repost_private_evidence_fault') from None
        if not band.cancellation_ok or not band.inventory_proven:
            raise HoldEnd('repost_inventory_unproven')
        new_fill = any(quantity(band.ledger.legs[key]['size_matched']) > quantity(before.get(key, 0))
                       for key in band.ledger.sessions[band.session_id]['legs'])
        if depth_paused and new_fill and not continue_fills:
            raise HoldEnd('fill')
        band.active.clear()  # All these identities are terminal; known IDs/counters are retained.
        band.repost_waiting = True
        proof_time, delay = None, 5
        while True:
            if band.clock.monotonic() >= band.deadline:
                raise HoldEnd('fixed_end')
            band.control()
            if next_depth is not None and band.clock.monotonic() < next_depth:
                yield min(1, next_depth - band.clock.monotonic())
                continue
            if band.venue.coordinator.repost_proof is None:
                raise HoldEnd('repost_inventory_capability_missing')
            # A valid private packet never substitutes for account inventory.
            try:
                with bounded_read_progress(band):
                    proof = band.venue.coordinator.repost_proof(band)
                    from weather.market.lfc_campaign import TransientPrecheck
                    if (proof.get('inventory_proven') is True and
                            not band.observed_trade_ids <= set(proof['proven_trade_ids'])):
                        raise TransientPrecheck('repost_stream_fill_unproven')
            except Exception as exc:
                from weather.market.lfc_campaign import TransientPrecheck
                from weather.market.lfc_campaign_runtime import transient_read_error
                if not isinstance(exc, (TransientPrecheck, CapitalRefused)) and not transient_read_error(exc):
                    raise
                band.note_evidence_fault('repost_inventory_unavailable')
                band.journal.record('repost_inventory_unavailable', exception_type=type(exc).__name__)
                for _ in range(delay):
                    band.control()
                    if band.clock.monotonic() >= band.deadline:
                        raise HoldEnd('fixed_end')
                    yield 1
                delay = min(60, delay * 2)
                continue
            if proof.get('inventory_proven') is not True or proof.get('unknown_submit') is not False:
                raise HoldEnd('repost_inventory_unproven')
            band.proven_trade_ids = set(proof['proven_trade_ids'])
            band.journal.record('repost_inventory_proven', read_sha256=proof['read_sha256'],
                                private_proof=private, filled_cap_pusd=band.campaign_policy.raw['per_band_daily_filled_cap_pusd'])
            band._evidence_faults.discard('repost_inventory_unavailable')
            band._evidence_failed = bool(band._evidence_faults)
            if proof_time is None:
                proof_time = band.clock.monotonic()
            cooldown = band.campaign_policy.raw['fill_cooldown_seconds'] if not depth_paused or new_fill else 0
            if band.clock.monotonic() < proof_time + cooldown:
                band.journal.record('repost_cooldown', seconds=cooldown, proven_at_monotonic=proof_time)
                while band.clock.monotonic() < min(proof_time + cooldown, band.deadline):
                    band.control()
                    yield min(1, proof_time + cooldown - band.clock.monotonic())
                continue  # Re-read after cooldown before placing a new pair.
            try:
                band.refresh_repost_prices()
            except HoldEnd as exc:
                if exc.reason != 'thin_book_depth':
                    raise
                depth_paused = True
                next_depth = band.clock.monotonic() + 60
                band.journal.record('depth_paused', reason='thin_book_depth', recheck_seconds=60)
                continue
            break
        try:
            daily_gate(band.ledger, band.ledger.sessions[band.session_id]['start'],
                       reserve=band.size * sum(band.reserve_prices()), journal=band.journal)
        except CapitalRefused as exc:
            raise HoldEnd(str(exc)) from None
        band.repost_waiting = False
        band.closed = band.cleanup_ok = band.cancellation_ok = band.inventory_proven = False
        if depth_paused:
            band.journal.record('depth_resumed', condition_id=band.condition,
                                trade_legs=list(band.TRADE_LEGS))
        band.journal.record('repost_ready', submits_consumed=band.submits, requotes_consumed=band.requotes)
