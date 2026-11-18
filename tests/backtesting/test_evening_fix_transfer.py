"""Evening-fix no-market read on transferred host outputs (evening_fix_transfer + scorer Stage 1/2).

Guards: master ruling 2026-10-31 for the evening-fix read - market_yes nulled at source by
``lockin_anchor_replay --no-market``; the scorer asserts null prices and computes no market Brier;
the transfer loader verifies the ledger hash chain, projects forecast fields only, drops price keys,
and opens labels only after the B2 reproduction check; window 2026-10-16..10-27 plus 10-28 only,
2026-10-29 never; Clarification 1 two-stage outcome and the Denver-excluded sensitivity.
All rows are synthetic fixtures; no real dated data is read.
"""
import json
from datetime import date, timedelta

import pytest

from weather.backtesting import evening_fix_scorer as scorer
from weather.backtesting import evening_fix_transfer as transfer
from weather.backtesting import lockin_anchor_replay as replay_cmd
from weather.backtesting.settlement_ledger import read_jsonl, upsert_ledger_record

AFTER_READ = date(2026, 10, 29)
BANDS = [
    {"label": "87F or below", "kind": "lte", "value": 87.0, "value_hi": 87.0, "market_yes": None},
    {"label": "88-89F", "kind": "eq", "value": 88.0, "value_hi": 89.0, "market_yes": None},
    {"label": "90F or higher", "kind": "gte", "value": 90.0, "value_hi": 90.0, "market_yes": None},
]
GOOD = [0.0, 0.95, 0.05]
BAD = [0.10, 0.60, 0.30]


def _window(n=12):
    return [scorer.WINDOW_START + timedelta(days=i) for i in range(n)]


def _rows(days, markets=scorer.US_MARKETS, new=GOOD, old=BAD, hours=(18, 21, 10), l1=0.0):
    rows = []
    for day in days:
        for market in markets:
            for hour in hours:
                rows.append({
                    "snapshot_id": f"{market}-{day}-{hour}", "market_id": market,
                    "event_slug": f"{market}|{day.isoformat()}", "target_date": day.isoformat(),
                    "hour": hour, "bands": [dict(b) for b in BANDS], "new_band_p": list(new),
                    "old_band_p": list(old), "l1_new_vs_recorded": l1, "model_version": "v0.5.12",
                    "lockin_anchor": {"source": "observed_station_rows", "bucket": 89},
                })
    return rows


def _labels(rows, countable=True):
    return {row["event_slug"]: {"settlement_bucket": 89, "promotion_countable": countable}
            for row in rows}


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _ledger(tmp_path, slugs, bucket=89, countable=True, name="ledger"):
    """Whole ledger rows written by the real append-only writer, then concatenated."""
    root = tmp_path / f"{name}_root"
    markets = set()
    for slug in sorted(slugs):
        market, day = slug.split("|")
        markets.add(market)
        upsert_ledger_record({
            "schema_version": "settlement_ledger_v2", "event_slug": slug, "market_id": market,
            "target_date": day, "settlement_bucket": bucket, "settlement_source": "daily_summary",
            "promotion_countable": countable, "finalized_at_utc": f"{day}T23:59:00+00:00",
            "evidence": {"five_time_provenance": {}, "raw_resolution_hashes": {}, "override_provenance": {}},
        }, root)
    rows = [row for market in sorted(markets) for row in read_jsonl(root / market / "ledger.jsonl")]
    return _jsonl(tmp_path / f"{name}_rows.jsonl", rows)


@pytest.fixture
def signed(tmp_path):
    prereg = tmp_path / "prereg.md"
    prereg.write_text("# evening fix prereg\n", encoding="utf-8")
    digest = scorer.file_sha256(prereg)
    log = tmp_path / "DECISION_LOG.md"
    log.write_text(f"| 2026-10-15 | evening-fix prereg signed, sha256 {digest} |\n", encoding="utf-8")
    return prereg, log


# --- 1. replay --no-market nulls market_yes at source ------------------------------

def test_replay_no_market_never_reads_the_price_column(tmp_path):
    (tmp_path / "snapshots_long.csv").write_text(
        "snapshot_id,range_label,bin_kind,bin_value,bin_value_hi,market_yes\n"
        "s1,88-89F,eq,88,89,0.42\n", encoding="utf-8")
    priced = replay_cmd.load_band_rows(tmp_path)
    blind = replay_cmd.load_band_rows(tmp_path, no_market=True)
    assert priced["s1"][0]["market_yes"] == 0.42
    assert "market_yes" not in blind["s1"][0]
    assert replay_cmd.band_descriptor(blind["s1"][0], no_market=True)["market_yes"] is None
    assert replay_cmd.band_descriptor(priced["s1"][0], no_market=True)["market_yes"] is None
    assert "--no-market" in replay_cmd.build_parser().format_help()


