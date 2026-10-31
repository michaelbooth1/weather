"""Bounded 83a period/capture diagnostics; no fitting or forecast scoring."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import requests

from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax_v1, station_nbp_block


def p5(artifact: Path, output: Path) -> None:
    """Compare inputs, inspect trusted pinned selectors; never call predict/fit."""
    from weather.market.market_registry import all_specs
    from weather.model.toronto_model import TorontoHighTempModel
    from weather.sources.nbm_probabilistic_tmax import (
        NBM_PROB_TMAX_FEATURE_COLUMNS, parse_nbp_station_tmax,
    )
    output.mkdir(parents=True, exist_ok=False)
    data = artifact.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != '3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c':
        raise ValueError('artifact does not match the handoff LFS oid')
    payload = pickle.loads(data)
    selectors = []
    def visit(value, path=''):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'feature_names':
                    names = [str(n) for n in item if str(n).startswith('nbm_prob_tmax_')]
                    if names:
                        selectors.append({'path': path + '/feature_names', 'fields': names})
                elif isinstance(item, (dict, list, tuple)):
                    visit(item, path + '/' + str(key))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, (dict, list, tuple)):
                    visit(item, path + '/' + str(i))
    visit(payload)
    (output / 'selectors.json').write_text(json.dumps({'sha256': digest, 'selectors': selectors}, indent=2) + '\n')
    specs = {spec.icao: spec for spec in all_specs() if ':US' in spec.wu_history_id}
    fixtures = Path(__file__).resolve().parents[2] / 'tests/fixtures/nbm_target_fix'
    rows = []
    for path in sorted(fixtures.glob('20260917T*.txt')):
        station = path.stem.split('-')[1]
        if station not in specs or path.stem[9:11] not in ('01','07','13','19'):
            continue
        text = path.read_text()
        model = TorontoHighTempModel(target_date='2026-09-17', market_id=specs[station].id)
        old = parse_nbp_station_tmax_v1(text, station, '2026-09-17')
        new = parse_nbp_station_tmax(text, station, '2026-09-17')
        for floor in (None, 80.):
            outputs = []
            for parsed in (old, new):
                outputs.append(model.us_guidance_features(nbm_probabilistic_tmax=parsed,
                    forecast_high=85., observed_floor_native=floor))
            for field in NBM_PROB_TMAX_FEATURE_COLUMNS[:15]:
                row = {'cycle': path.stem.split('-')[0], 'station':station,
                       'target_date':'2026-09-17', 'synthetic_floor_f':floor,
                       'synthetic_forecast_high_f':85., 'feature':field}
                for version, parsed, values in zip((1,2),(old,new),outputs):
                    value = values[field]
                    row[f'v{version}_value'] = value
                    row[f'v{version}_state'] = ('unavailable' if not parsed['available'] else
                        'present' if value is not None else 'dropped')
                rows.append(row)
    with (output / 'inputs.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'artifact_sha256':digest,'selector_count':len(selectors), 'input_comparisons':len(rows)}))


def contracts(output: Path) -> None:
    """Exercise unchanged persistence/fan-out owners and retain missing contracts."""
    from unittest.mock import patch
    from weather.collection.snapshot_store import SnapshotStore
    from weather.collection.forecast_payload_fetch_fanout import CrossProcessMarketInvariantFetchFanout
    from weather.model.toronto_model import TorontoHighTempModel
    output.mkdir(parents=True, exist_ok=False)
    fixtures = Path(__file__).resolve().parents[2] / 'tests/fixtures/nbm_target_fix'
    now = datetime(2026,9,17,20,tzinfo=timezone.utc)
    cycles = [now.replace(hour=h) for h in (19,13,12,7,1,0)]
    downloads = []
    manifests = []
    shared = output / 'cas'
    for pass_number in (1,2):
        fanout = CrossProcessMarketInvariantFetchFanout(shared)
        for market, station in (('nyc','KLGA'), ('los-angeles','KLAX')):
            for day in ('2026-09-17','2026-09-18'):
                model = TorontoHighTempModel(target_date=day, market_id=market)
                model.market_invariant_fetch_fanout = fanout
                model.market_invariant_fetch_scope = f'83a-pass-{pass_number}'
                def fetch(url):
                    downloads.append({'pass': pass_number, 'url': url})
                    hour = int(url[-3:-1])
                    return '\n'.join((fixtures / f'20260917T{hour:02d}Z-{s}.txt').read_text() for s in ('KLGA','KLAX'))
                model.get_text = fetch
                with patch('weather.model.model_sources.nbp_cycle_candidates', return_value=cycles):
                    payload = model.fetch_nbm_probabilistic_tmax()
                store = SnapshotStore(root=output / f'{pass_number}-{market}-{day}', event_slug=f'{market}-{day}',
                    shared_forecast_payload_cas_root=shared)
                store.root.mkdir(parents=True)
                row = store.write_forecast_payloads({'nbm_probabilistic_tmax': {'ok':True,'data':payload,
                    'fetched_at':payload['fetched_at']}}, 'fixture', datetime.now(timezone.utc), 'fixture',
                    config_identity={'market_id':market,'target_date':day})[0]
                required = ['period_kind','group_index','token_index','cycle_age_hours','raw_values','value_rejection_reasons']
                manifests.append({'pass':pass_number,'market':market,'target_date':day,
                    'parser_version':row.get('parser_version'), 'payload_hash':row['payload_hash'],
                    'missing_manifest_fields':[key for key in required if key not in row]})
    result = {'network_downloads': downloads, 'manifest_probes':manifests,
              'unique_blob_count':len(list(shared.glob('sha256/*/*.blob'))),
              'status':'BLOCK', 'reason':'manifest_fields_missing_and_cross_pass_downloads_repeat'}
    (output / 'contracts.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def p0(cache: Path, output: Path) -> None:
    """Fetch exactly four previously unsampled cycles serially, once per cache."""
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for hour in (0, 2, 12, 18):
        url = ("https://noaa-nbm-grib2-pds.s3.amazonaws.com/"
               f"blend.20260917/{hour:02d}/text/blend_nbptx.t{hour:02d}z")
        path = cache / f"nbp-20260917T{hour:02d}Z.txt"
        receipt_path = path.with_suffix('.txt.json')
        if receipt_path.exists() and not path.exists():
            receipt = json.loads(receipt_path.read_text())
            assert receipt['url'] == url and receipt['status'] in (403, 404)
            results.append({**receipt, 'hour': hour})
            continue
        if path.exists():
            receipt = json.loads(receipt_path.read_text())
            body = path.read_bytes()
            assert receipt['url'] == url
            assert receipt['sha256'] == hashlib.sha256(body).hexdigest()
        else:
            response = requests.get(url, timeout=90)
            if response.status_code in (403, 404):
                receipt = {'url': url, 'status': response.status_code,
                           'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
                receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
                results.append({**receipt, 'hour': hour})
                continue
            response.raise_for_status()
            body = response.content
            with path.open('xb') as handle:
                handle.write(body)
            receipt = {'url': url, 'sha256': hashlib.sha256(body).hexdigest(),
                       'bytes': len(body), 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        block = '\n'.join(station_nbp_block(body.decode('utf-8'), 'KLGA')) + '\n'
        (output / f'20260917T{hour:02d}Z-KLGA.txt').write_text(block, encoding='utf-8')
        payload = parse_nbp_station_tmax_v1(block, 'KLGA', '2026-09-17')
        guam = '\n'.join(station_nbp_block(body.decode('utf-8'), 'PGUM')) + '\n'
        (output / f'20260917T{hour:02d}Z-PGUM.txt').write_text(guam, encoding='utf-8')
        guam_payload = parse_nbp_station_tmax_v1(guam, 'PGUM', '2026-09-17')
        results.append({**receipt, 'hour': hour, 'legacy_available': payload['available'],
                        'percentiles': payload.get('percentiles'),
                        'txn_rows': [line[:6].strip() for line in block.splitlines() if line.strip().startswith('TXN')],
                        'guam_legacy_available': guam_payload['available'],
                        'guam_percentiles': guam_payload.get('percentiles')})
    (output / 'p0.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


def window(output: Path) -> None:
    """83b: table the existing candidate search, without forecasts or outcomes."""
    from datetime import date
    from zoneinfo import ZoneInfo
    from weather.sources.nbm_probabilistic_tmax import nbp_target_cycle_candidates
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for day in (date(2026, 1, 17), date(2026, 9, 17)):
        for zone in ('America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles'):
            for hour in range(24):
                now = datetime.combine(day, datetime.min.time(), ZoneInfo(zone)).replace(hour=hour)
                cycles = nbp_target_cycle_candidates(now.astimezone(timezone.utc), day)
                row = {'season': 'standard' if day.month == 1 else 'daylight',
                       'zone': zone, 'local_hour': hour, 'captured_at': now.isoformat()}
                for index, label in enumerate(('healthy', 'if_404')):
                    cycle = cycles[index] if len(cycles) > index else None
                    row[label + '_cycle'] = cycle.isoformat() if cycle else 'unavailable'
                    row[label + '_age_hours'] = (now - cycle).total_seconds() / 3600 if cycle else None
                rows.append(row)
    with (output / 'window.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    unavailable = sum(row['healthy_cycle'] == 'unavailable' for row in rows)
    print(json.dumps({'rows': len(rows), 'healthy_unavailable': unavailable,
                      'output': str(output / 'window.csv')}))


def reuse_cost(cache: Path, output: Path) -> None:
    """83c: time one retained national bulletin with every download stubbed."""
    import gc
    import time
    import tracemalloc
    from unittest.mock import patch
    from weather.collection.forecast_payload_fetch_fanout import (
        CrossProcessMarketInvariantFetchFanout, _complete_nbp, _nbp_reuse_stations,
    )
    from weather.sources.nbm_probabilistic_tmax import nbp_request_key, nbp_cycle_key_from_url

    output.mkdir(parents=True, exist_ok=False)
    body = cache.read_bytes()
    receipt = json.loads(cache.with_suffix(cache.suffix + '.json').read_text())
    digest = hashlib.sha256(body).hexdigest()
    if digest != receipt['sha256'] or len(body) != receipt['bytes']:
        raise ValueError('retained national file does not match its original receipt')
    cycle = nbp_cycle_key_from_url(receipt['url'])
    key = dict(source='nbm_probabilistic_tmax', request_key=nbp_request_key(receipt['url']), cycle_key=cycle)
    stations = _nbp_reuse_stations()
    downloads = []

    def download():
        downloads.append(1)
        return dict(text=body.decode('utf-8'), fetched_at=receipt['retrieved_at_utc'],
                    request_started_at=receipt['started_at_utc'],
                    response_received_at=receipt['retrieved_at_utc'])

    measurements = []

    def measure(name, callback):
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        try:
            result = callback()
            seconds = time.perf_counter() - started
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        measurements.append(dict(operation=name, wall_seconds=seconds,
                                 traced_current_bytes=current, traced_peak_bytes=peak))
        return result

    with patch('requests.sessions.Session.request', side_effect=AssertionError('83c forbids network')):
        warm = CrossProcessMarketInvariantFetchFanout(output / 'cas')
        first = warm.fetch_reusable_nbp(**key, scope_key='warm', fetch_fn=download)
        if not list((output / 'cas' / 'nbp_cycle_index').glob('*/*.json')):
            raise ValueError('retained bulletin failed completeness or receipt admission')
        del first, warm
        coordinator = CrossProcessMarketInvariantFetchFanout(output / 'cas')
        raw = measure('blob_read_hash', lambda: coordinator.cas.read(digest, expected_bytes=len(body)))
        text = raw.decode('utf-8')
        del raw
        if not measure('complete_nbp', lambda: _complete_nbp(text, cycle, stations)):
            raise ValueError('retained bulletin is incomplete')
        del text
        before = len(downloads)
        result = measure('whole_reuse', lambda: coordinator.fetch_reusable_nbp(
            **key, scope_key='later-reuse', fetch_fn=download))
        assert result.reused and not result.fetched and len(downloads) == before
        assert result.coordinator_network_fetch_count == 0
        del result, coordinator
        ordinary = CrossProcessMarketInvariantFetchFanout(output / 'cas')
        result = measure('whole_per_scope_stubbed', lambda: ordinary.fetch(
            **key, scope_key='later-ordinary', fetch_fn=download))
        assert result.fetched and len(downloads) == before + 1
        del result, ordinary
    summary = dict(national_sha256=digest, national_bytes=len(body), cycle=cycle,
                   stations=list(stations), network_requests=0, stub_downloads=len(downloads),
                   measurements=measurements)
    (output / 'cost.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['p0', 'p5', 'contracts', 'window', 'reuse-cost'])
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.stage == 'p0':
        if args.cache is None:
            parser.error('p0 requires --cache')
        p0(args.cache, args.output)
    elif args.stage == 'p5':
        if args.artifact is None:
            parser.error('p5 requires --artifact')
        p5(args.artifact, args.output)
    elif args.stage == 'window':
        window(args.output)
    elif args.stage == 'reuse-cost':
        if args.cache is None:
            parser.error('reuse-cost requires --cache naming an existing national file')
        reuse_cost(args.cache, args.output)
    else:
        contracts(args.output)


if __name__ == "__main__":
    main()
