"""Owner-attended RE-1M rehearsal, preflight, live, panic, reconcile and collection."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys

from weather.market.mm_stage2_hold import digest, write_new
from weather.market.mm_stage2_rehearsal import ReplayClock
from weather.market.re1_attended import Session, SecretGuard, LAST_DAY, MAX_SESSIONS
from weather.market.re1_evidence import campaign_root, live_mutex, reserve_attempt, load_prediction, payout_verdict
from weather.market.re1_rehearsal import RehearsalVenue, WallClock, Re1PublicBooks
from weather.market.re1_sizing import session_caps

_LIVE_STARTED = False


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    modes = result.add_subparsers(dest='mode', required=True)
    rehearsal = modes.add_parser('rehearse')
    rehearsal.add_argument('--selection', type=Path, help='retained public table for accelerated replay')
    rehearsal.add_argument('--output', type=Path, required=True)
    rehearsal.add_argument('--realtime', action='store_true', help='900 seconds using live public books and an inert exchange')
    modes.add_parser('live')
    modes.add_parser('cancel-only')
    modes.add_parser('preflight')
    reconcile = modes.add_parser('reconcile')
    reconcile.add_argument('attempt', type=int, choices=range(1, 21))
    collect = modes.add_parser('collect-payout')
    collect.add_argument('prediction', type=Path)
    collect.add_argument('--payment-evidence', type=Path, help='independently reconciled distribution/wallet evidence; absent means payment unverified')
    evidence = modes.add_parser('collect-evidence', help='read-only payout sources; missing linkage stays inconclusive')
    evidence.add_argument('prediction', type=Path)
    return result


def run_rehearsal(args):
    public = Re1PublicBooks()
    if args.realtime and args.selection:
        raise ValueError('realtime_requires_fresh_public_selection')
    table = json.loads(args.selection.read_bytes()) if args.selection else public.selection(available_collateral='50')
    if not table['selected_condition_id']:
        write_new(args.output / 'selection.json', table)
        raise RuntimeError('no_qualifying_band')
    row = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
    clock = WallClock() if args.realtime else ReplayClock(table['created_at_utc'])
    venue = RehearsalVenue(row['snapshot'], args.output, clock=clock, public=public if args.realtime else None)
    session = Session(venue=venue, public=venue, table=table, clock=clock, directory=args.output,
                      realtime_rehearsal=args.realtime)
    result = session.run(rehearsal_seconds=900 if args.realtime else None)
    return 0 if result['cleanup_ok'] and result['failure_type'] is None else 1


def confirmation(table, guard, *, reader=input):
    if not sys.stdin.isatty(): raise RuntimeError('owner_terminal_required')
    selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
    phrase = 'go ' + digest(table)[:6]  # owner 2026-09-24: short phrase, still bound to the exact selection digest
    guard.print({'condition': selected['condition_id'], 'quote': selected['quote'], 'selection_sha256': digest(table),
                 'size': selected['quote']['size'], 'reserve_pusd': selected['quote']['reserve_pusd'],
                 'available_collateral': table.get('available_collateral'),
                 'minutes': 360, 'max_submits': 10, 'max_sessions': MAX_SESSIONS, 'last_date': LAST_DAY})
    guard.print('Dedicated testing wallet: at most 200 pUSD. The full two-sided reserve is at risk; the session capital ceiling is 0.98 times the chosen size, bounded by wallet minus 10 and 75 pUSD. Check the tunnel is down, geography is eligible, no open orders or rewarded activity today, and remain within reach for six hours.')
    guard.print('Type: ' + phrase)
    typed = ' '.join(str(reader()).lower().split())
    if typed != phrase: raise RuntimeError('owner_confirmation_refused')
    return {'text': phrase, 'at_utc': datetime.now(timezone.utc).isoformat()}


def run_live():
    global _LIVE_STARTED
    if _LIVE_STARTED: raise RuntimeError('one_session_per_process')
    _LIVE_STARTED = True
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue, geography
    from weather.market.re1_owner_checks import clean_preflight, code_identity
    with live_mutex():
        now = datetime.now(timezone.utc)
        if now.date().isoformat() > LAST_DAY or (now + timedelta(hours=6)).date() != now.date():
            raise RuntimeError('session_duration_or_utc_day')
        preflight = clean_preflight(campaign_root(), now=now, commit=code_identity())
        if geography().get('blocked') is not False: raise RuntimeError('geoblock')
        fields, guard = load_owner_credentials('live')
        if fields['FUNDER_ADDRESS'] != preflight['maker_address']:
            raise RuntimeError('preflight_account_changed')
        timeouts = preflight['timeouts_seconds']
        client = build_client(fields, timeout=max(timeouts.values()))
        venue = None
        session = None
        handlers = {}
        try:
            # No order/heartbeat capability is used before the exact phrase.
            wallet_reader = OwnerVenue(client, fields, guard, readonly=True, timeouts=timeouts)
            balances = wallet_reader.balances()
            public = Re1PublicBooks()
            table = public.selection(available_collateral=balances['available_collateral'])
            if not table['selected_condition_id']: raise RuntimeError('no_qualifying_band')
            receipt = confirmation(table, guard)
            selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
            _, reserve_cap = session_caps(selected['quote']['size'], table['available_collateral'])
            venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'],
                               timeouts=timeouts, size=selected['quote']['size'], reserve_cap=reserve_cap)
            directory, attempt = reserve_attempt(campaign_root(), now=datetime.now(timezone.utc), selection_sha256=digest(table),
                                                 open_orders=venue.open_orders, maker=venue.maker)
            venue = OwnerVenue(client, fields, guard, condition=selected['condition_id'], tokens=selected['token_ids'],
                               directory=directory, timeouts=timeouts, size=selected['quote']['size'], reserve_cap=reserve_cap)
            session = Session(venue=venue, public=public, table=table, clock=WallClock(), directory=directory,
                              guard=guard, mode='live', confirmation=receipt, attempt=attempt)
            def interrupted(_signal, _frame): raise KeyboardInterrupt()
            for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
                if hasattr(signal, name):
                    value = getattr(signal, name)
                    handlers[value] = signal.signal(value, interrupted)
            venue.start()
            result = session.run()
            return 0 if result['cleanup_ok'] and result['failure_type'] is None else 1
        finally:
            if session is not None: session.cleanup()
            try:
                if venue is not None: venue.close()
                else: client.close()
            finally:
                for value, handler in handlers.items(): signal.signal(value, handler)


def run_cancel():
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    fields, guard = load_owner_credentials('cancel-only')
    client = build_client(fields)
    venue = OwnerVenue(client, fields, guard)
    output = campaign_root() / ('panic-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    try:
        response, remaining, failure = None, None, None
        try:
            response = venue.cancel_all()
        except Exception as exc:
            failure = type(exc).__name__
        try:
            remaining = venue.open_orders()
        except Exception as exc:
            failure = type(exc).__name__
        receipt = {'at_utc': datetime.now(timezone.utc).isoformat(), 'response': response,
                   'remaining': remaining, 'failure_type': failure}
        write_new(output, guard.clean(receipt))
        guard.print(receipt)
        return 0 if remaining == [] and failure is None else 1
    finally:
        venue.close()


def run_collect(args):
    # Verify the prior-day frozen evidence before resolving any credentials.
    prediction = load_prediction(args.prediction, now=datetime.now(timezone.utc))
    if prediction['mode'] != 'live': raise RuntimeError('rehearsal_is_not_payout_evidence')
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    fields, guard = load_owner_credentials('collect-payout')
    if fields['FUNDER_ADDRESS'].lower() != prediction['scope']['maker_address'].lower():
        raise RuntimeError('collection_account_changed')
    client = build_client(fields, readonly=True)
    venue = OwnerVenue(client, fields, guard, condition=prediction['condition_id'], readonly=True)
    try:
        accrual = venue.accrual(prediction['reward_day'])
        balances = venue.balances()
        payment_bytes = args.payment_evidence.read_bytes() if args.payment_evidence else None
        payment = json.loads(payment_bytes) if payment_bytes is not None else None
        binding = {'payment_evidence_path': str(args.payment_evidence.absolute()) if args.payment_evidence else None,
                   'payment_evidence_sha256': hashlib.sha256(payment_bytes).hexdigest() if payment_bytes is not None else None}
        diagnostics = payment.get('payout_diagnostics') if isinstance(payment, dict) else None
        result = {**payout_verdict(prediction, accrual, payment), 'accrual': accrual, 'balances': balances,
                  'payout_diagnostics': diagnostics, **binding}
        destination = args.prediction.parent / ('payout-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        write_new(destination, guard.clean(result))
        guard.print({'verdict': result['verdict'], 'k': result['k'], 'k_accrued': result['k_accrued'],
                     'verdict_frozen': result['verdict_frozen'], 'verdict_amended': result['verdict_amended'],
                     'accrued_verdict': result['accrued_verdict'], 'flags': result['flags'],
                     'receipt': str(destination), 'payout_diagnostics': diagnostics, **binding})
        return 0
    finally:
        venue.close()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.mode == 'rehearse': return run_rehearsal(args)
        if args.mode == 'live': return run_live()
        if args.mode == 'cancel-only': return run_cancel()
        if args.mode == 'preflight':
            from weather.market.re1_owner_checks import run_preflight
            return run_preflight()
        if args.mode == 'reconcile':
            from weather.market.re1_owner_checks import run_reconcile
            return run_reconcile(args.attempt)
        if args.mode == 'collect-evidence':
            from weather.market.re1_payout_evidence import run_collect_evidence
            return run_collect_evidence(args)
        return run_collect(args)
    except BaseException as exc:
        # Do not echo exception messages: SDK/parser errors can carry secrets.
        SecretGuard().print({'status': 'REFUSED', 'exception_type': type(exc).__name__,
                             'action': 'If orders may exist, run cancel-only and check the venue in your browser.'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
