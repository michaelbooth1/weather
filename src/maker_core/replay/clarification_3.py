"""Clarification 3, reported only: quote presence, economic MDE and the screen-suppression label.

Nothing here feeds a status, hurdle flag, reason or decision rule. The registered
decision is computed first by ``evaluate_hurdles`` and these fields are attached
beside it under one key; tests pin the decision byte-identical with and without them.
"""
from decimal import Decimal as D

from maker_core.replay.execution_receipt import evaluate_hurdles

# The frozen pull hurdle's point ratio. Against an exposure-matched clock whose pulls do
# not depend on moves, a policy quoting a fraction f of the common minutes has an expected
# ratio of at most N / max(L, P) <= 1 / (1 - f), even if it pulls before every large move.
# Below 1 - 1/2 the registered hurdle is out of reach by construction, not by evidence.
PULL_RATIO_HURDLE = D(2)
SCREEN_SUPPRESSION_THRESHOLD = 1 - 1 / PULL_RATIO_HURDLE
SCREEN_SUPPRESSED = "NOT_MET_SCREEN_SUPPRESSED"
ECONOMIC_BASELINES = ("blind_re1", "no_quote")
CLUSTERS = ("date", "date_x_market")


def _presence(eligible, quoted):
    return dict(eligible_seconds=eligible, quoted_seconds=quoted,
                quoted_fraction=quoted / eligible if eligible else None)


def quote_presence(scores):
    """Per policy and city-market: covered active band time, the share with a leg resting.

    Eligible time is every covered second of a declared active interval, whatever the
    band-day row's status; coverage gaps and inactive periods are excluded, never zeros.
    """
    result = {}
    for policy, rows in scores.items():
        markets = {}
        for r in rows:
            totals = markets.setdefault(r["market_id"], [D(0), D(0)])
            totals[0] += r["covered_seconds"]
            totals[1] += r["covered_seconds"] - r["pulled_seconds"]
        result[policy] = dict(
            pooled=_presence(sum((v[0] for v in markets.values()), D(0)), sum((v[1] for v in markets.values()), D(0))),
            markets={market: _presence(*totals) for market, totals in sorted(markets.items())})
    return result


def economic_mde(primary):
    """The four registered economic cells at the registered bootstrap, with what each could detect."""
    cells, mdes = {}, []
    for baseline in ECONOMIC_BASELINES:
        estimates = primary.get("intervals", {}).get(baseline + ":modeled_net_k1", {}).get("intervals") or {}
        for cluster in CLUSTERS:
            e = estimates.get(cluster) or {}
            interval, mde = e.get("interval"), e.get("mde_80_normal_approx")
            distinguishable = e.get("status") == "OK" and bool(interval) and interval[0] > 0
            mdes.append(mde)
            cells[baseline + ":" + cluster] = dict(
                status=e.get("status", "MISSING"), estimate=e.get("estimate"),
                lower_bound=interval[0] if interval else None,
                bootstrap_standard_error=e.get("bootstrap_standard_error"), mde_80=mde,
                distinguishable_from_zero=distinguishable,
                statement=None if distinguishable else (
                    "not distinguishable from zero; MDE unavailable" if mde is None else
                    f"not distinguishable from zero; this panel had about 80% power only for a true mean paired "
                    f"difference of at least {mde} pUSD per complete market/UTC-day"))
    return dict(fill_bound="strictly_through", metric="modeled_net_k1", cells=cells,
                binding_mde_80=None if None in mdes else max(mdes),
                method="(z_0.95 + z_0.80) x bootstrap standard error; one-sided 5% matches a 90% two-sided lower bound",
                interpretation="Descriptive design sensitivity; changes no status, hurdle or decision rule.")


def screen_label(decision, primary):
    presence = (primary.get("quote_presence") or {}).get("informed-v0", {}).get("pooled", {})
    fraction = presence.get("quoted_fraction")
    counts = (primary.get("pull_efficiency") or {}).get("counts") or {}
    opportunities = counts.get("opportunities")
    common = (1 - D(counts["informed_pulled"]) / D(opportunities)) if opportunities else None
    suppressed = decision.get("status") == "HURDLE_NOT_MET" and fraction is not None and fraction < SCREEN_SUPPRESSION_THRESHOLD
    return dict(label=SCREEN_SUPPRESSED if suppressed else None, threshold=SCREEN_SUPPRESSION_THRESHOLD,
                informed_quoted_fraction=fraction, pull_common_set_quoted_fraction=common,
                expected_pull_ratio_ceiling=None if common is None or common >= 1 else 1 / (1 - common),
                rule="HURDLE_NOT_MET and pooled informed-v0 strictly_through quoted fraction < 1 - 1/2",
                interpretation="Label only; the status is unchanged.")


def registered_decision(report):
    """The unchanged registered decision plus the Clarification 3 reported fields under one key."""
    decision = evaluate_hurdles(report)
    primary = report.get("bounds", {}).get("strictly_through") or {}
    return dict(decision, clarification_3=dict(
        quote_presence={bound: value.get("quote_presence") for bound, value in report.get("bounds", {}).items()},
        economic_mde=economic_mde(primary), screen=screen_label(decision, primary),
        interpretation="Clarification 3 reporting only; changes no status, hurdle, estimator or decision rule."))
