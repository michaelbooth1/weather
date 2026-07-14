"""Command-line interface for immutable release lifecycle operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    ReleaseLifecycleError,
    create_release,
    verify_release,
)
from weather.release_artifacts import strict_json_loads
from weather.operations.release_promotion import (
    DEFAULT_ACTIVE_POINTER,
    DEFAULT_CANDIDATES_ROOT,
    DEFAULT_ROLLBACK_DRILL,
    assert_candidate_only_output,
    promote_release,
    resolve_active_release,
    rollback_release,
)
from weather.paths import REPO_ROOT


CREATE_SPEC_KEYS = {
    "release_id",
    "artifacts",
    "route",
    "expected_live_runtimes",
    "parent_release",
    "rollback_target",
    "lineage",
}


def _read_object(path: str | Path, *, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseLifecycleError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseLifecycleError(f"{label} must be a JSON object: {path}")
    return payload


def _print_result(payload: dict[str, Any]) -> None:
    concise = {key: value for key, value in payload.items() if key != "manifest"}
    print(json.dumps(concise, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, verify, promote, resolve, or roll back immutable model releases."
    )
    parser.add_argument("--releases-root", type=Path, default=DEFAULT_RELEASES_ROOT)
    parser.add_argument(
        "--pointer",
        type=Path,
        default=None,
        help=f"active pointer (default: <releases-root>/{DEFAULT_ACTIVE_POINTER.name})",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="copy a candidate into a new immutable release")
    create.add_argument("--candidate", type=Path, required=True)
    create.add_argument("--spec", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="verify every release file and runtime compatibility")
    verify.add_argument("release_id")
    verify.add_argument("--integrity-only", action="store_true")

    promote = subparsers.add_parser("promote", help="atomically activate a fully verified release")
    promote.add_argument("release_id")
    promote.add_argument("--decision", type=Path, required=True)
    promote.add_argument("--market-day-boundary", type=Path, required=True)
    promote.add_argument(
        "--bootstrap-first-release",
        action="store_true",
        help=(
            "allow one reviewed research-only serving-identity release only when "
            "no active pointer exists"
        ),
    )

    rollback = subparsers.add_parser("rollback", help="atomically return to the prior verified release")
    rollback.add_argument("--market-day-boundary", type=Path, required=True)
    rollback.add_argument(
        "--drill-record",
        type=Path,
        default=DEFAULT_ROLLBACK_DRILL,
        help="atomic rollback drill record output (default: data/backtest/release_rollback_drill.json)",
    )

    subparsers.add_parser("active", help="resolve the active release after complete verification")

    guard = subparsers.add_parser("guard-candidate", help="fail unless an output is candidate-only")
    guard.add_argument("output", type=Path)
    guard.add_argument("--candidates-root", type=Path, default=None)
    return parser


def _create(args: argparse.Namespace) -> dict[str, Any]:
    spec = _read_object(args.spec, label="release create spec")
    unknown = sorted(set(spec) - CREATE_SPEC_KEYS)
    if unknown:
        raise ReleaseLifecycleError(f"release create spec contains unknown fields: {unknown}")
    required = {"release_id", "artifacts", "route", "expected_live_runtimes"}
    missing = sorted(required - set(spec))
    if missing:
        raise ReleaseLifecycleError(f"release create spec is missing required fields: {missing}")
    if not isinstance(spec["artifacts"], list):
        raise ReleaseLifecycleError("release create spec artifacts must be a list")
    return create_release(
        release_id=spec["release_id"],
        candidate_dir=args.candidate,
        declarations=spec["artifacts"],
        route=spec["route"],
        expected_live_runtimes=spec["expected_live_runtimes"],
        releases_root=args.releases_root,
        repo_root=args.repo_root,
        parent_release=spec.get("parent_release"),
        rollback_target=spec.get("rollback_target"),
        lineage=spec.get("lineage"),
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    pointer = args.pointer or (Path(args.releases_root) / DEFAULT_ACTIVE_POINTER.name)
    if args.command == "create":
        return _create(args)
    if args.command == "verify":
        return verify_release(
            Path(args.releases_root) / args.release_id,
            repo_root=args.repo_root,
            check_runtime=not args.integrity_only,
        )
    if args.command == "promote":
        return promote_release(
            args.release_id,
            decision=_read_object(args.decision, label="promotion decision"),
            market_day_boundary=_read_object(args.market_day_boundary, label="market-day boundary proof"),
            releases_root=args.releases_root,
            pointer_path=pointer,
            repo_root=args.repo_root,
            bootstrap_first_release=args.bootstrap_first_release,
        )
    if args.command == "rollback":
        return rollback_release(
            market_day_boundary=_read_object(args.market_day_boundary, label="market-day boundary proof"),
            releases_root=args.releases_root,
            pointer_path=pointer,
            drill_record_path=args.drill_record,
        )
    if args.command == "active":
        return resolve_active_release(
            releases_root=args.releases_root,
            pointer_path=pointer,
            repo_root=args.repo_root,
        )
    if args.command == "guard-candidate":
        output = assert_candidate_only_output(
            args.output,
            candidates_root=args.candidates_root
            or (Path(args.releases_root).parent / DEFAULT_CANDIDATES_ROOT.name),
            releases_root=args.releases_root,
            active_pointer=pointer,
        )
        return {"status": "PASS", "candidate_output": str(output)}
    raise ReleaseLifecycleError(f"unsupported release lifecycle command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except ReleaseLifecycleError as exc:
        print(json.dumps({"status": "BLOCK", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
