"""110u: synthetic sealed bundles only; no production evidence or provider IO."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import socket

import numpy as np
import pytest

from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.replay.bundle import FORMAT, sha256
from weather.market import maker_fair_value_score as scorer
from weather.market.maker_fair_value_statistics import cluster_weights, summarize, tables
from weather.market.maker_plugin.fair_value import WeatherFairValue
from weather.market.maker_plugin.settlement import WeatherSettlement
from tests.market.test_maker_plugin import bulletin, fixture, forecast, ledger, served_inputs
from tests.maker_core.fixtures.replay_bundle import seal

AT = datetime(2026, 9, 25, 15, tzinfo=timezone.utc)
SCORE_AT = datetime(2026, 10, 15, tzinfo=timezone.utc)
TIP = "a" * 40


class SyntheticPanel:
    def __init__(self):
        self.rows, self.conditions = defaultdict(list), defaultdict(dict)

    def add(self, at, cid, kind, payload):
        payload = plain(payload)
        row = dict(sequence=len(self.rows[at.date()]), captured_at=at.isoformat(), condition_id=cid,
                   kind=kind, payload=payload, payload_sha256=sha256(canonical_bytes(payload)),
                   source_hashes={"synthetic-generator": sha256(b"110u fixtures only")})
        self.rows[at.date()].append(row)
        return row

    def event(self, *, at=AT, city="nyc", lead=1, source="nbp", minutes=(0,), settled=True):
        universe, bands, spec, target, _, _ = fixture(city, lead, now=at)
        markets = universe.discover(at, 2).markets
        if source == "nbp":
            raw = bulletin(spec, target, issue=at.replace(hour=13, minute=0), fetched=at-timedelta(minutes=30))
            support = {"bulletins": [raw]}
        else:
            support = {"forecasts": [forecast(bands, spec, target, now=at)]}
        provider = WeatherFairValue(universe, **support)
        explanation, lineage = served_inputs(bands)
        support.update(snapshots=bands, source_rows=[lineage], explanations=[explanation])
        generated = []
        for minute in minutes:
            when = at + timedelta(minutes=minute)
            for market in markets:
                start = when.replace(hour=0, minute=0, second=0, microsecond=0)
                self.conditions[when.date()][market.condition_id] = dict(condition_id=market.condition_id,
                    market_id=spec.id, domain_id="weather", active_from=start.isoformat(),
                    active_until=(start+timedelta(days=1)).isoformat())
                self.add(when, market.condition_id, "descriptor", dict(market=market, horizon_days=lead))
                book = self.add(when, market.condition_id, "book", dict(as_of_utc=when,
                    yes_bids=[[".4", "75"]], yes_asks=[[".6", "75"]],
                    no_bids=[[".4", "75"]], no_asks=[[".6", "75"]]))
                view = provider.evaluate(market, when)
                self.add(when, market.condition_id, "outcome_view", dict(available=True, value=view))
                generated.append(book)
                if minute == minutes[0]:
                    for name, rows in support.items():
                        for raw in rows:
                            original = raw[scorer.SUPPORT_CLOCKS[name]]
                            self.add(when, market.condition_id, "plugin_input",
                                     dict(source=name, original_captured_at=original, record=raw))
        if settled:
            label = ledger(bands, spec, target)
            if city == "toronto":
                # Fixture ledger helper is F-native; construct the equivalent C label.
                from weather.market.maker_plugin.inputs import digest
                from weather.market.maker_plugin.settlement import REVISION_FIELDS
                label.update(settlement_bucket=23, settlement_high=23, winning_band="20-25 C",
                    polymarket_winning_band="20-25 C", winning_band_value=20, winning_band_value_hi=25)
                label["label_hash"] = digest({k: v for k, v in label.items() if k not in REVISION_FIELDS})
                label["revision_changes"] = [{"field": k, "old": None, "new": v}
                    for k, v in sorted(label.items()) if k not in REVISION_FIELDS and v is not None]
                label["revision_id"] = "sha256:" + digest({k: label.get(k) for k in
                    ("event_slug", "revision_number", "recorded_at_utc", "label_hash", "supersedes_revision_id")})
            when = datetime.fromisoformat(label["recorded_at_utc"])
            settler = WeatherSettlement(universe, ledger_rows=[label])
            for market in markets:
                start = when.replace(hour=0)
                self.conditions[when.date()][market.condition_id] = dict(condition_id=market.condition_id,
                    market_id=spec.id, domain_id="weather", active_from=start.isoformat(), active_until=start.isoformat())
                self.add(when, market.condition_id, "descriptor", dict(market=market, horizon_days=-1))
                self.add(when, market.condition_id, "settlement", settler.resolve(market, when))
        return generated

    def write(self, root):
        paths = []
        for day, rows in sorted(self.rows.items()):
            path = root / str(day)
            path.mkdir(parents=True)
            manifest = dict(format=FORMAT, day=str(day), provenance="synthetic",
                sealed_at=datetime.combine(day+timedelta(days=1), datetime.min.time(), timezone.utc).isoformat(),
                conditions=list(self.conditions[day].values()), streams=[])
            for row in rows:
                row["payload_sha256"] = sha256(canonical_bytes(row["payload"]))
            seal(path, manifest, list(reversed(rows)))
            paths.append(path)
        return paths


def test_earliest_guard_precedes_any_input_read(monkeypatch):
    monkeypatch.setattr(scorer, "load_bundle", lambda *a, **k: pytest.fail("early evidence read"))
    with pytest.raises(ValueError, match="earliest_date"):
        scorer.score(["never-open"], code_tip=TIP, now=SCORE_AT.replace(month=10, day=8))
    # Registered first day is admitted to input validation, not moved to the planned execution date.
    with pytest.raises(ValueError, match="bundle_count_cap"):
        scorer.score([], code_tip=TIP, now=SCORE_AT.replace(day=9))


@pytest.mark.parametrize("source,lead,city", [("nbp", 1, "nyc"), ("nbp", 2, "nyc"),
                                             ("fallback", 1, "nyc"), ("fallback", 1, "toronto")])
def test_bundle_pipeline_native_units_and_separate_strata(tmp_path, monkeypatch, source, lead, city):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network accessed"))
    panel = SyntheticPanel()
    panel.event(source=source, lead=lead, city=city, minutes=(0, 1, 60))
    paths = panel.write(tmp_path)
    before = {p: p.read_bytes() for folder in paths for p in folder.iterdir()}
    result = scorer.score(paths, code_tip=TIP, now=SCORE_AT)
    table = result["tables"][f"{source}_lead_{lead}"]
    assert table["hours"] == 2 and table["band_hours"] == 6
    assert table["status"] == "UNDERPOWERED"
    assert (table["date_clusters"], table["market_clusters"], table["market_days"]) == (1, 1, 1)
    assert result["coverage"]["later_captures_in_selected_hour"] == 1
    assert result["capture_exclusions"] == result["settlement_exclusions"] == {}
    assert table["brier"]["mid"]["estimate"] == .25
    assert result["preregistration"]["bootstrap_replicates"] == 10000
    assert result["preregistration"]["bootstrap_seed"] == 110
    assert before == {p: p.read_bytes() for folder in paths for p in folder.iterdir()}
    repeat = scorer.score(list(reversed(paths)), code_tip=TIP, now=SCORE_AT + timedelta(days=1))
    assert canonical_bytes(result) == canonical_bytes(repeat)
    assert scorer.markdown(result) == scorer.markdown(repeat)


def test_first_complete_minute_without_stitching_and_no_label_dependent_reselection(tmp_path):
    panel = SyntheticPanel()
    books = panel.event(minutes=(0, 1, 2, 60), settled=False)
    books[0]["payload"]["yes_asks"] = []
    paths = panel.write(tmp_path)
    result = scorer.score(paths, code_tip=TIP, now=SCORE_AT)
    assert result["coverage"]["selected_complete_event_hours"] == 2
    assert result["coverage"]["later_captures_in_selected_hour"] == 1
    assert result["capture_exclusions"] == {"missing_contemporaneous_two_sided_mid": 1}
    assert result["settlement_exclusions"] == {"missing_reconciled_settlement": 2}
    assert result["tables"]["pooled_descriptive"]["brier"] is None


@pytest.mark.parametrize("defect,reason", [
    ("probability", "joint disagrees with marginal"),
    ("stdev", "fair_value_input_binding_mismatch"),
    ("future_issue", "input_unavailable:"),
    ("missing_band", "incomplete_event_partition"),
    ("crossed", "crossed_book"),
    ("missing_book", "incomplete_captured_minute"),
    ("future_support", "missing_captured_band_metadata"),
    ("lead", "local_lead_identity_mismatch"),
])
def test_bad_first_capture_never_scores_as_zero_or_half(tmp_path, defect, reason):
    panel = SyntheticPanel()
    panel.event()
    rows = panel.rows[AT.date()]
    if defect in ("probability", "stdev"):
        row = next(r for r in rows if r["kind"] == "outcome_view")
        row["payload"]["value"]["p_yes" if defect == "probability" else "stdev"] = .123
    elif defect == "future_issue":
        for r in rows:
            if r["kind"] == "plugin_input" and r["payload"]["source"] == "bulletins":
                raw = r["payload"]["record"]
                raw["text"] = raw["text"].replace("1300 UTC", "1900 UTC")
                raw["payload_hash"] = sha256(raw["text"].encode())
    elif defect == "missing_band":
        rows[:] = [r for r in rows if not (r["kind"] == "plugin_input" and r["payload"]["source"] == "snapshots"
                                          and r["payload"]["record"]["bin_kind"] == "gte")]
    elif defect == "crossed":
        next(r for r in rows if r["kind"] == "book")["payload"]["yes_bids"] = [[".9", "75"]]
    elif defect == "missing_book":
        rows.remove(next(r for r in rows if r["kind"] == "book"))
    elif defect == "future_support":
        for r in rows:
            if r["kind"] == "plugin_input":
                r["captured_at"] = (AT + timedelta(seconds=1)).isoformat()
    else:
        next(r for r in rows if r["kind"] == "descriptor")["payload"]["horizon_days"] = 2
    result = scorer.score(panel.write(tmp_path), code_tip=TIP, now=SCORE_AT)
    assert result["tables"]["pooled_descriptive"]["brier"] is None
    assert any(k.startswith(reason) for k in result["capture_exclusions"])


@pytest.mark.parametrize("defect", ["stream_hash", "duplicate_bundle", "identity", "support_clock", "unsealed"])
def test_invalid_export_refuses_whole_run(tmp_path, defect):
    panel = SyntheticPanel()
    panel.event()
    if defect == "identity":
        panel.conditions[AT.date()][next(iter(panel.conditions[AT.date()]))]["market_id"] = "chicago"
    if defect == "support_clock":
        next(r for r in panel.rows[AT.date()] if r["kind"] == "plugin_input")["payload"]["original_captured_at"] = AT.isoformat()
    paths = panel.write(tmp_path)
    if defect == "stream_hash":
        (paths[0] / "records.jsonl").write_bytes(b"changed\n")
    if defect == "duplicate_bundle":
        paths += paths[:1]
    if defect == "unsealed":
        path = paths[0] / "bundle.json"
        manifest = json.loads(path.read_bytes())
        manifest["sealed_at"] = AT.isoformat()
        path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(ValueError):
        scorer.score(paths, code_tip=TIP, now=SCORE_AT)


def test_conflicting_or_unbound_settlement_excluded(tmp_path):
    panel = SyntheticPanel()
    panel.event()
    rows = panel.rows[date(2026, 9, 27)]
    row = next(r for r in rows if r["kind"] == "settlement")
    row["payload"]["source_hashes"]["ledger"] = "bad"
    result = scorer.score(panel.write(tmp_path), code_tip=TIP, now=SCORE_AT)
    assert result["settlement_exclusions"] == {"settlement_identity_unbound": 1}
    assert result["coverage"]["selected_complete_event_hours"] == 1


def test_local_calendar_lead_and_panel_boundaries(tmp_path):
    panel = SyntheticPanel()
    # 01Z on September 25 is still September 24 in New York. This is T+1,
    # although its target date equals the UTC capture date.
    panel.event(at=AT.replace(hour=1), source="fallback")
    result = scorer.score(panel.write(tmp_path / "local"), code_tip=TIP, now=SCORE_AT)
    row, = result["selected_hours"]
    assert row["target_date"] == "2026-09-25" and row["lead"] == 1
    for name, at, lead, reason in (("t0", AT, 0, "local_lead_out_of_scope"),
                                  ("outside", AT.replace(day=23), 1, "target_outside_frozen_panel")):
        panel = SyntheticPanel()
        panel.event(at=at, lead=lead, settled=False)
        result = scorer.score(panel.write(tmp_path / name), code_tip=TIP, now=SCORE_AT)
        assert result["capture_exclusions"] == {reason: 1}
        assert result["selected_hours"] == []


def statistical_row(day, market, p, *, source="nbp", lead=1):
    return dict(target_date=day, market_id=market, source=source, lead=lead,
                bands=[dict(probability=p, mid=.5, observed_yes=0, stdev=.2)])


def test_hour_then_equal_market_day_weighting_and_separate_pooled_table():
    rows = [statistical_row("d1", "a", .1), statistical_row("d1", "a", .3),
            statistical_row("d2", "a", .9, source="fallback")]
    result = tables(rows)
    assert result["pooled_descriptive"]["brier"]["provider"]["estimate"] == pytest.approx((.05 + .81) / 2)
    assert result["nbp_lead_1"]["brier"]["provider"]["estimate"] == pytest.approx(.05)
    assert result["fallback_lead_1"]["brier"]["provider"]["estimate"] == pytest.approx(.81)
    assert result["nbp_lead_2"]["brier"] is None


def test_crossed_multiplicity_product_independent_reference_and_sparse_draws():
    cells = [("d1", "a"), ("d2", "b")]
    crossed, date_only = cluster_weights(cells)
    rng = np.random.default_rng(110)
    dates = rng.integers(2, size=(10000, 2))
    markets = rng.integers(2, size=(10000, 2))
    for i in (0, 3, 51, 9999):
        assert crossed[i].tolist() == [list(dates[i]).count(j) * list(markets[i]).count(j) for j in (0, 1)]
        assert date_only[i].tolist() == [list(dates[i]).count(j) for j in (0, 1)]
    table = summarize([statistical_row("d1", "a", .2), statistical_row("d2", "b", .8)])
    metric = table["brier"]["provider_minus_mid"]
    weights = crossed.sum(axis=1)
    expected = (crossed @ np.array([.04 - .25, .64 - .25]))[weights > 0] / weights[weights > 0]
    assert metric["crossed"]["interval_90"] == pytest.approx(np.quantile(expected, [.05, .95]))
    assert metric["crossed"]["undefined_replicates"] == int((weights == 0).sum()) > 0
    assert metric["date_only"]["undefined_replicates"] == 0


def test_fixed_bins_endpoints_empty_bins_and_underpowered_rule():
    rows = [statistical_row(str(d), str(m), p) for d in range(10) for m in range(10)
            for p in (0, .1, .3, 1)]
    result = summarize(rows)
    assert result["status"] == "DESCRIPTIVE"
    assert [r["count"] for r in result["reliability"]] == [100, 100, 0, 100, 0, 0, 0, 0, 0, 100]
    empty = result["reliability"][2]["mean_probability"]
    assert empty["estimate"] is None and empty["crossed"]["interval_90"] is None
    assert empty["crossed"]["undefined_replicates"] == 10000
    assert summarize([r for r in rows if r["market_id"] != "9"])["status"] == "UNDERPOWERED"
    assert summarize([r for r in rows if r["target_date"] != "9"])["status"] == "UNDERPOWERED"


def test_cli_deterministic_create_only_reports(tmp_path, monkeypatch, capsys):
    panel = SyntheticPanel()
    panel.event()
    paths = panel.write(tmp_path / "inputs")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return SCORE_AT

    monkeypatch.setattr(scorer, "datetime", Clock)
    monkeypatch.setattr(scorer.subprocess, "check_output", lambda *a, **k: TIP)
    args = [arg for p in paths for arg in ("--bundle", str(p))]
    output = tmp_path / "out"
    assert scorer.main([*args, "--out", str(output)]) == 0
    assert "DESCRIPTIVE_ONLY" in capsys.readouterr().out
    assert (output / "report.md").read_text().startswith("# T+1/T+2")
    report = json.loads((output / "report.json").read_bytes())
    assert report["implementation_hashes"] and report["exports"]
    with pytest.raises(SystemExit) as exc:
        scorer.main([*args, "--out", str(output)])
    assert exc.value.code == 2


def test_actual_110l_export_and_settlement_carry_roundtrip(tmp_path, monkeypatch):
    from tests.market import test_maker_plugin_dry_run as fixtures
    from weather.market.maker_replay_bundle import export
    when = AT.replace(minute=20)
    monkeypatch.setattr(fixtures, "NOW", when)
    monkeypatch.setattr(fixtures, "bulletin", lambda spec, target: bulletin(
        spec, target, issue=AT.replace(hour=13), fetched=AT-timedelta(minutes=30)))
    args, _, _ = fixtures.layout(tmp_path, minutes=2)
    args.out = tmp_path / "capture"
    args.max_output_bytes, args.max_records = 64 * 1024**2, 100000
    export(args, now=SCORE_AT)
    first = args.out
    _, bands, spec, target, _, _ = fixture(lead=1, now=when)
    label = ledger(bands, spec, target)
    fixtures.jsonl(args.data_root / "settlements/nyc/ledger.jsonl", [label])
    args.date, args.carry_bundle, args.out = label["recorded_at_utc"][:10], [first], tmp_path / "settled"
    export(args, now=SCORE_AT)
    result = scorer.score([first, args.out], code_tip=TIP, now=SCORE_AT)
    assert result["capture_exclusions"] == result["settlement_exclusions"] == {}
    assert result["tables"]["nbp_lead_1"]["hours"] == 1
    assert result["selected_hours"][0]["captured_at"] == when.isoformat()
