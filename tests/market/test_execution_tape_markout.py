"""Hermetic tests for the execution-tape maker markout (synthetic tape + midpoints in tmp_path)."""

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from weather.market import execution_tape_markout as markout


SLUG = "highest-temperature-in-nyc-on-june-10-2026"
TARGET = "2026-06-10"
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
TOKEN = "111"
TOKEN_WITHOUT_BOOK = "222"
SUMMARY_COLUMNS = [
    "captured_at_utc", "event_slug", "market_id", "range_label", "bin_kind", "bin_value",
    "bin_value_hi", "outcome", "clob_token_id", "best_bid", "best_ask", "midpoint",
]


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def trade_row(index, *, price, size, side, at, token=TOKEN, slug=SLUG, target=TARGET, market="nyc"):
    row = {
        "asset_id": token,
        "event_slug": slug,
        "event_type": "last_trade_price",
        "fee_rate_bps": "0",
        "market": "0x" + "ab" * 32,
        "market_id": market,
        "price": str(price),
        "size": str(size),
        "target_date": target,
        "timestamp": str(int(utc(at).timestamp() * 1000)),
        "trade_time_utc": utc(at).isoformat(),
        "transaction_hash": "0x" + f"{index:064x}",
    }
    if side is not None:
        row["side"] = side
    return row


def write_tape(root, rows, *, slug=SLUG, raw_lines=()):
    tape = root / slug / "execution_tape"
    tape.mkdir(parents=True, exist_ok=True)
    with (tape / "trades-00000.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        for line in raw_lines:
            handle.write(line + "\n")


def book_row(at, bid, ask, *, token=TOKEN, slug=SLUG, outcome="Yes"):
    return {
        "captured_at_utc": utc(at).isoformat(),
        "event_slug": slug,
        "market_id": "nyc",
        "range_label": "78-79 F",
        "bin_kind": "eq",
        "bin_value": "78",
        "bin_value_hi": "79",
        "outcome": outcome,
        "clob_token_id": token,
        "best_bid": "" if bid is None else str(bid),
        "best_ask": "" if ask is None else str(ask),
        "midpoint": "",
    }


def write_summary(root, rows, *, slug=SLUG):
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "order_books_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def standard_books():
    return [
        book_row("2026-06-10T14:59:50", 0.57, 0.59),   # pre-trade mid 0.58
        book_row("2026-06-10T15:01:05", 0.54, 0.56),   # +1m mark 0.55 (5 s late)
        book_row("2026-06-10T15:05:10", 0.49, 0.51),   # +5m mark 0.50
        book_row("2026-06-10T15:30:20", 0.39, 0.41),   # +30m mark 0.40
    ]


def standard_trades():
    return [
        trade_row(1, price="0.60", size="100", side="BUY", at="2026-06-10T15:00:00"),
        trade_row(2, price="0.50", size="300", side="SELL", at="2026-06-10T15:00:00"),
        trade_row(3, price="0.20", size="10", side="BUY", at="2026-06-10T15:00:00", token=TOKEN_WITHOUT_BOOK),
        trade_row(4, price="0.90", size="50", side="BUY", at="2026-06-11T03:50:00"),
    ]


def standard_root(tmp_path):
    root = tmp_path / "snapshots"
    write_tape(root, standard_trades())
    write_summary(root, standard_books())
    (root / SLUG / "settlement.json").write_text(json.dumps({"settlement_bucket": 78}), encoding="utf-8")
    return root


def build(root, **kwargs):
    kwargs.setdefault("dates", [date(2026, 6, 10)])
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("bootstrap_replicates", 50)
    return markout.build_markout_report(root, **kwargs)


def test_module_under_test_is_this_checkout():
    # The venv is an editable install of another tree; a silent wrong import proves nothing.
    assert Path(markout.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[2])


def test_maker_side_is_the_opposite_of_the_aggressor():
    assert markout.maker_side_from_aggressor("BUY") == markout.MAKER_SOLD
    assert markout.maker_side_from_aggressor("sell ") == markout.MAKER_BOUGHT
    assert markout.maker_side_from_aggressor(None) is None
    assert markout.maker_side_from_aggressor("HOLD") is None


def test_quote_rule_fallback_direction_and_ties():
    assert markout.maker_side_from_quote_rule(0.60, 0.58) == markout.MAKER_SOLD
    assert markout.maker_side_from_quote_rule(0.56, 0.58) == markout.MAKER_BOUGHT
    assert markout.maker_side_from_quote_rule(0.58, 0.58) is None
    assert markout.maker_side_from_quote_rule(0.58, None) is None


def test_markout_sign_for_both_maker_sides():
    assert markout.maker_markout(markout.MAKER_SOLD, 0.60, 0.55) == pytest.approx(0.05)
    assert markout.maker_markout(markout.MAKER_SOLD, 0.60, 0.70) == pytest.approx(-0.10)
    assert markout.maker_markout(markout.MAKER_BOUGHT, 0.60, 0.55) == pytest.approx(-0.05)
    assert markout.maker_markout(markout.MAKER_BOUGHT, 0.60, 0.70) == pytest.approx(0.10)
    with pytest.raises(ValueError):
        markout.maker_markout("sideways", 0.5, 0.5)


def test_rebate_formula():
    assert markout.maker_rebate_per_share(0.5) == pytest.approx(0.003125)
    assert markout.maker_rebate_per_share(0.0) == 0.0
    assert markout.maker_rebate_per_share(1.0) == 0.0
    assert markout.maker_rebate_per_share(0.6) == pytest.approx(0.003)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.0, "p<0.1"), (0.099, "p<0.1"), (0.1, "0.1-0.3"), (0.299, "0.1-0.3"), (0.3, "0.3-0.7"),
        (0.699, "0.3-0.7"), (0.7, "0.7-0.9"), (0.9, "0.7-0.9"), (0.901, ">0.9"), (1.0, ">0.9"),
    ],
)
def test_price_bucket_edges(price, expected):
    assert markout.price_bucket(price) == expected
    assert expected in markout.PRICE_BUCKETS


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (-0.01, "after_close"), (0.0, "<1h"), (0.999, "<1h"), (1.0, "1-6h"), (5.999, "1-6h"),
        (6.0, "6-24h"), (24.0, "6-24h"), (24.001, ">24h"),
    ],
)
def test_hours_to_close_bucket_edges(hours, expected):
    assert markout.hours_to_close_bucket(hours) == expected
    assert expected in markout.HOURS_TO_CLOSE_BUCKETS


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0.5, "<10"), (9.99, "<10"), (10, "10-100"), (99.9, "10-100"), (100, "100-1000"), (999, "100-1000"), (1000, ">=1000")],
)
def test_size_bucket_edges(size, expected):
    assert markout.size_bucket(size) == expected
    assert expected in markout.SIZE_BUCKETS


