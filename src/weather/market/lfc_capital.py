"""F2's fixed sleeve, in collateral native units, on the existing account ledger.

The old L remains an immutable historical measure. It is NOT the F2 admission
rail. A terminal fill creates a cost-basis lot; only evidenced redemption can
release that basis. Neither prices, predicted income nor an unknown payout can
release money. All mutations are events of the existing single ledger writer.
"""
from decimal import Decimal, ROUND_CEILING
import re

from weather.market.lfc_accounting import quantity
from weather.market.mm_stage2_hold import digest, utc


DECIMALS = 6
SCALE = 10 ** DECIMALS
ASSET = '0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb'
MODE = 'fixed_sleeve_redeemed_principal_only'
CEILING = 300 * SCALE
EVENTS = {'capital_anchor', 'capital_bridge', 'capital_native_group', 'capital_activity', 'capital_resolution',
          'capital_cost', 'capital_zero_resolution'}


class CapitalRefused(ValueError):
    pass


def native(value, *, ceil=False):
    scaled = quantity(value) * SCALE
    if ceil:
        return int(scaled.to_integral_value(rounding=ROUND_CEILING))
    if scaled != scaled.to_integral_value():
        raise CapitalRefused('capital_native_precision')
    return int(scaled)


def pusd(value):
    return str(Decimal(value) / SCALE)


def integer(value):
    if type(value) is not int or value < 0:
        raise CapitalRefused('capital_native_integer')
    return value


def fill_lots(ledger):
    terminal_at = {r['order_id']: r['sequence'] for r in ledger.rows if r['event'] == 'leg_terminal'}
    intent_at = {r['intent_key']: r['recorded_at_utc'] for r in ledger.rows if r['event'] == 'leg_intent'}
    return {key: {'token_id': leg['token_id'], 'condition_id': leg['condition_id'],
                  'quantity': quantity(leg['size_matched']),
                  'remaining_quantity': quantity(leg['size_matched']),
                  'basis': native(quantity(leg['size_matched']) * quantity(leg['price']), ceil=True),
                  'remaining_basis': native(quantity(leg['size_matched']) * quantity(leg['price']), ceil=True),
                  'session_id': leg['session_id'], 'intent_at_utc': intent_at[key],
                  'terminal_sequence': terminal_at.get(leg['order_id'], len(ledger.rows))}
            for key, leg in ledger.legs.items() if leg['status'] == 'terminal' and quantity(leg['size_matched'])}


