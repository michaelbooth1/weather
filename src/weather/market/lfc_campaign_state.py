"""Durable account-scoped claims and incidents. Policy revisions cannot reset it."""
from pathlib import Path
import uuid

from weather.market.lfc_campaign_guard import account_key, require_account
from weather.market.lfc_campaign_incidents import EvidenceArtifactError, latch_occurrence, occurrence_closed
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.market.mm_stage2_hold import digest
from weather.operations.live_path_security import validate_nonreparse_directory, validate_regular_nonreparse_file


STATE_SCHEMA = 'lfc_campaign_state_v0.1'
DEFAULT_STATE_ROOT = Path(r'C:\t\pilot\account-state')


class StateRefused(RuntimeError):
    pass


class MoneyContradiction(StateRefused):
    pass


class AccountState:
    def __init__(self, root, ledger):
        self.root = Path(root) / account_key(ledger.rows[0]['maker_address'])
        self.ledger = ledger
        self.maker = ledger.rows[0]['maker_address']
        self.policy_binding = {'policy_name': None, 'policy_revision': None, 'evidence_lane': None}

    @property
    def policy_binding(self):
        return self._policy_binding

    @policy_binding.setter
    def policy_binding(self, value):
        self._policy_binding = dict(value)
        self.ledger.policy_metadata = dict(value) if value.get('policy_name') is not None else {}

    def read(self, path):
        row = strict_json(read_bytes(validate_regular_nonreparse_file(Path(path).absolute()), 2_000_000))
        if not isinstance(row, dict) or row.get('schema_version') != STATE_SCHEMA:
            raise StateRefused('state_schema')
        return row

    def save(self, relative, fields):
        require_account(self.maker)
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise StateRefused('state_path_escape')
        validate_nonreparse_directory(self.root.absolute())
        path = self.root / relative
        current = self.root
        for part in relative.parts[:-1]:
            current = current / part
            current.mkdir(exist_ok=True)
            validate_nonreparse_directory(current.absolute())
        write_new(path, {'schema_version': STATE_SCHEMA, **self.policy_binding, **fields})
        return file_sha(path)

    def enroll(self, now):
        """Owner-run enrollment only, after the frozen F0 session is closed.

        A partial enrollment refuses; re-registration never creates a new account
        history. Old ledger readers reject the explicit protocol-version event.
        """
        require_account(self.maker)
        if self.ledger.enrollment is not None or self.root.exists():
            raise StateRefused('already_or_partially_enrolled')
        if self.ledger.open_sessions() or self.ledger.unresolved_legs() or self.ledger.halted:
            raise StateRefused('enrollment_unresolved_money')
        self.require_history()
        from weather.market.lfc_campaign_history import history_manifest
        retained_history = history_manifest(self.ledger, self.ledger.path.parent)
        self.root.mkdir(parents=True, exist_ok=False)
        validate_nonreparse_directory(self.root.absolute())
        row = {'account': str(self.maker).lower(), 'genesis_sha256': self.ledger.row_sha256(0),
               'ledger_path': str(self.ledger.path.resolve()), 'state_id': uuid.uuid4().hex,
               'historical_private_evidence': retained_history,
               'enrolled_at_utc': now.isoformat(), 'previous_ledger_sha256': self.ledger.previous}
        sha = self.save('identity.json', row)
        self.ledger.record('autostart_enroll', state_id=row['state_id'], identity_sha256=sha,
                           state_root=str(self.root.resolve()), protocol='lfc_autostart_v1')
        return sha

    def require_history(self):
        from weather.market.lfc_campaign_history import history_refusals
        artifact = 'history/identity.json'
        try:
            if self.ledger.enrollment is not None:
                identity = self.read(self.root / 'identity.json')
                from weather.operations.live_path_security import validate_contained_regular_file
                originals = identity['historical_private_evidence']
                if not isinstance(originals, dict):
                    raise ValueError('history_manifest')
                for name, sha in originals.items():
                    artifact = 'history/' + Path(name).as_posix()
                    if file_sha(validate_contained_regular_file(self.ledger.path.parent,
                            self.ledger.path.parent / name)) != sha:
                        raise ValueError('history_original_changed')
            artifact = 'history/recovery-proof'
            refused = history_refusals(self.ledger, self.ledger.path.parent)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            if self.ledger.enrollment is not None:
                self.evidence_fault('legacy-history', artifact=artifact)
            raise StateRefused('historical_recovery_evidence_fault') from None
        if refused:
            if self.ledger.enrollment is not None:
                self.evidence_fault('legacy-history', artifact='history/money-proof')
            raise StateRefused('historical_money_ambiguity_requires_owner_recovery')

    def verify(self):
        validate_nonreparse_directory(self.root.absolute())
        row = self.read(self.root / 'identity.json')
        event = self.ledger.enrollment
        if (event is None or event['identity_sha256'] != file_sha(self.root / 'identity.json') or
                row['state_id'] != event['state_id'] or row['account'] != str(self.maker).lower() or
                row['genesis_sha256'] != self.ledger.row_sha256(0) or
                row['previous_ledger_sha256'] != event['previous_sha256'] or
                Path(row['ledger_path']).resolve() != self.ledger.path.resolve() or
                Path(event['state_root']).resolve() != self.root.resolve()):
            raise StateRefused('enrollment_continuity')
        for event in self.ledger.autostart_claims:
            claim_path = self.root / 'claims' / (event['local_date'] + '.json')
            if file_sha(claim_path) != event['file_sha256']:
                raise StateRefused('claim_continuity')
            claim = self.read(claim_path)
            if claim.get('ledger_sha256') != event['previous_sha256']:
                raise StateRefused('claim_ledger_continuity')
            policy_path = self.root / 'policies' / (claim['attempt_id'] + '.json')
            if file_sha(policy_path) != claim.get('policy_snapshot_sha256'):
                raise StateRefused('policy_snapshot_continuity')
            policy = self.read(policy_path)
            if digest(policy.get('policy')) != claim['policy_sha256'] or policy.get('sha256') != claim['policy_sha256']:
                raise StateRefused('policy_snapshot_continuity')
            prepared_file, prepared_sha = claim.get('prepared_file'), claim.get('prepared_sha256')
            if prepared_file is not None or prepared_sha is not None:
                relative = Path(str(prepared_file))
                if relative.is_absolute() or '..' in relative.parts or file_sha(self.root / relative) != prepared_sha:
                    raise StateRefused('prepared_receipt_continuity')
        for event in self.ledger.autostart_incidents:
            path = self.root / 'incidents' / (event['attempt_id'] + '.json')
            if file_sha(path) != event['file_sha256']:
                raise StateRefused('incident_continuity')
        for event in list(self.ledger.autostart_results):
            self.result_anchor(event['attempt_id'])
        chain = {self.ledger.row_sha256(i) for i in range(len(self.ledger.rows))}
        for path in (self.root / 'closed').glob('*.json'):
            closed = self.read(path)
            if (not isinstance(closed.get('proof'), dict) or closed['proof'].get('ledger_head_sha256') not in chain or
                    closed.get('proof_sha256') != digest(closed['proof'])):
                raise StateRefused('closeout_ledger_continuity')
        from weather.market.lfc_f2_freeze import verify
        verify(self)
        return row

    def evidence_fault(self, attempt, *, artifact='private-evidence'):
        """Persist a sticky fault even when ordinary verification is now failing."""
        return latch_occurrence(self, attempt, 'private_evidence_fault', artifact, self.ledger.clock())

    def policy_labels(self, policy, local_date):
        from weather.market.lfc_f2_freeze import labels
        return labels(self, policy, local_date)

    def result_anchor(self, attempt):
        events = [r for r in self.ledger.autostart_results if r['attempt_id'] == attempt]
        path = self.root / 'results' / (attempt + '.json')
        try:
            if len(events) != 1 or file_sha(path) != events[0]['file_sha256']:
                raise ValueError('result_not_anchored')
            return self.read(path), events[0]['file_sha256']
        except (OSError, ValueError, RuntimeError):
            self.evidence_fault(attempt, artifact='results/' + attempt + '.json')
            raise StateRefused('private_result_evidence_fault') from None

    def retained_result(self, claim):
        from weather.market.lfc_campaign_proof import local_money_proof
        result, sha = self.result_anchor(claim['attempt_id'])
        relative = Path(str(result.get('private_evidence_directory', '')))
        try:
            if not relative.parts or relative.is_absolute() or '..' in relative.parts:
                raise ValueError('private_evidence_path')
            self.result_original_hashes(result, relative)
            local = local_money_proof(self.ledger.path.parent / relative, ledger=self.ledger,
                                      session_id=result['session_id'], attempt_id=claim['attempt_id'],
                                      outcome=result['outcome'])
            if local.get('complete') is not True or local != result.get('local_money_proof'):
                raise ValueError('private_evidence_changed')
            return result, sha, local
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.evidence_fault(claim['attempt_id'], artifact=getattr(exc, 'artifact', 'private-proof'))
            raise StateRefused('retained_private_evidence_fault') from None

    def result_original_hashes(self, result, relative):
        from weather.operations.live_path_security import validate_contained_regular_file
        hashes = result['private_file_hashes']
        if not isinstance(hashes, dict) or not {'journal.jsonl', 'prediction.json', 'session_end.json'} <= hashes.keys():
            raise ValueError('private_original_hashes_missing')
        expected = {}
        for declared in (result['outcome']['evidence_sha256'], result.get('local_money_proof', {}).get('evidence_sha256', {})):
            if not isinstance(declared, dict):
                raise ValueError('private_original_hashes_schema')
            for name, sha in declared.items():
                if name in expected and expected[name] != sha:
                    raise ValueError('private_original_hashes_conflict')
                expected[name] = sha
        if any(hashes.get(name) != sha for name, sha in expected.items()):
            raise ValueError('private_original_hashes_conflict')
        for name, sha in hashes.items():
            parts = Path(name).parts
            f2_name = (result['outcome'].get('f2_session') is True and len(parts) == 2 and
                       parts[0] in ('band-1', 'band-2') and parts[1] not in ('.', '..'))
            if Path(name).name != name and not f2_name:
                raise ValueError('private_original_name')
            try:
                if file_sha(validate_contained_regular_file(self.ledger.path.parent,
                        self.ledger.path.parent / relative / name)) != sha:
                    raise ValueError('private_original_hash_changed')
            except (OSError, ValueError, RuntimeError):
                raise EvidenceArtifactError('private/' + name) from None
        return hashes

    def require_retained_evidence(self):
        for claim in self.claims():
            path = self.root / 'closed' / (claim['attempt_id'] + '.json')
            if not path.exists():
                continue
            has_session = any(s['start'].get('autostart_attempt_id') == claim['attempt_id']
                              for s in self.ledger.sessions.values())
            if has_session or any(e['attempt_id'] == claim['attempt_id'] for e in self.ledger.autostart_results):
                proof = self.read(path)['proof']
                if proof.get('authority') == 'owner_recovery':
                    self.owner_close_binding(claim, proof)
                    continue
                _, sha, local = self.retained_result(claim)
                if proof.get('result_sha256') != sha or proof.get('private_evidence_sha256') != digest(local):
                    self.evidence_fault(claim['attempt_id'], artifact='closed/private-proof-binding')
                    raise StateRefused('closed_private_evidence_binding')

    def owner_result_binding(self, claim):
        """Only retained originals, never an inferred automatic clean result."""
        from weather.market.lfc_campaign_proof import owner_originals
        result, sha = self.result_anchor(claim['attempt_id'])
        try:
            relative = Path(str(result.get('private_evidence_directory', '')))
            if not relative.parts or relative.is_absolute() or '..' in relative.parts:
                raise ValueError('owner_original_path')
            hashes = self.result_original_hashes(result, relative)
            outcome = {**result['outcome'], 'evidence_sha256': {**result['outcome']['evidence_sha256'], **hashes}}
            binding = owner_originals(self.ledger.path.parent / relative, ledger=self.ledger,
                                      session_id=result['session_id'], attempt_id=claim['attempt_id'], outcome=outcome)
            return {**binding, 'result_sha256': sha}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.evidence_fault(claim['attempt_id'], artifact=getattr(exc, 'artifact', 'owner/private-proof'))
            raise StateRefused('owner_original_evidence_fault') from None

    def owner_close_binding(self, claim, proof):
        try:
            relative = Path(proof['owner_closure_file'])
            if len(relative.parts) != 2 or relative.parts[0] != 'owner-closures' or relative.suffix != '.json':
                raise ValueError('owner_closure_path')
            path = self.root / relative
            closure = self.read(path)
            binding = self.owner_result_binding(claim)
            if (file_sha(path) != proof.get('owner_closure_sha256') or
                    closure.get('authority') != 'owner_recovery' or
                    closure.get('incident_sha256') != file_sha(self.root / 'incidents' / relative.name) or
                    closure.get('bindings', {}).get(claim['attempt_id']) != binding or
                    proof.get('result_sha256') != binding['result_sha256'] or
                    proof.get('private_evidence_sha256') != digest(binding) or
                    closure.get('proof', {}).get('money_accounting_complete') is not True or
                    closure.get('proof', {}).get('cleanup_proven') is not True or
                    closure.get('proof', {}).get('unknown_submit') is not False or
                    closure['proof'].get('read_sha256') != digest(closure.get('account_read'))):
                raise ValueError('owner_closure_binding')
            return binding
        except StateRefused:
            raise
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            self.evidence_fault(claim['attempt_id'], artifact='owner-closure/' + claim['attempt_id'])
            raise StateRefused('owner_closure_evidence_fault') from None

    def claims(self):
        self.verify()
        return [self.read(path) for path in sorted((self.root / 'claims').glob('*.json'))]

    def skips(self):
        self.verify()
        return [self.read(path) for path in sorted((self.root / 'skips').glob('*.json'))]

    def consumed_dates(self):
        days = {row['local_date'] for row in self.claims() + self.skips()}
        for directory in ('incidents', 'owner-closures'):
            for path in (self.root / directory).glob('*.json'):
                row = self.read(path)
                if row.get('local_date'):
                    days.add(row['local_date'])
        return days

    def incidents(self):
        self.verify()
        pending = []
        for path in sorted((self.root / 'incidents').glob('*.json')):
            row = self.read(path)
            if not occurrence_closed(self, path, row, file_sha(path)):
                pending.append(row)
        return pending

    def latch(self, attempt, reason, now):
        # Safe reason codes only; never serialize exception messages/credentials.
        self.verify()
        return latch_occurrence(self, attempt, reason, 'attempt', now, initial_id=attempt)

    def claim(self, entry, policy, now, *, prepared=None):
        require_account(self.maker)
        self.verify()
        self.require_history()
        self.require_retained_evidence()
        self.policy_binding = self.policy_labels(policy, entry.local_date)
        if self.incidents():
            raise StateRefused('account_incident_latched')
        from weather.market.lfc_campaign_policy import ZONE
        if not entry.permits(now) or now.astimezone(ZONE).date().isoformat() != entry.local_date:
            raise StateRefused('claim_outside_window')
        # Account+date is the stable id, independent of campaign name/revision.
        if entry.local_date in self.consumed_dates():
            raise StateRefused('account_date_consumed')
        if any(s['start'].get('owner_local_date') == entry.local_date and s['legs']
               for s in self.ledger.sessions.values()):
            raise StateRefused('legacy_account_date_consumed')
        for previous in self.claims():
            old = self.read(self.root / 'policies' / (previous['attempt_id'] + '.json'))['policy']
            same_f2_protocol = policy.f2 and old.get('schema_version') == 'lfc_campaign_policy_v0.2'
            if previous.get('policy_name') != policy.raw['policy_name'] and not same_f2_protocol:
                continue
            old_revision = previous.get('policy_revision')
            if type(old_revision) is not int or old_revision > policy.raw['policy_revision']:
                raise StateRefused('policy_revision_regressed')
            keys = ('terms', 'local_event_dte', 'band_limit_session', 'band_limit_concurrent', 'bands_per_event',
                    'start_window_toronto', 'trading_end_toronto', 'max_session_seconds')
            if same_f2_protocol:
                from weather.market.lfc_f2_policy import ECONOMIC_FIELDS
                keys = ECONOMIC_FIELDS
            if old_revision == policy.raw['policy_revision'] and any(old.get(key) != policy.raw.get(key) for key in keys):
                raise StateRefused('economic_policy_change_requires_revision')
        attempt = uuid.uuid4().hex
        snapshot_sha = self.save(f'policies/{attempt}.json', {'policy': policy.raw, 'sha256': policy.sha256})
        claim = {'attempt_id': attempt, 'local_date': entry.local_date, 'entry_id': entry.id,
                 'prepared_file': (prepared or {}).get('file'), 'prepared_sha256': (prepared or {}).get('sha256'),
                 'campaign_id': policy.raw['campaign_id'], 'policy_sha256': policy.sha256,
                 'policy_snapshot_sha256': snapshot_sha, 'claimed_at_utc': now.isoformat(),
                 'ledger_sha256': self.ledger.previous}
        sha = self.save(f'claims/{entry.local_date}.json', claim)
        self.ledger.record('autostart_claim', attempt_id=attempt, local_date=entry.local_date, file_sha256=sha)
        return self.read(self.root / 'claims' / (entry.local_date + '.json'))

    def pending(self):
        result = []
        for row in self.claims():
            path = self.root / 'closed' / (row['attempt_id'] + '.json')
            if not path.exists():
                result.append(row)
                continue
            closed = self.read(path)
            proof = closed.get('proof')
            if (closed.get('attempt_id') != row['attempt_id'] or closed.get('proof_sha256') != digest(proof) or
                    not isinstance(proof, dict) or proof.get('unknown_submit') is not False or
                    proof.get('cleanup_proven') is not True or proof.get('money_accounting_complete') is not True):
                raise StateRefused('closeout_continuity')
        return result

    def close(self, claim, proof, now):
        if self.incidents() or proof.get('unknown_submit') is not False or proof.get('money_accounting_complete') is not True:
            raise StateRefused('cannot_close_ambiguous_attempt')
        if proof.get('cleanup_proven') is not True:
            raise StateRefused('cannot_close_unclean_attempt')
        if (any(s['start'].get('autostart_attempt_id') == claim['attempt_id'] for s in self.ledger.sessions.values()) or
                any(e['attempt_id'] == claim['attempt_id'] for e in self.ledger.autostart_results)):
            if proof.get('authority') == 'owner_recovery':
                self.owner_close_binding(claim, proof)
            else:
                _, sha, local = self.retained_result(claim)
                if proof.get('result_sha256') != sha or proof.get('private_evidence_sha256') != digest(local):
                    raise StateRefused('closeout_private_evidence_binding')
        if proof.get('ledger_head_sha256', self.ledger.previous) != self.ledger.previous:
            raise StateRefused('closeout_proof_stale')
        proof = {**proof, 'ledger_head_sha256': self.ledger.previous}
        return self.save(f"closed/{claim['attempt_id']}.json", {'attempt_id': claim['attempt_id'],
                         'proof': proof, 'proof_sha256': digest(proof), 'closed_at_utc': now.isoformat()})
