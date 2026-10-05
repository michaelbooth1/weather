"""Landing preflight check runners owned by L-P2: diff hygiene, docs audits, schema, shards, docs transaction.

Each runner takes a :class:`~weather.operations.landing_preflight.PreflightContext`
and returns a :class:`~weather.operations.landing_preflight.CheckResult`.
``register_checks`` adds them to the registry in run order.  Stubs return
ERROR (fail closed) until implemented.
"""

from __future__ import annotations

from weather.operations.landing_preflight import (
    ERROR,
    PHASE_OBJECTS,
    PHASE_WORKTREE,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
)

OWNER = "L-P2"


def classify_conflict_path(path: str) -> str:
    """``fix_class`` for a conflicted path (F5): regenerate_index, generated_config, ci_matrix, docs, tests, src."""

    normalized = path.replace("\\", "/")
    if "correspondence-index" in normalized or normalized.startswith("docs/roadmap/index"):
        return "regenerate_index"
    if normalized.startswith("config/") and ("generated" in normalized or normalized.endswith(".generated.json")):
        return "generated_config"
    if normalized.startswith(".github/workflows/"):
        return "ci_matrix"
    if normalized.startswith("docs/") or normalized.endswith(".md"):
        return "docs"
    if normalized.startswith("tests/"):
        return "tests"
    return "src"


def _stub(check_id: str):
    def run(ctx: PreflightContext) -> CheckResult:
        return CheckResult(ERROR, f"stub: {check_id} not implemented yet ({OWNER})")

    return run


def register_checks(registry: CheckRegistry) -> None:
    # Object phase (no worktree): the night-span gate and its attribution per step (F10).
    registry.register(CheckSpec("diff_check", PHASE_OBJECTS, _stub("diff_check"), OWNER, ("merge_chain",),
                                "git diff --check base..landing_tree and per chain step"))
    registry.register(CheckSpec("whitespace_only", PHASE_OBJECTS, _stub("whitespace_only"), OWNER, ("merge_chain",),
                                "M13 evidence: --ignore-space-at-eol --ignore-blank-lines empty, no add/rename/mode/binary"))
    registry.register(CheckSpec("docs_transaction", PHASE_OBJECTS, _stub("docs_transaction"), OWNER, ("merge_chain",),
                                "blob OIDs of the four required docs as of the final planned tip"))
    # Worktree phase: the four audits from the worktree interpreter, then static YAML/ps1 checks.
    for check_id, text in (
        ("agent_docs_audit", "-m weather.operations.agent_docs_audit --repo-root <wt>"),
        ("correspondence_index", "-m weather.reporting.roadmap.correspondence_index --check"),
        ("roadmap_backlog", "-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check"),
        ("schema_registry", "-m weather.schema_registry audit; schema_additive when schema_registry* changed"),
        ("shard_coverage", "windows-qualification.yml shard files exist; spawning tests sharded"),
        ("ps1_param_defaults", "advanced scripts with $PSScriptRoot in param() (WARN pre-#222)"),
    ):
        registry.register(CheckSpec(check_id, PHASE_WORKTREE, _stub(check_id), OWNER, ("import_probe",), text))
