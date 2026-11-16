"""Offline T113 proposal/touch replay on hash-bound copies of retained books.

No venue, tick, credentials or order capability is constructed. Observed A fills
are exogenous inputs; touches are never booked as executions. The filtered B
trace suppresses A fills incompatible with B and assumes no replacement fills.
"""
import argparse
import csv
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path
import re
from types import SimpleNamespace

from weather.market.lfc_accounting import quantity
from weather.market.lfc_pair_completion import OwnLot, inventory, instant, quote
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new


BOOK_EVENTS = frozenset({'opening_market_snapshot', 'submit_market_snapshot', 'market_snapshot',
                         'repost_market_snapshot', 'minute'})
BOOK_LINE = re.compile(r'"event"\s*:\s*"(?:' + '|'.join(sorted(BOOK_EVENTS)) + ')"')


class CopiedInputs:
    """Only listed, immutable files inside the declared copy directory are read."""
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        rows = strict_json((self.root / 'copy_manifest.json').read_text(encoding='utf-8-sig'))
        self.receipts = {}
        for row in rows:
            path = Path(row['copy']).resolve(strict=True)
            relative = path.relative_to(self.root).as_posix()
            if relative in self.receipts:
                raise ValueError('replay_duplicate_copy')
            self.receipts[relative] = row
        self.used = {}

    def path(self, relative):
        from weather.operations.live_path_security import validate_regular_nonreparse_file
        path = (self.root / relative).resolve(strict=True)
        key = path.relative_to(self.root).as_posix()
        row = self.receipts.get(key)
        if row is None:
            raise ValueError('replay_unlisted_input')
        validate_regular_nonreparse_file(path)
        if path.stat().st_size != row['length'] or file_sha(path) != row['sha256']:
            raise ValueError('replay_copy_changed')
        self.used[key] = row['sha256']
        return path

    def csv(self, relative):
        with self.path(relative).open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))


@dataclass(frozen=True)
class RecordedBook:
    at: object
    snapshot: dict
    source: str


def read_books(path, *, condition_id, source):
    """Select book events before JSON decoding; do not inspect geography rows."""
    books, seen = [], set()
    with Path(path).open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not BOOK_LINE.search(line):
                continue
            row = strict_json(line)
            if row.get('event') not in BOOK_EVENTS:
                continue
            snap = row.get('snapshot')
            if not isinstance(snap, dict) or snap.get('condition_id') != condition_id:
                raise ValueError('replay_book_scope')
            at = instant(snap['observed_at_utc'])
            if at > instant(row['recorded_at_utc']):
                raise ValueError('replay_book_clock')
            key = (at, json.dumps(snap['quote_inputs'], sort_keys=True))
            if key not in seen:
                books.append(RecordedBook(at, snap, f'{source}:{line_number}'))
                seen.add(key)
    return sorted(books, key=lambda b: b.at)


def candidate(state, book, *, policy, offset):
    """Reuse ordinary midpoint/depth/reward screens for one captured proposal."""
    from weather.market.re1_attended import observe, replacement_price
    from weather.market.lfc_f2_selection import check_book
    from weather.market.mm_stage2_hold import HoldEnd
    from weather.market.reward_quote import QuoteRefused
    snap, values = book.snapshot, book.snapshot['quote_inputs']
    result = {'proposal_at_utc': book.at.isoformat(), 'proposal_source': book.source,
              'screen_refusal': None}
    try:
        first = observe(snap, ['.5', '.5'], 20, (Decimal(20),), trade_legs=(),
                        min_reward_rate=policy.raw['min_reward_rate'])
        normal = tuple(replacement_price(first['adjusted_mid'], leg, Decimal(offset)) for leg in (0, 1))
        token = snap['token_ids'][state.completion_leg]
        rules = snap['rules'][token]
        proposed = quote(state, normal, tick=rules['tick_size'], leg_bounds=policy.raw['leg_price_range'],
                         min_order_size=rules['min_order_size'], reward_min_size=values['reward_min_size'])
        result.update(proposed.evidence())
        if not proposed.allowed:
            result['screen_refusal'] = proposed.refusal
            return result
        prices = list(normal)
        prices[proposed.leg] = proposed.price
        observation = observe(snap, prices, 20, (Decimal(20),), trade_legs=(proposed.leg,),
                              min_reward_rate=policy.raw['min_reward_rate'])
        check_book(values, mid=observation['adjusted_mid'], size=20,
                   share=observation['share_many'], policy=policy)
        asks = values['yes_asks' if proposed.leg == 0 else 'no_asks']
        best = min(quantity(row['price']) for row in asks if quantity(row['size']) > 0)
        if proposed.price >= best:
            result['screen_refusal'] = 'fresh_ask'
        if quantity(rules['tick_size']) != Decimal('.01'):
            result['screen_refusal'] = 'market_rules'
    except (HoldEnd, QuoteRefused) as exc:
        result['screen_refusal'] = str(getattr(exc, 'reason', exc))
    return result


