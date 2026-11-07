"""Synthetic verification of MG-1's outcome-blind amendment.

Guards: Clarification 4's coverage/one-winner/key mask, primary-only dates and MG1_LAST,
NONDECIDING sensitivity isolation, exact freeze binding and amendment receipt binding. No runtime evidence.
"""
import json
from datetime import datetime, timedelta

import pytest

from tests.calibration.test_mg1_countable import D0, FINAL_NOW, LAST, MARKETS, freeze_keys, write_ledger
from tests.calibration.test_mg1_look import RULE, _nothing_spent, _root, _score, _synthetic, _written  # noqa: F401
from weather import mg1_reserved_window as window
from weather.backtesting import settlement_ledger as sl
from weather.calibration import mg1_countable as c
from weather.calibration import mg1_look as m


def test_equal_coverage_changing_only_venue_winner_does_not_select_primary(tmp_path):
    primary, old = [], []
    for bucket in (80, 82):
        event = {"closed": True, "markets": [{"groupItemTitle": f"{bucket}-{bucket + 1}°F",
                 "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]'}]}
        reconciliation = sl.reconcile_with_polymarket(event, 80)
        root = tmp_path / str(bucket)
        (root / "atlanta").mkdir(parents=True)
        row = {"event_slug": "one-event", "target_date": D0.isoformat(), "revision_number": 1,
               "material_coverage_grade": "strict_complete", "polymarket_reconciliation": reconciliation,
               "promotion_countable": reconciliation["status"] == "match"}
        (root / "atlanta/ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        sensitivity = {}
        flags, _ = c.market_day_flags(root, [D0], ["atlanta"],
                                      {"atlanta": {D0.isoformat()}}, sensitivity_flags=sensitivity)
        primary.append(flags[("atlanta", D0.isoformat())])
        old.append(sensitivity[("atlanta", D0.isoformat())])
    assert primary == [True, True]
    assert old == [True, False]  # the old mask still measures the diagnosed selection


@pytest.mark.parametrize("grade,closed,winners,key,expected", [
    ("strict_complete", True, [{}], True, True),
    ("minor_gap_material", True, [{}], True, True),
    ("manual_override", True, [{}], True, True),
    ("insufficient", True, [{}], True, False),
    ("strict_complete", False, [{}], True, False),
    ("strict_complete", True, [], True, False),
    ("strict_complete", True, [{}, {}], True, False),
    ("strict_complete", True, None, True, False),
    ("strict_complete", True, [{}], False, False),
])
def test_primary_mask_requires_coverage_closed_single_winner_and_key(tmp_path, grade, closed, winners, key,
                                                                  expected):
    folder = tmp_path / "atlanta"
    folder.mkdir()
    row = {"event_slug": "one", "target_date": D0.isoformat(), "revision_number": 1,
           "material_coverage_grade": grade, "polymarket_reconciliation": {
               "event_closed": closed, "winning_markets": winners}, "promotion_countable": True}
    (folder / "ledger.jsonl").write_text(json.dumps(row), encoding="utf-8")
    flags, _ = c.market_day_flags(tmp_path, [D0], ["atlanta"],
                                  {"atlanta": {D0.isoformat()} if key else set()})
    assert flags[("atlanta", D0.isoformat())] is expected


def test_date_population_uses_primary_and_missing_keys_extend_only_forward(tmp_path, monkeypatch):
    def disagree(market, day):
        # Old mask false on every day, while coverage, closed winner and keys remain admitted.
        return [{"event_slug": f"event-{day}", "target_date": day.isoformat(), "revision_number": 1,
                 "material_coverage_grade": "strict_complete", "promotion_countable": False,
                 "polymarket_reconciliation": {"event_closed": True, "winning_markets": [{}]}}]

    root = write_ledger(tmp_path, LAST + timedelta(days=5), disagree)
    freeze = freeze_keys(root, FINAL_NOW)
    rows, _ = c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert rows[-1]["date"] == LAST.isoformat() and len(rows) == 45
    assert all(any(r["markets"].values()) and not any(r["sensitivity_markets"].values()) for r in rows)
    hole = D0 + timedelta(days=4)
    freeze = freeze_keys(root, FINAL_NOW, missing={(mk, hole.isoformat()) for mk in MARKETS})
    report = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert report["required_mg1_last"] == (LAST + timedelta(days=1)).isoformat()
    assert report["extend_mg1_last"] is True
    with pytest.raises(c.CountableRefused, match="extend the window"):
        c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    monkeypatch.setattr(window, "MG1_LAST", LAST + timedelta(days=1))
    rows, _ = c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert len(rows) == 46 and rows[4]["markets"] == dict.fromkeys(MARKETS, False)
    assert rows[-1]["date"] == (LAST + timedelta(days=1)).isoformat()


@pytest.mark.parametrize("old_mask", ["all", "none", "some", "error"])
def test_sensitivity_is_reported_without_deciding_or_extra_reads(tmp_path, monkeypatch, old_mask):
    inputs = _synthetic(tmp_path, bad_markets=("miami",) if old_mask == "some" else ())
    body = json.loads(inputs["countable"].read_text(encoding="utf-8"))
    for row in body["dates"]:
        row["sensitivity_markets"] = {mk: old_mask != "none" and (old_mask != "some" or mk == "miami")
                                      for mk in row["markets"]}
    inputs["countable"].write_text(json.dumps(body), encoding="utf-8")
    calls = []
    loader, scorer = m.load_outcomes, m.score_rows

    def load_once(*args, **kwargs):
        calls.append("join")
        return loader(*args, **kwargs)

    def primary(*args, **kwargs):
        result = scorer(*args, **kwargs)
        calls.append(result["decision"])
        return result

    monkeypatch.setattr(m, "load_outcomes", load_once)
    monkeypatch.setattr(m, "score_rows", primary)
    if old_mask == "error":
        def broken(*args, **kwargs):
            raise RuntimeError("synthetic secondary failure")
        monkeypatch.setattr(m, "promotion_sensitivity", broken)
    receipt_path, result = _score(monkeypatch, inputs)
    assert calls[0] == "join" and len(calls) == 2
    assert result["decision"] == calls[1]  # every primary decision field is unchanged
    report = result["promotion_mask_sensitivity"]
    assert report["wording"] == m.SENSITIVITY_WORDING and "decision" not in report
    assert report["status"] == {"none": "unavailable", "error": "error"}.get(old_mask, "ok")
    if old_mask == "all":
        assert report["contrast_00_16"] == result["primary"]
        assert report["included_market_days"] == 450 and report["excluded_market_days"] == 0
    if old_mask == "some":
        assert report["included_market_days"] == 45 and report["excluded_market_days"] == 405
        assert report["contrast_00_16"]["fixed_market"]["estimate"] > 0
        assert result["decision"]["verdict"] == "PASS"  # sensitivity harm cannot veto primary improvement
    if old_mask == "none":
        assert report["dates_represented"] == 0 and report["contrast_00_16"] is None
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["result"]["sha256"] == m.sha256_file(inputs["out"] / m.RESULT)
    assert receipt["clarifications_sha256"] == m.CLARIFICATIONS_SHA256
    assert len(receipt["clarifications_sha256"]) == 4 and m.receipt_problems(receipt_path) == []


def test_stale_freeze_binding_holds_before_any_outcome(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    body = json.loads(inputs["countable"].read_text(encoding="utf-8"))
    body["label_freeze_receipt_sha256"] = "0" * 64
    inputs["countable"].write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(m.MG1LookHeld, match="another label freeze receipt"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)


def test_old_flags_cannot_admit_a_market_day_outside_the_primary(tmp_path):
    inputs = _synthetic(tmp_path)
    body = json.loads(inputs["countable"].read_text(encoding="utf-8"))
    body["dates"][0]["markets"]["miami"] = False  # old flag deliberately stays true
    inputs["countable"].write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(m.MG1LookRefused, match="within the primary market-day mask"):
        m.read_countable(inputs["countable"])


def test_amendment_bytes_are_checked_before_stamping_and_receipt_rejects_repinning(tmp_path, monkeypatch):
    _, path = _written(tmp_path, monkeypatch)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert len(receipt["clarifications_sha256"]) == 4
    amendment = next(k for k in receipt["clarifications_sha256"] if "clarification-4-" in k)
    receipt["clarifications_sha256"][amendment] = "0" * 64
    receipt["body_sha256"] = m.body_sha256(receipt)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert m.receipt_problems(path) == ["MG-1 look receipt does not bind the pinned clarifications"]
    monkeypatch.setattr(m, "CLARIFICATIONS_SHA256", {amendment: "0" * 64})
    with pytest.raises(m.MG1LookRefused, match="clarification bytes differ"):
        m.Look(RULE)


def test_reporting_never_requests_the_old_mask(tmp_path, monkeypatch):
    root = write_ledger(tmp_path, LAST)
    freeze = freeze_keys(root, FINAL_NOW)
    original = c.market_day_flags
    calls = []

    def primary_only(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(c, "market_day_flags", primary_only)
    c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert len(calls) == 1 and set(calls[0]) == {"disclosures"}


def test_countability_previews_do_not_consume_or_replace_the_single_look_freeze(tmp_path):
    root = write_ledger(tmp_path, LAST)
    freeze = freeze_keys(root, FINAL_NOW)
    body = json.loads(freeze.read_text(encoding="utf-8"))
    body["look_id"] = "mg1-countability-p1"
    freeze.write_text(json.dumps(body), encoding="utf-8")
    report = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert report["countable_reached"] == 45
    with pytest.raises(c.CountableRefused, match="freeze for look 'mg1'"):
        c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)


@pytest.mark.parametrize("last,at,allowed", [
    (LAST, "2026-11-30T04:59:59+00:00", False),  # still Nov 29 in Toronto
    (LAST, "2026-11-30T05:00:00+00:00", True),
    (LAST + timedelta(days=3), "2026-12-03T04:59:59+00:00", False),
    (LAST + timedelta(days=3), "2026-12-03T05:00:00+00:00", True),
])
def test_look_timing_stays_nov30_and_two_local_days_after_actual_last(last, at, allowed):
    now = datetime.fromisoformat(at)
    if allowed:
        m.look_timing_check(last, now)
    else:
        with pytest.raises(m.MG1LookRefused, match="at least 2 days"):
            m.look_timing_check(last, now)


def test_legacy_countability_lists_are_not_silently_reinterpreted(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema": "mg1_countable/1", "dates": []}), encoding="utf-8")
    with pytest.raises(m.MG1LookRefused, match="not mg1_countable/2"):
        m.read_countable(path)


@pytest.mark.parametrize("encoding", ["basic", "week"])
def test_frozen_receipt_keys_normalise_to_the_same_primary_population(tmp_path, encoding):
    from datetime import date

    root = write_ledger(tmp_path, LAST + timedelta(days=3))
    freeze = freeze_keys(root, FINAL_NOW)
    original = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    body = json.loads(freeze.read_text(encoding="utf-8"))

    def encode(day):
        parsed = date.fromisoformat(day)
        if encoding == "basic":
            return parsed.isoformat().replace("-", "")
        year, week, weekday = parsed.isocalendar()
        return f"{year:04d}-W{week:02d}-{weekday}"

    for entry in body["markets"].values():
        entry["label_dates"] = [encode(d) for d in entry["label_dates"]]
    freeze.write_text(json.dumps(body), encoding="utf-8")
    # label_key_check accepts and normalises the receipt list against the unchanged ISO manifest keys.
    keys, _ = c.frozen_keys(freeze, FINAL_NOW)
    assert D0.isoformat() in keys[MARKETS[0]]
    normalised = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert normalised["dates"] == original["dates"] and normalised["countable_reached"] == 45
    rows, _ = c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert len(rows) == 45 and rows[-1]["date"] == LAST.isoformat()
    direct, _ = c.market_day_flags(root, [D0], [MARKETS[0]], {MARKETS[0]: {"20261015"}})
    assert direct[(MARKETS[0], D0.isoformat())] is True


def test_unparseable_frozen_key_refuses_instead_of_emptying_population(tmp_path):
    root = write_ledger(tmp_path, LAST)
    freeze = freeze_keys(root, FINAL_NOW)
    body = json.loads(freeze.read_text(encoding="utf-8"))
    body["markets"][MARKETS[0]]["label_dates"][0] = "not-a-date"
    freeze.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(c.CountableRefused, match="frozen label keys unavailable"):
        c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)


def test_disclosures_count_only_primary_dates_and_the_sole_missing_settlement_failure(tmp_path):
    from tests.calibration.test_mg1_countable import _row

    def override(market, day):
        row = _row(market, day, True)
        if market == MARKETS[0] and day in (D0, LAST + timedelta(days=1)):
            row["material_coverage_grade"] = "manual_override"
        if market == MARKETS[1] and day in (D0, LAST + timedelta(days=1)):
            row["material_coverage_grade"] = "missing_settlement"
        if market == MARKETS[2] and day == D0:
            row["material_coverage_grade"] = "missing_settlement"
            row["polymarket_reconciliation"]["event_closed"] = False  # second failed condition
        if market == MARKETS[3] and day == D0:
            row["material_coverage_grade"] = "missing_settlement"  # key removed below: two failures
        if row["material_coverage_grade"] == "missing_settlement":
            row["settlement_bucket"] = None
            row["settlement_high"] = None
            row["promotion_countable"] = False
        return [row]

    root = write_ledger(tmp_path, LAST + timedelta(days=3), override)
    freeze = freeze_keys(root, FINAL_NOW, missing={(MARKETS[3], D0.isoformat())})
    report = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert report["countability_disclosures"] == {"manual_override": 1, "missing_settlement": 1}
    assert report["countability_disclosure_dates"] == 45
    rows, _ = c.final_rows(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert rows[0]["disclosures"] == report["countability_disclosures"]
    assert m.countability_disclosures(rows) == report["countability_disclosures"]
    # Changing strict_complete to manual_override, or adding/removing a second failed condition on an already
    # excluded missing_settlement cell, changes disclosures without changing primary selection or dates.
    for market in (MARKETS[0], MARKETS[1]):
        path = root / market / "ledger.jsonl"
        ledger = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if market == MARKETS[0]:
            ledger[0]["material_coverage_grade"] = "strict_complete"
        else:
            ledger[0]["polymarket_reconciliation"]["event_closed"] = False
        path.write_text("".join(json.dumps(row) + "\n" for row in ledger), encoding="utf-8")
    changed = c.report(ledger_root=root, label_freeze=freeze, now=FINAL_NOW)
    assert changed["countability_disclosures"] == {"manual_override": 0, "missing_settlement": 0}
    for key in ("dates", "countable_reached", "required_mg1_last", "extend_mg1_last"):
        assert changed[key] == report[key]


@pytest.mark.parametrize("key", m.COUNTABILITY_DISCLOSURE_KEYS)
def test_each_disclosure_count_can_change_without_changing_any_decision(tmp_path, monkeypatch, key):
    inputs = _synthetic(tmp_path)
    results = []
    for value in (0, 17):
        body = json.loads(inputs["countable"].read_text(encoding="utf-8"))
        body["dates"][0]["disclosures"][key] = value
        inputs["countable"].write_text(json.dumps(body), encoding="utf-8")
        monkeypatch.setattr(m, "LOOK_ROOT", tmp_path / f"look-{value}")
        _, result = _score(monkeypatch, {**inputs, "out": tmp_path / f"result-{value}"})
        assert result["countability_disclosures"][key] == value
        results.append(result)
    for field in ("decision", "primary", "counted_dates", "not_countable", "promotion_mask_sensitivity"):
        assert results[0][field] == results[1][field]
    assert results[0]["decision"]["verdict"] == "PASS"
