"""Immutable promotion-corpus binding for scheduled daily refresh."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping
from pathlib import Path

from weather.operations.daily_refresh_locks import backtest_path, utc_iso
from weather.release_artifacts import (
    ReleaseArtifactVerificationError,
    assert_no_link_or_reparse_ancestors,
    is_link_or_reparse_point,
    lexical_absolute_path,
)
from weather.reporting.promotion.promotion_corpus import (
    generation_scoped_manifest_path,
    load_manifest_bytes,
)


PROMOTION_CORPUS_BINDING_SCHEMA_VERSION = (
    "daily_refresh_promotion_corpus_binding_v0.1"
)
DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION = "daily_refresh_resume_source_v0.1"


def daily_refresh_generation_id(args):
    value = str(getattr(args, "_daily_refresh_run_id", "") or "").strip()
    if not value:
        value = str(
            getattr(args, "_daily_refresh_manual_generation_id", "") or ""
        ).strip()
    if not value:
        value = f"daily-manual-{utc_iso()}"
        setattr(args, "_daily_refresh_manual_generation_id", value)
    return value


def fresh_daily_manifest_path(args, filename):
    return generation_scoped_manifest_path(
        backtest_path(args, filename),
        daily_refresh_generation_id(args),
    )


def _stat_identity(stat_result):
    return (
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat.S_IFMT(stat_result.st_mode)),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(stat_result.st_ctime_ns),
    )


def _strict_json_loads(raw):
    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(
                    f"daily-refresh resume status has duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_non_finite(value):
        raise ValueError(
            "daily-refresh resume status has non-finite JSON "
            f"constant {value!r}"
        )

    payload = json.loads(
        raw,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_non_finite,
    )

    def require_finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                "daily-refresh resume status has a non-finite JSON number"
            )
        if isinstance(value, dict):
            for nested in value.values():
                require_finite(nested)
        elif isinstance(value, list):
            for nested in value:
                require_finite(nested)

    require_finite(payload)
    return payload


def _read_stable_bytes(path, *, description):
    lexical = lexical_absolute_path(Path(path).expanduser())
    try:
        assert_no_link_or_reparse_ancestors(lexical, label=description)
    except ReleaseArtifactVerificationError as exc:
        raise RuntimeError(f"{description} path is unsafe: {exc}") from exc
    if is_link_or_reparse_point(lexical):
        raise RuntimeError(
            f"{description} must not be a symlink or reparse point: {lexical}"
        )
    try:
        with lexical.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeError(
                    f"{description} path is not a regular file: {lexical}"
                )
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(
            f"{description} path is missing or unreadable: {lexical}"
        ) from exc
    if _stat_identity(before) != _stat_identity(after) or len(raw) != after.st_size:
        raise RuntimeError(
            f"{description} changed while being read: {lexical}"
        )
    try:
        assert_no_link_or_reparse_ancestors(lexical, label=description)
        if is_link_or_reparse_point(lexical):
            raise RuntimeError(
                f"{description} became a symlink or reparse point: {lexical}"
            )
        rebound = lexical.lstat()
    except RuntimeError:
        raise
    except (OSError, ReleaseArtifactVerificationError) as exc:
        raise RuntimeError(
            f"{description} path changed while being read: {lexical}: {exc}"
        ) from exc
    if (
        not stat.S_ISREG(rebound.st_mode)
        or _stat_identity(rebound) != _stat_identity(after)
    ):
        raise RuntimeError(
            f"{description} path no longer names the opened file: {lexical}"
        )
    return lexical, raw


def _read_stable_promotion_corpus(path):
    resolved, raw = _read_stable_bytes(
        path,
        description="promotion corpus binding",
    )
    try:
        manifest = load_manifest_bytes(raw, path=resolved)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"promotion corpus binding is not a valid operational manifest: {resolved}"
        ) from exc
    return resolved, raw, manifest


def build_promotion_corpus_receipt(path, *, producer_run_id):
    resolved, raw, manifest = _read_stable_promotion_corpus(path)
    return {
        "schema_version": PROMOTION_CORPUS_BINDING_SCHEMA_VERSION,
        "path": str(resolved),
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "producer_daily_refresh_run_id": str(producer_run_id or "").strip(),
    }


def _verified_carried_producer(args, step, receipt):
    provenance = getattr(args, "_daily_refresh_resume_provenance", None)
    carried_source = step.get("carried_forward_source")
    carried_sources = step.get("carried_forward_sources")
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("schema_version")
        != DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION
        or provenance.get("status") != "VERIFIED"
        or provenance.get("runner") != "daily_refresh"
        or not isinstance(carried_source, Mapping)
    ):
        raise RuntimeError(
            "carried promotion corpus lacks verified daily-refresh status "
            "ledger provenance"
        )
    expected_source = {
        "schema_version": DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION,
        "run_id": provenance.get("run_id"),
        "ledger_path": provenance.get("ledger_path"),
        "ledger_sha256": provenance.get("ledger_sha256"),
    }
    if dict(carried_source) != expected_source:
        raise RuntimeError(
            "carried promotion corpus step does not match the verified "
            "resume status ledger"
        )
    if (
        not isinstance(carried_sources, list)
        or not carried_sources
        or not all(isinstance(source, Mapping) for source in carried_sources)
        or dict(carried_sources[-1]) != expected_source
    ):
        raise RuntimeError(
            "carried promotion corpus lacks an ordered status-ledger "
            "provenance chain"
        )
    for source in carried_sources:
        if (
            source.get("schema_version")
            != DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION
            or not str(source.get("run_id") or "").strip()
            or not str(source.get("ledger_path") or "").strip()
            or len(str(source.get("ledger_sha256") or "")) != 64
        ):
            raise RuntimeError(
                "carried promotion corpus status-ledger provenance chain "
                "contains an invalid entry"
            )
    producer_run_id = str(
        receipt.get("producer_daily_refresh_run_id") or ""
    ).strip()
    if not producer_run_id or producer_run_id != carried_sources[0].get("run_id"):
        raise RuntimeError(
            "carried promotion corpus producer run does not match the origin "
            "of the verified resume status-ledger chain"
        )


def _verify_receipt_bytes(result, receipt):
    resolved, raw, manifest = _read_stable_promotion_corpus(receipt["path"])
    expected_size = receipt.get("byte_size")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or expected_size != len(raw)
    ):
        raise RuntimeError(
            "scheduled promotion corpus byte size does not match its immutable "
            f"receipt: expected={expected_size!r}; observed={len(raw)}"
        )
    if receipt.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise RuntimeError(
            "scheduled promotion corpus bytes do not match their immutable "
            "SHA-256 receipt"
        )
    if (
        receipt.get("manifest_schema_version") != manifest.get("schema_version")
        or receipt.get("corpus_hash") != manifest.get("corpus_hash")
        or result.get("corpus_schema_version") != manifest.get("schema_version")
        or result.get("corpus_hash") != manifest.get("corpus_hash")
    ):
        raise RuntimeError(
            "scheduled promotion corpus semantic identity does not match its "
            "step summary and immutable receipt"
        )
    return str(resolved)


def verified_scheduled_promotion_corpus_path(args):
    run_id = str(getattr(args, "_daily_refresh_run_id", "") or "").strip()
    promotion_steps = [
        step
        for step in list(getattr(args, "_daily_refresh_steps_so_far", []) or [])
        if isinstance(step, Mapping) and step.get("name") == "promotion_refresh"
    ]
    if len(promotion_steps) != 1:
        raise RuntimeError(
            "scheduled active-variant shadow requires exactly one promotion "
            f"refresh step; observed={len(promotion_steps)}"
        )
    step = promotion_steps[0]
    if step.get("status") != "ok":
        raise RuntimeError(
            "scheduled active-variant shadow requires promotion step status "
            f"'ok'; observed={step.get('status')!r}"
        )
    result = step.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "OK":
        observed = result.get("status") if isinstance(result, Mapping) else None
        raise RuntimeError(
            "scheduled active-variant shadow requires promotion result status "
            f"'OK'; observed={observed!r}"
        )
    receipt = result.get("corpus_receipt")
    if not isinstance(receipt, Mapping):
        raise RuntimeError(
            "scheduled active-variant shadow promotion step lacks an immutable "
            "corpus receipt"
        )
    if receipt.get("schema_version") != PROMOTION_CORPUS_BINDING_SCHEMA_VERSION:
        raise RuntimeError(
            "scheduled active-variant shadow promotion corpus receipt schema "
            f"is unsupported: {receipt.get('schema_version')!r}"
        )

    result_path = str(result.get("corpus_path") or "").strip()
    receipt_path = str(receipt.get("path") or "").strip()
    if not result_path or not receipt_path:
        raise RuntimeError(
            "scheduled active-variant shadow promotion corpus binding lacks "
            "an exact path"
        )
    try:
        result_resolved = str(Path(result_path).expanduser().resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            f"scheduled promotion corpus path is missing: {result_path}"
        ) from exc
    if result_resolved != receipt_path:
        raise RuntimeError(
            "scheduled promotion corpus path does not match its immutable "
            f"receipt: result={result_resolved}; receipt={receipt_path}"
        )

    carried = step.get("carried_forward", False)
    if not isinstance(carried, bool):
        raise RuntimeError(
            "scheduled promotion corpus step has ambiguous carried-forward "
            f"status: {carried!r}"
        )
    if carried:
        _verified_carried_producer(args, step, receipt)
    else:
        producer_run_id = str(
            receipt.get("producer_daily_refresh_run_id") or ""
        ).strip()
        if not producer_run_id or producer_run_id != run_id:
            raise RuntimeError(
                "scheduled promotion corpus was not produced by the current "
                f"daily-refresh run: expected={run_id!r}; "
                f"observed={producer_run_id!r}"
            )
    return _verify_receipt_bytes(result, receipt)


def promotion_corpus_path_for_active_shadow(args):
    if getattr(args, "_daily_refresh_run_id", None):
        return verified_scheduled_promotion_corpus_path(args)

    current = str(
        getattr(args, "_current_promotion_corpus_path", "") or ""
    ).strip()
    if current:
        return current
    for step in reversed(
        list(getattr(args, "_daily_refresh_steps_so_far", []) or [])
    ):
        if step.get("name") != "promotion_refresh":
            continue
        result = step.get("result") or {}
        current = str(
            result.get("corpus_path")
            or ((result.get("corpus") or {}).get("path"))
            or ""
        ).strip()
        if current:
            setattr(args, "_current_promotion_corpus_path", current)
            return current
    legacy = Path(backtest_path(args, "promotion_corpus.json"))
    if legacy.exists():
        # Direct/manual research calls retain the durable-corpus fallback.
        return str(legacy)
    current = str(fresh_daily_manifest_path(args, "promotion_corpus.json"))
    setattr(args, "_current_promotion_corpus_path", current)
    return current


def active_shadow_window_corpus_path(args):
    path = fresh_daily_manifest_path(
        args,
        "active_variant_shadow_window_corpus.json",
    )
    setattr(args, "_current_active_shadow_window_corpus_path", str(path))
    return str(path)


def _resume_source_provenance(path, raw, prior, *, expected_schema_version):
    if not isinstance(prior, dict):
        return {
            "schema_version": DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION,
            "status": "UNVERIFIED",
            "reason": "status_root_not_object",
        }
    run_id = str(prior.get("run_id") or "").strip()
    if (
        prior.get("schema_version") != expected_schema_version
        or prior.get("runner") != "daily_refresh"
        or not run_id
    ):
        return {
            "schema_version": DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION,
            "status": "UNVERIFIED",
            "reason": "status_identity_invalid",
            "run_id": run_id,
        }
    return {
        "schema_version": DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION,
        "status": "VERIFIED",
        "runner": "daily_refresh",
        "daily_refresh_schema_version": expected_schema_version,
        "run_id": run_id,
        "ledger_path": str(path),
        "ledger_sha256": hashlib.sha256(raw).hexdigest(),
        "source_status": prior.get("status"),
        "source_started_at_utc": prior.get("started_at_utc"),
    }


def read_resume_source_status(path, *, expected_schema_version):
    try:
        resolved, raw = _read_stable_bytes(
            path,
            description="daily-refresh resume status",
        )
        prior = _strict_json_loads(raw)
    except (
        OSError,
        RuntimeError,
        UnicodeDecodeError,
        ValueError,
    ):
        return {}, {
            "schema_version": DAILY_REFRESH_RESUME_SOURCE_SCHEMA_VERSION,
            "status": "UNVERIFIED",
            "reason": "status_missing_unreadable_or_unstable",
        }
    return prior, _resume_source_provenance(
        resolved,
        raw,
        prior,
        expected_schema_version=expected_schema_version,
    )
