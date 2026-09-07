from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.live_candidate_fixture import (
    build_current_gamma_event_payload,
    build_stage0_event_metadata_payload,
    build_stage0_scope_payload,
)
from weather.market import mm_live_stage0_scope as stage0_scope


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
TARGET_DATE = "2026-08-31"
CONDITION_ID = "0x" + "1" * 64
TOKEN_ID = "101"
ALTERNATE_TOKEN_ID = "102"


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _rehash(payload):
    payload["plan_sha256"] = stage0_scope.stage0_scope_plan_sha256(payload)
    return payload


def _event_file(tmp_path, *, generated_at=NOW):
    return _write_json(
        tmp_path / "location-market-events.json",
        build_stage0_event_metadata_payload(
            generated_at=generated_at,
            target_date=TARGET_DATE,
            condition_id=CONDITION_ID,
            token_id=TOKEN_ID,
            alternate_token_id=ALTERNATE_TOKEN_ID,
        ),
    )


def _book(token_id, *, bids, asks):
    return {
        "asset_id": token_id,
        "market": CONDITION_ID,
        "min_order_size": "5",
        "tick_size": "0.01",
        "neg_risk": False,
        "bids": [{"price": str(price), "size": "10"} for price in bids],
        "asks": [{"price": str(price), "size": "10"} for price in asks],
    }


def test_default_gamma_reader_binds_slug_timeout_and_public_json(monkeypatch):
    expected = _gamma_payload()
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(expected).encode("utf-8")

    def fake_urlopen(request, *, timeout):
        observed["url"] = request.full_url
        observed["user_agent"] = request.get_header("User-agent")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(stage0_scope.urllib.request, "urlopen", fake_urlopen)

    assert stage0_scope._default_gamma_event_reader(
        "highest-temperature-in-toronto-on-august-31-2026"
    ) == expected
    assert observed == {
        "url": (
            "https://gamma-api.polymarket.com/events/slug/"
            "highest-temperature-in-toronto-on-august-31-2026"
        ),
        "user_agent": stage0_scope.GAMMA_USER_AGENT,
        "timeout": stage0_scope.GAMMA_TIMEOUT_SECONDS,
    }


def _gamma_payload():
    return build_current_gamma_event_payload(
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        alternate_token_id=ALTERNATE_TOKEN_ID,
    )


def test_wide_and_empty_books_are_structurally_eligible(tmp_path):
    event_path = _event_file(tmp_path)
    plan_path = tmp_path / "scope.json"

    payload = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        plan_path,
        now=NOW,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
            _book(ALTERNATE_TOKEN_ID, bids=[], asks=[]),
        ],
        gamma_reader=lambda _slug: _gamma_payload(),
    )

    assert payload["status"] == "PASS"
    assert payload["scope_count"] == 2
    assert payload["selected"]["token_id"] == TOKEN_ID
    assert payload["selected"]["best_ask"] - payload["selected"]["best_bid"] == pytest.approx(0.25)
    assert payload["alternates"][0]["token_id"] == ALTERNATE_TOKEN_ID
    assert payload["alternates"][0]["best_bid"] is None
    assert payload["alternates"][0]["best_ask"] is None
    assert "spread" not in payload["selected"]
    assert "midpoint" not in payload["selected"]
    assert "fee_rate" not in payload["selected"]
    assert "paper_quote_proof" not in payload["selected"]
    assert stage0_scope.load_stage0_scope_discovery_gate(plan_path, now=NOW)[
        "token_id"
    ] == TOKEN_ID


def test_crossed_book_remains_eligible_but_ranks_after_ordinary_book(tmp_path):
    event_path = _event_file(tmp_path)
    plan_path = tmp_path / "scope.json"

    payload = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        plan_path,
        now=NOW,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.60], asks=[0.40]),
            _book(ALTERNATE_TOKEN_ID, bids=[0.10], asks=[0.80]),
        ],
        gamma_reader=lambda _slug: _gamma_payload(),
    )

    assert payload["status"] == "PASS"
    assert payload["scope_count"] == 2
    assert payload["selected"]["token_id"] == ALTERNATE_TOKEN_ID
    assert payload["alternates"][0]["token_id"] == TOKEN_ID
    assert payload["alternates"][0]["best_bid"] > payload["alternates"][0]["best_ask"]


