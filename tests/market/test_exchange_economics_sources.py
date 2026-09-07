"""Public economics capture must not turn partial responses into campaign absence."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json

import pytest

from weather.market import exchange_economics as core
from weather.market import exchange_economics_sources as sources


NOW = "2026-06-24T12:00:00+00:00"
TARGET = "2026-06-24"
CONDITION = "0x" + "a" * 64
ASSET = "0x" + "b" * 40


def reward(condition=CONDITION):
    return {
        "condition_id": condition, "total_daily_rate": 46,
        "rewards_min_size": 20, "rewards_max_spread": 4.5,
        "rewards_config": [{
            "id": 123, "asset_address": ASSET, "start_date": TARGET,
            "end_date": "2500-12-31", "rate_per_day": 46, "total_rewards": 0,
        }],
    }


def page(rows, cursor="LTE=", **overrides):
    return {"data": rows, "count": len(rows), "limit": 500, "next_cursor": cursor, **overrides}


def collect_pages(pages, **kwargs):
    requested = []
    pending = iter(pages)

    def fetch(url, *, timeout_seconds):
        assert timeout_seconds == 3
        requested.append(url)
        return next(pending)

    rows, evidence = core._fetch_current_rewards(fetch, timeout_seconds=3, **kwargs)
    return rows, evidence, requested


def test_terminal_empty_page_is_verified_empty_not_missing_data():
    rows, evidence, requested = collect_pages([page([])])
    assert rows == []
    assert len(requested) == 1
    proof = evidence[0]
    raw = base64.b64decode(proof["response_body_base64"])
    assert json.loads(raw) == page([])
    assert proof["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert proof["response_origin"] == "caller_supplied_canonical_json"


def test_cursor_chain_retains_every_page_and_exact_request():
    first, second = reward(), reward("0x" + "c" * 64)
    rows, evidence, requested = collect_pages([page([first], "AQ=="), page([second])])
    assert rows == [first, second]
    assert len(evidence) == 2
    assert "next_cursor" not in requested[0]
    assert "next_cursor=AQ%3D%3D" in requested[1]
    assert all(sources.response_evidence_valid(proof) for proof in evidence)


@pytest.mark.parametrize("field", ["data", "count", "limit", "next_cursor"])
def test_missing_required_page_field_cannot_establish_empty_result(field):
    payload = page([])
    del payload[field]
    with pytest.raises(ValueError, match="required page fields"):
        collect_pages([payload])


@pytest.mark.parametrize("payload", [None, [], 0, "empty"])
def test_wrong_top_level_json_shape_is_refused(payload):
    with pytest.raises(ValueError, match="required page fields"):
        collect_pages([payload])


@pytest.mark.parametrize(("field", "value"), [
    ("data", None), ("data", {}), ("count", True), ("count", 1),
    ("count", -1), ("count", "0"), ("limit", False), ("limit", 0),
    ("limit", 501), ("next_cursor", None), ("next_cursor", ""),
    ("next_cursor", " LTE="), ("next_cursor", "-1"), ("next_cursor", 1),
])
def test_invalid_page_metadata_is_refused(field, value):
    with pytest.raises(ValueError, match="invalid page metadata"):
        collect_pages([page([], **{field: value})])


def test_empty_nonterminal_page_does_not_prove_campaign_absence():
    with pytest.raises(ValueError, match="empty page lacks terminal"):
        collect_pages([page([], "AQ==")])


@pytest.mark.parametrize("separate_pages", [False, True])
def test_duplicate_conditions_are_not_overwritten_even_when_identical(separate_pages):
    first, second = reward(), reward()
    second["condition_id"] = "0x" + "A" * 64
    pages = [page([first], "AQ=="), page([second])] if separate_pages else [page([first, second])]
    with pytest.raises(ValueError, match="repeats a condition"):
        collect_pages(pages)


def test_conflicting_duplicate_condition_cannot_choose_last_campaign():
    first, second = reward(), reward()
    second["total_daily_rate"] = 100
    with pytest.raises(ValueError, match="repeats a condition"):
        collect_pages([page([first], "AQ=="), page([second])])


def test_repeated_cursor_and_exhausted_page_budget_fail_closed():
    pages = [page([reward()], "AQ=="), page([reward("0x" + "c" * 64)], "AQ==")]
    with pytest.raises(ValueError, match="repeated cursor"):
        collect_pages(pages)
    with pytest.raises(ValueError, match="exceeded 1 pages"):
        collect_pages(pages, max_pages=1)


@pytest.mark.parametrize(("field", "value"), [
    ("page_limit", 0), ("page_limit", 501), ("page_limit", True),
    ("max_pages", 0), ("max_pages", 51), ("max_pages", True),
])
def test_pagination_budget_is_validated_before_fetch(field, value):
    with pytest.raises(ValueError, match="current rewards page"):
        collect_pages([], **{field: value})


@pytest.mark.parametrize(("field", "value"), [
    ("condition_id", "wrong"), ("condition_id", None),
    ("total_daily_rate", -1), ("total_daily_rate", True),
    ("rewards_min_size", "20"), ("rewards_max_spread", None),
    ("rewards_config", None), ("rewards_config", {}),
])
def test_incomplete_condition_economics_are_refused(field, value):
    row = reward()
    row[field] = value
    with pytest.raises(ValueError, match="current rewards"):
        collect_pages([page([row])])


@pytest.mark.parametrize(("field", "value"), [
    ("id", None), ("id", True), ("asset_address", "USDC"),
    ("start_date", "2026-06-24T00:00:00Z"), ("end_date", None),
    ("end_date", "2026-06-23"), ("rate_per_day", -1), ("total_rewards", None),
])
def test_incomplete_allocation_identity_and_amounts_are_refused(field, value):
    row = reward()
    row["rewards_config"][0][field] = value
    with pytest.raises(ValueError, match="allocation is incomplete or invalid"):
        collect_pages([page([row])])


def test_duplicate_allocation_is_not_double_counted():
    row = reward()
    row["rewards_config"].append(deepcopy(row["rewards_config"][0]))
    with pytest.raises(ValueError, match="repeats an allocation"):
        collect_pages([page([row])])


def test_calendar_boundaries_are_retained_without_inventing_interval_semantics():
    row = reward()
    row["rewards_config"][0]["end_date"] = TARGET
    rows, _, _ = collect_pages([page([row])])
    assert rows[0]["rewards_config"][0]["end_date"] == TARGET


@pytest.mark.parametrize("body", [
    b'{"data": [], "data": [1]}', b'{"nested": {"id": 1, "id": 2}}',
    b'{"rate": NaN}', b'{"rate": Infinity}', b'{"rate": -Infinity}',
    b'{"rate": 1e999}', b'{invalid}', b'\xff',
])
def test_duplicate_or_nonfinite_raw_json_is_rejected(body):
    with pytest.raises(ValueError):
        sources.json_response_payload(body)


class PublicResponse(BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}


def test_default_public_json_capture_preserves_original_bytes_and_retrieval_time(monkeypatch):
    body = b'\xef\xbb\xbf{\r\n  "value": "original bytes", "number": 1.2500\r\n}\r\n'
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: PublicResponse(body))
    before = datetime.now(timezone.utc)
    payload, proof = core._default_fetch_json("https://clob.polymarket.com/rewards/markets/current")
    after = datetime.now(timezone.utc)
    assert payload == {"value": "original bytes", "number": 1.25}
    assert base64.b64decode(proof["response_body_base64"]) == body
    assert proof["response_sha256"] == hashlib.sha256(body).hexdigest()
    assert proof["response_bytes"] == len(body)
    assert proof["response_origin"] == "http_response_bytes"
    assert proof["request_method"] == "GET"
    assert before <= datetime.fromisoformat(proof["retrieved_at_utc"]) <= after
    assert sources.response_payload_matches(proof, payload)


def test_default_rule_capture_preserves_bom_and_line_endings(monkeypatch):
    body = b'\xef\xbb\xbf# Rules\r\n\r\nOriginal source.\r\n'
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: PublicResponse(body))
    text, proof = core._default_fetch_text("https://docs.polymarket.com/trading/fees.md")
    assert base64.b64decode(proof["response_body_base64"]) == body
    assert sources.response_payload_matches(proof, text, text=True)


def test_json_response_size_is_bounded_during_read(monkeypatch):
    monkeypatch.setattr(core, "MAX_SOURCE_RESPONSE_BYTES", 8)
    monkeypatch.setattr(core, "urlopen", lambda request, timeout: PublicResponse(b'{"long": "body"}'))
    with pytest.raises(ValueError, match="size limit"):
        core._default_fetch_json("https://clob.polymarket.com/rewards/markets/current")


def test_total_capture_budget_refuses_before_next_page(monkeypatch):
    monkeypatch.setattr(sources, "MAX_TOTAL_RESPONSE_BYTES", 1)
    with pytest.raises(ValueError, match="total size limit"):
        collect_pages([page([reward()], "AQ==")])


@pytest.mark.parametrize(("field", "value"), [
    ("response_sha256", "0" * 64), ("response_bytes", True),
    ("response_body_base64", "invalid!"), ("retrieved_at_utc", "2026-06-24T12:00:00"),
    ("retrieved_at_utc", None), ("response_origin", "verified_payment"),
])
def test_new_raw_evidence_is_checked_even_when_outer_source_hash_is_recomputed(field, value):
    snapshot = core.build_snapshot_payload(target_date=TARGET, verified_at_utc=NOW)
    proof = sources.response_evidence(
        b'{}', url=snapshot["source_verification"]["responses"][0]["url"],
        http_status=200, content_type="application/json", origin="http_response_bytes",
    )
    proof[field] = value
    snapshot["source_verification"]["responses"][0] = proof
    snapshot["source_hash"] = core.source_proof_hash(snapshot)
    snapshot["source_hash_sha256"] = snapshot["source_hash"]
    gate = core._check_snapshot_payload(snapshot, target_date=TARGET, now=NOW)
    assert gate["status"] == "BLOCK"
    assert "global_source_response_hashes_recorded" in gate["missing"]


def test_injected_raw_response_must_agree_with_parsed_payload_and_request():
    url = "https://clob.polymarket.com/rewards/markets/current"
    proof = sources.response_evidence(
        b'{"flag": true}', url=url, http_status=200,
        content_type="application/json", origin="http_response_bytes",
    )
    # Python's True == 1 must not hide a type change in the supplied projection.
    with pytest.raises(ValueError, match="differs from captured bytes"):
        core._call_fetch_json(lambda *args, **kwargs: ({"flag": 1}, proof), url, timeout_seconds=3)
    with pytest.raises(ValueError, match="request/status mismatch"):
        core._call_fetch_json(lambda *args, **kwargs: ({"flag": True}, proof), url + "?changed=1", timeout_seconds=3)


def test_additive_response_capture_changes_source_hash_not_economics_identity():
    original = core.build_snapshot_payload(target_date=TARGET, verified_at_utc=NOW)
    changed = deepcopy(original)
    proof = changed["source_verification"]["responses"][0]
    proof.update(sources.response_evidence(
        b'{}', url=proof["url"], http_status=200,
        content_type="application/json", origin="http_response_bytes",
    ))
    assert core.source_proof_hash(changed) != core.source_proof_hash(original)
    assert core.snapshot_hash(changed) == core.snapshot_hash(original)
    assert core.compare_snapshots(changed, original) == []
    assert sources.response_evidence_valid(original["source_verification"]["responses"][0])


@pytest.mark.parametrize("field", ["response_body_base64", "retrieved_at_utc", "response_origin", "request_method"])
def test_partially_recorded_new_response_proof_is_invalid(field):
    proof = sources.response_evidence(
        b"{}", url="https://clob.polymarket.com/rewards/markets/current",
        http_status=200, content_type="application/json", origin="http_response_bytes",
    )
    del proof[field]
    assert not sources.response_evidence_valid(proof)


@pytest.mark.parametrize("bad_page", [
    {}, page([], "AQ=="), page([reward(), reward()]),
])
def test_incomplete_rewards_collection_cannot_replace_existing_snapshot(tmp_path, monkeypatch, bad_page):
    snapshot_path = tmp_path / "economics.json"
    retained = b'{"retained": "previous complete snapshot"}\n'
    snapshot_path.write_bytes(retained)
    metadata_path = tmp_path / "events.json"
    metadata_path.write_text('{"locations": []}', encoding="utf-8")
    event_slug = "highest-temperature-in-toronto-on-june-24-2026"
    monkeypatch.setattr(core, "_event_rows_for_global_snapshot", lambda *_: ([{
        "location_id": "toronto", "event_date": TARGET, "event_slug": event_slug,
        "registry_markets": [],
    }], []))
    monkeypatch.setattr(core, "_fetch_global_rule_documents", lambda *args, **kwargs: [])

    def fetch(url, **kwargs):
        if "/events/slug/" in url:
            return {"id": "9", "slug": event_slug, "markets": []}
        return bad_page

    with pytest.raises(ValueError, match="current rewards"):
        core.collect_and_publish_global_snapshot(
            snapshot_path=snapshot_path, target_date=TARGET,
            event_metadata_path=metadata_path, now=NOW, fetch_json=fetch,
        )
    assert snapshot_path.read_bytes() == retained
