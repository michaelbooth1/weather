"""Ledger-bound completed attempts, checked before pending/idle processing.

The disposable idle manifest is never the authority for completion. Every
closure anchor is checked independently, even when full private validation is
skipped. A missing original is an evidence fault, never a pending postcheck.
"""
import os
import hashlib
from pathlib import Path
import re
import uuid

from weather.market.lfc_ledger_queries import event_rows
from weather.market.lfc_ledger import LedgerUnavailable
from weather.market.lfc_campaign_persistence import retry_failure
from weather.market.lfc_recording_io import STATE_JSON_LIMIT, file_sha, strict_json, read_bytes
from weather.market.mm_stage2_hold import canonical_bytes, digest, utc
from weather.operations.live_path_security import validate_regular_nonreparse_file


PROTOCOL = 'lfc_closure_intent_v2'
KINDS = {'postcheck', 'automatic_no_intent', 'owner_recovery', 'owner_operational_close'}


def validate_anchor(ledger, row, *, intent=False):
    """Replay checks only; filesystem validation belongs to account state."""
    from weather.market.lfc_ledger import LedgerUnavailable
    attempt = row.get('attempt_id')
    shas = ('file_sha256', 'proof_sha256', 'close_ledger_sha256')
    if (not any(c['attempt_id'] == attempt for c in ledger.autostart_claims) or
            row.get('file') != 'closed/' + str(attempt) + '.json' or
            type(row.get('file_size')) is not int or not 0 < row['file_size'] <= STATE_JSON_LIMIT or
            not isinstance(row.get('close_kind'), str) or row['close_kind'] not in KINDS or
            any(not isinstance(row.get(k), str) or not re.fullmatch('[0-9a-f]{64}', row[k]) for k in shas) or
            not isinstance(row.get('read_binding'), dict) or
            event_rows(ledger, 'autostart_close', field='attempt_id', value=attempt)):
        raise LedgerUnavailable('ledger_closure_anchor_scope')
    try:
        utc(row['closed_at_utc'])
        binding = row['read_binding']
        if set(binding) != {'read_sha256', 'started_at_utc', 'ended_at_utc'}:
            raise ValueError('read_binding')
        if binding['read_sha256'] is not None and (not isinstance(binding['read_sha256'], str) or
                not re.fullmatch('[0-9a-f]{64}', binding['read_sha256'])):
            raise ValueError('read_hash')
        for key in ('started_at_utc', 'ended_at_utc'):
            if binding[key] is not None:
                utc(binding[key])
        if row['close_ledger_sha256'] not in {ledger.row_sha256(i) for i in range(row['sequence'])}:
            raise ValueError('close_head')
    except (ValueError, TypeError, KeyError):
        raise LedgerUnavailable('ledger_closure_anchor_binding') from None
    if not intent and ledger.enrollment.get('closure_anchor_protocol') == PROTOCOL:
        from weather.market.lfc_campaign_close_intent import saved_intent
        saved = saved_intent(ledger, attempt)
        keys = ('attempt_id', 'file', 'file_size', 'close_kind', 'closed_at_utc', 'read_binding', *shas)
        if saved is None or any(saved.get(key) != row.get(key) for key in keys):
            raise LedgerUnavailable('ledger_closure_anchor_binding')


def write_closure(path, row, *, max_bytes, before_publish=None):
    """Fsync first, then Windows atomic no-replace rename; never overwrite."""
    raw = canonical_bytes(row)
    if len(raw) > max_bytes:
        raise ValueError('recording_file_budget')
    strict_json(raw)
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.attempt-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        if stream.write(raw) != len(raw):
            raise OSError('recording_short_write')
        stream.flush(); os.fsync(stream.fileno())
    if before_publish is not None:
        before_publish(path, raw)
    if os.name == 'nt':
        os.rename(temporary, path)  # Windows refuses an existing destination.
    else:
        os.link(temporary, path)  # Portable exclusive publication, same bytes.
        temporary.unlink()


def fields(state, path):
    raw = read_bytes(validate_regular_nonreparse_file(path.absolute()), STATE_JSON_LIMIT)
    return fields_from_raw(path, raw)


