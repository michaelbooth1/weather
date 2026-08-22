"""Prepare one no-argument launcher for a reviewed fixed live-session manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from weather.operations.international_live_session_runner import (
    SESSION_SCHEMA_VERSION,
)
from weather.operations.international_live_wrapper_sealer import (
    _canonical_json,
    _default_powershell_parser,
    _write_new,
)
from weather.operations.live_path_security import (
    validate_nonreparse_directory,
    validate_private_attempt_root,
    validate_regular_nonreparse_file,
)
from weather.paths import REPO_ROOT


TEMPLATE_PATH = (
    REPO_ROOT
    / "scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl"
)
RUNNER_SOURCE = REPO_ROOT / "src/weather/operations/international_live_session_runner.py"


class SessionLauncherSealError(RuntimeError):
    """Raised when a reviewed fixed-session launcher cannot be prepared."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _replace(source: str, marker: str, value: str) -> str:
    quoted = f'"{marker}"'
    if source.count(quoted) != 1:
        raise SessionLauncherSealError(f"launcher marker is not unique: {marker}")
    return source.replace(quoted, _ps(value), 1)


def prepare_fixed_session_launcher(
    session_manifest_path: str | Path,
    expected_session_manifest_sha256: str,
    *,
    repo_root: str | Path = REPO_ROOT,
    template_path: str | Path = TEMPLATE_PATH,
    powershell_parser=_default_powershell_parser,
    attempt_root_validator=validate_private_attempt_root,
) -> dict:
    """Write the canonical no-argument launcher, review receipt, and sidecar."""

    manifest_path = validate_regular_nonreparse_file(session_manifest_path)
    root = validate_nonreparse_directory(repo_root)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionLauncherSealError("session manifest is unreadable") from exc
    observed_hash = hashlib.sha256(raw).hexdigest()
    if observed_hash != str(expected_session_manifest_sha256).lower():
        raise SessionLauncherSealError("reviewed session manifest hash changed")
    sidecar = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    validate_regular_nonreparse_file(sidecar)
    if sidecar.read_text(encoding="ascii") != f"{observed_hash}  {manifest_path.name}\n":
        raise SessionLauncherSealError("session manifest sidecar changed")
    if manifest.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise SessionLauncherSealError("session manifest schema is unsupported")
    stage = str(manifest.get("stage") or "")
    scope = manifest.get("scope") or {}
    raw_attempt_root = Path(str(scope.get("attempt_root") or ""))
    if attempt_root_validator(raw_attempt_root).get("status") != "PASS":
        raise SessionLauncherSealError("attempt root security validation did not pass")
    attempt_root = validate_nonreparse_directory(raw_attempt_root)
    if manifest_path != (
        attempt_root / "inputs" / f"{stage}-session-manifest.json"
    ).resolve():
        raise SessionLauncherSealError("session manifest path is not canonical")
    production = manifest.get("production") or {}
    if Path(str(production.get("root") or "")).resolve() != root:
        raise SessionLauncherSealError("launcher repository differs from reviewed production")
    python = validate_regular_nonreparse_file(str(production.get("python") or ""))
    if python != (root / "venv/Scripts/python.exe").resolve() or not python.is_file():
        raise SessionLauncherSealError("reviewed production interpreter is unavailable")
    candidate = attempt_root / "incoming" / f"fresh-{stage}-candidate.json"
    if candidate.exists():
        raise SessionLauncherSealError("fixed candidate inbox must be new at review time")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    launcher = attempt_root / "session" / f"{stage}-launch.ps1"
    receipt_path = attempt_root / "session" / f"{stage}-launcher-review.json"
    receipt_sidecar = receipt_path.with_suffix(receipt_path.suffix + ".sha256")
    if any(path.exists() for path in (launcher, receipt_path, receipt_sidecar)):
        raise SessionLauncherSealError("fixed session launcher namespace is spent")
    template = validate_regular_nonreparse_file(template_path)
    runner_source = root / RUNNER_SOURCE.relative_to(REPO_ROOT)
    validate_regular_nonreparse_file(runner_source)
    rendered = template.read_text(encoding="utf-8")
    replacements = {
        "__SESSION_REPO_ROOT__": str(root),
        "__SESSION_PYTHON__": str(python),
        "__SESSION_PYTHON_SHA256__": _sha(python),
        "__SESSION_RUNNER_SOURCE__": str(runner_source),
        "__SESSION_RUNNER_SHA256__": _sha(runner_source),
        "__SESSION_MANIFEST__": str(manifest_path),
        "__SESSION_MANIFEST_SHA256__": observed_hash,
        "__SESSION_MANIFEST_SIDECAR__": str(sidecar),
        "__SESSION_MANIFEST_SIDECAR_SHA256__": _sha(sidecar),
        "__SESSION_CANDIDATE_INBOX__": str(candidate.resolve()),
    }
    for marker, value in replacements.items():
        rendered = _replace(rendered, marker, value)
    powershell_parser(rendered)
    launcher_raw = rendered.encode("utf-8-sig")
    receipt = {
        "schema_version": "international_live_session_launcher_review_v0.1",
        "status": "PASS",
        "stage": stage,
        "session_manifest": {
            "path": str(manifest_path),
            "sha256": observed_hash,
            "sidecar_path": str(sidecar),
            "sidecar_sha256": _sha(sidecar),
        },
        "candidate_inbox": str(candidate.resolve()),
        "launcher": {
            "path": str(launcher.resolve()),
            "sha256": hashlib.sha256(launcher_raw).hexdigest(),
            "bytes": len(launcher_raw),
        },
        "runner_source": {"path": str(runner_source), "sha256": _sha(runner_source)},
        "launcher_template": {"path": str(template), "sha256": _sha(template)},
        "production_python": {"path": str(python), "sha256": _sha(python)},
        "no_argument_surface": True,
        "live_mutation_attempted": False,
        "credential_values_read_in_memory": False,
    }
    receipt_raw = _canonical_json(receipt)
    _write_new(launcher, launcher_raw)
    _write_new(receipt_path, receipt_raw)
    _write_new(
        receipt_sidecar,
        f"{hashlib.sha256(receipt_raw).hexdigest()}  {receipt_path.name}\n".encode(
            "ascii"
        ),
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-manifest", required=True)
    parser.add_argument("--expected-session-manifest-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = prepare_fixed_session_launcher(
            args.session_manifest,
            args.expected_session_manifest_sha256,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCK", "exception_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