def test_soft_rank_prefers_narrower_ordinary_book_without_excluding_wide(tmp_path):
    event_path = _event_file(tmp_path)
    plan_path = tmp_path / "scope.json"

    payload = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        plan_path,
        now=NOW,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
            _book(ALTERNATE_TOKEN_ID, bids=[0.48], asks=[0.52]),
        ],
        gamma_reader=lambda _slug: _gamma_payload(),
    )

    assert payload["scope_count"] == 2
    assert payload["selected"]["token_id"] == ALTERNATE_TOKEN_ID
    assert payload["alternates"][0]["token_id"] == TOKEN_ID


def test_malformed_empty_token_fails_closed_without_index_error(tmp_path):
    event_path = _write_json(
        tmp_path / "malformed-events.json",
        build_stage0_event_metadata_payload(
            generated_at=NOW,
            target_date=TARGET_DATE,
            condition_id=CONDITION_ID,
            token_id="",
            alternate_token_id=ALTERNATE_TOKEN_ID,
        ),
    )

    with pytest.raises(RuntimeError, match="current_builtin_event"):
        stage0_scope.load_stage0_event_metadata_gate(
            event_path,
            TARGET_DATE,
            now=NOW,
        )


def test_old_metadata_age_is_telemetry_while_scope_plan_freshness_is_hard(tmp_path):
    generated_at = NOW - timedelta(days=30)
    event_path = _event_file(tmp_path, generated_at=generated_at)
    plan_path = tmp_path / "scope.json"

    payload = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        plan_path,
        now=NOW,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
        ],
        gamma_reader=lambda _slug: _gamma_payload(),
    )

    assert payload["status"] == "PASS"
    assert payload["event_metadata"]["file_sha256"] == hashlib.sha256(
        event_path.read_bytes()
    ).hexdigest()
    assert payload["event_metadata"]["generated_at_utc"] == generated_at.isoformat()
    assert payload["scope_policy"]["event_metadata_age_is_nonblocking_telemetry"] is True
    assert stage0_scope.load_stage0_scope_discovery_gate(plan_path, now=NOW)["ok"] is True

    stale = build_stage0_scope_payload(
        now=NOW,
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        event_metadata_file_sha256=hashlib.sha256(event_path.read_bytes()).hexdigest(),
        event_metadata_generated_at=generated_at,
        remaining_seconds=0,
        constrained=False,
    )
    stale_path = _write_json(tmp_path / "stale-scope.json", stale)
    with pytest.raises(RuntimeError, match="current"):
        stage0_scope.load_stage0_scope_discovery_gate(stale_path, now=NOW)


@pytest.mark.parametrize(
    "drift",
    [
        "event_closed",
        "event_inactive",
        "market_closed",
        "market_inactive",
        "superseded",
        "condition_mapping",
        "token_mapping",
    ],
)
def test_current_gamma_drift_blocks_scope_generation(tmp_path, drift):
    event_path = _event_file(tmp_path, generated_at=NOW - timedelta(days=30))
    plan_path = tmp_path / "scope.json"
    current = _gamma_payload()
    if drift == "event_closed":
        current["closed"] = True
    elif drift == "event_inactive":
        current["active"] = False
    elif drift == "market_closed":
        current["markets"][0]["closed"] = True
    elif drift == "market_inactive":
        current["markets"][0]["active"] = False
    elif drift == "superseded":
        current["id"] = "replacement-event"
    elif drift == "condition_mapping":
        current["markets"][0]["conditionId"] = "0x" + "3" * 64
    else:
        current["markets"][0]["clobTokenIds"] = json.dumps(
            [TOKEN_ID, "999"]
        )

    with pytest.raises(RuntimeError, match="current Gamma rebind"):
        stage0_scope.select_stage0_scope(
            event_path,
            TARGET_DATE,
            plan_path,
            now=NOW,
            book_reader=lambda _tokens: [
                _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
            ],
            gamma_reader=lambda _slug: current,
        )
    assert not plan_path.exists()


