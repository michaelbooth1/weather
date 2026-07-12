"""Dependency-safe executable experiment manifest and terminal result contract."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from weather.schema_registry import schema_version
from weather.schema_registry_data import SCHEMAS_BY_VERSION


MANIFEST_SCHEMA_VERSION = schema_version("executable_experiment_manifest")
RESULT_SCHEMA_VERSION = schema_version("executable_experiment_result")
QUEUE_SCHEMA_VERSION = schema_version("automatic_experiment_queue")
RELEASE_MANIFEST_SCHEMA_VERSION = schema_version("release_manifest")
TERMINAL_DISPOSITIONS = frozenset(
    {"resolved", "rejected", "regressed", "inconclusive", "superseded"}
)
INDEPENDENT_SAMPLE_UNITS = frozenset({"fleet_target_date", "market_day"})
OPERATORS = frozenset({"<", "<=", ">", ">="})
DIRECTIONS = frozenset({"minimize", "maximize"})
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PYTHON_EXECUTABLE_RE = re.compile(r"^python(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?$")
WEATHER_MODULE_RE = re.compile(
    r"^weather(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
)


class ExperimentContractError(ValueError):
    """An experiment manifest or result is incomplete, unsafe, or inconsistent."""


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def payload_sha256(payload: Mapping[str, Any], *, hash_field: str) -> str:
    unhashed = {key: value for key, value in payload.items() if key != hash_field}
    return hashlib.sha256(canonical_json(unhashed).encode("utf-8")).hexdigest()


def finalize_self_hash(payload: Mapping[str, Any], *, hash_field: str) -> dict[str, Any]:
    finalized = json.loads(canonical_json(payload))
    finalized.pop(hash_field, None)
    finalized[hash_field] = payload_sha256(finalized, hash_field=hash_field)
    return finalized


def verify_self_hash(payload: Mapping[str, Any], *, hash_field: str) -> None:
    actual = str(payload.get(hash_field) or "")
    if not HASH_RE.fullmatch(actual) or actual != payload_sha256(
        payload, hash_field=hash_field
    ):
        raise ExperimentContractError(f"{hash_field} is missing or invalid")


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExperimentContractError(f"{field} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ExperimentContractError(f"{field} contains an unsafe control character")
    return text


def _finite_number(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ExperimentContractError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentContractError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ExperimentContractError(f"{field} must be finite")
    if positive and number <= 0:
        raise ExperimentContractError(f"{field} must be positive")
    if nonnegative and number < 0:
        raise ExperimentContractError(f"{field} must be nonnegative")
    return number


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ExperimentContractError(f"{field} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentContractError(f"{field} must be a positive integer") from exc
    if number <= 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise ExperimentContractError(f"{field} must be a positive integer")
    return number


def _timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ExperimentContractError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ExperimentContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _relative_path(value: Any, field: str) -> str:
    text = _required_text(value, field).replace("\\", "/")
    path = PurePosixPath(text)
    if text.startswith("/") or WINDOWS_DRIVE_RE.match(text) or ".." in path.parts or "." in path.parts:
        raise ExperimentContractError(f"{field} must be a normalized repository-relative path")
    return path.as_posix()


def _under_root(path: str, root: str) -> bool:
    path_parts = PurePosixPath(path).parts
    root_parts = PurePosixPath(root).parts
    return len(path_parts) > len(root_parts) and path_parts[: len(root_parts)] == root_parts


def _registered_schema(value: Any, field: str) -> str:
    version = _required_text(value, field)
    if version not in SCHEMAS_BY_VERSION:
        raise ExperimentContractError(f"{field} is not registered: {version}")
    return version


def _hash(value: Any, field: str) -> str:
    digest = _required_text(value, field)
    if not HASH_RE.fullmatch(digest):
        raise ExperimentContractError(f"{field} must be a lowercase SHA-256")
    return digest


def _safe_identifier(value: Any, field: str) -> str:
    text = _required_text(value, field)
    if text in {".", ".."} or not SAFE_IDENTIFIER_RE.fullmatch(text):
        raise ExperimentContractError(
            f"{field} must be a safe single path component"
        )
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root(value: str | Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExperimentContractError(
            f"repo_root does not resolve to an existing directory: {value}"
        ) from exc
    if not root.is_dir():
        raise ExperimentContractError("repo_root must be a directory")
    return root


def _resolve_repo_path(
    repo_root: Path,
    value: Any,
    field: str,
    *,
    must_exist: bool,
) -> tuple[str, Path, Path]:
    relative = _relative_path(value, field)
    lexical = repo_root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = lexical.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise ExperimentContractError(f"{field} does not resolve: {relative}") from exc
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ExperimentContractError(f"{field} resolves outside repo_root") from exc
    return relative, lexical, resolved


def _reject_symlink_components(path: Path, repo_root: Path, field: str) -> None:
    try:
        relative = path.relative_to(repo_root)
    except ValueError as exc:
        raise ExperimentContractError(f"{field} is outside repo_root") from exc
    current = repo_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ExperimentContractError(f"{field} contains a symlink component")


def _verify_embedded_json_schema(path: Path, expected: str, field: str) -> None:
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExperimentContractError(f"{field} is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ExperimentContractError(f"{field} JSON must be an object")
        if payload.get("schema_version") != expected:
            raise ExperimentContractError(
                f"{field} embedded schema_version does not match the manifest"
            )
        return
    if path.suffix.lower() not in {".jsonl", ".ndjson"}:
        return
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentContractError(f"{field} is not valid JSONL") from exc
    if not rows or any(
        not isinstance(row, Mapping) or row.get("schema_version") != expected
        for row in rows
    ):
        raise ExperimentContractError(
            f"{field} JSONL rows must carry the declared schema_version"
        )


def _verify_materialized_input(
    row: Mapping[str, Any],
    *,
    repo_root: Path,
    field: str,
) -> Path:
    _relative, _lexical, resolved = _resolve_repo_path(
        repo_root,
        row.get("path"),
        f"{field}.path",
        must_exist=True,
    )
    if not resolved.is_file():
        raise ExperimentContractError(f"{field}.path must resolve to a regular file")
    expected_hash = _hash(row.get("sha256"), f"{field}.sha256")
    if _sha256_file(resolved) != expected_hash:
        raise ExperimentContractError(f"{field}.sha256 does not match materialized bytes")
    expected_schema = _registered_schema(
        row.get("schema_version"), f"{field}.schema_version"
    )
    _verify_embedded_json_schema(resolved, expected_schema, field)
    return resolved


def _verify_materialized_argv(manifest: Mapping[str, Any]) -> None:
    argv = list(manifest.get("argv") or [])
    executable = PurePosixPath(str(argv[0]).replace("\\", "/")).name.lower()
    if not PYTHON_EXECUTABLE_RE.fullmatch(executable):
        raise ExperimentContractError("argv executable must be Python")
    if "-c" in argv:
        raise ExperimentContractError("argv cannot use Python -c")
    if len(argv) < 3 or argv[1] != "-m" or not WEATHER_MODULE_RE.fullmatch(
        str(argv[2])
    ):
        raise ExperimentContractError("argv must invoke an allowlisted weather.* module")
    if any(str(value).startswith("--output-root=") for value in argv):
        raise ExperimentContractError("argv must use an explicit --output-root value pair")
    output_indexes = [
        index for index, value in enumerate(argv) if value == "--output-root"
    ]
    output_root = manifest["candidate_output_root"]
    if (
        len(output_indexes) != 1
        or output_indexes[0] + 1 >= len(argv)
        or argv[output_indexes[0] + 1] != output_root
        or argv.count(output_root) != 1
    ):
        raise ExperimentContractError(
            "argv must bind exactly one explicit --output-root to candidate_output_root"
        )


def _validate_artifact_rows(
    rows: Any,
    *,
    field: str,
    path_root: str | None = None,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ExperimentContractError(f"{field} must be a non-empty list")
    by_role: dict[str, Mapping[str, Any]] = {}
    paths: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ExperimentContractError(f"{field}[{index}] must be an object")
        role = _required_text(row.get("role"), f"{field}[{index}].role")
        path = _relative_path(row.get("path"), f"{field}[{index}].path")
        _hash(row.get("sha256"), f"{field}[{index}].sha256")
        _registered_schema(row.get("schema_version"), f"{field}[{index}].schema_version")
        if role in by_role or path in paths:
            raise ExperimentContractError(f"{field} roles and paths must be unique")
        if path_root is not None and not _under_root(path, path_root):
            raise ExperimentContractError(f"{field}[{index}].path must be below candidate_output_root")
        by_role[role] = row
        paths.add(path)
    return by_role


def _validate_manifest_body(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ExperimentContractError("executable experiment manifest schema is unsupported")
    queue_id = _required_text(payload.get("queue_id"), "queue_id")
    candidate_id = _safe_identifier(payload.get("candidate_id"), "candidate_id")
    _required_text(payload.get("owner"), "owner")
    _required_text(payload.get("hypothesis"), "hypothesis")
    _timestamp(payload.get("created_at_utc"), "created_at_utc")
    dispositions = payload.get("terminal_dispositions")
    if (
        not isinstance(dispositions, list)
        or len(dispositions) != len(TERMINAL_DISPOSITIONS)
        or not all(isinstance(value, str) for value in dispositions)
        or set(dispositions) != TERMINAL_DISPOSITIONS
    ):
        raise ExperimentContractError(
            "terminal_dispositions must declare the complete terminal taxonomy exactly once"
        )
    if payload.get("terminal_dispositions") != sorted(TERMINAL_DISPOSITIONS):
        raise ExperimentContractError(
            "terminal_dispositions must declare the complete canonical taxonomy"
        )

    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ExperimentContractError("argv must be a non-empty JSON array, never a shell string")
    normalized_argv = [_required_text(value, f"argv[{index}]") for index, value in enumerate(argv)]
    executable = PurePosixPath(normalized_argv[0].replace("\\", "/")).name.lower()
    if executable in SHELL_EXECUTABLES:
        raise ExperimentContractError("argv cannot invoke a command shell")

    output_root = _relative_path(payload.get("candidate_output_root"), "candidate_output_root")
    required_prefix = f"artifacts/candidates/{candidate_id}/experiments"
    if not _under_root(output_root, required_prefix):
        raise ExperimentContractError(
            "candidate_output_root must be isolated below artifacts/candidates/<candidate_id>/experiments"
        )
    if normalized_argv.count(output_root) != 1:
        raise ExperimentContractError("argv must contain candidate_output_root exactly once")

    release = payload.get("release")
    if not isinstance(release, Mapping):
        raise ExperimentContractError("release binding is required")
    _safe_identifier(release.get("release_id"), "release.release_id")
    _hash(release.get("manifest_sha256"), "release.manifest_sha256")
    corpus = payload.get("corpus")
    if not isinstance(corpus, Mapping):
        raise ExperimentContractError("corpus binding is required")
    _relative_path(corpus.get("path"), "corpus.path")
    _hash(corpus.get("sha256"), "corpus.sha256")
    _registered_schema(corpus.get("schema_version"), "corpus.schema_version")
    _validate_artifact_rows(payload.get("inputs"), field="inputs")

    primary = payload.get("primary_metric")
    if not isinstance(primary, Mapping):
        raise ExperimentContractError("primary_metric is required")
    primary_name = _required_text(primary.get("name"), "primary_metric.name")
    if primary.get("direction") not in DIRECTIONS:
        raise ExperimentContractError("primary_metric.direction must be minimize or maximize")
    _required_text(primary.get("aggregation"), "primary_metric.aggregation")

    protected = payload.get("protected_metrics")
    if not isinstance(protected, list) or not protected:
        raise ExperimentContractError("protected_metrics must be a non-empty list")
    protected_names: set[str] = set()
    for index, metric in enumerate(protected):
        if not isinstance(metric, Mapping):
            raise ExperimentContractError(f"protected_metrics[{index}] must be an object")
        name = _required_text(metric.get("name"), f"protected_metrics[{index}].name")
        if name == primary_name or name in protected_names:
            raise ExperimentContractError("metric names must be unique")
        if metric.get("operator") not in OPERATORS:
            raise ExperimentContractError(f"protected_metrics[{index}].operator is unsupported")
        _finite_number(metric.get("threshold"), f"protected_metrics[{index}].threshold")
        protected_names.add(name)

    sample = payload.get("minimum_independent_sample")
    if not isinstance(sample, Mapping):
        raise ExperimentContractError("minimum_independent_sample is required")
    if sample.get("unit") not in INDEPENDENT_SAMPLE_UNITS:
        raise ExperimentContractError("minimum_independent_sample.unit is unsupported")
    _positive_int(sample.get("count"), "minimum_independent_sample.count")

    decision = payload.get("decision_rule")
    if not isinstance(decision, Mapping):
        raise ExperimentContractError("decision_rule is required")
    _required_text(decision.get("rule"), "decision_rule.rule")
    if decision.get("metric") != primary_name:
        raise ExperimentContractError("decision_rule.metric must equal primary_metric.name")
    if decision.get("operator") not in OPERATORS:
        raise ExperimentContractError("decision_rule.operator is unsupported")
    if (
        primary.get("direction") == "minimize"
        and decision.get("operator") not in {"<", "<="}
    ) or (
        primary.get("direction") == "maximize"
        and decision.get("operator") not in {">", ">="}
    ):
        raise ExperimentContractError(
            "decision_rule.operator contradicts primary_metric.direction"
        )
    _finite_number(decision.get("threshold"), "decision_rule.threshold")

    _validate_artifact_rows(
        payload.get("expected_artifacts"),
        field="expected_artifacts",
        path_root=output_root,
    )
    budget = payload.get("resource_budget")
    if not isinstance(budget, Mapping):
        raise ExperimentContractError("resource_budget is required")
    _positive_int(budget.get("timeout_seconds"), "resource_budget.timeout_seconds")
    _finite_number(budget.get("cpu_cores"), "resource_budget.cpu_cores", positive=True)
    _positive_int(budget.get("memory_mb"), "resource_budget.memory_mb")
    _finite_number(budget.get("io_read_mb"), "resource_budget.io_read_mb", positive=True)
    _finite_number(budget.get("io_write_mb"), "resource_budget.io_write_mb", positive=True)
    if queue_id in {".", ".."}:
        raise ExperimentContractError("queue_id is invalid")


def build_experiment_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = json.loads(canonical_json(payload))
    manifest.pop("manifest_sha256", None)
    manifest.setdefault("schema_version", MANIFEST_SCHEMA_VERSION)
    _validate_manifest_body(manifest)
    return finalize_self_hash(manifest, hash_field="manifest_sha256")


def verify_experiment_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ExperimentContractError("experiment manifest must be an object")
    _validate_manifest_body(payload)
    verify_self_hash(payload, hash_field="manifest_sha256")
    return json.loads(canonical_json(payload))


def verify_materialized_experiment_manifest(
    payload: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Verify that a structural manifest is bound to current repository bytes.

    This is intentionally separate from ``verify_experiment_manifest`` so a
    reporting surface may describe a structurally complete contract without
    incorrectly claiming that it is executable.
    """

    manifest = verify_experiment_manifest(payload)
    root = _repo_root(repo_root)
    _verify_materialized_argv(manifest)

    release = manifest["release"]
    release_id = _safe_identifier(release.get("release_id"), "release.release_id")
    release_relative = f"artifacts/releases/{release_id}/release_manifest.json"
    _relative, _lexical, release_path = _resolve_repo_path(
        root,
        release_relative,
        "release.manifest_path",
        must_exist=True,
    )
    if not release_path.is_file():
        raise ExperimentContractError("release manifest must be a regular file")
    try:
        release_payload = json.loads(release_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentContractError("release manifest is not valid JSON") from exc
    if not isinstance(release_payload, Mapping):
        raise ExperimentContractError("release manifest must be a JSON object")
    if release_payload.get("schema_version") != RELEASE_MANIFEST_SCHEMA_VERSION:
        raise ExperimentContractError("release manifest schema is unsupported")
    if release_payload.get("release_id") != release_id:
        raise ExperimentContractError("release manifest path and release_id disagree")
    declared_release_hash = _hash(
        release.get("manifest_sha256"), "release.manifest_sha256"
    )
    if (
        release_payload.get("manifest_sha256") != declared_release_hash
        or payload_sha256(release_payload, hash_field="manifest_sha256")
        != declared_release_hash
    ):
        raise ExperimentContractError(
            "release.manifest_sha256 does not match the canonical release manifest"
        )

    _verify_materialized_input(
        manifest["corpus"], repo_root=root, field="corpus"
    )
    for index, row in enumerate(manifest["inputs"]):
        _verify_materialized_input(
            row,
            repo_root=root,
            field=f"inputs[{index}]",
        )

    output_root = manifest["candidate_output_root"]
    _relative, output_lexical, output_resolved = _resolve_repo_path(
        root,
        output_root,
        "candidate_output_root",
        must_exist=True,
    )
    _reject_symlink_components(output_lexical, root, "candidate_output_root")
    if not output_resolved.is_dir():
        raise ExperimentContractError("candidate_output_root must be an existing directory")
    experiments_root = root / "artifacts" / "candidates" / manifest["candidate_id"] / "experiments"
    _reject_symlink_components(
        experiments_root,
        root,
        "candidate experiments root",
    )
    try:
        experiments_resolved = experiments_root.resolve(strict=True)
        relative_output = output_resolved.relative_to(experiments_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentContractError(
            "candidate_output_root is not below the exact candidate experiments root"
        ) from exc
    if not relative_output.parts:
        raise ExperimentContractError(
            "candidate_output_root must be below the exact candidate experiments root"
        )

    for index, row in enumerate(manifest["expected_artifacts"]):
        _relative, lexical, _resolved = _resolve_repo_path(
            root,
            row.get("path"),
            f"expected_artifacts[{index}].path",
            must_exist=False,
        )
        _reject_symlink_components(
            lexical,
            root,
            f"expected_artifacts[{index}].path",
        )
        if lexical.exists() or lexical.is_symlink():
            raise ExperimentContractError(
                f"expected_artifacts[{index}].path already exists"
            )
    return manifest


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExperimentContractError(f"{field} must be a JSON string array")
    return list(value)


def _verified_terminal_item(item: Mapping[str, Any]) -> bool:
    return (
        item.get("status") in TERMINAL_DISPOSITIONS
        and isinstance(item.get("last_result"), Mapping)
        and item["last_result"].get("contract_status") == "PASS"
    )


def verify_automatic_experiment_queue(
    payload: Mapping[str, Any],
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify the exact queue artifact a consumer is allowed to trust.

    An item may be ``eligible=True`` only when its manifest is structurally
    valid *and* materialized under the explicit ``repo_root``. Consumers such
    as nightly orchestration should call this function before selecting work.
    """

    if not isinstance(payload, Mapping):
        raise ExperimentContractError("automatic experiment queue must be an object")
    if payload.get("schema_version") != QUEUE_SCHEMA_VERSION:
        raise ExperimentContractError("automatic experiment queue schema is unsupported")
    verify_self_hash(payload, hash_field="queue_sha256")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ExperimentContractError("automatic experiment queue items must be a list")
    seen_ids: set[str] = set()
    eligible_items: list[Mapping[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ExperimentContractError(f"items[{index}] must be an object")
        queue_id = _required_text(item.get("queue_id"), f"items[{index}].queue_id")
        if queue_id in seen_ids:
            raise ExperimentContractError(f"duplicate experiment queue_id: {queue_id}")
        seen_ids.add(queue_id)
        if not isinstance(item.get("eligible"), bool):
            raise ExperimentContractError(f"items[{index}].eligible must be boolean")
        command = _string_list(item.get("command"), f"items[{index}].command")
        argv = _string_list(item.get("argv"), f"items[{index}].argv")
        if item["eligible"] is not True:
            if command or argv:
                raise ExperimentContractError(
                    f"items[{index}] is ineligible but exposes an executable command"
                )
            continue
        if item.get("status") != "queued":
            raise ExperimentContractError(
                f"items[{index}] eligible status must be queued"
            )
        if (
            item.get("contract_status") != "PASS"
            or item.get("materialization_status") != "PASS"
            or item.get("contract_eligible") is not True
            or item.get("materialized_executable") is not True
        ):
            raise ExperimentContractError(
                f"items[{index}] eligibility lacks contract/materialization proof"
            )
        manifest = verify_experiment_manifest(item.get("experiment_manifest"))
        if repo_root is None:
            raise ExperimentContractError(
                "eligible queue verification requires an explicit repo_root"
            )
        verify_materialized_experiment_manifest(manifest, repo_root=repo_root)
        expected_argv = list(manifest["argv"])
        if command != expected_argv or argv != expected_argv:
            raise ExperimentContractError(
                f"items[{index}] command/argv do not exactly match the manifest"
            )
        for field, expected in (
            ("queue_id", manifest["queue_id"]),
            ("manifest_sha256", manifest["manifest_sha256"]),
            ("candidate_output_root", manifest["candidate_output_root"]),
        ):
            if item.get(field) != expected:
                raise ExperimentContractError(
                    f"items[{index}].{field} does not match the manifest"
                )
        eligible_items.append(item)

    terminal_items = [item for item in items if _verified_terminal_item(item)]
    blocked_items = [
        item
        for item in items
        if item.get("eligible") is not True and not _verified_terminal_item(item)
    ]
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise ExperimentContractError("automatic experiment queue summary is required")
    expected_summary = {
        "queue_count": len(items),
        "eligible_count": len(eligible_items),
        "contract_eligible_count": sum(
            1 for item in items if item.get("contract_eligible") is True
        ),
        "materialized_executable_count": len(eligible_items),
        "ineligible_count": len(blocked_items),
        "blocked_count": len(blocked_items),
        "verified_terminal_count": len(terminal_items),
        "still_open_count": len(eligible_items),
        **{
            f"{disposition}_count": sum(
                1 for item in terminal_items if item.get("status") == disposition
            )
            for disposition in sorted(TERMINAL_DISPOSITIONS)
        },
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            raise ExperimentContractError(
                f"summary.{field} is inconsistent with queue items"
            )
    expected_status = "READY" if eligible_items else "EMPTY"
    if payload.get("status") != expected_status:
        raise ExperimentContractError("queue status is inconsistent with eligible items")
    return json.loads(canonical_json(payload))


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    raise ExperimentContractError(f"unsupported operator: {operator}")


def _validate_resource_usage(usage: Any) -> dict[str, float]:
    if not isinstance(usage, Mapping):
        raise ExperimentContractError("resource_usage is required")
    fields = ("duration_seconds", "cpu_seconds", "peak_memory_mb", "io_read_mb", "io_write_mb")
    return {
        field: _finite_number(usage.get(field), f"resource_usage.{field}", nonnegative=True)
        for field in fields
    }


def _validate_result_body(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ExperimentContractError("executable experiment result schema is unsupported")
    _required_text(payload.get("result_id"), "result_id")
    if payload.get("queue_id") != manifest.get("queue_id"):
        raise ExperimentContractError("result queue_id does not match manifest")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ExperimentContractError("result manifest hash does not match")
    started = _timestamp(payload.get("started_at_utc"), "started_at_utc")
    finished = _timestamp(payload.get("finished_at_utc"), "finished_at_utc")
    if finished < started:
        raise ExperimentContractError("finished_at_utc precedes started_at_utc")
    disposition = str(payload.get("disposition") or "")
    if disposition not in TERMINAL_DISPOSITIONS:
        raise ExperimentContractError("disposition is not in the terminal taxonomy")
    _required_text(payload.get("disposition_reason"), "disposition_reason")
    sample_count = int(_finite_number(
        payload.get("independent_sample_count"),
        "independent_sample_count",
        nonnegative=True,
    ))
    if sample_count != float(payload.get("independent_sample_count")):
        raise ExperimentContractError("independent_sample_count must be an integer")
    usage = _validate_resource_usage(payload.get("resource_usage"))
    budget = manifest["resource_budget"]
    over_budget = (
        usage["duration_seconds"] > float(budget["timeout_seconds"])
        or usage["peak_memory_mb"] > float(budget["memory_mb"])
        or usage["io_read_mb"] > float(budget["io_read_mb"])
        or usage["io_write_mb"] > float(budget["io_write_mb"])
        or usage["cpu_seconds"] > float(budget["timeout_seconds"]) * float(budget["cpu_cores"])
    )
    minimum = int(manifest["minimum_independent_sample"]["count"])

    metrics = payload.get("metrics")
    artifacts = payload.get("artifacts")
    if disposition == "superseded":
        if metrics not in ({}, None) or artifacts not in ([], None) or sample_count != 0:
            raise ExperimentContractError("superseded results cannot claim measurements or artifacts")
        if payload.get("returncode") not in (None, 0):
            raise ExperimentContractError("superseded result returncode must be null or zero")
        return
    if not isinstance(metrics, Mapping):
        raise ExperimentContractError("metrics are required for a completed attempt")
    primary = metrics.get("primary")
    if not isinstance(primary, Mapping) or primary.get("name") != manifest["primary_metric"]["name"]:
        raise ExperimentContractError("observed primary metric does not match manifest")
    primary_value = _finite_number(primary.get("value"), "metrics.primary.value")
    observed_protected = metrics.get("protected")
    if not isinstance(observed_protected, list):
        raise ExperimentContractError("metrics.protected must be a list")
    observed_by_name: dict[str, float] = {}
    for index, row in enumerate(observed_protected):
        if not isinstance(row, Mapping):
            raise ExperimentContractError(f"metrics.protected[{index}] must be an object")
        name = _required_text(row.get("name"), f"metrics.protected[{index}].name")
        if name in observed_by_name:
            raise ExperimentContractError("observed protected metric names must be unique")
        observed_by_name[name] = _finite_number(row.get("value"), f"metrics.protected[{index}].value")
    protected_specs = {row["name"]: row for row in manifest["protected_metrics"]}
    if set(observed_by_name) != set(protected_specs):
        raise ExperimentContractError("observed protected metric inventory does not match manifest")
    protected_pass = all(
        _compare(observed_by_name[name], spec["operator"], float(spec["threshold"]))
        for name, spec in protected_specs.items()
    )
    decision = manifest["decision_rule"]
    primary_pass = _compare(primary_value, decision["operator"], float(decision["threshold"]))
    enough_sample = sample_count >= minimum

    if not isinstance(payload.get("returncode"), int) or isinstance(payload.get("returncode"), bool):
        raise ExperimentContractError("returncode must be an integer")
    successful_attempt = payload.get("returncode") == 0 and enough_sample and not over_budget
    expected_disposition = (
        "inconclusive"
        if not successful_attempt
        else "regressed"
        if not protected_pass
        else "resolved"
        if primary_pass
        else "rejected"
    )
    if disposition != expected_disposition:
        raise ExperimentContractError(
            f"disposition {disposition!r} contradicts metrics/budget; expected {expected_disposition!r}"
        )
    expected_artifacts = _validate_artifact_rows(
        manifest["expected_artifacts"], field="expected_artifacts"
    )
    if artifacts in (None, []):
        actual_artifacts: dict[str, Mapping[str, Any]] = {}
    else:
        actual_artifacts = _validate_artifact_rows(artifacts, field="artifacts")
    if disposition in {"resolved", "rejected", "regressed"} and set(actual_artifacts) != set(
        expected_artifacts
    ):
        raise ExperimentContractError("terminal measured result is missing expected artifacts")
    if not set(actual_artifacts) <= set(expected_artifacts):
        raise ExperimentContractError("result contains undeclared artifacts")
    for role, row in actual_artifacts.items():
        expected = expected_artifacts[role]
        if any(row.get(field) != expected.get(field) for field in ("path", "sha256", "schema_version")):
            raise ExperimentContractError(f"result artifact {role!r} does not match manifest")


def build_experiment_result(
    payload: Mapping[str, Any], *, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    verified_manifest = verify_experiment_manifest(manifest)
    result = json.loads(canonical_json(payload))
    result.pop("result_sha256", None)
    result.setdefault("schema_version", RESULT_SCHEMA_VERSION)
    _validate_result_body(result, verified_manifest)
    return finalize_self_hash(result, hash_field="result_sha256")


def verify_experiment_result(
    payload: Mapping[str, Any], *, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ExperimentContractError("experiment result must be an object")
    verified_manifest = verify_experiment_manifest(manifest)
    _validate_result_body(payload, verified_manifest)
    verify_self_hash(payload, hash_field="result_sha256")
    return json.loads(canonical_json(payload))


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "QUEUE_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "TERMINAL_DISPOSITIONS",
    "ExperimentContractError",
    "build_experiment_manifest",
    "verify_experiment_manifest",
    "verify_materialized_experiment_manifest",
    "verify_automatic_experiment_queue",
    "build_experiment_result",
    "verify_experiment_result",
    "finalize_self_hash",
    "verify_self_hash",
]
