"""Paired replay of R0 against the served models on captured inputs (retrain memo R0.2, piece M15).

Each captured snapshot (``replay_inputs.jsonl``) is replayed twice through the
same code, the same captured sources and the same build ``now``:

* **A0 (served):** ``TorontoHighTempModel`` exactly as research replay builds
  it today (no active release; global served artifacts);
* **R0:** the same model, except that its ``feature_hgb`` and
  ``feature_lr_coefficients`` are the verified bytes of a research-only R0
  release (``all_shadow_release_bootstrap --r0-candidate-manifest``). The
  release's other five base components must equal the served artifacts the A0
  arm loads, so the two arms differ in exactly those two components.

The arm schedule picks the R0 release by local target date (R0a for
11-17..12-01, R0b for 12-02..12-19 in the memo's switch rule); its sha256 is in
every output header. ``--max-target-date`` is required: a folder dated after it
is skipped without being opened, which keeps rehearsals on dev dates and the
production read on the dates its pre-registration names. The replay reads only
``replay_inputs.jsonl`` (never tapes, settlements or prices) and writes paired
distributions; scoring them against settlement is a separate, later step.

    python -m weather.backtesting.r0_paired_replay --schedule r0_schedule.json \
        --max-target-date 2026-09-29 --out <new.jsonl> <snapshot folder> ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from weather.artifacts import resolve_artifact_path
from weather.backtesting.replay import (
    distribution_l1,
    is_reconstructed,
    load_replay_records,
    replay_distribution,
    replay_identity_hash,
)
from weather.backtesting.settled_days import folder_market_id
from weather.market.market_config import date_from_event_slug
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import REPO_ROOT
from weather.release_artifacts import sha256_file, strict_json_loads, verify_release
from weather.release_contract import RESEARCH_ONLY_CANDIDATE_MODE
from weather.release_serving import STATUS_RESEARCH_UNBOUND

R0_COMPONENTS = ("feature_hgb", "feature_lr_coefficients")
SERVED_COMPONENT_FILES = {
    "late_day_lr_coefficients": "late_day_model_coefs{suffix}.json",
    "calibrated_weights": "calibrated_weights{suffix}.json",
    "probability_calibration": "probability_calibration{suffix}.json",
    "forecast_error_model": "forecast_error_model{suffix}.json",
    "settlement_lag_model": "settlement_lag_model{suffix}.json",
}
OUTPUT_RECORD = "r0_paired_replay"
OUTPUT_RECORD_VERSION = 1


class R0PairedReplayError(ValueError):
    """The paired replay cannot be bound or run exactly."""


def _canonical_sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _inventory(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = (manifest.get("artifacts") or {}).get("inventory") or []
    return {str(row.get("role")): row for row in rows if isinstance(row, Mapping)}


def _load_role(release_dir: Path, row: Mapping[str, Any], label: str) -> Any:
    path = release_dir / str(row["path"])
    if not path.is_file() or sha256_file(path) != row.get("sha256"):
        raise R0PairedReplayError(f"release role bytes do not verify: {label}")
    if path.suffix.casefold() == ".json":
        return strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    with path.open("rb") as handle:
        return pickle.load(handle)  # noqa: S301 - hash-verified immutable release artifact


def load_r0_release(
    release_dir: str | Path,
    *,
    expected_manifest_sha256: str,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    verifier=verify_release,
) -> dict[str, Any]:
    """Verify one research-only R0 release and load its per-market base components."""
    release_dir = Path(release_dir).resolve()
    verified = verifier(
        release_dir,
        repo_root=repo_root,
        expected_manifest_sha256=expected_manifest_sha256,
        check_runtime=check_runtime,
    )
    semantic = verified.get("semantic_contract") or {}
    if verified.get("status") != "PASS" or semantic.get("candidate_mode") != RESEARCH_ONLY_CANDIDATE_MODE:
        raise R0PairedReplayError("R0 replay needs a verified research_only release")
    manifest = verified["manifest"]
    r0 = ((manifest.get("lineage") or {}).get("source_provenance") or {}).get("r0_candidate")
    if not isinstance(r0, Mapping) or not r0.get("markets"):
        raise R0PairedReplayError("release was not built from an R0 candidate manifest")
    roles = _inventory(manifest)
    markets = {}
    for market_id in r0["markets"]:
        components = {}
        for component in (*R0_COMPONENTS, *SERVED_COMPONENT_FILES):
            role = f"base_model.{market_id}.{component}"
            if role not in roles:
                raise R0PairedReplayError(f"release lacks role {role}")
            components[component] = _load_role(release_dir, roles[role], role)
        markets[market_id] = components
    return {
        "release_id": str(verified.get("release_id")),
        "manifest_sha256": str(verified.get("manifest_sha256")),
        "candidate_manifest_sha256": r0.get("manifest_sha256"),
        "window": r0.get("window"),
        "markets": markets,
    }


class R0BoundModel(TorontoHighTempModel):
    """Research replay model whose two R0 components come from a verified R0 release.

    Construction is the research (no active release) path; afterwards the
    release's other five components must equal the served files this model
    loaded, so only ``feature_hgb`` and ``feature_lr_coefficients`` differ.
    """

    def __init__(self, *, r0_release: Mapping[str, Any], market_id: str, **kwargs):
        if market_id not in r0_release["markets"]:
            raise R0PairedReplayError(f"R0 release has no market {market_id!r}")
        self._r0_components = r0_release["markets"][market_id]
        super().__init__(market_id=market_id, **kwargs)

    def _configure_base_model_components(self):
        super()._configure_base_model_components()
        if self.serving_bundle.status != STATUS_RESEARCH_UNBOUND:
            raise R0PairedReplayError(
                "paired replay needs the research (unbound) served path on both arms; "
                f"serving bundle is {self.serving_bundle.status}"
            )
        suffix = self.spec.artifact_suffix
        for component, template in SERVED_COMPONENT_FILES.items():
            path = resolve_artifact_path(template.format(suffix=suffix))
            served = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            if served != self._r0_components[component]:
                raise R0PairedReplayError(
                    f"R0 release {component} for {self.market_id} differs from the served artifact"
                )
        self._feature_model_hgb = self._r0_components["feature_hgb"]
        self._feature_model_coefs = self._r0_components["feature_lr_coefficients"]


def load_schedule(path: str | Path) -> dict[str, Any]:
    """``{"arms": [{"name", "release_dir", "manifest_sha256", "first_target_date", "last_target_date"}]}``.

    Ranges must be valid and must not overlap.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    arms = []
    for row in payload.get("arms") or []:
        first = date.fromisoformat(str(row["first_target_date"]))
        last = date.fromisoformat(str(row["last_target_date"]))
        if last < first:
            raise R0PairedReplayError(f"arm {row.get('name')!r} range is reversed")
        arms.append({**row, "first": first, "last": last})
    if not arms:
        raise R0PairedReplayError("schedule names no arm")
    arms.sort(key=lambda row: row["first"])
    for earlier, later in zip(arms, arms[1:]):
        if later["first"] <= earlier["last"]:
            raise R0PairedReplayError(f"arms {earlier['name']!r} and {later['name']!r} overlap")
    return {
        "arms": arms,
        "schedule_sha256": _canonical_sha256(payload),
    }