class CapitalBook:
    """Deterministic replay. No independent money file or in-memory credit."""
    def __init__(self, ledger):
        self.ledger = ledger
        self.lots = fill_lots(ledger)
        self.bridge = None
        self.anchor = None
        self.losses = self.profit = self.incentives = self.costs = self.external = 0
        self.cash_in = self.cash_out = self.returned_principal = 0
        self.seen = set()
        self.removed = {}
        self.removal_events = []
        self.redeemed_transactions = {}
        self.unknown = []
        self.allocations = []
        self.zero_resolutions = []
        self.activities, self.sources, self.activity_sequences, self.redemptions = {}, {}, {}, {}
        self.activity_transactions = {}
        self.native_groups, self.native_bytes = {}, 0
        self.bridge_quarantine = None
        self.legacy_reclassified = self.withdrawal_costs = 0
        self.pool_movements, self.pools_dirty = [], False
        for row in getattr(ledger, 'capital_rows', []):
            self.apply(row)
        self.refresh_pools()

    def apply(self, row):
        event = row['event']
        if event == 'capital_native_group':
            from weather.market.lfc_capital_native import cash_native
            proof, sha = row['proof'], row['proof_sha256']
            if sha in self.native_groups or digest(proof) != sha:
                raise CapitalRefused('capital_native_group_identity')
            encoded = len(proof.get('receipt', {}).get('raw_response', '')) if proof.get('receipt') else 0
            if proof.get('failed_response'):
                from weather.market.lfc_recording_io import response_bytes
                encoded += len(response_bytes(proof['failed_response']))
            from weather.market.lfc_recording_io import response_bytes
            encoded += sum(len(response_bytes(v)) for v in proof.get('ctf_views', {}).values())
            if self.native_bytes + encoded > 64_000_000:
                raise CapitalRefused('capital_native_storage_budget')
            for source in proof['rows']:
                cash_native(source, proof)
            self.native_groups[sha] = proof
            self.native_bytes += encoded
        elif event == 'capital_anchor':
            baseline = row['baseline']
            if (self.anchor is not None or row['baseline_sha256'] != digest(baseline) or
                    not any(r['sha256'] == row['baseline_sha256'] for r in self.ledger.baselines) or
                    baseline['maker_address'].lower() != self.ledger.rows[0]['maker_address'].lower()):
                raise CapitalRefused('capital_baseline_anchor')
            self.anchor = baseline
        elif event == 'capital_bridge':
            if self.bridge is not None:
                raise CapitalRefused('capital_bridge_already_exists')
            if self.unknown != []:
                raise CapitalRefused('capital_bridge_unknown_cash')
            if (row.get('mode') != MODE or row.get('asset') != ASSET or row.get('decimals') != DECIMALS or
                    integer(row['funding_native']) > CEILING or row['funding_native'] == 0 or
                    integer(row['owner_funding_ceiling_native']) > CEILING or
                    row['funding_native'] > row['owner_funding_ceiling_native'] or
                    row.get('legacy_head') != row.get('previous_sha256') or
                    self.anchor is None or not isinstance(row.get('proof'), dict) or row['proof'].get('complete') is not True or
                    row.get('proof_sha256') != digest(row['proof']) or
                    row['proof'].get('legacy_L_native') != legacy_exposure(self.ledger, row['sequence']) or
                    row['proof'].get('genesis_sha256') != self.ledger.row_sha256(0) or
                    row['proof'].get('baseline_sha256') != digest(self.anchor) or
                    row['proof'].get('asset') != ASSET or row['proof'].get('decimals') != DECIMALS or
                    row['proof'].get('cash_native') != row.get('cash_native') or
                    any(not isinstance(row['proof'].get(key), str) or
                        re.fullmatch('[0-9a-f]{64}', row['proof'][key]) is None
                        for key in ('read_sha256', 'activity_packet_sha256')) or
                    row['proof'].get('inventory', {}).get('changed') != [] or
                    row['proof']['inventory'].get('expected') != prefix_inventory(self.ledger, self.anchor, row['sequence'])):
                raise CapitalRefused('capital_bridge_unreconciled')
            self.bridge = row
            self.refresh_pools()
            quarantine = integer(row['external_cash_native']) - self.external
            if quarantine < 0:
                raise CapitalRefused('capital_bridge_external_cash')
            # Known external cash already has its own grant. Only the excess
            # balance is available to reclassify when an older credit arrives.
            self.bridge_quarantine = self.credit('external', quarantine, {
                'timestamp': int(utc(row['recorded_at_utc']).timestamp()), 'id': 'bridge-quarantine'},
                sequence=row['sequence'])
            integer(row['cash_native'])
        elif event == 'capital_activity':
            activity = row['activity']
            evidence = row.get('native_evidence', self.native_groups.get(row.get('native_group_sha256')))
            if self.ledger.enrollment is not None and evidence is None:
                raise CapitalRefused('capital_native_evidence_required')
            if row.get('source_sha256') != digest(row['source']) or normalize_activity(row['source'], evidence) != activity:
                raise CapitalRefused('capital_activity_source')
            if activity['wallet'] != self.ledger.rows[0]['maker_address'].lower():
                raise CapitalRefused('capital_activity_wallet')
            key = activity['id']
            if key in self.seen:
                raise CapitalRefused('capital_activity_repeated')
            self.seen.add(key)
            self.activities[key] = activity
            self.sources[key] = row['source_sha256']
            self.activity_sequences[key] = row['sequence']
            self.activity_transactions[key] = str(row['source']['transaction_hash']).lower()
            cash = activity['cash_native']
            kind = activity['type']
            included = self.cash_before_bridge(activity)
            if (included and cash is not None and self.incoming(activity) and kind != 'DEPOSIT' and
                    not self.known_redemption_cash(activity)):
                self.reclassify_legacy_credit(cash)
            if kind == 'REDEEM':
                self.redeem(activity, row['sequence'])
            elif kind in {'REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE', 'REFERRAL_REWARD'}:
                if cash is None:
                    self.unknown.append(key)
                else:
                    self.credit('incentives', cash, activity)
                    if not included:
                        self.cash_in += cash
            elif kind == 'DEPOSIT':
                if cash is None:
                    self.unknown.append(key)
                else:
                    # Every later contribution is segregated, never new principal.
                    if self.deposit_is_external(activity):
                        self.credit('external', cash, activity)
                    if not included:
                        self.cash_in += cash
            elif kind == 'TIP' and activity['direction'] == 'IN':
                if cash is None:
                    self.unknown.append(key)
                else:
                    self.credit('external', cash, activity)
                    if not included:
                        self.cash_in += cash
            elif kind in {'WITHDRAWAL', 'TIP'}:
                if cash is None:
                    self.unknown.append(key)
                else:
                    self.withdraw(cash, activity, counted=not included)
            else:
                raise CapitalRefused('capital_activity_type')
        elif event == 'capital_resolution':
            evidence = row.get('native_evidence', self.native_groups.get(row.get('native_group_sha256')))
            if self.ledger.enrollment is not None and evidence is None:
                raise CapitalRefused('capital_native_evidence_required')
            item = normalize_activity(row['source'], evidence)
            old = self.activities.get(item['id'])
            if (old is None or item['cash_native'] is None or
                    old['cash_native'] is not None and not ('native_redemption' not in old and 'native_redemption' in item) or
                    old['cash_native'] is not None and old['cash_native'] != item['cash_native'] or
                    row.get('source_sha256') != digest(row['source']) or
                    row.get('previous_source_sha256') != self.sources[item['id']] or
                    {k: v for k, v in item.items() if k not in {'cash_native', 'native_redemption', 'principal_unproved'}} !=
                    {k: v for k, v in old.items() if k not in {'cash_native', 'native_redemption', 'principal_unproved'}}):
                raise CapitalRefused('capital_resolution_scope')
            cash, kind = item['cash_native'], item['type']
            before_bridge = self.bridge is not None and (self.activity_sequences[item['id']] < self.bridge['sequence'] or
                                                        self.cash_before_bridge(item))
            if (before_bridge and old['cash_native'] is None and self.incoming(item) and kind != 'DEPOSIT' and
                    not self.known_redemption_cash(item)):
                # The first balance already contains this previously unknown
                # incoming credit. Reclassify its quarantined cash; never add
                # the same receipt to the bridge a second time.
                self.reclassify_legacy_credit(cash)
            if kind == 'REDEEM':
                self.undo_redemption(old)
                self.redeem(item, row['sequence'])
            elif kind in {'REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE', 'REFERRAL_REWARD'}:
                self.credit('incentives', cash, item)
            elif kind == 'DEPOSIT':
                if self.deposit_is_external(item):
                    self.credit('external', cash, item)
            elif kind == 'TIP' and item['direction'] == 'IN':
                self.credit('external', cash, item)
            elif kind in {'WITHDRAWAL', 'TIP'}:
                self.withdraw(cash, item, counted=not before_bridge)
            if kind != 'REDEEM' and not before_bridge and self.incoming(item):
                self.cash_in += cash
            if item['id'] in self.unknown:
                self.unknown.remove(item['id'])
            self.activities[item['id']], self.sources[item['id']] = item, row['source_sha256']
        elif event == 'capital_zero_resolution':
            from weather.market.lfc_settlement_record import validate_settlement_row, envelope
            from weather.market.lfc_recording_io import response_bytes
            record = validate_settlement_row(row['settlement'], row['condition_id'])
            if record.get('terminal') is not True or row.get('settlement_sha256') != digest(record):
                raise CapitalRefused('capital_zero_resolution_evidence')
            payouts = envelope(response_bytes(record['resolution']))['data'][0]['payouts']
            zero_tokens = {token for token, payout in zip(record['token_ids'], payouts) if payout == 0}
            keys = row.get('intent_keys')
            if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)):
                raise CapitalRefused('capital_zero_resolution_scope')
            for key in keys:
                lot = self.lots[key]
                if (lot['condition_id'] != row['condition_id'] or lot['token_id'] not in zero_tokens or
                        lot['terminal_sequence'] >= row['sequence'] or lot['remaining_basis'] <= 0 or
                        lot['remaining_quantity'] <= 0 or lot.get('zero_payout_evidence_sha256')):
                    raise CapitalRefused('capital_zero_resolution_scope')
                self.losses += lot['remaining_basis']
                self.zero_resolutions.append({'intent_key': key, 'token_id': lot['token_id'],
                    'realized_loss_native': lot['remaining_basis'], 'settlement_sha256': row['settlement_sha256']})
                lot['remaining_basis'] = 0
                lot['zero_payout_evidence_sha256'] = row['settlement_sha256']
                # Physical quantity remains until an actual burn is proved.
        elif event == 'capital_cost':
            if row.get('evidence_sha256') != digest(row.get('evidence')) or row.get('cost_id') in self.seen:
                raise CapitalRefused('capital_cost_evidence')
            self.seen.add(row['cost_id'])
            self.costs += integer(row['amount_native'])
            if row.get('paid') is True:
                self.cash_out += row['amount_native']
            elif row.get('paid') is not False:
                raise CapitalRefused('capital_cost_paid_flag')
        else:
            raise CapitalRefused('capital_event')

    @staticmethod
    def incoming(activity):
        return activity['type'] not in {'WITHDRAWAL', 'TIP'} or activity.get('direction') == 'IN'

    def cash_before_bridge(self, activity):
        # Reclassify strictly older legacy cash within the immutable bridge.
        # Same-second rows require fresh cash reconciliation; their ordering
        # cannot be proved from the Data API's whole-second timestamp.
        return self.bridge is not None and activity['timestamp'] < int(utc(self.bridge['recorded_at_utc']).timestamp())

    def known_redemption_cash(self, activity):
        if activity['type'] != 'REDEEM':
            return False
        tx = self.activity_transactions[activity['id']]
        return any(key != activity['id'] and self.activity_transactions[key] == tx and
                   prior['type'] == 'REDEEM' and prior['cash_native'] == activity['cash_native']
                   for key, prior in self.activities.items())

    def deposit_is_external(self, activity):
        enrollment = self.ledger.enrollment
        return (enrollment is not None and activity['timestamp'] >= utc(enrollment['recorded_at_utc']).timestamp() or
                self.bridge is not None and not self.cash_before_bridge(activity))

    def reclassify_legacy_credit(self, cash):
        # Consume ONLY quarantine originating at the bridge, never a later
        # deposit. Otherwise a top-up could replace misclassified principal.
        quarantined = min(cash, self.bridge_quarantine['amount'])
        reduction = cash - quarantined
        if self.legacy_reclassified + reduction > self.bridge['funding_native']:
            raise CapitalRefused('capital_legacy_credit_exceeds_funding')
        self.bridge_quarantine['amount'] -= quarantined
        self.pools_dirty = True
        self.legacy_reclassified += reduction

    def credit(self, pool, cash, activity, *, sequence=None):
        movement = {'kind': 'credit', 'pool': pool, 'amount': cash, 'activity_id': activity['id'],
                    'timestamp': activity['timestamp'],
                    'sequence': self.activity_sequences[activity['id']] if sequence is None else sequence}
        self.pool_movements.append(movement)
        self.pools_dirty = True
        return movement

    def withdraw(self, cash, activity, *, counted=True):
        self.pool_movements.append({'kind': 'withdraw', 'amount': cash, 'timestamp': activity['timestamp'],
                                    'sequence': self.activity_sequences[activity['id']]})
        self.pools_dirty = True
        if counted:
            self.cash_out += cash

    def refresh_pools(self):
        if not self.pools_dirty:
            return
        pools, costs = dict.fromkeys(('external', 'profit', 'incentives'), 0), 0
        # Resolving an old debit cannot spend a later deposit. Conversely, a
        # late-known older profit can explain an already-recorded withdrawal.
        # Recompute from retained facts; no ledger event or date is reset.
        # Whole-second activity timestamps do not prove which transaction came
        # first within a second. Charge the debit before an ambiguous credit.
        for move in sorted(self.pool_movements, key=lambda m: (m['timestamp'], m['kind'] == 'credit', m['sequence'])):
            if move['kind'] == 'credit':
                pools[move['pool']] += move['amount']
                continue
            remaining = move['amount']
            for pool in pools:
                taken = min(remaining, pools[pool])
                pools[pool] -= taken
                remaining -= taken
            costs += remaining
        self.costs += costs - self.withdrawal_costs
        self.withdrawal_costs = costs
        self.external, self.profit, self.incentives = (pools[k] for k in ('external', 'profit', 'incentives'))
        self.pools_dirty = False

    def undo_redemption(self, activity):
        key = activity['id']
        redemption = self.redemptions.pop(key)
        self.losses -= redemption['cost_basis_released_native'] - redemption['returned_principal_native']
        self.returned_principal -= redemption['returned_principal_native']
        if activity['cash_native'] is not None and not self.cash_before_bridge(activity) and not redemption.get('duplicate_of'):
            self.cash_in -= activity['cash_native']
        for allocation in self.allocations:
            if allocation['activity_id'] == key:
                lot = self.lots[allocation['intent_key']]
                lot['remaining_quantity'] += quantity(allocation['quantity'])
                lot['remaining_basis'] += allocation['cost_basis_released_native']
        self.allocations = [a for a in self.allocations if a['activity_id'] != key]
        for removal in self.removal_events:
            if removal['activity_id'] == key:
                self.removed[removal['token_id']] -= quantity(removal['quantity'])
        self.removal_events = [r for r in self.removal_events if r['activity_id'] != key]
        self.pool_movements = [m for m in self.pool_movements if m.get('activity_id') != key]
        self.pools_dirty = True
        for tx, owner in list(self.redeemed_transactions.items()):
            if owner == key:
                del self.redeemed_transactions[tx]

    def redeem(self, activity, sequence):
        key, cash = activity['id'], activity['cash_native']
        bundle = activity.get('native_redemption')
        if bundle is not None:
            tx = bundle['transaction_hash']
            if tx in self.redeemed_transactions:
                self.redemptions[key] = {'activity_id': key, 'cash_native': 0,
                    'cost_basis_released_native': 0, 'returned_principal_native': 0,
                    'duplicate_of': self.redeemed_transactions[tx], 'outside_campaign': True}
                return
            # A late receipt proves the whole transaction, not one API row at
            # a time. Undo provisional same-transaction removals before assigning
            # its positions, or another row's unknown burn would hide a lot.
            for other, old in list(self.activities.items()):
                if (other != key and self.activity_transactions[other] == tx and old['type'] == 'REDEEM' and
                        other in self.redemptions and not self.redemptions[other].get('duplicate_of')):
                    if old['cash_native'] not in (None, cash):
                        raise CapitalRefused('capital_redemption_cash_contradiction')
                    self.undo_redemption(old)
                    self.redemptions[other] = {'activity_id': other, 'cash_native': 0,
                        'cost_basis_released_native': 0, 'returned_principal_native': 0,
                        'duplicate_of': key, 'outside_campaign': True}
                    if other in self.unknown:
                        self.unknown.remove(other)
            self.redeemed_transactions[tx] = key
            parts = bundle['positions']
        else:
            parts = [{'token_id': activity['token_id'], 'quantity': activity['quantity'], 'cash_native': cash}]
        basis = principal = outside_cash = 0
        refused = []
        for part in parts:
            token, remaining = part['token_id'], quantity(part['quantity'])
            lots = [(k, lot) for k, lot in self.lots.items() if lot['token_id'] == token and
                    (bundle is not None or lot['condition_id'] == activity['condition_id']) and
                    lot['remaining_quantity'] and lot['terminal_sequence'] < sequence and
                    utc(lot['intent_at_utc']).timestamp() <= activity['timestamp']]
            total = remaining
            # The snapshot already includes older campaign lots. Do not count
            # their quantity a second time as unrelated owner holdings.
            anchor = self.anchor or {}
            cut = next((r['sequence'] for r in self.ledger.baselines if r['sha256'] == digest(anchor)), -1)
            outside = max(Decimal(0), quantity(anchor.get('positions', {}).get(token, 0)) -
                sum((lot['quantity'] for lot in self.lots.values() if lot['token_id'] == token and lot['terminal_sequence'] < cut), Decimal(0)))
            outside -= sum((quantity(r['outside_quantity']) for r in self.removal_events if r['token_id'] == token), Decimal(0))
            capacity = outside + sum((lot['remaining_quantity'] for _, lot in lots), Decimal(0))
            if (remaining <= 0 or remaining > capacity or
                    anchor and activity['timestamp'] < utc(anchor['at_utc']).timestamp()):
                refused.append({'token_id': token, 'reason': 'unproved_or_pre_snapshot_redemption'})
                outside_cash += part['cash_native'] or 0
                continue
            # Fungible outside inventory is consumed first: no unproved choice
            # of which principal lot was redeemed can create sleeve headroom.
            owner_take = min(max(outside, Decimal(0)), remaining)
            remaining -= owner_take
            outside_cash += (int(Decimal(part['cash_native']) * owner_take / total)
                             if part['cash_native'] is not None else 0)
            self.removed[token] = self.removed.get(token, Decimal(0)) + total
            self.removal_events.append({'activity_id': key, 'token_id': token, 'quantity': str(total),
                'outside_quantity': str(owner_take), 'timestamp': activity['timestamp']})
            for intent, lot in lots:
                take = min(remaining, lot['remaining_quantity'])
                if not take:
                    break
                if lot.get('zero_payout_evidence_sha256') and part['cash_native'] not in (None, 0):
                    raise CapitalRefused('capital_zero_payout_contradiction')
                release = (lot['remaining_basis'] if take == lot['remaining_quantity'] else
                           int(Decimal(lot['remaining_basis']) * take / lot['remaining_quantity']))
                payout = (int(Decimal(part['cash_native']) * take / total)
                          if part['cash_native'] is not None and not activity.get('principal_unproved') else 0)
                returned = min(release, payout)
                lot['remaining_quantity'] -= take
                lot['remaining_basis'] -= release
                basis += release
                principal += returned
                remaining -= take
                self.allocations.append({'activity_id': key, 'intent_key': intent, 'quantity': str(take),
                    'cost_basis_released_native': release, 'payout_native': payout, 'returned_principal_native': returned})
        self.redemptions[key] = {'activity_id': key, 'cash_native': cash,
            'cost_basis_released_native': basis, 'returned_principal_native': principal,
            'outside_campaign': basis == 0, 'unallocated': refused}
        self.losses += basis - principal
        self.returned_principal += principal
        if cash is None:
            self.unknown.append(key)
        else:
            self.credit('external', outside_cash, activity)
            self.credit('profit' if basis and not activity.get('principal_unproved') else 'external',
                        max(0, cash - principal - outside_cash), activity)
            if not self.cash_before_bridge(activity):
                self.cash_in += cash

    def figures(self):
        self.refresh_pools()
        inventory = sum(lot['remaining_basis'] for lot in self.lots.values())
        resting = native(self.ledger.L_resting(), ceil=True)
        charged = self.losses + inventory + resting + self.costs
        funding = self.bridge['funding_native'] - self.legacy_reclassified if self.bridge else 0
        return {'funding_native': funding, 'realized_principal_losses_native': self.losses,
                'legacy_cash_reclassified_native': self.legacy_reclassified,
                'owner_contributions_native': funding,
                'owner_funding_ceiling_native': self.bridge['owner_funding_ceiling_native'] if self.bridge else 0,
                'cumulative_purchase_cost_native': sum(lot['basis'] for lot in self.lots.values()),
                'unrecovered_inventory_cost_native': inventory, 'resting_reserve_native': resting,
                'paid_or_reserved_campaign_costs_native': self.costs,
                'segregated_profit_native': self.profit, 'segregated_incentives_native': self.incentives,
                'segregated_external_cash_native': self.external, 'charged_native': charged,
                'headroom_native': max(0, funding - charged), 'returned_principal_native': self.returned_principal,
                'unknown_payouts': list(self.unknown), 'cost_basis_releases': list(self.allocations),
                'zero_payout_losses': list(self.zero_resolutions),
                'redemptions': list(self.redemptions.values())}

    def gate(self, *, reserve, available_cash=None, own_resting=0):
        if self.bridge is None:
            raise CapitalRefused('capital_bridge_required')
        if self.ledger.halted or self.ledger.mismatches:
            raise CapitalRefused('capital_ledger_halted')
        if any(self.activities[key]['type'] == 'WITHDRAWAL' or
               self.activities[key]['type'] == 'TIP' and self.activities[key].get('direction') != 'IN'
               for key in self.unknown):
            raise CapitalRefused('capital_unknown_outgoing_cost')
        if any(self.cash_before_bridge(self.activities[key]) for key in self.unknown):
            raise CapitalRefused('capital_legacy_unknown_cash')
        reserve, own = native(reserve, ceil=True), native(own_resting)
        figures = self.figures()
        if own > figures['resting_reserve_native']:
            raise CapitalRefused('capital_own_reserve')
        if figures['charged_native'] - own + reserve > figures['funding_native']:
            raise CapitalRefused('capital_total_ceiling')
        if available_cash is not None:
            cash = native(available_cash)
            expected = self.expected_cash()
            if cash < expected:
                # An unexplained debit could be a fill or a payable cost. It
                # cannot be ignored while admitting another order.
                raise CapitalRefused('capital_cash_changed')
            # Unrecorded incoming profit/top-ups never become spendable merely
            # because the wallet balance increased during an active session.
            cash = min(cash, expected)
            segregated = self.profit + self.incentives + self.external
            # A reserve includes own still-resting legs exactly once.
            if cash - segregated < figures['resting_reserve_native'] - own + reserve:
                raise CapitalRefused('capital_spendable_cash')
        return figures

    def expected_cash(self):
        if self.bridge is None:
            raise CapitalRefused('capital_bridge_required')
        anchor = self.bridge
        return (anchor['cash_native'] - (sum(lot['basis'] for lot in self.lots.values()) - anchor['purchased_native_at_bridge']) +
                self.cash_in - anchor['cash_in_at_bridge'] - self.cash_out + anchor['cash_out_at_bridge'])


