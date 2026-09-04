"""Fail-closed filesystem transaction for the WU outcome export contract.

The public CLI and artifact validator remain in
``weather.operations.wu_outcome_export_contract``.  This module owns only the
read-only source capture, strict evidence reconciliation, staged artifact
creation, and create-only atomic publication.
"""

from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any, Mapping, Sequence
import uuid

from weather.market.market_registry import BUILTIN_SPECS
from weather.operations import wu_outcome_export_contract as contract


TRACKED_SPEC_RELATIVE = PurePosixPath(
    "docs/roadmap/wu-outcome-gap-production-export-spec-2026-09-100a.json"
)
TRACKED_SPEC_FILE_SHA256 = (
    "cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f"
)
TRACKED_SPEC_SELF_SHA256 = (
    "5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9"
)
TRACKED_GAP_FILE_SHA256 = (
    "6ba020575e3ef1eb903ae0010510caea20f31b31bdf3451c0e03f11175c3de94"
)
TRACKED_GAP_SELF_SHA256 = (
    "64176a727907c8f62c496f6fb1893c1f7462cfef15c1db3f06ef7b3e244f0ce8"
)
MAX_SOURCE_BYTES = 128 * 1024 * 1024
DAILY_SCHEMAS = frozenset({"wu_daily_native_v1", "wu_daily_native_v2"})
REVISION_METADATA_FIELDS = frozenset(
    {
        "ledger_record_type",
        "revision_id",
        "revision_number",
        "recorded_at_utc",
        "supersedes_revision_id",
        "previous_label_hash",
        "label_hash",
        "revision_changes",
        "revision_provenance",
    }
)
MONTH_NAMES = (
    "",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


@dataclass(frozen=True)
class SourceSnapshot:
    role: str
    relative_path: str
    path: Path
    raw: bytes
    byte_count: int
    sha256: str
    file_identity: tuple[int, int, int, int]


def _block(code: str) -> contract.ContractError:
    return contract.ContractError(code)


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_normalized(path), _normalized(root))) == _normalized(root)
    except ValueError:
        return False


