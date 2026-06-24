import json

from weather.reporting.model_market_disagreement_analysis import (
    build_payload,
    rehydrate_audit_log,
    render_report,
    route_for_pattern,
    write_outputs,
    write_review_queue,
)


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


def _write_labels(path, rows):
    fieldnames = [
        "event_slug",
        "market_id",
        "target_date",
        "settlement_bucket",
        "settlement_unit",
        "settlement_source",
        "quality_grade",
        "winning_band",
        "finalized_at_utc",
    ]
    path.write_text(
        ",".join(fieldnames)
        + "\n"
        + "\n".join(
            ",".join(str(row.get(field, "")) for field in fieldnames)
            for row in rows
        )
        + "\n",
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
    assert payload["summary"]["ready_for_operator_review_count"] == 2
    assert payload["summary"]["settlement_watchlist_recommendation_count"] == 1
    assert ("nyc", "market_higher_than_model") in directions
    assert ("seattle", "model_higher_than_market") in directions
    assert any(row["category"] == "settlement_watchlist" for row in recommendations)
    assert any("under-allocation" in row["action"] for row in recommendations)
    assert any("over-allocation" in row["action"] for row in recommendations)
    routes = {
        (row["market_id"], row["direction"]): row["route"]["repair_lane"]
        for row in recommendations
    }
    assert routes[("nyc", "market_higher_than_model")] == "exact-band/winner-centering"
    assert routes[("seattle", "model_higher_than_market")] == "warm-tail dampening"
    queue_rows = payload["operator_review_queue"]["rows"]
    assert any(row["status"] == "WATCHLIST_PENDING_SETTLEMENT" for row in queue_rows)
    assert all(row["automatic_model_or_trading_change_allowed"] is False for row in queue_rows)


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
    queue_out = tmp_path / "review_queue.json"

    written_json, written_report = write_outputs(payload, json_out, report_out, review_queue_out=queue_out)
    written_queue = write_review_queue(payload, tmp_path / "review_queue_direct.json")

    assert "Model-Market Disagreement Audit Analysis" in report
    assert "## Recommendations" in report
    assert "## Operator Review Queue" in report
    assert "## Pending Watchlist" in report
    assert written_json.exists()
    assert written_report.exists()
    assert queue_out.exists()
    assert written_queue.exists()
    assert json.loads(written_json.read_text(encoding="utf-8"))["summary"]["deduped_audit_snapshots"] == 2
    queue = json.loads(queue_out.read_text(encoding="utf-8"))
    assert queue["schema_version"] == "model_market_disagreement_review_queue_v0.1"
    assert queue["policy"]["automatic_model_or_trading_change_allowed"] is False


def test_route_for_pattern_covers_source_state_and_residual_fallback_lanes():
    source_state_route = route_for_pattern({
        "market_closer_count": 1,
        "market_id": "nyc",
        "band_key": "gte:72",
        "range_label": "72+ F",
        "direction": "market_higher_than_model",
    })
    residual_route = route_for_pattern({
        "market_closer_count": 1,
        "market_id": "chicago",
        "band_key": "unknown",
        "range_label": "74-75 F",
        "direction": "unknown",
    })

    assert source_state_route["repair_lane"] == "source-state reliability"
    assert source_state_route["roadmap_owner"] == "Items 105, 136"
    assert residual_route["repair_lane"] == "market-specific residual repair"
    assert residual_route["owner"] == "chicago market residual repair"
    assert residual_route["automatic_model_or_trading_change_allowed"] is False


def test_rehydrate_audit_log_resolves_pending_and_excludes_partial_labels(tmp_path):
    target_date = "2099-06-23"
    log_path = tmp_path / "audit.jsonl"
    labels_csv = tmp_path / "market_day_labels.csv"
    rows = [
        _record("model-closer", market_id="nyc", range_label="70 F", model=0.92, market=0.20, fair=None, target_date=target_date),
        _record("market-closer", market_id="seattle", range_label="71 F", model=0.05, market=0.86, fair=None, target_date=target_date),
        _record("partial-label", market_id="miami", range_label="72 F", model=0.90, market=0.10, fair=None, target_date=target_date),
    ]
    _write_jsonl(log_path, rows)
    _write_labels(labels_csv, [
        {
            "event_slug": rows[0]["event_slug"],
            "market_id": rows[0]["market_id"],
            "target_date": target_date,
            "settlement_bucket": 70,
            "settlement_unit": "F",
            "settlement_source": "daily_summary",
            "quality_grade": "complete",
            "winning_band": "70 F",
            "finalized_at_utc": "2099-06-24T00:00:00+00:00",
        },
        {
            "event_slug": rows[1]["event_slug"],
            "market_id": rows[1]["market_id"],
            "target_date": target_date,
            "settlement_bucket": 71,
            "settlement_unit": "F",
            "settlement_source": "daily_summary",
            "quality_grade": "complete",
            "winning_band": "71 F",
            "finalized_at_utc": "2099-06-24T00:00:00+00:00",
        },
        {
            "event_slug": rows[2]["event_slug"],
            "market_id": rows[2]["market_id"],
            "target_date": target_date,
            "settlement_bucket": 72,
            "settlement_unit": "F",
            "settlement_source": "snapshot_high",
            "quality_grade": "partial",
            "winning_band": "72 F",
            "finalized_at_utc": "2099-06-24T00:00:00+00:00",
        },
    ])

    rehydration = rehydrate_audit_log(
        log_path=log_path,
        labels_csv=labels_csv,
        target_date=target_date,
        generated_at_utc="2099-06-24T01:00:00+00:00",
    )
    payload = build_payload(
        log_path=log_path,
        generated_at_utc="2099-06-24T01:01:00+00:00",
        rehydration_summary=rehydration,
    )
    report = render_report(payload)
    latest = {row["audit_key"]: row for row in payload["pending_watchlist"]}

    assert rehydration["status"] == "WARN"
    assert rehydration["rehydrated_count"] == 2
    assert rehydration["model_closer_rehydrated_count"] == 1
    assert rehydration["market_closer_rehydrated_count"] == 1
    assert rehydration["excluded_partial_label_count"] == 1
    assert rehydration["unresolved_after_rehydrate_count"] == 0
    assert payload["summary"]["pending_count"] == 0
    assert payload["summary"]["settlement_rehydration_excluded_count"] == 1
    assert latest == {}
    assert "## Settlement Rehydration" in report
    assert "## Rehydration Interpretation Changes" in report


def test_rehydrate_audit_log_blocks_complete_label_rows_that_cannot_resolve(tmp_path):
    target_date = "2099-06-23"
    log_path = tmp_path / "audit.jsonl"
    labels_csv = tmp_path / "market_day_labels.csv"
    row = _record("bad-band", range_label="not a band", model=0.60, market=0.10, fair=None, target_date=target_date)
    _write_jsonl(log_path, [row])
    _write_labels(labels_csv, [
        {
            "event_slug": row["event_slug"],
            "market_id": row["market_id"],
            "target_date": target_date,
            "settlement_bucket": 70,
            "settlement_unit": "F",
            "settlement_source": "daily_summary",
            "quality_grade": "complete",
            "winning_band": "70 F",
            "finalized_at_utc": "2099-06-24T00:00:00+00:00",
        },
    ])

    rehydration = rehydrate_audit_log(
        log_path=log_path,
        labels_csv=labels_csv,
        target_date=target_date,
        generated_at_utc="2099-06-24T01:00:00+00:00",
    )
    payload = build_payload(log_path=log_path, rehydration_summary=rehydration)

    assert rehydration["status"] == "BLOCK"
    assert rehydration["unresolved_after_rehydrate_count"] == 1
    assert rehydration["blockers"][0]["gate"] == "target_date_complete_label_rows_still_pending"
    assert payload["summary"]["pending_count"] == 1
