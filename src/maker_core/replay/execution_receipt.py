"""Single-look receipts beside the canonical manifest; fail closed.

Clarification 2: a refusal before any score, fill, reward or hurdle value is computed
leaves a non-consuming refusal record naming its stage. Reservation immediately
precedes the first policy replay; any later stop consumes the look and says where.
"""
from datetime import timezone
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from maker_core.replay.bundle import BundleError, regular_path
from maker_core.replay.pack_io import read_json, write_json

MAX_REFUSAL_RECORDS = 1000


def attempts_root(manifest_path):
    # Production must retain its canonical sealed manifest directory. A relocated
    # copy is not a new attempt, just as an archived pre-revocation log is not authority.
    return regular_path(Path(manifest_path).parent / "attempts")


def reserve_attempt(manifest_path, doc, key, now):
    root = attempts_root(manifest_path)
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


def record_stop(attempt, stage, reason, now):
    """A consumed look that stopped after reservation; the reservation remains the authority."""
    return write_json(attempt.with_suffix(".stopped.json"), dict(status="CONSUMED_STOPPED", stage=stage,
                      reason=str(reason)[:500], stopped_at=now.isoformat()))


def record_refusal(root, authorization_id, stage, reason, now, manifest_sha256=None):
    """Non-consuming operational refusal before any score; one create-only file per refusal."""
    root = regular_path(root)
    root.mkdir(exist_ok=True)
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", authorization_id) is None:
        raise BundleError("invalid_authorization_id")
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"{authorization_id}.refusal-{stamp}-{os.urandom(4).hex()}.json"
    write_json(path, dict(status="NOT_CONSUMED_OPERATIONAL_REFUSAL", authorization_id=authorization_id,
                          stage=stage, reason=str(reason)[:500], refused_at=now.isoformat(),
                          toronto_date=now.astimezone(ZoneInfo("America/Toronto")).date().isoformat(),
                          manifest_sha256=manifest_sha256))
    return path


def late_look_permitted(manifest_path, doc):
    """True only when a non-consuming refusal was recorded on the scoring date itself."""
    decision = doc.get("owner_decision") if isinstance(doc, dict) else None
    if not isinstance(decision, dict) or not isinstance(decision.get("authorization_id"), str):
        return False
    root = Path(manifest_path).parent / "attempts"
    if not root.is_dir():
        return False
    found = sorted(root.glob(decision["authorization_id"]+".refusal-*.json"))
    if len(found) > MAX_REFUSAL_RECORDS:
        raise BundleError("refusal_record_cap")
    if (root / (decision["authorization_id"]+".json")).exists():
        return False
    for path in found:
        record, _ = read_json(path, 65536)
        if (record.get("status") == "NOT_CONSUMED_OPERATIONAL_REFUSAL"
                and record.get("authorization_id") == decision["authorization_id"]
                and record.get("toronto_date") == decision.get("scoring_date")):
            return True
    return False


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
