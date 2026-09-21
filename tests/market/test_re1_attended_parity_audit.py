"""Mission 84a's stop-on-divergence audit, without credentials or network calls.

These tests retain counterexamples against the unmodified 80b implementation;
passing them proves the NO-GO, not readiness of an attended trading script.
"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.market.stage2_fakes import Clock, Venue, CONDITION, TOKENS
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import observe_held_quote, public_quote
from weather.market.mm_stage2_selection import select_table


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/roadmap/re1-reference"
RECORDED = REFERENCE / "re1_selection_2026-09-22_2026-09-21T172047757Z.json"


def reference_evaluate(snapshot, own=None):
    """Execute the supplied JavaScript itself, with identical public inputs."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to reproduce the supplied JavaScript")
    values = snapshot["quote_inputs"]
    payload = {
        "book": {"bids": values["yes_bids"], "asks": values["yes_asks"]},
        "terms": {"maxSpread": float(values["reward_max_spread_cents"]),
                  "minSize": float(values["reward_min_size"])},
        "own": own,
    }
    code = """
const fs = require('fs');
const L = require(process.argv[1]);
const x = JSON.parse(fs.readFileSync(0, 'utf8'));
const mid = L.evaluate(x.book, x.terms, null).mid;
const quote = L.quoteFor(mid, 0.01, 1.5);
const own = x.own || {yesBid: quote.yesBid, yesAsk: quote.yesAsk, size: 20};
process.stdout.write(JSON.stringify({quote, ...L.evaluate(x.book, x.terms, own)}));
"""
    result = subprocess.run(
        [node, "-e", code, str(REFERENCE / "re1_lib.js")],
        input=json.dumps(payload), text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def snapshot(bid=".40", ask=".43", no_bid=".57", no_ask=".60"):
    result = Venue(Clock()).snapshot()
    values = result["quote_inputs"]
    for name, price in (("yes_bids", bid), ("yes_asks", ask),
                        ("no_bids", no_bid), ("no_asks", no_ask)):
        values[name] = [{"price": price, "size": "100"}]
    values["reward_rate_per_day"] = "45"
    return result


def test_selection_counterexample_crosses_the_frozen_eligibility_threshold():
    inputs = snapshot()
    reference = reference_evaluate(inputs)
    table = select_table([{
        "market_id": "los-angeles", "market_timezone": REGISTRY["los-angeles"].timezone,
        "target_date": "2026-09-22", "condition_id": CONDITION,
        "token_ids": list(TOKENS), "snapshot": inputs,
    }], now=Clock().now())
    row = table["rows"][0]
    js_prediction = 45 / 1440 * 360 * reference["share_many"]
    assert reference["quote"]["yesBuyPrice"] == pytest.approx(.40)
    assert reference["quote"]["noBuyPrice"] == pytest.approx(.57)
    assert float(row["quote"]["yes_buy"]) == pytest.approx(.40)
    assert float(row["quote"]["no_buy"]) == pytest.approx(.57)
    assert reference["share_many"] == pytest.approx(.20)
    assert row["quote"]["share_many"] == pytest.approx(1 / 6)
    assert js_prediction == pytest.approx(2.25)
    assert row["predicted_360_minutes"] == pytest.approx(1.875)
    assert js_prediction >= 2
    assert row["refusal"] == "predicted_below_two"
    assert table["selected_condition_id"] is None
    print(json.dumps({"case": "selection_counterexample", "verdict": "BLOCKED",
                      "reference_share_many": reference["share_many"],
                      "python_share_many": row["quote"]["share_many"],
                      "reference_prediction": js_prediction,
                      "python_prediction": row["predicted_360_minutes"]}))


def test_minute_counterexample_uses_different_midpoints_on_identical_books():
    inputs = snapshot(".33", ".36", ".64", ".67")
    quote = public_quote(inputs, now=Clock().now(), condition_id=CONDITION, token_ids=TOKENS)
    own = {"yesBid": float(quote.yes_buy), "yesAsk": float(1 - quote.no_buy), "size": 20}
    # Positive control: the same midpoint and same resting prices agree.
    js_control = reference_evaluate(inputs, own)
    py_control = observe_held_quote(inputs, quote)
    assert py_control["visible_two_sided"] is True
    assert py_control["per_minute_many"] == pytest.approx(45 / 1440 * js_control["share_many"])
    # A valid sub-minimum touch changes JS midpoint but is ignored by Python.
    inputs["quote_inputs"]["yes_bids"].append({"price": ".34", "size": "1"})
    reference = reference_evaluate(inputs, own)
    observed = observe_held_quote(inputs, quote)
    assert observed["visible_two_sided"] is True
    assert reference["displayed_at_our_bid"] >= 20
    assert reference["displayed_at_our_ask"] >= 20
    assert Decimal(observed["adjusted_mid"]) == Decimal(".345")
    assert reference["mid"] == pytest.approx(.35)
    js_minute = 45 / 1440 * reference["share_many"]
    assert observed["per_minute_many"] != pytest.approx(js_minute)
    print(json.dumps({"case": "minute_counterexample", "verdict": "BLOCKED",
                      "reference_mid": reference["mid"], "python_mid": observed["adjusted_mid"],
                      "reference_share_many": reference["share_many"],
                      "python_share_many": observed["per_minute_many"] / (45 / 1440),
                      "reference_per_minute_many": js_minute,
                      "python_per_minute_many": observed["per_minute_many"]}))


def test_recorded_table_reproduces_only_what_its_retained_inputs_allow():
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    priority = {city: i for i, city in enumerate(recorded["location_order"])}
    eligible = sorted(recorded["eligible"], key=lambda row: (
        -row["predicted_pusd_many"], priority.get(row["location_id"], len(priority)), row["condition_id"]))
    assert eligible == recorded["eligible"]
    assert eligible[0] == recorded["selected"]
    rows = recorded["eligible"] + recorded["rejected"]
    quoted = [row for row in rows if "mid" in row]
    for row in quoted:
        mid, tick = Decimal(str(row["mid"])), Decimal(str(row["tick"]))
        # The recorded JS midpoint has binary rounding; use its tick epsilon.
        outward = lambda value: ((value / tick + Decimal("1e-9"))
                                  .to_integral_value(rounding="ROUND_FLOOR") * tick)
        yes, no = outward(mid - Decimal(".015")), outward(1 - mid - Decimal(".015"))
        assert float(yes) == pytest.approx(row["yes_buy_price"])
        assert float(no) == pytest.approx(row["no_buy_price"])
        assert float(20 * (yes + no)) == pytest.approx(row["capital_pusd"])
        for bound in ("many", "single"):
            assert row["rate"] / 1440 * 360 * row["share_" + bound] == pytest.approx(row["predicted_pusd_" + bound])
    # No level sizes or NO books were retained: do not invent a raw-book replay.
    assert all("bids" not in row and "asks" not in row and "snapshot" not in row for row in rows)
    print(json.dumps({"case": "recorded_table_partial_reproduction", "rows": len(rows),
                      "eligible": len(eligible), "quoted_rows": len(quoted),
                      "selected_condition": eligible[0]["condition_id"],
                      "reference_sha256": hashlib.sha256(RECORDED.read_bytes()).hexdigest(),
                      "raw_book_share_parity": "UNVERIFIABLE_INPUTS_NOT_RETAINED"}))


def test_retained_80b_books_also_have_selection_share_differences():
    """Supplement the 17:20 summary with 80b's earlier, complete book capture."""
    source = ROOT / "tests/fixtures/stage2_hold/20260921/selection.json"
    retained = json.loads(source.read_text(encoding="utf-8"))
    divergences = []
    for row in retained["rows"]:
        if "quote" not in row:
            continue
        reference = reference_evaluate(row["snapshot"])
        quote = row["quote"]
        if reference["share_many"] != pytest.approx(quote["share_many"]):
            divergences.append({"market_id": row["market_id"], "condition_id": row["condition_id"],
                                "reference_share_many": reference["share_many"],
                                "python_share_many": quote["share_many"],
                                "reference_yes_buy": reference["quote"]["yesBuyPrice"],
                                "python_yes_buy": quote["yes_buy"]})
    assert divergences, "If parity is repaired, replace this historical NO-GO audit"
    print(json.dumps({"case": "retained_80b_books", "verdict": "BLOCKED",
                      "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "source_time": retained["created_at_utc"], "divergences": divergences}))
