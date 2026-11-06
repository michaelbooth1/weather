"""T2's taker rule (WS-3 prereg ``docs/research/ws3-early-warning-prereg-2026-11-06.md`` sections 2-3).

Synthetic fixtures under tmp_path only: no network, no data/, no captured file.
"""

import ast
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.backtesting import t2_taker_rule as t2
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

MODULE = Path(t2.__file__)
UTC = timezone.utc
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
SLUG = "highest-temperature-in-nyc-on-october-1-2026"
BAND = "70-71 F"
HEADER = ["capture_id", "captured_at_utc", "event_slug", "range_label", "outcome", "clob_token_id", "book_time_utc",
          "min_order_size", "best_bid", "best_ask", "ask_count", "ask_size_at_best", "midpoint"]


def _row(captured, outcome, ask, size=20, count=1, mos=5, band=BAND, slug=SLUG, lag=1.0):
    return {"capture_id": "c", "captured_at_utc": captured.isoformat(), "event_slug": slug, "range_label": band,
            "outcome": outcome, "clob_token_id": f"{slug}|{band}|{outcome}",
            "book_time_utc": (captured - timedelta(seconds=lag)).isoformat(), "min_order_size": mos,
            "best_bid": 0.01, "best_ask": ask, "ask_count": count, "ask_size_at_best": size, "midpoint": 0.5}


