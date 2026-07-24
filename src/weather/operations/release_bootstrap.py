"""Fail-closed construction contract for the first inactive production release.

This module breaks the initial release-identity deadlock without creating a
serving exception.  It authorizes only one offline action: copying an exactly
qualified production candidate into an immutable, inactive release directory.
It never writes an active pointer, promotes a release, or supplies a runtime
fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    ReleaseLifecycleError,
    canonical_payload_sha256,
    verify_release,
)
from weather.operations.release_promotion import DEFAULT_ACTIVE_POINTER
from weather.release_artifacts import (
    assert_no_link_or_reparse_ancestors,
    is_link_or_reparse_point,
    lexical_absolute_path,
)
from weather.release_contract import PRODUCTION_CANDIDATE_MODE
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("first_inactive_release_bootstrap")
CONTRACT_NAME = "first_inactive_release_bootstrap"
POLICY = "FIRST_INACTIVE_PRODUCTION_RELEASE_ONLY"
PARITY_DISPOSITION = "DEFERRED_UNTIL_EXACT_INACTIVE_RELEASE_EXISTS"


def _utc_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _release_store_inventory(releases_root: Path) -> tuple[str, list[dict[str, str]]]:
    try:
        assert_no_link_or_reparse_ancestors(
            releases_root,
            label="first-inactive release store",
        )
    except ReleaseLifecycleError:
        return "LINK_OR_REPARSE", []
    if not releases_root.exists():
        return "ABSENT", []
    if not releases_root.is_dir():
        return "INVALID", []
    rows = []
    for path in sorted(releases_root.iterdir(), key=lambda value: value.name):
        rows.append(
            {
                "name": path.name,
                "kind": (
                    "link_or_reparse"
                    if is_link_or_reparse_point(path)
                    else "directory"
                    if path.is_dir()
                    else "file"
                    if path.is_file()
                    else "other"
                ),
            }
        )
    return "EMPTY" if not rows else "POPULATED", rows


def _pointer_state(pointer_path: Path) -> str:
    try:
        assert_no_link_or_reparse_ancestors(
            pointer_path,
            label="first-inactive active pointer",
        )
    except ReleaseLifecycleError:
        return "LINK_OR_REPARSE"
    if not pointer_path.exists():
        return "ABSENT"
    if pointer_path.is_file():
        return "PRESENT"
    return "INVALID"


def _with_hash(payload: dict[str, Any]) -> dict[str, Any]:
    payload["contract_sha256"] = canonical_payload_sha256(
        payload,
        omit=("contract_sha256",),
    )
    return payload


def evaluate_first_inactive_release_bootstrap(
    args: Any,
    *,
    release_identity: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the explicit pre-release exception without changing state."""

    requested = bool(getattr(args, "bootstrap_first_inactive_release", False))
    releases_input = lexical_absolute_path(
        getattr(args, "releases_root", "") or DEFAULT_RELEASES_ROOT
    )
    releases_root = releases_input
    pointer_value = getattr(args, "release_pointer", "")
    pointer_input = lexical_absolute_path(
        pointer_value
        if pointer_value
        else releases_root / DEFAULT_ACTIVE_POINTER.name
    )
    pointer_path = pointer_input
    store_state, entries = _release_store_inventory(releases_input)
    pointer_state = _pointer_state(pointer_input)
    candidate_mode = str(getattr(args, "release_candidate_mode", "") or "")
    parity_served = [
        str(path)
        for path in (getattr(args, "captured_input_parity_served", []) or [])
        if str(path or "").strip()
    ]
    parity_replay = [
        str(path)
        for path in (getattr(args, "captured_input_parity_replay", []) or [])
        if str(path or "").strip()
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_NAME,
        "evaluated_at_utc": _utc_iso(now),
        "requested": requested,
        "status": "DISABLED",
        "policy": POLICY,
        "scope": "INACTIVE_IDENTITY_ONLY",
        "candidate_mode": candidate_mode,
        "build_candidate_release": bool(
            getattr(args, "build_candidate_release", False)
        ),
        "active_pointer": {
            "path": str(pointer_path),
            "state": pointer_state,
        },
        "release_store": {
            "path": str(releases_root),
            "state": store_state,
            "entries": entries,
        },
        "observed_serving_identity_status": str(
            (release_identity or {}).get("status") or ""
        ),
        "pre_release_parity": {
            "ordinary_requirement_waived": False,
            "disposition": "REQUIRED",
            "generic_skip_flag": bool(
                getattr(args, "skip_captured_input_replay_parity", False)
            ),
            "served_input_count": len(parity_served),
            "replay_input_count": len(parity_replay),
        },
        "prohibited_actions": [
            "ACTIVE_POINTER_WRITE",
            "PROMOTION",
            "SERVING",
            "LIVE_FALLBACK",
        ],
        "blockers": [],
    }
    if not requested:
        return _with_hash(payload)

    blockers: list[dict[str, str]] = []
    if candidate_mode != PRODUCTION_CANDIDATE_MODE:
        blockers.append(
            {
                "code": "production_candidate_mode_required",
                "detail": "first inactive bootstrap requires exact production qualification",
            }
        )
    if not bool(getattr(args, "build_candidate_release", False)):
        blockers.append(
            {
                "code": "candidate_release_build_required",
                "detail": "bootstrap cannot run when immutable release construction is disabled",
            }
        )
    if Path(pointer_path).parent != releases_root:
        blockers.append(
            {
                "code": "active_pointer_outside_release_store",
                "detail": "active pointer must be directly inside the declared releases root",
            }
        )
    if pointer_state != "ABSENT":
        blockers.append(
            {
                "code": (
                    "active_pointer_link_or_reparse"
                    if pointer_state == "LINK_OR_REPARSE"
                    else "active_pointer_not_absent"
                ),
                "detail": f"active pointer state is {pointer_state}",
            }
        )
    if store_state not in {"ABSENT", "EMPTY"}:
        blockers.append(
            {
                "code": (
                    "release_store_link_or_reparse"
                    if store_state == "LINK_OR_REPARSE"
                    else "release_store_not_empty"
                ),
                "detail": f"release store state is {store_state}",
            }
        )
    if (release_identity or {}).get("status") == "PASS":
        blockers.append(
            {
                "code": "serving_identity_already_exists",
                "detail": "a verified serving identity cannot use first-release bootstrap",
            }
        )
    if str(getattr(args, "release_parent", "") or "").strip():
        blockers.append(
            {
                "code": "release_parent_forbidden",
                "detail": "the first inactive release cannot declare a parent",
            }
        )
    if bool(getattr(args, "skip_captured_input_replay_parity", False)):
        blockers.append(
            {
                "code": "generic_parity_skip_forbidden",
                "detail": "use only the bounded first-inactive bootstrap contract",
            }
        )
    if parity_served or parity_replay:
        blockers.append(
            {
                "code": "preexisting_parity_inputs_forbidden",
                "detail": "supplied parity evidence must be verified normally, not bypassed",
            }
        )

    payload["blockers"] = blockers
    payload["status"] = "PASS" if not blockers else "BLOCK"
    if not blockers:
        payload["pre_release_parity"] = {
            **payload["pre_release_parity"],
            "ordinary_requirement_waived": True,
            "disposition": PARITY_DISPOSITION,
        }
    return _with_hash(payload)


