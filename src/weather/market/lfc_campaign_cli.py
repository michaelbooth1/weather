"""Owner-only campaign enrollment/check and scheduled finite dispatch.

Agents never invoke seal/tick/recover on a real account. Tests inject a complete
temporary runtime; there is no live dry-run switch that can bypass admission.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid
import json
import re

from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_control import CONTROL_ROOT, control_record
from weather.market.lfc_campaign_guard import AdmissionBusy, account_lease
from weather.market.lfc_campaign_policy import PolicyRefused, load_policy
from weather.market.lfc_campaign_policy import ZONE
from weather.market.lfc_campaign_release import load_release, seal_release, task_enabled, validate_release
from weather.market.lfc_campaign_state import AccountState, DEFAULT_STATE_ROOT, StateRefused
from weather.market.lfc_ledger import Ledger, ledger_path
from weather.market.lfc_pilot import pilot_root
from weather.market.lfc_recording_io import file_sha
from weather.operations.live_path_security import validate_regular_nonreparse_file


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    seal = commands.add_parser('seal', help='owner registrar only, after qualification and frozen F0')
    for key in ('campaign', 'release', 'pregate', 'head', 'python'):
        seal.add_argument('--' + key, required=True)
    for command in ('check', 'tick', 'owner-recover', 'owner-clear-workload'):
        item = commands.add_parser(command)
        item.add_argument('--release', required=True)
        item.add_argument('--release-sha256', required=True)
        if command == 'check':
            item.add_argument('--require-enabled', action='store_true')
        if command == 'owner-recover':
            item.add_argument('--incident', required=True)
    return result


def bound_state(release, clock):
    root = pilot_root()
    ledger = Ledger.open(validate_regular_nonreparse_file(ledger_path(root)), clock=clock.now,
                         maker_address=release['maker_address'])
    if ledger.row_sha256(0) != release['ledger_genesis_sha256']:
        raise StateRefused('ledger_genesis_changed')
    state = AccountState(DEFAULT_STATE_ROOT, ledger)
    if state.verify()['state_id'] != release['state_id']:
        raise StateRefused('account_state_changed')
    return root, state


def owner_recover(runtime, incident):
    """Explicit owner closure, never called by tick or automatic reconciliation.

    Any ambiguous identities must first be resolved by an owner-reviewed repair.
    This command does not adopt orders, manufacture a crashed success, reset a
    date/count, infer a redemption or erase original flags/evidence.
    """
    if not sys.stdin.isatty():
        raise StateRefused('owner_terminal_required')
    path = runtime.state.root / 'incidents' / (incident + '.json')
    if not path.is_file() or path.parent != runtime.state.root / 'incidents':
        raise StateRefused('incident_missing')
    receipt_sha = file_sha(path)
    phrase = 'recover ' + receipt_sha[:12]
    print('Owner-led recovery: read the incident and all monetary evidence before closing it. Type: ' + phrase)
    if input().strip() != phrase:
        raise StateRefused('owner_confirmation_refused')
    with runtime.admission():
        ledger = runtime.reload_ledger()
        if ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted:
            raise StateRefused('owner_money_repair_required')
        read = runtime.read_account()
        proof = runtime.core_proof(ledger, read)
        if not proof['money_accounting_complete'] or not proof['cleanup_proven'] or proof['unknown_submit']:
            raise StateRefused('owner_money_repair_required')
        runtime.state.save('owner-closures/' + incident + '.json', {
            'authority': 'owner_recovery', 'incident_sha256': receipt_sha, 'proof': proof,
            'local_date': runtime.clock.now().astimezone(ZONE).date().isoformat(),
            'closed_at_utc': runtime.clock.now().isoformat()})
        if not runtime.state.incidents():
            for claim in runtime.state.pending():
                runtime.state.close(claim, {**proof, 'authority': 'owner_recovery',
                                           'original_result_retained': True}, runtime.clock.now())
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'seal':
        seal_release(campaign_path=args.campaign, pregate_path=args.pregate, qualified_head=args.head,
                     python_path=args.python, output=args.release)
        print('Campaign release sealed; task activation remains owner-only.')
        return 0
    attempt = uuid.uuid4().hex
    try:
        release = load_release(args.release, args.release_sha256)
        validate_release(release)
        from weather.market.lfc_campaign_runtime import CampaignClock, Runtime
        clock = CampaignClock()
        with account_lease(release['maker_address']):
            root, state = bound_state(release, clock)
            load = lambda: load_policy(release['campaign_path'])
            if args.command == 'check':
                policy = load()
                if args.require_enabled and not policy.raw['enabled']:
                    raise StateRefused('campaign_disabled')
                print('Campaign policy and immutable identity valid; no live action performed.')
                return 0
            runtime = Runtime(state=state, pilot_root=root, policy_path=release['campaign_path'], release=release,
                              clock=clock, control_root=CONTROL_ROOT,
                              task_enabled=lambda: task_enabled(release, args.release, args.release_sha256))
            if args.command == 'owner-recover':
                return owner_recover(runtime, args.incident)
            if args.command == 'owner-clear-workload':
                from weather.market.lfc_campaign_guard import ExclusiveWorkload
                from weather.market.lfc_campaign_workload import owner_release_workload_after_reboot
                path = ExclusiveWorkload(state.maker).poison_root / 'heavy_workload_v1.poison'
                owner_release_workload_after_reboot(path=path, expected_sha=file_sha(path),
                                         state_id=state.verify()['state_id'], maker=state.maker)
                return 0
            result = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=CONTROL_ROOT).tick(load)
            return 1 if result == 'INCIDENT' or state.incidents() else 0
    except AdmissionBusy:
        control_record(CONTROL_ROOT, attempt, phase='DEFERRED', now=datetime.now(timezone.utc))
        return 0
    except (PolicyRefused, StateRefused):
        code = str(sys.exc_info()[1])
        code = code if re.fullmatch(r'[a-z0-9_]{1,96}', code) else 'policy_refused'
        print(json.dumps({'state': 'REFUSED', 'code': code}))
        control_record(CONTROL_ROOT, attempt, phase='REFUSED', now=datetime.now(timezone.utc), reason='policy_refused')
        return 1
    except BaseException:
        # Never expose credentials/paths/raw exception messages. Existing claims
        # retain their sticky incident; missing state is never bootstrapped here.
        control_record(CONTROL_ROOT, attempt, phase='INCIDENT', now=datetime.now(timezone.utc), incident=True,
                       postchecks_pending=True)
        return 130 if sys.exc_info()[0] is KeyboardInterrupt else 1


if __name__ == '__main__':
    raise SystemExit(main())
