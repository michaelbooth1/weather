"""T2's taker rule (WS-3 prereg ``docs/research/ws3-early-warning-prereg-2026-11-06.md`` sections 2-3).

Synthetic fixtures under tmp_path only: no network, no data/, no captured file.
"""

import ast
import csv
import inspect
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.backtesting import t2_taker_rule as t2
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

MODULE = Path(t2.__file__)
UTC = timezone.utc
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # 11:00 in New York
DAY = date(2026, 10, 1)
SLUG = "highest-temperature-in-nyc-on-october-1-2026"
OTHER = "highest-temperature-in-miami-on-october-1-2026"
BAND = "70-71 F"
RAW_BAND = "70-71°F"
HEADER = ["capture_id", "captured_at_utc", "event_slug", "range_label", "outcome", "clob_token_id", "book_time_utc",
          "min_order_size", "best_bid", "best_ask", "ask_count", "ask_size_at_best", "midpoint"]
S = timedelta(seconds=1)


def _row(captured, outcome, ask, size=20, count=1, mos=5, band=RAW_BAND, slug=SLUG, lag=1.0):
    return {"capture_id": "c", "captured_at_utc": captured.isoformat(), "event_slug": slug, "range_label": band,
            "outcome": outcome, "clob_token_id": f"{slug}|{t2.clean_temperature_label(band)}|{outcome}",
            "book_time_utc": (captured - timedelta(seconds=lag)).isoformat(), "min_order_size": mos,
            "best_bid": 0.01, "best_ask": ask, "ask_count": count, "ask_size_at_best": size, "midpoint": 0.5}


