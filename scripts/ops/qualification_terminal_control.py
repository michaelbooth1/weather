"""Fixed adopted B read-only terminal inspection; expiry is not new authority."""

from pathlib import Path
import sys

if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
    raise RuntimeError("fixed isolated terminal arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification import frozen, git_policy, host_runtime, reconciliation, source
from weather.operations.qualification.contracts import Graph, fields
from weather.operations.qualification.host_session import _raw_reference
from weather.operations.qualification.records import checked_root, publish, read, require, timestamp, utc_now

request_path = Path(sys.argv[1])
output = checked_root(request_path.parent)
ref = _raw_reference(output, request_path.name)
require(ref["sha256"] == sys.argv[2], "terminal request changed")
request = fields(read(output, ref).value, {"manifest_path", "manifest_sha256", "prepared_baseline", "execution_required", "deadline"})
require(timestamp(utc_now()) < timestamp(request["deadline"]), "terminal deadline elapsed")
path = Path(request["manifest_path"])
root = checked_root(path.parent)
require(output.parent == root / "reconciliations", "terminal output escaped its fixed observation namespace")
ref = _raw_reference(root, path.name)
require(ref["sha256"] == request["manifest_sha256"], "terminal manifest changed")
m = read(root, ref).value
require(m["schema"] == "weather_integration_attempt_manifest_v2" and m["qualification_mode"] == "split_v2" and
        trusted == Path(m["control"]["root"]), "terminal controller is not the frozen baseline")
local, graph = Graph(root), Graph(Path(m["qualification"]["root"]))
plan = local.get(m["host"])
checked = {"manifest": m, "host_plan": plan, "local": local, "graph": graph,
           "review": graph.get(m["qualification"]["review"]), "policy": graph.get(m["qualification"]["policy"])}
selected = host_runtime.profile(local.get(plan["environment"]), checked=checked)
git = host_runtime.tool(selected, "git")
production = checked_root(Path(m["repo_root"]))
options = git_policy.validate(local.get(m["control"]["git_policy"]), git=git, production=production,
    candidate=Path(m["worktree_root"]), baseline=m["baseline"]["master"], commit=m["expected_tip"],
    graph=graph, environment_ref=selected["environment"], bindings=selected["bindings"])
source.bind_host_git_policy(options)
frozen.validate(git, production, m["baseline"]["master"], destination=trusted, value=local.get(m["control"]["closure"]))
host_runtime.verify_environment(checked, selected)
result = reconciliation.inspect_tree(checked, git, prepared_baseline=request["prepared_baseline"])
sys.path[:] = [*sys.path, *selected["bindings"]["site_roots"]]
from weather import paths

paths.REPO_ROOT = production
for name, directory in (("DATA_ROOT", "data"), ("ARTIFACTS_ROOT", "artifacts"), ("CONFIG_ROOT", "config"),
                        ("DOCS_ROOT", "docs"), ("TOOLS_ROOT", "tools")):
    setattr(paths, name, production / directory)
from weather.operations.capture_recovery_check import check_capture_recovery

capture = check_capture_recovery(production)
require(capture["ok"] is True and len(capture["workers"]) == 3 and all(row["ok"] for row in capture["workers"]),
        "terminal capture recovery is not healthy for all three workers")
require(type(request["execution_required"]) is bool, "terminal auxiliary producer requirement is untyped")
execution = reconciliation.execution_health(production) if request["execution_required"] else None
health_ref = reconciliation.retain_health(output, {"capture": capture, "execution_tape": execution})
graph.fresh()
local.fresh()
require(timestamp(utc_now()) < timestamp(request["deadline"]), "terminal inspection exceeded its native deadline")
publish(output, "current.json", {"schema": "qualification_terminal_current_v2", "manifest_sha256": ref["sha256"],
    "validated_at": utc_now(), "capture": {"ok": True, "workers": [
        {key: row[key] for key in ("name", "ok", "pid")} for row in capture["workers"]]}, "health": health_ref,
    "execution_required": request["execution_required"], "execution_healthy": True if execution is not None else None,
    "native_parent_completion_required": True, **result})
