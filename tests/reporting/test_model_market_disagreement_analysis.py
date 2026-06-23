import json

from weather.reporting.model_market_disagreement_analysis import build_payload, render_report, write_outputs


def _record(
    key,
    *,
    market_id="nyc",
    range_label="70-71 F",
    model=0.05,
    market=0.86,
    fair=1.0,
    revision=1,
    target_date="2099-06-23",
):
    outcome = None if fair is None else int(fair)
    model_distance = None if fair is None else abs(model - fair) * 100.0
    market_distance = None if fair is None else abs(market - fair) * 100.0
    if fair is None:
        closer = "pending_settlement"
    elif model_distance < market_distance:
        closer = "model"
    elif market_distance < model_distance:
        closer = "market"
    else:
        closer = "tie"
    return {
        "schema_version": "model_market_disagreement_audit_v0.1",
        "audit_key": key,
        "audit_revision": revision,
        "audited_at_utc": f"{target_date}T18:00:00+00:00",
        "event_slug": f"highest-temperature-in-{market_id}-on-june-23-2099",
        "market_id": market_id,
        "city": market_id.upper(),
        "target_date": target_date,
        "snapshot_id": f"{key}-snapshot",
        "captured_at_local": f"{target_date}T14:00:00-04:00",
        "range_label": range_label,
        "band_key": "eq:" + range_label.replace(" F", "").replace("-", "-"),
        "model_probability": model,
        "market_yes": market,
        "fair_value_probability": fair,
        "fair_value_percent": None if fair is None else fair * 100.0,
        "model_minus_market_points": (model - market) * 100.0,
        "gap_points": abs(model - market) * 100.0,
        "closer_source": closer,
        "model_distance_points": model_distance,
        "market_distance_points": market_distance,
        "outcome": outcome,
        "status": "pending_settlement" if fair is None else "resolved",
    }


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_build_payload_dedupes_revisions_and_finds_both_direction_patterns(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    _write_jsonl(log_path, [
        _record("nyc-70-old", fair=None, revision=1),
        _record("nyc-70-old", fair=1.0, revision=2),
        _record("sea-84", market_id="seattle", range_label="84-85 F", model=0.76, market=0.10, fair=0.0),
        _record("mia-90", market_id="miami", range_label="90-91 F", model=0.75, market=0.12, fair=None),
        _record("atl-82", market_id="atlanta", range_label="82-83 F", model=0.80, market=0.20, fair=1.0),
    ])

    payload = build_payload(log_path=log_path, generated_at_utc="2099-06-24T00:00:00+00:00")
    recommendations = payload["recommendations"]
    directions = {(row["market_id"], row["direction"]) for row in payload["priority_patterns"]}

    assert payload["schema_version"] == "model_market_disagreement_analysis_v0.1"
    assert payload["summary"]["raw_log_rows"] == 5
    assert payload["summary"]["deduped_audit_snapshots"] == 4
    assert payload["summary"]["superseded_revision_count"] == 1
    assert payload["summary"]["market_closer_count"] == 2
    assert payload["summary"]["model_closer_count"] == 1
    assert payload["summary"]["pending_count"] == 1
    assert ("nyc", "market_higher_than_model") in directions
    assert ("seattle", "model_higher_than_market") in directions
    assert any(row["category"] == "settlement_watchlist" for row in recommendations)
    assert any("under-allocation" in row["action"] for row in recommendations)
    assert any("over-allocation" in row["action"] for row in recommendations)


def test_render_and_write_outputs_include_actionable_sections(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    _write_jsonl(log_path, [
        _record("nyc-70", fair=1.0),
        _record("sea-84", market_id="seattle", range_label="84-85 F", model=0.76, market=0.10, fair=None),
    ])
    payload = build_payload(log_path=log_path, generated_at_utc="2099-06-24T00:00:00+00:00")
    report = render_report(payload)
    json_out = tmp_path / "analysis.json"
    report_out = tmp_path / "analysis.md"

    written_json, written_report = write_outputs(payload, json_out, report_out)

    assert "Model-Market Disagreement Audit Analysis" in report
    assert "## Recommendations" in report
    assert "## Pending Watchlist" in report
    assert written_json.exists()
    assert written_report.exists()
    assert json.loads(written_json.read_text(encoding="utf-8"))["summary"]["deduped_audit_snapshots"] == 2
