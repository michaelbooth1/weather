"""Bounded terminal-account reconciliation for observations made while F2 quoted."""
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, native
from weather.market.lfc_f2_owner_notice import OVERLAP
from weather.market.lfc_ledger import normalize_positions
from weather.market.lfc_owner_close_activity import sources as activity_sources
from weather.market.lfc_owner_external_close import (
    DECODE_ERRORS, PROTOCOL_MOVEMENTS, SCHEMA, SESSION_SCHEMA, WalletCashMismatch,
    attempt_bands, coverage, gap_receipts,
    normalized_sources, protocol_rows, receipt_facts, reconcile, require_gap_snapshot, retained_activity,
)
from weather.market.mm_stage2_hold import _order_id, digest, utc


class ActivityPending(TransientPrecheck):
    """The consumed attempt stays pending until another fresh read can prove it."""

    def __init__(self, reason, *, stage=None):
        super().__init__(reason)
        self.stage = stage


class Budget:
    """Leave time for account freshness and bound each auxiliary read."""
    def __init__(self, clock, *, seconds=40):
        self.clock, self.seconds = clock, seconds
        self.deadline = None
        self.component_times = {}

    def timeout(self, maximum):
        now = self.clock.monotonic()
        if self.deadline is None:
            self.deadline = now + self.seconds
        remaining = self.deadline - now
        if remaining <= 0:
            raise ActivityPending('owner_activity_proof_deadline')
        return min(remaining, maximum)

    def rpc(self, method, params, **kwargs):
        from weather.market.lfc_capital_native import rpc_read
        return rpc_read(method, params, timeout=self.timeout(5), **kwargs)

    def public_get(self, path, params):
        from weather.market.lfc_settlement_record import public_get
        return public_get(path, params, timeout=self.timeout(10))


def enabled(ledger, attempt):
    return any(start.get('autostart_attempt_id') == attempt and 'f2_owner_activity_tokens' in start
               for start in (session['start'] for session in ledger.sessions.values()))


def replay(book, row):
    packet = row['proof']
    try:
        attempt = row['attempt_id']
        bands = attempt_bands(book.ledger, attempt)
        if (packet['schema_version'] != SESSION_SCHEMA or packet['facts']['attempt_id'] != attempt or
                not all(band['start'].get('f2_owner_activity_tokens') for band in bands) or
                any(band['end']['sequence'] >= row['sequence'] for band in bands) or
                packet['facts']['coverage_utc'] != packet['coverage_utc'] or
                not (packet['additional_trades'] or packet['additional_activity']) or
                row['proof_sha256'] != digest(packet)):
            raise StateRefused('owner_activity_proof_binding')
        allocation = reconcile(book, packet, sequence=row['sequence'])
    except (StateRefused, *DECODE_ERRORS) as exc:
        raise CapitalRefused('owner_activity_replay') from exc
    if packet['owner_cash_allocation'] != allocation:
        raise CapitalRefused('owner_external_cash_allocation_changed')


def make_proof(book, attempt, read, notices, budget):
    from weather.market.lfc_capital_reads import read_activity

    ledger, anchor = book.ledger, utc(book.inventory_anchor['snapshot_at_utc'])
    wallet = ledger.rows[0]['maker_address'].lower()
    cut = coverage(read)
    require_gap_snapshot(read)
    trades = normalized_sources(book, read, attempt, cut, fresh=True, session=True)
    rows = retained_activity(ledger, read)
    movement = read_activity(wallet, int(anchor.timestamp()), int(cut.timestamp()),
                             types=PROTOCOL_MOVEMENTS, get=budget.public_get)
    groups = activity_sources(book, [*rows, *protocol_rows(wallet, anchor, cut, movement)], None, cut)
    receipts = {tx: budget.rpc('eth_getTransactionReceipt', [tx]) for tx in sorted(trades)}
    bound_trades = [{'source': trades[tx], 'receipt': receipt_facts(wallet, tx, trades[tx], receipt, improvement=True)}
                    for tx, receipt in receipts.items()]
    observed_ids = {digest(['trade', item['source']['trade_id']]) for item in bound_trades}
    observed_ids.update(digest(['trade', item['sdk_source']['trade_id']])
                        for item in book.personal_trades.values() if 'sdk_source' in item)
    observed_ids.update(digest(['transaction', tx]) for tx in (*book.activity_transactions.values(), *groups))
    for row in read['trades']:
        # A delayed lifecycle message can refer to a trade already included in
        # the anchor, or to a MATCHED event that the REST source settled FAILED.
        # Neither authorizes a booking. The exact cash and position checks
        # must still pass, and only an authenticated own trade can discharge it.
        status = row.get('status')
        if (status == 'FAILED' or status == 'CONFIRMED' and row.get('matched_at') and
                utc(row['matched_at']) < anchor):
            own_taker = row.get('trader_side') == 'TAKER' and str(row.get('maker_address', '')).lower() == wallet
            own_maker = row.get('trader_side') == 'MAKER' and any(
                str(part.get('maker_address', '')).lower() == wallet for part in row.get('maker_orders') or ())
            if (own_taker or own_maker) and isinstance(row.get('id'), str):
                observed_ids.add(digest(['trade', row['id']]))
    pending = None
    if not {identity for _, identity in notices if identity is not None} <= observed_ids:
        pending = 'owner_activity_confirmation_pending'
    elif any(set(item) != {'native_group_sha256'} for item in
             read['capital_activity'].get('pending_native', {}).get('native_receipts', {}).values()):
        pending = 'owner_activity_pending_native'
    cash = native(read['balances']['available_collateral'])
    if ([native(value) for asset, value in read['balances']['assets'].items() if asset.lower() == ASSET] != [cash] or
            str(read['balances']['collateral_evidence']['balance']) != str(cash)):
        raise StateRefused('owner_external_collateral_identity')
    facts = {'schema': SCHEMA, 'attempt_id': attempt, 'anchor_sha256': digest(book.inventory_anchor),
             'coverage_utc': cut.isoformat(), 'trades': []}
    packet = {'schema_version': SESSION_SCHEMA, 'facts': facts, 'facts_sha256': digest(facts),
            'read_sha256': digest(read), 'positions': normalize_positions(read['positions']), 'cash_native': cash,
            'coverage_utc': cut.isoformat(), 'receipts': receipts, 'additional_trades': bound_trades,
            'additional_activity': gap_receipts(book, read, groups, rpc=budget.rpc), 'protocol_movements': movement}
    return packet, pending