# --- 2. the scorer asserts null prices and computes no market Brier --------------------

def test_no_market_scorer_refuses_a_priced_band():
    rows = _rows(_window())
    rows[5]["bands"][1]["market_yes"] = 0.9
    with pytest.raises(scorer.ScoreRefused, match="carries a market price"):
        scorer.evaluate(rows, _labels(rows), use_market=False)


def test_no_market_scorer_computes_no_market_brier_and_stops_at_stage1():
    rows = _rows(_window())
    scored = scorer.score_rows(rows, _labels(rows), use_market=False)
    assert all(row["market"] is None for row in scored if row["scored"])
    result = scorer.evaluate(rows, _labels(rows), use_market=False)
    assert result["outcome"] == scorer.STAGE1_MET == "CONDITIONS 1-2 MET, condition 3 pending"
    assert result["final"] is False
    assert result["primary"]["old_minus_market_gap"] is None
    assert result["primary"]["material"] is None


@pytest.mark.parametrize("new,old,outcome", [(BAD, GOOD, "HARM"), (GOOD, GOOD, "NOT_CONFIRMED")])
def test_stage1_harm_and_not_confirmed_are_final(new, old, outcome):
    rows = _rows(_window(), new=new, old=old)
    result = scorer.evaluate(rows, _labels(rows), use_market=False)
    assert result["outcome"] == outcome and result["final"] is True
    assert scorer.stage2_outcome(result, 0.01) == {"outcome": outcome, "final": True, "stage2_applied": False}


def test_stage2_applies_condition_3_from_the_gap():
    rows = _rows(_window())
    stage1 = scorer.evaluate(rows, _labels(rows), use_market=False)
    estimate = stage1["primary"]["estimate"]
    assert estimate < 0
    assert scorer.stage2_outcome(stage1, -estimate / 0.05 * 0.99)["outcome"] == "PASS"
    assert scorer.stage2_outcome(stage1, -estimate / 0.05 * 10)["outcome"] == "NOT_CONFIRMED"
    with pytest.raises(scorer.ScoreRefused, match="MG-1"):
        scorer.stage2_outcome(stage1, None)


def test_denver_stays_in_primary_and_is_excluded_only_in_the_sensitivity():
    rows = _rows(_window(), markets=tuple(m for m in scorer.US_MARKETS if m != scorer.DENVER))
    rows += _rows(_window(), markets=(scorer.DENVER,), new=BAD, old=GOOD)
    result = scorer.evaluate(rows, _labels(rows), use_market=False)
    assert result["primary"]["markets_n"] == 11
    assert scorer.DENVER in result["primary"]["per_market"]
    sensitivity = result["denver_excluded_sensitivity"]
    assert sensitivity["markets_n"] == 10 and scorer.DENVER not in sensitivity["per_market"]
    assert sensitivity["markets_negative"] == 10 and sensitivity["decides_nothing"] is True
    assert result["primary"]["estimate"] > sensitivity["estimate"]


def test_h2_is_tested_but_conditional_after_stage1():
    rows = _rows(_window())
    for row in rows:
        row["v3_band_p"] = list(GOOD)
    h2 = scorer.evaluate(rows, _labels(rows), use_market=False)["h2_pre_lockin_floor_non_inferiority_00_16"]
    assert h2["tested"] is True and h2["conditional_on_stage2"] is True


# --- window: 10-16..10-27 plus 10-28 only; 10-29 never --------------------------------

def test_window_never_extends_to_10_29():
    rows = _rows(_window(5))
    result = scorer.evaluate(rows, _labels(rows), use_market=False)
    assert result["outcome"] == "VOID"
    assert result["window_dates"][-1] == "2026-10-28"
    assert "2026-10-29 is never added" in " ".join(result["void_reasons"])
    with pytest.raises(scorer.WindowStop):
        scorer.check_window_before_labels(rows, {r["event_slug"]: {"promotion_countable": True} for r in rows})