def arm_for_date(schedule: Mapping[str, Any], target_date: date) -> Mapping[str, Any] | None:
    for arm in schedule["arms"]:
        if arm["first"] <= target_date <= arm["last"]:
            return arm
    return None


def run_paired_replay(
    folders: Sequence[str | Path],
    schedule: Mapping[str, Any],
    *,
    max_target_date: date,
    out_path: str | Path,
    repo_root: str | Path = REPO_ROOT,
    include_reconstructed: bool = False,
    release_loader=load_r0_release,
    served_model_factory=TorontoHighTempModel,
    r0_model_factory=R0BoundModel,
) -> dict[str, Any]:
    out_path = Path(out_path)
    if out_path.exists():
        raise R0PairedReplayError(f"output already exists (never overwritten): {out_path}")
    releases: dict[str, Any] = {}
    served_models: dict[str, Any] = {}
    r0_models: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for folder in folders:
        folder = Path(folder)
        target_date = date_from_event_slug(folder.name)
        market_id = folder_market_id(folder)
        if target_date is None or market_id is None:
            skipped.append({"folder": folder.name, "reason": "not a market-day folder"})
            continue
        if target_date > max_target_date:
            skipped.append({"folder": folder.name, "reason": "after --max-target-date (not opened)"})
            continue
        arm = arm_for_date(schedule, target_date)
        if arm is None:
            skipped.append({"folder": folder.name, "reason": "no R0 arm covers this date"})
            continue
        name = str(arm["name"])
        if name not in releases:
            releases[name] = release_loader(
                arm["release_dir"], expected_manifest_sha256=arm["manifest_sha256"], repo_root=repo_root,
            )
        release = releases[name]
        if market_id not in release["markets"]:
            skipped.append({"folder": folder.name, "reason": f"market not in R0 arm {name}"})
            continue
        if market_id not in served_models:
            served_models[market_id] = served_model_factory(market_id=market_id)
        if (name, market_id) not in r0_models:
            r0_models[(name, market_id)] = r0_model_factory(r0_release=release, market_id=market_id)
        served, r0 = served_models[market_id], r0_models[(name, market_id)]
        for record in load_replay_records(folder):
            if is_reconstructed(record) and not include_reconstructed:
                continue
            served_distribution = replay_distribution(served, record)
            r0_distribution = replay_distribution(r0, record)
            if not served_distribution or not r0_distribution:
                continue
            rows.append({
                "kind": "pair",
                "snapshot_id": str(record.get("snapshot_id")),
                "market_id": market_id,
                "target_date": target_date.isoformat(),
                "built_at": record.get("built_at") or record.get("captured_at_local"),
                "arm": name,
                "release_id": release["release_id"],
                "served_distribution": {str(k): v for k, v in sorted(served_distribution.items())},
                "r0_distribution": {str(k): v for k, v in sorted(r0_distribution.items())},
                "l1_r0_vs_served": distribution_l1(r0_distribution, served_distribution),
                "served_identity_hash": replay_identity_hash(served),
                "r0_identity_hash": replay_identity_hash(r0),
                "reconstructed": is_reconstructed(record),
            })
    header = {
        "kind": "header",
        "record": OUTPUT_RECORD,
        "record_version": OUTPUT_RECORD_VERSION,
        "schedule_sha256": schedule["schedule_sha256"],
        "max_target_date": max_target_date.isoformat(),
        "include_reconstructed": bool(include_reconstructed),
        "arms": [
            {
                "name": str(arm["name"]),
                "first_target_date": arm["first"].isoformat(),
                "last_target_date": arm["last"].isoformat(),
                "manifest_sha256": arm["manifest_sha256"],
                "release_id": releases[str(arm["name"])]["release_id"] if str(arm["name"]) in releases else None,
                "candidate_manifest_sha256": (
                    releases[str(arm["name"])]["candidate_manifest_sha256"]
                    if str(arm["name"]) in releases else None
                ),
            }
            for arm in schedule["arms"]
        ],
        "pairs": len(rows),
        "skipped": skipped,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in [header, *rows]:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return header


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paired R0-vs-served replay on captured inputs.")
    parser.add_argument("folders", nargs="+", help="Market-day snapshot folders.")
    parser.add_argument("--schedule", required=True, help="Arm schedule JSON (release per date range).")
    parser.add_argument("--max-target-date", required=True, help="Skip, unopened, any folder after this date.")
    parser.add_argument("--out", required=True, help="New JSONL file (never overwritten).")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--include-reconstructed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    header = run_paired_replay(
        args.folders,
        load_schedule(args.schedule),
        max_target_date=date.fromisoformat(args.max_target_date),
        out_path=args.out,
        repo_root=args.repo_root,
        include_reconstructed=args.include_reconstructed,
    )
    print(json.dumps({key: header[key] for key in ("pairs", "schedule_sha256")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
