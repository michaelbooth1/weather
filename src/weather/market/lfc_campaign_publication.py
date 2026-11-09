"""Bounded exclusive publication of the original, intent-bound staging bytes."""
import os
import time

from weather.market.lfc_recording_io import read_bytes, STATE_JSON_LIMIT
from weather.operations.live_path_security import validate_regular_nonreparse_file


PUBLISH_ATTEMPTS = 3


def publish(temporary, path):
    """Never overwrite; a sharing violation gets at most 150 ms of backoff."""
    for index in range(PUBLISH_ATTEMPTS):
        try:
            if os.name == 'nt':
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
                temporary.unlink()
            return
        except OSError:
            # A completed rename whose return was lost must be verified by
            # the caller, not attempted again with a now-missing source.
            if path.exists() or not temporary.exists() or index == PUBLISH_ATTEMPTS - 1:
                raise
            time.sleep(.05 * (index + 1))


def matching_stage(state, saved):
    """No glob/inference: only the exact staging pathname bound in the intent."""
    from weather.market.lfc_campaign_closures import fields_from_raw
    name = saved.get('staged_file')
    if name is None:
        return None  # Historical intents cannot acquire a new staging identity.
    path = state.root / name
    try:
        raw = read_bytes(validate_regular_nonreparse_file(path.absolute()), STATE_JSON_LIMIT)
        item = fields_from_raw(state.root / saved['file'], raw)
        if any(saved.get(key) != value for key, value in item.items()):
            return None
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return None
    return path


def resume(state, saved):
    """Finish the same durable transaction, never synthesize another receipt."""
    from weather.market.lfc_campaign_closures import fields, fault
    from weather.market.lfc_campaign_persistence import ClosureRetryPending
    state.require_writer()
    path = state.root / saved['file']
    temporary = matching_stage(state, saved)
    if temporary is None:
        fault(state, saved['attempt_id'])
    # A complete append whose fsync return raised is not a torn append. Reprove
    # its durability before making its intent-bound bytes visible.
    try:
        with state.ledger.path.open('r+b') as stream:
            os.fsync(stream.fileno())
    except OSError:
        raise ClosureRetryPending(state, saved['attempt_id']) from None
    try:
        publish(temporary, path)
    except OSError:
        if not path.exists():
            if matching_stage(state, saved) is None:
                fault(state, saved['attempt_id'])
            raise ClosureRetryPending(state, saved['attempt_id']) from None
        # Publication may have completed before its return raised.
    try:
        item = fields(state, path)
        if any(saved.get(key) != value for key, value in item.items()):
            raise ValueError('published_closure_changed')
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        fault(state, saved['attempt_id'])