def _books(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _scope(start=date(2026, 9, 30), end=date(2026, 10, 14), excluded=()):
    return t2.Scope(start, end, frozenset(excluded))


def _times(*seconds):
    return [T0 + s * S for s in seconds]


# --- costs, windows, rows --------------------------------------------------------------------------------------

def test_costs_and_pnl_follow_pt1():
    assert t2.fee(0.6) == pytest.approx(0.012)
    assert t2.net_edge(0.8, 0.6) == pytest.approx(0.8 - 0.6 - 0.012 - 0.01)
    assert t2.entry_pnl(10, 1.0, 0.59) == pytest.approx(10 * (1 - 0.59 - 0.05 * 0.59 * 0.41 - 0.01))
    assert t2.entry_pnl(5, 0.0, 0.42) == pytest.approx(-5 * (0.42 + 0.05 * 0.42 * 0.58 + 0.01))
    ask = 0.5
    q_at_theta = t2.THETA + ask + t2.fee(ask) + t2.SLIPPAGE
    assert t2.passes_entry(q_at_theta - 5e-10, ask) and not t2.passes_entry(q_at_theta - 2e-9, ask)


def test_decision_row_respects_receipt_gap_and_lookback():
    assert t2.decision_index(_times(-15), T0) == 0
    assert t2.decision_index(_times(-14), T0) is None
    assert t2.decision_index(_times(-120), T0) == 0
    assert t2.decision_index(_times(-121), T0) is None
    assert t2.decision_index(_times(-60, -20, -5), T0) == 1


def test_fill_row_is_the_earliest_in_t_plus_30_to_150():
    assert t2.fill_index(_times(29), T0, 30) is None
    assert t2.fill_index(_times(30), T0, 30) == 0
    assert t2.fill_index(_times(150), T0, 30) == 0
    assert t2.fill_index(_times(151), T0, 30) is None
    assert t2.fill_index(_times(40, 100), T0, 30) == 0


def test_load_books_unusable_rows_exactly_15s_nan_and_allowlist(tmp_path):
    path = _books(tmp_path / "order_books_summary.csv", [
        _row(T0, "Yes", 0.5, lag=-15), _row(T0 + 5 * S, "Yes", 0.5, lag=-15.001),
        _row(T0 + 6 * S, "Yes", "nan"), _row(T0 + 7 * S, "Yes", 0.5, size="inf"),
        _row(T0 + 8 * S, "Yes", 0.5, mos="nan"), _row(T0 + 9 * S, "Yes", 0.5, count="nan")])
    books = t2.load_books([path], _scope())
    assert books.rows_read == 6 and books.unusable_rows == 5
    assert books.token_of == {(SLUG, BAND, "Yes"): f"{SLUG}|{BAND}|Yes"}  # the degree sign is cleaned
    assert set(t2.BookRow.__dataclass_fields__) == {"captured", "best_ask", "ask_size", "ask_count", "min_order_size"}
    with pytest.raises(t2.RuleError, match="not an order_books_summary"):
        t2.load_books([tmp_path / "other.csv"], _scope())


def test_book_rows_outside_the_window_or_b10_are_refusals(tmp_path):
    late = "highest-temperature-in-nyc-on-october-15-2026"
    with pytest.raises(t2.RuleError, match="outside the window"):
        t2.load_books([_books(tmp_path / "order_books_summary.csv", [_row(T0, "Yes", 0.5, slug=late)])], _scope())
    denver = "highest-temperature-in-denver-on-october-1-2026"
    with pytest.raises(t2.RuleError, match="outside B's 10"):
        t2.load_books([_books(tmp_path / "order_books_summary.csv", [_row(T0, "Yes", 0.5, slug=denver)])], _scope())


# --- entries, fills, caps --------------------------------------------------------------------------------------

def _world(rows):
    books = t2.Books()
    for slug, band, side, when, ask, size, count, mos in rows:
        token = f"{slug}|{band}|{side}"
        books.token_of[(slug, band, side)] = token
        books.tokens.setdefault(token, t2.TokenBook()).rows.append(t2.BookRow(when, ask, size, count, mos))
    for book in books.tokens.values():
        book.finalize()
    return books


def _snap(t=T0, slug=SLUG, day=DAY):
    return t2.Snapshot(slug, day, t, 11)


def _rows(band=BAND, slug=SLUG, t=T0, yes=0.6, no=0.42, fill_yes=0.59, fill_no=0.42, size=20, mos=5, count=1,
          fill_count=1):
    return [(slug, band, "Yes", t - 20 * S, yes, size, count, mos), (slug, band, "No", t - 20 * S, no, size, count, mos),
            (slug, band, "Yes", t + 40 * S, fill_yes, size, fill_count, mos),
            (slug, band, "No", t + 40 * S, fill_no, size, fill_count, mos)]


def _run(snaps, books):
    return t2.run_arm("mg2", snaps, {(s.slug, s.t) for s in snaps}, books, 30)


def test_entry_takes_the_qualifying_side_and_fills_at_top_of_book():
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows()))
    assert [(t.side, t.decision_ask, t.fill_price, t.shares) for t in trades] == [("Yes", 0.6, 0.59, 10.0)]
    assert counts["decision_instants"] == 1 and counts["entry_signals"] == 1
    trades, _ = _run({_snap(): {BAND: 0.5}}, _world(_rows()))
    assert [(t.side, t.q_side) for t in trades] == [("No", 0.5)]
    assert _run({_snap(): {BAND: 0.62}}, _world(_rows()))[0] == []


def test_both_sides_passing_take_the_larger_edge_and_yes_on_a_tie():
    trades, _ = _run({_snap(): {BAND: 0.5}}, _world(_rows(yes=0.4, no=0.4, fill_yes=0.4, fill_no=0.4)))
    assert [t.side for t in trades] == ["Yes"]
    trades, _ = _run({_snap(): {BAND: 0.5}}, _world(_rows(yes=0.4, no=0.3, fill_yes=0.4, fill_no=0.3)))
    assert [t.side for t in trades] == ["No"]


def test_ask_count_zero_at_decision_or_fill_never_trades():
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows(count=0)))
    assert trades == [] and counts["no_decision"] == 2
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows(fill_count=0)))
    assert trades == [] and counts["no_fill_price"] == 1


def test_no_fill_when_the_ask_rises_size_is_small_or_min_order_size_is_missing():
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows(fill_yes=0.61)))
    assert trades == [] and counts["no_fill_price"] == 1
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows(size=4)))
    assert trades == [] and counts["below_min_order_size"] == 1
    trades, counts = _run({_snap(): {BAND: 0.8}}, _world(_rows(mos=None)))
    assert trades == [] and counts["missing_min_order_size"] == 1