def _require_absolute(path: Path, code: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise _block(code)
    return path.absolute()


def _require_exact_case_below(root: Path, path: Path) -> None:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise _block("E_PATH_ESCAPE") from exc
    current = root.absolute()
    for part in relative.parts:
        try:
            matches = [name for name in os.listdir(current) if name.casefold() == part.casefold()]
        except OSError as exc:
            raise _block("E_PATH_ANCESTRY_UNREADABLE") from exc
        if matches != [part]:
            raise _block("E_PATH_CASE_COLLISION")
        current = current / part


def _resolve_source(repo_root: Path, relative_path: str) -> Path:
    try:
        path = contract._contained(repo_root, relative_path, "production source")
    except contract.ContractError as exc:
        raise _block("E_SOURCE_ESCAPE_OR_REPARSE") from exc
    _require_exact_case_below(repo_root, path)
    if not path.is_file() or contract._is_reparse(path):
        raise _block("E_SOURCE_MISSING_OR_REPARSE")
    return path


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _read_source(repo_root: Path, role: str, relative_path: str) -> SourceSnapshot:
    path = _resolve_source(repo_root, relative_path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        # CPython's Windows CRT open uses deny-none sharing.  No advisory or
        # mandatory lock is taken, so ordinary atomic-replace writers proceed.
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise _block("E_SOURCE_READ_FAILED") from exc
    if len(raw) == 0 or len(raw) > MAX_SOURCE_BYTES:
        raise _block("E_SOURCE_BYTE_BOUND")
    if _file_identity(before) != _file_identity(after):
        raise _block("E_SOURCE_CHANGED_DURING_READ")
    path = _resolve_source(repo_root, relative_path)
    try:
        path_identity = _file_identity(path.stat())
    except OSError as exc:
        raise _block("E_SOURCE_DISAPPEARED") from exc
    identity = _file_identity(after)
    if path_identity != identity:
        raise _block("E_SOURCE_PATH_IDENTITY_CHANGED")
    return SourceSnapshot(
        role=role,
        relative_path=relative_path,
        path=path,
        raw=raw,
        byte_count=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        file_identity=identity,
    )


def _require_same_source(before: SourceSnapshot, after: SourceSnapshot) -> None:
    if (
        before.role != after.role
        or before.relative_path != after.relative_path
        or before.byte_count != after.byte_count
        or before.sha256 != after.sha256
        or before.file_identity != after.file_identity
    ):
        raise _block("E_SOURCE_PRE_POST_DRIFT")


def _run_git(repo_root: Path, arguments: Sequence[str], code: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(repo_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise _block(code) from exc
    if result.returncode != 0:
        raise _block(code)
    return result.stdout.strip()


def _git_common_directory(worktree_root: Path, code: str) -> Path:
    raw = _run_git(
        worktree_root,
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        code,
    )
    common = Path(raw)
    if not common.is_absolute():
        common = worktree_root / common
    try:
        return common.resolve(strict=True)
    except OSError as exc:
        raise _block(code) from exc


def _load_frozen_spec(repo_root: Path, spec_path: Path) -> dict[str, Any]:
    repo_root = _require_absolute(repo_root, "E_REPO_ROOT_NOT_ABSOLUTE")
    spec_path = _require_absolute(spec_path, "E_SPEC_NOT_ABSOLUTE")
    contract._require_non_reparse_tree(repo_root)
    if not repo_root.is_dir():
        raise _block("E_REPO_ROOT_MISSING")
    top = _run_git(repo_root, ["rev-parse", "--show-toplevel"], "E_REPO_ROOT_UNTRACKED")
    if _normalized(Path(top)) != _normalized(repo_root):
        raise _block("E_REPO_ROOT_IDENTITY")
    if not spec_path.is_file():
        raise _block("E_SPEC_MISSING")
    contract._require_non_reparse_tree(spec_path)
    spec_top = _run_git(
        spec_path.parent,
        ["rev-parse", "--show-toplevel"],
        "E_SPEC_WORKTREE_UNTRACKED",
    )
    spec_root = Path(spec_top)
    if not spec_root.is_absolute() or not spec_root.is_dir():
        raise _block("E_SPEC_WORKTREE_IDENTITY")
    contract._require_non_reparse_tree(spec_root)
    expected = spec_root.joinpath(*TRACKED_SPEC_RELATIVE.parts)
    if _normalized(spec_path) != _normalized(expected):
        raise _block("E_SPEC_PATH_MISMATCH")
    _require_exact_case_below(spec_root, spec_path)
    if _normalized(
        _git_common_directory(repo_root, "E_REPO_GIT_IDENTITY")
    ) != _normalized(
        _git_common_directory(spec_root, "E_SPEC_REPOSITORY_IDENTITY")
    ):
        raise _block("E_SPEC_REPOSITORY_IDENTITY")
    tracked = _run_git(
        spec_root,
        ["ls-files", "--error-unmatch", "--", TRACKED_SPEC_RELATIVE.as_posix()],
        "E_SPEC_NOT_TRACKED",
    ).replace("\\", "/")
    if tracked != TRACKED_SPEC_RELATIVE.as_posix():
        raise _block("E_SPEC_TRACKED_IDENTITY")
    try:
        if contract.sha256_file(spec_path) != TRACKED_SPEC_FILE_SHA256:
            raise _block("E_SPEC_FILE_HASH")
        spec = contract._read_json(spec_path)
    except (OSError, contract.ContractError) as exc:
        if isinstance(exc, contract.ContractError) and str(exc).startswith("E_"):
            raise
        raise _block("E_SPEC_READ") from exc
    if (
        spec.get("schema_version") != contract.SPEC_SCHEMA
        or spec.get("spec_sha256") != TRACKED_SPEC_SELF_SHA256
        or contract.self_hash(spec, "spec_sha256") != TRACKED_SPEC_SELF_SHA256
    ):
        raise _block("E_SPEC_SELF_HASH")
    gap = spec.get("gap_binding")
    if not isinstance(gap, dict) or (
        gap.get("file_sha256") != TRACKED_GAP_FILE_SHA256
        or gap.get("self_hash") != TRACKED_GAP_SELF_SHA256
    ):
        raise _block("E_SPEC_GAP_BINDING")
    authority = spec.get("downstream_authority")
    if not isinstance(authority, dict) or not authority or any(value is not False for value in authority.values()):
        raise _block("E_SPEC_DOWNSTREAM_AUTHORITY")
    return spec


def _market_configuration(spec: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    request = spec.get("request")
    rows = request.get("keys") if isinstance(request, dict) else None
    if not isinstance(rows, list) or len(rows) != 96 or request.get("requested_rows") != 96:
        raise _block("E_REQUEST_COUNT")
    builtins = {item.id: item for item in BUILTIN_SPECS}
    if len(builtins) != 12:
        raise _block("E_BUILTIN_MARKET_COUNT")
    seen: set[tuple[str, str]] = set()
    markets: set[str] = set()
    market_case: dict[str, str] = {}
    checked: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise _block("E_REQUEST_NONOBJECT")
        market = str(row.get("market") or "")
        folded = market.casefold()
        if folded in market_case and market_case[folded] != market:
            raise _block("E_REQUEST_MARKET_CASE_COLLISION")
        market_case[folded] = market
        if market != folded or market not in builtins:
            raise _block("E_REQUEST_MARKET")
        target_text = str(row.get("target_date") or "")
        try:
            target = date.fromisoformat(target_text)
        except ValueError as exc:
            raise _block("E_REQUEST_DATE") from exc
        key = (market, target_text)
        if key in seen:
            raise _block("E_REQUEST_DUPLICATE")
        seen.add(key)
        configured = builtins[market]
        expected_side = (
            "post_boundary_directional"
            if target >= contract.BOUNDARY_DATE
            else "pre_boundary"
        )
        if (
            row.get("station") != configured.icao.casefold()
            or row.get("settlement_unit") != configured.display_unit
            or row.get("provenance_side") != expected_side
            or row.get("local_status") not in {"missing", "present_below_threshold"}
        ):
            raise _block("E_REQUEST_CONFIGURATION")
        markets.add(market)
        checked.append(row)
    if markets != set(builtins):
        raise _block("E_REQUEST_MARKET_COVERAGE")
    return checked, builtins


def _decode_utf8(raw: bytes, code: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise _block(code) from exc


def _parse_ledger(snapshot: SourceSnapshot, expected_market: str) -> list[dict[str, Any]]:
    text = _decode_utf8(snapshot.raw, "E_LEDGER_ENCODING")
    lines = text.splitlines()
    if not lines:
        raise _block("E_LEDGER_EMPTY")
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            raise _block("E_LEDGER_BLANK_LINE")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _block("E_LEDGER_MALFORMED_JSON") from exc
        if not isinstance(row, dict):
            raise _block("E_LEDGER_NONOBJECT")
        market = str(row.get("market_id") or "")
        if market != expected_market or market != market.casefold():
            raise _block("E_LEDGER_MARKET_PATH_MISMATCH")
        target = str(row.get("target_date") or "")
        try:
            date.fromisoformat(target)
        except ValueError as exc:
            raise _block("E_LEDGER_DATE") from exc
        raw_revision = row.get("revision_number")
        if raw_revision is not None and (
            isinstance(raw_revision, bool)
            or not isinstance(raw_revision, int)
            or raw_revision < 1
        ):
            raise _block("E_LEDGER_REVISION")
        rows.append(row)
    # The stable owner helper is the only market/date revision selector.
    contract.latest_authoritative_ledger_rows(rows)
    _verify_histories(rows)
    return rows


def _label_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in REVISION_METADATA_FIELDS}


def _ledger_canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _label_hash(row: Mapping[str, Any]) -> str:
    return _ledger_canonical_sha256(_label_payload(row))


def _legacy_revision_id(row: Mapping[str, Any]) -> str:
    return f"sha256:legacy:{_label_hash(row)}"


def _revision_number(row: Mapping[str, Any]) -> int:
    value = row.get("revision_number")
    return 0 if value is None else int(value)


def _revision_id(row: Mapping[str, Any]) -> str:
    value = row.get("revision_id")
    return str(value) if value else _legacy_revision_id(row)


def _revision_changes(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = _label_payload(previous or {})
    after = _label_payload(current)
    return [
        {"field": field, "old": before.get(field), "new": after.get(field)}
        for field in sorted(set(before) | set(after))
        if before.get(field) != after.get(field)
    ]


def _verify_histories(rows: Sequence[Mapping[str, Any]]) -> None:
    previous_by_slug: dict[str, Mapping[str, Any]] = {}
    explicit_seen: dict[tuple[str, int], str] = {}
    for row in rows:
        slug = str(row.get("event_slug") or "")
        if not slug:
            raise _block("E_LEDGER_EVENT_SLUG")
        revision = _revision_number(row)
        previous = previous_by_slug.get(slug)
        if revision == 0:
            if any(
                row.get(field) not in (None, "")
                for field in ("revision_id", "recorded_at_utc", "ledger_record_type")
            ):
                raise _block("E_LEDGER_PARTIAL_REVISION_IDENTITY")
            previous_by_slug[slug] = row
            continue
        fingerprint = _ledger_canonical_sha256(row)
        seen_key = (slug, revision)
        prior_fingerprint = explicit_seen.get(seen_key)
        if prior_fingerprint is not None:
            if prior_fingerprint != fingerprint:
                raise _block("E_LEDGER_EQUAL_REVISION_CONFLICT")
            continue
        explicit_seen[seen_key] = fingerprint
        if row.get("ledger_record_type") != "settlement_revision":
            raise _block("E_LEDGER_RECORD_TYPE")
        label_hash = _label_hash(row)
        if row.get("label_hash") != label_hash:
            raise _block("E_LEDGER_LABEL_HASH")
        recorded_at = contract._require_utc_timestamp(
            row.get("recorded_at_utc"), "ledger revision time"
        )
        expected_number = _revision_number(previous or {}) + 1
        if revision != expected_number:
            raise _block("E_LEDGER_REVISION_SEQUENCE")
        supersedes = _revision_id(previous) if previous is not None else None
        previous_hash = _label_hash(previous) if previous is not None else None
        seed = {
            "event_slug": slug,
            "revision_number": revision,
            "recorded_at_utc": recorded_at,
            "label_hash": label_hash,
            "supersedes_revision_id": supersedes,
        }
        if row.get("revision_id") != f"sha256:{_ledger_canonical_sha256(seed)}":
            raise _block("E_LEDGER_REVISION_ID")
        if row.get("supersedes_revision_id") != supersedes:
            raise _block("E_LEDGER_SUPERSESSION")
        if row.get("previous_label_hash") != previous_hash:
            raise _block("E_LEDGER_PREVIOUS_HASH")
        if row.get("revision_changes") != _revision_changes(previous, row):
            raise _block("E_LEDGER_REVISION_CHANGES")
        previous_by_slug[slug] = row


def _parse_integral(value: Any, code: str) -> int:
    if isinstance(value, bool) or value is None or value == "":
        raise _block(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _block(code) from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise _block(code)
    return int(number)


def _parse_daily(snapshot: SourceSnapshot, expected_unit: str) -> dict[str, dict[str, int]]:
    text = _decode_utf8(snapshot.raw, "E_DAILY_ENCODING")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fields = reader.fieldnames
    except csv.Error as exc:
        raise _block("E_DAILY_CSV") from exc
    if not fields or any(field is None or not field for field in fields):
        raise _block("E_DAILY_COLUMNS")
    if len(fields) != len(set(fields)) or len({field.casefold() for field in fields}) != len(fields):
        raise _block("E_DAILY_COLUMN_COLLISION")
    required = {"schema_version", "local_date", "temperature_unit", "row_count"}
    if not required.issubset(fields) or not {
        "max_temp_bucket_native",
        "max_temp_bucket",
        "max_temp_bucket_c",
    }.intersection(fields):
        raise _block("E_DAILY_COLUMNS")
    selected: dict[str, dict[str, int]] = {}
    try:
        for row in reader:
            if None in row:
                raise _block("E_DAILY_EXTRA_COLUMNS")
            if row.get("schema_version") not in DAILY_SCHEMAS:
                raise _block("E_DAILY_SCHEMA")
            target = str(row.get("local_date") or "")
            try:
                date.fromisoformat(target)
            except ValueError as exc:
                raise _block("E_DAILY_DATE") from exc
            if target in selected:
                raise _block("E_DAILY_DUPLICATE_DATE")
            if row.get("temperature_unit") != expected_unit:
                raise _block("E_DAILY_UNIT")
            row_count_text = str(row.get("row_count") or "")
            if not row_count_text.isdigit():
                raise _block("E_DAILY_ROW_COUNT")
            row_count = int(row_count_text)
            bucket_value = row.get("max_temp_bucket_native")
            if bucket_value in (None, ""):
                bucket_value = row.get("max_temp_bucket")
            if bucket_value in (None, ""):
                bucket_value = row.get("max_temp_bucket_c")
            selected[target] = {
                "row_count": row_count,
                "bucket": _parse_integral(bucket_value, "E_DAILY_BUCKET"),
            }
    except csv.Error as exc:
        raise _block("E_DAILY_CSV") from exc
    if not selected:
        raise _block("E_DAILY_EMPTY")
    return selected


def _event_slug(configured: Any, target: date) -> str:
    return (
        f"{configured.slug_prefix}-{MONTH_NAMES[target.month]}-"
        f"{target.day}-{target.year}"
    )


def _label_path_matches(value: Any, repo_root: Path, expected_relative: str) -> bool:
    text = str(value or "")
    if text.replace("\\", "/") == expected_relative:
        return True
    candidate = Path(text)
    if not candidate.is_absolute():
        return False
    expected = repo_root.joinpath(*PurePosixPath(expected_relative).parts)
    if _normalized(candidate) != _normalized(expected):
        return False
    try:
        _require_exact_case_below(repo_root, candidate)
        contract._require_non_reparse_tree(candidate)
    except contract.ContractError:
        return False
    return True


def _selected_revision_identity(row: Mapping[str, Any]) -> tuple[str, int, str]:
    revision = _revision_number(row)
    if revision == 0:
        timestamp = row.get("finalized_at_utc")
        revision_id = _legacy_revision_id(row)
    else:
        timestamp = row.get("recorded_at_utc")
        revision_id = str(row.get("revision_id") or "")
    if not revision_id:
        raise _block("E_LEDGER_REVISION_IDENTITY_ABSENT")
    try:
        recorded_at = contract._require_utc_timestamp(timestamp, "selected revision time")
    except contract.ContractError as exc:
        raise _block("E_LEDGER_REVISION_TIME_ABSENT") from exc
    return revision_id, revision, recorded_at


def _validate_selected_label(
    *,
    row: Mapping[str, Any],
    request: Mapping[str, Any],
    configured: Any,
    repo_root: Path,
    ledger_relative: str,
    daily_relative: str,
    daily_row: Mapping[str, int],
) -> tuple[int, str, int, str]:
    market = str(request["market"])
    target_text = str(request["target_date"])
    target = date.fromisoformat(target_text)
    if (
        row.get("market_id") != market
        or row.get("target_date") != target_text
        or row.get("event_slug") != _event_slug(configured, target)
    ):
        raise _block("E_LEDGER_LABEL_IDENTITY")
    if not _label_path_matches(row.get("ledger_path"), repo_root, ledger_relative):
        raise _block("E_LEDGER_PATH_IDENTITY")
    if not _label_path_matches(row.get("daily_summary_path"), repo_root, daily_relative):
        raise _block("E_DAILY_PATH_IDENTITY")
    if (
        row.get("settlement_unit") != configured.display_unit
        or row.get("resolution_station") != configured.icao
        or row.get("resolution_timezone") != configured.timezone
        or row.get("resolution_wu_history_id") != configured.wu_history_id
    ):
        raise _block("E_LEDGER_RESOLUTION_IDENTITY")
    if (
        row.get("settlement_source") != "daily_summary"
        or row.get("resolution_source_type") != "wunderground_history"
    ):
        raise _block("E_LEDGER_NOT_AUTHORITATIVE_WU")
    if row.get("daily_max_window") != "00:00:00-23:59:59 local" or row.get("rounding") != "round_half_up whole degree":
        raise _block("E_LEDGER_SETTLEMENT_METHOD")
    bucket = _parse_integral(row.get("settlement_bucket"), "E_LEDGER_BUCKET")
    if daily_row["row_count"] < contract.MIN_WU_ROWS:
        raise _block("E_DAILY_BELOW_THRESHOLD")
    if bucket != daily_row["bucket"]:
        raise _block("E_LEDGER_DAILY_BUCKET_DISAGREEMENT")
    evidence = row.get("evidence")
    summary = evidence.get("summary") if isinstance(evidence, dict) else None
    if not isinstance(summary, dict):
        raise _block("E_LEDGER_DAILY_EVIDENCE_ABSENT")
    if (
        _parse_integral(summary.get("bucket"), "E_LEDGER_EVIDENCE_BUCKET") != bucket
        or _parse_integral(summary.get("row_count"), "E_LEDGER_EVIDENCE_COUNT")
        != daily_row["row_count"]
        or not _label_path_matches(summary.get("path"), repo_root, daily_relative)
    ):
        raise _block("E_LEDGER_DAILY_EVIDENCE_MISMATCH")
    revision_id, revision, recorded_at = _selected_revision_identity(row)
    return bucket, revision_id, revision, recorded_at


def _capture_sources(
    repo_root: Path, markets: Sequence[str], configured: Mapping[str, Any]
) -> dict[tuple[str, str], SourceSnapshot]:
    snapshots: dict[tuple[str, str], SourceSnapshot] = {}
    for market in sorted(markets):
        paths = (
            ("settlement_ledger", f"data/settlements/{market}/ledger.jsonl"),
            (
                "wu_daily_summary",
                f"data/wunderground/{configured[market].icao.casefold()}/daily/daily_summary.csv",
            ),
        )
        for role, relative in paths:
            snapshots[(role, market)] = _read_source(repo_root, role, relative)
    return snapshots


def _build_rows(
    *,
    repo_root: Path,
    requests: Sequence[Mapping[str, Any]],
    configured: Mapping[str, Any],
    sources: Mapping[tuple[str, str], SourceSnapshot],
) -> list[dict[str, Any]]:
    ledger_indexes: dict[str, dict[tuple[str, str], Mapping[str, Any]]] = {}
    daily_indexes: dict[str, dict[str, dict[str, int]]] = {}
    for market in sorted(configured):
        ledger = sources[("settlement_ledger", market)]
        daily = sources[("wu_daily_summary", market)]
        ledger_indexes[market] = contract.latest_authoritative_ledger_rows(
            _parse_ledger(ledger, market)
        )
        daily_indexes[market] = _parse_daily(daily, configured[market].display_unit)
    rows: list[dict[str, Any]] = []
    for request in requests:
        market = str(request["market"])
        target = str(request["target_date"])
        ledger = sources[("settlement_ledger", market)]
        daily = sources[("wu_daily_summary", market)]
        label = ledger_indexes[market].get((market, target))
        if label is None:
            raise _block("E_REQUESTED_LEDGER_LABEL_MISSING")
        daily_row = daily_indexes[market].get(target)
        if daily_row is None:
            raise _block("E_REQUESTED_DAILY_ROW_MISSING")
        bucket, revision_id, revision, recorded_at = _validate_selected_label(
            row=label,
            request=request,
            configured=configured[market],
            repo_root=repo_root,
            ledger_relative=ledger.relative_path,
            daily_relative=daily.relative_path,
            daily_row=daily_row,
        )
        rows.append(
            {
                "schema_version": contract.EXPORT_ROW_SCHEMA,
                "market": market,
                "target_date": target,
                "provenance_side": request["provenance_side"],
                "settlement_bucket_native": bucket,
                "settlement_unit": configured[market].display_unit,
                "wu_daily_row_count": daily_row["row_count"],
                "settlement_source": "daily_summary",
                "resolution_source_type": "wunderground_history",
                "resolution_wu_history_id": configured[market].wu_history_id,
                "resolution_station": configured[market].icao,
                "resolution_timezone": configured[market].timezone,
                "source_event_slug": str(label["event_slug"]),
                "source_revision_id": revision_id,
                "source_revision_number": revision,
                "source_recorded_at_utc": recorded_at,
                "source_label_hash": contract.canonical_sha256(label),
                "source_ledger_relative_path": ledger.relative_path,
                "source_ledger_sha256": ledger.sha256,
                "source_daily_summary_relative_path": daily.relative_path,
                "source_daily_summary_sha256": daily.sha256,
            }
        )
    return rows


def _windows_acl_proof(path: Path) -> dict[str, str]:
    if os.name != "nt":
        raise _block("E_ACL_PLATFORM_UNSUPPORTED")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    owner_sid = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    security_info = 0x00000001 | 0x00000002 | 0x00000004
    result = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(os.fspath(path)),
        1,
        security_info,
        ctypes.byref(owner_sid),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise _block("E_ACL_READ")
    sddl_pointer = ctypes.c_wchar_p()
    owner_pointer = ctypes.c_wchar_p()
    try:
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            1,
            security_info,
            ctypes.byref(sddl_pointer),
            None,
        ):
            raise _block("E_ACL_SDDL")
        if not advapi32.ConvertSidToStringSidW(owner_sid, ctypes.byref(owner_pointer)):
            raise _block("E_ACL_OWNER")
        sddl = str(sddl_pointer.value or "")
        owner = str(owner_pointer.value or "")
    finally:
        if sddl_pointer:
            kernel32.LocalFree(ctypes.cast(sddl_pointer, ctypes.c_void_p))
        if owner_pointer:
            kernel32.LocalFree(ctypes.cast(owner_pointer, ctypes.c_void_p))
        if descriptor:
            kernel32.LocalFree(descriptor)
    if not owner or not sddl:
        raise _block("E_ACL_EMPTY")
    return {
        "owner": owner,
        "sddl": sddl,
        "sddl_sha256": hashlib.sha256(sddl.encode("utf-8")).hexdigest(),
    }


def _write_bytes_create_only(path: Path, raw: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise _block("E_STAGING_FILE_EXISTS") from exc


def _source_bindings(
    before: Mapping[tuple[str, str], SourceSnapshot],
    after: Mapping[tuple[str, str], SourceSnapshot],
) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(before):
        first = before[key]
        second = after[key]
        _require_same_source(first, second)
        rows.append(
            {
                "role": first.role,
                "relative_path": first.relative_path,
                "bytes_before": first.byte_count,
                "bytes_after": second.byte_count,
                "sha256_before": first.sha256,
                "sha256_after": second.sha256,
            }
        )
    return rows


def _prepare_destination(repo_root: Path, destination: Path) -> tuple[Path, Path]:
    destination = _require_absolute(destination, "E_DESTINATION_NOT_ABSOLUTE")
    parent = destination.parent
    if not parent.is_dir():
        raise _block("E_DESTINATION_PARENT_MISSING")
    contract._require_non_reparse_tree(parent)
    resolved_parent = parent.resolve(strict=True)
    destination = resolved_parent / destination.name
    if _normalized(destination) == _normalized(repo_root) or _is_within(
        destination, repo_root / "data"
    ):
        raise _block("E_DESTINATION_FORBIDDEN_REPO_PATH")
    if destination.exists() and contract._is_reparse(destination):
        raise _block("E_DESTINATION_REPARSE")
    matches = [
        item.name
        for item in parent.iterdir()
        if item.name.casefold() == destination.name.casefold()
    ]
    if matches:
        raise _block("E_DESTINATION_EXISTS_OR_CASE_COLLIDES")
    return destination, resolved_parent


def _create_staging(parent: Path, destination: Path) -> Path:
    for _attempt in range(8):
        staging = parent / f".{destination.name}.wu-export-staging-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
        except FileExistsError:
            continue
        contract._require_non_reparse_tree(staging)
        if [
            item.name
            for item in parent.iterdir()
            if item.name.casefold() == staging.name.casefold()
        ] != [staging.name]:
            raise _block("E_STAGING_CASE_COLLISION")
        return staging
    raise _block("E_STAGING_CREATE")


def _volume_identity(path: Path) -> int:
    try:
        return int(path.stat().st_dev)
    except OSError as exc:
        raise _block("E_VOLUME_IDENTITY") from exc


def _atomic_publish(staging: Path, destination: Path) -> None:
    if _volume_identity(staging) != _volume_identity(destination.parent):
        raise _block("E_PUBLICATION_CROSS_VOLUME")
    if destination.exists() or any(
        item.name.casefold() == destination.name.casefold()
        for item in destination.parent.iterdir()
    ):
        raise _block("E_DESTINATION_RACE")
    if os.name != "nt":
        raise _block("E_ATOMIC_NOREPLACE_UNSUPPORTED")
    try:
        os.rename(staging, destination)
    except OSError as exc:
        raise _block("E_PUBLICATION_RENAME") from exc


def _safe_remove_owned(path: Path, parent: Path, prefix: str) -> None:
    if path.parent != parent or not path.name.startswith(prefix):
        return
    if path.exists() and path.is_dir() and not contract._is_reparse(path):
        shutil.rmtree(path)


def export_production(
    *, repo_root: Path, spec_path: Path, destination: Path
) -> dict[str, Any]:
    """Create and atomically publish the exact frozen 96-row export."""

    repo_root = _require_absolute(repo_root, "E_REPO_ROOT_NOT_ABSOLUTE")
    spec = _load_frozen_spec(repo_root, spec_path)
    requests, configured = _market_configuration(spec)
    destination, parent = _prepare_destination(repo_root, destination)
    markets = sorted(configured)
    before = _capture_sources(repo_root, markets, configured)
    rows = _build_rows(
        repo_root=repo_root,
        requests=requests,
        configured=configured,
        sources=before,
    )
    after = _capture_sources(repo_root, markets, configured)
    bindings = _source_bindings(before, after)
    payload_raw = b"".join(
        contract.canonical_json_bytes(row) + b"\n" for row in rows
    )
    payload_sha = hashlib.sha256(payload_raw).hexdigest()
    staging: Path | None = None
    published = False
    prefix = f".{destination.name}.wu-export-staging-"
    try:
        staging = _create_staging(parent, destination)
        acl = _windows_acl_proof(staging)
        manifest: dict[str, Any] = {
            "schema_version": contract.EXPORT_MANIFEST_SCHEMA,
            "status": "COMPLETE_CREATE_ONLY_EXPORT",
            "spec_sha256": spec["spec_sha256"],
            "gap_manifest_sha256": spec["gap_binding"]["self_hash"],
            "requested_rows": len(requests),
            "exported_rows": len(rows),
            "destination_acl_proof": acl,
            "payload_file": {
                "relative_path": "wu-outcomes.jsonl",
                "bytes": len(payload_raw),
                "sha256": payload_sha,
                "rows": len(rows),
            },
            "source_files": bindings,
            "downstream_authority": dict(spec["downstream_authority"]),
        }
        manifest["manifest_sha256"] = contract.self_hash(
            manifest, "manifest_sha256"
        )
        manifest_raw = json.dumps(
            manifest, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8") + b"\n"
        manifest_file_sha = hashlib.sha256(manifest_raw).hexdigest()
        if len(payload_raw) + len(manifest_raw) > contract.MAX_EXPORT_BYTES:
            raise _block("E_EXPORT_BYTE_BOUND")
        _write_bytes_create_only(staging / "wu-outcomes.jsonl", payload_raw)
        _write_bytes_create_only(staging / "manifest.json", manifest_raw)
        validation = contract.validate_export(spec_path=spec_path, export_root=staging)
        if validation.get("status") != "PASS":
            raise _block("E_STAGED_VALIDATION")
        final_check = _capture_sources(repo_root, markets, configured)
        for key in before:
            _require_same_source(before[key], final_check[key])
        if _windows_acl_proof(staging) != acl:
            raise _block("E_STAGING_ACL_DRIFT")
        _atomic_publish(staging, destination)
        published = True
        staging = None
        if _windows_acl_proof(destination) != acl:
            raise _block("E_DESTINATION_ACL_DRIFT")
        return {
            "status": "PASS",
            "destination": os.fspath(destination),
            "exported_rows": len(rows),
            "manifest_sha256": manifest["manifest_sha256"],
            "manifest_file_sha256": manifest_file_sha,
            "payload_sha256": payload_sha,
        }
    except Exception:
        if published and destination.exists():
            _safe_remove_owned(destination, parent, destination.name)
        elif staging is not None:
            _safe_remove_owned(staging, parent, prefix)
        raise