def touch_evidence(books, *, leg, price, after, end):
    """A positive displayed ask at/below a proposal is evidence of touch only."""
    matches, available = [], []
    for book in books:
        if not after < book.at <= end:
            continue
        asks = book.snapshot['quote_inputs']['yes_asks' if leg == 0 else 'no_asks']
        levels = [(quantity(r['price']), quantity(r['size'])) for r in asks if quantity(r['size']) > 0]
        if not levels:
            continue
        available.append(book.at)
        best = min(p for p, _ in levels)
        if best <= price:
            matches.append((book, best, sum(s for p, s in levels if p <= price)))
    result = {'touch_evidence': bool(matches) if available else None,
              'later_book_count': len(available), 'touch_book_count': len(matches),
              'first_touch_at_utc': None, 'first_touch_ask': None, 'first_touch_displayed_size': None,
              'first_touch_source': None,
              'last_later_book_at_utc': available[-1].isoformat() if available else None}
    if matches:
        book, ask, size = matches[0]
        result.update(first_touch_at_utc=book.at.isoformat(), first_touch_ask=str(ask),
                      first_touch_displayed_size=str(size), first_touch_source=book.source)
    return result


def residual_variance(states, probabilities):
    """Illustrative independent binary payout proxy, never an edge estimate."""
    return sum((s.u*s.u*quantity(probabilities[c])*(1-quantity(probabilities[c]))
                for c, s in states.items()), Decimal(0))


def replay_fills(fills, books, bands, *, policy, end):
    """Two transparent traces: actual A and B-filtered observed fills, no new fills."""
    actual, filtered, rows = [], [], []
    campaign = policy.raw['campaign_id']
    for fill in sorted(fills, key=lambda f: instant(f['time'])):
        band = bands[(fill['session'], fill['band'])]
        condition = band['condition_id']
        lot = OwnLot(fill['trade_id'], fill['order_id'], campaign, condition,
                     {'yes': 0, 'no': 1}[fill['leg'].lower()], fill['size'], fill['price'], instant(fill['time']))
        if fill['status'] != 'CONFIRMED' or fill['side'] != 'BUY' or fill['trader_side'] != 'MAKER':
            raise ValueError('replay_own_confirmed_maker_required')
        before = inventory(filtered, campaign_id=campaign, condition_id=condition)
        rejection = None
        if before.completing:
            if lot.leg != before.completion_leg:
                rejection = 'overheld_side_suppressed'
            elif lot.price > ((1-before.average_cost-Decimal('.015')) / Decimal('.01')).to_integral_value(
                    rounding=ROUND_FLOOR)*Decimal('.01'):
                rejection = 'observed_price_exceeds_pair_cap'
        actual.append(lot)
        if rejection is None:
            filtered.append(lot)
        a = inventory(actual, campaign_id=campaign, condition_id=condition)
        b = inventory(filtered, campaign_id=campaign, condition_id=condition)
        row = {'trade_id': lot.trade_id, 'order_id': lot.order_id, 'fill_at_utc': lot.at_utc.isoformat(),
               'market': fill['market'], 'condition_id': condition, 'leg': fill['leg'],
               'actual_fill_size': str(lot.shares), 'actual_fill_price': str(lot.price),
               'a_u_after': str(a.u), 'b_u_after': str(b.u), 'b_observed_fill_admitted': rejection is None,
               'b_observed_fill_refusal': rejection,
               'b_unpaired_avg_cost': str(b.average_cost) if b.u else None,
               'b_completion_leg': b.completion_leg, 'b_pair_cap': str(1-b.average_cost-Decimal('.015')) if b.u else None,
               'screen_refusal': None, 'touch_evidence': None}
        if b.completing:
            # This is the first recorded fresh-book opportunity after the
            # unchanged cooldown, not a claim of unrecorded private proof.
            eligible = [book for book in books[condition]
                        if lot.at_utc+timedelta(seconds=policy.raw['fill_cooldown_seconds']) <= book.at <= end]
            if not eligible:
                row['screen_refusal'] = 'no_recorded_book_after_cooldown'
            else:
                book = eligible[0]
                row.update(candidate(b, book, policy=policy, offset=band['offset']))
                if not row['screen_refusal']:
                    cost = sum((l.shares*l.price for l in filtered if l.condition_id == condition), Decimal(0))
                    if cost+20*quantity(row['capped_completion_price']) > quantity(policy.raw['per_band_daily_filled_cap_pusd']):
                        row['screen_refusal'] = 'per_band_daily_filled_cap'
                if not row['screen_refusal']:
                    row.update(touch_evidence(books[condition], leg=b.completion_leg,
                        price=quantity(row['capped_completion_price']), after=book.at, end=end))
        rows.append(row)
    conditions = {lot.condition_id for lot in actual}
    return rows, {c: inventory(actual, campaign_id=campaign, condition_id=c) for c in conditions}, {
        c: inventory(filtered, campaign_id=campaign, condition_id=c) for c in conditions}