def test_an_unfilled_band_retries_later_and_a_held_band_never_takes_the_other_side():
    t1 = T0 + timedelta(minutes=10)
    trades, _ = _run({_snap(): {BAND: 0.8}, _snap(t1): {BAND: 0.8}}, _world(_rows(fill_yes=0.61) + _rows(t=t1)))
    assert [t.t for t in trades] == [t1]
    trades, counts = _run({_snap(): {BAND: 0.8}, _snap(t1): {BAND: 0.3}}, _world(_rows() + _rows(t=t1)))
    assert [t.side for t in trades] == ["Yes"] and counts["band_already_held"] == 1


def test_caps_three_entries_and_notional_per_market_day_and_date():
    bands = [f"{60 + i} F" for i in range(5)]
    rows = [r for b in bands for r in _rows(band=b, yes=0.2, fill_yes=0.2)]
    trades, counts = _run({_snap(): {b: 0.6 for b in bands}}, _world(rows))
    assert len(trades) == 3 and counts["cap_entries"] == 2
    rows = [r for b in bands[:3] for r in _rows(band=b, yes=0.9, fill_yes=0.9)]
    trades, counts = _run({_snap(): {b: 1.0 for b in bands[:3]}}, _world(rows))
    assert len(trades) == 2 and counts["cap_notional"] == 1  # 9 + 9 = 18; a third 9 would breach 25
    slugs = [f"highest-temperature-in-{m}-on-october-1-2026" for m in list(t2.B10)[:6]]
    rows = [r for s in slugs for b in bands[:2] for r in _rows(band=b, slug=s, yes=0.9, fill_yes=0.9)]
    trades, counts = _run({_snap(slug=s): {b: 1.0 for b in bands[:2]} for s in slugs}, _world(rows))
    assert sum(t.shares * t.fill_price for t in trades) <= 100 and len(trades) == 11 and counts["cap_notional"] == 1


@pytest.mark.parametrize("latency", [29, math.nan, math.inf])
def test_latency_must_be_finite_and_at_least_30_s(latency):
    with pytest.raises(t2.RuleError, match="finite and >= 30"):
        t2.run_arm("mg2", {}, set(), t2.Books(), latency)


# --- countability, statistics ----------------------------------------------------------------------------------

def test_coverage_and_countability_take_timestamps_ids_and_status_only():
    assert list(inspect.signature(t2.coverage).parameters) == ["snaps", "token_of", "token_times"]
    assert list(inspect.signature(t2.countable_events).parameters) == ["arm_events", "cov", "outcome_blind_pass",
                                                                       "winners_ok"]
    token_of = {(SLUG, BAND, side): side for side in t2.SIDES}
    times = {side: [T0 - 20 * S] for side in t2.SIDES}
    snaps = {_snap(): {BAND}, _snap(slug=OTHER): {BAND}, _snap(T0 + 3600 * S): {BAND, "72-73 F"}}
    cov = t2.coverage(snaps, token_of, times)
    assert cov[SLUG] == {"snapshots": 2, "covered": 1, "unmatched_bands": 1}
    assert cov[OTHER] == {"snapshots": 1, "covered": 0, "unmatched_bands": 1}
    cov = t2.coverage({_snap(): {BAND}}, token_of, times)
    arms = {"mg2": {SLUG, OTHER}, "served": {SLUG}}
    assert t2.countable_events(arms, cov, {SLUG, OTHER}, {SLUG: "matched"}) == {SLUG: "", OTHER: "arm_vector_missing"}
    assert t2.countable_events(arms, cov, set(), {SLUG: "matched"})[SLUG] == "outcome_blind_check_not_passed"
    assert t2.countable_events(arms, cov, {SLUG}, {SLUG: "missing"})[SLUG] == "no_venue_winner"
    assert t2.countable_events(arms, cov, {SLUG}, {SLUG: "unmatched"})[SLUG] == "winner_unmatched"


def test_winner_status_cleans_labels_and_never_returns_the_band():
    bands = {SLUG: {BAND, "72-73 F"}}
    status = t2.winner_status({SLUG: RAW_BAND}, bands)
    assert status == {SLUG: "matched"}
    assert t2.winner_status({SLUG: "74-75°F"}, bands) == {SLUG: "unmatched"}
    assert t2.winner_status({SLUG: ""}, bands) == {SLUG: "missing"}


