"""Bounded copy-only RE-1 analysis; optional throttled credential-free public reads.

python tools/re1_campaign_analysis_20260924.py --copy-root <owner-copy> --output <scratch>
Use --fetch-public once, then omit it to reproduce from immutable cached responses.
Never point this at an active campaign. No exchange SDK or live commands are imported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FILES = ('prediction.json', 'selection.json', 'journal.jsonl', 'user-stream.jsonl', 'reconciliation.json')
# 89b, d059cc78753757cec6cc1a6ba34cbe03a28f508c: historical modal report
# minutes, NOT actual publication timestamps. No dependency on unmerged code.
STATIONS = {'nyc': ('KLGA', 51), 'miami': ('KMIA', 53), 'atlanta': ('KATL', 52),
            'chicago': ('KORD', 51), 'los-angeles': ('KLAX', 53), 'san-francisco': ('KSFO', 56)}


def stamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('naive timestamp')
    return d.astimezone(timezone.utc)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    if path.stat().st_size > 16 * 1024**2 or path.is_symlink():
        raise ValueError('input exceeds per-file bound or is redirected')
    if path.suffix == '.jsonl':
        with path.open(encoding='utf-8') as stream:
            return [json.loads(line) for line in stream if line.strip()]
    return json.loads(path.read_text(encoding='utf-8'))


def short(value):
    return str(value)[:8] if value else 'unknown'


def book_features(snapshot, adjusted=None):
    q = snapshot['quote_inputs']
    bids, asks = q['yes_bids'], q['yes_asks']
    bid = max(float(x['price']) for x in bids)
    ask = min(float(x['price']) for x in asks)
    mid = (bid + ask) / 2
    center = mid if adjusted is None else float(adjusted)
    distance = float(q['reward_max_spread_cents']) / 100
    # YES book only: complementary NO levels represent the same two sides;
    # adding them would double-count displayed liquidity.
    depth = [sum(float(x['size']) for x in levels
                 if abs(float(x['price']) - center) <= distance + 1e-9)
             for levels in (bids, asks)]
    return {'mid': mid, 'spread': ask - bid, 'bid_depth': depth[0], 'ask_depth': depth[1]}


class PublicCache:
    def __init__(self, root, fetch):
        self.root, self.fetch, self.last = root, fetch, {}
        root.mkdir(parents=True, exist_ok=True)

    def get(self, url, head=False):
        path = self.root / (hashlib.sha256((('HEAD ' if head else '') + url).encode()).hexdigest() + '.json')
        if path.exists():
            return read(path)
        if not self.fetch:
            return {'error': 'not_cached'}
        host = urllib.parse.urlsplit(url).netloc
        time.sleep(max(0, 1.05 - (time.monotonic() - self.last.get(host, 0))))
        self.last[host] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'WeatherResearch/92a copy-analysis'},
                                         method='HEAD' if head else 'GET')
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(8 * 1024**2 + 1) if not head else b'{}'
                headers = dict(response.headers)
            if len(raw) > 8 * 1024**2:
                raise ValueError('response exceeds bound')
            result = {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                      'payload': json.loads(raw), 'headers': headers}
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            result = {'url': url, 'error': type(exc).__name__, 'detail': str(exc)[:200]}
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, sort_keys=True)
        return result


def write_table(out, name, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (out / (name + '.csv')).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze(root, out, fetch=False):
    if not root.is_dir() or root.is_symlink() or 'analysis-copy' not in root.name:
        raise ValueError('requires an explicitly named analysis-copy directory')
    if out.resolve().is_relative_to(root.resolve()):
        raise ValueError('outputs must be outside evidence copy')
    out.mkdir(parents=True, exist_ok=True)
    cache = PublicCache(out / 'public', fetch)
    folders = sorted((p for p in root.iterdir() if re.fullmatch(r'session-\d+', p.name) and p.is_dir()),
                     key=lambda p: int(p.name.split('-')[1]))
    if not 1 <= len(folders) <= 20:
        raise ValueError('session-count bound')
    sessions, minutes, accrual, fills, books, manifest, checkpoints = [], [], [], [], [], [], []
    for folder in folders:
        inputs = {}
        for name in FILES:
            path = folder / name
            if path.exists():
                inputs[name] = read(path)
                manifest.append({'path': folder.name + '/' + name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
        pred, selection, journal = (inputs[k] for k in FILES[:3])
        if sha(folder / 'journal.jsonl') != pred['journal_sha256']:
            raise ValueError('prediction journal binding mismatch: ' + folder.name)
        selected = next(x for x in selection['rows'] if x['condition_id'] == selection['selected_condition_id'])
        condition = selected['condition_id']
        quote, snapshot = selected['quote'], selected['snapshot']
        pick = stamp(snapshot['observed_at_utc'])
        start = stamp(journal[0]['recorded_at_utc'])
        own_ids = set(pred['order_ids'])
        base = {'session': folder.name, 'market': selected['market_id'],
                'band': snapshot['reward_record']['question'], 'target_date': selected['target_date'],
                'pick_utc': pick.isoformat(), 'start_utc': start.isoformat(),
                'pick_local': pick.astimezone(ZoneInfo(selected['market_timezone'])).isoformat(),
                'day_ahead': (datetime.fromisoformat(selected['target_date']).date() -
                              pick.astimezone(ZoneInfo(selected['market_timezone'])).date()).days,
                'Q_pick': quote['competing_q_many'], 'own_Q_pick': quote['own_q_min'],
                'share_pick': quote['share_many'], 'size': quote['size'], **book_features(snapshot, quote['adjusted_mid']),
                'minutes': pred['minute_samples'], 'P_many': pred['P_many'], 'P_single': pred['P_single'],
                'posts': pred['post_count'], 'stop': pred['reason'], 'fill_seen': pred['fill_seen'],
                'evidence_complete': pred['evidence_complete'], 'cleanup_ok': pred['cleanup_ok'],
                'reward_day': pred['reward_day'], 'condition_prefix': short(condition)}
        local_minutes = []
        trades = {}
        for row in journal:
            event, when = row['event'], stamp(row['recorded_at_utc'])
            if event in ('minute', 'market_snapshot', 'submit_market_snapshot') and 'snapshot' in row:
                snap = row['snapshot']
                if 'quote_inputs' in snap:
                    books.append({'condition': condition, 'utc': snap['observed_at_utc'],
                                  **book_features(snap), 'session': folder.name})
            if event == 'minute':
                obs = row['observation']
                m = {'session': folder.name, 'utc': when.isoformat(),
                     'elapsed_minutes': (when - start).total_seconds() / 60,
                     'share_many': obs['share_many'], 'share_single': obs['share_single'],
                     'mid': float(obs['plain_mid']), 'adjusted_mid': float(obs['adjusted_mid']),
                     'P_many_cumulative': row['P_many'], 'P_single_cumulative': row['P_single'],
                     'per_minute_many': obs['per_minute_many'], 'visible_two_sided': obs['visible_two_sided']}
                # Infer competition/own ratio from recorded share; absolute Q varies
                # with re-quotes and midpoint, so do not pretend it is constant.
                m['Q_competitor_over_own'] = (1 / obs['share_many'] - 1) if obs['share_many'] > 0 else None
                minutes.append(m)
                local_minutes.append(m)
            if event in ('accrual_response', 'final_accrual_response'):
                response = row['response']
                matching = [r for r in response.get('rows', []) if r.get('condition_id') == condition]
                accrual.append({'session': folder.name, 'utc': when.isoformat(), 'event': event,
                                'reward_day': response['day'], 'condition_prefix': short(condition),
                                'earnings_cumulative': sum(float(r['earnings']) for r in matching),
                                'venue_percent': response.get('percentages', {}).get(condition),
                                'payment_verified': response.get('payment_verified', False),
                                'matching_rows': len(matching)})
            if event == 'terminal_trades':
                for trade in row['rows']:
                    for maker in trade.get('maker_orders', []):
                        if maker.get('order_id') in own_ids:
                            key = (trade['id'], maker['order_id'])
                            trades[key] = (trade, maker)
        if local_minutes:
            base['share_first'], base['share_last'] = local_minutes[0]['share_many'], local_minutes[-1]['share_many']
            base['share_min'] = min(m['share_many'] for m in local_minutes)
            base['half_pick_minutes'] = next((m['elapsed_minutes'] for m in local_minutes
                                              if m['share_many'] <= quote['share_many'] / 2), None)
            base['half_first_minutes'] = next((m['elapsed_minutes'] - local_minutes[0]['elapsed_minutes']
                                               for m in local_minutes if m['share_many'] <= base['share_first'] / 2), None)
            first5 = local_minutes[:5]
            base['first5_mid_range'] = max(m['mid'] for m in first5) - min(m['mid'] for m in first5)
            for at in (1, 2, 5, 10, 20, 30, 60, 88):
                if len(local_minutes) >= at:
                    checkpoints.append(local_minutes[at - 1] | {'sample': at})
            if not math.isclose(local_minutes[-1]['P_many_cumulative'], pred['P_many'], abs_tol=1e-10):
                raise ValueError('minute prediction mismatch')
        latest = [x for x in accrual if x['session'] == folder.name]
        if latest:
            base['venue_final_cumulative'] = latest[-1]['earnings_cumulative']
            base['venue_first_cumulative'] = latest[0]['earnings_cumulative']
            base['venue_observed_delta'] = latest[-1]['earnings_cumulative'] - latest[0]['earnings_cumulative']
            base['venue_first_utc'] = latest[0]['utc']
            base['delta_over_P_many'] = base['venue_observed_delta'] / pred['P_many'] if pred['P_many'] else None
            base['delta_over_P_single'] = base['venue_observed_delta'] / pred['P_single'] if pred['P_single'] else None
        if len(local_minutes) != pred['minute_samples']:
            raise ValueError('minute-count mismatch')
        if bool(trades) != bool(pred['fill_seen']):
            raise ValueError('fill flag cannot be reproduced from own-order terminal trades')
        sessions.append(base)
        for (trade_id, order_id), (trade, maker) in trades.items():
            fills.append({'session': folder.name, 'market': selected['market_id'], 'condition': condition,
                          'trade_id': trade_id, 'transaction': trade.get('transaction_hash'),
                          'token': maker['token_id'], 'yes_token': selected['token_ids'][0],
                          'utc': trade['matched_at'], 'outcome': maker['outcome'], 'side': maker['side'],
                          'price': float(maker['price']), 'size': float(maker['matched_amount']),
                          'order_prefix': short(order_id), 'taker_order_prefix': short(trade.get('taker_order_id')),
                          'taker_owner_prefix': short(trade.get('owner')), 'trade_prefix': short(trade_id),
                          'fee_rate_bps': trade.get('fee_rate_bps'),
                          'minutes_to_fill': (stamp(trade['matched_at']) - start).total_seconds() / 60})
    public_paths, markouts, clocks, publications = [], [], [], []
    for fill in fills:
        when = stamp(fill['utc'])
        params = {'market': fill['yes_token'], 'startTs': int(when.timestamp()) - 1800,
                  'endTs': int(when.timestamp()) + 7320, 'fidelity': 1}
        history = cache.get('https://clob.polymarket.com/prices-history?' + urllib.parse.urlencode(params))
        points = history.get('payload', {}).get('history', [])
        for point in points:
            public_paths.append({'session': fill['session'], 'utc': datetime.fromtimestamp(point['t'], timezone.utc).isoformat(),
                                 'minutes_from_fill': (point['t'] - when.timestamp()) / 60,
                                 'yes_history_price': point['p'], 'basis': 'sampled_price_not_verified_mid'})
        public_trades = cache.get('https://data-api.polymarket.com/trades?' + urllib.parse.urlencode(
            {'market': fill['condition'], 'limit': 500, 'takerOnly': 'true'}))
        candidates = [t for t in public_trades.get('payload', []) if t.get('transactionHash') == fill['transaction']]
        wallets = set(t['proxyWallet'] for t in candidates if t.get('proxyWallet'))
        fill['taker_wallet_prefix'] = short(next(iter(wallets))) if len(wallets) == 1 else 'unknown'
        fill['public_history_status'] = history.get('error', str(len(points)) + '_samples')
        meta = cache.get('https://clob.polymarket.com/markets/' + fill['condition'])
        winners = [t for t in meta.get('payload', {}).get('tokens', []) if t.get('winner') is True]
        fill['settlement_markout'] = (float(winners[0]['token_id'] == fill['token']) - fill['price']) if len(winners) == 1 else None
        for horizon in (-30, 0, 5, 30, 120):
            target = when.timestamp() + 60 * horizon
            nearby = sorted((p for p in points if abs(p['t'] - target) <= 90), key=lambda p: abs(p['t'] - target))
            books_near = sorted((b for b in books if b['condition'] == fill['condition'] and
                                 abs(stamp(b['utc']).timestamp() - target) <= 90),
                                key=lambda b: abs(stamp(b['utc']).timestamp() - target))
            value = nearby[0]['p'] if nearby else None
            mid = books_near[0]['mid'] if books_near else None
            def pnl(v):
                if v is None:
                    return None
                return (v if fill['outcome'].lower() == 'yes' else 1 - v) - fill['price']
            markouts.append({'session': fill['session'], 'horizon_minutes': horizon, 'yes_mid': mid,
                             'mid_offset_seconds': stamp(books_near[0]['utc']).timestamp() - target if books_near else None,
                             'mid_markout_per_share': pnl(mid), 'yes_history_price': value,
                             'history_offset_seconds': nearby[0]['t'] - target if nearby else None,
                             'sampled_price_markout_per_share': pnl(value),
                             'sampled_price_markout_total': pnl(value) * fill['size'] if value is not None else None})
        station, minute = STATIONS[fill['market']]
        routine = when.replace(minute=minute, second=0, microsecond=0)
        if routine > when:
            routine -= timedelta(hours=1)
        cycles = [when.replace(hour=h, minute=0, second=0, microsecond=0) for h in (1, 7, 13, 19)]
        nbm = max(t for d in (0, 1) for t in (c - timedelta(days=d) for c in cycles) if t <= when)
        gfs = when.replace(hour=(when.hour // 6) * 6, minute=0, second=0, microsecond=0)
        hrrr = when.replace(minute=0, second=0, microsecond=0)
        # Public NOAA Open Data mirror object publication proxy. A file's cycle
        # is not its release time; HEAD avoids downloading GRIB data.
        for model, cycle in [('gfs', gfs), ('hrrr', hrrr), ('hrrr', hrrr - timedelta(hours=1)),
                             ('hrrr', hrrr - timedelta(hours=2))]:
            day, hour = cycle.strftime('%Y%m%d'), cycle.strftime('%H')
            if model == 'gfs':
                url = f'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{day}/{hour}/atmos/gfs.t{hour}z.pgrb2.0p25.f000'
            else:
                url = f'https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{day}/conus/hrrr.t{hour}z.wrfsfcf00.grib2'
            response = cache.get(url, head=True)
            modified = next((v for k,v in response.get('headers', {}).items() if k.lower() == 'last-modified'), None)
            from email.utils import parsedate_to_datetime
            release = parsedate_to_datetime(modified) if modified else None
            publications.append({'session': fill['session'], 'model': model, 'cycle_utc': cycle.isoformat(),
                                 'object': url, 'mirror_last_modified_utc': release.isoformat() if release else None,
                                 'minutes_before_fill': (when-release).total_seconds()/60 if release else None,
                                 'status': response.get('error', 'HEAD_OK'),
                                 'basis': 'representative_f000_mirror_object_not_all_forecast_hours'})
        clocks.append({'session': fill['session'], 'fill_utc': fill['utc'], 'station': station,
                       'prior_modal_METAR_time': routine.isoformat(), 'METAR_lag_minutes': (when-routine).total_seconds()/60,
                       'prior_NBM_cycle': nbm.isoformat(), 'NBM_lag_minutes': (when-nbm).total_seconds()/60,
                       'prior_GFS_cycle': gfs.isoformat(), 'prior_HRRR_cycle': hrrr.isoformat(),
                       'publication_before_fill': 'unmeasured; cycles and report minutes are not availability'})
    thresholds = []
    for label, predicate in [('Q>=10', lambda s: s['Q_pick'] >= 10),
                             ('depth>=75_each', lambda s: min(s['bid_depth'], s['ask_depth']) >= 75),
                             ('day_ahead>=1', lambda s: s['day_ahead'] >= 1),
                             ('Q>=10_and_day_ahead>=1', lambda s: s['Q_pick'] >= 10 and s['day_ahead'] >= 1)]:
        accepted = [s for s in sessions if predicate(s)]
        thresholds.append({'rule': label, 'keep': ', '.join(s['session'] for s in accepted),
                           'exclude': ', '.join(s['session'] for s in sessions if not predicate(s)),
                           'fill_sessions_kept': sum(s['fill_seen'] for s in accepted),
                           'minute_samples_kept': sum(s['minutes'] for s in accepted)})
    safe_fills = [{k:v for k,v in f.items() if k not in ('condition', 'trade_id', 'transaction', 'token', 'yes_token')}
                  for f in fills]
    daily = {}
    for a in accrual:
        key = (a['reward_day'], a['condition_prefix'])
        if key not in daily or stamp(a['utc']) > stamp(daily[key]['utc']):
            daily[key] = a
    tables = {'sessions': sessions, 'minutes': minutes, 'accrual': accrual, 'fills': safe_fills,
              'share_checkpoints': checkpoints, 'price_path': public_paths, 'markouts': markouts,
              'information_clock': clocks, 'publications': publications, 'latest_condition_accrual': list(daily.values()),
              'thresholds': thresholds, 'input_manifest': manifest}
    for name, rows in tables.items():
        write_table(out, name, rows)
    # Recheck every source: report never silently accepts a moving copy.
    for item in manifest:
        if sha(root / item['path']) != item['sha256']:
            raise ValueError('source changed during analysis')
    (out / 'tables.json').write_text(json.dumps(tables, indent=2, sort_keys=True), encoding='utf-8')
    display = {
        'sessions': ['session','market','day_ahead','minutes','posts','stop','P_many','P_single','venue_final_cumulative'],
        'selection_features': ['session','Q_pick','bid_depth','ask_depth','spread','pick_local','first5_mid_range'],
        'share_decay': ['session','share_pick','share_first','share_last','half_pick_minutes','half_first_minutes'],
        'share_checkpoints': ['session','sample','elapsed_minutes','share_many','Q_competitor_over_own','mid'],
        'accrual_comparison': ['session','venue_observed_delta','delta_over_P_many','delta_over_P_single'],
        'fills': ['session','utc','outcome','price','size','minutes_to_fill','taker_wallet_prefix','settlement_markout'],
        'markouts': ['session','horizon_minutes','yes_mid','yes_history_price','history_offset_seconds','sampled_price_markout_per_share'],
        'information_clock': ['session','station','METAR_lag_minutes','prior_NBM_cycle','NBM_lag_minutes'],
        'publications': ['session','model','cycle_utc','mirror_last_modified_utc','minutes_before_fill'],
        'thresholds': ['rule','keep','exclude','fill_sessions_kept','minute_samples_kept'],
    }
    sections = []
    def fmt(v):
        return 'NA' if v is None else f'{v:.4f}' if isinstance(v, float) else str(v).replace('|', '/')
    for name, fields in display.items():
        rows = tables.get(name, sessions)
        sections += ['## ' + name, '', '| ' + ' | '.join(fields) + ' |',
                     '| ' + ' | '.join('---' for _ in fields) + ' |']
        sections += ['| ' + ' | '.join(fmt(r.get(k)) for k in fields) + ' |' for r in rows]
        sections += ['']
    (out / 'tables.md').write_text('\n'.join(sections), encoding='utf-8')
    print(json.dumps({'sessions': len(sessions), 'fills': len(fills), 'minute_samples': len(minutes),
                      'output': str(out), 'public_cache_files': len(list(cache.root.glob('*.json')))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch-public', action='store_true')
    args = parser.parse_args()
    analyze(args.copy_root, args.output, args.fetch_public)
