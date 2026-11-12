"""Owner task's runtime adapter. Imported only after finite policy admission.

Agents implement and fixture-test this code; they never invoke it on an account.
The scheduled lane explicitly replaces the historical T-24 lead-time contract
with an entry-bound fresh baseline while preserving the original inventory anchor.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import signal
import threading
import time
import uuid

from weather.market.lfc_accounting import inventory_delta, quantity
from weather.market.lfc_campaign import OwnerStopRequested, TransientPrecheck
from weather.market.lfc_campaign_control import control_record, active_incidents, orders_unproven, stable_id, known_live_orders
from weather.market.lfc_campaign_guard import (ExclusiveWorkload, OwnedHold, HOLD_PATH, CAMPAIGN_WORK_LOCK, AdmissionBusy,
                                               workstation_headroom)
from weather.market.lfc_campaign_policy import PROTOCOL, ZONE, load_policy, parse_policy
from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS, account_read_age
from weather.market.lfc_campaign_state import MoneyContradiction, StateRefused
from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_ledger import (Ledger, fetch_account_positions, ledger_path, normalize_positions,
                                       take_baseline, traded_shares, write_baseline)
from weather.market.lfc_pilot import PilotProfile
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.market.mm_stage2_hold import digest

TASK_READBACK_RETRY_SECONDS = 20
TASK_READBACK_TOLERANCE_SECONDS = 60


def transient_read_error(exc):
    from urllib.error import HTTPError, URLError
    from weather.market.mm_account_reads import AmbiguousAccountRead
    status = getattr(getattr(exc, 'response', None), 'status_code', getattr(exc, 'status', getattr(exc, 'code', None)))
    return (isinstance(exc, (TransientPrecheck, TimeoutError, ConnectionError, AmbiguousAccountRead)) or
            isinstance(exc, URLError) and not isinstance(exc, HTTPError) or
            type(status) is int and (status == 429 or 500 <= status <= 599) or
            type(exc).__module__.startswith(('httpx', 'httpcore')) and type(exc).__name__ in {
                'ReadTimeout', 'ConnectTimeout', 'WriteTimeout', 'PoolTimeout', 'ConnectError',
                'ReadError', 'RemoteProtocolError'} or
            isinstance(exc, RuntimeError) and str(exc) in {'positions_unreadable', 'positions_walks_differ',
                'positions_conflict', 'positions_page_budget', 'user_stream_readiness'} or
            isinstance(exc, ValueError) and str(exc).startswith(('capital_rpc_', 'capital_native_', 'capital_activity_')))


class CampaignClock:
    realtime = True
    def now(self):
        return datetime.now(timezone.utc)

    def monotonic(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


class ScheduledProfile(PilotProfile):
    def __init__(self, policy, entry):
        super().__init__()
        self.seconds, self.policy = entry.seconds, policy
        self.local_event_dte = tuple(policy.raw['local_event_dte'])

    def venue_ceiling(self, size):
        super().venue_ceiling(size)
        return quantity(self.policy.terms['per_order_cap']), quantity(self.policy.terms['per_band_cap'])


def claim_labels(policy, claim, entry):
    return ({**{key: claim[key] for key in ('policy_name', 'policy_revision', 'evidence_lane')},
             'sleeve_loss_basis': claim.get('sleeve_loss_basis', 'gross')}
            if policy.f2 else policy.labels(entry.local_date))


def reward_context(fields):
    from weather.market.wallet_reader_security import SecretGuard
    keys = ('API_KEY', 'API_SECRET', 'API_PASSPHRASE', 'WALLET_ADDRESS', 'FUNDER_ADDRESS')
    if not all(key in fields for key in keys) or fields.get('SIGNATURE_TYPE') not in ('2', '3'):
        return None
    selected = {key: fields[key] for key in keys}
    return selected, SecretGuard(selected[key] for key in ('API_KEY', 'API_SECRET', 'API_PASSPHRASE')), int(fields['SIGNATURE_TYPE'])


def selection_account_screen(table, balances):
    from weather.market.lfc_session_driver import neg_risk_screen, allowance_screen
    ok, code, risk, _ = neg_risk_screen(table, table['selected_condition_id'], session0=False)
    if not ok:
        raise StateRefused(code)
    selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
    allowances = (balances.get('collateral_evidence') or {}).get('allowances')
    ok, code, _ = allowance_screen(allowances, selected['quote']['size'], next(iter(risk.values())))
    if not ok:
        raise StateRefused(code)


class ScheduledAuthority:
    protocol = PROTOCOL

    def __init__(self, runtime, claim, entry, policy, prepared):
        self.runtime, self.claim, self.entry, self.policy = runtime, claim, entry, policy
        self.prepared, self.baseline = prepared, prepared['baseline']
        self.pilot_root = runtime.pilot_root
        self.profile = ScheduledProfile(policy, entry)
        self.last_wall, self.last_mono = runtime.clock.now(), runtime.clock.monotonic()
        self.last_control = None
        if policy.f2:
            from weather.market.lfc_f2_breadth import enabled, PROTOCOL as BREADTH_PROTOCOL
            self.protocol = BREADTH_PROTOCOL if enabled(policy) else 'lfc_autostart_v2'

    def check(self, *, starting=False):
        from weather.market.lfc_campaign_launch import require_launch, LaunchDeferred
        bound = getattr(self.runtime, 'wrapper_launch', None)
        if bound is not None:
            try:
                require_launch(bound, self.policy, self.entry)
            except LaunchDeferred as exc:
                from weather.market.mm_stage2_hold import HoldEnd
                raise HoldEnd(str(exc)) from None
        self.runtime.lease.check()
        self.runtime.state.verify()
        now, mono = self.runtime.clock.now(), self.runtime.clock.monotonic()
        elapsed, wall = mono - self.last_mono, (now - self.last_wall).total_seconds()
        # Checkpoints normally occur within 5 s. A delayed loop, suspend or
        # stepped wall clock must clean up; QPC is not a suspend-proof UTC clock.
        if elapsed < 0 or abs(wall - elapsed) > 2 or (elapsed > 15 and not starting):
            self.runtime.state.latch(self.claim['attempt_id'], 'clock_or_resume_uncertain', now)
            raise RuntimeError('clock_or_resume_uncertain')
        self.last_wall, self.last_mono = now, mono
        if self.last_control is None or mono - self.last_control >= 60:
            gaps = False
            if self.runtime.sidecar is not None:
                observation = self.runtime.sidecar.observe()
                gaps = observation.get('research_evidence_complete') is not True
                try:
                    self.runtime.state.save('sidecar-observations/' + uuid.uuid4().hex + '.json', observation)
                except OSError:
                    gaps = True
            control_record(self.runtime.control_root, self.claim['attempt_id'], phase='RUNNING', now=now,
                           research_gaps=gaps, reason='running', orders_open_unproven=orders_unproven(self.runtime.state, self.runtime),
                           orders_live=known_live_orders(self.runtime.state),
                           policy_metadata=claim_labels(self.policy, self.claim, self.entry))
            self.last_control = mono
        if not load_policy(self.runtime.policy_path).raw['enabled'] or not self.task_enabled_at_checkpoint():
            from weather.market.re1_attended import HoldEnd
            raise HoldEnd('owner_campaign_disabled')
        now = self.runtime.clock.now()
        go_read = getattr(self, 'go_read', self.prepared.get('account_read'))
        go_expiry = getattr(self, 'go_expires_utc', self.prepared.get('expires_utc'))
        if starting and (not self.entry.permits(now) or datetime.fromisoformat(go_expiry) < now or
                         account_read_age(go_read, now) > 120):
            raise RuntimeError('go_window_or_freshness_expired')

    def task_enabled_at_checkpoint(self):
        """Before the first intent, wait for proof inside the same durable claim.

        Setup checkpoints also run before any band session exists. A transient
        there must not escape as a failed claimed date. Once an intent exists,
        ordinary paced tolerance owns cleanup; this never retries a placement.
        """
        from weather.market.mm_stage2_hold import HoldEnd
        from weather.market.lfc_campaign_recovery import attempt_intents
        while True:
            since = getattr(self.runtime, '_task_failure_since', None)
            if since is not None and self.runtime.clock.monotonic() - since >= TASK_READBACK_TOLERANCE_SECONDS:
                raise HoldEnd('campaign_task_readback_unavailable')
            try:
                enabled = self.runtime.task_enabled()
                unavailable = getattr(self.runtime, '_task_failures', 0) != 0
            except (TransientPrecheck, HoldEnd) as exc:
                if str(exc) != 'campaign_task_readback_unavailable' and getattr(exc, 'reason', None) != 'campaign_task_readback_unavailable':
                    raise
                enabled, unavailable = None, True
                if attempt_intents(self.runtime.state.ledger, self.claim['attempt_id']):
                    raise
            if not unavailable or attempt_intents(self.runtime.state.ledger, self.claim['attempt_id']):
                return enabled
            since = self.runtime._task_failure_since
            if (self.runtime.clock.monotonic() - since >= TASK_READBACK_TOLERANCE_SECONDS or
                    not self.entry.permits(self.runtime.clock.now())):
                raise HoldEnd('campaign_task_readback_unavailable')
            self.runtime.lease.check()
            self.runtime.state.verify()
            if not load_policy(self.runtime.policy_path).raw['enabled']:
                raise HoldEnd('owner_campaign_disabled')
            status = getattr(self.runtime, '_task_status', None)
            if status is not None:
                status.owner_stop()
                status.progress()
            # No sleep spans a checkpoint or hides a wall/monotonic change.
            if not self.resync():
                raise RuntimeError('clock_or_resume_uncertain')
            self.runtime.clock.sleep(1)

    def refresh_go(self, *, progress=lambda: None):
        """After breadth setup, re-prove money without absorbing wallet changes.

        No band session or intent may exist yet. This can retry reads inside
        the original entry window; it grants no placement retry or new date.
        """
        from weather.market.lfc_f2_breadth import enabled
        if not enabled(self.policy):
            raise StateRefused('go_refresh_protocol')
        ledger = self.runtime.state.ledger
        if ledger.open_sessions() or ledger.unresolved_legs():
            raise StateRefused('go_refresh_after_placement')
        delay = 1
        while self.entry.permits(self.runtime.clock.now()):
            self.runtime.lease.check()
            progress()
            try:
                read = self.runtime.read_account()
                proof = self.runtime.core_proof(ledger, read)
                if (not proof['money_accounting_complete'] or not proof['cleanup_proven'] or
                        proof.get('unknown_submit') is not False or
                        proof.get('capital', {}).get('cash_bridge_complete') is not True):
                    raise TransientPrecheck('setup_money_not_yet_reconciled')
            except Exception as exc:
                if not transient_read_error(exc):
                    raise
                self.runtime.state.save('go-read-gaps/' + uuid.uuid4().hex + '.json', {
                    'at_utc': self.runtime.clock.now().isoformat(), 'exception_type': type(exc).__name__,
                    'attempt_id': self.claim['attempt_id'], 'monetary_placement_retried': False})
                for _ in range(delay):
                    progress()
                    if not self.entry.permits(self.runtime.clock.now()):
                        raise StateRefused('start_window_expired')
                    self.runtime.clock.sleep(1)
                delay = min(15, delay * 2)
                continue
            now = self.runtime.clock.now()
            if not self.entry.permits(now):
                raise StateRefused('start_window_expired')
            self.runtime.state.save('go-refreshes/' + uuid.uuid4().hex + '.json', {
                'attempt_id': self.claim['attempt_id'], 'policy_sha256': self.policy.sha256,
                'source_prepared_file': self.prepared.get('file'),
                'source_prepared_sha256': self.prepared.get('sha256'),
                'read': read, 'proof': proof, 'at_utc': now.isoformat()})
            self.go_read, self.go_proof = read, proof
            self.go_expires_utc = (now + timedelta(seconds=120)).isoformat()
            self.check(starting=True)
            return read
        raise StateRefused('start_window_expired')

    def resync(self):
        """A bounded band cleanup is progress, not a stalled quote loop.

        Keep drift detection; leave a bad clock unchanged for normal cleanup.
        This hook cannot raise while cancellation is finishing.
        """
        try:
            now, mono = self.runtime.clock.now(), self.runtime.clock.monotonic()
            elapsed = mono - self.last_mono
            if elapsed < 0 or abs((now - self.last_wall).total_seconds() - elapsed) > 2:
                return False
            self.last_wall, self.last_mono = now, mono
            return True
        except Exception:
            return False

    @contextmanager
    def owned_admission(self):
        self.check(starting=True)
        yield

    def preflight(self, *, now, commit):
        self.check(starting=True)
        receipt = self.prepared['preflight']
        if receipt['commit'] != commit or receipt['maker_address'].lower() != self.runtime.state.maker.lower():
            raise StateRefused('preflight_binding')
        path = self.runtime.state.root / self.prepared['file']
        if (file_sha(path) != self.prepared['sha256'] or self.claim.get('prepared_file') != self.prepared['file'] or
                self.claim.get('prepared_sha256') != self.prepared['sha256'] or
                self.prepared.get('entry_id') != self.entry.id or self.prepared.get('local_date') != self.entry.local_date or
                self.prepared.get('policy_sha256') != self.policy.sha256 or
                account_read_age(self.prepared['account_read'], now) > 120):
            raise StateRefused('prepared_hash')
        return receipt

    def selection(self):
        self.check(starting=True)
        from weather.operations.live_path_security import validate_contained_regular_file
        path = self.runtime.state.root / self.prepared['preflight']['readiness_directory'] / 'selection.json'
        path = validate_contained_regular_file(self.runtime.state.root, path)
        if file_sha(path) != self.prepared['preflight']['selection_sha256']:
            raise StateRefused('prepared_selection_hash')
        return strict_json(read_bytes(path, 4_000_000))

    def start_gates(self, *, ledger, now, maker_address, open_orders, positions, **_):
        self.check(starting=True)
        self.runtime.state.require_history()
        self.runtime.state.require_retained_evidence()
        refused = []
        if self.runtime.state.incidents():
            refused.append('account_incident_latched')
        if ledger.enrollment is None or ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted:
            refused.append('unresolved_campaign_money')
        if open_orders != []:
            refused.append('account_not_empty')
        if not self.policy.f2 and ledger.counted_sessions() >= self.policy.terms['max_sessions']:
            refused.append('session_cap')
        if not self.policy.f2 and ledger.L() > quantity(self.policy.terms['budget_pusd']):
            refused.append('cap_below_committed_l')
        if str(maker_address).lower() != str(self.baseline['maker_address']).lower():
            refused.append('baseline_account_changed')
        if inventory_delta(ledger, self.baseline, normalize_positions(positions))['changed']:
            refused.append('inventory_changed_after_baseline')
        from weather.market.lfc_cli import session0_passed
        if not session0_passed(ledger, root=self.pilot_root):
            refused.append('session0_not_passed')
        return refused

    def confirmation(self, table, ledger):
        self.check(starting=True)
        # A real account-scoped durable claim replaces only the console phrase.
        saved = self.runtime.state.read(self.runtime.state.root / 'claims' / (self.entry.local_date + '.json'))
        if saved != self.claim or self.runtime.state.incidents():
            raise StateRefused('claim_or_incident_changed')
        chosen = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        quote = chosen['quote']
        reserve = (quantity(quote['reserve_pusd']) if self.policy.f2 else
                   quantity(quote['size']) * sum((quantity(quote[k]) for k in ('yes_buy', 'no_buy')), quantity(0)))
        self.policy.cost_gate(ledger, self.entry, reserve)
        return {'text': PROTOCOL, 'at_utc': self.runtime.clock.now().isoformat(),
                'claim_sha256': digest(self.claim), 'policy_sha256': self.policy.sha256}

    def check_selection(self, table, balances):
        self.check(starting=True)
        from weather.market.lfc_horizon import horizon_allowed
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        if not horizon_allowed(selected, self.runtime.clock.now(), self.policy.raw['local_event_dte']):
            raise StateRefused('market_local_horizon')
        selection_account_screen(table, balances)

    def session_end(self, started, maximum):
        self.check(starting=True)
        return min(started + timedelta(seconds=maximum), self.entry.session_end(started))

    def confirmation_valid(self, table, receipt):
        expected = self.confirmation(table, self.runtime.state.ledger)
        return isinstance(receipt, dict) and all(receipt.get(key) == expected[key]
                                               for key in ('text', 'claim_sha256', 'policy_sha256'))


class Runtime:
    def __init__(self, *, state, pilot_root, policy_path, release, clock, control_root, task_enabled, hold_path=CAMPAIGN_WORK_LOCK, heavy_hold_path=None, wrapper_launch=None):
        self.state, self.pilot_root, self.policy_path = state, Path(pilot_root), Path(policy_path)
        self.release, self.clock, self.control_root = release, clock, Path(control_root)
        self._read_task_enabled = task_enabled
        self.lease = None
        self._task_checked, self._task_value = None, False
        self._task_failures = 0
        self._task_failure_since, self._task_retry_at = None, None
        self._task_status = None
        self.hold_path = Path(hold_path)
        self.heavy_hold_path = Path(HOLD_PATH if heavy_hold_path is None else heavy_hold_path)
        self.sidecar = None
        self.wrapper_launch = wrapper_launch

        from weather.market.lfc_campaign_control import observe_latches
        observe_latches(state, self, self.control_root)

    def notify_control(self, row):
        from weather.market.lfc_campaign_visibility import notify_control
        return notify_control(self, row)

    def write_emergency_result(self, claim):
        # The watcher never writes the money ledger or claims absence of an
        # intent. A hard-exit receipt is explicitly incomplete and create-only.
        target = self.state.root / 'emergency' / (claim['attempt_id'] + '.json')
        if not target.exists():
            write_new(target, {'schema_version': 'lfc_emergency_result_v0.1', 'attempt_id': claim['attempt_id'],
                'state': 'INTERRUPTED', 'reason': 'session_stalled', 'unknown_submit': True,
                'evidence_complete': False, 'inventory_proven': False, 'at_utc': self.clock.now().isoformat()})

    def confirm_funding(self):
        """Owner pre-enable enrollment read; no session/date/order capability."""
        from weather.market.lfc_capital import CapitalRefused
        with self.admission():
            ledger = self.reload_ledger()
            self.state.require_history()
            self.state.require_retained_evidence()
            preparing = getattr(self, 'preparing_f2', False)
            self.preparing_f2 = True
            try:
                for attempt in range(3):
                    try:
                        ledger = self.reload_ledger()
                        proof = self.core_proof(ledger, self.read_account())
                        break
                    except (CapitalRefused, TransientPrecheck) as exc:
                        if str(exc) not in {'f2_anchor_snapshot_pending', 'capital_cash_snapshot_pending'}:
                            raise
                        if attempt == 2:
                            raise TransientPrecheck(str(exc)) from None
                        self.clock.sleep(10)
            finally:
                self.preparing_f2 = preparing
            capital = proof.get('capital') or {}
            if (proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
                    proof.get('unknown_submit') is not False or capital.get('cash_bridge_complete') is not True or
                    self.state.incidents()):
                raise StateRefused('enrollment_funding_unreconciled')
            row = {'funding_native': capital['funding_native'], 'cash_asset': 'pUSD', 'native_decimals': 6,
                   'capital_bridge_complete': True, 'ledger_head_sha256': ledger.previous,
                   'proof': proof, 'observed_at_utc': self.clock.now().isoformat()}
            self.state.save('funding/' + uuid.uuid4().hex + '.json', row)
            return {key: row[key] for key in ('funding_native', 'cash_asset', 'native_decimals', 'capital_bridge_complete')}

    def task_enabled(self):
        from subprocess import TimeoutExpired
        from weather.market.lfc_campaign_release import TaskReadbackUnavailable
        now = self.clock.monotonic()
        if self._task_failures:
            expired = now - self._task_failure_since >= TASK_READBACK_TOLERANCE_SECONDS
            # Before a claim/session there is no stale enabled permission to
            # retain. A later admission probe may establish new fresh proof.
            if expired and not self.state.ledger.open_sessions():
                self._task_failures = 0
                self._task_failure_since, self._task_retry_at = None, None
            else:
                if expired or self._task_failures >= 3 or now < self._task_retry_at:
                    if not self.state.ledger.open_sessions():
                        raise TransientPrecheck('campaign_task_readback_unavailable')
                    if expired or self._task_checked is None:
                        from weather.market.mm_stage2_hold import HoldEnd
                        raise HoldEnd('campaign_task_readback_unavailable')
                    return self._task_value
        if self._task_checked is None or self._task_failures or now - self._task_checked >= 60:
            try:
                value = self._read_task_enabled()
                if type(value) is not bool:
                    raise TaskReadbackUnavailable('invalid')
            except (TaskReadbackUnavailable, TimeoutExpired) as exc:
                if not self._task_failures:
                    self._task_failure_since = now
                self._task_failures += 1
                self._task_retry_at = self.clock.monotonic() + TASK_READBACK_RETRY_SECONDS
                self.task_readback_gap(getattr(exc, 'reason', 'timeout'))
                # Admission never spends a stale proof. A running session may
                # retain its last proven value only inside the fixed window.
                if not self.state.ledger.open_sessions():
                    raise TransientPrecheck('campaign_task_readback_unavailable') from None
                if self._task_checked is None:
                    from weather.market.mm_stage2_hold import HoldEnd
                    raise HoldEnd('campaign_task_readback_unavailable') from None
                return self._task_value
            self._task_value, self._task_checked = value, self.clock.monotonic()
            self._task_failures = 0
            self._task_failure_since, self._task_retry_at = None, None
        return self._task_value

    def task_readback_gap(self, reason):
        row = {'readback_reason': reason, 'consecutive_failures': self._task_failures,
               'at_utc': self.clock.now().isoformat()}
        session = getattr(self._task_status, 'session', None)
        record = getattr(session, 'note_task_readback_gap', None)
        if record is not None:
            record(row)
        else:
            self.state.save('task-readback-gaps/' + uuid.uuid4().hex + '.json',
                            {'event': 'campaign_task_readback_unavailable', **row})

    def reload_ledger(self):
        self.state.ledger = Ledger.open(ledger_path(self.pilot_root), clock=self.clock.now, maker_address=self.state.maker)
        self.state.policy_binding = self.state.policy_binding
        self.state.verify(owner_fault_review=getattr(self, 'owner_fault_review', False))
        return self.state.ledger

    @contextmanager
    def readonly_admission(self):
        """All-slot GET exclusion with no crash-persistent live marker or lease."""
        if self.heavy_hold_path.exists():
            raise AdmissionBusy('agent_heavy_hold')
        identity = self.state.verify(owner_fault_review=True)
        with ExclusiveWorkload(self.state.maker, read_only=True, state_id=identity['state_id']):
            # Do not set self.lease: a recorder can never satisfy live authority.
            yield

    def followup(self, load_current, *, evidence_only=False):
        from weather.market.lfc_f2_followup import maintenance
        try:
            policy = load_current()
        except (OSError, ValueError):
            policy = None
            for row in reversed(self.state.ledger.autostart_claims):
                saved = self.state.read(self.state.root / 'policies' / (row['attempt_id'] + '.json'))
                candidate = parse_policy(saved['policy'])
                if candidate.f2:
                    policy = candidate
                    break
        if policy is not None and policy.f2:
            maintenance(self, policy, evidence_only=evidence_only)

    def followup_due(self, policy):
        from weather.market.lfc_f2_followup import due
        return policy.f2 and due(self, policy)

    @contextmanager
    def admission(self):
        if self.heavy_hold_path.exists():
            raise AdmissionBusy('agent_heavy_hold')
        if self.hold_path.exists():
            raise AdmissionBusy('hold_already_owned')
        with ExclusiveWorkload(self.state.maker) as lease:
            from weather.market.lfc_campaign_workload import WorkloadMarker
            marker = WorkloadMarker(poison_root=lease.poison_root, state_id=self.state.verify(
                                    owner_fault_review=getattr(self, 'owner_fault_review', False))['state_id'],
                                    maker=self.state.maker, policy_metadata=self.state.policy_binding)
            hold = OwnedHold(self.hold_path, policy_metadata=self.state.policy_binding)
            hold.acquire()
            self.lease = lease
            try:
                marker.acquire(hold_sha256=hold.sha256, hold_owner=hold.identity)
                yield
            finally:
                try:
                    # The adapter owns every optional sidecar child. Its stop
                    # proves its job is empty before releasing all-slot exclusion.
                    contained = self.sidecar is None or self.sidecar.stop()
                    if marker.sha256 is not None:
                        marker.release(contained=contained)
                    elif marker.path.exists():
                        from weather.market.lfc_campaign_guard import AdmissionUncertain
                        raise AdmissionUncertain('workload_marker_ownership_unknown')
                    hold.release(contained=contained)
                finally:
                    self.lease = None

    def read_account(self):
        try:
            read = self.account_read_once()
            # Retain every observation, including an early quantity mismatch
            # that a later bounded read explains as propagation delay.
            self.state.save('account-reads/' + uuid.uuid4().hex + '.json',
                            {'read': read, 'read_sha256': digest(read)})
            return read
        except Exception as exc:
            retryable = transient_read_error(exc)
            self.state.save('read-failures/' + uuid.uuid4().hex + '.json', {
                'at_utc': self.clock.now().isoformat(), 'exception_type': type(exc).__name__,
                'retryable_read_gap': retryable, 'monetary_placement_retried': False})
            if retryable:
                raise TransientPrecheck('account_read_unavailable') from None
            raise

    def account_read_once(self):
        """Read-only SDK route, retaining bounded source responses in the runtime.

        The independent LAN reader remains useful owner evidence, not an extra
        required service. F0's v2 positions and guarded exhaustive SDK trades
        supply the core quantity proof here; no field names are guessed.
        """
        from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
        fields, guard = load_owner_credentials('preflight')
        if fields['FUNDER_ADDRESS'].lower() != self.state.maker.lower():
            raise StateRefused('account_changed')
        # Share only the existing read credential subset in memory with R3.
        # No private key, reader token, credential path or file is exported.
        self.reward_read_context = reward_context(fields)
        client = build_client(fields, readonly=True)
        venue = OwnerVenue(client, fields, guard, readonly=True)
        try:
            venue.trades_after = str(int(datetime.fromisoformat(self.state.ledger.rows[0]['recorded_at_utc']).timestamp()))
            from weather.market import lfc_constants as C
            venue.trades_seconds = C.TRADE_READ_SECONDS
            start = self.clock.now()
            values, times = {}, {}
            readers = {'open_orders': venue.open_orders, 'trades': venue.trades,
                       'positions': lambda: fetch_account_positions(self.state.maker),
                       'balances': venue.balances, 'geography': venue.geography}
            for name in ACCOUNT_READ_COMPONENTS:
                observed_start = self.clock.now()
                values[name] = readers[name]()
                times[name] = {'started_at_utc': observed_start.isoformat(),
                               'ended_at_utc': self.clock.now().isoformat()}
            terminal_orders = {}
            for leg in self.state.ledger.unresolved_legs():
                if leg['order_id'] is not None:
                    observed_start = self.clock.now()
                    order = venue.order(leg['order_id'])
                    terminal_orders[leg['order_id']] = {'row': order, 'started_at_utc': observed_start.isoformat(),
                                                       'ended_at_utc': self.clock.now().isoformat()}
            if values['geography'].get('blocked') is not False:
                raise StateRefused('geoblock')
            policy = load_policy(self.policy_path)
            if policy.f2 or any(r['event'] == 'capital_bridge' for r in self.state.ledger.capital_rows):
                from weather.market.lfc_capital_reads import read_activity
                from weather.market.lfc_f2_inventory import activity_start
                activity_since = (activity_start(self.state.ledger, start.isoformat()) if policy.f2 else
                                  int(venue.trades_after))
                values['capital_activity'] = read_activity(self.state.maker, activity_since,
                                      int(self.clock.now().timestamp()))
                if policy.f2:
                    from weather.market.lfc_f2_wallet_reads import bootstrap_scope, require_bootstrap_trades
                    scope = bootstrap_scope(self.state.ledger, values['positions'])
                    if scope is not None:
                        require_bootstrap_trades(self.state.ledger, values['trades'], scope['tokens'])
                        end = values['capital_activity']['scope']['end']
                        values['capital_activity']['bootstrap_scope'] = scope
                        values['capital_activity']['bootstrap_activity'] = read_activity(self.state.maker, scope['start'], end)
                from weather.market.lfc_capital_native import collect
                if policy.f2:
                    from weather.market.lfc_f2_wallet_reads import collect_window
                    collect = collect_window
                values['capital_activity'] = collect(values['capital_activity'], ledger=self.state.ledger)
            return {'schema_version': 'lfc_campaign_account_read_v0.1', 'maker_address': self.state.maker,
                    **self.state.policy_binding,
                    'since': venue.trades_after, 'started_at_utc': start.isoformat(),
                    'ended_at_utc': self.clock.now().isoformat(), 'complete': True,
                    'errors': [], 'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
                    'component_times': times, 'terminal_orders': terminal_orders, **values}
        except (TimeoutError, ConnectionError):
            raise TransientPrecheck('account_transport_unavailable') from None
        finally:
            venue.close()

    def original_baseline(self, ledger):
        policy_path = getattr(self, 'policy_path', None)
        if policy_path is not None and policy_path.is_file() and load_policy(policy_path).f2:
            from weather.market.lfc_capital import CapitalBook
            anchor = CapitalBook(ledger).inventory_anchor
            if anchor is not None:
                return anchor
        # The earliest baseline remains the inventory anchor. Never advance a
        # new baseline over a missing holding or a stale filled quantity.
        rows = [r for r in ledger.baselines if r['label'] == 't40']
        if not rows:
            raise StateRefused('original_baseline_missing')
        row = rows[0]
        path = self.pilot_root / row['file']
        from weather.operations.live_path_security import validate_contained_regular_file
        path = validate_contained_regular_file(self.pilot_root, path)
        if file_sha(path) != row['sha256']:
            raise StateRefused('original_baseline_hash')
        from weather.market.lfc_recording_io import STATE_JSON_LIMIT
        return strict_json(read_bytes(path, STATE_JSON_LIMIT))

    def validate_account_read(self, ledger, read):
        if (read.get('schema_version') != 'lfc_campaign_account_read_v0.1' or read.get('complete') is not True or
                read.get('maker_address', '').lower() != self.state.maker.lower() or
                read.get('since') != str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp())) or
                read.get('scope') != 'account_wide_sdk_trades_and_f0_v2_positions' or read.get('errors') != [] or
                any(not isinstance(read.get(key), list) for key in ('open_orders', 'trades', 'positions')) or
                not isinstance(read.get('balances'), dict) or not isinstance(read.get('geography'), dict) or
                read['geography'].get('blocked') is not False or
                not 0 <= (self.clock.now() - datetime.fromisoformat(read['ended_at_utc'])).total_seconds() <= 120 or
                not datetime.fromisoformat(read['started_at_utc']) <= datetime.fromisoformat(read['ended_at_utc'])):
            raise StateRefused('account_read_binding')

    def core_proof(self, ledger, read, *, loss_basis=None):
        self._orders_open_unproven = True
        self.validate_account_read(ledger, read)
        traded = traded_shares(read['trades'], ledger.our_order_ids())
        if account_read_age(read, self.clock.now()) > 120:
            raise TransientPrecheck('account_read_stale')
        self._orders_open_unproven = read['open_orders'] != [] or bool(ledger.unacknowledged_intents())
        if ledger.unresolved_legs():
            return {'money_accounting_complete': False, 'cleanup_proven': False,
                    'unknown_submit': bool(ledger.unacknowledged_intents()), 'money_contradiction': False,
                    'inventory': {'proven': False}, 'trade_differences': [],
                    'ledger_head_sha256': ledger.previous, 'read_sha256': digest(read),
                    'open_orders': len(read['open_orders'])}
        differences = ledger.trade_mismatches(traded)
        capital = None
        if 'capital_activity' in read:
            from weather.market.lfc_capital_reads import synchronize
            from weather.market.lfc_capital import CapitalRefused
            from weather.market.lfc_capital_consistency import observe, REASONS
            from weather.market.lfc_capital import CapitalBook
            from weather.market.lfc_f2_inventory import between_sessions
            policy_path = getattr(self, 'policy_path', None)
            f2 = policy_path is not None and policy_path.is_file() and load_policy(policy_path).f2
            if f2 and differences:
                return {'money_accounting_complete': False, 'cleanup_proven': read['open_orders'] == [],
                        'unknown_submit': bool(ledger.unacknowledged_intents()), 'money_contradiction': True,
                        'inventory': {'proven': False}, 'trade_differences': differences,
                        'ledger_head_sha256': ledger.previous, 'read_sha256': digest(read),
                        'open_orders': len(read['open_orders'])}
            mode, bridge_allowed = None, True
            if f2 and CapitalBook(ledger).bridge is None:
                from weather.market.lfc_campaign_history import history_refusals
                issues = history_refusals(ledger, self.pilot_root)
                recovering = getattr(self, 'history_recovery_session', None)
                if issues and recovering not in issues:
                    raise StateRefused('f2_anchor_history_unresolved')
                bridge_allowed = not (set(issues) - {recovering})
                mode = 'enrollment'
            elif f2 and getattr(self, 'preparing_f2', False):
                mode = 'session'
            elif f2 and between_sessions(ledger):
                mode = 'idle'
            elif f2:
                # A terminal claim may finish its proof before its closure
                # exists. This cannot absorb changed inventory or open orders.
                mode = 'closing'
            try:
                capital = synchronize(ledger, self.original_baseline(ledger), read,
                    loss_basis=loss_basis, anchor_mode=mode, bridge_allowed=bridge_allowed,
                    **({'owner_fault_review': True} if getattr(self, 'owner_fault_review', False) else {}))
            except CapitalRefused as exc:
                if mode == 'closing' and str(exc) == 'f2_anchor_snapshot_pending':
                    raise TransientPrecheck(str(exc)) from None
                if str(exc) not in REASONS:
                    raise
                observe(self.state, self.clock.now(), reason=str(exc), read_sha256=digest(read))
            observe(self.state, self.clock.now(), read_sha256=digest(read))
        elif any(r['event'] == 'capital_bridge' for r in ledger.capital_rows):
            raise StateRefused('capital_activity_missing')
        inventory = (capital['inventory'] if capital is not None else
                     inventory_delta(ledger, self.original_baseline(ledger), normalize_positions(read['positions'])))
        return {'money_accounting_complete': not differences and not inventory['changed'] and not ledger.unresolved_legs(),
                'ledger_head_sha256': ledger.previous,
                'money_contradiction': bool(differences or inventory['changed']), 'inventory': inventory,
                'trade_differences': differences, 'open_orders': len(read['open_orders']),
                'cleanup_proven': read['open_orders'] == [] and not ledger.unresolved_legs(),
                'unknown_submit': bool(ledger.unacknowledged_intents()), 'read_sha256': digest(read),
                **({} if capital is None else {'capital': capital})}

    def readiness(self, entry, policy, read):
        """Fresh private-stream, heartbeat and latency proof before the claim.

        Scoring, earnings and the optional public sidecar are ancillary. Their
        absence is recorded separately and cannot strand a money-clean account.
        """
        from weather.market.lfc_pilot import LfcPublicBooks
        from weather.market.lfc_fees import require_maker_fee_zero
        from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
        from weather.market.re1_owner_checks import latency
        from weather.market import lfc_constants as C
        fields, guard = load_owner_credentials('preflight')
        if fields['FUNDER_ADDRESS'].lower() != self.state.maker.lower():
            raise StateRefused('account_changed')
        public = LfcPublicBooks()
        if policy.f2:
            from weather.market.lfc_f2_selection import discover
            from weather.market.lfc_capital import CapitalBook
            table = discover(public, policy, now=self.clock.now(), cash=read['balances']['available_collateral'],
                      capital=CapitalBook(self.state.ledger).figures(loss_basis=policy.raw.get('sleeve_loss_basis', 'gross')),
                      held_conditions=sorted(set(
                          r.get('conditionId', '') for r in read['positions'])))
        else:
            table = require_maker_fee_zero(public.selection(
            available_collateral=read['balances']['available_collateral'], treatment=C.TREATMENT,
            ledger=self.state.ledger.figures(), held_conditions=sorted(set(
                r.get('conditionId', '') for r in read['positions'])), local_event_dte=policy.raw['local_event_dte']))
        if not table.get('selected_condition_id'):
            if policy.f2:
                from weather.market.lfc_capital import native
                figures = CapitalBook(self.state.ledger).figures(loss_basis=policy.raw.get('sleeve_loss_basis', 'gross'))
                needed = [native(row['quote']['reserve_pusd'], ceil=True) for row in table['rows'] if row['eligible'] and
                          native(row['quote']['reserve_pusd'], ceil=True) <= figures['headroom_native']]
                segregated = sum(figures[key] for key in ('segregated_profit_native', 'segregated_incentives_native',
                                                         'segregated_external_cash_native')) - figures['retained_gains_offset_native']
                if needed and native(read['balances']['available_collateral']) - segregated < min(needed):
                    raise TransientPrecheck('wallet_cash_below_sleeve')
            raise TransientPrecheck('no_qualifying_band')
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        selection_account_screen(table, read['balances'])
        if policy.f2:
            from weather.market.lfc_f2_selection import band_table
            for cid in table['selected_condition_ids'][1:]:
                selection_account_screen(band_table(table, cid), read['balances'])
        quote = selected['quote']
        reserve = (sum((quantity(r['quote']['reserve_pusd']) for r in table['rows']
                          if r['condition_id'] in table['selected_condition_ids']), quantity(0)) if policy.f2 else
                   quantity(quote['size']) * sum((quantity(quote[k]) for k in ('yes_buy', 'no_buy')), quantity(0)))
        policy.cost_gate(self.state.ledger, entry, reserve)
        if not policy.f2 and (any(quantity(quote[k]) * quantity(quote['size']) > quantity(policy.terms['per_order_cap'])
               for k in ('yes_buy', 'no_buy')) or reserve > quantity(policy.terms['per_band_cap'])):
            raise TransientPrecheck('no_qualifying_band_for_policy')
        directory = self.state.root / 'readiness' / uuid.uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        write_new(directory / 'selection.json', table)
        client = build_client(fields, readonly=True)
        profile = ScheduledProfile(policy, entry)
        venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'],
                           directory=directory, readonly=True, preflight=True,
                           size=profile.size, reserve_cap=profile.venue_ceiling(profile.size)[1], profile=profile)
        timings = {}
        try:
            venue.start()
            for name, fn in [('user_stream', venue.events), ('open_orders', venue.open_orders),
                             ('positions', venue.positions), ('balances', venue.balances),
                             ('geoblock', venue.geography), ('heartbeat', venue.heartbeat)]:
                values = []
                for _ in range(6 if name == 'heartbeat' else 3):
                    if not entry.permits(self.clock.now()) or not self.task_enabled():
                        raise TransientPrecheck('pre_go_window_or_task_changed')
                    started = self.clock.monotonic()
                    result = fn()
                    values.append(self.clock.monotonic() - started)
                    if name == 'open_orders' and result != []:
                        raise StateRefused('account_not_empty')
                    if name == 'geoblock' and result.get('blocked') is not False:
                        raise StateRefused('geoblock')
                    if name == 'heartbeat':
                        self.clock.sleep(5)
                timings[name] = latency(values)
            if max(2, 3 * timings['heartbeat']['p95']) >= 8:
                raise TransientPrecheck('heartbeat_latency_budget')
            return {'timeouts_seconds': {name: max(2, 3 * row['p95']) for name, row in timings.items()},
                    'latency_seconds': timings, 'selection_sha256': file_sha(directory / 'selection.json'),
                    'readiness_directory': directory.relative_to(self.state.root).as_posix(),
                    'sidecar_scope': {'market_id': selected['market_id'], 'event_date': selected['target_date'],
                                      'event_slug': selected['event_slug'],
                                      'condition_ids': selected['event_condition_ids']}}
        except (TimeoutError, ConnectionError):
            raise TransientPrecheck('readiness_transport_unavailable') from None
        except RuntimeError as exc:
            if str(exc) == 'user_stream_readiness':
                raise TransientPrecheck('private_stream_not_ready') from None
            raise
        finally:
            venue.close()

    def pre_go(self, entry, policy):
        self.preparing_f2 = policy.f2
        try:
            return self.pre_go_once(entry, policy)
        except Exception as exc:
            from weather.market.lfc_capital import CapitalRefused
            if isinstance(exc, CapitalRefused) and str(exc) == 'f2_anchor_campaign_inventory':
                raise MoneyContradiction('pre_go_money_contradiction') from None
            if isinstance(exc, CapitalRefused) and str(exc) == 'foreign_open_order':
                raise TransientPrecheck('foreign_open_order') from None
            if isinstance(exc, CapitalRefused) and str(exc).startswith('f2_personal_trade_'):
                raise TransientPrecheck(str(exc)) from None
            if isinstance(exc, CapitalRefused) and str(exc) == 'f2_anchor_snapshot_pending':
                raise TransientPrecheck('f2_anchor_snapshot_pending') from None
            if isinstance(exc, (CapitalRefused, TransientPrecheck)) and str(exc) == 'capital_cash_snapshot_pending':
                raise TransientPrecheck('capital_cash_snapshot_pending') from None
            if isinstance(exc, CapitalRefused) and str(exc) == 'capital_spendable_cash':
                raise TransientPrecheck('wallet_cash_below_sleeve') from None
            if transient_read_error(exc):
                raise TransientPrecheck('pre_go_read_unavailable') from None
            raise
        finally:
            self.preparing_f2 = False

    def pre_go_once(self, entry, policy):
        self.lease.check()
        from weather.market.lfc_session_status import OWNER_STOP_FILE
        # OWNER ONLY: existence is observed, never created/removed by the task.
        if OWNER_STOP_FILE.exists():
            raise OwnerStopRequested('owner_stop')
        resources = workstation_headroom()
        from weather.market.lfc_campaign_visibility import disk_headroom
        resources.update(disk_headroom(self.pilot_root))
        ledger = self.reload_ledger()
        self.state.require_history()
        self.state.require_retained_evidence()
        if ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted or self.state.incidents():
            raise MoneyContradiction('prior_money_unresolved')
        if not policy.f2 and ledger.counted_sessions() >= policy.terms['max_sessions']:
            raise StateRefused('session_cap')
        if not policy.f2 and quantity(policy.terms['budget_pusd']) < ledger.L():
            raise StateRefused('cap_below_committed_l')
        from weather.market.lfc_cli import session0_passed
        if not session0_passed(ledger, root=self.pilot_root):
            raise StateRefused('session0_not_passed')
        read = self.read_account()
        proof = self.core_proof(ledger, read, **({'loss_basis': policy.raw.get('sleeve_loss_basis', 'gross')} if policy.f2 else {}))
        if not proof['money_accounting_complete'] or not proof['cleanup_proven']:
            raise MoneyContradiction('pre_go_money_contradiction')
        readiness = self.readiness(entry, policy, read)
        if account_read_age(read, self.clock.now()) > 60:
            read = self.read_account()
            proof = self.core_proof(ledger, read, **({'loss_basis': policy.raw.get('sleeve_loss_basis', 'gross')} if policy.f2 else {}))
            if not proof['money_accounting_complete'] or not proof['cleanup_proven']:
                raise MoneyContradiction('pre_go_money_contradiction')
        # Explicit protocol change: no T-24 age requirement in this lane. Old
        # manual/F0 gates are unchanged. Bind this exact T-40 file to the attempt.
        baseline = take_baseline(label='t40', now=self.clock.now(), maker_address=self.state.maker,
                                 positions=read['positions'], open_orders=read['open_orders'],
                                 available_collateral=read['balances']['available_collateral'])
        baseline.update(self.state.policy_labels(policy, entry.local_date))
        filename, sha = write_baseline(self.pilot_root, baseline, ledger)
        from weather.market.re1_owner_checks import code_identity
        prepared = {'wrapper_launch': self.wrapper_launch, 'baseline': baseline, 'baseline_file': filename, 'baseline_sha256': sha, 'headroom': resources,
                    'entry_id': entry.id, 'local_date': entry.local_date, 'policy_sha256': policy.sha256,
                    'account_read': read, 'money_proof': proof,
                    'preflight': {'commit': code_identity(), 'maker_address': self.state.maker,
                                  **readiness},
                    'prepared_at_utc': self.clock.now().isoformat(),
                    'expires_utc': (self.clock.now() + timedelta(seconds=120)).isoformat()}
        relative = 'prepared/' + uuid.uuid4().hex + '.json'
        digest_file = self.state.save(relative, prepared)
        return {**prepared, 'file': relative, 'sha256': digest_file}

    def run_session(self, claim, entry, policy, prepared):
        from weather.market.lfc_campaign_launch import require_launch
        require_launch(self.wrapper_launch, policy, entry)
        from weather.market.lfc_cli import _run_live, parser
        from weather.market.lfc_session_status import SessionStatus
        if policy.f2:
            from weather.market.lfc_f2_evidence import F2Status
            SessionStatus = F2Status
        status = SessionStatus(kind='autostart', clock=self.clock.now, monotonic=self.clock.monotonic,
                               policy_metadata=claim_labels(policy, claim, entry))
        self._task_status = status
        status.directory = self.state.root / 'owner-status'
        # STOP remains the existing owner-only fixed path; agents never create
        # it. Tests inject a temporary status/STOP surface before any checkpoint.
        previous = {}
        progress = [time.monotonic()]
        status.progress_hook = lambda: progress.__setitem__(0, time.monotonic())
        stop_watcher = threading.Event()
        def watch_owner_stop():
            # Observation only. The coordinator's normal checkpoint/cleanup is
            # the sole cancellation path; this thread never touches the venue.
            while not stop_watcher.wait(1):
                from weather.market.lfc_campaign_visibility import stalled
                stalled(self, claim, last_progress=progress[0], now_mono=time.monotonic(), phase=status.phase)
                try:
                    status.owner_stop()
                except OSError:
                    status.stop_seen = True
        watcher = None
        def interrupted(_signal, _frame):
            raise KeyboardInterrupt()
        code = 1
        try:
            authority = ScheduledAuthority(self, claim, entry, policy, prepared)
            status.resync_hook = authority.resync
            def progress_check():
                authority.check()
                progress[0] = time.monotonic()
            status.checkpoint_hook = progress_check
            sidecar_policy = policy.raw['sidecar']
            if sidecar_policy is not None and sidecar_policy['enabled']:
                from weather.market.lfc_campaign_sidecar import Sidecar
                self.sidecar = Sidecar(manifest=sidecar_policy['release_manifest'],
                                       output=self.state.root / 'sidecars' / claim['attempt_id'],
                                       scope=prepared['preflight']['sidecar_scope'], started=self.clock.now(),
                                       seconds=entry.seconds, policy_metadata=claim_labels(policy, claim, entry))
            watcher = threading.Thread(target=watch_owner_stop, name='lfc-owner-stop', daemon=True)
            watcher.start()
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                if hasattr(signal, name):
                    number = getattr(signal, name)
                    previous[number] = signal.signal(number, interrupted)
            status.checkpoint()
            if policy.f2:
                from weather.market.lfc_f2_runtime import run_live
                code = run_live(self, authority, status)
            else:
                code = _run_live(parser().parse_args(['live']), status=status, scheduled=authority)
        except BaseException as exc:
            status.failed = True
            status.reason = status.reason or ('owner_interrupt' if isinstance(exc, KeyboardInterrupt) else
                                             'exception_' + type(exc).__name__)
            raise
        finally:
            stop_watcher.set()
            self._task_status = None
            if watcher is not None and watcher.ident is not None:
                watcher.join(timeout=2)
            for number, handler in previous.items():
                signal.signal(number, handler)
            status.phase = 'FINALIZE'
            try:
                outcome = status.finish(success=code == 0)
            except BaseException:
                from weather.market.lfc_campaign_recovery import failure_result
                outcome = failure_result(self.state.ledger, claim, 'status_persistence_failed')['outcome']
            try:
                if self.sidecar is not None and not self.sidecar.stop():
                    self.state.latch(claim['attempt_id'], 'sidecar_teardown_unproved', self.clock.now())
            finally:
                try:
                    result = self.session_result(claim, status, outcome, code)
                except BaseException:
                    from weather.market.lfc_campaign_recovery import failure_result
                    result = failure_result(self.state.ledger, claim, 'postclaim_result_incomplete')
                    result['outcome'] = outcome
                if not any(row['attempt_id'] == claim['attempt_id'] for row in self.state.ledger.autostart_results):
                    self.save_result(claim, result)
            unproven = outcome.get('cancellation_proven') is not True or outcome.get('orders_open_at_exit') != []
            incidents = active_incidents(self.state)
            incident = bool(incidents) or outcome.get('unknown_submit') is not False
            phase = 'INCIDENT' if incident else 'POSTCHECK_PENDING'
            notice_attempt = incidents[0]['attempt_id'] if incidents else claim['attempt_id']
            notice_attempt = stable_id((self.state.ledger.enrollment or {}).get('state_id'), phase, None, None,
                                       notice_attempt, incident=bool(incidents))
            self.notify_control(control_record(self.control_root, notice_attempt, phase=phase, now=self.clock.now(),
                incident=incident, postchecks_pending=True, orders_open_unproven=unproven,
                reason='account_incident' if incident else 'postcheck_pending',
                policy_metadata=claim_labels(policy, claim, entry)))
        return result

    def session_result(self, claim, status, outcome, code):
        session = status.session
        self.reload_ledger()
        from weather.market.lfc_campaign_proof import local_money_proof
        local = (local_money_proof(status.evidence_directory, ledger=self.state.ledger, session_id=status.session_id,
                                   attempt_id=claim['attempt_id'], outcome=outcome)
                 if status.evidence_directory is not None else {'complete': False,
                     'unknown_submit': bool(self.state.ledger.unacknowledged_intents())})
        result = {'exit_code': code, 'session_id': status.session_id, 'outcome': outcome,
                  'private_evidence_directory': (str(Path(status.evidence_directory).relative_to(self.pilot_root))
                                                 if status.evidence_directory is not None else None),
                  **evidence_flags(outcome), 'unknown_submit': (bool(self.state.ledger.unacknowledged_intents()) or
                      session is not None and session.posts != len(session.known)),
                  'local_money_proof': local,
                  'public_coverage': self.sidecar.report if self.sidecar is not None else
                                     {'configured': False, 'research_evidence_complete': False, 'gap': 'not_configured'}}
        return result

    def save_result(self, claim, result):
        original_files = {}
        relative = Path(str(result.get('private_evidence_directory', '')))
        if relative.parts and not relative.is_absolute() and '..' not in relative.parts:
            file_limit = 307  # Retained single-band/non-F2 result contract.
            from weather.operations.live_path_security import validate_contained_regular_file
            directory = self.pilot_root / relative
            paths = [path for name in ('journal.jsonl', 'prediction.json', 'session_end.json', 'attempt.json', 'selection.json')
                     if (path := directory / name).exists()]
            paths += list(directory.glob('submit-*.intent.json')) + list(directory.glob('submit-*.ack.json'))
            if result['outcome'].get('f2_session') is True:
                paths.append(directory / 'f2_manifest.json')
                if 'go_account.json' in result['outcome'].get('evidence_sha256', {}):
                    paths.append(directory / 'go_account.json')
                from weather.market.lfc_f2_evidence import manifest_at, result_file_limit
                file_limit = result_file_limit(self.state.ledger, claim['attempt_id'])
                for band in manifest_at(directory)['bands']:
                    paths += [directory / band['directory'] / name for name in band['evidence_sha256']]
            if len(paths) > file_limit:
                raise StateRefused('private_file_count')
            for path in paths:
                original_files[path.relative_to(directory).as_posix()] = file_sha(validate_contained_regular_file(self.pilot_root, path))
        sha = self.state.save('results/' + claim['attempt_id'] + '.json',
                              {**result, 'private_file_hashes': original_files})
        self.state.ledger.record('autostart_result', attempt_id=claim['attempt_id'], file_sha256=sha)

    def saved_result(self, claim):
        path = self.state.root / 'results' / (claim['attempt_id'] + '.json')
        if not path.exists() and not any(e['attempt_id'] == claim['attempt_id'] for e in self.state.ledger.autostart_results):
            return None
        return self.state.result_anchor(claim['attempt_id'])[0]

    def postcheck(self, claim, result):
        if self.lease is None:
            with self.admission():
                return self.postcheck(claim, result)
        ledger = self.reload_ledger()
        retained, result_sha, local = self.state.retained_result(claim)
        if retained != result:
            self.state.evidence_fault(claim['attempt_id'], artifact='results/postcheck-binding')
            raise StateRefused('private_result_changed')
        if ledger.open_sessions() or ledger.unacknowledged_intents():
            # No adoption and no closing crashed sessions. Only owner recovery
            # may address missing private identities or an interrupted cleanup.
            return {'money_accounting_complete': False, 'cleanup_proven': False, 'unknown_submit': True}
        read = self.read_account()
        # Known acknowledged identities may finish bounded GET accounting. This
        # never adopts an intent, closes a crash or retries a placement.
        self.core_proof(ledger, read)  # Validate account/scope/completeness before any ledger append.
        for leg in list(ledger.unresolved_legs()):
            observed = read.get('terminal_orders', {}).get(leg['order_id'])
            if observed is None:
                continue
            begin, end = (datetime.fromisoformat(observed[k]) for k in ('started_at_utc', 'ended_at_utc'))
            if (begin.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0) or
                    not datetime.fromisoformat(read['started_at_utc']) <= begin <= end <=
                    datetime.fromisoformat(read['ended_at_utc']) or
                    not 0 <= (self.clock.now() - begin).total_seconds() <= 120):
                raise StateRefused('terminal_read_binding')
            ledger.terminal(leg['order_id'], observed['row'], source='autostart_postcheck')
        proof = self.core_proof(ledger, read)
        for _ in range(4):
            if not proof.get('money_contradiction'):
                break
            self.clock.sleep(2)
            read = self.read_account()
            proof = self.core_proof(ledger, read)
        proof.update(research_evidence_complete=result.get('evidence_complete') is True,
                     result_sha256=result_sha, private_evidence_sha256=digest(local),
                     raw_evidence_flags=evidence_flags(result), account_read=read,
                     public_coverage=result.get('public_coverage'))
        public = result.get('public_coverage') or {}
        if (public.get('gap') not in (None, 'not_configured') or public.get('source_gaps') is True or
                public.get('historical_gaps') is True or public.get('configured') is True and
                public.get('research_evidence_complete') is not True):
            proof['research_evidence_complete'] = False
        self.state.save('postchecks/' + uuid.uuid4().hex + '.json', {'attempt_id': claim['attempt_id'], 'proof': proof})
        if result.get('outcome', {}).get('f2_session') is True:
            from weather.market.lfc_f2_economics import publish_supplements
            publish_supplements(self)
        return proof

    def record_skip(self, entry, policy, reason):
        relative = 'skips/' + entry.local_date + '.json'
        if not (self.state.root / relative).exists():
            self.state.save(relative, {'local_date': entry.local_date, 'entry_id': entry.id,
                                      'policy_sha256': policy.sha256, 'reason': reason,
                                      'at_utc': self.clock.now().isoformat()})