def _books(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _book(rows):
    book = t2.TokenBook([t2.BookRow(when, ask, 20.0, 1, 5.0) for when, ask in rows])
    book.finalize()
    return book


def test_costs_and_pnl_follow_pt1():
    assert t2.fee(0.6) == pytest.approx(0.012)
    assert t2.net_edge(0.8, 0.6) == pytest.approx(0.8 - 0.6 - 0.012 - 0.01)
    assert t2.entry_pnl(10, 1.0, 0.59) == pytest.approx(10 * (1 - 0.59 - 0.05 * 0.59 * 0.41 - 0.01))
    assert t2.entry_pnl(5, 0.0, 0.42) == pytest.approx(-5 * (0.42 + 0.05 * 0.42 * 0.58 + 0.01))


def test_decision_row_respects_receipt_gap_and_lookback():
    s = timedelta(seconds=1)
    assert _book([(T0 - 15 * s, 0.5)]).decision_row(T0).captured == T0 - 15 * s
    assert _book([(T0 - 14 * s, 0.5)]).decision_row(T0) is None
    assert _book([(T0 - 120 * s, 0.5)]).decision_row(T0) is not None
    assert _book([(T0 - 121 * s, 0.5)]).decision_row(T0) is None
    latest = _book([(T0 - 60 * s, 0.4), (T0 - 20 * s, 0.5), (T0 - 5 * s, 0.6)]).decision_row(T0)
    assert latest.best_ask == 0.5


def test_fill_row_is_the_earliest_in_t_plus_30_to_150():
    s = timedelta(seconds=1)
    assert _book([(T0 + 29 * s, 0.4)]).fill_row(T0, 30) is None
    assert _book([(T0 + 30 * s, 0.4)]).fill_row(T0, 30) is not None
    assert _book([(T0 + 150 * s, 0.4)]).fill_row(T0, 30) is not None
    assert _book([(T0 + 151 * s, 0.4)]).fill_row(T0, 30) is None
    assert _book([(T0 + 100 * s, 0.3), (T0 + 40 * s, 0.4)]).fill_row(T0, 30).best_ask == 0.4


def test_load_books_drops_late_book_rows_and_keeps_only_allowlisted_fields(tmp_path):
    path = _books(tmp_path / "order_books_summary.csv", [
        _row(T0, "Yes", 0.5), _row(T0 + timedelta(seconds=5), "Yes", 0.5, lag=-16),
        _row(T0, "Yes", 0.5, slug="highest-temperature-in-austin-on-october-1-2026")])
    books = t2.load_books([path], {SLUG})
    assert books.rows_read == 2 and books.unusable_rows == 1
    assert set(t2.BookRow.__dataclass_fields__) == {"captured", "best_ask", "ask_size", "ask_count", "min_order_size"}
    with pytest.raises(t2.RuleError, match="not an order_books_summary"):
        t2.load_books([tmp_path / "other.csv"], {SLUG})


def _world(rows):
    books = t2.Books()
    for slug, band, side, when, ask, size, count, mos in rows:
        token = f"{slug}|{band}|{side}"
        books.token_of[(slug, band, side)] = token
        books.tokens.setdefault(token, t2.TokenBook()).rows.append(t2.BookRow(when, ask, size, count, mos))
    for book in books.tokens.values():
        book.finalize()
    return books


def _snap(t=T0, slug=SLUG, day=date(2026, 10, 1)):
    return t2.Snapshot(slug, day, t, 10)


def _rows(band=BAND, slug=SLUG, t=T0, yes=0.6, no=0.42, fill_yes=0.59, fill_no=0.42, size=20, mos=5):
    s = timedelta(seconds=1)
    return [(slug, band, "Yes", t - 20 * s, yes, size, 1, mos), (slug, band, "No", t - 20 * s, no, size, 1, mos),
            (slug, band, "Yes", t + 40 * s, fill_yes, size, 1, mos), (slug, band, "No", t + 40 * s, fill_no, size, 1, mos)]


def _run(snaps, books):
    both = {(s.slug, s.t) for s in snaps}
    return t2.run_arm("mg2", snaps, both, books, 30)


def test_entry_takes_the_qualifying_side_and_fills_at_top_of_book():
    trades, _ = _run({_snap(): {BAND: 0.8}}, _world(_rows()))
    assert [(t.side, t.decision_ask, t.fill_price, t.shares) for t in trades] == [("Yes", 0.6, 0.59, 10.0)]
    trades, _ = _run({_snap(): {BAND: 0.5}}, _world(_rows()))
    assert [(t.side, t.q_side) for t in trades] == [("No", 0.5)]
    trades, _ = _run({_snap(): {BAND: 0.62}}, _world(_rows()))
    assert trades == []


def test_no_fill_when_the_ask_rises_or_size_is_below_min_order_size():
    trades, skips = _run({_snap(): {BAND: 0.8}}, _world(_rows(fill_yes=0.61)))
    assert trades == [] and skips["no_fill_price"] == 1
    trades, skips = _run({_snap(): {BAND: 0.8}}, _world(_rows(size=4)))
    assert trades == [] and skips["below_min_order_size"] == 1


def test_an_unfilled_band_retries_later_and_a_held_band_never_takes_the_other_side():
    t1 = T0 + timedelta(minutes=10)
    rows = _rows(fill_yes=0.61) + _rows(t=t1)
    trades, _ = _run({_snap(): {BAND: 0.8}, _snap(t1): {BAND: 0.8}}, _world(rows))
    assert [t.t for t in trades] == [t1]
    rows = _rows() + _rows(t=t1)
    trades, skips = _run({_snap(): {BAND: 0.8}, _snap(t1): {BAND: 0.3}}, _world(rows))
    assert [t.side for t in trades] == ["Yes"] and skips["band_already_held"] == 1


def test_caps_three_entries_and_notional_per_market_day_and_date():
    bands = [f"{60 + i} F" for i in range(5)]
    rows = [r for b in bands for r in _rows(band=b, yes=0.2, fill_yes=0.2)]
    trades, skips = _run({_snap(): {b: 0.6 for b in bands}}, _world(rows))
    assert len(trades) == 3 and skips["cap_entries"] == 2
    rows = [r for b in bands[:3] for r in _rows(band=b, yes=0.9 - 0.0, fill_yes=0.9)]
    trades, skips = _run({_snap(): {b: 1.0 for b in bands[:3]}}, _world(rows))
    assert len(trades) == 2 and skips["cap_notional"] == 1  # 9 + 9 = 18; a third 9 would breach 25
    slugs = [f"highest-temperature-in-m{i}-on-october-1-2026" for i in range(6)]
    rows = [r for s in slugs for b in bands[:2] for r in _rows(band=b, slug=s, yes=0.9, fill_yes=0.9)]
    trades, skips = _run({_snap(slug=s): {b: 1.0 for b in bands[:2]} for s in slugs}, _world(rows))
    assert sum(t.shares * t.fill_price for t in trades) <= 100 and len(trades) == 11 and skips["cap_notional"] == 1


def test_latency_below_30_s_is_refused():
    with pytest.raises(t2.RuleError, match="below the 30"):
        t2.run_arm("mg2", {}, set(), t2.Books(), 29)


def test_bootstrap_is_seeded_and_kill_rules_hold():
    day_of = {f"e{i}": date(2026, 10, 1) + timedelta(days=i // 10) for i in range(150)}
    values = {slug: -1.0 + 0.01 * (i % 7) for i, slug in enumerate(day_of)}
    first, second = t2.bootstrap_bounds(values, day_of), t2.bootstrap_bounds(values, day_of)
    assert first == second and set(first) == {"date_cluster", "block3"}
    upper = max(b["upper"] for b in first.values())
    assert upper < 0 and t2.kill_outcome(15, 150, 30, upper) == "KILL"
    assert t2.kill_outcome(15, 150, 30, 0.0) == "NOT_KILLED"
    assert t2.kill_outcome(11, 150, 30, -1.0) == "UNTESTABLE"
    assert t2.kill_outcome(15, 99, 30, -1.0) == "UNTESTABLE"
    assert t2.kill_outcome(15, 150, 29, -1.0) == "UNTESTABLE"


def test_countability_needs_both_arms_blind_checks_and_90pct_coverage():
    other = "highest-temperature-in-austin-on-october-1-2026"
    vectors = {"mg2": {_snap(): {BAND: 0.8}, _snap(slug=other): {BAND: 0.8}}, "served": {_snap(): {BAND: 0.5}}}
    books = _world(_rows())
    cov = t2.coverage(vectors, books)
    assert cov[SLUG] == {"snapshots": 1, "covered": 1} and cov[other] == {"snapshots": 1, "covered": 0}
    assert t2.countable_events(vectors, cov, {SLUG, other}) == {SLUG: "", other: "arm_vector_missing"}
    assert t2.countable_events(vectors, cov, set())[SLUG] == "outcome_blind_check_not_passed"


def _cli_inputs(tmp_path):
    vec = tmp_path / "vectors.csv"
    with vec.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(t2.VECTOR_COLUMNS)
        writer.writerow(["mg2", SLUG, "2026-10-01", T0.isoformat(), 10, BAND, 0.8])
        writer.writerow(["served", SLUG, "2026-10-01", T0.isoformat(), 10, BAND, 0.5])
        writer.writerow(["mg2", SLUG, "2026-10-01", (T0 + timedelta(hours=8)).isoformat(), 19, BAND, 0.8])
    s = timedelta(seconds=1)
    books = _books(tmp_path / "order_books_summary.csv", [
        _row(T0 - 20 * s, "Yes", 0.6), _row(T0 - 20 * s, "No", 0.42),
        _row(T0 + 40 * s, "Yes", 0.59), _row(T0 + 40 * s, "No", 0.42, size=5)])
    event = tmp_path / SLUG
    event.mkdir()
    (event / "settlement.json").write_text(json.dumps({"event_slug": SLUG, "polymarket_winning_band": BAND,
                                                       "settlement_high": 70}), encoding="utf-8")
    lists = {"books": books, "settlements": event / "settlement.json"}
    for name, path in lists.items():
        (tmp_path / f"{name}.txt").write_text(f"{path}\n", encoding="utf-8")
    (tmp_path / "blind.txt").write_text(SLUG + "\n", encoding="utf-8")
    return ["--vectors", str(vec), "--books-list", str(tmp_path / "books.txt"), "--settlements-list",
            str(tmp_path / "settlements.txt"), "--outcome-blind-pass", str(tmp_path / "blind.txt"),
            "--window-start", "2026-09-30", "--window-end", "2026-10-14", "--arms", "mg2", "served",
            "--out", str(tmp_path / "run")]


def test_cli_single_look_writes_every_output_once_and_refuses_a_second_run(tmp_path, capsys):
    argv = _cli_inputs(tmp_path)
    assert t2.main(argv) == 0
    out = tmp_path / "run"
    assert sorted(p.name for p in out.iterdir()) == sorted([*t2.OUTPUT_NAMES, t2.MARKER_NAME])
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    mg2, served = summary["arms"]["mg2"], summary["arms"]["served"]
    assert mg2["M"] == pytest.approx(t2.entry_pnl(10, 1.0, 0.59)) and served["M"] == pytest.approx(
        t2.entry_pnl(5, 0.0, 0.42))
    assert mg2["outcome"] == served["outcome"] == "UNTESTABLE" and summary["countable_market_days"] == 1
    manifest = json.loads((out / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["coverage"][SLUG] == {"snapshots": 1, "covered": 1}  # the 19:00 vector is outside 07-16
    assert manifest["schema_version"] == schema_version("t2_taker_rule_input_manifest")
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["single_look"] is True and set(receipt["outputs"]) == set(t2.OUTPUT_NAMES[:-1])
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    capsys.readouterr()
    assert t2.main(argv) == 3 and "single look already taken" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_cli_refuses_bad_arguments_and_forbidden_inputs(tmp_path):
    argv = _cli_inputs(tmp_path)
    same = [*argv[:argv.index("--arms") + 1], "mg2", "mg2", *argv[argv.index("--arms") + 3:]]
    assert t2.main(same) == 2 and not (tmp_path / "run").exists()
    assert t2.main([*argv, "--latency-s", "10"]) == 2
    ledger = tmp_path / "data" / "settlements" / "nyc" / "ledger.jsonl"
    (tmp_path / "settlements.txt").write_text(f"{ledger}\n", encoding="utf-8")
    with pytest.raises(t2.RuleError, match="forbidden input path"):
        t2.main(argv)
    assert not (tmp_path / "run").exists()


def test_module_imports_size_and_schemas():
    source = MODULE.read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert {name for name in imported if name.startswith("weather")} == {"weather.schema_families"}
    forbidden = ("requests", "httpx", "urllib", "socket", "http", "aiohttp", "websocket", "websockets", "py_clob_client",
                 "eth_account", "web3", "keyring", "dotenv", "subprocess", "ssl")
    assert not {name for name in imported if name.split(".")[0] in forbidden}
    assert imported <= {"__future__", "argparse", "bisect", "csv", "gzip", "hashlib", "json", "math", "re", "sys",
                        "collections", "dataclasses", "datetime", "pathlib", "numpy", "weather.schema_families"}
    for token in ("open_ledger", "Path.cwd", "getcwd", "rmtree", "unlink", "os.environ", "private_key"):
        assert token not in source
    assert len(source.splitlines()) <= 600
    registry = load_families()
    assert registry.errors == ()
    for name in ("t2_taker_rule_input_manifest", "t2_taker_rule_summary", "t2_taker_rule_receipt"):
        assert registry.family_of(name) == "t2_taker" and schema_version(name) == f"{name}_v1"