def validate_first_inactive_release_bootstrap(
    contract: Mapping[str, Any],
    *,
    args: Any | None = None,
) -> dict[str, Any]:
    """Authenticate a PASS contract before binding it into a release."""

    payload = dict(contract)
    expected_hash = canonical_payload_sha256(
        payload,
        omit=("contract_sha256",),
    )
    failures = []
    expected = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_NAME,
        "status": "PASS",
        "requested": True,
        "policy": POLICY,
        "scope": "INACTIVE_IDENTITY_ONLY",
        "candidate_mode": PRODUCTION_CANDIDATE_MODE,
        "build_candidate_release": True,
        "contract_sha256": expected_hash,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            failures.append(f"{field} must be {value!r}")
    if payload.get("blockers") != []:
        failures.append("blockers must be empty")
    try:
        evaluated_at = datetime.fromisoformat(
            str(payload.get("evaluated_at_utc") or "").replace("Z", "+00:00")
        )
        if evaluated_at.tzinfo is None:
            raise ValueError("timezone is missing")
    except ValueError:
        failures.append("evaluated_at_utc must be timezone-aware ISO-8601")
    if payload.get("observed_serving_identity_status") == "PASS":
        failures.append("verified serving identity was already present")
    if (payload.get("active_pointer") or {}).get("state") != "ABSENT":
        failures.append("active pointer was not attested absent")
    if (payload.get("release_store") or {}).get("state") not in {
        "ABSENT",
        "EMPTY",
    }:
        failures.append("release store was not attested empty")
    if (payload.get("release_store") or {}).get("entries") != []:
        failures.append("release store inventory was not empty")
    parity = payload.get("pre_release_parity") or {}
    if (
        parity.get("ordinary_requirement_waived") is not True
        or parity.get("disposition") != PARITY_DISPOSITION
        or parity.get("generic_skip_flag") is not False
        or parity.get("served_input_count") != 0
        or parity.get("replay_input_count") != 0
    ):
        failures.append("pre-release parity disposition is invalid")
    if sorted(payload.get("prohibited_actions") or []) != sorted(
        ["ACTIVE_POINTER_WRITE", "PROMOTION", "SERVING", "LIVE_FALLBACK"]
    ):
        failures.append("prohibited action inventory is invalid")
    if args is not None:
        releases_root = lexical_absolute_path(getattr(args, "releases_root"))
        pointer_path = lexical_absolute_path(getattr(args, "release_pointer"))
        try:
            assert_no_link_or_reparse_ancestors(
                releases_root,
                label="first-inactive release store",
            )
        except ReleaseLifecycleError as exc:
            failures.append(str(exc))
        try:
            assert_no_link_or_reparse_ancestors(
                pointer_path,
                label="first-inactive active pointer",
            )
        except ReleaseLifecycleError as exc:
            failures.append(str(exc))
        if (payload.get("release_store") or {}).get("path") != str(releases_root):
            failures.append("release store path no longer matches the invocation")
        if (payload.get("active_pointer") or {}).get("path") != str(pointer_path):
            failures.append("active pointer path no longer matches the invocation")
    if failures:
        raise ReleaseLifecycleError(
            "first inactive release bootstrap contract failed closed: "
            + "; ".join(failures)
        )
    return payload


