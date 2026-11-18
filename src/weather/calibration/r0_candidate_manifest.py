"""Candidate manifest for one R0 retrain centre (retrain memo R0.1 step 4, piece M13).

One JSON per centre binds what the R0 arm hash will cite:

* per trained market: the sha256 of the base-only coefs, HGB and report written
  by ``feature_model --output-root``, the training-column allowlist record and
  its sha256, and the trainer's ``training_inputs`` record;
* per trained market: the sha256 of the five **served** components a research
  release copies unchanged (``late_day_lr_coefficients``,
  ``calibrated_weights``, ``probability_calibration``, ``forecast_error_model``,
  ``settlement_lag_model``);
* per trained market: the ``served_model_differences`` record (every column
  removed from the served list with its reason and decision, base models only,
  forecast source, training window);
* the centre date and its +/-7-day window, the corpus ids and manifest sha256s,
  the training-year composition, the build commit and the exclusion list.

Scope (owner M8, ``weather.calibration.r0_scope``): every trained market must be
one of the US 11 and trained in ``r0:<market>`` allowlist mode; every US 11
market is either trained or explicitly excluded with a reason; Toronto is
always recorded as excluded with the code-owned reason.

The manifest is self-hashed (``manifest_sha256``), written once and never
overwritten. It is training-only evidence; nothing in serving reads it.

    python -m weather.calibration.r0_candidate_manifest \
        --candidate-root artifacts/candidates/retrain-r0-2026-11-24 \
        --candidate-id retrain-r0-2026-11-24 --centre 2026-11-24 \
        --build-commit <40-hex> --market atlanta --market austin ... --market seattle
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from weather.calibration.feature_model_training_inputs import parse_target_date
from weather.calibration.r0_scope import (
    DECISION_BASE_ONLY,
    DECISION_CONSENSUS,
    DECISION_PRESSURE,
    R0_MARKET_IDS,
    R0_OUT_OF_SCOPE_MARKETS,
    SERVED_HGB_MIN_SAMPLES_LEAF,
    served_model_differences,
)
from weather.market.market_registry import spec_for_id
from weather.model.model_constants import HISTORY_WINDOW_DAYS
from weather.paths import REPO_ROOT

MANIFEST_RECORD = "r0_candidate_manifest"
# v2 (2026-10-23): R0 scope, r0 allowlist mode and served_model_differences.
MANIFEST_RECORD_VERSION = 2
R0_ALLOWLIST_MODE = "r0"
MANIFEST_FILENAME = "r0_candidate_manifest.json"
TRAINED_COMPONENTS = ("feature_hgb", "feature_lr_coefficients")
# The five components a research release copies unchanged from serving.
SERVED_COMPONENTS = (
    "late_day_lr_coefficients",
    "calibrated_weights",
    "probability_calibration",
    "forecast_error_model",
    "settlement_lag_model",
)
LFS_POINTER_PREFIX = b"version https://git-lfs"
_COMMIT = re.compile(r"\A[0-9a-f]{40}\Z")
_CANDIDATE_ID = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,95}\Z")


class R0CandidateManifestError(ValueError):
    """The candidate cannot be bound into a manifest exactly."""


def canonical_sha256(payload: Any, *, omit: Sequence[str] = ()) -> str:
    body = {key: value for key, value in payload.items() if key not in omit} if omit else payload
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_suffix(market_id: str) -> str:
    return "" if market_id == "toronto" else f"_{market_id}"


def trained_files(market_root: Path, market_id: str) -> dict[str, Path]:
    suffix = artifact_suffix(market_id)
    return {
        "feature_lr_coefficients": market_root / f"feature_model_coefs{suffix}.json",
        "feature_hgb": market_root / f"feature_model_hgb{suffix}.pkl",
        "report": market_root / f"feature_model_report{suffix}.md",
    }


def served_component_paths(repo_root: Path, market_id: str) -> dict[str, Path]:
    """Served paths of the five copied components (same layout the release builder freezes)."""
    suffix = artifact_suffix(market_id)
    artifacts = Path(repo_root) / "artifacts"
    return {
        "late_day_lr_coefficients": artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json",
        "calibrated_weights": artifacts / "calibration" / f"calibrated_weights{suffix}.json",
        "probability_calibration": artifacts / "calibration" / f"probability_calibration{suffix}.json",
        "forecast_error_model": artifacts / "calibration" / f"forecast_error_model{suffix}.json",
        "settlement_lag_model": artifacts / "calibration" / f"settlement_lag_model{suffix}.json",
    }


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise R0CandidateManifestError(f"{label} is missing or not a regular file: {path}")
    with path.open("rb") as handle:
        if handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX:
            raise R0CandidateManifestError(f"{label} is an LFS pointer, not its bytes: {path}")
    return path


def centre_window(centre: date) -> dict[str, Any]:
    start = centre - timedelta(days=HISTORY_WINDOW_DAYS)
    end = centre + timedelta(days=HISTORY_WINDOW_DAYS)
    return {
        "centre": centre.isoformat(),
        "half_width_days": HISTORY_WINDOW_DAYS,
        "prior_year_month_day_start": start.strftime("%m-%d"),
        "prior_year_month_day_end": end.strftime("%m-%d"),
    }


def _market_entry(market_root: Path, market_id: str, centre: date, repo_root: Path) -> dict[str, Any]:
    files = trained_files(market_root, market_id)
    for name, path in files.items():
        _regular_file(path, f"{market_id} {name}")
    coefs = json.loads(files["feature_lr_coefficients"].read_text(encoding="utf-8"))
    with files["feature_hgb"].open("rb") as handle:
        hgb = pickle.load(handle)  # noqa: S301 - the trainer's own local candidate output
    if not isinstance(coefs, Mapping) or not isinstance(hgb, Mapping):
        raise R0CandidateManifestError(f"{market_id}: candidate artifacts are not mappings")
    for label, info in (("coefs", coefs), ("hgb", hgb)):
        if info.get("base_models_only") is not True:
            raise R0CandidateManifestError(f"{market_id} {label}: not a base-models-only fit")
        if not isinstance(info.get("training_inputs"), Mapping):
            raise R0CandidateManifestError(f"{market_id} {label}: no training_inputs record")
        if not isinstance(info.get("training_column_allowlist"), Mapping):
            raise R0CandidateManifestError(f"{market_id} {label}: no training_column_allowlist")
    if coefs["training_inputs"] != hgb["training_inputs"]:
        raise R0CandidateManifestError(f"{market_id}: coefs and HGB training_inputs differ")
    if coefs["training_column_allowlist"] != hgb["training_column_allowlist"]:
        raise R0CandidateManifestError(f"{market_id}: coefs and HGB allowlist records differ")
    if coefs["training_column_allowlist"].get("mode") != R0_ALLOWLIST_MODE:
        raise R0CandidateManifestError(
            f"{market_id}: trained with allowlist mode "
            f"{coefs['training_column_allowlist'].get('mode')!r}, not 'r0:{market_id}'"
        )
    for label, info in (("coefs", coefs), ("hgb", hgb)):
        if not isinstance(info.get("served_model_differences"), Mapping):
            raise R0CandidateManifestError(f"{market_id} {label}: no served_model_differences record")
    if coefs["served_model_differences"] != hgb["served_model_differences"]:
        raise R0CandidateManifestError(f"{market_id}: coefs and HGB served_model_differences differ")
    differences = dict(coefs["served_model_differences"])
    if coefs.get("hgb_hyperparameters") != hgb.get("hgb_hyperparameters"):
        raise R0CandidateManifestError(f"{market_id}: coefs and HGB hgb_hyperparameters differ")
    leaf = hgb_min_samples_leaf(coefs)
    expected = served_model_differences(
        coefs["training_column_allowlist"], coefs["training_inputs"], base_models_only=True,
        hgb_min_samples_leaf=leaf,
    )
    if differences != expected:
        raise R0CandidateManifestError(
            f"{market_id}: served_model_differences does not match the allowlist and inputs records"
        )
    inputs = dict(coefs["training_inputs"])
    if inputs.get("centre_date") != centre.isoformat() or inputs.get("centre_date_pinned") is not True:
        raise R0CandidateManifestError(
            f"{market_id}: trained at centre {inputs.get('centre_date')!r}, not pinned {centre}"
        )
    allowlist = dict(coefs["training_column_allowlist"])
    served = {}
    for component, path in served_component_paths(repo_root, market_id).items():
        _regular_file(path, f"{market_id} served {component}")
        served[component] = {
            "path": path.relative_to(repo_root).as_posix(),
            "sha256": file_sha256(path),
        }
    return {
        "market_id": market_id,
        "trained": {
            name: {"file": path.name, "sha256": file_sha256(path)}
            for name, path in files.items()
        },
        "training_column_allowlist": allowlist,
        "training_column_allowlist_sha256": allowlist.get("sha256") or canonical_sha256(allowlist),
        "training_inputs": inputs,
        "served_model_differences": differences,
        "hgb_min_samples_leaf": leaf,
        "served_components": served,
    }


def hgb_min_samples_leaf(info: Mapping[str, Any]) -> int:
    """The leaf floor a base-only fit used; fits before the flag record none (served 20)."""
    params = info.get("hgb_hyperparameters")
    if params is None:
        return SERVED_HGB_MIN_SAMPLES_LEAF
    if not isinstance(params, Mapping) or not isinstance(params.get("min_samples_leaf"), int):
        raise R0CandidateManifestError("hgb_hyperparameters has no integer min_samples_leaf")
    return int(params["min_samples_leaf"])


def r0_scope_exclusions(
    market_ids: Sequence[str],
    excluded_markets: Mapping[str, str] | None,
) -> dict[str, str]:
    """Check the R0 scope and return the full, reason-bearing exclusion map.

    Every trained market must be an R0 market. Every R0 market not trained
    needs a caller-given reason. Out-of-scope markets (Toronto) are always
    excluded with the code-owned reason; a caller reason is appended to it.
    """
    trained = [str(market) for market in market_ids]
    outside = sorted(set(trained) - set(R0_MARKET_IDS))
    if outside:
        raise R0CandidateManifestError(
            f"markets outside R0 (the US 11, owner M8) cannot be trained: {outside}"
        )
    caller = {str(key): str(value) for key, value in (excluded_markets or {}).items()}
    unknown = sorted(set(caller) - set(R0_MARKET_IDS) - set(R0_OUT_OF_SCOPE_MARKETS))
    if unknown:
        raise R0CandidateManifestError(f"excluded markets are not built-in markets: {unknown}")
    missing = [market for market in R0_MARKET_IDS if market not in trained and market not in caller]
    if missing:
        raise R0CandidateManifestError(
            f"R0 markets neither trained nor excluded with a reason: {missing}"
        )
    excluded = {market: reason for market, reason in caller.items() if market in R0_MARKET_IDS}
    for market, reason in R0_OUT_OF_SCOPE_MARKETS.items():
        extra = caller.get(market)
        excluded[market] = reason if not extra or extra == reason else f"{reason}; caller: {extra}"
    return dict(sorted(excluded.items()))


def build_r0_candidate_manifest(
    candidate_root: str | Path,
    *,
    candidate_id: str,
    centre: str | date,
    markets: Sequence[str],
    build_commit: str,
    excluded_markets: Mapping[str, str] | None = None,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Bind one centre's trained markets and served components; fail closed on any gap."""
    root = Path(candidate_root).resolve()
    repo_root = Path(repo_root).resolve()
    centre_date = parse_target_date(centre)
    if not _CANDIDATE_ID.fullmatch(str(candidate_id)):
        raise R0CandidateManifestError(f"candidate id is not a plain slug: {candidate_id!r}")
    if not _COMMIT.fullmatch(str(build_commit)):
        raise R0CandidateManifestError("build commit must be a full 40-hex sha")
    market_ids = [str(market) for market in markets]
    if not market_ids or len(set(market_ids)) != len(market_ids):
        raise R0CandidateManifestError("markets must be a non-empty list without repeats")
    caller_excluded = {str(key): str(value) for key, value in (excluded_markets or {}).items()}
    overlap = sorted(set(caller_excluded) & set(market_ids))
    if overlap:
        raise R0CandidateManifestError(f"markets both trained and excluded: {overlap}")
    for market_id in [*market_ids, *caller_excluded]:
        spec_for_id(market_id)
    excluded = r0_scope_exclusions(market_ids, caller_excluded)
    entries = {
        market_id: _market_entry(root / market_id, market_id, centre_date, repo_root)
        for market_id in sorted(market_ids)
    }
    corpus_identities = {
        canonical_sha256(entry["training_inputs"].get("pit_forecast_corpus")) for entry in entries.values()
    }
    years = {tuple(entry["training_inputs"].get("training_years") or ()) for entry in entries.values()}
    if len(corpus_identities) != 1 or len(years) != 1:
        raise R0CandidateManifestError("markets were trained on different corpora or training years")
    leaves = {entry["hgb_min_samples_leaf"] for entry in entries.values()}
    if len(leaves) != 1:
        raise R0CandidateManifestError(f"markets were trained at different HGB leaf floors: {sorted(leaves)}")
    first = next(iter(entries.values()))["training_inputs"]
    corpus = first.get("pit_forecast_corpus") or {}
    manifest = {
        "record": MANIFEST_RECORD,
        "record_version": MANIFEST_RECORD_VERSION,
        "candidate_id": str(candidate_id),
        "candidate_mode": "research_only",
        "base_models_only": True,
        "window": centre_window(centre_date),
        "build_commit": str(build_commit),
        "forecast_source": first.get("forecast_source"),
        "training_years": list(first.get("training_years") or []),
        "pit_forecast_corpora": [
            {"corpus_id": row["corpus_id"], "manifest_sha256": row["manifest_sha256"], "years": row["years"]}
            for row in corpus.get("corpora") or []
        ],
        "pit_forecast_corpus_union_sha256": corpus.get("union_sha256"),
        "hgb_min_samples_leaf": next(iter(leaves)),
        "trained_components": list(TRAINED_COMPONENTS),
        "served_components": list(SERVED_COMPONENTS),
        "scope": {
            "r0_market_ids": list(R0_MARKET_IDS),
            "allowlist_mode": R0_ALLOWLIST_MODE,
            "decisions": [DECISION_PRESSURE, DECISION_CONSENSUS, DECISION_BASE_ONLY],
        },
        "markets": entries,
        "excluded_markets": excluded,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest, omit=("manifest_sha256",))
    return manifest


