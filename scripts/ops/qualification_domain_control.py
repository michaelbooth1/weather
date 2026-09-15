"""Fixed B recovery/documentation entrypoints with explicit production paths.

Recovery remains possible after certificate expiry. Its authority is the exact
attempt manifest and adopted control closure, never a newly imported S module.
"""

from pathlib import Path
import json
import sys


if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 4:
    raise RuntimeError("fixed isolated domain-controller arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification import frozen, git_policy, host_runtime, source
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.host_session import _raw_reference
from weather.operations.qualification.records import checked_root, read, require


manifest_path, manifest_sha, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
require(mode in {"capture", "execution-status", "documentation"}, "unsupported fixed domain action")
root = checked_root(manifest_path.parent)
ref = _raw_reference(root, manifest_path.name)
require(ref["sha256"] == manifest_sha, "domain controller manifest changed")
m = read(root, ref).value
require(m["schema"] == "weather_integration_attempt_manifest_v2" and m["qualification_mode"] == "split_v2" and
        trusted == Path(m["control"]["root"]), "domain controller is not the frozen baseline")
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
# No site processing: only exact already-qualified package directories are added.
sys.path[:] = [*sys.path, *selected["bindings"]["site_roots"]]
from weather import paths

paths.REPO_ROOT = production
for name, directory in (("DATA_ROOT", "data"), ("ARTIFACTS_ROOT", "artifacts"), ("CONFIG_ROOT", "config"),
                        ("DOCS_ROOT", "docs"), ("TOOLS_ROOT", "tools")):
    setattr(paths, name, production / directory)
if mode == "capture":
    from weather.operations.capture_recovery_check import check_capture_recovery
    result = check_capture_recovery(production)
elif mode == "execution-status":
    from weather.operations.execution_tape_supervisor import read_status, execution_tape_health
    status = read_status()
    result = {"status": status, "health": execution_tape_health(status, stale_after_seconds=180)}
else:
    from weather.operations.documentation_transaction import begin_transaction
    head = source.git_output(git, production, "rev-parse", "HEAD").decode().strip()
    result = begin_transaction(production, integration_tip=head, branch=m["branch_ref"], expected_tip=m["expected_tip"])
print(json.dumps(result, sort_keys=True, default=str))