def test_market_close_uses_the_market_local_day_end():
    close, known = markout.market_close_utc("nyc", date(2026, 6, 10))
    assert known is True
    assert close == datetime(2026, 6, 11, 4, 0, tzinfo=timezone.utc)
    close, known = markout.market_close_utc("not-a-market", date(2026, 6, 10))
    assert known is False
    assert close == datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc)


def test_slug_date_parsing():
    assert markout.target_date_from_slug(SLUG) == date(2026, 6, 10)
    assert markout.target_date_from_slug("highest-temperature-in-nyc-on-smarch-10-2026") is None
    assert markout.target_date_from_slug("highest-temperature-in-nyc-on-june-31-2026") is None
    assert markout.target_date_from_slug("not-an-event") is None


def test_midpoint_lookup_tolerance_and_direction():
    series = markout.MidpointSeries()
    series.add("t", 200.0, 0.40)
    series.add("t", 100.0, 0.50)   # out of order on purpose
    assert series.at_or_after("t", 100.0, 0.0) == 0.50
    assert series.at_or_after("t", 90.0, 10.0) == 0.50
    assert series.at_or_after("t", 89.0, 10.0) is None
    assert series.at_or_after("t", 101.0, 99.0) == 0.40
    assert series.at_or_after("t", 201.0, 1000.0) is None
    assert series.at_or_before("t", 150.0, 50.0) == 0.50
    assert series.at_or_before("t", 150.0, 49.0) is None
    assert series.at_or_before("t", 99.0, 1000.0) is None
    assert series.at_or_after("missing", 0.0, 1000.0) is None
    assert series.point_count() == 2
    assert series.point_count("missing") == 0


