"""Retry intact closure transactions; never repair or truncate ledger bytes."""
from weather.market.lfc_ledger import Ledger, LedgerUnavailable


class ClosureRetryPending(LedgerUnavailable):
    def __init__(self, state, attempt_id):
        super().__init__('closure_anchor_retry_pending')
        self.state, self.attempt_id = state, attempt_id


def retry_labels(state, attempt):
    claim = next((r for r in state.ledger.autostart_claims if r['attempt_id'] == attempt), {})
    return {**{key: claim.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')},
            'sleeve_loss_basis': claim.get('sleeve_loss_basis', 'gross')}


def retry_failure(state, attempt, error, *, expected=None):
    """Only a verified original/prefix can turn a failed write into a retry.

    A complete append followed by an exception is adopted once on verified
    replay. A torn append refuses replay; it is never truncated or relabelled
    as loss of the intact closure. The next owning tick retries the transaction.
    """
    from weather.market.lfc_campaign_closures import fields, fault
    from weather.market.lfc_campaign_close_intent import saved_intent, require_match
    from weather.market.lfc_campaign_guard import require_account
    require_account(state.maker)
    if isinstance(error, LedgerUnavailable):
        if str(error) in {'ledger_closure_anchor_scope', 'ledger_closure_anchor_binding'}:
            fault(state, attempt)
        if str(error) not in {'ledger_write_failed', 'ledger_snapshot_write_failed'}:
            raise error
    elif not isinstance(error, OSError):
        raise error
    previous = state.ledger
    fresh = Ledger.open(previous.path, clock=previous.clock, maker_address=state.maker)
    prefix = len(previous.rows)
    if len(fresh.rows) < prefix or fresh.row_sha256(prefix-1) != previous.row_sha256(prefix-1):
        raise LedgerUnavailable('ledger_changed_underneath')
    added = fresh.rows[prefix:]
    if any(row['event'] not in {'autostart_close', 'autostart_no_intent_close', 'autostart_close_intent'} or
           row.get('attempt_id') != attempt for row in added):
        raise LedgerUnavailable('ledger_changed_underneath')
    fresh.policy_metadata = dict(getattr(previous, 'policy_metadata', {}))
    state.ledger = fresh
    path = state.root / 'closed' / (attempt + '.json')
    intent = saved_intent(fresh, attempt)
    from weather.market.lfc_campaign_publication import matching_stage
    published = any(row.get('attempt_id') == attempt for kind in
                   ('autostart_close', 'autostart_no_intent_close') for row in fresh.event_rows(kind))
    staged = intent is not None and not published and matching_stage(state, intent) is not None
    anchored = intent is not None or published
    try:
        actual = fields(state, path) if path.exists() else None
        if ((expected is not None and actual != expected) or
                actual is None and anchored and not staged or
                actual is not None and any(r.get('file_sha256') != actual['file_sha256'] for r in added)):
            raise ValueError('closure_changed_during_append')
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        fault(state, attempt)
    if actual is not None and any(row['event'] == 'autostart_close' and
            any(row.get(key) != value for key, value in actual.items()) for row in added):
        raise LedgerUnavailable('ledger_changed_underneath')
    if actual is not None:
        require_match(state, actual)
    raise ClosureRetryPending(state, attempt) from None
