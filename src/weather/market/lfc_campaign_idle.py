"""Disposable metadata cache for healthy, non-admitting scheduled idle ticks.

It never supplies money proof, clears incidents or authorizes a claim. Any
missing/changed file, unavailable NTFS change stamp, due work or entry lookback
keeps the ordinary full retained-evidence verifier and its N1 fault path.
"""
from datetime import timedelta
from pathlib import Path
import os
import time
import uuid

from weather.market.lfc_recording_io import read_bytes, strict_json, write_new
from weather.market.lfc_campaign_state import STATE_SCHEMA
from weather.operations.live_path_security import validate_nonreparse_directory, validate_regular_nonreparse_file


CACHE_NAME = '.idle-validation.json'
MAX_FILES = 50000
CACHE_LIMIT = 16 * 1024**2


def eligible(coordinator, policy):
    state, runtime = coordinator.state, coordinator.runtime
    ledger = state.ledger
    if policy is None or not policy.raw['enabled'] or not runtime.task_enabled():
        return False
    if ledger.halted or ledger.open_sessions() or ledger.unresolved_legs():
        return False
    if getattr(ledger, 'capital_rows', ()):
        from weather.market.lfc_capital import CapitalBook
        book = CapitalBook(ledger)
        figures = book.figures()
        if (book.blocking_unknown() or figures['unrecovered_inventory_cost_native'] or
                figures['resting_reserve_native']):
            return False
    if coordinator.record_followups is not None:
        due = getattr(runtime, 'followup_due', None)
        if not callable(due) or due(policy):
            return False
    # Owner 11-13: no one-try-per-day rule; mirror the coordinator's entry loop.
    blocked = state.consumed_dates()
    attempted = {row['local_date'] for row in state.claims()} | {row['local_date'] for row in state.skips()} | {
        session['start'].get('owner_local_date') for session in state.ledger.sessions.values() if session['legs']}
    now = coordinator.clock.now()
    for entry in policy.entries:
        if entry.local_date in blocked or (now >= entry.end and entry.local_date in attempted):
            continue
        lookback = timedelta(seconds=max(300, 1800 - (entry.end-entry.start).total_seconds()))
        # An expired unconsumed date needs its ordinary durable skip, too.
        if now >= entry.start-lookback:
            return False
    return True


def context(coordinator, policy):
    state = coordinator.state
    return {'version': 1, 'state_root': str(state.root.absolute()),
            'state_id': state.ledger.enrollment['state_id'], 'ledger_sha256': state.ledger.previous,
            'policy_sha256': policy.sha256, 'policy_bytes_sha256': policy.source_sha256,
            'release_head': getattr(coordinator.runtime, 'release', {}).get('head')}


def snapshot(state):
    """Check names, presence, sizes, file identities and native change sequences.

    The whole private directory is watched, including ACKs accepted in an
    owner closure and later restored artifacts. No evidence content is read.
    Missing roots/reparse points disable the shortcut rather than waive a fault.
    """
    began = time.monotonic()
    private = state.ledger.path.parent.absolute()
    roots = {state.root.absolute()}
    # Full result packets are immutable ledger-bound sources of parent paths;
    # per-band session paths alone omit the shared F2 journal and go packet.
    for event in state.ledger.autostart_results:
        row = state.read_uncached(state.root/'results'/(event['attempt_id']+'.json'))
        name = Path(str(row.get('private_evidence_directory') or ''))
        if name.parts:
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('idle_private_scope')
            roots.add(private/name)
    for session in state.ledger.sessions.values():
        name = Path(str(session['start'].get('directory') or ''))
        if name.parts:
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('idle_session_scope')
            roots.add(private/name)
    roots = sorted(roots, key=lambda p: (len(p.parts), str(p)))
    minimal = []
    for root in roots:
        if not any(root.is_relative_to(parent) for parent in minimal):
            minimal.append(root)
    pending, files, directories = list(minimal), {}, []
    while pending:
        directory = validate_nonreparse_directory(pending.pop())
        directories.append(str(directory))
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                # This is disposable derived data, never an original receipt.
                if path.parent == state.root and path.name.startswith('.idle-validation'):
                    continue
                if len(files)+len(directories)+len(pending) >= MAX_FILES or time.monotonic()-began > 25:
                    raise ValueError('idle_metadata_budget')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    signature = state._retained_cache.signature(path)
                    if signature[-1] is None:
                        raise ValueError('idle_native_stamp_unavailable')
                    files[str(path)] = signature
    return {'directories': sorted(directories), 'files': files}


def unchanged(coordinator, policy, observed):
    path = coordinator.state.root/CACHE_NAME
    try:
        row = strict_json(read_bytes(validate_regular_nonreparse_file(path), CACHE_LIMIT))
        # JSON normalizes native stamp tuples to lists. Compare canonical data.
        from weather.market.mm_stage2_hold import digest
        return (row.get('schema_version') == STATE_SCHEMA and row.get('kind') == 'idle_retained_validation' and
                row.get('context') == context(coordinator, policy) and
                row.get('metadata_sha256') == digest(observed) == digest(row.get('metadata')))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return False


def prepare(coordinator, policy):
    try:
        if eligible(coordinator, policy):
            return snapshot(coordinator.state)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        pass
    return None


def remember(coordinator, policy, before):
    """Publish only when a full successful validation was bracketed unchanged."""
    if before is None:
        return
    temporary = coordinator.state.root/('.idle-validation-'+uuid.uuid4().hex+'.tmp')
    try:
        from weather.market.mm_stage2_hold import digest
        after = snapshot(coordinator.state)
        if digest(before) != digest(after):
            return
        target = coordinator.state.root/CACHE_NAME
        if target.exists():
            validate_regular_nonreparse_file(target)
        write_new(temporary, {'schema_version': STATE_SCHEMA, 'kind': 'idle_retained_validation',
            'context': context(coordinator, policy), 'metadata': after, 'metadata_sha256': digest(after)},
            max_bytes=CACHE_LIMIT)
        os.replace(temporary, target)  # Mutable cache only; originals stay create-only.
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        pass  # No cache means the next idle tick performs full validation again.
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