def run(input_root, output):
    inputs = CopiedInputs(input_root)
    policy = SimpleNamespace(raw=strict_json(read_bytes(inputs.path('campaign.json'), 65536)))
    fills, band_rows = inputs.csv('fills.csv'), inputs.csv('bands.csv')
    bands = {(r['session'], r['band']): r for r in band_rows}
    sessions = sorted({r['session'] for r in fills})
    books = {}
    # Restrict the journal reads to the two retained sessions containing fills.
    for session in sessions:
        directories = [key.split('/')[0] for key in inputs.receipts
                       if key.startswith('session-F2-'+session) and key.endswith('/f2_manifest.json')]
        if len(directories) != 1:
            raise ValueError('replay_session_binding')
        for (sid, name), band in bands.items():
            if sid != session:
                continue
            relative = f'{directories[0]}/{name}/journal.jsonl'
            books.setdefault(band['condition_id'], []).extend(read_books(inputs.path(relative),
                condition_id=band['condition_id'], source=relative))
    for rows in books.values():
        rows.sort(key=lambda b: b.at)
    end = instant('2026-11-13T23:45:00Z')
    rows, actual, filtered = replay_fills(fills, books, bands, policy=policy, end=end)
    # A091's exact comparison probabilities are its fresh post-session market
    # mids; preserve that illustrative convention, not a fitted probability.
    probabilities = {}
    for fill in fills:
        c = bands[(fill['session'], fill['band'])]['condition_id']
        p = quantity(fill['latest_public_mid'])
        probabilities[c] = p if fill['leg'].lower() == 'yes' else 1-p
    report = {'analysis': 'T113 copied November 13 proposal and touch replay',
        'fill_assumption': 'Observed A fills filtered by complementary side and margin cap; no new fills assumed.',
        'touch_is_fill': False, 'inputs_sha256': inputs.used, 'fills': rows,
        'a_inventory': {c: s.evidence() for c, s in actual.items()},
        'b_filtered_inventory': {c: s.evidence() for c, s in filtered.items()},
        'a_residual_variance_proxy': str(residual_variance(actual, probabilities)),
        'b_filtered_residual_variance_proxy': str(residual_variance(filtered, probabilities)),
        'probabilities': {c: str(p) for c, p in probabilities.items()},
        'over_completions': sum(len(s.flips) for s in filtered.values()),
        'new_completion_fills_assumed': 0,
        'full_day_dry_run': 'NOT_REPRODUCIBLE',
        'missing_for_full_day': ['Recorded day begins after 13:43 ET, not 09:00.',
            'No continuous post-retirement or post-fill books for several bands.',
            'No counterfactual private inventory, order ACK, geoblock pass/fail, stream and cash proofs.',
            'Displayed-book touch cannot identify execution, queue priority or the resulting later fill path.']}
    write_new(Path(output), report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.input_root.is_absolute() or not args.output.is_absolute():
        parser.error('absolute copied-input and output paths required')
    if args.input_root.resolve() == args.output.resolve() or args.input_root.resolve() in args.output.resolve().parents:
        parser.error('output must be outside immutable input copies')
    report = run(args.input_root, args.output)
    print(json.dumps({key: report[key] for key in ('a_residual_variance_proxy',
          'b_filtered_residual_variance_proxy', 'over_completions', 'full_day_dry_run')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
