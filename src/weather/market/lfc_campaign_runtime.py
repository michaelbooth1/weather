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
from weather.market.lfc_campaign_control import control_record
from weather.market.lfc_campaign_guard import (ExclusiveWorkload, OwnedHold, HOLD_PATH, AdmissionBusy,
                                               workstation_headroom)
from weather.market.lfc_campaign_policy import PROTOCOL, ZONE, load_policy
from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS, account_read_age
from weather.market.lfc_campaign_state import MoneyContradiction, StateRefused
from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_ledger import (Ledger, fetch_account_positions, ledger_path, normalize_positions,
                                       take_baseline, traded_shares, write_baseline)
from weather.market.lfc_pilot import PilotProfile
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.market.mm_stage2_hold import digest


def transient_read_error(exc):
    from urllib.error import HTTPError, URLError
    from weather.market.mm_account_reads import AmbiguousAccountRead
    status = getattr(getattr(exc, 'response', None), 'status_code', getattr(exc, 'code', None))
    return (isinstance(exc, (TransientPrecheck, TimeoutError, ConnectionError, AmbiguousAccountRead)) or
            isinstance(exc, URLError) and not isinstance(exc, HTTPError) or
            type(status) is int and (status == 429 or 500 <= status <= 599) or
            type(exc).__module__.startswith(('httpx', 'httpcore')) and type(exc).__name__ in {
                'ReadTimeout', 'ConnectTimeout', 'WriteTimeout', 'PoolTimeout', 'ConnectError',
                'ReadError', 'RemoteProtocolError'} or
            isinstance(exc, RuntimeError) and str(exc) in {'positions_unreadable', 'positions_walks_differ',
                'positions_conflict', 'positions_page_budget', 'user_stream_readiness'})


