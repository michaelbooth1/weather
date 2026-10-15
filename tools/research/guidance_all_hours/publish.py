"""Render aggregate 111h tables from retained stage outputs; never loads rows or scores."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.research.missing_information.extract import sha256
from tools.research.guidance_all_hours.run import FREEZE_COMMIT, PREREG_HASH


def fmt(x, digits=6):
    return "n/a" if x is None else f"{x:.{digits}f}"


def est(r, digits=6):
    return f"{fmt(r['estimate'], digits)} [{fmt(r['ci95'][0], digits)}, {fmt(r['ci95'][1], digits)}]"


def reasons(counts):
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def planning(p):
    if p.get("status") != "PLUG_IN_PLANNING_ONLY":
        tail = fmt(p.get("power_by_new_dates", {}).get("45"), 3) if "power_by_new_dates" in p else "n/a"
        return f"{p['status']} (half {fmt(p['half_development_effect'])}; power@45 {tail})"
    return f"N = {p['new_dates']} dates (half {fmt(p['half_development_effect'])}; end {p['end_date_at_full_accrual']})"


def publish(control, census, development, output):
    sources = {"control": control, "census": census, "development": development}
    data = {k: json.loads(v.read_text(encoding="utf-8")) for k, v in sources.items()}
    for d in data.values():
        assert d["header"]["freeze"]["preregistration_sha256"] == PREREG_HASH
        assert d["header"]["freeze"]["freeze_commit"] == FREEZE_COMMIT
    dev = data["development"]
    header = f"Pre-registration SHA-256 `{PREREG_HASH}`; freeze commit `{FREEZE_COMMIT}`."
    label = dev["decision"]["label"]
    lines = [header, ""]
    if label:
        lines += [f"**Every v2 table below: {label}.**", ""]
    lines += ["95% crossed date × market bootstrap, 2,000 draws, seed 20260921. N = market-days; "
              "D/M = date/market clusters. Delta = candidate − served Brier.", "",
              "### v2 C1/C2 versus served and market", "",
              "| Block / stratum | Rows; N; D/M | Cand. | Delta [95%] | MDE80; power@−0.0075 | "
              "Ratio to market [95%] | Ratio MDE80; power@−0.10 | Changed rows (share) | Changed N; D/M |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in dev["tables"]:
        for c in ("C1", "C2"):
            x = t[c]
            lines.append(
                f"| {t['block']} / {t['stratum']} | {t['snapshots']}; {t['market_days']}; "
                f"{t['date_clusters']}/{t['market_clusters']} | {c} | {est(x['delta'])} | "
                f"{fmt(x['delta']['mde80'])}; {fmt(x['delta']['power'], 3)} | {est(x['ratio_to_market'], 4)} | "
                f"{fmt(x['ratio_to_market']['mde80'], 4)}; {fmt(x['ratio_to_market']['power'], 3)} | "
                f"{x['changed_snapshots']} ({100 * x['changed_snapshot_share']:.2f}%) | "
                f"{x['changed_market_days']}; {x['changed_date_clusters']}/{x['changed_market_clusters']} |")
    lines += ["", "### Absolute Brier, C2 − C1 and eligibility reasons", "",
              "| Block / stratum | Served [95%] | Market [95%] | C1 [95%] | C2 [95%] | C2 − C1 [95%] | "
              "Day-weighted changed share C1 [95%] | Eligibility reasons (rows) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in dev["tables"]:
        lines.append(f"| {t['block']} / {t['stratum']} | {est(t['served'])} | {est(t['market'])} | "
                     f"{est(t['C1']['brier'])} | {est(t['C2']['brier'])} | {est(t['C2_minus_C1'])} | "
                     f"{est(t['C1']['changed_market_day_share'], 4)} | {reasons(t['reason_counts'])} |")
    lines += ["", "### Half-development-effect planning (plug-in, not an α spend)", "",
              "| Block / stratum | C1 | C2 |", "| --- | --- | --- |"]
    for t in dev["tables"]:
        lines.append(f"| {t['block']} / {t['stratum']} | {planning(t['C1']['planning'])} | "
                     f"{planning(t['C2']['planning'])} |")
    output.mkdir(parents=True, exist_ok=False)
    (output / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = {"header": dev["header"], "source_output_sha256": {k: sha256(v) for k, v in sources.items()},
              "control": data["control"], "census": data["census"],
              "development": {"tables": dev["tables"], "decision": dev["decision"]}}
    (output / "evidence.json").write_text(json.dumps(bundle, indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("control", "census", "development", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    publish(args.control, args.census, args.development, args.output)


if __name__ == "__main__":
    main()
