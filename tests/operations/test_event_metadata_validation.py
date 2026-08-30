import copy
import json
from unittest.mock import patch

import pytest

from weather.operations import event_metadata_validation as gate
from weather.operations.location_config_refresh import build_location_market_events


TARGET_DATE = "2026-06-24"
EVENT_SLUG = "highest-temperature-in-atlanta-on-june-24-2026"


def locations_payload():
    return {
        "schema_version": "location_registry_v0.1",
        "locations": [
            {
                "id": "atlanta",
                "city": "Atlanta",
                "polymarket": {
                    "series_slug": "atlanta-daily-weather",
                    "event_slug_prefix": "highest-temperature-in-atlanta-on",
                },
            }
        ],
    }


def market(*, yes="yes-token", no="no-token", condition="condition-1", active=True, closed=False):
    return {
        "id": "market-1",
        "conditionId": condition,
        "groupItemTitle": "80-81",
        "question": "Will the high be 80-81F?",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps([yes, no]),
        "enableOrderBook": True,
        "active": active,
        "closed": closed,
    }


def event(*, slug=EVENT_SLUG, event_id="event-1", markets=None):
    return {
        "id": event_id,
        "slug": slug,
        "title": "Highest temperature in Atlanta on June 24?",
        "endDate": "2026-06-24T23:00:00Z",
        "resolutionSource": "https://example.test/KATL",
        "active": True,
        "closed": False,
        "markets": [market()] if markets is None else markets,
    }


def generated_payload(events, generated_at="2026-06-24T10:00:00+00:00"):
    return build_location_market_events(
        locations_payload(),
        events,
        generated_at_utc=generated_at,
        offsets=[0],
    )


def validate(events, live_events=None, **overrides):
    return gate.build_validation_payload(
        target_date=TARGET_DATE,
        markets=["atlanta"],
        locations_payload=locations_payload(),
        event_metadata_payload=generated_payload(events),
        live_events=live_events if live_events is not None else events,
        fetch_live=False,
        now="2026-06-24T12:00:00+00:00",
        **overrides,
    )


def first_issue(payload):
    return payload["market_rows"][0]["first_issue"]


def test_validation_passes_when_generated_metadata_matches_live_gamma_tokens():
    payload = validate([event()])

    assert payload["schema_version"] == "event_metadata_validation_v0.1"
    assert payload["status"] == "PASS"
    assert payload["summary"]["pass_count"] == 1
    assert payload["market_rows"][0]["active_day_evidence_countable"] is True
    assert payload["validation_hash"]


def test_report_and_write_outputs_render_markdown_tables(tmp_path):
    payload = validate([event()])

    report = gate.render_report(payload)
    json_out, report_out = gate.write_outputs(
        payload,
        json_out=tmp_path / "event_metadata_validation.json",
        report_out=tmp_path / "event_metadata_validation.md",
    )

    assert "| Metric | Value |" in report
    assert "| Market | Status | Issues | First Issue | Command |" in report
    assert json_out.exists()
    assert report_out.exists()
    assert "| atlanta | PASS | 0 | - | -" in report_out.read_text(encoding="utf-8")


def test_stale_target_event_uses_refresh_remediation():
    stale_event = event(
        slug="highest-temperature-in-atlanta-on-june-23-2026",
        event_id="event-old",
    )
    payload = validate([stale_event], live_events=[event()])

    assert payload["status"] == "BLOCK"
    assert first_issue(payload)["code"] == "target_event_missing"
    assert first_issue(payload)["category"] == "stale_generated_metadata"
    assert first_issue(payload)["manual_review_required"] is False
    assert "location_config_refresh" in first_issue(payload)["remediation_command"]
    assert payload["summary"]["stale_count"] >= 1


def test_mismatched_token_map_requires_manual_review():
    generated = event(markets=[market(yes="yes-old")])
    live = event(markets=[market(yes="yes-new")])
    payload = validate([generated], live_events=[live])

    assert payload["status"] == "BLOCK"
    issue_codes = {row["code"] for row in payload["market_rows"][0]["issues"]}
    assert "token_map_hash_mismatch" in issue_codes
    row = payload["market_rows"][0]
    assert row["manual_review_required"] is True
    assert "review Polymarket" in row["remediation_command"]
    assert payload["summary"]["mismatch_count"] >= 1


def test_ambiguous_generated_target_events_block_countability():
    duplicate = copy.deepcopy(event(event_id="event-2"))
    payload = validate([event(), duplicate], live_events=[event()])

    assert payload["status"] == "BLOCK"
    assert first_issue(payload)["code"] == "ambiguous_generated_target_events"
    assert first_issue(payload)["category"] == "ambiguous_event_metadata"
    assert payload["summary"]["ambiguous_count"] == 1


def test_blank_live_clob_token_blocks_countability():
    payload = validate([event()], live_events=[event(markets=[market(yes="")])])

    issue_codes = {row["code"] for row in payload["market_rows"][0]["issues"]}
    assert "live_yes_token_id_blank" in issue_codes
    assert payload["summary"]["blank_token_count"] >= 1
    market_gate = gate.gate_for_market(payload, "atlanta")
    assert market_gate["ok"] is False
    assert market_gate["validation_hash"] == payload["validation_hash"]


def test_cli_require_pass_exits_nonzero_after_writing_block_outputs(tmp_path):
    blocked = validate([], live_events=[])
    with patch.object(gate, "build_validation_payload", return_value=blocked):
        with pytest.raises(SystemExit) as error:
            gate.main([
                "--target-date", TARGET_DATE,
                "--json-out", str(tmp_path / "validation.json"),
                "--report-out", str(tmp_path / "validation.md"),
                "--require-pass",
            ])

    assert error.value.code == 2
    assert (tmp_path / "validation.json").exists()