def test_window_check_uses_countability_metadata_only():
    rows = _rows(_window())
    meta = {r["event_slug"]: {"promotion_countable": True} for r in rows}
    assert scorer.check_window_before_labels(rows, meta)[-1] == "2026-10-27"


def test_scorer_refuses_a_replay_row_on_10_29(tmp_path):
    rows = _rows(_window(1), markets=("atlanta",)) + _rows([date(2026, 10, 29)], markets=("atlanta",))
    with pytest.raises(scorer.ScoreRefused, match="day 0"):
        scorer.load_replay_rows(_jsonl(tmp_path / "r.jsonl", rows))


# --- 3. transfer loader ----------------------------------------------------------------

def test_pass1_projects_forecast_fields_and_drops_price_keys():
    row = _rows(_window(1), markets=("atlanta",))[0]
    row.update({"best_bid": 0.4, "settlement_bucket": 89, "extra": {"mid_price": 0.5}})
    row["bands"][0]["market_no"] = 0.3
    projected = transfer.project_replay_row(row)
    assert "best_bid" not in projected and "settlement_bucket" not in projected and "extra" not in projected
    assert set(projected["bands"][0]) == set(transfer.BAND_FIELDS)
    assert transfer.drop_price_keys({"a": [{"yes_price": 1, "keep": 2}], "spread": 3}) == {"a": [{"keep": 2}]}
    row["bands"][0]["market_yes"] = 0.1
    with pytest.raises(transfer.TransferRefused, match="--no-market"):
        transfer.project_replay_row(row)


@pytest.mark.parametrize("day,match", [("2026-10-29", "day 0"), ("2026-11-02", "day 0"),
                                       ("2026-10-15", "outside")])
def test_transfer_refuses_rows_outside_the_window(tmp_path, day, match):
    row = _rows([date.fromisoformat(day)], markets=("atlanta",))[0]
    with pytest.raises(transfer.TransferRefused, match=match):
        transfer.load_replay(_jsonl(tmp_path / "r.jsonl", [row]))


def test_b2_stop_emits_the_per_date_table_when_no_commit_reproduces():
    good = _rows(_window(2), markets=("atlanta",))
    bad = _rows(_window(2), markets=("atlanta",), l1=0.5)
    mixed = good[:3] + bad[3:]
    with pytest.raises(transfer.ReproductionStop) as stop:
        transfer.select_reproducing_commit({"aaa": bad, "bbb": mixed},
                                           {"2026-10-16": ["c1"], "2026-10-17": ["c1", "c2"]})
    table = stop.value.table
    assert table["commits"]["bbb"]["per_date"]["2026-10-16"]["share"] == 1.0
    assert table["commits"]["bbb"]["per_date"]["2026-10-17"]["share"] == 0.0
    assert table["dates"]["2026-10-17"]["served_commits"] == ["c1", "c2"]
    assert table["dates"]["2026-10-16"]["served_model_versions"] == {"v0.5.12": 6}
    receipt = transfer.select_reproducing_commit({"aaa": bad, "bbb": good})
    assert receipt.commit == "bbb"


def test_reproduction_table_shows_vector_coverage_per_date_and_in_the_summary():
    rows = _rows(_window(2), markets=("atlanta",))   # 3 rows per date
    for row in rows[3:5]:                             # 10-17: only one row keeps its recorded vector
        row["l1_new_vs_recorded"] = None
    receipt = transfer.select_reproducing_commit({"aaa": rows})   # the pass rule is unchanged
    info = receipt.table["commits"]["aaa"]
    assert info["pass"] is True
    full = info["per_date"]["2026-10-16"]
    assert (full["all_rows"], full["rows_with_vector"], full["vector_coverage"]) == (3, 3, 1.0)
    thin = info["per_date"]["2026-10-17"]
    assert (thin["all_rows"], thin["rows_with_vector"]) == (3, 1)
    assert thin["vector_coverage"] == pytest.approx(1 / 3)
    assert (info["all_rows"], info["rows_with_vector"]) == (6, 4)
    assert info["vector_coverage"] == pytest.approx(4 / 6)
    for day in info["per_date"].values():
        assert {"all_rows", "rows_with_vector", "vector_coverage"} <= set(day)


def test_ledger_hash_chain_is_verified_and_tampering_refuses(tmp_path):
    slugs = {"atlanta|2026-10-16", "nyc|2026-10-16"}
    path = _ledger(tmp_path, slugs)
    ledger = transfer.TransferredLedger(path, slugs)
    assert ledger.verification == {slug: 1 for slug in sorted(slugs)}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["settlement_bucket"] = 90
    with pytest.raises(transfer.TransferRefused, match="hash chain"):
        transfer.TransferredLedger(_jsonl(tmp_path / "tampered.jsonl", rows), slugs)


