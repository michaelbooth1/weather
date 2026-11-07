"""Finite owner-activated campaign dispatcher; dependencies are injected in tests.

This module has no exchange or credential imports. Only the qualified owner task
constructs a production Runtime. A claimed opportunity never runs twice.
"""
from datetime import timedelta
import hashlib
import re
import uuid

from weather.market.lfc_campaign_control import control_record
from weather.market.lfc_campaign_guard import AdmissionBusy, AdmissionUncertain
from weather.market.lfc_campaign_policy import ZONE
from weather.market.lfc_campaign_state import MoneyContradiction, StateRefused


class TransientPrecheck(RuntimeError):
    """Unavailable transport/headroom, never contradictory money facts."""


class OwnerStopRequested(RuntimeError):
    pass


class CampaignCoordinator:
    def __init__(self, *, state, runtime, clock, control_root):
        self.state, self.runtime, self.clock, self.control_root = state, runtime, clock, control_root
        self.policy_binding = {}

    def status(self, phase, attempt=None, *, reason=None, **kwargs):
        reasons = {'IDLE': 'idle', 'DEFERRED': 'transport_deferred', 'MISSED': 'window_missed',
                   'DISABLED': 'campaign_disabled', 'RUNNING': 'running', 'POSTCHECK_PENDING': 'postcheck_pending',
                   'COMPLETE': 'completed', 'INCIDENT': 'account_incident'}
        opaque = (attempt if isinstance(attempt, str) and re.fullmatch(r'[0-9a-f]{32}', attempt) else
                  hashlib.sha256(str(attempt).encode()).hexdigest()[:32] if attempt else uuid.uuid4().hex)
        return control_record(self.control_root, opaque, phase=phase,
                              now=self.clock.now(), reason=reason or reasons.get(phase),
                              policy_metadata=self.policy_binding, **kwargs)

    def pending(self):
        """Postcheck ticks return here; they cannot fall through to another live entry."""
        pending = self.state.pending()
        if not pending:
            return False
        for claim in pending:
            self.policy_binding = {key: claim.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')}
            self.state.policy_binding = dict(self.policy_binding)
            attempt = claim['attempt_id']
            result = self.runtime.saved_result(claim)
            if result is None or result.get('unknown_submit') is not False:
                self.state.latch(attempt, 'interrupted_or_ambiguous_attempt', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
                continue
            try:
                proof = self.runtime.postcheck(claim, result)
            except (TransientPrecheck, AdmissionBusy):
                self.status('POSTCHECK_PENDING', attempt, postchecks_pending=True)
                continue
            if proof.get('unknown_submit') is not False:
                self.state.latch(attempt, 'postcheck_unknown_private_proof', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
            elif proof.get('money_contradiction') is True:
                self.state.latch(attempt, 'postcheck_money_contradiction', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
            elif (proof.get('money_accounting_complete') is True and proof.get('cleanup_proven') is True and
                  proof.get('unknown_submit') is False and not self.state.incidents()):
                sha = self.state.close(claim, proof, self.clock.now())
                outcome = result.get('outcome') or {}
                reason = ('owner_stop' if outcome.get('halt_reason') == 'owner_stop' else
                          'market_local_horizon' if outcome.get('horizon_retirement') else 'completed')
                self.status('COMPLETE', attempt, evidence_sha256=sha,
                            research_gaps=proof.get('research_evidence_complete') is not True, reason=reason)
            else:
                self.status('POSTCHECK_PENDING', attempt, postchecks_pending=True,
                            research_gaps=proof.get('research_evidence_complete') is not True)
        return True

    def tick(self, load_policy):
        self.state.verify()
        # Incident state is durable and account scoped; readonly finalization is
        # allowed but automatic reconciliation can never close the incident.
        if self.pending():
            return 'POSTCHECKS'
        if self.state.incidents():
            self.status('INCIDENT', incident=True)
            return 'INCIDENT'
        policy = load_policy()
        self.policy_binding = policy.labels(self.clock.now().astimezone(ZONE).date().isoformat())
        self.state.policy_binding = dict(self.policy_binding)
        if not policy.raw['enabled'] or not self.runtime.task_enabled():
            self.status('DISABLED')
            return 'DISABLED'
        consumed = self.state.consumed_dates()
        for session in self.state.ledger.sessions.values():
            if session['legs']:
                consumed.add(session['start'].get('owner_local_date'))
        now = self.clock.now()
        for entry in policy.entries:
            if entry.local_date in consumed:
                continue
            if now >= entry.end:
                self.runtime.record_skip(entry, policy, 'window_missed')
                self.status('MISSED', entry.id)
                continue
            if now < entry.start:
                continue
            return self.start(entry, policy, load_policy)
        self.status('IDLE')
        return 'IDLE'

    def start(self, entry, policy, load_policy):
        delay = 5
        while self.clock.now() < entry.end:
            claim = None
            current = load_policy()
            # Policy changes are supported between attempts, not halfway through
            # a pre-go snapshot. Reloading on the next scheduled tick is enough.
            if current.sha256 != policy.sha256:
                self.status('DEFERRED', entry.id, reason='policy_changed')
                return 'DEFERRED'
            if not current.raw['enabled'] or not self.runtime.task_enabled():
                self.status('DISABLED', entry.id)
                return 'DISABLED'
            if not entry.permits(self.clock.now()):
                break
            if self.clock.now().astimezone(ZONE).date().isoformat() != entry.local_date:
                break
            try:
                with self.runtime.admission():
                    prepared = self.runtime.pre_go(entry, policy)
                    # No claim before all transient checks pass. Actual go
                    # revalidates time, policy and task state after slow reads.
                    if not entry.permits(self.clock.now()):
                        break
                    if load_policy().sha256 != policy.sha256 or not self.runtime.task_enabled():
                        self.status('DEFERRED', entry.id, reason='policy_changed')
                        return 'DEFERRED'
                    claim = self.state.claim(entry, policy, self.clock.now(), prepared=prepared)
                    self.status('RUNNING', claim['attempt_id'])
                    try:
                        result = self.runtime.run_session(claim, entry, policy, prepared)
                        self.runtime.save_result(claim, result)
                        if result.get('unknown_submit') is not False:
                            self.state.latch(claim['attempt_id'], 'ambiguous_placement', self.clock.now())
                        self.pending()
                    except BaseException:
                        self.state.latch(claim['attempt_id'], 'claimed_attempt_interrupted', self.clock.now())
                        self.status('INCIDENT', claim['attempt_id'], incident=True, postchecks_pending=True)
                        raise
                    return 'STARTED'
            except (TransientPrecheck, AdmissionBusy):
                if claim is not None:
                    # Never turn a post-claim transport failure into permission
                    # for a second order-capable invocation, even in this tick.
                    raise
                self.status('DEFERRED', entry.id)
                remaining = (entry.end - self.clock.now()).total_seconds()
                if remaining <= 0:
                    break
                self.clock.sleep(min(delay, remaining))
                delay = min(120, delay * 2)
            except AdmissionUncertain:
                self.state.latch(uuid.uuid4().hex, 'ownership_uncertain', self.clock.now())
                self.status('INCIDENT', incident=True)
                return 'INCIDENT'
            except MoneyContradiction:
                self.state.latch(uuid.uuid4().hex, 'pre_go_money_contradiction', self.clock.now())
                self.status('INCIDENT', incident=True)
                return 'INCIDENT'
            except OwnerStopRequested:
                self.status('DISABLED', entry.id)
                return 'DISABLED'
            except StateRefused:
                self.status('INCIDENT', incident=True)
                raise
        self.runtime.record_skip(entry, policy, 'window_missed')
        self.status('MISSED', entry.id)
        return 'MISSED'
