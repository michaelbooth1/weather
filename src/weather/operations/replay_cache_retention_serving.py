"""Exact serving-release input binding for replay-cache rebuilds."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from weather.backtesting.replay_cache import fingerprint
from weather.io import sha256_file
from weather.release_artifacts import RELEASE_MANIFEST_NAME
from weather.release_serving import (
    STATUS_BOUND,
    load_verified_active_serving_bundle,
)


def _is_reparse_point(stat_result: os.stat_result) -> bool:
    return bool(int(getattr(stat_result, "st_file_attributes", 0)) & 0x400)


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_reparse_components(path: str | Path, *, label: str) -> Path:
    lexical = _lexical_absolute(path)
    current = Path(lexical.anchor) if lexical.anchor else Path()
    parts = lexical.parts[1:] if lexical.anchor else lexical.parts
    for part in parts:
        current = current / part
        try:
            stat_result = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ValueError(
                f"cannot inspect {label} path component {current}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if current.is_symlink() or _is_reparse_point(stat_result):
            raise ValueError(f"{label} contains a link or reparse point: {current}")
    return lexical


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return _within(left, right) or _within(right, left)


def validated_standalone_output_root(
    output_root: str | Path,
    protected_roots: list[str | Path],
) -> Path:
    """Validate a receipt-only output that has no associated cache root."""

    output_lexical = _assert_no_reparse_components(
        output_root,
        label="output root",
    )
    normalized_roots = sorted(
        {
            _assert_no_reparse_components(
                root,
                label="protected root",
            ).resolve()
            for root in protected_roots
        },
        key=lambda path: os.path.normcase(str(path)),
    )
    if not normalized_roots:
        raise ValueError("at least one explicit protected data/mirror root is required")
    for protected_root in normalized_roots:
        if _paths_overlap(protected_root, output_lexical):
            raise ValueError(
                "output root must not overlap an explicit protected data/mirror "
                f"root ({protected_root})"
            )
    return output_lexical.resolve()


def cache_data_path(cache_root: Path, relative: Path) -> str:
    lowered = [part.lower() for part in cache_root.parts]
    if "data" in lowered:
        index = len(lowered) - 1 - lowered[::-1].index("data")
        suffix = Path(*cache_root.parts[index + 1 :]).as_posix()
        if suffix:
            prefix = suffix
        else:
            prefix = "backtest/replay_cache"
    elif (
        cache_root.name.lower() == "replay"
        and cache_root.parent.name.lower() == "cache"
    ):
        prefix = "backtest/cache/replay"
    else:
        prefix = "backtest/replay_cache"
    return f"{prefix.rstrip('/')}/{relative.as_posix()}"


def _file_identity(stat_result: os.stat_result) -> dict[str, int]:
    return {
        "device": int(stat_result.st_dev),
        "inode": int(stat_result.st_ino),
        "mtime_ns": int(stat_result.st_mtime_ns),
        "ctime_ns": int(stat_result.st_ctime_ns),
    }


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"duplicate JSON key {key!r}")
            output[key] = value
        return output

    def reject_non_finite(value):
        raise ValueError(f"non-finite JSON constant {value!r}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_non_finite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read JSON {path}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _stable_source(path: str | Path, *, kind: str) -> tuple[dict[str, Any], str]:
    lexical_path = _assert_no_reparse_components(path, label=kind)
    if not lexical_path.exists() or not lexical_path.is_file():
        raise ValueError(f"{kind} is missing or not a file: {lexical_path}")
    path = lexical_path.resolve(strict=True)
    before = path.lstat()
    digest = sha256_file(path)
    after = path.lstat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
        or before.st_dev != after.st_dev
    ):
        raise ValueError(f"{kind} changed while hashed: {path}")
    return (
        {
            "kind": kind,
            "path": str(path),
            "bytes": int(after.st_size),
            "sha256": digest,
            "file_identity": _file_identity(after),
        },
        digest,
    )


def _safe_release_artifact_path(release_dir: Path, raw_path: Any) -> Path:
    relative = Path(str(raw_path or ""))
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"release inventory path is unsafe: {raw_path!r}")
    path = _assert_no_reparse_components(
        release_dir / relative,
        label="release inventory artifact",
    ).resolve(strict=True)
    if not _within(path, release_dir):
        raise ValueError(f"release inventory path escapes release root: {path}")
    return path


def load_serving_rebuild_context(
    pointer_path: str | Path,
    releases_root: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bind every file used by an exact, active serving-release graph."""

    pointer_path = _assert_no_reparse_components(
        pointer_path,
        label="active release pointer",
    ).resolve(strict=True)
    releases_root = _assert_no_reparse_components(
        releases_root,
        label="releases root",
    ).resolve(strict=True)
    if not releases_root.is_dir():
        raise ValueError(f"releases root is not a directory: {releases_root}")

    pointer_source, pointer_file_sha256 = _stable_source(
        pointer_path,
        kind="active_release_pointer",
    )
    bundle = load_verified_active_serving_bundle(
        pointer_path=pointer_path,
        releases_root=releases_root,
    )
    if (
        bundle.status != STATUS_BOUND
        or not bundle.pointer_present
        or not bundle.base_model_bound
        or not bundle.release_id
        or not bundle.manifest_sha256
    ):
        raise ValueError(
            "replay rebuild requires a complete bound active serving release: "
            f"{bundle.status}: {bundle.reason}"
        )
    if bundle.pointer_file_sha256 != pointer_file_sha256:
        raise ValueError("active release pointer changed while serving graph loaded")

    release_dir = _assert_no_reparse_components(
        bundle.release_dir,
        label="active release directory",
    ).resolve(strict=True)
    if not release_dir.is_dir() or not _within(release_dir, releases_root):
        raise ValueError("active release directory is outside the releases root")
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest_source, manifest_file_sha256 = _stable_source(
        manifest_path,
        kind="active_release_manifest",
    )
    manifest = _strict_json(manifest_path)

    inventory = ((manifest.get("artifacts") or {}).get("inventory") or [])
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("active release manifest has no artifact inventory")
    inventory_sources: list[dict[str, Any]] = []
    inventory_paths: dict[str, dict[str, Any]] = {}
    for row in inventory:
        if not isinstance(row, dict):
            raise ValueError("active release inventory contains a non-object row")
        if row.get("declared") is not True:
            continue
        role = str(row.get("role") or "")
        if not role or role in inventory_paths:
            raise ValueError("active release inventory has a missing or duplicate role")
        path = _safe_release_artifact_path(release_dir, row.get("path"))
        source, digest = _stable_source(
            path,
            kind=f"active_release_artifact:{role}",
        )
        if digest != str(row.get("sha256") or ""):
            raise ValueError(f"active release artifact SHA-256 changed: {role}")
        if int(row.get("bytes") or -1) != int(source["bytes"]):
            raise ValueError(f"active release artifact bytes changed: {role}")
        inventory_paths[role] = source
        inventory_sources.append(source)

    if not inventory_sources:
        raise ValueError("active release has no declared artifact sources")
    for role, raw_path in bundle.artifact_paths.items():
        source = inventory_paths.get(str(role))
        if (
            source is None
            or Path(source["path"]) != Path(str(raw_path)).resolve()
            or source["sha256"] != bundle.artifact_hashes.get(role)
        ):
            raise ValueError(
                f"serving bundle artifact is absent from pinned inventory: {role}"
            )

    sources = [pointer_source, manifest_source, *inventory_sources]
    binding = {
        "active_pointer_path": str(pointer_path),
        "active_pointer_file_sha256": pointer_file_sha256,
        "releases_root": str(releases_root),
        "release_dir": str(release_dir),
        "release_id": bundle.release_id,
        "manifest_sha256": bundle.manifest_sha256,
        "manifest_file_sha256": manifest_file_sha256,
        "market_ids": sorted(
            str(market_id)
            for market_id in (bundle.route.get("markets") or {})
        ),
        "source_contract_sha256": fingerprint(
            [
                {
                    "kind": row["kind"],
                    "path": row["path"],
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                }
                for row in sorted(
                    sources,
                    key=lambda item: (item["kind"], item["path"]),
                )
            ]
        ),
        "binding": "genuine_active_pointer_plus_retained_release_inventory",
    }
    binding["identity"] = fingerprint(binding)
    return binding, sources