def test_one_sided_books_are_skipped_unless_bounded():
    one_sided = {"best_bid": "0.999", "best_ask": ""}
    assert markout.midpoint_from_summary_row(one_sided, "skip") == (None, "one_sided")
    mid, status = markout.midpoint_from_summary_row(one_sided, "bound")
    assert status == "one_sided"
    assert mid == pytest.approx(0.9995)
    assert markout.midpoint_from_summary_row({"best_bid": "", "best_ask": ""}, "bound") == (None, "empty")
    assert markout.midpoint_from_summary_row({"best_bid": "0.6", "best_ask": "0.5"}, "skip") == (None, "crossed")
    mid, status = markout.midpoint_from_summary_row({"best_bid": "0.4", "best_ask": "0.5"}, "skip")
    assert (status, mid) == ("two_sided", pytest.approx(0.45))


def test_token_settlement_payoff_for_yes_and_no_tokens():
    yes = {"bin_kind": "eq", "bin_value": "78", "bin_value_hi": "79", "outcome": "yes"}
    no = {**yes, "outcome": "no"}
    assert markout.token_settlement_payoff(yes, 79) == 1.0
    assert markout.token_settlement_payoff(no, 79) == 0.0
    assert markout.token_settlement_payoff(yes, 80) == 0.0
    assert markout.token_settlement_payoff(no, 80) == 1.0
    assert markout.token_settlement_payoff({**yes, "bin_kind": "gte"}, 90) == 1.0
    assert markout.token_settlement_payoff({**yes, "bin_kind": "lte"}, 90) == 0.0
    assert markout.token_settlement_payoff(yes, None) is None
    assert markout.token_settlement_payoff(None, 78) is None
    assert markout.token_settlement_payoff({**yes, "outcome": ""}, 78) is None


def test_end_to_end_markouts_weights_and_unmarkable_counts(tmp_path):
    report = build(standard_root(tmp_path))

    counts = report["counts"]
    assert counts["trades_accepted"] == 4
    assert counts["trades_analysed"] == 4
    assert counts["maker_side_recorded"] == 4
    assert counts["maker_side_quote_rule_fallback"] == 0
    assert report["aggressor_side"]["recorded_on_every_analysed_trade"] is True
    assert report["aggressor_side"]["quote_rule_checkable_trades"] == 2
    assert report["aggressor_side"]["quote_rule_agreement_rate"] == 1.0

    # Trade 3 has no book at all; trade 4 has no capture after it.  Counted, never dropped.
    assert report["unmarkable"] == {"1m": 2, "5m": 2, "30m": 2, "settlement": 1}
    assert report["unmarkable_reasons"]["5m"] == {
        "no_midpoints_for_token": 1,
        "no_midpoint_within_tolerance": 1,
    }
    assert report["unmarkable_reasons"]["settlement"] == {"token_band_unknown": 1}

    overall = report["results"]["overall"]["all"]
    five = overall["5m"]
    assert five["markable_trades"] == 2
    assert five["markable_shares"] == pytest.approx(400.0)
    assert five["share_weighted"]["mean_markout"] == pytest.approx(0.025)      # (100*0.10 + 300*0.0) / 400
    assert five["trade_weighted"]["mean_markout"] == pytest.approx(0.05)       # (0.10 + 0.0) / 2
    assert five["share_weighted"]["mean_rebate"] == pytest.approx(0.00309375)
    assert five["share_weighted"]["mean_net"] == pytest.approx(0.025 + 0.00309375)
    assert five["trade_weighted"]["mean_net"] == pytest.approx(0.05 + (0.003 + 0.003125) / 2)
    assert overall["1m"]["trade_weighted"]["mean_markout"] == pytest.approx(0.05)   # both sides +0.05
    assert overall["30m"]["share_weighted"]["mean_markout"] == pytest.approx((100 * 0.20 - 300 * 0.10) / 400)
    assert overall["settlement"]["markable_trades"] == 3
    assert overall["settlement"]["trade_weighted"]["mean_markout"] == pytest.approx(0.0)   # -0.40, +0.50, -0.10
    assert overall["settlement"]["share_weighted"]["mean_markout"] == pytest.approx(105.0 / 450.0)

    assert report["results"]["maker_side"]["sold"]["5m"]["trade_weighted"]["mean_markout"] == pytest.approx(0.10)
    assert report["results"]["maker_side"]["bought"]["5m"]["trade_weighted"]["mean_markout"] == pytest.approx(0.0)
    assert set(report["results"]["market"]) == {"nyc"}
    assert set(report["results"]["hours_to_close"]) == {"6-24h", "<1h"}
    assert report["results"]["hours_to_close"]["<1h"]["settlement"]["markable_trades"] == 1
    assert set(report["results"]["price"]["0.7-0.9"]) == {"settlement"}
    assert set(report["results"]["size"]) == {"10-100", "100-1000"}

    # One date cluster: no interval, flagged on every cell, and no verdict can be bought.
    assert five["date_clusters"] == 1
    assert five["underpowered"] is True
    assert five["interval_flag"] == "UNDERPOWERED"
    assert five["share_weighted"]["net_interval_90"] is None
    assert report["primary_metric"]["cell"] == five
    assert report["decision"]["verdict"] == "R_NOT_SUPPLIED"
    assert build(standard_root(tmp_path / "again"), reward_per_share=0.01)["decision"]["verdict"] == "INCONCLUSIVE"
    assert any("REBATE IS NOMINAL" in warning for warning in report["warnings"])
    assert "UNDERPOWERED" in markout.render_markdown(report)


