"""Offline descriptive capacity summaries; every dollar is modelled, never paid."""
from collections import defaultdict
import base64
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

from weather.market.mm_stage2_public import canonical_bytes, digest, utc
from weather.market.mm_stage2_selection import selection_rank
from weather.market.reward_capacity import ET, ROOT, SIZES, model_band, CapturedResponse
from weather.market.re1_rehearsal import Re1PublicBooks


def summarize(samples):
    ordered = sorted(samples, key=lambda row: row['started_at_utc'])
    complete = [r for r in ordered if r['complete']]
    starts = [utc(r['started_at_utc']) for r in complete]
    if len(set(starts)) != len(starts):
        raise ValueError('duplicate_sample_start')
    span = (max(starts) - min(starts)).total_seconds() / 3600 if starts else 0
    hourly, bands, top, support = defaultdict(list), defaultdict(list), defaultdict(list), set()
    # Each snapshot is at most one declared cadence cell. Missing intervals,
    # incomplete universes and session pauses receive no interpolation.
    covered_hours = 0.0
    for index, sample in enumerate(ordered):
        if not sample['complete']:
            continue
        start, finish = utc(sample['started_at_utc']), utc(sample['finished_at_utc'])
        next_start = utc(ordered[index + 1]['started_at_utc']) if index + 1 < len(ordered) else finish
        hours = max(0, min(sample.get('interval_seconds', 900), (next_start - start).total_seconds())) / 3600
        covered_hours += hours
        hour = start.astimezone(ET).hour
        for row in sample['rows']:
            support.add((row['market_id'], row['target_date']))
            bands[(hour, row['size'], row['condition_id'])].append(row)
        for size in SIZES:
            rows = [r for r in sample['rows'] if r['size'] == size and r['eligible']]
            rows.sort(key=selection_rank)
            hourly[(hour, size)].append({'qualifying_bands': len(rows),
                'modelled_dollars_6h': sum(r['predicted_360_minutes'] for r in rows),
                'capital_pusd': sum(r['capital_pusd'] for r in rows),
                'worst_case_one_fill_loss_pusd': sum(r['worst_case_one_fill_loss_pusd'] for r in rows)})
            for count in (1, 3, 10):
                chosen = rows[:count]
                top[(size, count)].append({'hours': hours, 'actual_bands': len(chosen),
                    'modelled_dollars_24h_equivalent': sum(r['predicted_360_minutes'] * 4 for r in chosen),
                    'modelled_dollars_covered': sum(r['predicted_360_minutes'] / 6 * hours for r in chosen),
                    'capital_pusd': sum(r['capital_pusd'] for r in chosen),
                    'worst_case_one_fill_loss_pusd': sum(r['worst_case_one_fill_loss_pusd'] for r in chosen),
                    'diluted_1_modelled_dollars_24h_equivalent': sum(
                        r['predicted_360_minutes'] * 4 * r['share_with_one_equal_competitor'] / r['quote']['share_many'] for r in chosen),
                    'diluted_3_modelled_dollars_24h_equivalent': sum(
                        r['predicted_360_minutes'] * 4 * r['share_with_three_equal_competitors'] / r['quote']['share_many'] for r in chosen)})
    pattern = []
    for hour in range(24):
        for size in SIZES:
            rows = hourly[(hour, size)]
            pattern.append({'hour_ET': hour, 'size': size, 'samples': len(rows),
                **{key: mean(r[key] for r in rows) if rows else None for key in (
                    'qualifying_bands', 'modelled_dollars_6h', 'capital_pusd', 'worst_case_one_fill_loss_pusd')}})
    band_hour = []
    for (hour, size, condition), rows in sorted(bands.items()):
        eligible = [r for r in rows if r['eligible']]
        band_hour.append({'hour_ET': hour, 'size': size, 'condition_id': condition,
            'market_id': rows[0]['market_id'], 'target_date': rows[0]['target_date'],
            'samples': len(rows), 'qualifying_samples': len(eligible),
            'mean_modelled_share_when_qualified': mean(r['quote']['share_many'] for r in eligible) if eligible else None,
            'mean_modelled_dollars_6h_when_qualified': mean(r['predicted_360_minutes'] for r in eligible) if eligible else None,
            'mean_capital_when_qualified': mean(r['capital_pusd'] for r in eligible) if eligible else None,
            'max_worst_case_one_fill_loss': max((r['worst_case_one_fill_loss_pusd'] for r in eligible), default=None)})
    portfolios = []
    for (size, count), rows in sorted(top.items()):
        total = sum(r['hours'] for r in rows)
        portfolios.append({'size': size, 'best_n': count, 'samples': len(rows),
            'covered_hours': total,
            **{key: sum(r[key] * r['hours'] for r in rows) / total if total else None for key in (
                'actual_bands', 'modelled_dollars_24h_equivalent', 'capital_pusd', 'worst_case_one_fill_loss_pusd',
                'diluted_1_modelled_dollars_24h_equivalent', 'diluted_3_modelled_dollars_24h_equivalent')},
            'max_capital_pusd': max(r['capital_pusd'] for r in rows),
            'max_worst_case_one_fill_loss_pusd': max(r['worst_case_one_fill_loss_pusd'] for r in rows),
            'modelled_dollars_covered': sum(r['modelled_dollars_covered'] for r in rows)})
    return {'verdict': 'MODELLED_DESCRIPTIVE_CURVE' if span >= 24 and covered_hours >= 24 else 'INCOMPLETE_24H_COLLECTION',
        'modelled_never_paid': True, 'samples': len(ordered), 'complete_samples': len(complete),
        'start_utc': min(starts).isoformat() if starts else None, 'end_utc': max(starts).isoformat() if starts else None,
        'span_hours': span, 'covered_hours': covered_hours, 'market_days': len(support),
        'date_clusters': len({d for _, d in support}), 'market_clusters': len({m for m, _ in support}),
        'hour_of_day_ET': pattern, 'band_hour': band_hour, 'best_bands': portfolios,
        'sensitivity_formula': 'Q(s)/(C + (n+1)*Q(s)); equivalently h/(1+n*h), h=Q(s)/(C+Q(s))',
        'limitations': ['No paid rewards, fill probabilities, adverse selection, fees or operational costs are measured.',
            'Daily equivalents assume sampled rates persist and continuous re-selection/recycling without inventory.',
            'Six-hour predictions hold the observed reward rate and displayed competition fixed.',
            'One-fill loss is s*max(YES_buy, NO_buy), excluding fees; gross cash reserve is s*(YES_buy+NO_buy).',
            'Across bands the sum of individual loss maxima is conservative; no cross-band settlement netting.',
            'No interval or hypothesis test: descriptive public snapshots; no independent daily support for inference.',
            'Unconfigured weather cities use ET date boundaries; RE-1 eligibility is separately preserved.',
            'Hours without a complete sample are missing, never zero or silently interpolated.']}


