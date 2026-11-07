"""Strict terminal-evidence qualification shared by LFC producers and consumers."""
from pathlib import Path

from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json


def evidence_flags(row):
    row = row if isinstance(row, dict) else {}
    return {'evidence_complete': row.get('evidence_complete') is True,
            'inventory_proven': row.get('inventory_proven') is True,
            'unknown_submit': row.get('unknown_submit') is not False}


def complete_evidence(row):
    flags = evidence_flags(row)
    return flags['evidence_complete'] and flags['inventory_proven'] and not flags['unknown_submit']


def session_prediction(directory):
    directory = Path(directory)
    row = strict_json(read_bytes(directory / 'prediction.json', 2_000_000))
    if not isinstance(row, dict) or not complete_evidence(row) or file_sha(directory / 'journal.jsonl') != row.get('journal_sha256'):
        raise ValueError('session_evidence_incomplete')
    return row


def ledger_completion(root, ledger):
    flags = {'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False}
    refused = []
    for session_id, session in ledger.sessions.items():
        try:
            relative = Path(session['start']['directory'])
            directory = (Path(root) / relative).resolve()
            directory.relative_to(Path(root).resolve())
            if session['end'] is None:
                raise ValueError('session_not_closed')
            # Older end envelopes did not copy these fields. Their canonical
            # prediction must still supply all three proofs; no default qualifies
            # it. An explicitly incomplete newer end envelope cannot be ignored.
            if any(key in session['end'] for key in evidence_flags(None)) and not complete_evidence(session['end']):
                raise ValueError('session_end_evidence_incomplete')
            session_prediction(directory)
        except (OSError, ValueError, KeyError, TypeError):
            refused.append(session_id)
    if refused or ledger.unacknowledged_intents() or ledger.unresolved_legs():
        flags.update(evidence_complete=False, inventory_proven=False,
                     unknown_submit=bool(refused or ledger.unacknowledged_intents()))
    return dict(flags, evidence_refusals=refused)
