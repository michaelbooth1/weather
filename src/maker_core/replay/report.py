"""Deterministic dual-bound report composition; CLI authority is enforced before IO."""
from dataclasses import replace
from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.authorization import POLICIES
from maker_core.replay.baselines import matched_clock
from maker_core.replay.diagnostics import ASSUMPTIONS, coverage_report
from maker_core.replay.engine import ReplayConfig, replay
from maker_core.replay.fill_model import BOUNDS
from maker_core.replay.inference import paired_cells, cluster_intervals
from maker_core.replay.score import score
from maker_core.replay.pull_efficiency import pull_efficiency

REPLAY_ASSUMPTIONS = (
    "Strictly-through is primary; at-price is sensitivity. Public price paths do not identify queue fills.",
    "Sibling and unfilled remainder cancel immediately, with zero latency; invisible cancels remain unobserved.",
    "Books are sampled, held at most 60 seconds, with ten-second submit freshness; gaps exclude exposure.",
    "Nominal rebates and modeled liquidity rewards are not payments and never increase replay cash.",
    "Markouts allow the first two-sided book up to 120 seconds after each horizon, never a zero for missing marks.",
    "Inventory starts empty and is held to reconciled settlement or censored at the last supplied day boundary.",
    "Band admission uses condition-ID order; inventory constrains caps without an invented liquidation rule.",
    "Late prints predating the current order are excluded; canceled historical orders are not reconstructed.",
    "Cash, hazard and caps are hypothetical predeclared inputs; no empirical hazard is fitted by the harness.",
    "Clock matching uses only retrospective pull exposure, not returns; unmatched controls have no intervals.",
    "Cluster minimums and synthetic checks do not establish power, economic edge or live readiness.",
)


# k=1 and k=0.5 are registered; k=0.3 (Clarification 2) is a reported sensitivity that
# no hurdle, estimator or decision reads.
REPORTED_METRICS = ("modeled_net_k1", "modeled_net_k05", "modeled_net_k03")
SENSITIVITY_METRICS = ("modeled_net_k03",)


def comparison_report(bundles, config=ReplayConfig(), *, replicates=2000, seed=20260926,
                      registration_hash=None, check=lambda: None):
    bundles = tuple(sorted(bundles, key=lambda b: b.day))
    report = dict(format="maker_core.replay.comparison.v0.1", mode="comparison",
        status="FIXTURE_ONLY" if all(b.provenance == "synthetic" for b in bundles) else "PRE_REGISTERED_REPLAY",
        pre_registration_sha256=registration_hash, configuration=config,
        input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
        coverage=[coverage_report(b, config.policy, check=check) for b in bundles],
        parity=dict(status="FULL_SESSION_NOT_QUALIFIED",
                    reason="all 313 recorded minutes match; five terminal projections retain source-revision/input-coverage findings",
                    available_fixture_scope="selection prices and recorded minute/terminal projections; see test_re1_parity"),
        assumptions=(*ASSUMPTIONS[:4], *REPLAY_ASSUMPTIONS), bounds={})
    for bound in BOUNDS:
        check()
        cfg = replace(config, policy="informed-v0", fill_bound=bound, clock_pulls=())
        results = {"informed-v0": replay(bundles, cfg, check=check)}
        for policy in ("no_quote", "blind_re1"):
            results[policy] = replay(bundles, replace(cfg, policy=policy), check=check)
        results["clock_only"], matching = matched_clock(bundles, cfg, results["informed-v0"], check=check)
        scores = {name: score(results[name], check=check) for name in POLICIES}
        intervals = {}
        for baseline in POLICIES[1:]:
            for metric in REPORTED_METRICS:
                key = baseline + ":" + metric
                if baseline == "clock_only" and matching["status"] != "MATCHED":
                    intervals[key] = dict(status="UNMATCHED_CLOCK_CONTROL", intervals=None)
                    continue
                cells, excluded = paired_cells(scores["informed-v0"], scores[baseline], metric)
                intervals[key] = dict(excluded_market_dates=excluded,
                    intervals=cluster_intervals(cells, replicates=replicates, seed=seed, check=check))
        report["bounds"][bound] = dict(scores=scores, intervals=intervals, clock_match=matching,
            pull_efficiency=pull_efficiency(results["informed-v0"], results["clock_only"], matching,
                                           replicates=replicates, seed=seed, check=check),
            traces={name: dict(decision_count=len(r.decisions), decision_sha256=digest(r.decisions),
                              final_cash=r.final_cash, fills=r.fills, exclusions=r.exclusions,
                              excluded_intervals=[dict(start=s.start, end=s.end, condition_id=s.condition_id,
                                  reason=s.reason) for s in r.spans if s.evaluation_active and not s.covered])
                    for name, r in results.items()})
    return report


