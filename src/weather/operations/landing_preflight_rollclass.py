"""Landing preflight roll-class prediction owned by L-P4 (NON-BINDING; the host's roll_verdict binds).

``roll_class``: closure snapshot (``ctx.options.closure_snapshot``, hash + date)
union a static import graph from the loop entry modules (execution-tape capture
included by default); ``schema_registry*`` always sensitive; F9 UNDECIDABLE rule;
``binding: false`` on every row.  ``landing_path`` derives the landing route.
Both are INFO/WARN and never block.  Stubs return ERROR (fail closed) until implemented.
"""

from __future__ import annotations

from weather.operations.landing_preflight import (
    ERROR,
    PHASE_OBJECTS,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
)

OWNER = "L-P4"


def _roll_class(ctx: PreflightContext) -> CheckResult:
    return CheckResult(ERROR, f"stub: roll_class not implemented yet ({OWNER})", evidence={"binding": False})


def _landing_path(ctx: PreflightContext) -> CheckResult:
    return CheckResult(ERROR, f"stub: landing_path not implemented yet ({OWNER})")


def register_checks(registry: CheckRegistry) -> None:
    registry.register(CheckSpec("roll_class", PHASE_OBJECTS, _roll_class, OWNER, ("merge_chain",),
                                "expected roll class from snapshot union static graph; binding false"))
    registry.register(CheckSpec("landing_path", PHASE_OBJECTS, _landing_path, OWNER, ("roll_class",),
                                "DOCS_LIGHT / ROLL_FREE_GUARDED / ROLL_SENSITIVE / UNDECIDABLE -> RS"))
