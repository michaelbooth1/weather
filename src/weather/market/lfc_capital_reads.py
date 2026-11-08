"""GET-only native cash/lot bridge for F2; no redemption or order capability.

Activity fields and cursor semantics: https://data-api.polymarket.com/v2/openapi.json
pUSD identity/precision: https://docs.polymarket.com/concepts/pusd and /resources/contracts.
The source envelopes live inside retained account reads; normalized movements
and their source rows are anchored in the existing append-only account ledger.
"""
from datetime import datetime, timezone
import time

from weather.market.lfc_accounting import inventory_delta, quantity
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, bridge, native, normalize_activity, record_activity
from weather.market.lfc_recording_io import retained, response_bytes, strict_json
from weather.market.lfc_settlement_record import public_get
from weather.market.mm_stage2_hold import digest


TYPES = ('REDEEM', 'REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE', 'REFERRAL_REWARD', 'DEPOSIT', 'WITHDRAWAL', 'TIP')
MAX_PAGES = 50
MAX_ROWS = 10000
MAX_BYTES = 20_000_000


def read_activity(maker, start, end, *, get=public_get, sleep=time.sleep):
    scope = {'user': maker.lower(), 'start': int(start), 'end': int(end), 'limit': 500,
             'type': ','.join(TYPES), 'sort_by': 'TIMESTAMP', 'sort_direction': 'ASC',
             'exclude_deposits_withdrawals': 'false'}
    if not 0 < scope['start'] <= scope['end']:
        raise CapitalRefused('capital_activity_window')
    pages, cursor, seen, rows, size = [], None, set(), [], 0
    for _ in range(MAX_PAGES):
        params = {**scope, **({'cursor': cursor} if cursor is not None else {})}
        raw = get('/v2/activity', params)
        size += len(raw)
        if size > MAX_BYTES:
            raise CapitalRefused('capital_activity_bytes')
        pages.append(retained(raw))
        page = strict_json(raw)
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise CapitalRefused('capital_activity_envelope')
        for source in page['data']:
            item = normalize_activity(source)
            if (item['wallet'] != scope['user'] or item['type'] not in TYPES or
                    not scope['start'] <= item['timestamp'] <= scope['end']):
                raise CapitalRefused('capital_activity_scope')
            rows.append(source)
        if len(rows) > MAX_ROWS:
            raise CapitalRefused('capital_activity_rows')
        pagination = page.get('pagination')
        if not isinstance(pagination, dict) or type(pagination.get('has_more')) is not bool or 'next_cursor' not in pagination:
            raise CapitalRefused('capital_activity_pagination')
        cursor = pagination['next_cursor']
        if cursor is not None and not isinstance(cursor, str):
            raise CapitalRefused('capital_activity_cursor')
        cursor = cursor or None
        if pagination['has_more'] != (cursor is not None):
            raise CapitalRefused('capital_activity_pagination')
        if cursor is None:
            packet = {'scope': scope, 'pages': pages, 'rows': rows, 'complete': True}
            validate_packet(packet, maker=maker, start=start, end=end)
            return packet
        if cursor in seen:
            raise CapitalRefused('capital_activity_cursor')
        seen.add(cursor)
        sleep(.5)  # bounded public reads, at most two requests per second
    raise CapitalRefused('capital_activity_page_budget')


def validate_packet(packet, *, maker, start, end):
    if packet.get('complete') is not True:
        raise CapitalRefused('capital_activity_incomplete')
    rows, cursors = [], set()
    for index, receipt in enumerate(packet['pages']):
        raw = response_bytes(receipt)
        page = strict_json(raw)
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise CapitalRefused('capital_activity_envelope')
        pagination = page.get('pagination')
        if (not isinstance(pagination, dict) or type(pagination.get('has_more')) is not bool or
                'next_cursor' not in pagination or pagination['has_more'] != (index < len(packet['pages']) - 1)):
            raise CapitalRefused('capital_activity_pagination')
        cursor = pagination['next_cursor'] or None
        if (cursor is not None and (not isinstance(cursor, str) or cursor in cursors) or
                pagination['has_more'] != (cursor is not None)):
            raise CapitalRefused('capital_activity_cursor')
        if cursor is not None:
            cursors.add(cursor)
        rows.extend(page['data'])
    expected_scope = {'user': maker.lower(), 'start': int(start), 'end': int(end), 'limit': 500,
                      'type': ','.join(TYPES), 'sort_by': 'TIMESTAMP', 'sort_direction': 'ASC',
                      'exclude_deposits_withdrawals': 'false'}
    if (not packet['pages'] or len(packet['pages']) > MAX_PAGES or len(rows) > MAX_ROWS or
            sum(len(response_bytes(p)) for p in packet['pages']) > MAX_BYTES or
            packet['scope'] != expected_scope or rows != packet['rows']):
        raise CapitalRefused('capital_activity_packet_binding')
    seen = set()
    for source in rows:
        item = normalize_activity(source)
        if (item['id'] in seen or item['wallet'] != maker.lower() or item['type'] not in TYPES or
                not int(start) <= item['timestamp'] <= int(end)):
            raise CapitalRefused('capital_activity_scope')
        seen.add(item['id'])
    return rows


