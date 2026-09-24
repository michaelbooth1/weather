"""95a offline shadow rows and descriptive public-print withdraw counterfactual.

No network calls. Prepare copies only named public caches into owned output;
analyze validates and rebuilds them. Nothing is served, submitted or scheduled.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from tools import cross_band_fill_clustering_20260924 as public
from tools import observation_clock_20260923 as history
from weather.market.observation_clock import RemainingRiseEstimator, day_grid, hourly_rule_minute, STATION_ROUTINE_MINUTES
from weather.market.timing_shadow import ShadowBand, timing_row
from weather.paths import data_path
from weather.units import round_half_up

UTC = timezone.utc
FIT_BEFORE = date(2026, 8, 13)  # Before the earliest T+2 exposure in the 94a panel.
ROOT = data_path('timing_shadow_95a')
PHASES = (0, 15, 30, 45)  # Fixed before observing policy results.
POLICIES = ('metar_2', 'metar_5', 'metar_10', 'nbm_5', 'nbm_15',
            'gfs_5', 'gfs_15', 'hrrr_5', 'hrrr_15', 'models_5',
            't3_95', 't3_99', 't3_95_lag0', 't3_95_lag15', 'combined_5_95')
METRICS = ('band_minutes', 'pulled_minutes', 'notional', 'pulled_notional',
           'eligible_moves', 'large_moves', 'pulled_large_moves', 't3_known_minutes',
           'trade_rows', 'pulled_trade_rows') + tuple(
               f'baseline_{p}_{m}' for p in PHASES for m in ('minutes', 'notional', 'large_moves'))


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(root, trade_cache, observation_cache):
    """Create-only copies: no mirror, tape, credential or old report discovery."""
    root.mkdir(parents=True, exist_ok=True)
    if (root/'public').exists() or (root/'observations').exists():
        raise ValueError('cache destination already exists; reuse it without prepare')
    for source in (trade_cache, observation_cache):
        if source.is_symlink() or 'mirror' in str(source).lower():
            raise ValueError('only the named public research caches may be copied')
    for name in ('http', 'events'):
        shutil.copytree(trade_cache/name, root/'public'/name)
    for name in ('universe.json', 'coverage.json'):
        shutil.copyfile(trade_cache/name, root/'public'/name)
    shutil.copytree(observation_cache/'cache', root/'observations'/'cache')
    public.write_json(root/'input_origins.json', {'public_cache': str(trade_cache),
                      'observation_cache': str(observation_cache), 'kind': 'public_research_cache_copy'})
    print('Created owned public-cache copies', flush=True)


def future_moves(times, prices, *, width=300, threshold=.03):
    """Strictly future condition-second print excursion, within five minutes.

    One anchor per condition-second, no same-second ordering inference. An
    anchor is eligible only with a future print; overlapping anchors stay so.
    """
    times, prices = np.asarray(times), np.asarray(prices)
    if len(times) != len(prices) or np.any(np.diff(times) <= 0):
        raise ValueError('move inputs require unique increasing seconds')
    if not np.all(np.isfinite(prices)) or np.any((prices < 0) | (prices > 1)):
        raise ValueError('invalid binary prices')
    high, low = deque(), deque()
    eligible, large = np.zeros(len(times), bool), np.zeros(len(times), bool)
    for i in range(len(times)-1, -1, -1):
        while high and times[high[0]] > times[i] + width:
            high.popleft()
        while low and times[low[0]] > times[i] + width:
            low.popleft()
        if high:
            eligible[i] = True
            large[i] = max(prices[high[0]]-prices[i], prices[i]-prices[low[0]]) >= threshold-1e-12
        while high and prices[high[-1]] <= prices[i]:
            high.pop()
        while low and prices[low[-1]] >= prices[i]:
            low.pop()
        high.append(i)
        low.append(i)
    return eligible, large


def clock_baseline(minutes, mask, phase):
    """Match pulled minutes exactly in each band/date/hour using fixed phase.

    Rank eligible clock minutes from phase modulo 60, never use print outcomes.
    Supports partial hours when an event is newly created.
    """
    minutes = np.asarray(minutes)
    groups = minutes//60 - minutes[0]//60
    counts = np.bincount(groups, weights=np.asarray(mask, int)).astype(int)
    order = np.lexsort(((minutes % 60 - phase) % 60, groups))
    sizes = np.bincount(groups)
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    rank = np.empty(len(minutes), int)
    rank[order] = np.arange(len(minutes)) - starts[groups[order]]
    return rank < counts[groups]


def load_weather(root):
    previous = history.ROOT
    try:
        history.ROOT = root/'observations'
        typed, _minute_days, provenance, conflicts, reuse, ambiguous = history.read_observations()
    finally:
        history.ROOT = previous
    result, training = {}, []
    for spec in history.SPECS:
        daily = defaultdict(list)
        for row in typed[spec.id].values():
            daily[row.valid.astimezone(spec.tz).date()].append(row)
        days = []
        for day in sorted(daily):
            if day >= FIT_BEFORE:
                continue
            summary, grid = day_grid(daily[day], spec.icao, spec.timezone, day, hourly=True)
            if any((kind, spec.id, day) in ambiguous for kind in ('routine', 'special')):
                summary['complete_hours'] = False
            days.append((summary, grid))
        estimator = RemainingRiseEstimator.fit(days, before=FIT_BEFORE)
        fit_n = sum(len(values) for values in estimator.rises.values())
        fit_zero = sum(sum(value == 0 for value in values) for values in estimator.rises.values())
        constant = fit_zero / fit_n if fit_n else None
        train_loss = sum(len(values)*(sum(v == 0 for v in values)/len(values))
                         *(1-sum(v == 0 for v in values)/len(values))
                         for values in estimator.rises.values()) / fit_n if fit_n else None
        if train_loss is not None and train_loss > constant*(1-constant)+1e-12:
            raise ValueError('training positive control failed')
        clock_counts = Counter(r.valid.minute for r in typed[spec.id].values()
                               if r.kind == 'routine' and r.valid.astimezone(spec.tz).date() < FIT_BEFORE)
        modal = min(clock_counts, key=lambda m: (-clock_counts[m], m))
        result[spec.id] = (spec, estimator, daily, ambiguous, modal)
        training.append({'city': spec.id, 'station': spec.icao, 'fit_before': FIT_BEFORE.isoformat(),
                         'complete_training_dates': sum(s['complete_hours'] for s, _ in days),
                         'modal_minute': modal, 'matches_89b_modal': modal in STATION_ROUTINE_MINUTES[spec.icao],
                         'training_decidedness_brier': train_loss,
                         'training_constant_brier': None if constant is None else constant*(1-constant),
                         'minimum_quarter_n': min(map(len, estimator.rises.values()), default=0)})
    public.write_json(root/'training.json', {'stations': training, 'conflicts': conflicts,
                      'reuse': reuse, 'source_response_count': len(provenance)})
    return result


def observed_grid(weather, target, minutes, lag):
    spec, estimator, daily, ambiguous, _modal = weather
    midnight = datetime.combine(target, datetime.min.time(), spec.tz)
    t0 = int(midnight.timestamp()) // 60
    cutoff = minutes - lag
    valid_day = (cutoff >= t0) & (cutoff < t0+1440) & (minutes < t0+1440)
    rows = sorted((r for r in daily.get(target, []) if r.temperature is not None
                   and hourly_rule_minute(spec.icao, r.valid.minute)), key=lambda r: r.valid)
    running = np.full(len(minutes), np.nan)
    if not rows or any((kind, spec.id, target) in ambiguous for kind in ('routine', 'special')):
        return running, (cutoff-t0) % 1440
    stamps = np.array([r.valid.timestamp() for r in rows])
    highs = np.maximum.accumulate([round_half_up(r.temperature) for r in rows])
    index = np.searchsorted(stamps, cutoff*60, side='right')-1
    okay = valid_day & (index >= 0)
    okay &= (cutoff*60-stamps[np.maximum(index, 0)]) <= 90*60
    running[okay] = highs[index[okay]]
    return running, (cutoff-t0) % 1440


def vector_risk(band, estimator, running, local_minutes):
    """Vectorized equivalent of timing_shadow.band_risk, tested against it."""
    risk = np.full(len(running), np.nan)
    p_high = np.full(len(running), np.nan)
    valid = np.isfinite(running)
    locked = valid & ((running > band.upper) if band.upper is not None else (running >= band.lower))
    risk[locked] = 1.
    inside = valid.copy()
    if band.lower is not None:
        inside &= running >= band.lower
    if band.upper is not None:
        inside &= running <= band.upper
    for q in np.unique(local_minutes//15*15):
        values = estimator.rises.get(int(q), ())
        if len(values) < estimator.minimum_days:
            continue
        selected = valid & (local_minutes//15*15 == q)
        p_high[selected] = np.searchsorted(values, 0, side='right') / len(values)
        active = selected & ~locked
        if not np.any(active):
            continue
        boundary = np.where(inside[active], band.upper if band.upper is not None else 0,
                            band.lower-1 if band.lower is not None else 0)
        risk[active] = np.searchsorted(values, boundary-running[active], side='right') / len(values)
    return risk, p_high


def lag_to_objects(minutes, object_seconds):
    objects = np.sort(np.asarray(object_seconds, float))
    if not len(objects):
        return np.full(len(minutes), np.inf), np.full(len(minutes), np.inf)
    times = minutes*60
    index = np.searchsorted(objects, times, side='right')
    since = np.where(index > 0, (times-objects[np.maximum(index-1, 0)])/60, np.inf)
    until = np.where(index < len(objects), (objects[np.minimum(index, len(objects)-1)]-times)/60, np.inf)
    return since, until


def policy_masks(minutes, modal, publications, risks):
    since, until = (minutes % 60-modal) % 60, (modal-minutes % 60) % 60
    result = {f'metar_{w}': (since < w) | (until <= w) for w in (2, 5, 10)}
    # Half-open [-W,+W), minute zero belongs once. At exactly -W pull;
    # at +W resume. NBM is a cycle clock, not an observed publication.
    nbm_phase = (minutes % (6*60)-60) % (6*60)
    result.update({f'nbm_{w}': (nbm_phase < w) | ((360-nbm_phase) % 360 <= w) for w in (5, 15)})
    for model in ('gfs', 'hrrr'):
        since, until = lag_to_objects(minutes, publications[model])
        result.update({f'{model}_{w}': (since < w) | (until <= w) for w in (5, 15)})
    result['models_5'] = result['nbm_5'] | result['gfs_5'] | result['hrrr_5']
    result['t3_95'], result['t3_99'] = risks[5] >= .95, risks[5] >= .99
    result['t3_95_lag0'], result['t3_95_lag15'] = risks[0] >= .95, risks[15] >= .95
    result['combined_5_95'] = result['metar_5'] | result['models_5'] | result['t3_95']
    return result


def summarize(frame, keys):
    result = frame.groupby(keys, dropna=False)[list(METRICS)].sum().reset_index()
    for field, numerator, denominator in (
        ('pulled_fraction', 'pulled_minutes', 'band_minutes'),
        ('notional_fraction', 'pulled_notional', 'notional'),
        ('large_move_fraction', 'pulled_large_moves', 'large_moves'),
        ('t3_known_fraction', 't3_known_minutes', 'band_minutes')):
        result[field] = result[numerator]/result[denominator].replace(0, np.nan)
    for p in PHASES:
        result[f'baseline_{p}_large_move_fraction'] = result[f'baseline_{p}_large_moves']/result.large_moves.replace(0, np.nan)
    result['best_clock_large_move_fraction'] = result[[f'baseline_{p}_large_move_fraction' for p in PHASES]].max(axis=1)
    result['lift_vs_best_clock'] = result.large_move_fraction/result.best_clock_large_move_fraction.replace(0, np.nan)
    return result


def analyze(root, *, shadow_date):
    frame, bands, coverage, rejected = public.load_trades(root/'public')
    if len(coverage) != 480 or any(not c['pagination_exhausted'] or c['error'] for c in coverage):
        raise ValueError('95a requires all 480 public event-days')
    print(f'Validated {len(frame)} trades across {len(bands)} bands', flush=True)
    objects = public.collect_publications(root/'public', online=False)
    pubs = {model: [datetime.fromisoformat(p['published_utc'].replace('Z', '+00:00'))
                   for p in objects if p['model'] == model] for model in ('gfs', 'hrrr')}
    publication_seconds = {m: [t.timestamp() for t in ts] for m, ts in pubs.items()}
    weather = load_weather(root)
    by_condition = {key: group for key, group in frame.groupby('condition', sort=False)}
    cells = defaultdict(lambda: np.zeros(len(METRICS), float))
    shadow_path = root/'shadow_rows.csv.gz'
    shadow_rows, shadow_columns = 0, True
    with shadow_path.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed, io.TextIOWrapper(compressed, encoding='utf-8', newline='') as shadow:
        for event_index, (_event, event_bands) in enumerate(bands.groupby('event', sort=True)):
            meta = event_bands.iloc[0]
            target = date.fromisoformat(meta.target_date)
            spec, estimator, daily, ambiguous, modal = weather[meta.city]
            t0 = int(datetime.combine(target, datetime.min.time(), spec.tz).timestamp())//60
            event_minutes = np.arange(int(event_bands.start.min())//60, int(meta.end)//60)
            ahead = -((event_minutes-t0)//1440)
            local_minute = (event_minutes-t0) % 1440
            observed = {lag: observed_grid(weather[meta.city], target, event_minutes, lag) for lag in (0, 5, 15)}
            for row in event_bands.itertuples():
                keep = event_minutes >= int(row.start)//60
                minutes = event_minutes[keep]
                group_id = (ahead[keep]*4 + local_minute[keep]//360).astype(int)
                band = ShadowBand.from_label(row.condition, target, row.label, spec.unit)
                risks = {lag: vector_risk(band, estimator, running[keep], clock[keep])[0]
                         for lag, (running, clock) in observed.items()}
                masks = policy_masks(minutes, modal, publication_seconds, risks)
                trade = by_condition.get(row.condition)
                notional, trade_counts, move_counts, eligible_counts = (np.zeros(len(minutes)) for _ in range(4))
                if trade is not None:
                    idx = trade.minute.to_numpy()-minutes[0]
                    notional = np.bincount(idx, weights=(trade.price*trade['size']).to_numpy(), minlength=len(minutes))
                    trade_counts = np.bincount(idx, minlength=len(minutes))
                    prices = np.where(trade.outcome == 'Yes', trade.price, 1-trade.price)
                    prints = pd.DataFrame({'t': trade.t, 'weighted': prices*trade['size'], 'size': trade['size']}).groupby('t').sum()
                    seconds = prints.index.to_numpy()
                    eligible, large = future_moves(seconds, (prints.weighted/prints['size']).to_numpy())
                    # Complete forward window inside the retained band interval.
                    eligible &= seconds+300 < int(row.end)
                    large &= eligible
                    ix = seconds//60-minutes[0]
                    eligible_counts = np.bincount(ix, weights=eligible, minlength=len(minutes))
                    move_counts = np.bincount(ix, weights=large, minlength=len(minutes))
                for policy in POLICIES:
                    mask = masks[policy]
                    arrays = [np.ones(len(minutes)), mask, notional, notional*mask,
                              eligible_counts, move_counts, move_counts*mask, np.isfinite(risks[5]),
                              trade_counts, trade_counts*mask]
                    for phase in PHASES:
                        baseline = clock_baseline(minutes, mask, phase)
                        assert baseline.sum() == mask.sum()
                        arrays.extend([baseline, notional*baseline, move_counts*baseline])
                    grouped = np.array([np.bincount(group_id, weights=a, minlength=12) for a in arrays]).T
                    for group in np.flatnonzero(grouped[:, 0]):
                        cells[(policy, row.city, row.target_date, int(group//4), int(group%4)*6)] += grouped[group]
                if target == shadow_date:
                    selected = ahead[keep] == 0
                    running = observed[5][0][keep]
                    clock = observed[5][1][keep]
                    output = []
                    for i in np.flatnonzero(selected):
                        now = datetime.fromtimestamp(int(minutes[i])*60, UTC)
                        rd = None if not np.isfinite(running[i]) else int(running[i])
                        value = timing_row(spec.icao, now, band, estimator, station_timezone=spec.timezone,
                                           running_degree=rd, observation_cutoff=now-timedelta(minutes=5),
                                           publications=pubs, routine_minutes=(modal,))
                        model_clocks = value.pop('model_clocks')
                        for model, timing in model_clocks.items():
                            value.update({model+'_'+k: v for k, v in timing.items()})
                        value['label'] = row.label
                        value['combined_5_95_withdrawn'] = bool(masks['combined_5_95'][i])
                        expected = risks[5][i]
                        assert (value['p_band_decided'] is None and np.isnan(expected)) or value['p_band_decided'] == expected
                        output.append(value)
                    pd.DataFrame(output).to_csv(shadow, index=False, header=shadow_columns)
                    shadow_columns = False
                    shadow_rows += len(output)
            if event_index % 20 == 0:
                print(f'Evaluated {event_index+1}/480 event-days', flush=True)
    columns = ['policy', 'city', 'target_date', 'ahead', 'hour_start'] + list(METRICS)
    cell_frame = pd.DataFrame([list(key)+list(values) for key, values in cells.items()], columns=columns)
    cell_frame.to_csv(root/'date_market_cells.csv', index=False)
    summary = summarize(cell_frame, ['policy'])
    summary.to_csv(root/'policy_summary.csv', index=False)
    summarize(cell_frame, ['policy', 'city', 'ahead', 'hour_start']).to_csv(root/'policy_strata.csv', index=False)
    eligible = summary[(summary.pulled_fraction > 0) & (summary.pulled_fraction < .5)]
    best = eligible.sort_values(['lift_vs_best_clock', 'large_move_fraction'], ascending=False).iloc[0]
    inventory = []
    for folder in (root/'public'/'http', root/'observations'/'cache'):
        for path in sorted(folder.glob('*.body')):
            inventory.append({'path': path.relative_to(root).as_posix(), 'sha256': file_hash(path), 'bytes': path.stat().st_size})
    public.write_json(root/'cache_inventory.json', inventory)
    public.write_json(root/'manifest.json', {
        'fit_before': FIT_BEFORE.isoformat(), 'panel_start': str(public.START), 'panel_end': str(public.END),
        'target_date_clusters': int(bands.target_date.nunique()), 'market_clusters': int(bands.city.nunique()),
        'event_days': len(coverage), 'bands': len(bands), 'trade_rows': len(frame), 'rejected_94a': rejected,
        'object_proxies': len(objects), 'shadow_date': str(shadow_date), 'shadow_rows': shadow_rows,
        'best_descriptive_policy_under_half_time': best['policy'],
        'best_lift_vs_all_fixed_clocks': float(best.lift_vs_best_clock),
        'artifacts': {p.name: file_hash(p) for p in [root/'policy_summary.csv', root/'policy_strata.csv',
                     root/'date_market_cells.csv', shadow_path, root/'training.json', root/'cache_inventory.json']},
        'code': {str(p.relative_to(Path(__file__).resolve().parents[1])): file_hash(p) for p in
                 [Path(__file__), Path(__file__).resolve().parents[1]/'src/weather/market/timing_shadow.py']},
        'identification': 'public print proxies; retrospective valid-time observations and model LastModified; no own fills',
    })
    print(summary[['policy', 'pulled_fraction', 'notional_fraction', 'large_move_fraction', 'lift_vs_best_clock']].to_string(index=False), flush=True)
    print(f'Shadow rows: {shadow_rows}; best descriptive policy: {best["policy"]}', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'analyze'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--trade-cache', type=Path)
    parser.add_argument('--observation-cache', type=Path)
    parser.add_argument('--shadow-date', type=date.fromisoformat, default=date(2026, 9, 22))
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        if args.trade_cache is None or args.observation_cache is None:
            parser.error('prepare requires both named public-cache paths')
        prepare(args.root, args.trade_cache, args.observation_cache)
    else:
        if not public.START <= args.shadow_date <= history.END:
            parser.error('shadow date must be in the public panel and 89b history')
        analyze(args.root, shadow_date=args.shadow_date)


if __name__ == '__main__':
    main()
