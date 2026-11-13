"""Current-window native reads plus bounded retries of ledger-bound unknowns."""
from weather.market.mm_stage2_hold import digest


def native_rows(packet, ledger):
    """Pre-enrollment owner history belongs to the opening cash snapshot."""
    from weather.market.lfc_capital import CapitalBook
    from weather.market.mm_stage2_hold import utc
    book = CapitalBook(ledger)
    first = book.inventory_anchors[0] if book.inventory_anchors else None
    cutoff = int(utc(first.get('snapshot_at_utc', first['at_utc'])).timestamp()) if first else packet['scope']['end']
    conditions = {str(leg['condition_id']).lower() for leg in ledger.legs.values()}
    campaign_tx = {str(row['transaction_hash']).lower() for row in packet['rows'] if
                   row['type'] == 'REDEEM' and str(row['condition_id']).lower() in conditions}
    return [row for row in packet['rows'] if (first is not None and row['timestamp'] >= cutoff) or
            str(row['transaction_hash']).lower() in campaign_tx]


def bootstrap_scope(ledger, positions):
    """Find only campaign holdings needing a pre-enrollment redemption proof."""
    from weather.market.lfc_capital import CapitalBook
    from weather.market.lfc_f2_inventory import lot_quantities
    from weather.market.lfc_accounting import quantity, below_position
    from weather.market.lfc_ledger import normalize_positions
    book = CapitalBook(ledger)
    if book.inventory_anchor is not None:
        return None
    observed = normalize_positions(positions)
    missing = sorted(token for token, size in lot_quantities(book, len(ledger.rows)).items()
                     if below_position(observed.get(token, 0), size))
    return scope_for_tokens(ledger, missing) if missing else None


def scope_for_tokens(ledger, tokens):
    from weather.market.mm_stage2_hold import utc
    intents = [row for row in ledger.rows if row['event'] == 'leg_intent' and row['token_id'] in tokens]
    return {'tokens': sorted(tokens), 'start': min(int(utc(row['recorded_at_utc']).timestamp()) for row in intents),
            'conditions': sorted({str(row['condition_id']).lower() for row in intents})}


def bootstrap_sources(packet):
    data = packet.get('bootstrap_activity')
    if data is None:
        return []
    transactions = {str(row['transaction_hash']).lower() for row in data['rows'] if row['type'] == 'REDEEM' and
                    str(row['condition_id']).lower() in packet['bootstrap_scope']['conditions']}
    current = {str(row['transaction_hash']).lower() for row in packet['rows']}
    # Keep every incoming row in a selected transaction. Per-row venue labels
    # cannot split a batched native cash transfer between campaign and owner.
    return [row for row in data['rows'] if str(row['transaction_hash']).lower() in transactions - current]


def require_bootstrap_trades(ledger, trades, tokens):
    """Foreign same-token trades make pre-anchor lot attribution unproved."""
    from weather.market.lfc_capital import CapitalRefused
    from weather.market.mm_stage2_hold import utc
    maker, known = ledger.rows[0]['maker_address'].lower(), ledger.our_order_ids()
    first = {token: min(int(utc(row['recorded_at_utc']).timestamp()) for row in ledger.rows
                        if row['event'] == 'leg_intent' and row['token_id'] == token) for token in tokens}
    def predates(row, token):
        try:
            return utc(row.get('matched_at')).timestamp() < first[token]
        except (TypeError, ValueError, AttributeError):
            return False
    for row in trades:
        if str(row.get('status', '')).upper() == 'FAILED':
            continue
        token = str(row.get('token_id'))
        if (str(row.get('trader_side')).upper() == 'TAKER' and token in tokens and
                row.get('taker_order_id') not in known and not predates(row, token)):
            raise CapitalRefused('f2_bootstrap_campaign_trade')
        for part in row.get('maker_orders', []):
            token = str(part.get('token_id'))
            if (token in tokens and str(part.get('maker_address', '')).lower() == maker and
                    part.get('order_id') not in known and not predates(row, token)):
                raise CapitalRefused('f2_bootstrap_campaign_trade')