def test_bootstrap_golden_values_on_a_tiny_fixture():
    day_of = {f"e{i}": date(2026, 10, 1) + timedelta(days=i // 2) for i in range(8)}
    values = {f"e{i}": v for i, v in enumerate([-1.0, 0.5, -2.0, 0.0, 1.0, -0.5, -1.5, 0.25])}
    bounds = t2.bootstrap_bounds(values, day_of)
    assert bounds == t2.bootstrap_bounds(values, day_of)
    assert sum(values.values()) / 8 == pytest.approx(-0.40625)
    assert bounds["date_cluster"]["upper"] == pytest.approx(GOLDEN["date_cluster_upper"], abs=1e-12)
    assert bounds["block3"]["upper"] == pytest.approx(GOLDEN["block3_upper"], abs=1e-12)
    assert bounds["date_cluster"]["lower"] == pytest.approx(GOLDEN["date_cluster_lower"], abs=1e-12)
    assert bounds["block3"]["lower"] == pytest.approx(GOLDEN["block3_lower"], abs=1e-12)


# Pinned from numpy default_rng(20260921) at this module's first pinned sha; U = max(upper) = 0.03125.
GOLDEN = {"date_cluster_upper": 0.03125, "block3_upper": -0.3125, "date_cluster_lower": -0.8125,
          "block3_lower": -0.59375}


def test_kill_rules():
    assert t2.kill_outcome(15, 150, 30, -0.01) == "KILL"
    assert t2.kill_outcome(15, 150, 30, 0.0) == "NOT_KILLED"
    assert t2.kill_outcome(11, 150, 30, -1.0) == "UNTESTABLE"
    assert t2.kill_outcome(15, 99, 30, -1.0) == "UNTESTABLE"
    assert t2.kill_outcome(15, 150, 29, -1.0) == "UNTESTABLE"
    assert t2.kill_outcome(15, 150, 30, None) == "UNTESTABLE"


# --- vectors: window, markets, hours ----------------------------------------------------------------------------

def _vectors(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(t2.VECTOR_COLUMNS)
        writer.writerows(rows)
    return path


def _vrow(arm="mg2", slug=SLUG, t=T0, hour=11, day="2026-10-01", band=RAW_BAND, q=0.8):
    return [arm, slug, day, t.isoformat(), hour, band, q]


def test_vector_hours_6_7_16_17_and_label_cleaning(tmp_path):
    rows = [_vrow(t=datetime(2026, 10, 1, h + 4, 30, tzinfo=UTC), hour=h) for h in (6, 7, 16, 17)]
    vectors, counts = t2.load_vectors(_vectors(tmp_path / "v.csv", rows), ("mg2", "served"), _scope())
    assert sorted(s.local_hour for s in vectors["mg2"]) == [7, 16] and counts["outside_decision_hours"] == 2
    assert all(set(b) == {BAND} for b in vectors["mg2"].values())


@pytest.mark.parametrize("row,match", [
    (_vrow(hour=12), "disagree"), (_vrow(day="2026-10-02"), "disagree"),
    (_vrow(slug="highest-temperature-in-nyc-on-october-2-2026", day="2026-10-02", t=T0 + 86400 * S), None),
    (_vrow(slug="highest-temperature-in-denver-on-october-1-2026"), "outside B's 10"),
    (_vrow(slug="highest-temperature-in-nyc-on-october-15-2026", day="2026-10-15", t=T0 + 14 * 86400 * S),
     "outside the window"),
    (_vrow(q="nan"), "q outside"),
])
def test_vector_refusals(tmp_path, row, match):
    path = _vectors(tmp_path / "v.csv", [row])
    if match is None:
        assert t2.load_vectors(path, ("mg2", "served"), _scope())[1]["rows"] == 1
        return
    with pytest.raises(t2.RuleError, match=match):
        t2.load_vectors(path, ("mg2", "served"), _scope())


# --- CLI -------------------------------------------------------------------------------------------------------

def _cli_inputs(tmp_path, winner=RAW_BAND, blind=(SLUG,), extra_vectors=(), settlement_text=None):
    vec = _vectors(tmp_path / "vectors.csv", [
        _vrow("mg2", q=0.8), _vrow("served", q=0.5),
        _vrow("mg2", t=T0 + timedelta(hours=6, minutes=30), hour=17), *extra_vectors])
    books = _books(tmp_path / "order_books_summary.csv", [
        _row(T0 - 20 * S, "Yes", 0.6), _row(T0 - 20 * S, "No", 0.42),
        _row(T0 + 40 * S, "Yes", 0.59), _row(T0 + 40 * S, "No", 0.42, size=5)])
    settlements = []
    for slug, text in ((SLUG, settlement_text or json.dumps({"event_slug": SLUG, "polymarket_winning_band": winner})),
                       (OTHER, "{")):  # the out-of-scope event's file is malformed: it must never be parsed
        (tmp_path / slug).mkdir(exist_ok=True)
        (tmp_path / slug / "settlement.json").write_text(text, encoding="utf-8")
        settlements.append(tmp_path / slug / "settlement.json")
    (tmp_path / "books.txt").write_text(f"{books}\n", encoding="utf-8")
    (tmp_path / "settlements.txt").write_text("".join(f"{p}\n" for p in settlements), encoding="utf-8")
    (tmp_path / "blind.txt").write_text("".join(f"{s}\n" for s in blind), encoding="utf-8")
    return ["--vectors", str(vec), "--books-list", str(tmp_path / "books.txt"), "--settlements-list",
            str(tmp_path / "settlements.txt"), "--outcome-blind-pass", str(tmp_path / "blind.txt"),
            "--window-start", "2026-09-30", "--window-end", "2026-10-14", "--arms", "mg2", "served",
            "--out", str(tmp_path / "run")]


def _summary(tmp_path):
    return json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))


def _manifest(tmp_path):
    return json.loads((tmp_path / "run" / "input_manifest.json").read_text(encoding="utf-8"))


def test_cli_degree_sign_book_and_cleaned_winner_settle_and_the_look_is_single(tmp_path, capsys):
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps({"projected": {"mg2": {"fills": 40}}}), encoding="utf-8")
    argv = _cli_inputs(tmp_path, winner="70-71 F") + ["--projection-receipt", str(projection)]
    assert t2.main(argv) == 0
    out = tmp_path / "run"
    assert sorted(p.name for p in out.iterdir()) == sorted([*t2.OUTPUT_NAMES, t2.MARKER_NAME])
    summary = _summary(tmp_path)
    mg2, served = summary["arms"]["mg2"], summary["arms"]["served"]
    assert mg2["M"] == pytest.approx(t2.entry_pnl(10, 1.0, 0.59))
    assert served["M"] == pytest.approx(t2.entry_pnl(5, 0.0, 0.42))
    assert mg2["fee_total"] == pytest.approx(10 * t2.fee(0.59)) and served["slippage_total"] == pytest.approx(0.05)
    assert mg2["realised_population"]["decision_instants"] == 1 and mg2["realised_population"]["fills_countable"] == 1
    assert mg2["outcome"] == served["outcome"] == "UNTESTABLE" and summary["countable_market_days"] == 1
    assert summary["projection_receipt"]["projected"] == {"mg2": {"fills": 40}}
    manifest = _manifest(tmp_path)
    assert manifest["coverage"][SLUG] == {"snapshots": 1, "covered": 1, "unmatched_bands": 0}
    assert manifest["vector_rows"]["outside_decision_hours"] == 1 and manifest["winner_unmatched_total"] == 0
    assert manifest["schema_version"] == schema_version("t2_taker_rule_input_manifest")
    assert "70-71" not in json.dumps(manifest)  # the manifest never carries a band or winner value
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["single_look"] is True and set(receipt["outputs"]) == set(t2.OUTPUT_NAMES[:-1])
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    capsys.readouterr()
    assert t2.main(argv) == 3 and "single look already taken" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


