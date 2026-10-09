"""Stage 2's exact two-token stream; unrelated account events still fail closed."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import hashlib
import json

from weather.market.mm_live_envelope import STAGE2_HOLD_V1, select_envelope
from weather.market.mm_official_adapter import normalize_official_user_event, _validated_normalized_official_user_event
from weather.market.mm_user_stream import OfficialUserStreamReader, SCHEMA_VERSION
from weather.market.reward_quote import _decimal
from weather.paths import REPO_ROOT


def verify_stage2_user_stream_journal(path, *, maker, condition, tokens, orders):
    """Require an exact pair, no trade lifecycle and a terminal cancel per ACK."""
    raw = Path(path).read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    if (not rows or any(r.get('schema_version') != SCHEMA_VERSION for r in rows)
            or rows[0].get('event_type') != 'stream_starting'
            or rows[0].get('maker_address') != maker or rows[0].get('condition_id') != condition
            or rows[0].get('token_ids') != list(tokens) or rows[0].get('account_wide_subscription') is not True
            or rows[-1].get('event_type') != 'stream_stopped'
            or sum(r.get('event_type') == 'stream_stopped' for r in rows) != 1
            or sum(r.get('event_type') == 'subscription_sent' for r in rows) != 1):
        raise RuntimeError('Stage 2 stream identity or terminal lifecycle is incomplete')
    terminal = set()
    for row in rows:
        event = row.get('event_type')
        if event not in {'stream_starting', 'subscription_sent', 'user_event', 'stream_stopped'}:
            raise RuntimeError('Stage 2 stream records a failure or unknown event')
        if event != 'user_event':
            continue
        payload = row['payload']
        token = payload.get('clob_token_id')
        if token not in tokens:
            raise RuntimeError('Stage 2 stream contains an unrelated token')
        normalized = _validated_normalized_official_user_event(payload, maker_address=maker,
            condition_id=condition, token_id=token)
        oid = normalized['order_id']
        if (oid not in orders or orders[oid] != token or normalized['official_event_type'] != 'order'
                or normalized.get('side') != 'BUY' or _decimal(normalized.get('size_matched')) != 0):
            raise RuntimeError('Stage 2 stream contains an unknown order or trade lifecycle')
        if normalized['event_type'] == 'canceled':
            terminal.add(oid)
    if terminal != set(orders):
        raise RuntimeError('Stage 2 stream lacks every exact zero-fill cancellation')
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'row_count': len(rows), 'terminal_order_ids': sorted(terminal)}


class Stage2UserStreamReader(OfficialUserStreamReader):
    def __init__(self, *, token_ids, authority_root=REPO_ROOT, utc_clock=None, **kwargs):
        tokens = tuple(token_ids)
        if (len(tokens) != 2 or len(set(tokens)) != 2
                or any(not isinstance(t, str) or not re.fullmatch(r"[1-9][0-9]*", t) for t in tokens)):
            raise ValueError("Stage 2 stream requires exactly two distinct token IDs")
        self.token_ids = tokens
        self.authority_root = Path(authority_root)
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self._require_grants()
        super().__init__(token_id=tokens[0], **kwargs)

    def _require_grants(self):
        select_envelope(
            STAGE2_HOLD_V1.profile_id,
            state_of_play_path=self.authority_root / "docs/operations/STATE_OF_PLAY.md",
            assignment_path=self.authority_root / "config/international_live_execution_host.json",
            now=self.utc_clock(),
        )

    def run(self, *, max_events=None):
        self._require_grants()
        return super().run(max_events=max_events)

    def _normalize_event(self, item):
        token = item.get("asset_id") if isinstance(item, dict) else None
        if token not in self.token_ids:
            raise RuntimeError("official user event is outside the two-token session")
        return normalize_official_user_event(
            item, maker_address=self.maker_address,
            condition_id=self.condition_id, token_id=token,
        )

    def _journal_token_scope(self):
        return {"token_id": self.token_id, "token_ids": list(self.token_ids)}

    def events_for_token(self, token_id):
        if token_id not in self.token_ids:
            raise ValueError("unknown session token")
        # All events have first passed the account-wide exact-scope validator.
        return [row for row in self.events() if row["clob_token_id"] == token_id]