def test_constrained_generation_checks_only_the_containing_gamma_event(tmp_path):
    payload = build_stage0_event_metadata_payload(
        generated_at=NOW - timedelta(days=30),
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        alternate_token_id=ALTERNATE_TOKEN_ID,
    )
    second = build_stage0_event_metadata_payload(
        generated_at=NOW - timedelta(days=30),
        target_date=TARGET_DATE,
        condition_id="0x" + "2" * 64,
        token_id="201",
        alternate_token_id="202",
        market_id="seattle",
    )
    payload["locations"].extend(second["locations"])
    payload["source"]["event_count"] = 2
    payload["source"]["location_count"] = 2
    event_path = _write_json(tmp_path / "two-events.json", payload)
    calls = []

    def gamma_reader(event_slug):
        calls.append(event_slug)
        return _gamma_payload()

    result = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        tmp_path / "scope.json",
        expected_condition_id=CONDITION_ID,
        expected_token_id=TOKEN_ID,
        now=NOW,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
        ],
        gamma_reader=gamma_reader,
    )

    assert result["status"] == "PASS"
    assert calls == [result["selected"]["event_slug"]]
    assert len(result["current_gamma"]["event_contracts"]) == 1


def test_gamma_check_may_precede_plan_creation_clock(tmp_path, monkeypatch):
    event_path = _event_file(tmp_path, generated_at=NOW - timedelta(days=30))
    ticks = iter(
        [
            NOW - timedelta(seconds=3),
            NOW - timedelta(seconds=2),
            NOW - timedelta(seconds=1),
            NOW,
        ]
    )

    def stepped_utc_now(override=None):
        return override if override is not None else next(ticks)

    monkeypatch.setattr(stage0_scope, "utc_now", stepped_utc_now)
    plan_path = tmp_path / "scope.json"
    result = stage0_scope.select_stage0_scope(
        event_path,
        TARGET_DATE,
        plan_path,
        now=None,
        book_reader=lambda _tokens: [
            _book(TOKEN_ID, bids=[0.19], asks=[0.44]),
        ],
        gamma_reader=lambda _slug: _gamma_payload(),
    )

    assert result["current_gamma"]["checked_at_utc"] == (
        NOW - timedelta(seconds=1)
    ).isoformat()
    assert result["created_at_utc"] == NOW.isoformat()
    assert stage0_scope.load_stage0_scope_discovery_gate(
        plan_path,
        now=NOW,
    )["ok"] is True


def test_metadata_extra_key_fails_exact_shape_gate(tmp_path):
    payload = build_stage0_event_metadata_payload(
        generated_at=NOW,
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        alternate_token_id=ALTERNATE_TOKEN_ID,
    )
    payload["unexpected"] = True
    event_path = _write_json(tmp_path / "extra-key-events.json", payload)

    with pytest.raises(RuntimeError, match="exact_file_shape"):
        stage0_scope.load_stage0_event_metadata_gate(
            event_path,
            TARGET_DATE,
            now=NOW,
        )


def test_constrained_gate_rejects_unrehash_tamper(tmp_path):
    event_path = _event_file(tmp_path)
    digest = hashlib.sha256(event_path.read_bytes()).hexdigest()
    base = build_stage0_scope_payload(
        now=NOW,
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        event_metadata_file_sha256=digest,
    )

    tampered = json.loads(json.dumps(base))
    tampered["selected"]["best_ask"] = 0.99
    tampered_path = _write_json(tmp_path / "tampered.json", tampered)
    with pytest.raises(RuntimeError, match="plan_hash"):
        stage0_scope.load_stage0_scope_gate(
            tampered_path,
            TARGET_DATE,
            expected_condition_id=CONDITION_ID,
            expected_token_id=TOKEN_ID,
            now=NOW,
        )


