"""Parent wrapper budget bound to the exact editable-policy byte snapshot.

This is a timing guard, never exchange authority or a policy-edit restriction
for a later unclaimed session. Active sessions retain their admitted snapshot.
"""
from datetime import datetime, timedelta, timezone
import re


class LaunchDeferred(ValueError):
    pass


def launch_packet(deadline, policy_sha256):
    try:
        end = datetime.fromisoformat(deadline)
        if (end.utcoffset() != timedelta(0) or
                re.fullmatch('[0-9a-f]{64}', policy_sha256) is None):
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise LaunchDeferred('wrapper_launch_missing_or_invalid') from None
    return {'deadline_utc': end.astimezone(timezone.utc).isoformat(), 'policy_bytes_sha256': policy_sha256}


def require_launch(packet, policy, entry):
    if not isinstance(packet, dict):
        raise LaunchDeferred('wrapper_launch_missing_or_invalid')
    bound = launch_packet(packet.get('deadline_utc'), packet.get('policy_bytes_sha256'))
    if getattr(policy, 'source_sha256', None) != bound['policy_bytes_sha256']:
        raise LaunchDeferred('wrapper_policy_changed')
    # The whole half-open window must fit. Setup/go may use any part of it;
    # a pre-window fallback must never become new session authority later.
    if entry.session_end(entry.end) + timedelta(minutes=30) > datetime.fromisoformat(bound['deadline_utc']):
        raise LaunchDeferred('wrapper_cleanup_budget_insufficient')
    return bound