def test_horizon_tolerance_turns_late_marks_into_unmarkable(tmp_path):
    report = build(standard_root(tmp_path), tolerance_seconds=3.0)
    assert report["unmarkable"]["1m"] == 4      # the +1m capture is 5 s late
    assert "1m" not in report["results"].get("overall", {}).get("all", {})
    assert report["counts"]["trades_analysed"] == 4


def test_missing_aggressor_side_falls_back_loudly_to_the_quote_rule(tmp_path):
    root = tmp_path / "snapshots"
    write_tape(root, [
        trade_row(1, price="0.60", size="100", side=None, at="2026-06-10T15:00:00"),
        trade_row(2, price="0.20", size="10", side=None, at="2026-06-10T15:00:00", token=TOKEN_WITHOUT_BOOK),
    ])
    write_summary(root, standard_books())

    report = build(root)

    assert report["counts"]["maker_side_quote_rule_fallback"] == 1
    assert report["counts"]["side_undetermined_skipped"] == 1
    assert report["counts"]["trades_analysed"] == 1
    assert report["aggressor_side"]["recorded_on_every_analysed_trade"] is False
    assert any("AGGRESSOR SIDE NOT RECORDED" in warning for warning in report["warnings"])
    flagged = report["results"]["maker_side_source"]
    assert set(flagged) == {markout.SIDE_SOURCE_QUOTE_RULE}
    # 0.60 printed above the 0.58 pre-trade mid: buy aggressor, maker sold, +5m mark 0.50.
    assert report["results"]["maker_side"]["sold"]["5m"]["trade_weighted"]["mean_markout"] == pytest.approx(0.10)


def test_malformed_lines_are_counted_and_skipped(tmp_path):
    root = tmp_path / "snapshots"
    write_tape(
        root,
        standard_trades()[:2],
        raw_lines=["{not json", "[1, 2]", json.dumps({"asset_id": TOKEN, "price": "1.7", "size": "1"})],
    )
    write_summary(root, standard_books())

    report = build(root)

    assert report["counts"]["malformed_lines_skipped"] == 2
    assert report["counts"]["invalid_price_or_token_skipped"] == 1
    assert report["counts"]["trades_analysed"] == 2
    assert any("malformed" in warning for warning in report["warnings"])


