from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timezone
import hashlib
import json

import pytest

from weather.market.mm_live_envelope import (
    EnvelopeNotAuthorized, GRANT_KEY, GRANT_PREFIX, STAGE1_V1, STAGE2_HOLD_V1,
    select_envelope,
)


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("profile, expected", [
    (STAGE1_V1, ("stage1_v1", 10, 10, 25, 25, 100, 1, True, True, True)),
    (STAGE2_HOLD_V1, ("stage2_hold_v1", 16, 20, 25, 25, 100, 2, True, True, True)),
])
def test_every_envelope_value_is_pinned_and_immutable(profile, expected):
    assert tuple(asdict(profile).values()) == expected
    assert profile.sha256 == hashlib.sha256(profile.canonical_bytes()).hexdigest()
    with pytest.raises(FrozenInstanceError):
        profile.per_order_pusd = 100
    for key, value in asdict(profile).items():
        changed = not value if isinstance(value, bool) else value + 1 if isinstance(value, int) else value + "-changed"
        assert replace(profile, **{key: changed}).sha256 != profile.sha256


def test_stage1_default_requires_no_new_document_or_authorization(tmp_path):
    assert select_envelope(state_of_play_path=tmp_path / "missing", assignment_path=tmp_path / "missing") is STAGE1_V1


def test_existing_stage1_and_policy_caps_match_the_inert_definition():
    from weather.market import mm_live_candidate_cli as candidate
    from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
    from weather.market.mm_official_adapter import MAX_STAGE1_ORDER_NOTIONAL
    from weather.market.mm_policy import DEFAULT_POLICY_CONFIG

    assert MAX_STAGE1_ORDER_NOTIONAL == candidate.MAX_SINGLE_ORDER_NOTIONAL == STAGE1_V1.per_order_pusd
    assert candidate.MAX_BAND_NOTIONAL_PUSD == DEFAULT_POLICY_CONFIG["max_band_notional"] == STAGE1_V1.per_band_pusd
    assert candidate.MAX_EVENT_NOTIONAL_PUSD == DEFAULT_POLICY_CONFIG["max_event_notional"] == STAGE1_V1.per_event_pusd
    assert candidate.MAX_DAILY_LOSS_PUSD == DEFAULT_POLICY_CONFIG["max_daily_loss"] == STAGE1_V1.daily_loss_pusd
    assert candidate.MAX_OPERATOR_PILOT_BUDGET_PUSD == MAX_OPERATOR_PILOT_BUDGET_USDC == STAGE1_V1.wallet_pusd


def test_checked_in_sources_do_not_authorize_stage2():
    with pytest.raises(EnvelopeNotAuthorized):
        select_envelope("stage2_hold_v1", now=NOW)


def sources(tmp_path, *, mutation=None, assignment_mutation=None):
    # Synthetic documents in tmp_path exercise the real parser. They are never
    # written into repository authority or used with a client/sealer/launcher.
    grant = {
        "profile_id": "stage2_hold_v1", "profile_sha256": STAGE2_HOLD_V1.sha256,
        "authorized_on": "2026-09-21", "expires_at_utc": "2026-09-21T12:45:00+00:00",
        **(mutation or {}),
    }
    state, assignment = tmp_path / "state.md", tmp_path / "assignment.json"
    state.write_text("# Fixture only\n\n## Current authority\n" + GRANT_PREFIX + json.dumps(grant) + "\n\n## Next\n", encoding="utf-8")
    assignment.write_text(json.dumps({GRANT_KEY: {**grant, **(assignment_mutation or {})}}), encoding="utf-8")
    return {"state_of_play_path": state, "assignment_path": assignment, "now": NOW}


def test_matching_fixture_grants_select_only_numeric_profile(tmp_path):
    assert select_envelope("stage2_hold_v1", **sources(tmp_path)) is STAGE2_HOLD_V1


@pytest.mark.parametrize("mutation", [
    {"profile_id": "stage1_v1"}, {"profile_sha256": "0" * 64},
    {"authorized_on": "2026-09-20"}, {"authorized_on": "2026-09-22"},
    {"authorized_on": None}, {"expires_at_utc": None},
    {"expires_at_utc": "2026-09-21T11:59:59Z"},
    {"expires_at_utc": "2026-09-21T12:45:00"},
    {"expires_at_utc": "2026-09-22T12:45:00Z"}, {"raise_caps": True},
])
def test_invalid_fixture_grants_refuse(tmp_path, mutation):
    with pytest.raises(EnvelopeNotAuthorized):
        select_envelope("stage2_hold_v1", **sources(tmp_path, mutation=mutation))


def test_disagreeing_fixture_grants_refuse(tmp_path):
    with pytest.raises(EnvelopeNotAuthorized, match="differs"):
        select_envelope("stage2_hold_v1", **sources(tmp_path, assignment_mutation={"profile_sha256": "0" * 64}))


@pytest.mark.parametrize("change", ["missing", "duplicate", "other_section", "duplicate_key"])
def test_grant_must_be_unique_and_in_current_authority(tmp_path, change):
    kwargs = sources(tmp_path)
    path = kwargs["state_of_play_path"]
    original = path.read_text(encoding="utf-8")
    if change == "missing":
        path.write_text("## Current authority\nNo authorization.\n", encoding="utf-8")
    elif change == "duplicate":
        path.write_text(original + original, encoding="utf-8")
    elif change == "other_section":
        path.write_text(original.replace("## Current authority", "## Proposed authority"), encoding="utf-8")
    else:
        path.write_text(original.replace('{"profile_id":', '{"profile_id": "x", "profile_id":'), encoding="utf-8")
    with pytest.raises(EnvelopeNotAuthorized):
        select_envelope("stage2_hold_v1", **kwargs)