def synchronize(ledger, baseline, read, *, funding='300'):
    """Reconcile before F2 admission. Repeated reads never repeat a cash credit."""
    if (read.get('complete') is not True or read.get('open_orders') != [] or ledger.unresolved_legs() or
            ledger.open_sessions() or read.get('maker_address', '').lower() != ledger.rows[0]['maker_address'].lower()):
        raise CapitalRefused('capital_bridge_money_unresolved')
    balances = read['balances']
    cash = native(balances['available_collateral'])
    assets = {str(key).lower(): value for key, value in balances.get('assets', {}).items()}
    collateral = balances.get('collateral_evidence') or {}
    if (ASSET not in assets or native(assets[ASSET]) != cash or
            str(collateral.get('balance')) != str(cash)):
        raise CapitalRefused('capital_collateral_identity')
    book = CapitalBook(ledger)
    if book.anchor is None:
        ledger.record('capital_anchor', baseline=baseline, baseline_sha256=digest(baseline))
    elif book.anchor != baseline:
        raise CapitalRefused('capital_original_anchor_changed')
    start = int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp())
    read_end = int(datetime.fromisoformat(read['ended_at_utc']).timestamp())
    end = read['capital_activity']['scope']['end']
    if type(end) is not int or not read_end - 120 <= end <= read_end:
        raise CapitalRefused('capital_activity_read_age')
    sources = validate_packet(read['capital_activity'], maker=ledger.rows[0]['maker_address'], start=start, end=end)
    from weather.market.lfc_capital_native import validate_packet as validate_native, evidence_for
    validate_native(read['capital_activity'], ledger=ledger)
    previous = CapitalBook(ledger)
    group_shas = {}
    from weather.market.lfc_capital_native import resolve
    for tx, reference in read['capital_activity']['native_receipts'].items():
        evidence = resolve(reference, ledger)
        sha = digest(evidence)
        if sha not in previous.native_groups:
            ledger.record('capital_native_group', proof=evidence, proof_sha256=sha)
        group_shas[tx] = sha
    for source in sources:
        evidence = evidence_for(read['capital_activity'], source, ledger=ledger)
        item = normalize_activity(source, evidence)
        old = previous.activities.get(item['id'])
        if old is not None:
            if old != item:
                ledger.record('capital_resolution', source=source, source_sha256=digest(source),
                              previous_source_sha256=previous.sources[item['id']],
                              native_group_sha256=group_shas[evidence['transaction_hash']])
            continue
        record_activity(ledger, source, native_evidence=evidence,
                        native_group_sha256=group_shas[evidence['transaction_hash']])
    from weather.market.lfc_ledger import normalize_positions
    inventory = inventory_delta(ledger, baseline, normalize_positions(read['positions']))
    book = CapitalBook(ledger)
    if inventory['changed']:
        raise CapitalRefused('capital_inventory_unreconciled')
    if any(book.activities[key].get('principal_unproved') and item['cash_native'] is not None and
           item['cost_basis_released_native'] for key, item in book.redemptions.items()):
        raise CapitalRefused('capital_redemption_allocation_unproved')
    if book.bridge is not None:
        expected_cash = book.expected_cash()
        if cash < expected_cash:
            raise CapitalRefused('capital_cash_unreconciled')
    else:
        proof = {'complete': True, 'genesis_sha256': ledger.row_sha256(0),
                 'legacy_L_native': native(ledger.L(), ceil=True), 'inventory': inventory,
                 'baseline_sha256': digest(baseline), 'read_sha256': digest(read),
                 'activity_packet_sha256': digest(read['capital_activity']), 'cash_native': cash,
                 'asset': ASSET, 'decimals': 6, 'native_asset_proof': read['capital_activity']['native_asset_proof']}
        bridge(ledger, funding=funding, cash=balances['available_collateral'], proof=proof)
        book = CapitalBook(ledger)
    book.gate(reserve='0', available_cash=balances['available_collateral'])
    return {'complete': True, 'cash_native': cash, 'inventory': inventory, **book.figures(),
            'legacy_L_native': native(ledger.L(), ceil=True), 'bridge_sha256': digest(book.bridge),
            'cash_bridge_complete': cash == book.expected_cash() and not book.unknown,
            'quarantined_unattributed_incoming_native': max(0, cash - book.expected_cash())}