def test_repeated_public_observations_are_collapsed_by_identity(tmp_path):
    root = tmp_path / "snapshots"
    first = standard_trades()[0]
    write_tape(root, [first, dict(first)])
    write_summary(root, standard_books())

    assert build(root)["counts"]["repeated_identity_observations_collapsed"] == 1
    kept = build(root, collapse_repeated_identities=False)
    assert kept["counts"]["repeated_identity_observations_collapsed"] == 0
    assert kept["counts"]["trades_analysed"] == 2


def test_max_trades_truncation_is_reported(tmp_path):
    report = build(standard_root(tmp_path), max_trades=2)
    assert report["counts"]["trades_accepted"] == 2
    assert report["events_truncated_by_max_trades"] == [SLUG]
    assert any("TRUNCATED" in warning for warning in report["warnings"])
    with pytest.raises(markout.MarkoutError):
        build(standard_root(tmp_path / "zero"), max_trades=0)


def test_open_dates_are_refused_unless_explicitly_allowed(tmp_path):
    root = standard_root(tmp_path)
    just_after = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    assert markout.date_is_closed(date(2026, 6, 10), just_after) is False
    assert markout.date_is_closed(date(2026, 6, 10), datetime(2026, 6, 12, 0, 0, tzinfo=timezone.utc)) is True
    with pytest.raises(markout.MarkoutError):
        build(root, now=just_after)
    assert build(root, now=just_after, allow_open_dates=True)["counts"]["trades_analysed"] == 4


def test_default_selection_takes_the_most_recent_closed_dates(tmp_path):
    root = tmp_path / "snapshots"
    for day in (8, 9, 10, 19):
        slug = f"highest-temperature-in-nyc-on-june-{day}-2026"
        write_tape(
            root,
            [trade_row(day, price="0.5", size="20", side="BUY", at=f"2026-06-{day:02d}T15:00:00",
                       slug=slug, target=f"2026-06-{day:02d}")],
            slug=slug,
        )
    (root / "not-an-event-folder").mkdir()

    report = build(root, dates=None, recent_dates=2)

    assert report["parameters"]["dates_selected"] == ["2026-06-09", "2026-06-10"]   # 06-19 is still open
    assert report["events_read"] == 2
    assert report["counts"]["trades_analysed"] == 2
    assert report["unmarkable"]["5m"] == 2
    only_chicago = build(root, dates=None, recent_dates=2, markets={"chicago"})
    assert only_chicago["events_read"] == 0


def test_empty_input_yields_a_valid_zero_report(tmp_path):
    empty_root = tmp_path / "snapshots"
    empty_root.mkdir()
    for root in (empty_root, tmp_path / "does-not-exist"):
        report = build(root, dates=None)
        assert report["counts"]["trades_analysed"] == 0
        assert report["counts"]["tape_lines_read"] == 0
        assert report["unmarkable"] == {"1m": 0, "5m": 0, "30m": 0, "settlement": 0}
        assert report["results"] == {}
        assert report["primary_metric"]["cell"] is None
        assert report["decision"]["verdict"] == "R_NOT_SUPPLIED"
        json.loads(json.dumps(report, allow_nan=False))
        assert "Execution-tape maker markout" in markout.render_markdown(report)


def _cell_with_clusters(count):
    cell = markout.CellAccumulator()
    for index in range(count):
        for trade in range(3):
            cell.add(f"2026-06-{index + 1:02d}", 10.0 * (trade + 1), -0.05 + 0.01 * index + 0.002 * trade, 0.003)
    return cell


def test_cluster_bootstrap_is_deterministic_for_a_fixed_seed():
    cell = _cell_with_clusters(12)
    first = markout.cluster_bootstrap_intervals(cell.by_date, seed=7, cell_key="overall|all|5m", replicates=400)
    second = markout.cluster_bootstrap_intervals(cell.by_date, seed=7, cell_key="overall|all|5m", replicates=400)
    assert first == second
    summary = markout.summarize_cell(cell, seed=7, cell_key="overall|all|5m", replicates=400)
    assert summary["share_weighted"]["net_interval_90"] == first["share_net"]
    low, high = first["share_net"]
    assert low < summary["share_weighted"]["mean_net"] < high
    low, high = first["trade_markout"]
    assert low < summary["trade_weighted"]["mean_markout"] < high
    # A constant rebate shifts the net interval by exactly that constant.
    assert first["trade_net"][0] == pytest.approx(first["trade_markout"][0] + 0.003)