def fields_from_raw(path, raw):
    from weather.market.lfc_campaign_state import StateRefused, STATE_SCHEMA
    row = strict_json(raw)
    if not isinstance(row, dict) or row.get('schema_version') != STATE_SCHEMA:
        raise StateRefused('closeout_schema')
    proof = row.get('proof', {})
    if (path.name != str(row.get('attempt_id')) + '.json' or not isinstance(proof, dict) or
            row.get('proof_sha256') != digest(proof) or proof.get('unknown_submit') is not False or
            proof.get('cleanup_proven') is not True or proof.get('money_accounting_complete') is not True):
        raise StateRefused('closeout_continuity')
    read = proof.get('account_read') or {}
    if not isinstance(read, dict) or read and proof.get('read_sha256') != digest(read):
        raise StateRefused('closeout_read_binding')
    return {'attempt_id': row['attempt_id'], 'file': 'closed/' + path.name,
        'file_sha256': hashlib.sha256(raw).hexdigest(), 'file_size': len(raw),
        'close_kind': proof.get('authority', 'postcheck'), 'closed_at_utc': row['closed_at_utc'],
        'close_ledger_sha256': proof['ledger_head_sha256'], 'proof_sha256': row['proof_sha256'],
        'read_binding': {'read_sha256': proof.get('read_sha256'),
            'started_at_utc': read.get('started_at_utc'), 'ended_at_utc': read.get('ended_at_utc')}}


def anchor(state, attempt):
    """File is already durable. The existing ledger writer fsyncs this anchor."""
    path = state.root / 'closed' / (attempt + '.json')
    from weather.market.lfc_campaign_close_intent import require_match
    item = fields(state, path)
    require_match(state, item)
    existing = event_rows(state.ledger, 'autostart_close', field='attempt_id', value=attempt)
    if existing:
        try:
            matches = file_sha(path) == existing[0]['file_sha256']
        except OSError:
            matches = False
        if not matches:
            fault(state, attempt)
        return existing[0]
    return state.ledger.record('autostart_close', **item)


def fault(state, attempt, *, refuse=True):
    from weather.market.lfc_campaign_state import StateRefused
    state.evidence_fault(attempt, artifact='state/closed/' + attempt + '.json')
    if refuse:
        raise StateRefused('anchored_closure_evidence_fault')


def accepted_loss(state, saved, observed):
    """One explicit committed owner decision may acknowledge the lost original.

    It never regenerates the old close. Restored artifacts retain N1's separate
    binding, so a later disappearance needs a new occurrence/owner decision.
    """
    name = 'state/' + saved['file']
    decisions = event_rows(state.ledger, 'autostart_owner_close', field='source_attempt_id', value=saved['attempt_id'])
    for decision in reversed(decisions):
        if decision['sequence'] <= saved['sequence']:
            continue
        receipt = state.read(state.root / decision['file'])
        manifest = receipt.get('artifact_manifest', {})
        if name not in manifest:
            continue
        expected = manifest[name]
        restored = [r for r in event_rows(state.ledger, 'autostart_owner_artifact_restored')
                    if r.get('closure_sha256') == decision['file_sha256'] and r.get('artifact') == name]
        if expected is None and restored:
            expected = restored[0]['file_sha256']
        if observed != expected:
            continue
        from weather.market.lfc_campaign_owner_close import binding
        return binding(state, saved['attempt_id'], incident=decision['incident_id']) is not None
    return False


