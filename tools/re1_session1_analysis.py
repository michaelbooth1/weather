"""Offline, stdlib-only desk analysis of the four copied RE-1 session-1 files.

Run with python -I -S tools/re1_session1_analysis.py. Inputs and generated output
are confined to this worktree's data/re1_session1. No campaign access, imports
of project startup code, credentials, network, or trading actions. Numeric
outputs are an explicit allowlist; raw payloads and identifiers are not emitted.
Formula reference: cached reward-test-attended tip 7e6e1709c243cf88aa7799bf4486a9af821abbf5,
re1_attended.observe and reward_share_estimate (not imported or executed).
"""

import base64
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 're1_session1'
FILES = ('journal.jsonl', 'prediction.json', 'selection.json', 'user-stream.jsonl')


def time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def levels(rows):
    result = defaultdict(D)
    for row in rows:
        result[D(row['price'])] += D(row['size'])
    return dict(result)


def remove(book, price, size=D(20)):
    result = book.copy()
    result[price] = max(D(0), result.get(price, D(0)) - size)
    return {p: s for p, s in result.items() if s > 0}


def score(size, distance, maximum, minimum):
    distance = abs(distance)
    return float(size * ((maximum - distance) / maximum) ** 2) if size >= minimum and distance < maximum else 0.0


def side(book, mid, maximum, minimum):
    return sum(score(s, (p-mid)*100, maximum, minimum) for p, s in book.items())


def qmin(a, b, mid):
    return max(min(a, b), max(a, b)/3) if D('.1') <= mid <= D('.9') else min(a, b)


def midpoint(bids, asks, minimum):
    return (max(p for p, s in bids.items() if s >= minimum) + min(p for p, s in asks.items() if s >= minimum)) / 2


def mirror(a, b):
    complement = {1-p: s for p, s in b.items()}
    return [(float(p), float(a.get(p, 0)), float(complement.get(p, 0)))
            for p in sorted(a.keys() | complement.keys()) if a.get(p, 0) != complement.get(p, 0)]