def write_summary(root=ROOT):
    root = Path(root)
    samples = []
    for path in sorted(root.glob('*/samples.jsonl')):
        payloads, rewards = set(), set()
        with (path.parent / 'responses.jsonl').open(encoding='utf-8') as handle:
            for line in handle:
                record = json.loads(line)
                body = base64.b64decode(record['response_body_base64'], validate=True)
                if hashlib.sha256(body).hexdigest() != record['response_sha256']:
                    raise ValueError('raw_response_hash_mismatch')
                if record['http_status'] != 200 or record.get('truncated'):
                    continue
                payload = json.loads(body)
                payloads.add(digest({'url': record['url'], 'payload': payload}))
                if '/rewards/markets/0x' in record['url']:
                    for row in payload.get('data', []):
                        rewards.add(digest(row))
        rebuilt = defaultdict(list)
        with (path.parent / 'snapshots.jsonl').open(encoding='utf-8') as handle:
            for line in handle:
                band = json.loads(line)
                snapshot = band['snapshot']
                if digest(snapshot['reward_record']) not in rewards:
                    raise ValueError('reward_record_not_bound_to_response')
                if any(digest(row) not in payloads for row in snapshot['raw_public_responses']):
                    raise ValueError('book_not_bound_to_response')
                captured = {row['url']: row['payload'] for row in snapshot['raw_public_responses']}
                def replay(request, **_kwargs):
                    return CapturedResponse(canonical_bytes(captured[request.full_url]), 200,
                                            {'Content-Type': 'application/json'}, request.full_url)
                reader = Re1PublicBooks(clock=lambda: utc(snapshot['observed_at_utc']), opener=replay)
                restored = reader.snapshot(band['condition_id'], band['token_ids'], reward=snapshot['reward_record'])
                if canonical_bytes(restored) != canonical_bytes(snapshot):
                    raise ValueError('snapshot_does_not_reproduce_public_responses')
                rebuilt[band['sample_started_at_utc']].extend(model_band(band))
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                sample = json.loads(line)
                if canonical_bytes(rebuilt[sample['started_at_utc']]) != canonical_bytes(sample['rows']):
                    raise ValueError('derived_sample_does_not_reproduce')
                samples.append(sample)
    result = summarize(samples)
    (root / 'capacity_summary.json').write_bytes(canonical_bytes(result))
    for key in ('hour_of_day_ET', 'band_hour', 'best_bands'):
        rows = result[key]
        if rows:
            with (root / f'{key}.csv').open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    return result


if __name__ == '__main__':
    result = write_summary()
    print(json.dumps({k: result[k] for k in ('verdict', 'complete_samples', 'span_hours', 'covered_hours')}))