def prove(runtime, ledger, attempt, read, traded, notices, budget):
    """Project first. A deferred or contradicted owner packet never books activity."""
    from weather.market.lfc_f2_order_scope import campaign_open_rows

    book = CapitalBook(ledger)
    differences = ledger.trade_mismatches(traded)
    try:
        open_rows = campaign_open_rows(ledger, read['open_orders'])
    except CapitalRefused as exc:
        raise ActivityPending(str(exc)) from exc
    from weather.market.lfc_f2_reconcile import campaign_inventory
    inv = campaign_inventory(ledger, read, book)
    cleanup = not open_rows and not ledger.unresolved_legs()
    runtime._orders_open_unproven = not cleanup
    proof = {'money_accounting_complete': False, 'cleanup_proven': cleanup, 'unknown_submit': False,
             'inventory': inv, 'trade_differences': differences, 'open_orders': len(open_rows),
             'foreign_open_orders': len(read['open_orders']) - len(open_rows),
             'read_sha256': digest(read), 'ledger_head_sha256': ledger.previous,
             'money_contradiction': bool(differences or inv['changed'] or
                 any(event == OVERLAP for event, _ in notices) or
                 any(_order_id(row) not in ledger.our_order_ids() for row in open_rows))}
    if not cleanup or proof['money_contradiction']:
        return proof
    try:
        packet, pending = make_proof(book, attempt, read, notices, budget)
        packet['owner_cash_allocation'] = reconcile(book, packet, sequence=len(ledger.rows),
                                                     collect_inventory=True, rpc=budget.rpc)
    except StateRefused as exc:
        reason = str(exc)
        campaign_cash = isinstance(exc, WalletCashMismatch) and exc.shortfall_native > exc.owner_cover_native
        if reason == 'owner_external_campaign_overlap' or campaign_cash:
            fresh_preflight(runtime, ledger, read)
            proof['money_contradiction'] = True
            proof['owner_activity_reason'] = reason
            return proof
        raise ActivityPending(reason) from exc
    except (OSError, *DECODE_ERRORS) as exc:
        raise ActivityPending('owner_activity_proof_unavailable') from exc
    fresh_preflight(runtime, ledger, read)
    if pending:
        raise ActivityPending(pending)
    try:
        book.gate(reserve='0')
    except CapitalRefused as exc:
        raise ActivityPending(str(exc)) from exc
    if packet['additional_activity'] or packet['additional_trades']:
        ledger.record('capital_f2_owner_activity', attempt_id=attempt, proof=packet, proof_sha256=digest(packet))
    proof.update(money_accounting_complete=True, ledger_head_sha256=ledger.previous,
                 capital={'cash_bridge_complete': True, 'figures': book.figures()})
    return proof


def fresh_preflight(runtime, ledger, read, *, stage='final_account_preflight'):
    from weather.market.lfc_campaign_reads import account_read_age

    if account_read_age(read, runtime.clock.now()) > 120:
        raise ActivityPending('account_read_stale', stage=stage)
    try:
        return runtime.account_read_preflight(ledger, read)
    except TransientPrecheck as exc:
        raise ActivityPending(str(exc), stage=stage) from exc


def gap_evidence(*, now, attempt, result_sha, local, ledger, read, components, stage, reason):
    import re
    from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS, account_read_age

    intervals = {}
    for name in ACCOUNT_READ_COMPONENTS:
        try:
            interval = components[name]
            intervals[name] = {key: utc(interval[key]).isoformat() for key in ('started_at_utc', 'ended_at_utc')}
        except (KeyError, TypeError, ValueError):
            continue
    try:
        age = account_read_age(read, now) if read is not None else None
    except (KeyError, TypeError, ValueError):
        age = None
    return {'at_utc': now.isoformat(), 'attempt_id': attempt,
            'pending_claim_sha256': digest(['f2-owner-postcheck', attempt, result_sha]),
            'stage': stage, 'reason': reason if re.fullmatch(r'[a-z][a-z_0-9]{0,95}', reason)
            else 'owner_activity_proof_unavailable',
            'preflight_age_seconds': age, 'component_times': intervals,
            'result_sha256': result_sha, 'private_evidence_sha256': digest(local),
            'read_sha256': digest(read) if read is not None else None, 'ledger_head_sha256': ledger.previous,
            'monetary_placement_retried': False}