class CampaignClock:
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

    def check(self, *, starting=False):
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
                           research_gaps=gaps, reason='running', policy_metadata=self.policy.labels(self.entry.local_date))
            self.last_control = mono
        if not load_policy(self.runtime.policy_path).raw['enabled'] or not self.runtime.task_enabled():
            from weather.market.re1_attended import HoldEnd
            raise HoldEnd('owner_campaign_disabled')
        if starting and (not self.entry.permits(now) or datetime.fromisoformat(self.prepared['expires_utc']) < now or
                         account_read_age(self.prepared['account_read'], now) > 120):
            raise RuntimeError('go_window_or_freshness_expired')

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
        refused = []
        if ledger.enrollment is None or ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted:
            refused.append('unresolved_campaign_money')
        if open_orders != []:
            refused.append('account_not_empty')
        if ledger.counted_sessions() >= self.policy.terms['max_sessions']:
            refused.append('session_cap')
        if ledger.L() > quantity(self.policy.terms['budget_pusd']):
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
        reserve = quantity(quote['size']) * sum((quantity(quote[k]) for k in ('yes_buy', 'no_buy')), quantity(0))
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
    def __init__(self, *, state, pilot_root, policy_path, release, clock, control_root, task_enabled, hold_path=HOLD_PATH):
        self.state, self.pilot_root, self.policy_path = state, Path(pilot_root), Path(policy_path)
        self.release, self.clock, self.control_root = release, clock, Path(control_root)
        self._read_task_enabled = task_enabled
        self.lease = None
        self._task_checked, self._task_value = None, False
        self.hold_path = Path(hold_path)
        self.sidecar = None

    def task_enabled(self):
        now = self.clock.monotonic()
        if self._task_checked is None or now - self._task_checked >= 5:
            self._task_value = self._read_task_enabled()
            self._task_checked = now
        return self._task_value

    def reload_ledger(self):
        self.state.ledger = Ledger.open(ledger_path(self.pilot_root), clock=self.clock.now, maker_address=self.state.maker)
        self.state.policy_binding = self.state.policy_binding
        self.state.verify()
        return self.state.ledger

    @contextmanager
    def admission(self):
        if self.hold_path.exists():
            raise AdmissionBusy('hold_already_owned')
        with ExclusiveWorkload(self.state.maker) as lease:
            from weather.market.lfc_campaign_workload import WorkloadMarker
            marker = WorkloadMarker(poison_root=lease.poison_root, state_id=self.state.verify()['state_id'],
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
            if values['geography'].get('blocked') is not False:
                raise StateRefused('geoblock')
            return {'schema_version': 'lfc_campaign_account_read_v0.1', 'maker_address': self.state.maker,
                    **self.state.policy_binding,
                    'since': venue.trades_after, 'started_at_utc': start.isoformat(),
                    'ended_at_utc': self.clock.now().isoformat(), 'complete': True,
                    'errors': [], 'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
                    'component_times': times, **values}
        except (TimeoutError, ConnectionError):
            raise TransientPrecheck('account_transport_unavailable') from None
        finally:
            venue.close()

    def original_baseline(self, ledger):
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
        return strict_json(read_bytes(path, 2_000_000))

    def core_proof(self, ledger, read):
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
        traded = traded_shares(read['trades'], ledger.our_order_ids())
        if account_read_age(read, self.clock.now()) > 120:
            raise TransientPrecheck('account_read_stale')
        differences = ledger.trade_mismatches(traded)
        inventory = inventory_delta(ledger, self.original_baseline(ledger), normalize_positions(read['positions']))
        return {'money_accounting_complete': not differences and not inventory['changed'] and not ledger.unresolved_legs(),
                'ledger_head_sha256': ledger.previous,
                'money_contradiction': bool(differences or inventory['changed']), 'inventory': inventory,
                'trade_differences': differences, 'open_orders': len(read['open_orders']),
                'cleanup_proven': read['open_orders'] == [] and not ledger.unresolved_legs(),
                'unknown_submit': bool(ledger.unacknowledged_intents()), 'read_sha256': digest(read)}

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
        table = require_maker_fee_zero(public.selection(
            available_collateral=read['balances']['available_collateral'], treatment=C.TREATMENT,
            ledger=self.state.ledger.figures(), held_conditions=sorted(set(
                r.get('conditionId', '') for r in read['positions'])), local_event_dte=policy.raw['local_event_dte']))
        if not table.get('selected_condition_id'):
            raise TransientPrecheck('no_qualifying_band')
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        selection_account_screen(table, read['balances'])
        quote = selected['quote']
        reserve = quantity(quote['size']) * sum((quantity(quote[k]) for k in ('yes_buy', 'no_buy')), quantity(0))
        policy.cost_gate(self.state.ledger, entry, reserve)
        if any(quantity(quote[k]) * quantity(quote['size']) > quantity(policy.terms['per_order_cap'])
               for k in ('yes_buy', 'no_buy')) or reserve > quantity(policy.terms['per_band_cap']):
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
        try:
            return self.pre_go_once(entry, policy)
        except Exception as exc:
            if transient_read_error(exc):
                raise TransientPrecheck('pre_go_read_unavailable') from None
            raise

    def pre_go_once(self, entry, policy):
        self.lease.check()
        from weather.market.lfc_session_status import OWNER_STOP_FILE
        # OWNER ONLY: existence is observed, never created/removed by the task.
        if OWNER_STOP_FILE.exists():
            raise OwnerStopRequested('owner_stop')
        resources = workstation_headroom()
        ledger = self.reload_ledger()
        if ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted or self.state.incidents():
            raise MoneyContradiction('prior_money_unresolved')
        if ledger.counted_sessions() >= policy.terms['max_sessions']:
            raise StateRefused('session_cap')
        if quantity(policy.terms['budget_pusd']) < ledger.L():
            raise StateRefused('cap_below_committed_l')
        from weather.market.lfc_cli import session0_passed
        if not session0_passed(ledger, root=self.pilot_root):
            raise StateRefused('session0_not_passed')
        read = self.read_account()
        proof = self.core_proof(ledger, read)
        if not proof['money_accounting_complete'] or not proof['cleanup_proven']:
            raise MoneyContradiction('pre_go_money_contradiction')
        readiness = self.readiness(entry, policy, read)
        if account_read_age(read, self.clock.now()) > 90:
            read = self.read_account()
            proof = self.core_proof(ledger, read)
            if not proof['money_accounting_complete'] or not proof['cleanup_proven']:
                raise MoneyContradiction('pre_go_money_contradiction')
        # Explicit protocol change: no T-24 age requirement in this lane. Old
        # manual/F0 gates are unchanged. Bind this exact T-40 file to the attempt.
        baseline = take_baseline(label='t40', now=self.clock.now(), maker_address=self.state.maker,
                                 positions=read['positions'], open_orders=read['open_orders'],
                                 available_collateral=read['balances']['available_collateral'])
        baseline.update(policy.labels(entry.local_date))
        filename, sha = write_baseline(self.pilot_root, baseline, ledger)
        from weather.market.re1_owner_checks import code_identity
        prepared = {'baseline': baseline, 'baseline_file': filename, 'baseline_sha256': sha, 'headroom': resources,
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
        from weather.market.lfc_cli import _run_live, parser
        from weather.market.lfc_session_status import SessionStatus
        status = SessionStatus(kind='autostart', clock=self.clock.now, monotonic=self.clock.monotonic,
                               policy_metadata=policy.labels(entry.local_date))
        status.directory = self.state.root / 'owner-status'
        # STOP remains the existing owner-only fixed path; agents never create
        # it. Tests inject a temporary status/STOP surface before any checkpoint.
        previous = {}
        stop_watcher = threading.Event()
        def watch_owner_stop():
            # Observation only. The coordinator's normal checkpoint/cleanup is
            # the sole cancellation path; this thread never touches the venue.
            while not stop_watcher.wait(1):
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
            status.checkpoint_hook = authority.check
            sidecar_policy = policy.raw['sidecar']
            if sidecar_policy is not None and sidecar_policy['enabled']:
                from weather.market.lfc_campaign_sidecar import Sidecar
                self.sidecar = Sidecar(manifest=sidecar_policy['release_manifest'],
                                       output=self.state.root / 'sidecars' / claim['attempt_id'],
                                       scope=prepared['preflight']['sidecar_scope'], started=self.clock.now(),
                                       seconds=entry.seconds, policy_metadata=policy.labels(entry.local_date))
            watcher = threading.Thread(target=watch_owner_stop, name='lfc-owner-stop', daemon=True)
            watcher.start()
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                if hasattr(signal, name):
                    number = getattr(signal, name)
                    previous[number] = signal.signal(number, interrupted)
            status.checkpoint()
            code = _run_live(parser().parse_args(['live']), status=status, scheduled=authority)
        except BaseException as exc:
            status.failed = True
            status.reason = status.reason or ('owner_interrupt' if isinstance(exc, KeyboardInterrupt) else
                                             'exception_' + type(exc).__name__)
            raise
        finally:
            stop_watcher.set()
            if watcher is not None and watcher.ident is not None:
                watcher.join(timeout=2)
            for number, handler in previous.items():
                signal.signal(number, handler)
            outcome = status.finish(success=code == 0)
            if self.sidecar is not None:
                if not self.sidecar.stop():
                    self.state.latch(claim['attempt_id'], 'sidecar_teardown_unproved', self.clock.now())
        session = status.session
        self.reload_ledger()
        from weather.market.lfc_campaign_proof import local_money_proof
        local = (local_money_proof(status.evidence_directory, ledger=self.state.ledger, session_id=status.session_id,
                                   attempt_id=claim['attempt_id'], outcome=outcome)
                 if status.evidence_directory is not None else {'complete': False, 'unknown_submit': True})
        result = {'exit_code': code, 'session_id': status.session_id, 'outcome': outcome,
                  **evidence_flags(outcome), 'unknown_submit': (session is None or session.posts != len(session.known) or
                                                               local['unknown_submit']),
                  'local_money_proof': local,
                  'public_coverage': self.sidecar.report if self.sidecar is not None else
                                     {'configured': False, 'research_evidence_complete': False, 'gap': 'not_configured'}}
        return result

    def save_result(self, claim, result):
        self.state.save('results/' + claim['attempt_id'] + '.json', result)

    def saved_result(self, claim):
        path = self.state.root / 'results' / (claim['attempt_id'] + '.json')
        return self.state.read(path) if path.exists() else None

    def postcheck(self, claim, result):
        if self.lease is None:
            with self.admission():
                return self.postcheck(claim, result)
        ledger = self.reload_ledger()
        if result.get('local_money_proof', {}).get('complete') is not True:
            return {'money_accounting_complete': False, 'cleanup_proven': False, 'unknown_submit': True}
        if ledger.open_sessions() or ledger.unresolved_legs() or ledger.unacknowledged_intents():
            # No adoption and no closing crashed sessions. Only owner recovery
            # may address missing private identities or an interrupted cleanup.
            return {'money_accounting_complete': False, 'cleanup_proven': False, 'unknown_submit': True}
        read = self.read_account()
        proof = self.core_proof(ledger, read)
        for _ in range(4):
            if not proof.get('money_contradiction'):
                break
            self.clock.sleep(2)
            read = self.read_account()
            proof = self.core_proof(ledger, read)
        proof.update(research_evidence_complete=result.get('evidence_complete') is True,
                     raw_evidence_flags=evidence_flags(result), account_read=read,
                     public_coverage=result.get('public_coverage'))
        if result.get('public_coverage', {}).get('gap') not in (None, 'not_configured'):
            proof['research_evidence_complete'] = False
        self.state.save('postchecks/' + uuid.uuid4().hex + '.json', {'attempt_id': claim['attempt_id'], 'proof': proof})
        return proof

    def record_skip(self, entry, policy, reason):
        relative = 'skips/' + entry.local_date + '.json'
        if not (self.state.root / relative).exists():
            self.state.save(relative, {'local_date': entry.local_date, 'entry_id': entry.id,
                                      'policy_sha256': policy.sha256, 'reason': reason,
                                      'at_utc': self.clock.now().isoformat()})