def _safe(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def report_bytes(report):
    raw = canonical_bytes(report)
    lines = ["# Maker replay report", "", "**" + report["status"] + " — modeled counterfactuals.**", "",
              "Full-session parity: NOT QUALIFIED. Recorded minutes match; terminal and transport coverage gaps remain; "
             "no live or promotion verdict follows from replay.", "",
              "Registration SHA-256: " + str(report["pre_registration_sha256"]), ""]
    if "registered_decision" in report:
        lines += ["Registered decision: **"+report["registered_decision"]["status"]+"**.",
                  "Reasons: "+", ".join(report["registered_decision"]["reasons"]), ""]
    for bound, result in report["bounds"].items():
        lines += ["## " + bound, "", "Clock match: " + result["clock_match"]["status"], "",
                  "| Policy | Date | Condition | Coverage | Reward k=1 | Reward k=.5 | Reward k=.3 (sensitivity) | Nominal rebate | Settlement P&L | Cash-hours | Pull fraction | Fills |",
                  "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for policy, rows in result["scores"].items():
            for r in rows:
                values = [policy, r["date"], r["condition_id"], r["status"], r["reward_k1"], r["reward_k05"], r["reward_k03"],
                          r["nominal_rebate"], r["settled_inventory_pnl"], r["cash_hours"], r["pulled_minute_fraction"], r["fills"]]
                lines.append("| " + " | ".join(_safe(v) for v in values) + " |")
        lines += ["", "### Paired 90% intervals", "",
                  "`modeled_net_k03` is the measured-reaction sensitivity (k=0.3): reported only, never a hurdle.", ""]
        for comparator, entry in result["intervals"].items():
            if entry.get("intervals") is None:
                lines.append("- " + comparator + ": " + entry["status"])
            else:
                for cluster, estimate in entry["intervals"].items():
                    lines.append(f"- {comparator} / {cluster}: {estimate['status']}; mean {estimate['estimate']}; "
                                 f"90% {estimate['interval']}; dates={estimate['date_clusters']}, markets={estimate['market_clusters']}.")
        pull = result["pull_efficiency"]
        lines += ["", "### Pull efficiency", "",
                  f"{pull['status']}; ratio {pull['ratio']}; common opportunities {pull['counts']['opportunities']}; "
                  f"sampled exposure {pull['exposure_match']['status']}.", ""]
        for policy in ("informed", "clock"):
            lines.append(f"- {policy}: {pull['counts'][policy + '_removed']} large moves removed / "
                         f"{pull['counts'][policy + '_pulled']} pulled minutes; efficiency {pull['efficiencies'][policy]}.")
        for cluster, estimate in pull["intervals"].items():
            lines.append(f"- {cluster}: {estimate['status']}; 90% {estimate['interval']}; "
                         f"dates={estimate['date_clusters']}, markets={estimate['market_clusters']}; "
                         f"valid={estimate['valid_replicates']}, empty={estimate['empty_replicates']}, "
                         f"undefined={estimate['undefined_replicates']}.")
        lines += ["", "Detailed markouts, missing counts, fees, requotes, event fills, coverage exclusions and trace hashes are in JSON.", ""]
    lines += ["## Assumptions", "", *("- " + x for x in report["assumptions"]), "", "## Input hashes", ""]
    for day, hashes in sorted(report["input_hashes"].items()):
        lines.extend(f"- {day} / {_safe(k)}: `{v}`" for k, v in sorted(hashes.items()))
    return raw, ("\n".join(lines) + "\n").encode()