@pytest.mark.parametrize("winner,reason", [("74-75°F", "winner_unmatched"), ("", "no_venue_winner")])
def test_cli_unmatched_or_missing_winner_leaves_the_day_non_countable(tmp_path, winner, reason):
    assert t2.main(_cli_inputs(tmp_path, winner=winner)) == 0
    assert _manifest(tmp_path)["countable"] == {SLUG: reason}
    summary = _summary(tmp_path)
    assert summary["countable_market_days"] == 0 and summary["arms"]["mg2"]["M"] is None
    assert summary["arms"]["mg2"]["outcome"] == "UNTESTABLE" and summary["arms"]["mg2"]["filled_entries"] == 0


def test_cli_zero_countable_market_days(tmp_path):
    assert t2.main(_cli_inputs(tmp_path, blind=())) == 0
    summary = _summary(tmp_path)
    assert summary["countable_market_days"] == summary["countable_dates"] == 0
    assert summary["arms"]["served"]["outcome"] == "UNTESTABLE" and summary["paired_difference"]["mean"] is None


def test_cli_exclude_slug_skips_rows_without_parsing_its_settlement(tmp_path):
    argv = _cli_inputs(tmp_path, settlement_text="{")
    assert t2.main([*argv, "--exclude-slug", SLUG]) == 0
    manifest = _manifest(tmp_path)
    assert manifest["vector_rows"]["excluded_slug"] == 3 and manifest["book_rows_excluded"] == 4
    assert manifest["countable"] == {} and manifest["excluded_slugs"] == [SLUG]


