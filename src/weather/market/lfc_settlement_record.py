"""Read-only venue resolution evidence, matched to campaign leg-intent token IDs.

Owner/analysis command: python -m weather.market.lfc_settlement_record --condition 0x... [--root DIR].
Pending observations are immutable; rerun until settlement/<condition>.json exists.
Contract: https://data-api.polymarket.com/v2/docs (Resolution and TokenRef).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import HTTPError
from functools import partial

from weather.market.mm_stage2_hold import utc
from weather.market.lfc_recording_io import (PublicReadFailure, observed_get, prepare_recovery,
    publish_recovery, read_bytes, read_recovered, retained, response_bytes, strict_json, write_new)
from weather.market.wallet_reader_transport import direct_opener

SETTLEMENT_SCHEMA = 'lfc_venue_settlement_v0.1'
API = 'https://data-api.polymarket.com'
MAX_BYTES = 2_000_000
USER_AGENT = 'weather-lfc-recording/1'


def condition_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
        raise ValueError('invalid_condition_id')
    return value.lower()


def public_get(path, params):
    """Exact public GET allowlist; no credential loader, SDK, or mutation transport."""
    if path not in {'/v2/resolutions', '/v2/tokens', '/v2/activity'}:
        raise ValueError('recording_endpoint_refused')
    request = Request(API + path + '?' + urlencode(params), method='GET',
                      headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
    response, status, body = None, None, bytearray()
    try:
        try:
            response = direct_opener().open(request, timeout=15)
        except HTTPError as exc:
            response = exc
        status = response.status
        while len(body) <= MAX_BYTES:
            block = response.read(min(65536, MAX_BYTES + 1 - len(body)))
            if not block:
                break
            body.extend(block)
        if len(body) > MAX_BYTES:
            raise PublicReadFailure('recording_response_budget', status=status,
                                    raw=bytes(body[:MAX_BYTES]), truncated=True)
        if status != 200 or response.geturl() != request.full_url:
            raise PublicReadFailure('recording_response_refused', status=status, raw=bytes(body))
        return bytes(body)
    except PublicReadFailure:
        raise
    except Exception:
        raise PublicReadFailure('recording_transport_failed', status=status,
                                raw=bytes(body) if body else None) from None
    finally:
        if response is not None:
            response.close()


def envelope(raw):
    result = strict_json(raw)
    if not isinstance(result, dict) or not isinstance(result.get('data'), list):
        raise ValueError('recording_envelope')
    return result


def traded_token_ids(root, condition):
    """Read only token identities from verified campaign leg_intent rows, never settlement labels."""
    from weather.market.lfc_ledger import Ledger, ledger_path
    ledger = Ledger.open(ledger_path(root), clock=lambda: datetime.now(timezone.utc))
    return sorted({str(row['token_id']) for row in ledger.rows if row['event'] == 'leg_intent'
                   and str(row['condition_id']).lower() == condition})


def select_token_pair(condition, rows, traded_tokens):
    traded = set(map(str, traded_tokens))
    groups = {}
    for row in rows:
        if condition_id(row['condition_id']) != condition:
            continue
        key = (row['module'], row.get('structural_condition_id'))
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        slots = {}
        for row in group:
            index, token = row['outcome_index'], row['token_id']
            if (type(index) is not int or index not in (0, 1) or index in slots or
                    not isinstance(token, str) or not re.fullmatch(r'[0-9]+', token)):
                break
            slots[index] = token
        else:
            if set(slots) == {0, 1} and len(set(slots.values())) == 2 and traded and traded <= set(slots.values()):
                return [slots[0], slots[1]]
    raise ValueError('no_matching_token_pair')


def resolution_result(condition, resolution_raw, tokens_raw, *, traded_tokens):
    """Use on-chain payout slots and reference ids only, never final_price or price."""
    rows = envelope(resolution_raw)['data']
    if any(condition_id(r['condition_id']) != condition for r in rows) or len(rows) > 1:
        raise ValueError('resolution_condition_scope')
    if not rows or rows[0]['status'] != 'resolved':
        return False, None, []
    payouts = rows[0].get('payouts')
    if payouts is None:
        # UMA lifecycle can say resolved before terminal CTF payout evidence is served.
        return False, None, []
    if (not isinstance(payouts, list) or len(payouts) != 2 or
            any(type(p) is not int or p < 0 for p in payouts) or sum(payouts) != 1_000_000):
        raise ValueError('resolution_payouts_unreadable')
    pair = select_token_pair(condition, envelope(tokens_raw)['data'], traded_tokens)
    winner = next((pair[i] for i, payout in enumerate(payouts) if payout == 1_000_000), None)
    return True, winner, pair


def record_settlement(root, condition, *, clock=None, get=public_get, traded_tokens=None, recover_corrupt=False):
    condition = condition_id(condition)
    clock = clock or (lambda: datetime.now(timezone.utc))
    directory = Path(root) / 'settlement'
    target = directory / (condition + '.json')
    recovery = None
    if target.exists():
        try:
            read_recovered(target, lambda p: validate_settlement(p, condition))
        except (ValueError, KeyError, TypeError, UnicodeError):
            if not recover_corrupt:
                raise
            target, recovery = prepare_recovery(target, clock=clock, reason='invalid_settlement_record')
        else:
            raise FileExistsError('settlement_exists')
    reason, terminal, winner, pair = None, False, None, []
    resolution_raw, tokens_raw = None, None
    read = partial(observed_get, directory / 'reads' / condition, get, clock=clock)
    if traded_tokens is None:
        try:
            traded_tokens = traded_token_ids(root, condition)
        except (OSError, ValueError, RuntimeError):
            traded_tokens, reason = [], 'traded_tokens_unavailable'
    traded_tokens = sorted(set(map(str, traded_tokens)))
    try:
        resolution_raw = read('/v2/resolutions', {'condition': condition})
        rows = envelope(resolution_raw)['data']
        tokens_raw = (read('/v2/tokens', {'condition': condition})
                      if rows and rows[0].get('status') == 'resolved' and rows[0].get('payouts') is not None
                      else b'{"data":[]}')
        terminal, winner, pair = resolution_result(condition, resolution_raw, tokens_raw, traded_tokens=traded_tokens)
    except Exception as exc:
        terminal, winner, pair = False, None, []
        reason = reason or (str(exc) if re.fullmatch(r'[a-z_]+', str(exc)) else 'resolution_evidence_refused')
    observed = utc(clock()).isoformat()
    result = {'schema_version': SETTLEMENT_SCHEMA, 'kind': 'lfc_venue_settlement',
              'condition_id': condition, 'observed_at_utc': observed, 'terminal': terminal,
              'winning_token_id': winner, 'token_ids': pair, 'traded_token_ids': traded_tokens,
              'reason': reason, 'resolution': retained(resolution_raw) if resolution_raw is not None else None,
              'tokens': retained(tokens_raw) if tokens_raw is not None else None}
    directory.mkdir(parents=True, exist_ok=True)
    if not terminal:
        directory = directory / 'pending' / condition
        directory.mkdir(parents=True, exist_ok=True)
        stem = utc(observed).strftime('%Y%m%dT%H%M%S%fZ')
        target = directory / (stem + '.json')
        for number in range(1, 1000):
            if not target.exists():
                break
            target = directory / f'{stem}-{number:03d}.json'
    write_new(target, result)
    if terminal and recovery:
        publish_recovery(target, recovery)
    return result


def validate_settlement(path, condition):
    row = strict_json(read_bytes(path, MAX_BYTES * 6))
    return validate_settlement_row(row, condition)


def validate_settlement_row(row, condition):
    """Pure replay validator for the retained recorder evidence in the ledger."""
    if row.get('schema_version') != SETTLEMENT_SCHEMA or row.get('condition_id') != condition:
        raise ValueError('settlement_record_scope')
    terminal, winner, pair = resolution_result(condition, response_bytes(row['resolution']),
        response_bytes(row['tokens']), traded_tokens=row['traded_token_ids'])
    if row.get('terminal') is not terminal or row.get('winning_token_id') != winner or row.get('token_ids') != pair:
        raise ValueError('settlement_record_mismatch')
    utc(row['observed_at_utc'])
    return row


def load_settlements(directory, conditions, *, tokens_by_condition=None):
    """Only recorder files are admitted; absent/nonterminal evidence stays unknown."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('settlement_directory_required')
    result = {}
    for condition in sorted(set(conditions)):
        condition = condition_id(condition)
        path = directory / (condition + '.json')
        if not path.exists():
            continue
        row, _ = read_recovered(path, lambda p: validate_settlement(p, condition))
        terminal, winner, pair = row['terminal'], row['winning_token_id'], row['token_ids']
        if tokens_by_condition and not set(tokens_by_condition.get(condition, ())) <= set(pair):
            raise ValueError('settlement_leg_token_outside_pair')
        utc(row['observed_at_utc'])
        if terminal and winner is not None:
            result[condition] = winner
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--condition', required=True, action='append')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--recover-corrupt', action='store_true', help='retain corrupt originals and publish an explicit recovery manifest')
    args = parser.parse_args(argv)
    from weather.market.lfc_pilot import pilot_root
    rows = [record_settlement(args.root or pilot_root(), condition, recover_corrupt=args.recover_corrupt) for condition in args.condition]
    return 0 if all(row['terminal'] for row in rows) else 2


if __name__ == '__main__':
    raise SystemExit(main())
