"""Evening lock-in fix scorer (weather.backtesting.evening_fix_scorer).

Guards: the evening-fix scoring pre-registration (draft (a), 2026-10-13) read gate and decision rule.

Covers the read gate (signed pre-registration, no read before 2026-10-29 without a
recorded token, nothing computed or written on refusal), the embargo refusal for
2026-09-30..2026-10-15, and the pre-registered decision rule. All rows are
synthetic fixtures; no real dated data is read.
"""
import json
from datetime import date, timedelta

import pytest

from weather.backtesting import evening_fix_scorer as scorer

BEFORE_READ = date(2026, 10, 20)
AFTER_READ = date(2026, 10, 29)
BANDS = [
    {"label": "87F or below", "kind": "lte", "value": 87.0, "value_hi": 87.0, "market_yes": 0.01},
    {"label": "88-89F", "kind": "eq", "value": 88.0, "value_hi": 89.0, "market_yes": 0.98},
    {"label": "90F or higher", "kind": "gte", "value": 90.0, "value_hi": 90.0, "market_yes": 0.01},
]
GOOD = [0.0, 0.95, 0.05]
BAD = [0.10, 0.60, 0.30]


def _slug(market, day):
    return f"{market}|{day.isoformat()}"


def _rows(days, markets=scorer.US_MARKETS, new=GOOD, old=BAD, hours=(18, 21, 10)):
    rows = []
    for day in days:
        for market in markets:
            for hour in hours:
                rows.append({
                    "snapshot_id": f"{market}-{day}-{hour}", "market_id": market,
                    "event_slug": _slug(market, day), "target_date": day.isoformat(),
                    "hour": hour, "bands": BANDS, "new_band_p": list(new),
                    "old_band_p": list(old), "l1_new_vs_recorded": 0.0,
                    "lockin_anchor": {"source": "observed_station_rows", "bucket": 89},
                })
    return rows


def _labels(rows, countable=True):
    return {row["event_slug"]: {"settlement_bucket": 89, "promotion_countable": countable}
            for row in rows}


def _window(n=12):
    return [scorer.WINDOW_START + timedelta(days=i) for i in range(n)]


@pytest.fixture
def signed(tmp_path):
    prereg = tmp_path / "prereg.md"
    prereg.write_text("# evening fix prereg\n", encoding="utf-8")
    digest = scorer.file_sha256(prereg)
    log = tmp_path / "DECISION_LOG.md"
    row = "| 2026-10-20 | owner authorises an early evening-fix read | test |"
    log.write_text(f"| 2026-10-15 | evening-fix prereg signed, sha256 {digest} |\n{row}\n",
                   encoding="utf-8")
    return prereg, log, digest, row


def _token(tmp_path, digest, row, **overrides):
    token = {"prereg": scorer.PREREG_ID, "prereg_sha256": digest, "reason": "owner test read",
             "issued_by": "owner", "decision_log_row": row, **overrides}
    path = tmp_path / "token.json"
    path.write_text(json.dumps(token), encoding="utf-8")
    return path


def _no_market(rows):
    """Rows as ``lockin_anchor_replay --no-market`` writes them: every band price null."""
    return [{**row, "bands": [{**band, "market_yes": None} for band in row["bands"]]} for row in rows]


def _replay_file(tmp_path, rows):
    path = tmp_path / "replay.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _argv(tmp_path, prereg, log, replay, *extra):
    return ["--replay", str(replay), "--prereg", str(prereg), "--decision-log", str(log),
            "--out", str(tmp_path / "result.json"), "--no-market", *extra]


# --- read gate -------------------------------------------------------------------

def test_unsigned_prereg_is_refused_at_any_date(tmp_path, signed, capsys):
    prereg, log, _, _ = signed
    log.write_text("no signature here\n", encoding="utf-8")
    code = scorer.main(_argv(tmp_path, prereg, log, tmp_path / "missing.jsonl"), today=AFTER_READ)
    assert code == scorer.REFUSED_EXIT
    assert "unsigned" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_before_read_date_without_token_refuses_before_opening_any_input(tmp_path, signed, capsys):
    prereg, log, _, _ = signed
    # The replay path does not exist: the refusal must come from the gate, not from I/O.
    code = scorer.main(_argv(tmp_path, prereg, log, tmp_path / "missing.jsonl"), today=BEFORE_READ)
    assert code == scorer.REFUSED_EXIT
    assert "first read is 2026-10-29" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("overrides,message", [
    ({"prereg": "other-prereg"}, "names"),
    ({"prereg_sha256": "0" * 64}, "different pre-registration hash"),
    ({"reason": " "}, "no reason"),
    ({"issued_by": ""}, "no issued_by"),
    ({"decision_log_row": "| 2026-10-20 | made up |"}, "not recorded"),
    ({"decision_log_row": "| 2026-10-20 |"}, "as a whole row"),
    ({"decision_log_row": "early evening-fix read"}, "as a whole row"),
])
def test_invalid_read_token_is_refused(tmp_path, signed, overrides, message, capsys):
    prereg, log, digest, row = signed
    token = _token(tmp_path, digest, row, **overrides)
    code = scorer.main(_argv(tmp_path, prereg, log, tmp_path / "missing.jsonl",
                             "--read-token", str(token)), today=BEFORE_READ)
    assert code == scorer.REFUSED_EXIT
    assert message in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_recorded_token_allows_an_early_read_and_is_recorded(tmp_path, signed, monkeypatch):
    prereg, log, digest, row = signed
    rows = _no_market(_rows(_window()))
    monkeypatch.setattr(scorer, "load_labels", lambda slugs, ledger_root=None: _labels(rows))
    token = _token(tmp_path, digest, row)
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows),
                             "--read-token", str(token)), today=BEFORE_READ)
    assert code == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["gate"]["early_read"] is True
    assert result["gate"]["read_token"]["decision_log_row"] == row
    assert result["gate"]["prereg_sha256"] == digest