def legacy_exposure(ledger, sequence):
    intents, orders = {}, {}
    for row in ledger.rows[:sequence]:
        if row['event'] == 'leg_intent':
            intents[row['intent_key']] = [quantity(row['price']), quantity(row['size'])]
        elif row['event'] in {'leg_ack', 'leg_adopt'}:
            orders[row['order_id']] = row['intent_key']
        elif row['event'] == 'leg_terminal':
            intents[orders[row['order_id']]][1] = quantity(row['size_matched'])
    return native(sum((price * size for price, size in intents.values()), Decimal(0)), ceil=True)


def prefix_inventory(ledger, baseline, sequence):
    """Reconstruct the bridge's inventory at its own historical prefix."""
    from weather.market.mm_stage2_hold import utc
    cut = next(row['sequence'] for row in ledger.baselines if row['sha256'] == digest(baseline))
    intents, orders, before, after = {}, {}, {}, {}
    expected = {token: quantity(size) for token, size in baseline['positions'].items()}
    for row in ledger.rows[:sequence]:
        event = row['event']
        if event == 'leg_intent':
            intents[row['intent_key']] = row['token_id']
        elif event in {'leg_ack', 'leg_adopt'}:
            orders[row['order_id']] = row['intent_key']
        elif event == 'leg_terminal':
            after[row['order_id']] = quantity(row['size_matched'])
            if row['sequence'] < cut:
                before[row['order_id']] = quantity(row['size_matched'])
    for oid, size in after.items():
        token = intents[orders[oid]]
        expected[token] = expected.get(token, Decimal(0)) + size - before.get(oid, Decimal(0))
    from types import SimpleNamespace
    prefix_keys = {r['intent_key'] for r in ledger.rows[:sequence] if r['event'] == 'leg_intent'}
    prefix = SimpleNamespace(rows=ledger.rows[:sequence], capital_rows=[r for r in ledger.capital_rows if r['sequence'] < sequence and r['event'] != 'capital_bridge'],
        legs={key: leg for key, leg in ledger.legs.items() if key in prefix_keys},
        baselines=ledger.baselines, enrollment=ledger.enrollment)
    for removal in CapitalBook(prefix).removal_events:
        if removal['timestamp'] >= utc(baseline['at_utc']).timestamp():
            token = removal['token_id']
            expected[token] = expected.get(token, Decimal(0)) - quantity(removal['quantity'])
    if any(size < 0 for size in expected.values()):
        raise CapitalRefused('capital_bridge_inventory')
    return {token: str(size) for token, size in expected.items() if size}


