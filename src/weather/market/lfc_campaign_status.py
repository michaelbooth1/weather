"""Read-only status; no account authority, repairs, control writes or venue calls."""
from datetime import datetime, timezone
import json
import re

from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market import lfc_campaign_guard as guard
from weather.market.lfc_campaign_control import latest_control, watch_status
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_f2_policy import effective_loss_basis
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_ledger import Ledger, ledger_path
from weather.operations.live_path_security import validate_regular_nonreparse_file


class ReadOnlyState(AccountState):
    def require_writer(self):
        raise StateRefused('status_repair_required')

    def save(self, *args, **kwargs):
        raise StateRefused('status_repair_required')

    def evidence_fault(self, *args, **kwargs):
        # The next owning tick records the occurrence. An observer never
        # changes the newest control record or the account's incident history.
        raise StateRefused('status_evidence_fault')


def snapshot(release, *, root, state_root, control_root):
    ledger = Ledger.open(validate_regular_nonreparse_file(ledger_path(root)),
        clock=lambda: datetime.now(timezone.utc), maker_address=release['maker_address'])
    def refuse_write(*args, **kwargs):
        raise StateRefused('status_repair_required')
    ledger.record = refuse_write
    state = ReadOnlyState(state_root, ledger)
    if ledger.row_sha256(0) != release['ledger_genesis_sha256']:
        raise StateRefused('ledger_genesis_changed')
    if state.verify()['state_id'] != release['state_id']:
        raise StateRefused('account_state_changed')
    policy = load_policy(release['campaign_path'])
    basis = effective_loss_basis(policy)
    control, code = watch_status(latest_control(control_root))
    capital = CapitalBook(ledger).figures(loss_basis=basis)
    # Reuse the existing full-file unchanged proof, with no possible string
    # intent key. This grants no posting authority or writer handle.
    if not ledger.intent_proven_absent(None):
        raise StateRefused('status_snapshot_changed')
    return {'state': 'STATUS', 'sleeve_loss_basis': basis,
        'basis_explicit': 'sleeve_loss_basis' in policy.raw,
        'active_sleeve_loss_basis': ledger.sleeve_loss_basis,
        'ledger_head_sha256': ledger.row_sha256(len(ledger.rows)-1),
        'claims': [{'attempt_id': c['attempt_id'], 'sleeve_loss_basis': c.get('sleeve_loss_basis', 'gross')}
                   for c in ledger.autostart_claims],
        'capital': capital, 'control': control, 'clean': code == 0}, code


def report(args, *, load_release, validate_release, root, state_root, control_root):
    """Contain every error locally; the mutating dispatcher never handles it."""
    try:
        release = load_release(args.release, args.release_sha256)
        if guard.account_lease_busy(release['maker_address']):
            print('deferred: lease busy')
            return 1
        validate_release(release)
        row, code = snapshot(release, root=root(), state_root=state_root, control_root=control_root)
        # A concurrent owner may have started since our first observation.
        # Do not report a mixed snapshot as a fresh account read.
        if guard.account_lease_busy(release['maker_address']):
            print('deferred: lease busy')
            return 1
        print(json.dumps(row))
        return code
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        if isinstance(exc, StateRefused) and str(exc) == 'status_repair_required':
            print(json.dumps({'state': 'retry_pending', 'reason': 'retry_pending', 'attention_required': True}))
            return 1
        reason = str(exc) if isinstance(exc, (StateRefused, guard.AdmissionUncertain)) else 'status_unavailable'
        reason = reason if re.fullmatch('[a-z0-9_]{1,96}', reason) else 'status_unavailable'
        print(json.dumps({'state': 'STATUS_UNAVAILABLE', 'reason': reason, 'attention_required': True}))
        return 1
