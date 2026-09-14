"""Read-only arming proof; only the admitted native parent may publish ARMED."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import attempt, authentication, host_acceptance, host_runtime
from .contracts import fields
from .host_session import _raw_reference
from .records import checked_root, publish, read, require, timestamp, utc_now


def planned_expiry(checked, *, now):
    """The latest possible merge fits both independently authenticated expiries."""
    m, p, graph = checked["manifest"], checked["policy"], checked["graph"]
    q = m["qualification"]
    certificate = graph.get(q["certificate"])
    authentication.validate_import_graph(graph, q["import"], p=p, policy_ref=q["policy"],
        review_ref=q["review"], certificate_ref=q["certificate"], certificate=certificate, now=now, boundary="arm")
    # Local schedule timestamps include their reviewed UTC offset; using 04:00
    # is stricter than guessing how quickly the merge will finish after trigger.
    merge = datetime.fromisoformat(m["schedule"]["merge_at_local"])
    require(merge.tzinfo is not None, "arming requires the actual reviewed local UTC offset")
    latest = merge.replace(hour=4, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    require(now < latest, "planned adoption interval has elapsed")
    # Re-run the authoritative validator at the actual latest boundary. It
    # owns field names, code lifetime and authenticated remote-query freshness.
    authentication.validate_import_graph(graph, q["import"], p=p, policy_ref=q["policy"],
        review_ref=q["review"], certificate_ref=q["certificate"], certificate=certificate, now=latest, boundary="merge")
    from .evidence import validate_code
    validate_code(graph, q["policy"], q["review"], q["certificate"], now=latest)
    return latest.isoformat().replace("+00:00", "Z")


def run(request_path, request_sha256):
    request_path = Path(request_path)
    output = checked_root(request_path.parent)
    ref = _raw_reference(output, request_path.name)
    require(ref["sha256"] == request_sha256, "arming request bytes changed")
    request = fields(read(output, ref).value, {"manifest_path", "manifest_sha256", "deadline"})
    deadline = timestamp(request["deadline"])
    require(datetime.now(timezone.utc) < deadline <= datetime.now(timezone.utc) + timedelta(seconds=120),
            "arming metadata deadline exceeds native bound")
    path = Path(request["manifest_path"])
    root = checked_root(path.parent)
    manifest_ref = _raw_reference(root, path.name)
    require(manifest_ref["sha256"] == request["manifest_sha256"], "arming manifest changed")
    checked = attempt.manifest(read(root, manifest_ref).value, actual_root=root)
    m, plan = checked["manifest"], checked["host_plan"]
    require(output == root / "arm-work", "arming evidence escaped its fixed namespace")
    selected = host_runtime.profile(checked["local"].get(plan["environment"]), checked=checked)
    measured = host_acceptance.measurements(checked["local"], plan["measurements"], policy=checked["policy"], host_plan=plan)
    host_runtime.verify_source(checked, selected)
    host_runtime.verify_environment(checked, selected)
    host_runtime.verify_configuration(checked, selected, measured["phases"]["metadata"]["maximum"])
    signature = output / "signature"
    signature.mkdir()
    verified = host_runtime.verify_code_in_parent(checked, selected, scratch=signature,
                                                deadline=request["deadline"], boundary="arm")
    latest = planned_expiry(checked, now=datetime.now(timezone.utc))
    checked["graph"].fresh()
    checked["local"].fresh()
    completed = utc_now()
    require(timestamp(completed) <= deadline, "arming proof missed its deadline")
    return publish(output, "proof.json", {"schema": "qualification_arming_proof_v2",
        "manifest_sha256": manifest_ref["sha256"], "host_plan_sha256": m["host"]["sha256"],
        "configuration_sha256": plan["configuration"]["sha256"], "environment_sha256": plan["environment"]["sha256"],
        "certificate_sha256": m["qualification"]["certificate"]["sha256"], "import_sha256": m["qualification"]["import"]["sha256"],
        "validated_at": completed, "latest_merge": latest, "signature": verified,
        "native_parent_completion_required": True, "integration_eligible": False})