def test_underpowered_flag_below_ten_date_clusters():
    nine = markout.summarize_cell(_cell_with_clusters(9), seed=1, cell_key="k", replicates=100)
    ten = markout.summarize_cell(_cell_with_clusters(10), seed=1, cell_key="k", replicates=100)
    one = markout.summarize_cell(_cell_with_clusters(1), seed=1, cell_key="k", replicates=100)
    assert (nine["date_clusters"], nine["underpowered"], nine["interval_flag"]) == (9, True, "UNDERPOWERED")
    assert nine["share_weighted"]["net_interval_90"] is not None
    assert (ten["date_clusters"], ten["underpowered"], ten["interval_flag"]) == (10, False, "")
    assert one["underpowered"] is True
    assert one["share_weighted"]["net_interval_90"] is None


def _primary(interval, *, clusters=12):
    return {
        "date_clusters": clusters,
        "underpowered": clusters < markout.MIN_DATE_CLUSTERS,
        "share_weighted": {"net_interval_90": interval},
    }


def test_preregistered_decision_rule():
    assert markout.decision_verdict(_primary([-0.03, -0.02]), 0.01)["verdict"] == "KILL-SIGNAL"
    assert markout.decision_verdict(_primary([0.0, 0.01]), 0.01)["verdict"] == "SUPPORTIVE"
    assert markout.decision_verdict(_primary([-0.02, 0.0]), 0.01)["verdict"] == "INCONCLUSIVE"
    underpowered = markout.decision_verdict(_primary([-0.03, -0.02], clusters=9), 0.01)
    assert (underpowered["verdict"], underpowered["reason"]) == ("INCONCLUSIVE", "UNDERPOWERED")
    assert markout.decision_verdict(_primary([-0.03, -0.02]), None)["verdict"] == "R_NOT_SUPPLIED"
    assert markout.decision_verdict(None, 0.01)["verdict"] == "INCONCLUSIVE"


def test_refuses_to_write_under_a_data_tree(tmp_path):
    report = build(tmp_path / "does-not-exist", dates=None)
    literal = tmp_path / "data" / "out"
    with pytest.raises(markout.MarkoutError):
        markout.write_outputs(report, literal)
    assert not literal.exists()
    repo_data_root = tmp_path / "repo" / "datastore"
    with pytest.raises(markout.MarkoutError):
        markout.write_outputs(report, repo_data_root / "reports", data_root=repo_data_root)
    assert not repo_data_root.exists()

    paths = markout.write_outputs(report, tmp_path / "out", data_root=repo_data_root)
    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))["report_kind"] == "execution_tape_markout"
    assert Path(paths["markdown"]).is_file()
    assert sorted(item.name for item in (tmp_path / "out").iterdir()) == [
        markout.JSON_REPORT_NAME, markout.MARKDOWN_REPORT_NAME,
    ]


def test_cli_refuses_data_output_and_writes_elsewhere(tmp_path, capsys):
    root = standard_root(tmp_path)
    refused = markout.main([
        "--snapshots-root", str(root), "--output-dir", str(tmp_path / "data" / "out"), "--dates", TARGET,
    ])
    assert refused == 2
    assert "REFUSED" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()

    code = markout.main([
        "--snapshots-root", str(root), "--output-dir", str(tmp_path / "out"), "--dates", TARGET,
        "--bootstrap-replicates", "20", "--seed", "3",
    ])
    output = capsys.readouterr().out
    assert code == 0
    assert "UNDERPOWERED" in output
    assert "verdict: R_NOT_SUPPLIED" in output
    written = json.loads((tmp_path / "out" / markout.JSON_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["counts"]["trades_analysed"] == 4
    assert written["parameters"]["seed"] == 3
