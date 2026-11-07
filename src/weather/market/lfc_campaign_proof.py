"""Local private evidence binding before any later read can qualify money proof."""
from pathlib import Path

from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json


def local_money_proof(directory, *, ledger, session_id, attempt_id, outcome):
    """Retain failed raw flags; never interpret an unexplained false as ancillary.

    A later complete quantity read can resolve an unavailable acknowledged
    postcheck. It cannot replace missing private identities/journals, invent a
    clean crashed session, or turn unknown placement into a known submission.
    """
    result = {'complete': False, 'unknown_submit': True, 'failure': 'private_evidence_unbound'}
    try:
        directory = Path(directory)
        session = ledger.sessions[session_id]
        if session['end'] is None or session['start'].get('autostart_attempt_id') != attempt_id:
            return result
        hashes = outcome['evidence_sha256']
        for name in ('journal.jsonl', 'prediction.json', 'session_end.json'):
            if hashes.get(name) != file_sha(directory / name):
                return result
        prediction = strict_json(read_bytes(directory / 'prediction.json', 2_000_000))
        flags = evidence_flags(prediction)
        ids = [ledger.legs[key]['order_id'] for key in session['legs']]
        if (prediction.get('mode') != 'live' or flags['unknown_submit'] or any(oid is None for oid in ids) or
                prediction.get('post_count') != len(ids) or set(prediction.get('order_ids', [])) != set(ids) or
                prediction.get('journal_sha256') != hashes['journal.jsonl'] or
                prediction.get('scope', {}).get('session_id') != session_id):
            return result
        journal = directory / 'journal.jsonl'
        if journal.stat().st_size > 256 * 1024 * 1024:
            return result
        explained = set()
        with journal.open('rb') as stream:
            for _ in range(100000):
                raw = stream.readline(2_000_001)
                if not raw:
                    break
                if len(raw) > 2_000_000 or not raw.endswith(b'\n'):
                    return result
                row = strict_json(raw)
                event = row.get('event')
                if event == 'scoring_missed':
                    explained.add('scoring_missed')
                if event == 'missing_sample' and row.get('sample') in {'accrual', 'final_accrual', 'final_balances'}:
                    explained.add('ancillary_sample_missed')
            else:
                return result
        if not flags['evidence_complete'] and not explained and prediction.get('failure_type') is None:
            return dict(result, failure='unexplained_false_evidence_flag', raw_flags=flags)
        return {'complete': True, 'unknown_submit': False, 'raw_flags': flags,
                'explained_gaps': sorted(explained), 'failure_type': prediction.get('failure_type'),
                'evidence_sha256': {name: hashes[name] for name in ('journal.jsonl', 'prediction.json', 'session_end.json')}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result