def test_ledger_refuses_slugs_without_replay_rows_and_forbidden_dates(tmp_path):
    with pytest.raises(transfer.TransferRefused, match="no replay row"):
        transfer.TransferredLedger(_ledger(tmp_path, {"atlanta|2026-10-16"}), {"nyc|2026-10-16"})
    with pytest.raises(transfer.TransferRefused, match="day 0"):
        transfer.TransferredLedger(_ledger(tmp_path, {"atlanta|2026-10-29"}, name="d0"), {"atlanta|2026-10-29"})


def test_labels_open_only_with_a_reproduction_receipt(tmp_path):
    slugs = {"atlanta|2026-10-16"}
    ledger = transfer.TransferredLedger(_ledger(tmp_path, slugs), slugs)
    assert ledger.countability() == {"atlanta|2026-10-16": {"promotion_countable": True,
                                                            "promotion_countable_reason": None}}
    with pytest.raises(transfer.TransferRefused, match="reproduction"):
        ledger.labels(None)
    receipt = transfer.ReproductionReceipt("bbb", {})
    assert ledger.labels(receipt)["atlanta|2026-10-16"]["settlement_bucket"] == 89


# --- end to end through main (transfer mode) -------------------------------------------

def _transfer_argv(tmp_path, signed, replays, ledger, *extra):
    prereg, log = signed
    argv = ["--no-market", "--prereg", str(prereg), "--decision-log", str(log),
            "--ledger-rows", str(ledger), "--out", str(tmp_path / "result.json"), *extra]
    for commit, path in replays.items():
        argv += ["--replay", f"{commit}={path}"]
    return argv


def test_transfer_mode_scores_stage1(tmp_path, signed):
    rows = _rows(_window())
    replay = _jsonl(tmp_path / "replay.jsonl", rows)
    ledger = _ledger(tmp_path, {r["event_slug"] for r in rows})
    code = scorer.main(_transfer_argv(tmp_path, signed, {"8cdcb62e": replay}, ledger), today=AFTER_READ)
    assert code == 0
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["outcome"] == scorer.STAGE1_MET
    assert result["replay_commit"] == "8cdcb62e"
    assert len(result["ledger_records_verified"]) == 132


def test_transfer_mode_b2_stop_reads_no_ledger(tmp_path, signed, monkeypatch):
    replay = _jsonl(tmp_path / "replay.jsonl", _rows(_window(), l1=0.5))

    def no_ledger(*args, **kwargs):
        raise AssertionError("ledger opened before the reproduction check passed")

    monkeypatch.setattr(transfer, "TransferredLedger", no_ledger)
    code = scorer.main(_transfer_argv(tmp_path, signed, {"aaa": replay}, tmp_path / "missing.jsonl"),
                       today=AFTER_READ)
    assert code == scorer.STOP_EXIT
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["stop"] == "B2_REPRODUCTION"
    assert result["reproduction_table"]["commits"]["aaa"]["pass"] is False


def test_transfer_mode_window_stop_opens_no_label(tmp_path, signed, monkeypatch):
    rows = _rows(_window(5))
    replay = _jsonl(tmp_path / "replay.jsonl", rows)
    ledger = _ledger(tmp_path, {r["event_slug"] for r in rows})

    def no_labels(self, receipt):
        raise AssertionError("labels opened although the window would need 10-29")

    monkeypatch.setattr(transfer.TransferredLedger, "labels", no_labels)
    code = scorer.main(_transfer_argv(tmp_path, signed, {"aaa": replay}, ledger), today=AFTER_READ)
    assert code == scorer.STOP_EXIT
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["stop"] == "WINDOW_NEEDS_FORBIDDEN_DATE"


def test_transfer_mode_requires_no_market(tmp_path, signed, capsys):
    replay = _jsonl(tmp_path / "replay.jsonl", _rows(_window(1), markets=("atlanta",)))
    argv = [a for a in _transfer_argv(tmp_path, signed, {"aaa": replay}, tmp_path / "l.jsonl") if a != "--no-market"]
    assert scorer.main(argv, today=AFTER_READ) == scorer.REFUSED_EXIT
    assert "requires --no-market" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()