def pending_rows(ledger, *, excluding=()):
    from weather.market.lfc_capital import CapitalBook, normalize_activity
    book = CapitalBook(ledger)
    wanted = {book.activity_transactions[key] for key in book.unknown
              if book.activities[key]['cash_native'] is None} - set(excluding)
    sources = {book.sources[key] for key in book.unknown if book.activities[key]['cash_native'] is None}
    if book.pending_native_outgoing:
        for proof in book.native_groups.values():
            for raw in proof['rows']:
                if normalize_activity(raw)['id'] in book.pending_native_outgoing:
                    wanted.add(proof['transaction_hash'])
                    sources.add(digest(raw))
        wanted -= set(excluding)
    groups = {}
    for row in ledger.capital_rows:
        proof = row.get('proof') if row['event'] == 'capital_native_group' else row.get('native_evidence')
        if proof is not None and proof['transaction_hash'] in wanted and any(digest(raw) in sources for raw in proof['rows']):
            groups[proof['transaction_hash']] = proof['rows']
    from weather.market.lfc_capital_native import MAX_NEW_RECEIPTS
    remaining = max(0, MAX_NEW_RECEIPTS - len(set(excluding)))
    return [raw for tx in sorted(groups)[:remaining] for raw in groups[tx]]


def collect_window(packet, *, ledger):
    from weather.market.lfc_capital_native import collect
    selected_rows = native_rows(packet, ledger)
    current = {str(row['transaction_hash']).lower() for row in selected_rows}
    bootstrap = bootstrap_sources(packet)
    selected = current | {str(row['transaction_hash']).lower() for row in bootstrap}
    pending = pending_rows(ledger, excluding=selected)
    observed = collect({**packet, 'rows': selected_rows + bootstrap + pending}, ledger=ledger)
    receipts = observed['native_receipts']
    return {**packet, 'native_asset_proof': observed['native_asset_proof'],
            'native_receipts': {tx: proof for tx, proof in receipts.items() if tx in current},
            'bootstrap_native_receipts': {tx: proof for tx, proof in receipts.items() if tx in selected - current},
            'pending_native': {'rows': pending,
                'native_receipts': {tx: proof for tx, proof in receipts.items() if tx not in selected}}}


def validate_pending(packet, *, ledger, trades=(), original_sha256=None):
    from weather.market.lfc_capital import CapitalBook, CapitalRefused
    from weather.market.lfc_capital_native import validate_packet
    book = CapitalBook(ledger)
    pending = packet.get('pending_native')
    bootstrap = bootstrap_sources(packet)
    bootstrap_receipts = packet.get('bootstrap_native_receipts', {})
    if packet.get('bootstrap_activity') is not None:
        from weather.market.lfc_capital_reads import validate_packet as validate_activity
        scope = packet['bootstrap_scope']
        known = {row['token_id'] for row in ledger.rows if row['event'] == 'leg_intent'}
        if (not isinstance(scope.get('tokens'), list) or not scope['tokens'] or
                not set(scope['tokens']) <= known or scope != scope_for_tokens(ledger, scope['tokens'])):
            raise CapitalRefused('capital_bootstrap_scope')
        if (book.inventory_anchor is not None and
                book.bridge['proof'].get('activity_packet_sha256') != (original_sha256 or digest(packet))):
            raise CapitalRefused('capital_bootstrap_scope')
        require_bootstrap_trades(ledger, trades, scope['tokens'])
        data = packet['bootstrap_activity']
        validate_activity(data, maker=ledger.rows[0]['maker_address'], start=scope['start'], end=data['scope']['end'])
        if data['scope']['end'] != packet['scope']['end']:
            raise CapitalRefused('capital_bootstrap_scope')
        validate_packet({'rows': bootstrap, 'native_receipts': bootstrap_receipts,
                         'native_asset_proof': packet['native_asset_proof']}, ledger=ledger)
    combined = {**packet, 'native_receipts': {**packet['native_receipts'], **bootstrap_receipts}}
    if pending is None:
        return combined, bootstrap
    current = {str(row['transaction_hash']).lower() for row in packet['rows']}
    allowed = {digest(raw) for raw in pending_rows(ledger, excluding=current)}
    for row in ledger.capital_rows:
        if row['event'] not in {'capital_activity', 'capital_resolution'}:
            continue
        allowed.add(row['source_sha256'])
        proof = row.get('native_evidence', book.native_groups.get(row.get('native_group_sha256')))
        if proof is not None:
            allowed.update(digest(raw) for raw in proof['rows'])
    if any(digest(raw) not in allowed or str(raw['transaction_hash']).lower() in current for raw in pending['rows']):
        raise CapitalRefused('capital_pending_native_scope')
    validate_packet({**pending, 'native_asset_proof': packet['native_asset_proof']}, ledger=ledger)
    return {**combined, 'native_receipts': {**combined['native_receipts'], **pending['native_receipts']}}, bootstrap + pending['rows']