def test_on_read_date_scores_without_token(tmp_path, signed, monkeypatch):
    prereg, log, _, _ = signed
    rows = _no_market(_rows(_window()))
    monkeypatch.setattr(scorer, "load_labels", lambda slugs, ledger_root=None: _labels(rows))
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)), today=AFTER_READ)
    assert code == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["outcome"] == scorer.STAGE1_MET
    assert result["window_dates"][-1] == "2026-10-27"
    assert result["reproduction_table"]["commits"]["local"]["pass"] is True
    assert result["gate"]["read_token"] is None


@pytest.mark.parametrize("day", [date(2026, 9, 30), date(2026, 10, 15)])
def test_an_embargo_row_refuses_the_whole_run(tmp_path, signed, monkeypatch, day, capsys):
    prereg, log, _, _ = signed
    rows = _no_market(_rows(_window()) + _rows([day], markets=("atlanta",)))
    monkeypatch.setattr(scorer, "load_labels", lambda slugs, ledger_root=None: _labels(rows))
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)), today=AFTER_READ)
    assert code == scorer.REFUSED_EXIT
    assert "embargo" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_development_rows_outside_the_window_are_skipped(tmp_path):
    rows = _rows([date(2026, 9, 20)], markets=("atlanta",)) + _rows(_window(1), markets=("atlanta",))
    kept, skipped = scorer.load_replay_rows(_replay_file(tmp_path, rows))
    assert skipped == 3
    assert {row["target_date"] for row in kept} == {"2026-10-16"}


# --- decision rule -----------------------------------------------------------------

def test_us11_is_eleven_markets():
    assert len(scorer.US_MARKETS) == 11
    assert "toronto" not in scorer.US_MARKETS


def test_pass_when_new_beats_old_everywhere():
    rows = _rows(_window())
    result = scorer.evaluate(rows, _labels(rows))
    assert result["outcome"] == "PASS"
    assert result["primary"]["markets_negative"] == 11
    assert result["primary"]["ci95"][1] < 0
    assert result["countable_us_market_days"] == 132
    assert result["window_dates"][-1] == "2026-10-27"


def test_harm_when_old_beats_new():
    rows = _rows(_window(), new=BAD, old=GOOD)
    assert scorer.evaluate(rows, _labels(rows))["outcome"] == "HARM"


def test_not_confirmed_when_no_difference():
    rows = _rows(_window(), new=GOOD, old=GOOD)
    assert scorer.evaluate(rows, _labels(rows))["outcome"] == "NOT_CONFIRMED"


def test_void_when_too_few_qualifying_dates_even_after_extension():
    rows = _rows(_window(5))
    result = scorer.evaluate(rows, _labels(rows))
    assert result["outcome"] == "VOID"
    # Master 2026-10-31: the extension adds 10-28 only; 10-29 is another read's day 0.
    assert result["window_dates"][-1] == "2026-10-28"
    assert "never added" in " ".join(result["void_reasons"])


def test_extension_adds_only_the_dates_needed():
    rows = _rows(_window(8) + [date(2026, 10, 28)])
    result = scorer.evaluate(rows, _labels(rows))
    assert result["window_dates"][-1] == "2026-10-28"
    assert len(result["qualifying_dates"]) == 9
    assert result["outcome"] == "PASS"


def test_uncountable_days_do_not_count():
    rows = _rows(_window())
    result = scorer.evaluate(rows, _labels(rows, countable=False))
    assert result["countable_us_market_days"] == 0
    assert result["outcome"] == "VOID"