def analyze_minute(row):
    snap = row['snapshot']; v = snap['quote_inputs']; obs = row['observation']
    minimum, maximum, rate = (D(v[k]) for k in ('reward_min_size', 'reward_max_spread_cents', 'reward_rate_per_day'))
    yb, ya, nb, na = (levels(v[k]) for k in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'))
    yp, np = map(D, row['prices']); mid = midpoint(yb, ya, minimum)
    clean = (remove(yb, yp), remove(ya, 1-np), remove(nb, np), remove(na, 1-yp))
    syb, sya = (side(b, mid, maximum, minimum) for b in clean[:2])
    snb, sna = (side(b, 1-mid, maximum, minimum) for b in clean[2:])
    own = qmin(score(D(20), (mid-yp)*100, maximum, minimum), score(D(20), (1-mid-np)*100, maximum, minimum), mid)
    many = (syb+sya)/2; single = qmin(syb, sya, mid)
    # Both representations are redundant under mirroring. Average each
    # corresponding side; never add duplicate displays as independent orders.
    both_many = (syb+sna+sya+snb)/4
    native_many = (syb+snb)/2
    shares = {'many': own/(own+many), 'single': own/(own+single)}
    for label in shares:
        assert abs(shares[label]-obs['share_'+label]) < 1e-12
    assert mid == D(obs['adjusted_mid'])
    own_free_mid = midpoint(clean[0], clean[1], minimum)
    configs = snap['reward_record']['rewards_config']
    day = snap['observed_at_utc'][:10]
    active = [c for c in configs if c['start_date'][:10] <= day <= c['end_date'][:10]]
    raw_books = [r['payload'] for r in snap['raw_public_responses'] if isinstance(r.get('payload'), dict) and 'bids' in r['payload']]
    return {'sequence': row['sequence'], 'at': snap['observed_at_utc'], 'recorded_at': row['recorded_at_utc'],
            'rate': float(rate), 'mid': float(mid), 'mid_without_own': float(own_free_mid),
            'plain_mid': float(obs['plain_mid']), 'own_q': own, 'q_yes_bid': syb, 'q_yes_ask': sya,
            'q_no_bid': snb, 'q_no_ask': sna, 'q_many': many, 'q_single': single,
            'share_many': shares['many'], 'share_single': shares['single'],
            'both_share_many': own/(own+both_many), 'native_bid_share_many': own/(own+native_many),
            'cents_minute': float(rate)/1440*shares['many']*100,
            'mirror_differences': {'yes_bid_no_ask': mirror(yb, na), 'yes_ask_no_bid': mirror(ya, nb)},
            'book_exchange_times': [r.get('timestamp') for r in raw_books],
            'own_at_best_qualifying': [yp == max(p for p,s in yb.items() if s >= minimum), np == max(p for p,s in nb.items() if s >= minimum)],
            'external_at_own_prices': [float(clean[0].get(yp, 0)), float(clean[2].get(np, 0))],
            'distance_cents': [float((mid-yp)*100), float((1-mid-np)*100)],
            'leg_visible': [yb.get(yp,0) >= 20, nb.get(np,0) >= 20],
            'requote_legs': obs['requote_legs'], 'active_configs': len(active),
            'active_rate_sum': sum(float(c['rate_per_day']) for c in active),
            'best_prices': [float(max(yb)), float(min(ya)), float(max(nb)), float(min(na))],
            'qualifying_depth': [{str(p): float(s) for p,s in b.items() if score(s,(p-mid)*100,maximum,minimum)>0} for b in clean[:2]]}


def main():
    if DATA.is_symlink() or DATA.resolve() != DATA:
        raise ValueError('input_directory_must_be_local_to_worktree')
    hashes = {}
    for name in FILES:
        path = DATA / name
        if path.is_symlink() or path.resolve().parent != DATA or path.stat().st_size > 8_000_000:
            raise ValueError('input_path_or_size_refused')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads((DATA/'copy-manifest.json').read_text(encoding='utf-8-sig'))
    assert len(manifest) == len(FILES) and {r['name'] for r in manifest} == set(FILES)
    for row in manifest:
        assert all(row[k].lower() == hashes[row['name']] for k in ('source_before','source_after','copy_sha256'))
    rows = [json.loads(line) for line in (DATA/'journal.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    prediction = json.loads((DATA/'prediction.json').read_text(encoding='utf-8-sig'))
    selection = json.loads((DATA/'selection.json').read_text(encoding='utf-8-sig'))
    stream = [json.loads(line) for line in (DATA/'user-stream.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert prediction['journal_sha256'] == hashes['journal.jsonl']
    by = defaultdict(list)
    for row in rows:
        by[row['event']].append(row)
    minutes = [analyze_minute(row) for row in by['minute']]
    assert len(minutes) == prediction['minute_samples'] == 42
    assert len(by['market_snapshot']) == len(minutes)
    assert all(a['snapshot'] == b['snapshot'] for a,b in zip(by['minute'],by['market_snapshot']))
    sums = {k: sum(m['rate']/1440*m['share_'+k] for m in minutes) for k in ('many','single')}
    assert all(abs(sums[k]-prediction['P_'+k]) < 1e-12 for k in sums)
    for m, row in zip(minutes, by['minute']):
        assert all(abs(m['rate']/1440*m['share_'+k]-row['observation']['per_minute_'+k]) < 1e-12
                   for k in ('many', 'single'))
        assert m['active_rate_sum'] == m['rate']
    accruals = []
    cid = prediction['condition_id']
    for row in by['accrual_response']+by['final_accrual_response']:
        response = row['response']; pct = response['percentages'].get(cid)
        m = min(minutes, key=lambda m: abs((time(m['at'])-time(row['recorded_at_utc'])).total_seconds()))
        accruals.append({'at':row['recorded_at_utc'], 'event':row['event'], 'sequence':row['sequence'],
                         'percentage':pct, 'earnings':sum(float(r['earnings']) for r in response['rows'] if r['condition_id']==cid),
                         'earnings_row_count':len(response['rows']), 'payment_verified':response['payment_verified'],
                         'nearest_minute':m['at'], 'snapshot_age_seconds':(time(row['recorded_at_utc'])-time(m['at'])).total_seconds(),
                         'our_many':m['share_many'], 'our_single':m['share_single'],
                         'k_many':None if pct is None else pct/100/m['share_many'],
                         'k_single':None if pct is None else pct/100/m['share_single']})
    first, last = minutes[0], minutes[-1]
    delta_rate = (last['rate']-first['rate'])/1440*first['share_many']*100
    delta_depth = last['rate']/1440*(last['share_many']-first['share_many'])*100
    changes = [{'at':b['at'], 'q_change':b['q_many']-a['q_many'], 'cents_change':b['cents_minute']-a['cents_minute']}
               for a,b in zip(minutes,minutes[1:])]
    depth_delta = []
    for i in range(2):
        a,b = first['qualifying_depth'][i], last['qualifying_depth'][i]
        depth_delta.append({p:b.get(p,0)-a.get(p,0) for p in sorted(a.keys()|b.keys())})
    trades = []
    for row in by['terminal_trades']:
        for trade in row['rows']:
            ours = [m for m in trade['maker_orders'] if m['order_id'] in prediction['order_ids']]
            trades.append({'sequence':row['sequence'], 'at':trade['matched_at'], 'status':trade['status'],
                           'taker_outcome':trade['outcome'], 'taker_side':trade['side'], 'taker_price':trade['price'],
                           'taker_size':trade['size'], 'fee_rate_bps':trade['fee_rate_bps'],
                           'ours':[{k:m.get(k) for k in ('outcome','side','price','matched_amount','fee_rate_bps')} for m in ours],
                           'maker_amounts':[m['matched_amount'] for m in trade['maker_orders']]})
    # Decode bounded retained public source records; emit structure/counts and
    # explicit numeric fields only, never raw/base64 bodies or arbitrary strings.
    sources = []; reward_records = {}; books = {}
    for record in selection['source_records']:
        raw = base64.b64decode(record['response_body_base64'], validate=True)
        assert hashlib.sha256(raw).hexdigest() == record['response_sha256']
        body = json.loads(raw)
        url = record['url'].split('?',1)[0]
        path = ('reward_market' if '/rewards/markets/' in url else
                'event' if '/events/' in url else
                'book' if url.endswith('/book') else
                'fee_rate' if url.endswith('/fee-rate') else 'other')
        sources.append({'endpoint_tail':path, 'type':type(body).__name__, 'count':len(body)})
        def walk(x):
            if isinstance(x,dict):
                if 'condition_id' in x and 'rewards_config' in x:
                    reward_records[x['condition_id']] = x
                if 'asset_id' in x and 'bids' in x and 'asks' in x:
                    books[x['asset_id']] = x
                for val in x.values(): walk(val)
            elif isinstance(x,list):
                for val in x: walk(val)
        walk(body)
    population = []
    for rec in reward_records.values():
        slug = rec.get('event_slug','')
        date_label = '09-24' if 'september-24-2026' in slug else '09-23' if 'september-23-2026' in slug else 'other'
        token_books = [books.get(t.get('token_id')) for t in rec.get('tokens',[])]
        population.append({'event_date':date_label, 'rate':sum(float(c['rate_per_day']) for c in rec['rewards_config']),
                           'minimum':rec.get('rewards_min_size'), 'books':sum(b is not None for b in token_books)})
    candidates = []
    for r in selection['rows']:
        q = r.get('quote') or {}; v = r.get('snapshot',{}).get('quote_inputs',{})
        candidates.append({'city':r['market_id'], 'target_date':r['target_date'], 'eligible':r['eligible'],
                           'rate':v.get('reward_rate_per_day'), 'mid':q.get('adjusted_mid'),
                           'q_many':q.get('competing_q_many'), 'share_many':q.get('share_many'),
                           'share_single':q.get('share_single'), 'predicted_360':r.get('predicted_360_minutes')})
    # The handoff's 02:30:07 anchor is kept separately from the exchange's
    # second-resolution 02:30:06 match time. Last-known carry is not a markout.
    fill_anchor = time('2026-09-23T02:30:07+00:00')
    fill_quantity = sum(D(m['matched_amount']) for t in trades for m in t['ours'])
    markouts = []
    for horizon in (1, 5, 30):
        target_time = fill_anchor + timedelta(minutes=horizon)
        available = [m for m in minutes if time(m['at']) <= target_time]
        prior = max(available, key=lambda m: time(m['at']))
        bid, ask = map(lambda x:D(str(x)), prior['best_prices'][2:])
        markouts.append({'minutes_after_anchor':horizon, 'target_at':target_time.isoformat(),
                         'last_snapshot_at':prior['at'],
                         'snapshot_age_seconds':(target_time-time(prior['at'])).total_seconds(),
                         'has_post_fill_snapshot':time(prior['at']) >= fill_anchor,
                         'markout':'not identifiable' if time(prior['at']) < fill_anchor else 'observed',
                         'stale_bid_value':float(fill_quantity*bid),
                         'stale_mid_value':float(fill_quantity*(bid+ask)/2),
                         'stale_mid_minus_cost':float(fill_quantity*((bid+ask)/2-D('.48')))})
    final_accrual = accruals[-1]['earnings']
    comparisons = {label:{'prediction':value, 'site_absolute_error':abs(.12-value),
                         'accrual_absolute_error':abs(final_accrual-value),
                         'k_accrual':final_accrual/value} for label,value in sums.items()}
    summary = {'mirror_exact_minutes':sum(not any(m['mirror_differences'].values()) for m in minutes),
               'both_books_prediction_many':sum(m['rate']/1440*m['both_share_many'] for m in minutes),
               'max_share_change':max(abs(m['both_share_many']-m['share_many']) for m in minutes),
               'rate_counts':dict(Counter(m['rate'] for m in minutes)),
               'q_increases':sum(x['q_change']>1e-9 for x in changes),
               'q_decreases':sum(x['q_change']< -1e-9 for x in changes),
               'q_unchanged':sum(abs(x['q_change'])<=1e-9 for x in changes),
               'both_legs_best_minutes':sum(all(m['own_at_best_qualifying']) for m in minutes),
               'own_removal_mid_changes':sum(m['mid_without_own']!=m['mid'] for m in minutes),
               'both_legs_visible_minutes':sum(all(m['leg_visible']) for m in minutes),
               'minimum_external_size_at_own_prices':[min(m['external_at_own_prices'][i] for m in minutes) for i in range(2)],
               'selection_share_many_median':statistics.median(r['share_many'] for r in candidates)}
    output = {'hashes':hashes, 'journal_rows':len(rows), 'minutes':minutes, 'sums':sums,
              'accruals':accruals, 'decomposition_cents':{'total':last['cents_minute']-first['cents_minute'],
              'rate_first':delta_rate, 'depth_second':delta_depth, 'midpoint':0 if all(m['mid']==first['mid'] for m in minutes) else None},
              'depth_delta':depth_delta, 'changes':changes, 'trades':trades,
              'summary':summary, 'markouts':markouts, 'comparisons':comparisons,
              'stream_event_counts':dict(Counter(r['event_type'] for r in stream)),
              'stream_failure_times':[r['recorded_at_utc'] for r in stream if r['event_type']=='stream_failed'],
              'selection_candidates':candidates, 'source_record_count':len(sources),
              'source_endpoints':dict(Counter(r['endpoint_tail'] for r in sources)),
              'source_reward_population':population,
              'initial_collateral':by['initial_balances_response'][0]['response']['available_collateral'],
              'final_collateral':by['final_balances_response'][0]['response']['available_collateral'],
              'terminal_positions_count':len(by['terminal_positions'][0]['rows']),
              'terminal_order_matches':[r['order']['size_matched'] for r in by['terminal_order']]}
    # Re-read only copies after computation; source-copy comparison is in manifest.
    assert all(hashlib.sha256((DATA/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
    target = DATA/'analysis.json'
    if target.is_symlink() or target.resolve().parent != DATA:
        raise ValueError('output_path_refused')
    target.write_text(json.dumps(output, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'verified_files':len(hashes), 'minute_samples':len(minutes), 'predictions':sums,
                      'mirror_mismatch_minutes':sum(any(m['mirror_differences'].values()) for m in minutes),
                      'output':'data/re1_session1/analysis.json'}))


if __name__ == '__main__':
    main()