def serving_binding_identity(binding: Any) -> str:
    if not isinstance(binding, dict):
        raise ValueError("serving rebuild binding must be an object")
    payload = dict(binding)
    claimed = str(payload.pop("identity", "") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise ValueError("serving rebuild binding identity is invalid")
    if fingerprint(payload) != claimed:
        raise ValueError("serving rebuild binding identity changed")
    return claimed


def verify_serving_market_coverage(
    corpus_roots: list[dict[str, Any]],
    binding: dict[str, Any],
) -> None:
    corpus_markets = {
        str(entry.get("market_id") or "")
        for root in corpus_roots
        for entry in (root.get("manifest") or {}).get("entries") or []
    }
    serving_markets = {
        str(market_id) for market_id in binding.get("market_ids") or []
    }
    missing = sorted((corpus_markets - {""}) - serving_markets)
    if missing:
        raise ValueError(
            "pinned serving release lacks corpus markets: "
            + ", ".join(missing)
        )


def load_pinned_serving_bundle(
    binding: dict[str, Any],
):
    """Resolve the genuine active pointer and require the approved plan binding."""

    serving_binding_identity(binding)
    releases_root = _assert_no_reparse_components(
        str(binding.get("releases_root") or ""),
        label="approved releases root",
    ).resolve(strict=True)
    pointer_path = _assert_no_reparse_components(
        str(binding.get("active_pointer_path") or ""),
        label="genuine active release pointer",
    ).resolve(strict=True)
    if pointer_path.parent != releases_root:
        raise ValueError(
            "genuine active release pointer must be directly inside the "
            "approved releases root"
        )
    bundle = load_verified_active_serving_bundle(
        pointer_path=pointer_path,
        releases_root=releases_root,
    )
    if (
        bundle.status != STATUS_BOUND
        or not bundle.base_model_bound
        or bundle.pointer_file_sha256
        != str(binding.get("active_pointer_file_sha256") or "")
        or bundle.release_id != str(binding.get("release_id") or "")
        or bundle.manifest_sha256
        != str(binding.get("manifest_sha256") or "")
        or Path(bundle.release_dir).resolve()
        != Path(str(binding.get("release_dir") or "")).resolve()
    ):
        raise ValueError(
            "genuine active serving release no longer matches the approved plan"
        )
    return bundle