@pytest.mark.parametrize("change", ["window", "denver", "same_arms", "latency", "parse_error", "hour"])
def test_cli_refusals_happen_before_the_marker(tmp_path, change):
    argv = _cli_inputs(tmp_path)
    if change == "window":
        argv[argv.index("--window-end") + 1] = "2026-09-30"
    elif change == "denver":
        argv = _cli_inputs(tmp_path, extra_vectors=[_vrow(slug="highest-temperature-in-denver-on-october-1-2026")])
    elif change == "same_arms":
        argv[argv.index("--arms") + 2] = "mg2"
    elif change == "latency":
        argv += ["--latency-s", "nan"]
    elif change == "parse_error":
        argv = _cli_inputs(tmp_path, settlement_text="{")
    else:
        argv = _cli_inputs(tmp_path, extra_vectors=[_vrow(hour=10)])
    assert t2.main(argv) == 2 and not (tmp_path / "run").exists()


@pytest.mark.parametrize("bad", ["ledger.jsonl", "LEDGER.jsonl.gz", "a/../Data/Settlements/nyc/settlement.json",
                                 "config/Local/x.csv", "t/L2/p2/x.csv", "panels/x.csv"])
def test_path_guard_resolves_relative_and_dotdot_paths_case_insensitively(tmp_path, monkeypatch, bad):
    monkeypatch.chdir(tmp_path)
    target = Path(bad)
    (tmp_path / target).resolve().parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target).resolve().write_text("x", encoding="utf-8")
    assert t2.forbidden_reason(target)
    argv = _cli_inputs(tmp_path)
    (tmp_path / "books.txt").write_text(f"{bad}\n", encoding="utf-8")
    assert t2.main(argv) == 2 and not (tmp_path / "run").exists()


def test_out_may_not_be_inside_the_repository_or_a_data_folder(tmp_path):
    argv = _cli_inputs(tmp_path)
    for out in (t2.REPO_ROOT / "t2_out_never_created", tmp_path / "data" / "run"):
        argv[argv.index("--out") + 1] = str(out)
        assert t2.main(argv) == 2 and not out.exists()


# --- module contract -------------------------------------------------------------------------------------------

def _function(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_label_cleaner_is_a_verbatim_copy():
    ledger = MODULE.parent / "settlement_ledger.py"
    assert ast.dump(_function(ledger, "clean_temperature_label")) == ast.dump(
        _function(MODULE, "clean_temperature_label"))


def test_b10_and_zones_match_the_market_registry():
    from weather.market import market_registry

    assert sorted(t2.B10) == ["atlanta", "austin", "chicago", "dallas", "houston", "los-angeles", "miami", "nyc",
                              "san-francisco", "seattle"]
    for market, zone in t2.B10.items():
        assert market_registry.spec_for_slug(f"highest-temperature-in-{market}-on-october-1-2026").timezone == zone


def test_module_imports_size_and_schemas():
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert imported == {"__future__", "argparse", "bisect", "csv", "gzip", "hashlib", "io", "json", "math", "re",
                        "sys", "collections", "dataclasses", "datetime", "pathlib", "zoneinfo", "numpy",
                        "weather.schema_families"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not names & {"__import__", "importlib", "exec", "eval", "import_module", "system", "popen"}
    for token in ("importlib", "__import__", "Path.cwd", "getcwd", "rmtree", "unlink", "os.environ", "private_key"):
        assert token not in source
    assert len(source.splitlines()) <= 800  # module-local budget (master review 2026-11-06 grew the module)
    registry = load_families()
    assert registry.errors == ()
    for name in ("t2_taker_rule_input_manifest", "t2_taker_rule_summary", "t2_taker_rule_receipt"):
        assert registry.family_of(name) == "t2_taker" and schema_version(name) == f"{name}_v1"
