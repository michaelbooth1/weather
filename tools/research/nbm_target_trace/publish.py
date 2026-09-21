"""Finite-census tables and read-only artifact binding evidence for the handback."""
from __future__ import annotations

import json

import pandas as pd

from weather.paths import repo_path
from .run import sha, write_json


def publish(root):
    out = repo_path("tools/research/nbm_target_trace/evidence")
    copies = {
        "tokens.csv": root / "t0/tokens.csv",
        "picks.csv": root / "t1/picks.csv",
        "t0-receipt.json": root / "t0/receipt.json",
        "t1-receipt.json": root / "t1/receipt.json",
        "t2-summary.json": root / "t2/summary.json",
        "t2-receipt.json": root / "t2/receipt.json",
        "artifact-selectors.json": root / "artifact_audit.json",
        **{f"blocks/{p.name}": p for p in (root / "t0/blocks").glob("*.txt")},
    }
    for name, source in copies.items():
        destination = out / name
        # Git pins LF. Retained download bytes stay unchanged in scratch;
        # reviewed text tables are normalized before their publication hashes.
        body = source.read_bytes().replace(b"\r\n", b"\n")
        if name.startswith("blocks/"):
            body = b"\n".join(line.rstrip() for line in body.splitlines()) + b"\n"
        if destination.exists():
            if destination.read_bytes() != body:
                raise ValueError(f"published copy differs: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
    picks = pd.read_csv(root / "t1/picks.csv")
    tokens = pd.read_csv(root / "t0/tokens.csv")
    diagnostic = pd.read_csv(root / "t2/diagnostic_rows.csv")
    def distribution(series):
        values = series.dropna()
        return dict(n=len(values), median=float(values.median()) if len(values) else None,
                    q10=float(values.quantile(.1)) if len(values) else None,
                    q90=float(values.quantile(.9)) if len(values) else None)
    magnitude = []
    for kind, g in tokens.groupby("period_kind"):
        g = g[g.observed_max_f.notna() & g.observed_min_f.notna()]
        magnitude.append(dict(kind=kind, n=len(g), dates=g.period_date.nunique(),
            markets=g.market.nunique(), p50_minus_max=distribution(g.TXNP5 - g.observed_max_f),
            p50_minus_min=distribution(g.TXNP5 - g.observed_min_f)))
    actual_min = tokens[["market", "period_date", "observed_min_f"]].drop_duplicates()
    wrong = picks[picks.classification == "wrong"].merge(
        actual_min, on=["market", "period_date"], how="left")
    comparisons = dict(n=len(wrong), dates=wrong.target_date.nunique(), markets=wrong.market.nunique(),
                       p50_minus_requested_max=distribution(wrong.p50 - wrong.observed_max_f),
                       p50_minus_actual_period_min=distribution(wrong.p50 - wrong.observed_min_f_y))
    recovered = []
    for key, g in diagnostic[diagnostic.dropped_nbm].groupby(["stratum", "hour"]):
        for field in ("p10", "p25"):
            subset = g[g["recovered_" + field]]
            recovered.append(dict(stratum=key[0], hour=int(key[1]), quantile=field,
                 n=len(subset), dates=subset.date.nunique(), markets=subset.market.nunique(),
                 minus_max=distribution(subset[field] - subset.settled_max_f),
                 minus_next_min=distribution(subset[field] - subset.next_min_f)))
    sig = diagnostic[(diagnostic.signature_match == "minimum") & diagnostic.dropped_nbm]
    signature_support = dict(n=len(sig), dates=sig.date.nunique(), markets=sig.market.nunique(),
                             market_days=len(sig[["market", "date"]].drop_duplicates()))
    audit = json.loads((root / "artifact_audit.json").read_text())
    registry_path = repo_path("config/model_variant_registry.json")
    registry = json.loads(registry_path.read_text())
    variants = registry["variants"]
    selected = set(audit["selecting_nbm"])
    bindings = [v for v in variants if v.get("artifact_path") in selected]
    compact_audit = [dict(path=r["path"], sha256=r["sha256"], nbm_selected=r["nbm_selected"],
                          model_selectors={k: [n for n in v if n.startswith("nbm_prob_tmax_")]
                            for k, v in r["selector_sets"].items()
                            if k.startswith("/models/") and k.endswith("/feature_names")})
                     for r in audit["records"] if r["nbm_selected"]]
    write_json(out / "supplement.json", dict(token_magnitudes=magnitude,
        wrong_pick_magnitudes=comparisons, recovered_quantiles=recovered,
        minimum_signature_support=signature_support,
        active_artifact_bindings=bindings, selecting_artifacts=compact_audit,
        registry_sha256=sha(registry_path),
        active_nbm_consumption_blocks_t3=any(v.get("lifecycle") == "active" and
                                             v.get("live_capture_enabled") for v in bindings)))
    # This records the exact hash of every finite evidence file; national
    # bulletins remain only in the cache and have their own download receipts.
    write_json(out / "file-manifest.json", {
        str(p.relative_to(out)).replace("\\", "/"): sha(p)
        for p in sorted(out.rglob("*")) if p.is_file()})
    print(json.dumps(dict(token_magnitudes=magnitude, wrong_pick_magnitudes=comparisons,
                          minimum_signature_support=signature_support)), flush=True)
