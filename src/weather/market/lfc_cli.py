"""Owner commands of the live-fill calibration campaign (python -m weather.market.lfc_cli).

Governed by the owner-signed pre-registration and session-0 spec (2026-10-09, record @ c57a6d07).

    init-ledger                     create the L ledger once (refuses if it exists)
    baseline --label t24|t40        read-only wallet snapshot (positions, open orders, cash) bound into the ledger
    preflight [--session0 --run R]  RE-1 owner preflight under the campaign root and selection (no order); exits
                                    non-zero with any open order on the account (S0-4)
    live [--session0 --run R]       one unattended session (the owner types `go <6 hex>`, then may leave)
    verify                          read-only: our open orders vs foreign ones, L figures, sessions, unresolved legs
    wallet-verify [--since EPOCH]   read-only S0-1/S0-6 through the production-side wallet reader
                                    (weather.market.wallet_reader_client; no venue credential): zero open orders,
                                    L recomputed from venue fills of our order ids vs l_ledger.json to 0.01 pUSD, and
                                    positions outside our tokens unchanged against the T-40 min baseline
    reconcile                       read-only order and trade reads -> ledger; closes a crashed session, writes its
                                    session_end.json and raises the notification (S0 run 0c)
    session0-attest --s0-2-seconds S owner attestation session0/pass.json (once): every required sub-run passed in the
                                    ledger, S0-2 on 0c <= 20 s; bound to the current ledger row (review F-1)
    cancel-ours                     cancel OUR open orders only (ids from the ledger); never a foreign order
    exclusions --output F           band-days of panel_exclusions.jsonl (weather.market.lfc_panel_exclusion)

Session-0 flags (S0 sections 2 and 4): --session0 --run 0a|0b|0c|0d|0e|0f|0g --event-slug SLUG (repeatable: at least
three distinct owner-listed candidate events) --extra-conditions F (the 88a file in force) --shadow-scope F. Every command that reads the ledger
fails closed on missing or unreadable state. Nothing here widens an RE-1 limit: the controller is
weather.market.lfc_pilot.PilotSession.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import signal
import sys

from weather.market import lfc_constants as LFC
from weather.market.lfc_ledger import (SNAPSHOT_FILE, Ledger, LedgerUnavailable, compare_baselines,
                                       fetch_account_positions, latest_baseline, ledger_path, normalize_positions,
                                       take_baseline, traded_shares, write_baseline)
from weather.market.lfc_panel_exclusion import EXCLUSION_FILE, excluded_conditions, load_panel_exclusions
from weather.market.lfc_pilot import (PilotProfile, PilotSession, Session0Books, notify_owner, owner_local_date,
                                      pilot_root, require_zero_fee, session0_table, start_refusals,
                                      write_session_end)
from weather.market.mm_stage2_hold import _order_id, digest, utc, write_new

_LIVE_STARTED = False


def _now():
    return datetime.now(timezone.utc)


def parser():
    result = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = result.add_subparsers(dest='mode', required=True)
    modes.add_parser('init-ledger')
    baseline = modes.add_parser('baseline')
    baseline.add_argument('--label', choices=('t24', 't40'), required=True)
    for name in ('preflight', 'live'):
        mode = modes.add_parser(name)
        mode.add_argument('--session0', action='store_true',
                          help='uncounted session-0 sub-run on a market outside every panel (off by default)')
        mode.add_argument('--run', choices=sorted(LFC.SESSION0_RUNS), help='session 0 only: the sub-run')
        mode.add_argument('--event-slug', action='append', default=[],
                          help='session 0 only: a candidate event slug (repeatable)')
        mode.add_argument('--extra-conditions', type=Path,
                          help="session 0 only: the 88a --extra-conditions file in force (JSON list; may be [])")
        mode.add_argument('--shadow-scope', type=Path,
                          help='session 0 only: the shadow-panel scope (JSON list of condition ids; may be [])')
    modes.add_parser('verify')
    wallet = modes.add_parser('wallet-verify')
    wallet.add_argument('--since', type=int,
                        help='Unix seconds for the trades read (default: the ledger genesis, before any of our orders)')
    modes.add_parser('reconcile')
    attest = modes.add_parser('session0-attest')
    attest.add_argument('--s0-2-seconds', required=True,
                        help='S0-2 measured on run 0c (seconds from the crash to zero open orders); must be <= 20')
    modes.add_parser('cancel-ours')
    exclusions = modes.add_parser('exclusions')
    exclusions.add_argument('--output', type=Path, required=True)
    return result


def check_flags(args):
    if args.session0:
        if args.run is None:
            raise ValueError('session0_requires_run')
        if not args.event_slug or args.extra_conditions is None or args.shadow_scope is None:
            raise ValueError('session0_requires_event_slug_extra_conditions_shadow_scope')
        if len({slug.strip().lower() for slug in args.event_slug}) < LFC.SESSION0_MIN_CANDIDATE_EVENTS:
            # DRAFT clarification C: the owner lists at least three distinct off-panel events so the pick is a pick.
            raise ValueError('session0_requires_three_candidate_events')
    elif args.run or args.event_slug or args.extra_conditions or args.shadow_scope:
        raise ValueError('session0_flags_without_session0')
    return PilotProfile(session0=args.session0, run=args.run)


# ----- pure gates (unit-tested with fakes) -----------------------------------------------------------------------
SESSION0_PASS_SCHEMA = 'lfc_session0_pass_v0.1'
SESSION0_PASS_FILE = Path('session0') / 'pass.json'


def session0_runs_passed(ledger):
    """{run: [session ids]} of session-0 sub-runs that ended with their required reason and a clean cleanup
    (review F-1a; LFC.SESSION0_PASS_REASONS), each with the ledger sequence of its session_end row."""
    ends = {row['session_id']: row['sequence'] for row in ledger.rows if row['event'] == 'session_end'}
    passed = {}
    for session_id, session in ledger.sessions.items():
        start, end = session['start'], session['end']
        run = start.get('session0_run')
        if (start.get('counted') is False and run in LFC.SESSION0_PASS_REASONS and end is not None and
                end.get('reason') in LFC.SESSION0_PASS_REASONS[run] and end.get('cleanup_ok') is True):
            passed.setdefault(run, []).append((session_id, ends[session_id]))
    return passed


def session0_mechanical(ledger):
    """The required sub-runs still missing a clean pass (empty = the mechanical part holds)."""
    passed = session0_runs_passed(ledger)
    return sorted(run for run in LFC.SESSION0_PASS_REASONS if run not in passed)


def session0_attestation(root, ledger):
    """Refusals of the owner attestation session0/pass.json (empty = valid): it names one passing session per
    required sub-run, is bound to a ledger row at or after all of their session_end rows, and records S0-2 measured
    on run 0c at most 20 s (review F-1a/F-1c)."""
    try:
        body = json.loads((Path(root) / SESSION0_PASS_FILE).read_bytes())
    except (OSError, ValueError):
        return ['session0_attestation_missing']
    refusals = []
    passed = session0_runs_passed(ledger)
    try:
        if body.get('schema_version') != SESSION0_PASS_SCHEMA or body.get('kind') != 'lfc_session0_pass':
            refusals.append('session0_attestation_schema')
        sequence = int(body['ledger_sequence'])
        if not 0 <= sequence < len(ledger.rows) or ledger.row_sha256(sequence) != body['ledger_previous_sha256']:
            refusals.append('session0_attestation_not_bound_to_ledger')
        named = body['sessions']
        for run in LFC.SESSION0_PASS_REASONS:
            match = [seq for sid, seq in passed.get(run, []) if sid == named.get(run)]
            if not match or match[0] > sequence:
                refusals.append('session0_attestation_run_' + run)
        seconds = Decimal(str(body['s0_2_seconds_0c']))
        if not seconds.is_finite() or not 0 <= seconds <= LFC.SESSION0_S0_2_MAX_SECONDS:
            refusals.append('session0_s0_2_above_20_seconds')
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        refusals.append('session0_attestation_unreadable')
    return sorted(set(refusals))


def session0_passed(ledger, *, root):
    """Session 1 may not start until session 0 has passed (PR section 9; review F-1): every required sub-run (0a
    fixed_end, 0b foreign_open_order, 0c reconciled_after_crash, 0d heartbeat_stale or order_no_longer_resting, 0e
    l_budget_refused, 0g venue_deadman_cancelled; 0f optional) ended cleanly, and the owner attestation
    session0/pass.json is bound to the ledger with S0-2 on 0c <= 20 s (the binding gate for session 1)."""
    return not session0_mechanical(ledger) and not session0_attestation(root, ledger)


def start_gates(*, ledger, now, profile, root, maker_address, open_orders, positions):
    """Every refusal that must hold before selection; an empty list means the session may proceed."""
    refusals = list(start_refusals(now, session0=profile.session0, seconds=profile.seconds))
    stopped = ledger.stop_reason()
    if stopped:
        refusals.append(stopped)
    if ledger.open_sessions():
        refusals.append('ledger_open_session_needs_reconcile')
    if any(leg['order_id'] for leg in ledger.unresolved_legs()):
        refusals.append('ledger_unresolved_legs_need_reconcile')
    if ledger.unacknowledged_intents():
        # Review F-5: a lost submit ack stays in L until reconcile adopts its venue order and resolves it.
        refusals.append('ledger_unacknowledged_intent_needs_reconcile')
    if not profile.session0:
        if ledger.counted_sessions() >= LFC.MAX_SESSIONS:
            refusals.append('session_cap')
        today = owner_local_date(now).isoformat()
        if any(s['start'].get('counted') and s['legs'] and s['start'].get('owner_local_date') == today
               for s in ledger.sessions.values()):
            refusals.append('local_date_already_used')
        if not session0_passed(ledger, root=root):
            refusals.append('session0_not_passed')
    try:
        t24 = None if profile.session0 else latest_baseline(root, ledger, 't24')
        t40 = latest_baseline(root, ledger, 't40')
    except LedgerUnavailable as exc:
        refusals.append(str(exc))
    else:
        refusals += compare_baselines(t24, t40, now=now, current_positions=positions, current_open_orders=open_orders,
                                      ledger_tokens=ledger.tokens(), maker_address=maker_address)
    return sorted(set(refusals))


def session_identity(ledger, now, *, profile):
    stamp = utc(now).strftime('%Y%m%dT%H%M%SZ')
    if profile.session0:
        return f'S0{profile.run[1]}-{stamp}', {'session_number': 0, 'counted': False}
    number_ = ledger.counted_sessions() + 1
    return f'S{number_}-{stamp}', {'session_number': number_, 'counted': True}


def session_directory(root, session_id, *, profile):
    """Counted: session-<id>. Session 0: session0/<run> (S0 S0-3), session0/<run>-<id> for a repeated sub-run."""
    if not profile.session0:
        return Path(root) / f'session-{session_id}'
    first = Path(root) / 'session0' / profile.run
    return first if not first.exists() else Path(root) / 'session0' / f'{profile.run}-{session_id}'


def classify_open_orders(rows, ledger):
    ours = set(ledger.our_order_ids())
    return ([_order_id(r) for r in rows if _order_id(r) in ours], [_order_id(r) for r in rows if _order_id(r) not in ours])


def finish_session(ledger, session_id, result):
    """Close the session in the ledger; stop-at-100 then halts the campaign for good (PR section 6)."""
    ledger.record('session_end', session_id=session_id, reason=result.get('reason'),
                  cleanup_ok=bool(result.get('cleanup_ok')), fill_seen=result.get('fill_seen'),
                  source=result.get('source', 'session'), L=str(ledger.L()))
    if ledger.stop_reason() == 'l_stop_at_cap' and not ledger.halted:
        ledger.record('halt', reason='l_stop_at_cap', L_filled=str(ledger.L_filled()))
    return ledger.figures()


def session_fills(ledger, session_id):
    return [{'order_id': leg['order_id'], 'size_matched': leg['size_matched'], 'price': leg['price'],
             'status': leg['status']} for leg in ledger.legs.values()
            if leg['session_id'] == session_id and leg['order_id']]


def end_summary(ledger, session_id, *, number, counted, run, reason, failure_type, cleanup_ok, panic, open_rows):
    figures = ledger.figures()
    ours, foreign = classify_open_orders(open_rows, ledger) if isinstance(open_rows, list) else (None, None)
    return {'session_id': session_id, 'number': number, 'counted': counted, 'session0_run': run, 'reason': reason,
            'failure_type': failure_type, 'cleanup_ok': bool(cleanup_ok), 'panic': bool(panic),
            **{k: str(v) for k, v in figures.items()}, 'open_orders': {'ours': ours, 'foreign': foreign},
            'fills': session_fills(ledger, session_id), 'stop_reason': ledger.stop_reason(),
            'ended_at_utc': _now().isoformat()}


def close_out(root, directory, summary, *, notifier=notify_owner):
    """Notification first (its failure is recorded, never raised), then session_end.json with it."""
    summary = dict(summary)
    summary['notification'] = notifier(root, summary)
    if directory is not None:
        try:
            summary['session_end_sha256'] = write_session_end(directory, summary)
        except OSError:
            summary['session_end_sha256'] = None
    return summary


def load_conditions(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    conditions = value.get('conditions') if isinstance(value, dict) else value
    if not isinstance(conditions, list):
        raise ValueError('condition_file_shape')
    return [str(c).lower() for c in conditions], hashlib.sha256(raw).hexdigest()


def held_conditions(root, ledger):
    t40 = latest_baseline(root, ledger, 't40')
    return sorted(set(t40['position_conditions']) | set(c for c in t40['open_order_conditions'] if c))


def _selector(args, *, root, ledger, now_fn=_now):
    """(public books, select(balances)) for the profile; select builds the selection table from public reads."""
    from weather.market.re1_rehearsal import Re1PublicBooks
    if args.session0:
        public = Session0Books()
        extras, extras_sha = load_conditions(args.extra_conditions)
        shadow, shadow_sha = load_conditions(args.shadow_scope)
        path = Path(root) / EXCLUSION_FILE
        panel = excluded_conditions(load_panel_exclusions(path)) if path.exists() else set()
        sources = {'extra_conditions_sha256': extras_sha, 'shadow_scope_sha256': shadow_sha,
                   'panel_exclusions_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}

        def select(balances):
            return require_zero_fee(session0_table(
                public.candidates(sorted(set(args.event_slug))), now=now_fn(), run=args.run,
                available_collateral=balances['available_collateral'], ledger=ledger.figures(),
                excluded_conditions=set(extras) | set(shadow) | panel,
                held_conditions=held_conditions(root, ledger), scope_sources=sources))
        return public, select
    public = Re1PublicBooks()

    def select(balances):
        # Fee rule (review Q4 replacement): the selected market must read fee_rate_bps == 0, else fail closed.
        return require_zero_fee(public.selection(
            available_collateral=balances['available_collateral'], treatment=LFC.TREATMENT,
            ledger=ledger.figures(), held_conditions=held_conditions(root, ledger)))
    return public, select


def confirmation(table, guard, *, profile, ledger, reader=input):
    if not sys.stdin.isatty():
        raise RuntimeError('owner_terminal_required')
    selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
    phrase = 'go ' + digest(table)[:6]
    guard.print({'condition': selected['condition_id'], 'event_slug': selected.get('event_slug'),
                 'quote': selected['quote'], 'selection_sha256': digest(table), 'size': selected['quote']['size'],
                 'session0': profile.session0, 'run': profile.run, 'minutes': profile.seconds // 60,
                 **{k: str(v) for k, v in ledger.figures().items()}, 'budget_pusd': str(LFC.BUDGET_PUSD),
                 'available_collateral': table.get('available_collateral')})
    guard.print('Unattended after this phrase: every hard limit cancels all orders on the account and reconciles; '
                'the exchange dead-man cancels everything if this process hangs or dies. Leave no other order.')
    guard.print('Type: ' + phrase)
    typed = ' '.join(str(reader()).lower().split())
    if typed != phrase:
        raise RuntimeError('owner_confirmation_refused')
    return {'text': phrase, 'at_utc': _now().isoformat()}


# ----- commands --------------------------------------------------------------------------------------------------
def _read_only():
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    fields, guard = load_owner_credentials('reconcile')
    client = build_client(fields, readonly=True)
    return fields, guard, OwnerVenue(client, fields, guard, readonly=True)


def run_init_ledger():
    from weather.market.re1_transport import load_owner_credentials
    fields, guard = load_owner_credentials('reconcile')
    ledger = Ledger.create(ledger_path(pilot_root()), clock=_now, maker_address=fields['FUNDER_ADDRESS'])
    guard.print({'ledger': str(ledger.path), 'L': str(ledger.L()), 'status': 'CREATED'})
    return 0


def run_baseline(label):
    fields, guard, venue = _read_only()
    try:
        root = pilot_root()
        ledger = Ledger.open(ledger_path(root), clock=_now, maker_address=fields['FUNDER_ADDRESS'])
        baseline = take_baseline(label=label, now=_now(), maker_address=fields['FUNDER_ADDRESS'],
                                 positions=fetch_account_positions(fields['FUNDER_ADDRESS']),
                                 open_orders=venue.open_orders(),
                                 available_collateral=venue.balances()['available_collateral'])
        name, sha = write_baseline(root, baseline, ledger)
        guard.print({'baseline': name, 'sha256': sha, 'positions': len(baseline['positions']),
                     'open_orders': len(baseline['open_order_ids']), 'status': 'PASS'
                     if not baseline['open_order_ids'] else 'FAIL_FOREIGN_OPEN_ORDERS'})
        return 0 if not baseline['open_order_ids'] else 1
    finally:
        venue.close()


def run_preflight(args):
    from weather.market.re1_owner_checks import run_preflight as re1_preflight
    profile = check_flags(args)
    root = pilot_root()
    ledger = Ledger.open(ledger_path(root), clock=_now)
    stopped = ledger.stop_reason()
    if stopped:
        raise RuntimeError(stopped)
    from weather.market.re1_attended import SecretGuard
    SecretGuard().print(ledger_state(ledger))  # review F-10: what a live start would refuse on
    _, select = _selector(args, root=root, ledger=ledger)
    return re1_preflight(root=root, select=select, profile=profile)


def ledger_state(ledger):
    return {'open_sessions': ledger.open_sessions(),
            'unresolved_legs': [{k: leg[k] for k in ('session_id', 'intent_key', 'order_id', 'status')}
                                for leg in ledger.unresolved_legs()],
            **{k: str(v) for k, v in ledger.figures().items()}, 'stop_reason': ledger.stop_reason()}


def run_live(args):
    global _LIVE_STARTED
    if _LIVE_STARTED:
        raise RuntimeError('one_session_per_process')
    _LIVE_STARTED = True
    from weather.market.re1_evidence import live_mutex
    from weather.market.re1_owner_checks import clean_preflight, code_identity
    from weather.market.re1_rehearsal import WallClock
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue, geography
    profile = check_flags(args)
    root = pilot_root()
    with live_mutex():
        now = _now()
        early = start_refusals(now, session0=profile.session0, seconds=profile.seconds)
        if early:
            raise RuntimeError(early[0])
        preflight = clean_preflight(root, now=now, commit=code_identity())
        if geography().get('blocked') is not False:
            raise RuntimeError('geoblock')
        fields, guard = load_owner_credentials('live')
        maker = fields['FUNDER_ADDRESS']
        if maker != preflight['maker_address']:
            raise RuntimeError('preflight_account_changed')
        ledger = Ledger.open(ledger_path(root), clock=_now, maker_address=maker)
        timeouts = preflight['timeouts_seconds']
        client = build_client(fields, timeout=max(timeouts.values()))
        venue = session = None
        handlers, session_id, result, directory, numbering = {}, None, None, None, {}
        wallet_reader = OwnerVenue(client, fields, guard, readonly=True, timeouts=timeouts)
        try:
            balances = wallet_reader.balances()
            refusals = start_gates(ledger=ledger, now=_now(), profile=profile, root=root, maker_address=maker,
                                   open_orders=wallet_reader.open_orders(), positions=fetch_account_positions(maker))
            if refusals:
                guard.print({'status': 'REFUSED', 'refusals': refusals})
                return 1
            public, select = _selector(args, root=root, ledger=ledger)
            table = select(balances)
            if not table['selected_condition_id']:
                raise RuntimeError('no_qualifying_band')
            receipt = confirmation(table, guard, profile=profile, ledger=ledger)
            selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
            _, reserve_cap = profile.venue_ceiling(selected['quote']['size'])
            started = _now()
            session_id, numbering = session_identity(ledger, started, profile=profile)
            directory = session_directory(root, session_id, profile=profile)
            directory.mkdir(parents=True, exist_ok=False)
            attempt = {'number': numbering['session_number'], **numbering, 'session_id': session_id,
                       'protocol': LFC.PROTOCOL, 'selection_sha256': digest(table)}
            write_new(directory / 'attempt.json', attempt)
            ledger.record('session_start', session_id=session_id, counted=numbering['counted'],
                          session_number=numbering['session_number'], session0_run=profile.run,
                          owner_local_date=owner_local_date(started).isoformat(),
                          directory=directory.relative_to(root).as_posix(), condition_id=selected['condition_id'],
                          market_id=selected.get('market_id'), event_date=selected.get('target_date'),
                          event_slug=selected.get('event_slug'), selection_sha256=digest(table),
                          **{k: str(v) for k, v in ledger.figures().items()})
            exclusion = None if profile.session0 else {
                'event_slug': selected['event_slug'], 'condition_ids': selected['event_condition_ids'],
                'timezone_name': selected['market_timezone']}
            venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'],
                               directory=directory, timeouts=timeouts, size=selected['quote']['size'],
                               reserve_cap=reserve_cap, profile=profile)
            t40 = latest_baseline(root, ledger, 't40')
            baselines = {'t40_sha256': digest(t40)}
            if not profile.session0:
                baselines['t24_sha256'] = digest(latest_baseline(root, ledger, 't24'))
            session = PilotSession(ledger=ledger, session_id=session_id, profile=profile, root=root,
                                   exclusion=exclusion, baselines=baselines, venue=venue, public=public, table=table,
                                   clock=WallClock(), directory=directory, guard=guard, mode='live',
                                   confirmation=receipt, attempt=attempt)

            def interrupted(_signal, _frame):
                raise KeyboardInterrupt()
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                if hasattr(signal, name):
                    value = getattr(signal, name)
                    handlers[value] = signal.signal(value, interrupted)
            venue.start()
            result = session.run()
            return 0 if result['cleanup_ok'] and result['failure_type'] is None else 1
        finally:
            if session is not None:
                session.cleanup()
            open_rows = None
            if session_id is not None:
                try:
                    open_rows = wallet_reader.open_orders()
                except Exception:
                    open_rows = None
            try:
                if venue is not None:
                    venue.close()
                else:
                    client.close()
            finally:
                for value, handler in handlers.items():
                    signal.signal(value, handler)
            if session_id is not None:
                outcome = {'reason': (result or {}).get('reason', 'exception'),
                           'cleanup_ok': getattr(session, 'cleanup_ok', False),
                           'fill_seen': getattr(session, 'fill_seen', None)}
                close_error = None
                try:
                    finish_session(ledger, session_id, outcome)
                except Exception as exc:
                    close_error = type(exc).__name__
                summary = end_summary(ledger, session_id, number=numbering.get('session_number'),
                                      counted=numbering.get('counted'), run=profile.run, reason=outcome['reason'],
                                      failure_type=(result or {}).get('failure_type'),
                                      cleanup_ok=outcome['cleanup_ok'], panic=not outcome['cleanup_ok'],
                                      open_rows=open_rows)
                if close_error:
                    summary['ledger_close'] = close_error + ': run reconcile'
                close_out(root, directory, summary)


def run_verify():
    fields, guard, venue = _read_only()
    try:
        root = pilot_root()
        ledger = Ledger.open(ledger_path(root), clock=_now, maker_address=fields['FUNDER_ADDRESS'])
        ours, foreign = classify_open_orders(venue.open_orders(), ledger)
        report = {'our_open_orders': ours, 'foreign_open_orders': foreign, **ledger_state(ledger),
                  'counted_sessions': ledger.counted_sessions(),
                  'session0_passed': session0_passed(ledger, root=root),
                  'session0_runs_missing': session0_mechanical(ledger),
                  'session0_attestation': session0_attestation(root, ledger) or 'PASS'}
        report['status'] = 'PASS' if not ours and not foreign and not report['open_sessions'] else 'ATTENTION'
        guard.print(report)
        return 0 if report['status'] == 'PASS' else 1
    finally:
        venue.close()


L_TOLERANCE_PUSD = Decimal('0.01')


def positions_inventory_readable(positions):
    """Review F-4: S0-6 compares SIZES only. OBSERVED passes; a PARTIAL read passes only with a complete inventory
    (inventory_complete is True), no unclassified rows, no top-level errors and a readable size on every row (marks
    and resolved values are irrelevant). Anything else refuses."""
    if not isinstance(positions, dict):
        return False
    status = positions.get('status')
    if status not in ('OBSERVED', 'PARTIAL'):
        return False
    rows = positions.get('positions')
    resolved = positions.get('resolved_positions') or []
    if not isinstance(rows, list) or not isinstance(resolved, list):
        return False
    try:
        for row in rows + resolved:
            if not isinstance(row, dict) or not (row.get('token_id') or row.get('asset') or row.get('asset_id')):
                return False
            if not Decimal(str(row['size'])).is_finite():
                return False
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return False
    if status == 'OBSERVED':
        return True
    return (positions.get('inventory_complete') is True and positions.get('unclassified_positions') == [] and
            not positions.get('errors'))


def wallet_reader_report(ledger, snapshot, t40, *, open_orders, trades, positions):
    """S0-1 and S0-6 (session-0 spec section 5) from the wallet reader's open-orders, trades and positions routes.

    Pure: the reads are passed in (None = the read failed). S0-1: zero open orders account-wide. S0-6: L recomputed
    from the reader's authenticated fills for OUR order ids only, at each leg's limit price, equals the l_ledger.json
    L to 0.01 pUSD (the snapshot must also be the one the verified ledger history produces), and every position
    outside our tokens is unchanged against the T-40 min baseline. Any unreadable input fails that check.
    """
    report = {}
    if isinstance(open_orders, list):
        report['open_orders'] = len(open_orders)
        report['s0_1'] = 'PASS' if not open_orders else 'FAIL'
    else:
        report['open_orders'], report['s0_1'] = 'ERR', 'FAIL'

    ledger_l = ledger.L()
    report['ledger_L'] = str(ledger_l)
    try:
        snapshot_l = Decimal(str(snapshot['L']))
        fresh = snapshot.get('history_last_sha256') == ledger.previous and snapshot_l == ledger_l
    except (TypeError, KeyError, InvalidOperation):
        snapshot_l, fresh = None, False
    report['l_ledger_json_L'] = str(snapshot_l) if snapshot_l is not None else 'ERR'
    fills = trades.get('fills') if isinstance(trades, dict) else None
    if isinstance(fills, list) and all(isinstance(row, dict) for row in fills):
        traded = traded_shares(fills, ledger.our_order_ids())
        venue_l = sum((Decimal(traded.get(oid, '0')) * Decimal(str(ledger.legs[key]['price']))
                       for oid, key in ledger.by_order.items()), Decimal(0))
        report['venue_L'] = str(venue_l)
        difference = abs(venue_l - snapshot_l) if snapshot_l is not None else None
        report['l_difference'] = str(difference) if difference is not None else 'ERR'
        l_ok = fresh and difference is not None and difference <= L_TOLERANCE_PUSD
    else:
        report['venue_L'] = report['l_difference'] = 'ERR'
        l_ok = False
    if not fresh:
        report['l_ledger_json'] = 'stale_or_unreadable'

    tokens = ledger.tokens()
    changed = None
    report['positions_reader_status'] = positions.get('status') if isinstance(positions, dict) else 'ERR'
    if positions_inventory_readable(positions) and t40 is not None:
        try:
            rows = list(positions.get('positions') or []) + list(positions.get('resolved_positions') or [])
            current = {a: Decimal(v) for a, v in normalize_positions(rows).items() if a not in tokens}
            before = {a: Decimal(str(v)) for a, v in t40['positions'].items() if a not in tokens and Decimal(str(v))}
            changed = sorted(a for a in set(current) | set(before) if current.get(a) != before.get(a))
        except (TypeError, ValueError, KeyError, InvalidOperation):
            changed = None
    report['positions_changed_outside_pilot'] = changed if changed is not None else 'ERR'
    report['s0_6'] = 'PASS' if l_ok and changed == [] else 'FAIL'
    report['status'] = 'PASS' if report['s0_1'] == 'PASS' and report['s0_6'] == 'PASS' else 'FAIL'
    return report


def _epoch(value):
    return int(datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp())


def run_wallet_verify(args, *, reader=None, root=None):
    """Read-only: the three wallet-reader routes, the verified ledger, its l_ledger.json and the T-40 baseline."""
    from weather.market.re1_attended import SecretGuard
    if reader is None:
        from weather.market.wallet_reader_client import read_account as reader
    from weather.market.wallet_reader_security import ReaderError
    root = pilot_root() if root is None else Path(root)
    ledger = Ledger.open(ledger_path(root), clock=_now)
    since = args.since if args.since is not None else _epoch(ledger.rows[0]['recorded_at_utc'])
    try:
        snapshot = json.loads((root / SNAPSHOT_FILE).read_bytes())
    except (OSError, ValueError):
        snapshot = None
    try:
        t40 = latest_baseline(root, ledger, 't40')
    except LedgerUnavailable:
        t40 = None

    def read(command, **options):
        try:
            return reader(command, **options)
        except ReaderError:
            return None
    report = wallet_reader_report(ledger, snapshot if isinstance(snapshot, dict) else {}, t40,
                                  open_orders=read('open-orders'), trades=read('trades', since=str(since)),
                                  positions=read('positions', include_resolved=True))
    report['since'] = since
    SecretGuard().print(report)
    return 0 if report['status'] == 'PASS' else 1


def _post_order_ids(journal_path):
    """Order ids from the raw POST /order responses retained in a session journal (review F-5, first source)."""
    ids = []
    try:
        lines = Path(journal_path).read_bytes().splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            return None
        if (row.get('event') == 'sdk_response' and str(row.get('method', '')).upper() == 'POST' and
                str(row.get('path', '')).rstrip('/').endswith('/order') and isinstance(row.get('response'), dict)):
            response = row['response']
            oid = response.get('orderID') or response.get('order_id') or response.get('id')
            if oid:
                ids.append(str(oid))
    return ids


def _intent_request(root, ledger, leg):
    """The persisted submit-N.intent.json request of an intent, checked against the ledger leg; None if unusable."""
    start = ledger.sessions[leg['session_id']]['start']
    if not start.get('directory') or root is None:
        return None, None
    directory = Path(root) / start['directory']
    number_ = leg['intent_key'].rsplit(':', 1)[-1]
    try:
        request = json.loads((directory / f'submit-{number_}.intent.json').read_bytes())['request']
        same = (str(request['token_id']) == leg['token_id'] and Decimal(str(request['price'])) == Decimal(leg['price'])
                and Decimal(str(request['size'])) == Decimal(leg['size']) and request['side'] == 'BUY')
        return (request if same else None), directory
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation):
        return None, directory


def _adoption_match(row, leg, expiration):
    try:
        return (isinstance(row, dict) and str(row.get('asset_id') or row.get('token_id')) == leg['token_id'] and
                str(row.get('side', '')).upper() == 'BUY' and Decimal(str(row['price'])) == Decimal(leg['price']) and
                Decimal(str(row['original_size'])) == Decimal(leg['size']) and
                int(row['expiration']) == int(expiration))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False


def adopt_intents(ledger, venue, *, root, open_rows):
    """Review F-5: an unacknowledged intent stays in L. Adopt it onto the one venue order matching token, side BUY,
    price, original_size and expiration (= session end + 60 s, from the persisted intent request); candidates come
    first from the session journal's raw POST /order responses, then from foreign-looking open orders. Anything
    ambiguous (no usable intent file, an unreadable candidate, two matches, one order matching two intents) adopts
    nothing for that intent: it stays in L and start_gates keeps refusing."""
    pending = ledger.unacknowledged_intents()
    if not pending:
        return [], {}
    known = ledger.our_order_ids()
    reads, matches, refusals = {}, {}, {}

    def read(oid):
        if oid not in reads:
            try:
                reads[oid] = venue.order(oid)
            except Exception as exc:
                reads[oid] = exc
        return reads[oid]
    for leg in pending:
        request, directory = _intent_request(root, ledger, leg)
        if request is None:
            refusals[leg['intent_key']] = 'adoption_intent_request_unusable'
            continue
        journal_ids = _post_order_ids(directory / 'journal.jsonl')
        if journal_ids is None:
            refusals[leg['intent_key']] = 'adoption_journal_unreadable'
            continue
        candidates = [(oid, 'journal_post_response') for oid in journal_ids if oid not in known]
        candidates += [(_order_id(r), 'open_orders') for r in open_rows or [] if _order_id(r) not in known and
                       _adoption_match(r, leg, request['expiration'])]
        found = {}
        for oid, source in candidates:
            row = read(oid)
            if isinstance(row, Exception):
                refusals[leg['intent_key']] = 'adoption_candidate_unreadable'
                break
            if _adoption_match(row, leg, request['expiration']):
                found.setdefault(oid, source)
        else:
            if len(found) == 1:
                matches[leg['intent_key']] = next(iter(found.items()))
            elif found:
                refusals[leg['intent_key']] = 'adoption_ambiguous'
            else:
                refusals[leg['intent_key']] = 'adoption_no_matching_order'
    chosen = [oid for oid, _ in matches.values()]
    adopted = []
    for key, (oid, source) in matches.items():
        if chosen.count(oid) > 1:
            refusals[key] = 'adoption_ambiguous'
            continue
        row = reads[oid]
        ledger.adopt(key, oid, source=source, evidence={k: str(row.get(k)) for k in (
            'asset_id', 'side', 'price', 'original_size', 'expiration', 'status', 'size_matched')})
        adopted.append(oid)
    return adopted, refusals


def reconcile_trades_bounded(ledger, venue, *, attempts=LFC.TRADE_READ_ATTEMPTS,
                             pause=LFC.TRADE_READ_PAUSE_SECONDS, sleep=None):
    """Review F-6: the session's 5 x 2 s re-read at reconcile too. Before a mismatch is recorded, size_matched is
    re-read from the order (a terminal read that differs from the ledger is itself recorded by Ledger.terminal)."""
    import time
    sleep = sleep or time.sleep
    traded, found, before = {}, [], len(ledger.mismatches)
    for attempt in range(attempts):
        traded = traded_shares(venue.trades(), ledger.our_order_ids())
        found = ledger.trade_mismatches(traded)
        if not found:
            return traded, []
        for row in found:
            try:
                order = venue.order(row['order_id'])
            except Exception:
                continue
            ledger.terminal(row['order_id'], order, source='reconcile_trade_check')
        found = ledger.trade_mismatches(traded)
        if not found or len(ledger.mismatches) > before:
            break
        if attempt + 1 < attempts:
            sleep(pause)
    for row in found:
        ledger.record('mismatch', source='reconcile', **row)
    return traded, found


def reconcile_ledger(ledger, venue, *, root=None, sleep=None):
    """Adoption of lost acks, order reads -> terminal rows, venue trades -> mismatches (re-read first); a session
    left open by a crash is closed once none of our orders rests. Returns the report and the open-order rows."""
    if hasattr(venue, '__dict__') and ledger.rows:
        venue.trades_after = str(int(utc(ledger.rows[0]['recorded_at_utc']).timestamp()))
        venue.trades_seconds = LFC.TRADE_READ_SECONDS
    before = len(ledger.mismatches)
    open_rows = venue.open_orders()
    adopted, adoption_refusals = adopt_intents(ledger, venue, root=root, open_rows=open_rows)
    ours, foreign = classify_open_orders(open_rows, ledger)
    resolved = []
    for leg in ledger.unresolved_legs():
        if leg['order_id'] and leg['order_id'] not in ours:
            row = venue.order(leg['order_id'])
            if ledger.terminal(leg['order_id'], row, source='reconcile') is not None:
                resolved.append(leg['order_id'])
    traded, _ = reconcile_trades_bounded(ledger, venue, sleep=sleep)
    mismatches = [{k: m.get(k) for k in ('order_id', 'recorded', 'observed', 'mismatch_kind', 'source')}
                  for m in ledger.mismatches[before:]]
    closed = []
    if not ours and not adoption_refusals:
        for session_id in ledger.open_sessions():
            finish_session(ledger, session_id, {'reason': 'reconciled_after_crash', 'cleanup_ok': True,
                                                'fill_seen': None, 'source': 'reconcile'})
            closed.append(session_id)
    return {'resolved_order_ids': resolved, 'closed_sessions': closed, 'our_open_orders': ours,
            'foreign_open_orders': foreign, 'traded': traded, 'mismatches': mismatches,
            **{k: str(v) for k, v in ledger.figures().items()}, 'stop_reason': ledger.stop_reason(),
            'unacknowledged_intents': [leg['intent_key'] for leg in ledger.unacknowledged_intents()],
            'adopted_order_ids': adopted, 'adoption_refusals': adoption_refusals}, open_rows


def close_crashed(root, ledger, closed, open_rows, *, notifier=notify_owner):
    """session_end.json and the notification for each session the reconcile closed (S0-8: 0c via reconcile)."""
    written = []
    for session_id in closed:
        start = ledger.sessions[session_id]['start']
        directory = Path(root) / start['directory'] if start.get('directory') else None
        summary = end_summary(ledger, session_id, number=start.get('session_number'), counted=start.get('counted'),
                              run=start.get('session0_run'), reason='reconciled_after_crash', failure_type='process_ended',
                              cleanup_ok=True, panic=False, open_rows=open_rows)
        written.append(close_out(root, directory if directory and not (directory / 'session_end.json').exists()
                                 else None, summary, notifier=notifier))
    return written


def run_reconcile():
    fields, guard, venue = _read_only()
    try:
        root = pilot_root()
        ledger = Ledger.open(ledger_path(root), clock=_now, maker_address=fields['FUNDER_ADDRESS'])
        report, open_rows = reconcile_ledger(ledger, venue, root=root)
        close_crashed(root, ledger, report['closed_sessions'], open_rows)
        guard.print(report)
        return 0 if not (report['our_open_orders'] or report['mismatches'] or report['adoption_refusals'] or
                         report['unacknowledged_intents']) else 1
    finally:
        venue.close()


def session0_attest(root, ledger, *, s0_2_seconds, phrase, now):
    """Write session0/pass.json once (never overwritten). Refuses unless every required sub-run passed in the
    ledger and S0-2 on 0c is at most 20 s; the owner judges S0-1..S0-8 by the verify commands before typing."""
    missing = session0_mechanical(ledger)
    if missing:
        raise RuntimeError('session0_runs_missing_' + '_'.join(missing))
    seconds = Decimal(str(s0_2_seconds))
    if not seconds.is_finite() or not 0 <= seconds <= LFC.SESSION0_S0_2_MAX_SECONDS:
        raise RuntimeError('session0_s0_2_above_20_seconds')
    sequence = len(ledger.rows) - 1
    body = {'schema_version': SESSION0_PASS_SCHEMA, 'kind': 'lfc_session0_pass', 'attested_at_utc': utc(now).isoformat(),
            'ledger_sequence': sequence, 'ledger_previous_sha256': ledger.previous, 's0_2_seconds_0c': str(seconds),
            'sessions': {run: ids[-1][0] for run, ids in session0_runs_passed(ledger).items()
                         if run in LFC.SESSION0_PASS_REASONS},
            'owner_phrase': phrase}
    path = Path(root) / SESSION0_PASS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_new(path, body), body


def run_session0_attest(args, *, reader=input):
    from weather.market.re1_attended import SecretGuard
    root = pilot_root()
    ledger = Ledger.open(ledger_path(root), clock=_now)
    if not sys.stdin.isatty():
        raise RuntimeError('owner_terminal_required')
    phrase = 'attest session0 ' + str(ledger.previous)[:6]
    guard = SecretGuard()
    guard.print({'runs': session0_runs_passed(ledger), 's0_2_seconds_0c': args.s0_2_seconds,
                 'ledger_previous_sha256': ledger.previous})
    guard.print('Type: ' + phrase)
    if ' '.join(str(reader()).lower().split()) != phrase:
        raise RuntimeError('owner_confirmation_refused')
    sha, body = session0_attest(root, ledger, s0_2_seconds=args.s0_2_seconds, phrase=phrase, now=_now())
    guard.print({'status': 'ATTESTED', 'file': str(root / SESSION0_PASS_FILE), 'sha256': sha})
    return 0


def cancel_ours(ledger, venue):
    ours, foreign = classify_open_orders(venue.open_orders(), ledger)
    responses = {oid: venue.cancel(oid) for oid in ours}
    remaining, _ = classify_open_orders(venue.open_orders(), ledger)
    return {'cancelled': ours, 'responses': responses, 'remaining_ours': remaining, 'foreign_left': foreign}


def run_cancel_ours():
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    fields, guard = load_owner_credentials('cancel-only')
    venue = OwnerVenue(build_client(fields), fields, guard)
    try:
        ledger = Ledger.open(ledger_path(pilot_root()), clock=_now, maker_address=fields['FUNDER_ADDRESS'])
        receipt = cancel_ours(ledger, venue)
        write_new(pilot_root() / ('cancel-ours-' + _now().strftime('%Y%m%dT%H%M%S%fZ') + '.json'), guard.clean(receipt))
        guard.print(receipt)
        return 0 if not receipt['remaining_ours'] else 1
    finally:
        venue.close()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.mode == 'init-ledger':
            return run_init_ledger()
        if args.mode == 'baseline':
            return run_baseline(args.label)
        if args.mode == 'preflight':
            return run_preflight(args)
        if args.mode == 'live':
            return run_live(args)
        if args.mode == 'verify':
            return run_verify()
        if args.mode == 'wallet-verify':
            return run_wallet_verify(args)
        if args.mode == 'reconcile':
            return run_reconcile()
        if args.mode == 'cancel-ours':
            return run_cancel_ours()
        if args.mode == 'session0-attest':
            return run_session0_attest(args)
        from weather.market.lfc_panel_exclusion import main as exclusions_main
        return exclusions_main(['--exclusions', str(pilot_root() / EXCLUSION_FILE), '--output', str(args.output)])
    except BaseException as exc:
        # Never echo exception messages: SDK/parser errors can carry secrets. Ledger refusals are plain codes.
        from weather.market.re1_attended import SecretGuard
        detail = str(exc) if isinstance(exc, (LedgerUnavailable, ValueError, RuntimeError)) and \
            str(exc).replace('_', '').replace(':', '').replace(' ', '').replace(',', '').isalnum() else None
        SecretGuard().print({'status': 'REFUSED', 'exception_type': type(exc).__name__, 'code': detail,
                             'action': 'If orders may rest, run cancel-ours, then verify.'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