def bootstrap_release_lineage(
    contract: Mapping[str, Any],
    *,
    args: Any,
    parent_release: str | None,
) -> dict[str, Any]:
    """Return the immutable subset bound into the release manifest."""

    validated = validate_first_inactive_release_bootstrap(contract, args=args)
    if parent_release is not None:
        raise ReleaseLifecycleError(
            "first inactive release bootstrap cannot bind a parent release"
        )
    pointer_input = lexical_absolute_path(getattr(args, "release_pointer"))
    if _pointer_state(pointer_input) != "ABSENT":
        raise ReleaseLifecycleError(
            "active pointer appeared after first inactive bootstrap preflight"
        )
    store_state, entries = _release_store_inventory(
        lexical_absolute_path(getattr(args, "releases_root"))
    )
    if store_state not in {"ABSENT", "EMPTY"} or entries:
        raise ReleaseLifecycleError(
            "release store changed after first inactive bootstrap preflight"
        )
    return _bootstrap_release_lineage_payload(validated)


def _bootstrap_release_lineage_payload(
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": validated["schema_version"],
        "contract": validated["contract"],
        "contract_sha256": validated["contract_sha256"],
        "policy": validated["policy"],
        "scope": validated["scope"],
        "pre_release_parity_disposition": validated["pre_release_parity"][
            "disposition"
        ],
        "active_pointer_state_before": "ABSENT",
        "release_store_state_before": validated["release_store"]["state"],
        "prohibited_actions": list(validated["prohibited_actions"]),
    }