def test_constrained_gate_rejects_rehashed_semantic_forgery(tmp_path):
    event_path = _event_file(tmp_path)
    base = build_stage0_scope_payload(
        now=NOW,
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        alternate_token_id=ALTERNATE_TOKEN_ID,
        event_metadata_file_sha256=hashlib.sha256(event_path.read_bytes()).hexdigest(),
    )

    def assert_gamma_block(payload, name):
        path = _write_json(tmp_path / name, _rehash(payload))
        with pytest.raises(RuntimeError, match="current_gamma_binding"):
            stage0_scope.load_stage0_scope_gate(
                path,
                TARGET_DATE,
                expected_condition_id=CONDITION_ID,
                expected_token_id=TOKEN_ID,
                now=NOW,
            )

    forged_event_id = json.loads(json.dumps(base))
    forged_event_id["current_gamma"]["event_contracts"][0]["event_id"] = (
        "forged-event"
    )
    assert_gamma_block(forged_event_id, "forged-event-id.json")

    stale_observation = json.loads(json.dumps(base))
    stale_observation["current_gamma"]["checked_at_utc"] = (
        NOW - timedelta(seconds=stage0_scope.PLAN_PREPARATION_MARGIN_SECONDS + 1)
    ).isoformat()
    assert_gamma_block(stale_observation, "stale-gamma-observation.json")

    status_forgery = json.loads(json.dumps(base))
    status_row = status_forgery["current_gamma"]["event_contracts"][0]
    status_row["contract"]["closed"] = True
    status_row["contract_sha256"] = stage0_scope._canonical_sha256(
        status_row["contract"]
    )
    status_row["staged_contract_sha256"] = status_row["contract_sha256"]
    slug = status_row["event_slug"]
    status_forgery["event_metadata"]["event_contracts"][slug]["closed"] = True
    assert_gamma_block(status_forgery, "forged-closed-status.json")

    metadata_mismatch = json.loads(json.dumps(base))
    mismatch_row = metadata_mismatch["current_gamma"]["event_contracts"][0]
    mismatch_row["contract"]["event_id"] = "forged-event"
    mismatch_row["event_id"] = "forged-event"
    mismatch_row["contract_sha256"] = stage0_scope._canonical_sha256(
        mismatch_row["contract"]
    )
    mismatch_row["staged_contract_sha256"] = mismatch_row["contract_sha256"]
    assert_gamma_block(metadata_mismatch, "staged-contract-mismatch.json")

    duplicate_event = json.loads(json.dumps(base))
    duplicate_event["current_gamma"]["event_contracts"].append(
        json.loads(
            json.dumps(duplicate_event["current_gamma"]["event_contracts"][0])
        )
    )
    assert_gamma_block(duplicate_event, "duplicate-constrained-event.json")

    gamma_tampered = json.loads(json.dumps(base))
    gamma_tampered["current_gamma"]["event_contracts"][0][
        "contract_sha256"
    ] = "d" * 64
    gamma_tampered_path = _write_json(
        tmp_path / "gamma-tampered.json",
        gamma_tampered,
    )
    with pytest.raises(RuntimeError, match="plan_hash"):
        stage0_scope.load_stage0_scope_gate(
            gamma_tampered_path,
            TARGET_DATE,
            expected_condition_id=CONDITION_ID,
            expected_token_id=TOKEN_ID,
            now=NOW,
        )

    gamma_extra = json.loads(json.dumps(base))
    gamma_extra["current_gamma"]["unexpected"] = True
    gamma_extra["plan_sha256"] = stage0_scope.stage0_scope_plan_sha256(
        gamma_extra
    )
    gamma_extra_path = _write_json(tmp_path / "gamma-extra.json", gamma_extra)
    with pytest.raises(RuntimeError, match="current_gamma_binding"):
        stage0_scope.load_stage0_scope_gate(
            gamma_extra_path,
            TARGET_DATE,
            expected_condition_id=CONDITION_ID,
            expected_token_id=TOKEN_ID,
            now=NOW,
        )

    extra = json.loads(json.dumps(base))
    extra["unexpected"] = True
    extra["plan_sha256"] = stage0_scope.stage0_scope_plan_sha256(extra)
    extra_path = _write_json(tmp_path / "extra-key.json", extra)
    with pytest.raises(RuntimeError, match="exact_schema_shape"):
        stage0_scope.load_stage0_scope_gate(
            extra_path,
            TARGET_DATE,
            expected_condition_id=CONDITION_ID,
            expected_token_id=TOKEN_ID,
            now=NOW,
        )

    base_path = _write_json(tmp_path / "base.json", base)
    with pytest.raises(RuntimeError, match="constrained_scope|selected_scope"):
        stage0_scope.load_stage0_scope_gate(
            base_path,
            TARGET_DATE,
            expected_condition_id=CONDITION_ID,
            expected_token_id=ALTERNATE_TOKEN_ID,
            now=NOW,
        )


def test_bound_metadata_detects_content_tamper(tmp_path):
    event_path = _event_file(tmp_path)
    observed = stage0_scope.load_stage0_event_metadata_gate(
        event_path,
        TARGET_DATE,
        now=NOW,
    )
    binding = {
        key: observed[key] for key in stage0_scope.EVENT_METADATA_BINDING_KEYS
    }
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    payload["locations"][0]["active_events"][0]["title"] = "Changed title"
    _write_json(event_path, payload)

    with pytest.raises(RuntimeError, match="differs from the scope binding"):
        stage0_scope.validate_bound_stage0_event_metadata(
            event_path,
            binding,
            target_date=TARGET_DATE,
            now=NOW,
        )
