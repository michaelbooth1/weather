"""Consume a reviewed manifest's single look before policy invocation; fail closed."""
from pathlib import Path

from maker_core.replay.bundle import BundleError, regular_path
from maker_core.replay.pack_io import write_json


def reserve_attempt(manifest_path, doc, key, now):
    # Production must retain its canonical sealed manifest directory. A relocated
    # copy is not a new attempt, just as an archived pre-revocation log is not authority.
    root = regular_path(Path(manifest_path).parent / "attempts")
    root.mkdir(exist_ok=True)
    attempt = root / (doc["owner_decision"]["authorization_id"]+".json")
    try:
        write_json(attempt, dict(status="CONSUMED_BEFORE_POLICY", authorization_id=doc["owner_decision"]["authorization_id"],
            manifest_sha256=key, verified_at=now.isoformat(), owner_decision=doc["owner_decision"],
            input_hashes=doc["input_hashes"], source_hashes=doc["source_hashes"],
            replay_config=doc["replay_config"], calibration_sha256=doc["calibration_sha256"]))
    except FileExistsError as exc:
        raise BundleError("authorization_attempt_already_consumed") from exc
    return attempt


def evaluate_hurdles(report):
    """The frozen conjunction, never a best-baseline or best-bound selection."""
    reasons = []
    bounds = report.get("bounds", {})
    if set(bounds) != {"strictly_through", "at_price"}:
        return dict(status="BLOCKED", reasons=["missing_fill_bound"])
    primary = bounds["strictly_through"]
    for bound, value in bounds.items():
        for baseline in ("blind_re1", "no_quote", "clock_only"):
            for metric in ("modeled_net_k1", "modeled_net_k05"):
                if baseline+":"+metric not in value.get("intervals", {}):
                    reasons.append("missing_contrast:"+bound+":"+baseline+":"+metric)
        if not value.get("scores") or not value.get("traces") or "pull_efficiency" not in value:
            reasons.append("missing_report_fields:"+bound)
    economic_ok = True
    for baseline in ("blind_re1", "no_quote"):
        estimates = primary.get("intervals", {}).get(baseline+":modeled_net_k1", {}).get("intervals") or {}
        for cluster in ("date", "date_x_market"):
            e = estimates.get(cluster, {})
            if (e.get("status") != "OK" or e.get("date_clusters", 0) < 10 or e.get("market_clusters", 0) < 10
                    or e.get("valid_replicates", 0) < 100 or not e.get("interval")):
                reasons.append("UNDERPOWERED:"+baseline+":"+cluster)
                economic_ok = False
            elif e["interval"][0] <= 0:
                reasons.append("economic_lower_bound_not_positive:"+baseline+":"+cluster)
                economic_ok = False
    pull = primary.get("pull_efficiency", {})
    pull_ok = pull.get("status") == "HURDLE_MET"
    if not pull_ok:
        reasons.append("pull:"+str(pull.get("status", "BLOCKED")))
    status = "REPLAY_HURDLES_MET" if economic_ok and pull_ok and not reasons else "HURDLE_NOT_MET"
    if any(r.startswith("missing_") for r in reasons):
        status = "BLOCKED"
    elif any(r.startswith("UNDERPOWERED") for r in reasons) or pull.get("status") == "UNDERPOWERED":
        status = "UNDERPOWERED"
    elif pull.get("status") in ("UNMATCHED", "UNIDENTIFIED"):
        status = pull["status"]
    return dict(status=status, economic_hurdle_met=economic_ok, pull_hurdle_met=pull_ok,
                reasons=reasons, interpretation="Modeled replay hurdles only; no live or profitability authority.")