def write_r0_candidate_manifest(manifest: Mapping[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise R0CandidateManifestError(f"candidate manifest already exists (never overwritten): {path}") from exc
    return path


def verify_r0_candidate_manifest(
    path: str | Path,
    *,
    candidate_root: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Re-verify the self hash and, when roots are given, every bound file's bytes."""
    path = Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("record") != MANIFEST_RECORD or manifest.get("record_version") != MANIFEST_RECORD_VERSION:
        raise R0CandidateManifestError("not an R0 candidate manifest")
    if manifest.get("manifest_sha256") != canonical_sha256(manifest, omit=("manifest_sha256",)):
        raise R0CandidateManifestError("candidate manifest self-hash mismatch")
    root = Path(candidate_root) if candidate_root is not None else path.parent
    for market_id, entry in manifest["markets"].items():
        for name, row in entry["trained"].items():
            actual = root / market_id / row["file"]
            if not actual.is_file() or file_sha256(actual) != row["sha256"]:
                raise R0CandidateManifestError(f"{market_id} {name} bytes differ from the manifest")
        if repo_root is not None:
            for component, row in entry["served_components"].items():
                actual = Path(repo_root) / row["path"]
                if not actual.is_file() or file_sha256(actual) != row["sha256"]:
                    raise R0CandidateManifestError(
                        f"{market_id} served {component} differs from the manifest"
                    )
    return manifest


def _excluded(values: Sequence[str]) -> dict[str, str]:
    out = {}
    for value in values or ():
        market, sep, reason = str(value).partition("=")
        if not sep or not market or not reason:
            raise argparse.ArgumentTypeError(f"--exclude-market needs <market>=<reason>: {value!r}")
        out[market] = reason
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the R0 candidate manifest for one centre.")
    parser.add_argument("--candidate-root", required=True, help="Directory holding <market>/ trainer output.")
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--centre", required=True, help="Pinned centre date, YYYY-MM-DD.")
    parser.add_argument("--build-commit", required=True, help="Full sha of the pushed build commit.")
    parser.add_argument("--market", action="append", required=True, dest="markets")
    parser.add_argument("--exclude-market", action="append", default=[], help="<market>=<reason>")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Checkout holding the served artifacts.")
    parser.add_argument("--out", default=None, help=f"Default: <candidate-root>/{MANIFEST_FILENAME}.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_r0_candidate_manifest(
        args.candidate_root,
        candidate_id=args.candidate_id,
        centre=args.centre,
        markets=args.markets,
        build_commit=args.build_commit,
        excluded_markets=_excluded(args.exclude_market),
        repo_root=args.repo_root,
    )
    out = Path(args.out) if args.out else Path(args.candidate_root) / MANIFEST_FILENAME
    write_r0_candidate_manifest(manifest, out)
    print(json.dumps({"path": str(out), "manifest_sha256": manifest["manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
