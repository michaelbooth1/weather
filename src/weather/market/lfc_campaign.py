"""Finite owner-activated campaign dispatcher; dependencies are injected in tests.

This module has no exchange or credential imports. Only the qualified owner task
constructs a production Runtime. A claimed opportunity never runs twice.
"""
from datetime import timedelta

from weather.market.lfc_campaign_control import control_record, active_incidents, stable_id, orders_unproven
from weather.market.lfc_campaign_guard import AdmissionBusy, AdmissionUncertain
from weather.market.lfc_campaign_policy import ZONE
from weather.market.lfc_campaign_state import MoneyContradiction, StateRefused
from weather.market.lfc_campaign_persistence import ClosureRetryPending, retry_failure, retry_labels
from weather.market.lfc_ledger import LedgerUnavailable


class TransientPrecheck(RuntimeError):
    """Unavailable transport/headroom, never contradictory money facts."""


class OwnerStopRequested(RuntimeError):
    pass


class CampaignCoordinator:
    def __init__(self, *, state, runtime, clock, control_root, followup=None, wrapper_launch=None):
        self.state, self.runtime, self.clock, self.control_root = state, runtime, clock, control_root
        self.wrapper_launch = wrapper_launch
        self.policy_binding = {}
        self.record_followups = followup  # Only the qualified owner dispatcher supplies GET capability.
        from weather.market.lfc_campaign_control import observe_latches
        observe_latches(state, runtime, control_root)

    def status(self, phase, attempt=None, *, reason=None, **kwargs):
        reasons = {'IDLE': 'idle', 'DEFERRED': 'transport_deferred', 'MISSED': 'window_missed',
                   'DISABLED': 'campaign_disabled', 'RUNNING': 'running', 'POSTCHECK_PENDING': 'postcheck_pending',
                   'COMPLETE': 'completed', 'INCIDENT': 'account_incident'}
        incidents = active_incidents(self.state, retained_only=phase == 'RETRY_PENDING')
        if incidents:
            attempt = incidents[0]['attempt_id']
            phase, kwargs['incident'] = 'INCIDENT', True
            reason = reason if reason in {'admission_busy', 'hold_retained', 'freeze_missing'} else 'account_incident'
        if phase == 'DEFERRED' and not incidents and getattr(self.runtime, '_orders_open_unproven', None) is None:
            # Local ledger continuity is not a fresh venue account read.
            # This also covers an envelope refusal before pre_go is entered.
            kwargs.update(account_not_read=True, orders_open_unproven=None, incident=None)
        enrollment = self.state.ledger.enrollment or {}
        opaque = stable_id(enrollment.get('state_id', 'unbound'), phase, reason or reasons.get(phase),
                           self.clock.now().astimezone(ZONE).date().isoformat(), attempt, incident=bool(incidents))
        kwargs.setdefault('orders_open_unproven', orders_unproven(self.state, self.runtime))
        row = control_record(self.control_root, opaque, phase=phase,
                              now=self.clock.now(), reason=reason or reasons.get(phase),
                              policy_metadata=self.policy_binding, **kwargs)
        if hasattr(self.runtime, 'notify_control'):
            self.runtime.notify_control(row)
        return row

    def pending(self):
        """Postcheck ticks return here; they cannot fall through to another live entry."""
        from weather.market.lfc_campaign_recovery import recover_empty
        for claim in recover_empty(self.state, self.clock.now()):
            self.status('MISSED', claim['attempt_id'], reason='claim_no_intents', orders_open_unproven=False,
                        research_gaps=True)
        pending = self.state.pending()
        if not pending:
            return False
        for claim in pending:
            self.policy_binding = {key: claim.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')}
            self.policy_binding['sleeve_loss_basis'] = claim.get('sleeve_loss_basis', 'gross')
            self.state.policy_binding = dict(self.policy_binding)
            attempt = claim['attempt_id']
            try:
                result = self.runtime.saved_result(claim)
            except StateRefused:
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
                continue
            if result is None or result.get('unknown_submit') is not False:
                self.state.latch(attempt, 'interrupted_or_ambiguous_attempt', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
                continue
            try:
                proof = self.runtime.postcheck(claim, result)
            except (TransientPrecheck, AdmissionBusy):
                self.status('POSTCHECK_PENDING', attempt, postchecks_pending=True)
                continue
            except StateRefused:
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
                continue
            if proof.get('unknown_submit') is not False:
                self.state.latch(attempt, 'postcheck_unknown_private_proof', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
            elif proof.get('money_contradiction') is True:
                self.state.latch(attempt, 'postcheck_money_contradiction', self.clock.now())
                self.status('INCIDENT', attempt, incident=True, postchecks_pending=True)
            elif (proof.get('money_accounting_complete') is True and proof.get('cleanup_proven') is True and
                  proof.get('unknown_submit') is False and not self.state.incidents()):
                try:
                    sha = self.state.close(claim, proof, self.clock.now())
                except ClosureRetryPending:
                    raise
                except (OSError, LedgerUnavailable) as exc:
                    retry_failure(self.state, attempt, exc)
                outcome = result.get('outcome') or {}
                reason = ('owner_stop' if outcome.get('halt_reason') == 'owner_stop' else
                          'market_local_horizon' if outcome.get('horizon_retirement') else 'completed')
                self.status('COMPLETE', attempt, evidence_sha256=sha,
                            orders_open_unproven=False,
                            research_gaps=proof.get('research_evidence_complete') is not True, reason=reason)
            else:
                self.status('POSTCHECK_PENDING', attempt, postchecks_pending=True,
                            research_gaps=proof.get('research_evidence_complete') is not True)
        return True

    def tick(self, load_policy):
        try:
            return self._tick(load_policy)
        except ClosureRetryPending as exc:
            self.policy_binding = retry_labels(self.state, exc.attempt_id)
            self.status('RETRY_PENDING', exc.attempt_id, reason='retry_pending', postchecks_pending=True)
            return 'RETRY_PENDING'

    def _tick(self, load_policy):
        try:
            from weather.market.lfc_campaign_recovery import recover_empty
            for claim in recover_empty(self.state, self.clock.now()):
                self.status('MISSED', claim['attempt_id'], reason='claim_no_intents', orders_open_unproven=False,
                            research_gaps=True)
            self.state.verify()
        except StateRefused:
            if self.record_followups is not None:
                self.record_followups(load_policy, evidence_only=True)
            self.status('INCIDENT', incident=True, postchecks_pending=True)
            return 'INCIDENT'
        # Capture before pending/incident early returns. Broken current policy
        # cannot prevent immutable pending money postchecks from running.
        policy, policy_error = None, None
        try:
            policy = load_policy()
        except (OSError, ValueError) as exc:
            policy_error = exc
        if policy is not None and policy.f2:
            from weather.market.lfc_f2_freeze import capture, capture_window, verify
            capture(self.state, policy, self.clock.now())
            frozen = verify(self.state, policy=policy)
            if self.clock.now() > capture_window(policy)[1] and (frozen is None or frozen['on_time'] is not True):
                self.status('EVIDENCE_GAP', 'campaign-freeze', reason='freeze_missing', research_gaps=True,
                            orders_open_unproven=False)
        # Incident state is durable and account scoped; readonly finalization is
        # allowed but automatic reconciliation can never close the incident.
        if self.record_followups is not None:
            pending_claim = any(not (self.state.root / 'closed' / (row['attempt_id'] + '.json')).exists()
                                for row in self.state.ledger.autostart_claims)
            self.record_followups(load_policy, evidence_only=pending_claim or bool(active_incidents(self.state)))
        if self.pending():
            return 'POSTCHECKS'
        if self.state.incidents():
            self.status('INCIDENT', incident=True)
            return 'INCIDENT'
        from weather.market.lfc_campaign_idle import prepare, unchanged, remember
        idle_metadata = prepare(self, policy)
        try:
            if idle_metadata is None or not unchanged(self, policy, idle_metadata):
                self.state.require_retained_evidence()
                remember(self, policy, idle_metadata)
        except StateRefused:
            self.status('INCIDENT', incident=True, postchecks_pending=True)
            return 'INCIDENT'
        if policy_error is not None:
            raise policy_error
        if policy is None:
            raise StateRefused('policy_unavailable')
        self.policy_binding = self.state.policy_labels(policy, self.clock.now().astimezone(ZONE).date().isoformat())
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
        last_deferral = 'window_missed'
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
                from weather.market.lfc_campaign_launch import require_launch, LaunchDeferred
                require_launch(self.wrapper_launch, policy, entry)
                require_launch(self.wrapper_launch, current, entry)
                from weather.market.lfc_f2_policy import require_live_loss_basis
                require_live_loss_basis(policy)
                with self.runtime.admission():
                    prepared = self.runtime.pre_go(entry, policy)
                    # No claim before all transient checks pass. Actual go
                    # revalidates time, policy and task state after slow reads.
                    if not entry.permits(self.clock.now()):
                        break
                    latest = load_policy()
                    # Bind the exact tick-start object used by run_session and
                    # authority, including a byte-only A->B->A file edit. Missing
                    # parent authority must defer BEFORE consuming this date.
                    require_launch(self.wrapper_launch, policy, entry)
                    require_launch(self.wrapper_launch, latest, entry)
                    if latest.sha256 != policy.sha256 or not self.runtime.task_enabled():
                        self.status('DEFERRED', entry.id, reason='policy_changed')
                        return 'DEFERRED'
                    claim = self.state.claim(entry, policy, self.clock.now(), prepared=prepared)
                    self.status('RUNNING', claim['attempt_id'])
                    result = None
                    try:
                        result = self.runtime.run_session(claim, entry, policy, prepared)
                        if not any(r['attempt_id'] == claim['attempt_id'] for r in self.state.ledger.autostart_results):
                            self.runtime.save_result(claim, result)
                        if result.get('unknown_submit') is not False:
                            self.state.latch(claim['attempt_id'], 'ambiguous_placement', self.clock.now())
                        self.pending()
                    except ClosureRetryPending:
                        raise  # Completed money proof; retry its persistence, never invent an incident.
                    except BaseException:
                        from weather.market.lfc_campaign_recovery import failure_result, attempt_intents
                        if not any(r['attempt_id'] == claim['attempt_id'] for r in self.state.ledger.autostart_results):
                            self.runtime.save_result(claim, result or failure_result(self.state.ledger, claim, 'postclaim_failure'))
                        if not attempt_intents(self.state.ledger, claim['attempt_id']):
                            self.pending()
                            return 'FAILED_NO_ORDERS'
                        if self.state.ledger.unacknowledged_intents():
                            self.state.latch(claim['attempt_id'], 'claimed_attempt_interrupted', self.clock.now())
                        self.status('INCIDENT', claim['attempt_id'], incident=True, postchecks_pending=True)
                        raise
                    return 'STARTED'
            except LaunchDeferred as exc:
                if claim is not None:
                    raise
                self.status('DEFERRED', entry.id, reason=str(exc))
                return 'DEFERRED'
            except (TransientPrecheck, AdmissionBusy) as exc:
                if claim is not None:
                    # Never turn a post-claim transport failure into permission
                    # for a second order-capable invocation, even in this tick.
                    raise
                reason = ('hold_retained' if isinstance(exc, AdmissionBusy) and str(exc) in
                          {'hold_already_owned', 'hold_retained', 'agent_heavy_hold'} else
                          'admission_busy' if isinstance(exc, AdmissionBusy) else
                          'wallet_cash_below_sleeve' if str(exc) == 'wallet_cash_below_sleeve' else
                          'foreign_open_order' if str(exc) == 'foreign_open_order' else
                          'no_qualifying_band' if str(exc) in {'no_qualifying_band', 'no_qualifying_band_for_policy'} else
                          'transport_deferred')
                self.status('DEFERRED', entry.id, reason=reason)
                last_deferral = reason
                remaining = (entry.end - self.clock.now()).total_seconds()
                if remaining <= 0:
                    break
                self.clock.sleep(min(delay, remaining))
                delay = min(120, delay * 2)
            except AdmissionUncertain as exc:
                self.state.latch('workload-admission', 'ownership_uncertain', self.clock.now())
                self.status('INCIDENT', incident=True, reason='hold_retained' if str(exc) in {
                    'workload_poison', 'workload_marker_ownership_unknown', 'hold_retained_teardown_unproved'} else None)
                return 'INCIDENT'
            except MoneyContradiction:
                self.state.latch('pre-go-money', 'pre_go_money_contradiction', self.clock.now())
                self.status('INCIDENT', incident=True)
                return 'INCIDENT'
            except OwnerStopRequested:
                self.status('DISABLED', entry.id)
                return 'DISABLED'
            except StateRefused as exc:
                if str(exc) == 'disk_free_below_floor':
                    self.status('REFUSED', entry.id, reason='disk_free_below_floor')
                    return 'REFUSED'
                self.status('INCIDENT', incident=True)
                raise
        self.runtime.record_skip(entry, policy, 'window_missed')
        self.status('MISSED', entry.id, reason=last_deferral)
        return 'MISSED'