def normalize_activity(row, native_evidence=None):
    """Official /v2/activity shape (OpenAPI), never infer cash from price."""
    required = ('proxy_wallet', 'timestamp', 'condition_id', 'type', 'size', 'usdc_size',
                'transaction_hash', 'token_id')
    if not isinstance(row, dict) or any(key not in row for key in required):
        raise CapitalRefused('capital_activity_shape')
    if not isinstance(row['transaction_hash'], str) or not row['transaction_hash'] or type(row['timestamp']) is not int:
        raise CapitalRefused('capital_activity_identity')
    identity = {'proxy_wallet': str(row['proxy_wallet']).lower(), 'timestamp': row['timestamp'],
                'condition_id': str(row['condition_id']).lower(), 'type': row['type'],
                'transaction_hash': row['transaction_hash'].lower(), 'token_id': str(row['token_id'])}
    if row['type'] == 'TIP' and row.get('side') not in ('IN', 'OUT'):
        raise CapitalRefused('capital_tip_direction')
    if native_evidence is None:
        cash = None if row['usdc_size'] is None else native(row['usdc_size'])
    else:
        from weather.market.lfc_capital_native import cash_native
        cash = cash_native(row, native_evidence)
    bundle = None
    if native_evidence is not None and row['type'] == 'REDEEM' and cash is not None:
        from weather.market.lfc_redemption_native import positions
        bundle = positions(row, native_evidence)
    allocation = ({'native_redemption': bundle} if bundle is not None else
                  {'principal_unproved': True} if native_evidence is not None and row['type'] == 'REDEEM' else {})
    return {**allocation, 'id': digest(identity), 'wallet': str(row['proxy_wallet']).lower(), 'type': row['type'],
            'token_id': str(row['token_id']), 'condition_id': str(row['condition_id']).lower(),
            'quantity': str(quantity(row['size'])),
            'cash_native': cash,
            'timestamp': row['timestamp'], **({'direction': row['side']} if row['type'] == 'TIP' else {})}