def validate_first_inactive_release_route(
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Require the bootstrap's candidate route to remain wholly shadow-only."""

    failures = []
    if not isinstance(route, Mapping):
        failures.append("release route is missing or invalid")
        route = {}
    if route.get("promotion_verdict") != "shadow":
        failures.append("release route verdict is not shadow")
    if (
        route.get("promotion_eligibility")
        != "BLOCKED_NON_AUTHORIZING_EVIDENCE"
    ):
        failures.append(
            "release route is not blocked from promotion eligibility"
        )
    route_authorization = route.get("promotion_authorization")
    if (
        not isinstance(route_authorization, Mapping)
        or route_authorization.get("status")
        != "BLOCKED_NON_AUTHORIZING_EVIDENCE"
    ):
        failures.append("release route authorization is not explicitly blocked")
    route_markets = route.get("markets")
    if not isinstance(route_markets, Mapping) or not route_markets:
        failures.append("release route has no shadow markets")
        route_markets = {}
    invalid_route_markets = sorted(
        str(market_id)
        for market_id, row in route_markets.items()
        if (
            not isinstance(row, Mapping)
            or row.get("decision") != "shadow"
            or row.get("counts_toward_promotion") is not False
            or row.get("serving_release") is not None
        )
    )
    if invalid_route_markets:
        failures.append(
            "release route contains serving or promotion-capable markets: "
            + ", ".join(invalid_route_markets)
        )
    if failures:
        raise ReleaseLifecycleError(
            "first inactive release route failed closed: "
            + "; ".join(failures)
        )
    return dict(route)


def verify_first_inactive_release(
    contract: Mapping[str, Any],
    *,
    args: Any,
    release_result: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reverify the frozen release and prove that it remains inactive."""

    validated = validate_first_inactive_release_bootstrap(contract, args=args)
    if release_result.get("status") != "CREATED":
        raise ReleaseLifecycleError(
            "first inactive release was not created successfully"
        )
    releases_root = lexical_absolute_path(getattr(args, "releases_root"))
    assert_no_link_or_reparse_ancestors(
        releases_root,
        label="first-inactive release store",
    )
    pointer_input = lexical_absolute_path(getattr(args, "release_pointer"))
    if _pointer_state(pointer_input) != "ABSENT":
        raise ReleaseLifecycleError(
            "active pointer appeared during first inactive release construction"
        )
    release_id = str(release_result.get("release_id") or "")
    manifest_sha = str(
        release_result.get("manifest_sha256")
        or release_result.get("release_manifest_sha256")
        or ""
    )
    verified = verify_release(
        releases_root / release_id,
        repo_root=getattr(args, "repo_root"),
        expected_manifest_sha256=manifest_sha,
        check_runtime=False,
    )
    manifest = verified["manifest"]
    semantic = verified.get("semantic_contract") or {}
    route = manifest.get("route")
    expected_lineage = _bootstrap_release_lineage_payload(validated)
    failures = []
    if manifest.get("state") != "IMMUTABLE_CANDIDATE":
        failures.append("release state is not IMMUTABLE_CANDIDATE")
    if manifest.get("parent_release") is not None:
        failures.append("first inactive release has a parent")
    if manifest.get("rollback_target") is not None:
        failures.append("first inactive release has a rollback target")
    if semantic.get("candidate_mode") != PRODUCTION_CANDIDATE_MODE:
        failures.append("release semantic contract is not production mode")
    if semantic.get("production_capable") is not True:
        failures.append("release did not pass production qualification")
    try:
        validate_first_inactive_release_route(route)
    except ReleaseLifecycleError as exc:
        failures.append(str(exc))
    if (manifest.get("lineage") or {}).get(
        "first_inactive_release_bootstrap"
    ) != expected_lineage:
        failures.append("release manifest does not bind the bootstrap contract")
    store_state, entries = _release_store_inventory(
        lexical_absolute_path(getattr(args, "releases_root"))
    )
    if store_state != "POPULATED" or entries != [
        {"name": release_id, "kind": "directory"}
    ]:
        failures.append("release store changed outside the one authorized release")
    if failures:
        raise ReleaseLifecycleError(
            "first inactive release post-freeze verification failed: "
            + "; ".join(failures)
        )
    qualification = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT_NAME,
        "verified_at_utc": _utc_iso(now),
        "status": "PASS",
        "scope": "INACTIVE_IDENTITY_ONLY",
        "release_id": verified["release_id"],
        "manifest_path": verified["manifest_path"],
        "manifest_sha256": verified["manifest_sha256"],
        "file_count": verified["file_count"],
        "candidate_mode": semantic["candidate_mode"],
        "production_capable": True,
        "immutable_integrity_verified": True,
        "semantic_contract_verified": verified["semantic_contract_verified"],
        "active_pointer_state_after": "ABSENT",
        "active_pointer_unchanged": True,
        "activation": "NONE",
        "promotion_authorized": False,
        "serving_authorized": False,
        "live_fallback_authorized": False,
        "next_required_evidence": [
            "EXACT_RELEASE_BOUND_CAPTURED_INPUT_PARITY",
            "FORWARD_SHADOW_QUALIFICATION",
            "SEPARATE_REVIEWED_PROMOTION_DECISION",
        ],
        "bootstrap_contract_sha256": validated["contract_sha256"],
    }
    qualification["qualification_sha256"] = canonical_payload_sha256(
        qualification,
        omit=("qualification_sha256",),
    )
    return qualification


def assert_bootstrap_release_remains_inactive(
    contract: Mapping[str, Any],
    *,
    args: Any,
) -> None:
    """Final whole-run guard against concurrent or accidental activation."""

    validate_first_inactive_release_bootstrap(contract, args=args)
    pointer_input = lexical_absolute_path(getattr(args, "release_pointer"))
    if _pointer_state(pointer_input) != "ABSENT":
        raise ReleaseLifecycleError(
            "first inactive release bootstrap ended with an active pointer"
        )
