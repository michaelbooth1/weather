"""Render reviewed aggregate tables; do not load raw snapshots or score."""
from __future__ import annotations

import json
from tools.research.missing_information.extract import sha256
from tools.research.missing_information.run import write_json
from tools.research.morning_guidance.run import PREREG_HASH, FREEZE_COMMIT


def fmt(x, digits=6):
    return "unavailable" if x is None else f"{x:.{digits}f}"


def estimate(r, digits=6):
    return f"{fmt(r['estimate'], digits)} [{fmt(r['ci95'][0], digits)}, {fmt(r['ci95'][1], digits)}]"


def publish(root, output, header):
    sources = {name: root / path for name, path in {
        "P0": "coverage-2/coverage.json", "coverage_corrected": "coverage-3/coverage.json",
        "development": "development-2/development.json", "first_development": "development-1/development.json",
        "push_receipt": "push-receipt.json"}.items()}
    data = {k: json.loads(v.read_text()) for k, v in sources.items()}
    dev, coverage = data["development"], data["coverage_corrected"]
    assert dev["header"]["preregistration_sha256"] == PREREG_HASH
    assert dev["header"]["freeze_commit"] == FREEZE_COMMIT
    # The rerun only adds support bookkeeping. Every published score is unchanged.
    for old, new in zip(data["first_development"]["tables"], dev["tables"]):
        assert (old["window"], old["population"], old["stratum"]) == (new["window"], new["population"], new["stratum"])
        for candidate in ("C1", "C2"):
            for key in ("brier", "delta", "ratio_to_market", "planning"):
                assert old[candidate][key] == new[candidate][key], (candidate, key)
    bundle = {"header": {**header, "preregistration_sha256": PREREG_HASH, "freeze_commit": FREEZE_COMMIT,
                         "preregistration_status": "FROZEN_AND_PUSHED_DEVELOPMENT_ONLY"},
              "source_output_sha256": {k: sha256(v) for k, v in sources.items()},
              "first_score_at_utc": data["first_development"]["first_score_at_utc"],
              "push_receipt": data["push_receipt"], "development": dev,
              "coverage": {k: v for k, v in coverage.items() if k != "secondary_complete_inputs"},
              "P0_correction": "Only 1 of 17 later complete NBM rows had a guidance floor; 16 had no floor. The 1.08 F range refers to that one row only."}
    write_json(output / "evidence.json", bundle)
    lines = [f"Pre-registration SHA-256: `{PREREG_HASH}`; freeze `{FREEZE_COMMIT}`.", "",
             "All intervals are 95% crossed date x market, 2,000 draws. N = market-days; D/M = date/market clusters.", ""]
    for window in ("morning_06_10", "secondary_10_13"):
        lines += [f"### {window}", "",
                  "| Population / stratum | Rows; N; D/M | Candidate | Delta [95%] | MDE80; power at -0.0075 | Ratio to market [95%] | Ratio MDE80; power at -0.10 | Changed rows |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for t in dev["tables"]:
            if t["window"] != window:
                continue
            for c in ("C1", "C2"):
                x = t[c]
                lines.append(f"| {t['population']} / {t['stratum']} | {t['snapshots']}; {t['market_days']}; {t['date_clusters']}/{t['market_clusters']} | {c} | {estimate(x['delta'])} | {fmt(x['delta']['mde80'])}; {fmt(x['delta']['power'], 3)} | {estimate(x['ratio_to_market'], 4)} | {fmt(x['ratio_to_market']['mde80'], 4)}; {fmt(x['ratio_to_market']['power'], 3)} | {x['changed_snapshots']} ({100*x['changed_snapshot_share']:.4f}%) |")
        lines += [""]
    lines += ["### Absolute Brier and changed-share intervals", "",
              "The changed-share estimand below equally weights market-days; the raw snapshot share above is a finite-export count.", "",
              "| Window / population / stratum | Served Brier [95%] | Market Brier [95%] | C1 Brier [95%] | C2 Brier [95%] | Changed day-weighted share [95%] | Share MDE80; power at +.10 | Changed N; D/M |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in dev["tables"]:
        x = t["C1"]
        lines.append(f"| {t['window']} / {t['population']} / {t['stratum']} | {estimate(t['served'])} | {estimate(t['market'])} | {estimate(x['brier'])} | {estimate(t['C2']['brier'])} | {estimate(x['changed_market_day_share'], 5)} | {fmt(x['changed_market_day_share']['mde80'], 5)}; {fmt(x['changed_market_day_share']['power'], 3)} | {x['changed_market_days']}; {x['changed_date_clusters']}/{x['changed_market_clusters']} |")
    lines += ["", "### Half-effect planning, morning", "",
              "No cell below attains 80% in the frozen planning scenario. Alpha .025 one-sided per candidate; not a spend.", "",
              "| Population / stratum | Candidate | Half effect | Power at 45 dates | Infinite-date market-only power | N / end date |",
              "| --- | --- | --- | --- | --- | --- |"]
    for t in dev["tables"]:
        if t["window"] != "morning_06_10":
            continue
        for c in ("C1", "C2"):
            p = t[c]["planning"]
            lines.append(f"| {t['population']} / {t['stratum']} | {c} | {fmt(p['half_development_effect'])} | {fmt(p['power_by_new_dates']['45'], 3)} | {fmt(p['infinite_date_market_only_power'], 3)} | unavailable / no finite date established |")
    (output / "tables.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print("aggregate publication preserves every development-1 score and planning result", flush=True)