def check(state, *, full=False, owner_fault_review=False):
    """Cheap invariant independent of full validation or any idle cache.

    Cold or changed files are hashed, streamed. Warm unchanged files use native
    identity/change stamps; full validation always hashes every original.
    """
    from weather.market.lfc_campaign_state import StateRefused
    ledger = state.ledger
    if ledger.enrollment.get('closure_anchor_protocol') != PROTOCOL:
        # No production F2 campaign has enrolled. Refuse old roots entirely,
        # including an old result whose completed closure has disappeared.
        raise StateRefused('closure_anchor_protocol_required')
    generic = {r['attempt_id']: r for r in event_rows(ledger, 'autostart_close')}
    anchors = dict(generic)
    for saved in event_rows(ledger, 'autostart_close_intent'):
        anchors.setdefault(saved['attempt_id'], saved)
    # The older no-intent decision is itself proof that the file was already
    # published. Its hash must protect the tiny gap before the generic anchor.
    for saved in event_rows(ledger, 'autostart_no_intent_close'):
        anchors.setdefault(saved['attempt_id'], {**saved,
            'file': 'closed/' + saved['attempt_id'] + '.json', 'file_size': None})
    state._closure_faults, state._closure_accepted = set(), set()
    for attempt, saved in anchors.items():
        path = state.root / saved['file']
        observed = None
        try:
            if saved['file_size'] is not None and path.stat().st_size != saved['file_size']:
                raise ValueError('closure_size')
            observed = file_sha(path) if full else state.file_sha(path)
            if observed != saved['file_sha256']:
                raise ValueError('closure_hash')
        except (OSError, ValueError, RuntimeError):
            state._closure_faults.add(attempt)
            try:
                observed = state.file_sha(path) if path.exists() else None
                accepted = accepted_loss(state, saved, observed)
            except (OSError, ValueError, RuntimeError):
                accepted = False
            if accepted:
                state._closure_accepted.add(attempt)
                continue
            fault(state, attempt, refuse=not owner_fault_review)
    for path in (state.root/'closed').glob('*.json'):
        if path.stem in generic or path.stem in state._closure_accepted:
            continue
        attempt = path.stem
        item = None
        try:
            item = fields(state, path)
            if item['close_ledger_sha256'] not in {ledger.row_sha256(i) for i in range(len(ledger.rows))}:
                state.evidence_fault(attempt, artifact='state/closed/' + attempt + '.json')
                raise StateRefused('closeout_ledger_continuity')
            from weather.market.lfc_campaign_close_intent import require_match
            require_match(state, item)
            claims = [r for r in ledger.autostart_claims if r['attempt_id'] == attempt]
            if len(claims) != 1:
                raise StateRefused('closeout_claim_binding')
            claim = state.read_uncached(state.root/'claims'/(claims[0]['local_date']+'.json'),
                                       expected_sha256=claims[0]['file_sha256'])
            policy = state.read_uncached(state.root/'policies'/(attempt+'.json'),
                                        expected_sha256=claim['policy_snapshot_sha256'])
            if (claim['attempt_id'] != attempt or claim['ledger_sha256'] != claims[0]['previous_sha256'] or
                    policy.get('sha256') != claim['policy_sha256'] or digest(policy.get('policy')) != claim['policy_sha256']):
                raise StateRefused('closeout_claim_binding')
            if claim.get('prepared_file') is not None:
                relative = Path(claim['prepared_file'])
                if relative.is_absolute() or '..' in relative.parts or state.file_sha(state.root/relative) != claim['prepared_sha256']:
                    raise StateRefused('closeout_prepared_binding')
            state.require_history()
            proof = state.read_uncached(path)['proof']
            authority = item['close_kind']
            from weather.market.lfc_campaign_owner_close import binding
            if binding(state, attempt) is not None:
                pass  # A committed owner decision binds the preserved file and any acknowledged gaps.
            elif authority == 'automatic_no_intent':
                from weather.market.lfc_campaign_recovery import close_empty, empty_binding
                if empty_binding(state, attempt) is None:
                    close_empty(state, claim, utc(item['closed_at_utc']))
                if empty_binding(state, attempt) is None:
                    raise StateRefused('no_intent_close_binding')
            elif authority == 'owner_operational_close':
                raise StateRefused('owner_committed_close_binding')
            elif authority == 'owner_recovery':
                state.owner_close_binding(claim, proof)
            elif (any(s['start'].get('autostart_attempt_id') == attempt for s in ledger.sessions.values()) or
                  any(r['attempt_id'] == attempt for r in ledger.autostart_results)):
                _, sha, local = state.retained_result(claim)
                if proof.get('result_sha256') != sha or proof.get('private_evidence_sha256') != digest(local):
                    raise StateRefused('closeout_private_evidence_binding')
        except LedgerUnavailable as exc:
            # A dedicated no-intent/owner restoration append may occur during
            # binding. Ledger write errors are not lost closure evidence.
            if item is not None:
                retry_failure(state, attempt, exc, expected=item)
            raise
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            state._closure_faults.add(attempt)
            if isinstance(exc, StateRefused) and str(exc) in {
                    'retained_private_evidence_fault', 'private_result_evidence_fault',
                    'historical_recovery_evidence_fault', 'historical_money_ambiguity_requires_owner_recovery',
                    'closeout_ledger_continuity'}:
                if not owner_fault_review:
                    raise  # These paths already persist the actual artifact occurrence.
            else:
                fault(state, attempt, refuse=not owner_fault_review)
        else:
            # Validation has completed. Do not catch persistence failures in
            # the evidence-loss handler above, including recovery after fsync.
            try:
                anchor(state, attempt)
            except (OSError, LedgerUnavailable) as exc:
                retry_failure(state, attempt, exc, expected=item)
    state._closure_completed = set(generic) | state._closure_accepted | {r['attempt_id'] for r in event_rows(state.ledger, 'autostart_close')}
    return state._closure_completed


def verify_enrolled(ledger):
    """Shared legacy verify/wallet-verify consumer; no campaign means no change."""
    from contextlib import nullcontext
    from weather.market.lfc_campaign_guard import account_lease, account_owned
    from weather.market.lfc_campaign_state import AccountState
    from weather.market.lfc_ledger import Ledger
    if ledger.enrollment is None:
        return
    maker = ledger.rows[0]['maker_address']
    with nullcontext() if account_owned(maker) else account_lease(maker):
        fresh = Ledger.open(ledger.path, clock=ledger.clock, maker_address=maker)
        state = AccountState(Path(fresh.enrollment['state_root']).parent, fresh)
        state.verify()
        return bool(state._closure_accepted)  # Money may proceed; lost original evidence is still incomplete.
