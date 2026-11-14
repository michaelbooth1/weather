"""Narrow pre-enable exception: closed money state awaiting ordinary postchecks."""
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_f2_inventory import between_sessions


NOTICE = 'POSTCHECK_PENDING_WILL_RUN_ON_FIRST_TICK'


def pending_postchecks_only(state, ledger):
    if between_sessions(ledger):
        return False
    if (ledger.open_sessions() or ledger.unresolved_legs() or ledger.unacknowledged_intents() or
            ledger.halted or ledger.mismatches or state.incidents()):
        raise StateRefused('enrollment_funding_unreconciled')
    if not state.pending():
        raise StateRefused('enrollment_funding_unreconciled')
    return True