def record_activity(ledger, raw, *, native_evidence=None, native_group_sha256=None):
    activity = normalize_activity(raw, native_evidence)
    if activity['wallet'] != ledger.rows[0]['maker_address'].lower():
        raise CapitalRefused('capital_activity_wallet')
    return ledger.record('capital_activity', source=raw, source_sha256=digest(raw), activity=activity,
                         **({'native_group_sha256': native_group_sha256} if native_group_sha256 is not None else
                            {} if native_evidence is None else {'native_evidence': native_evidence}))


def bridge(ledger, *, funding, cash, proof):
    """Install once, only after the caller's read/lot/inventory bridge agrees."""
    if proof.get('complete') is not True or ledger.unresolved_legs() or ledger.open_sessions():
        raise CapitalRefused('capital_bridge_unreconciled')
    book = CapitalBook(ledger)
    if book.unknown:
        raise CapitalRefused('capital_bridge_unknown_cash')
    charged = book.figures()['charged_native']
    ceiling = native(funding)
    contributed = min(ceiling, max(0, native(cash) - book.profit - book.incentives - book.external) + charged)
    principal_cash = contributed - charged
    if principal_cash < 0:
        raise CapitalRefused('capital_bridge_below_legacy_commitment')
    return ledger.record('capital_bridge', mode=MODE, asset=ASSET, decimals=DECIMALS,
                         funding_native=contributed, owner_funding_ceiling_native=ceiling, cash_native=native(cash),
                         external_cash_native=max(0, native(cash) - principal_cash - book.profit - book.incentives),
                         purchased_native_at_bridge=sum(lot['basis'] for lot in book.lots.values()),
                         cash_in_at_bridge=book.cash_in, cash_out_at_bridge=book.cash_out,
                         legacy_head=ledger.previous, proof=proof, proof_sha256=digest(proof))
