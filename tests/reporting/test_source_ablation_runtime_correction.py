from __future__ import annotations

import copy
from pathlib import Path

import pytest

from weather.backtesting.source_ablation_contract import ALL_VARIANTS
from weather.reporting.research import source_ablation_runtime_correction as correction


def _support() -> dict:
    return {
        "variants": [
            {
                "variant": variant,
                "splits": {
                    split: {
                        "supported_snapshot_count": index * 2 + split_index,
                        "supported_snapshot_units_sha256": (
                            f"{index * 2 + split_index + 1:064x}"
                        ),
                    }
                    for split_index, split in enumerate(correction.PAIR_SPLITS)
                },
            }
            for index, variant in enumerate(ALL_VARIANTS)
        ]
    }


def _predecessors() -> dict:
    return {
        "corpus_file_sha256": "1" * 64,
        "corpus_hash": "2" * 64,
        "preregistration_sha256": "3" * 64,
        "support_sha256": "4" * 64,
        "feasibility_sha256": "5" * 64,
        "tune_dates_sha256": "6" * 64,
        "holdout_dates_sha256": "7" * 64,
        "replay_input_manifest_sha256": "8" * 64,
        "replay_input_file_count": 309,
        "pinned_record_count": 44178,
    }


def _fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    helper = repo / correction.HELPER_RELATIVE_PATH
    helper.parent.mkdir(parents=True)
    helper.write_text("CORRECTED = True\n", encoding="utf-8")
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    generation = output_parent / correction.RETRY_GENERATION_LEAF
    support = _support()
    predecessors = _predecessors()
    helper_receipt = correction.stable_file_receipt(helper)
    pairs = correction.expected_support_pairs(support)
    payload = {
        "schema_version": correction.CORRECTION_SCHEMA_VERSION,
        "status": correction.CORRECTION_STATUS,
        "research_only": True,
        "serving_or_release_authorization": False,
        "outcome_use": copy.deepcopy(correction.EXPECTED_OUTCOME_USE),
        "predecessors": copy.deepcopy(predecessors),
        "helper": {
            "relative_path": correction.HELPER_RELATIVE_PATH.as_posix(),
            "pre_fix_sha256": correction.PRE_FIX_HELPER_SHA256,
            "sha256": helper_receipt["sha256"],
            "size_bytes": helper_receipt["size_bytes"],
        },
        "correction": copy.deepcopy(correction.EXPECTED_CORRECTION),
        "all_44_parity": {
            "schema_version": correction.PARITY_SCHEMA_VERSION,
            "order": "ALL_VARIANTS order, then tune and holdout for each variant",
            "pair_count": 44,
            "pairs_sha256": correction.support_pairs_sha256(pairs),
            "pairs": pairs,
            "counters": copy.deepcopy(correction.EXPECTED_PARITY_COUNTERS),
        },
        "failed_attempt": copy.deepcopy(correction.EXPECTED_FAILED_ATTEMPT),
        "retry": copy.deepcopy(correction.EXPECTED_RETRY),
    }
    return repo, support, predecessors, generation, payload


def _validate(repo, support, predecessors, generation, payload):
    return correction.validate_runtime_support_correction(
        payload,
        repo_root=repo,
        support=support,
        predecessor_hashes=predecessors,
        generation_dir=generation,
    )


def test_exact_correction_accepts_44_pairs_and_live_helper(tmp_path):
    repo, support, predecessors, generation, payload = _fixture(tmp_path)

    result = _validate(repo, support, predecessors, generation, payload)

    assert len(result["pairs"]) == 44
    assert result["helper_path"] == (repo / correction.HELPER_RELATIVE_PATH).resolve()
    assert result["failed_generation_path"].name == correction.FAILED_GENERATION_LEAF


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda value: value["outcome_use"].__setitem__("scores_computed", True), "outcome"),
        (lambda value: value["predecessors"].__setitem__("support_sha256", "0" * 64), "predecessor"),
        (lambda value: value["helper"].__setitem__("sha256", "0" * 64), "helper"),
        (lambda value: value["correction"].__setitem__("support_units_changed", True), "diagnosis"),
        (lambda value: value["all_44_parity"]["pairs"].reverse(), "parity"),
        (
            lambda value: value["all_44_parity"]["counters"].__setitem__(
                "corrected_runtime_mismatch_count", 1
            ),
            "counters",
        ),
        (lambda value: value.__setitem__("unexpected", True), "keys differ"),
    ),
)
def test_correction_rejects_any_contract_drift(tmp_path, mutation, match):
    repo, support, predecessors, generation, payload = _fixture(tmp_path)
    mutation(payload)

    with pytest.raises(correction.RuntimeSupportCorrectionError, match=match):
        _validate(repo, support, predecessors, generation, payload)


def test_correction_rejects_wrong_retry_or_materialized_failed_attempt(tmp_path):
    repo, support, predecessors, generation, payload = _fixture(tmp_path)
    wrong = generation.with_name("generation-other")
    with pytest.raises(correction.RuntimeSupportCorrectionError, match="retry"):
        _validate(repo, support, predecessors, wrong, payload)

    failed = generation.with_name(correction.FAILED_GENERATION_LEAF)
    failed.mkdir()
    with pytest.raises(correction.RuntimeSupportCorrectionError, match="now exists"):
        _validate(repo, support, predecessors, generation, payload)