def test_reproduction_failure_voids_the_look():
    rows = _rows(_window())
    for row in rows[: len(rows) // 10]:
        row["l1_new_vs_recorded"] = 0.2
    result = scorer.evaluate(rows, _labels(rows))
    assert result["outcome"] == "VOID"
    assert "reproduce" in " ".join(result["void_reasons"])


def test_safety_count_flags_a_zeroed_settled_band():
    rows = _rows(_window())
    for row in rows:
        if row["market_id"] == "atlanta" and row["target_date"] == "2026-10-16" and row["hour"] == 18:
            row["new_band_p"] = [0.0, 0.0, 1.0]
    result = scorer.evaluate(rows, _labels(rows))
    assert result["safety"]["observed_anchor"] == ["atlanta|2026-10-16"]
    assert result["safety_fail"] is True


def test_h2_is_tested_only_after_a_primary_pass():
    rows = _rows(_window())
    for row in rows:
        row["v3_band_p"] = list(GOOD)
    passed = scorer.evaluate(rows, _labels(rows))
    assert passed["h2_pre_lockin_floor_non_inferiority_00_16"]["tested"] is True
    assert passed["h2_pre_lockin_floor_non_inferiority_00_16"]["non_inferior"] is True
    harmed = _rows(_window(), new=BAD, old=GOOD)
    for row in harmed:
        row["v3_band_p"] = list(GOOD)
    assert scorer.evaluate(harmed, _labels(harmed))["h2_pre_lockin_floor_non_inferiority_00_16"] == {"tested": False}


def test_token_quoting_the_signature_row_is_refused(tmp_path, signed, capsys):
    prereg, log, digest, _ = signed
    signature_row = next(line for line in log.read_text(encoding="utf-8").splitlines() if digest in line)
    token = _token(tmp_path, digest, signature_row)
    code = scorer.main(_argv(tmp_path, prereg, log, tmp_path / "missing.jsonl",
                             "--read-token", str(token)), today=BEFORE_READ)
    assert code == scorer.REFUSED_EXIT
    assert "quotes the signature row" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


# --- master 2026-10-31 F2: local mode guards; F3: the window never depends on labels -------

def _labels_must_not_open(slugs, ledger_root=None):
    raise AssertionError("labels opened")


def test_local_mode_without_no_market_is_refused_before_labels(tmp_path, signed, monkeypatch, capsys):
    prereg, log, _, _ = signed
    rows = _no_market(_rows(_window()))
    monkeypatch.setattr(scorer, "load_labels", _labels_must_not_open)
    argv = [a for a in _argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)) if a != "--no-market"]
    assert scorer.main(argv, today=AFTER_READ) == scorer.REFUSED_EXIT
    assert "requires --no-market" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_local_mode_with_a_market_price_is_refused_before_labels(tmp_path, signed, monkeypatch, capsys):
    prereg, log, _, _ = signed
    rows = _rows(_window())   # band prices present
    monkeypatch.setattr(scorer, "load_labels", _labels_must_not_open)
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)), today=AFTER_READ)
    assert code == scorer.REFUSED_EXIT
    assert "carries a market price" in capsys.readouterr().err
    assert not (tmp_path / "result.json").exists()


def test_local_mode_labels_unreached_when_reproduction_fails(tmp_path, signed, monkeypatch, capsys):
    prereg, log, _, _ = signed
    rows = _no_market(_rows(_window()))
    for row in rows[: len(rows) // 10]:
        row["l1_new_vs_recorded"] = 0.2
    monkeypatch.setattr(scorer, "load_labels", _labels_must_not_open)
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)), today=AFTER_READ)
    assert code == scorer.STOP_EXIT
    payload = json.loads((tmp_path / "result.json").read_text())
    assert payload["stop"] == "B2_REPRODUCTION"
    table = payload["reproduction_table"]["commits"]["local"]
    assert table["pass"] is False
    assert table["per_date"]["2026-10-16"]["share"] < 0.99
    assert "outcome" not in payload
    assert "stopping before labels" in capsys.readouterr().err


def test_local_mode_window_needing_10_29_stops(tmp_path, signed, monkeypatch):
    prereg, log, _, _ = signed
    rows = _no_market(_rows(_window(5)))
    monkeypatch.setattr(scorer, "load_labels", lambda slugs, ledger_root=None: _labels(rows))
    code = scorer.main(_argv(tmp_path, prereg, log, _replay_file(tmp_path, rows)), today=AFTER_READ)
    assert code == scorer.STOP_EXIT
    payload = json.loads((tmp_path / "result.json").read_text())
    assert payload["stop"] == "WINDOW_NEEDS_FORBIDDEN_DATE"
    assert "outcome" not in payload


def test_window_does_not_depend_on_settlement_labels():
    rows = _rows(_window())
    labels = _labels(rows)
    # Four dates countable by metadata but with no settlement bucket: before F3 the label-dependent
    # countable dropped them and the window grew to 10-28.
    for slug, label in labels.items():
        if slug.split("|")[1] in {"2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"}:
            label["settlement_bucket"] = None
    result = scorer.evaluate(rows, labels)
    assert result["window_dates"][-1] == "2026-10-27"
    assert len(result["qualifying_dates"]) == 8   # report only


def test_evaluate_uses_the_window_it_is_given():
    rows = _rows(_window() + [date(2026, 10, 28)])
    given = [d.isoformat() for d in _window(12)]
    result = scorer.evaluate(rows, _labels(rows), window_dates=given)
    assert result["window_dates"] == given
    assert "2026-10-28" not in result["qualifying_dates"]
    assert result["countable_us_market_days"] == 132
