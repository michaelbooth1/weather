"""Stage 2's exact two-token stream; unrelated account events still fail closed."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from weather.market.mm_live_envelope import STAGE2_HOLD_V1, select_envelope
from weather.market.mm_official_adapter import normalize_official_user_event
from weather.market.mm_user_stream import OfficialUserStreamReader
from weather.paths import REPO_ROOT


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
