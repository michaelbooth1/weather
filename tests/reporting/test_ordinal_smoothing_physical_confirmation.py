import hashlib
import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    InvocationSpec,
    PathBinding,
    capture_execution_identity,
)
from weather.market.market_registry import REGISTRY, spec_for_id
from weather.reporting.research import ordinal_smoothing_physical_confirmation as confirmation
from weather.reporting.research.research_generation import ResearchGeneration


def _receipt(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _fixture_layout(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / "src" / "weather" / "owner.py").write_text(
        "OWNER = True\n", encoding="utf-8"
    )
    (repo / "sitecustomize.py").write_text("BOOTSTRAP = True\n", encoding="utf-8")
    (repo / "weather").mkdir()
    (repo / "weather" / "__init__.py").write_text("SHIM = True\n", encoding="utf-8")
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "model.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "markets.yaml").write_text("markets: []\n", encoding="utf-8")

    data = tmp_path / "data"
    snapshots = data / "snapshots"
    snapshots.mkdir(parents=True)
    entries = []
    for date in confirmation.STRICT_DATES:
        for market_id in sorted(REGISTRY):
            slug = f"{market_id}-{date}"
            entry = {
                "market_id": market_id,
                "target_date": date,
                "event_slug": slug,
                "folder_relative_to_snapshots_root": slug,
                "snapshot_ids": [f"{slug}-snapshot"],
            }
            entries.append(entry)
            folder = snapshots / slug
            folder.mkdir()
            (folder / "snapshots.jsonl").write_text("{}\n", encoding="utf-8")
            (folder / "snapshots_long.csv").write_text(
                "snapshot_id\n", encoding="utf-8"
            )
            (folder / "replay_inputs.jsonl").write_text("{}\n", encoding="utf-8")
    for market_id, spec in REGISTRY.items():
        wu = data / "wunderground" / spec.icao.lower()
        (wu / "daily").mkdir(parents=True)
        (wu / "daily" / "daily_summary.csv").write_text(
            "date,max_temp\n", encoding="utf-8"
        )
        hourly = wu / "hourly" / "year=2026" / "month=07"
        hourly.mkdir(parents=True)
        (hourly / "observations.jsonl").write_text("{}\n", encoding="utf-8")

    tune = tmp_path / "gen2-tune"
    tune.mkdir()
    (tune / "COMPLETE.json").write_text('{"status":"COMPLETE"}\n', encoding="utf-8")
    (tune / confirmation.TUNE_RESULT_NAME).write_text(
        '{"status":"COMPLETE"}\n', encoding="utf-8"
    )
    fresh = tmp_path / "fresh.json"
    fresh.write_text('{"entries":[]}\n', encoding="utf-8")
    expected_generation = confirmation._expected_generation_dir(
        tune,
        _receipt(tune / "COMPLETE.json")["sha256"],
        _receipt(fresh)["sha256"],
    )
    monkeypatch.chdir(repo)
    args = Namespace(
        repo_root=str(repo),
        mirror_data_root=str(data),
        staged_data_root=str(data),
        snapshots_root=str(snapshots),
        tune_generation_dir=str(tune),
        fresh_corpus=str(fresh),
        generation_dir=str(expected_generation),
    )
    return args, entries


def _arm(probability_by_date) -> dict:
    rows = []
    distributions = []
    for date in confirmation.STRICT_DATES:
        probability = float(probability_by_date[date])
        for market_id in sorted(REGISTRY):
            unit = str(spec_for_id(market_id).display_unit).upper()
            snapshot_id = f"{market_id}-{date}-snapshot"
            captured = f"{date}T12:00:00-04:00"
            rows.append(
                {
                    "market_id": market_id,
                    "target_date": date,
                    "snapshot_id": snapshot_id,
                    "captured_at_local": captured,
                    "band": "warm",
                    "bin_type": "eq",
                    "bin_value_c": 1.0,
                    "bin_value_hi": 1.0,
                    "replayed_p": probability,
                    "outcome": 1,
                    "market_yes": 0.60,
                    "unit": unit,
                }
            )
            distributions.append(
                {
                    "market_id": market_id,
                    "target_date": date,
                    "snapshot_id": snapshot_id,
                    "captured_at_local": captured,
                    "cutoff_hour": 12,
                    "unit": unit,
                    "distribution": {"0": 1.0 - probability, "1": probability},
                }
            )
    return {
        "partition": "strict-fresh-confirmation",
        "model_graph": "RESEARCH_UNBOUND",
        "rows": rows,
        "distribution_rows": distributions,
        "replay": {
            "snaps_in_corpus": len(rows),
            "snaps_scored": len(rows),
            "total_rows": len(rows),
            "fidelity": {},
            "corpus_warnings": [],
            "blockers": [],
        },
    }


def _constant_arm(probability: float) -> dict:
    return _arm({date: probability for date in confirmation.STRICT_DATES})


def _sealed_tune_generation(tmp_path: Path, *, mutate_result=None) -> Path:
    anchor = tmp_path / "anchor.txt"
    anchor.write_text("anchor\n", encoding="utf-8")
    spec = ClosureSpec(
        name="tune-generation-fixture",
        base_root=tmp_path,
        invocation=InvocationSpec.current(run_parameters={"case": "sealed-tune"}),
        path_bindings=(PathBinding("anchor", anchor),),
        environment=EnvironmentSpec(include_packages=False),
    )
    identity = capture_execution_identity(spec)
    data = tmp_path / "readonly"
    data.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    builder = ResearchGeneration(
        generation_dir=output / "tune",
        read_only_roots=(data,),
        commit_schema_version=confirmation.TUNE_GENERATION_SCHEMA_VERSION,
    )
    parameters = {
        "profile": confirmation.TUNE_PROFILE,
        "schema_version": confirmation.TUNE_SCHEMA_VERSION,
        "model_graph": confirmation.RESEARCH_GRAPH_KIND,
        "research_only": True,
        "active_or_current_production_claimed": False,
        "repo_root": str(tmp_path.resolve()),
        "mirror_data_root": str(data.resolve()),
        "staged_data_root": str(data.resolve()),
        "snapshots_root": str(data.resolve()),
        "tune_corpus": str(anchor.resolve()),
        "tune_dates_file": str(anchor.resolve()),
        "generation_dir": str(builder.generation_dir.resolve(strict=False)),
        "tune_dates": list(confirmation.EXPECTED_TUNE_DATES),
        "tune_dates_file_sha256": confirmation.EXPECTED_TUNE_DATES_FILE_SHA256,
        "tune_corpus_file_sha256": confirmation.EXPECTED_TUNE_CORPUS_FILE_SHA256,
        "tune_corpus_hash": confirmation.EXPECTED_TUNE_CORPUS_HASH,
        "tune_corpus_entry_count": confirmation.EXPECTED_TUNE_ENTRY_COUNT,
        "canary_date": "2026-06-21",
        "physical_c_sigma_anchors": list(confirmation.PHYSICAL_C_SIGMA_ANCHORS),
        "native_mapping": {"C": "x", "F": "1.8*x"},
        "blend_weight": confirmation.FIXED_BLEND_WEIGHT,
        "selection_rule": (
            "negative tune mean paired Brier and log-loss deltas vs fresh W0; "
            "rank by Brier, log-loss, then smaller physical-C sigma"
        ),
        "fresh_manifest_accepted": False,
        "holdout_accepted": False,
        "prior_h1_result_accepted": False,
        "prior_cache_or_resume_accepted": False,
        "full_arms": 6,
        "independent_canary_arms": 1,
    }
    cli = ["fixture"]
    for flag, key in (
        ("--repo-root", "repo_root"),
        ("--mirror-data-root", "mirror_data_root"),
        ("--staged-data-root", "staged_data_root"),
        ("--snapshots-root", "snapshots_root"),
        ("--tune-corpus", "tune_corpus"),
        ("--tune-dates-file", "tune_dates_file"),
        ("--generation-dir", "generation_dir"),
    ):
        cli.extend((flag, parameters[key]))
    identity_payload = json.loads(json.dumps(identity.identity))
    identity_payload["closure_name"] = confirmation.TUNE_PROFILE
    identity_payload["base_root"] = tmp_path.resolve().as_posix()
    identity_payload["invocation"] = {
        "cwd": tmp_path.resolve().as_posix(),
        "argv": cli,
        "run_parameters": parameters,
    }
    identity = type(identity)(
        identity=identity_payload,
        identity_digest=confirmation._digest(identity_payload),
    )
    pass_gate = {"status": "PASS", "blockers": []}
    summaries = {"C": [], "F": []}
    for unit, target in (("C", 0.75), ("F", 1.25)):
        for value in confirmation.PHYSICAL_C_SIGMA_ANCHORS:
            score = -0.10 + abs(value - target) * 0.01
            summaries[unit].append(
                {
                    "unit": unit,
                    "physical_c_sigma": value,
                    "native_sigma": confirmation.native_sigma(value, unit),
                    "blend_weight": confirmation.FIXED_BLEND_WEIGHT,
                    "mean_brier_delta_vs_w0": score,
                    "mean_logloss_delta_vs_w0": score,
                }
            )
    selected, selection = confirmation.select_family_sigmas(summaries)
    terminal_seals = {
        "tune_corpus": {"sha256": confirmation.EXPECTED_TUNE_CORPUS_FILE_SHA256},
        "tune_dates": {"sha256": confirmation.EXPECTED_TUNE_DATES_FILE_SHA256},
        "sitecustomize": {"sha256": "b" * 64},
        "weather_import_shim": {"sha256": "c" * 64},
        "design": {
            "profile": confirmation.TUNE_PROFILE,
            "sha256": confirmation._digest(parameters),
        },
    }
    with builder as generation:
        cache_records = []

        def publish_cache(name, kind):
            receipt = generation.publish_json(name, {"sealed": True, "kind": kind}, compact=True)
            record = {
                **receipt,
                "fingerprint": hashlib.sha256(name.encode()).hexdigest(),
                "arm_contract": {"kind": kind},
                "gate": dict(pass_gate),
                "identity_gates": {
                    "pre_arm_digest": identity.identity_digest,
                    "post_arm_digest": identity.identity_digest,
                    "pre_cache": identity.to_dict(),
                    "post_cache": identity.to_dict(),
                    "identical_full_manifest": True,
                },
            }
            cache_records.append(record)
            return record

        baseline = publish_cache("cache/tune-fresh-w0.json", "fresh_w0")
        canary = publish_cache(
            "cache/tune-fresh-w0-canary.json", "independent_w0_canary"
        )
        arm_gates = {}
        for value in confirmation.PHYSICAL_C_SIGMA_ANCHORS:
            name = "cache/tune-physical-c-" + f"{value:.2f}".replace(".", "p") + ".json"
            record = publish_cache(name, "physical_candidate")
            arm_gates[str(value)] = {**pass_gate, "cache_sha256": record["sha256"]}
        result = {
            "schema_version": confirmation.TUNE_SCHEMA_VERSION,
            "status": "COMPLETE",
            "disposition": "FROZEN_FOR_ONE_SHOT_STRICT_CONFIRMATION",
            "research_only": True,
            "promotion_authorized": False,
            "serving_changed": False,
            "holdout_opened": False,
            "fresh_panel_opened": False,
            "prior_h1_result_or_cache_used": False,
            "model_graph": confirmation.RESEARCH_GRAPH_KIND,
            "active_or_current_production_claimed": False,
            "profile_gate": dict(pass_gate),
            "experiment": {
                **parameters,
                "design_digest": confirmation._digest(parameters),
                "runtime_seconds": 0.0,
                "tune_market_days": confirmation.EXPECTED_TUNE_ENTRY_COUNT,
            },
            "terminal_seals": terminal_seals,
            "lineage": {
                "model_graph": confirmation.RESEARCH_GRAPH_KIND,
                "execution_identity_digest": identity.identity_digest,
                "current_release_pointers": [
                    {"path": "first", "state": "absent"},
                    {"path": "second", "state": "absent"},
                ],
                "active_or_current_production_claimed": False,
            },
            "execution_identity": {
                "start": identity.to_dict(),
                "completion": identity.to_dict(),
                "identical_full_manifest": True,
            },
            "baseline_gate": dict(pass_gate),
            "canary_gate": {**pass_gate, "cache_sha256": canary["sha256"]},
            "arm_gates": arm_gates,
            "summaries": summaries,
            "selection": selection,
            "selected_physical_c_sigmas": selected,
            "frozen_candidate": {
                "status": "FROZEN",
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: confirmation.native_sigma(selected[unit], unit)
                    for unit in ("C", "F")
                },
                "blend_weight": confirmation.FIXED_BLEND_WEIGHT,
                "selection_uses_tune_only": True,
                "confirmation_runs_completed": 0,
                "one_shot_confirmation_authorized": True,
                "promotion_authorized": False,
            },
            "cache_records": cache_records,
            "generation_contract": {
                "complete_marker": "COMPLETE.json",
                "multi_leaf_atomic_transaction_claimed": False,
                "prior_generation_reuse": False,
            },
            "technical_blockers": [],
        }
        if mutate_result is not None:
            mutate_result(result)
        generation.publish_json(confirmation.TUNE_RESULT_NAME, result)
        generation.publish_text(confirmation.TUNE_REPORT_NAME, "# sealed tune\n")
        generation.commit(
            start=identity,
            expected_completion=identity,
            terminal_recapture=lambda: identity,
            terminal_seals=terminal_seals,
            extra={
                "profile": confirmation.TUNE_PROFILE,
                "model_graph": confirmation.RESEARCH_GRAPH_KIND,
                "result": confirmation.TUNE_RESULT_NAME,
                "report": confirmation.TUNE_REPORT_NAME,
                "selected_physical_c_sigmas": result[
                    "selected_physical_c_sigmas"
                ],
                "one_shot_confirmation_authorized": True,
            },
        )
    return builder.generation_dir


def test_parser_is_a_one_shot_firewall():
    destinations = {action.dest for action in confirmation.build_parser()._actions}
    assert destinations == {
        "help",
        "repo_root",
        "mirror_data_root",
        "staged_data_root",
        "snapshots_root",
        "tune_generation_dir",
        "fresh_corpus",
        "generation_dir",
    }
    assert not any(
        token in destination
        for destination in destinations
        for token in ("date", "candidate", "anchor", "grid", "resume", "cache")
    )


def test_generation_path_is_deterministic_from_terminal_seals(tmp_path):
    tune = tmp_path / "tune"
    tune.mkdir()
    first = confirmation._expected_generation_dir(tune, "a" * 64, "b" * 64)
    second = confirmation._expected_generation_dir(tune, "a" * 64, "c" * 64)
    assert first.name == "physical-confirmation-aaaaaaaaaaaa-bbbbbbbbbbbb"
    assert first != second


def test_sealed_tune_validation_streams_output_hashing_and_detects_drift(
    tmp_path, monkeypatch
):
    generation = _sealed_tune_generation(tmp_path)
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_identity_semantics",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    original = confirmation._stable_file
    calls = []

    def observed(path, **kwargs):
        calls.append((Path(path).name, kwargs.get("capture", True)))
        return original(path, **kwargs)

    monkeypatch.setattr(confirmation, "_stable_file", observed)
    result, receipts = confirmation._validate_tune_generation(
        generation, verify_all_outputs=True
    )
    assert result["status"] == "COMPLETE"
    assert receipts["selected_physical_c_sigmas"] == {"C": 0.75, "F": 1.25}
    assert ("tune-fresh-w0.json", False) in calls

    (generation / "cache" / "tune-fresh-w0.json").write_text(
        '{"sealed":false}\n', encoding="utf-8"
    )
    with pytest.raises(confirmation.ConfirmationError, match="hash mismatch"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_recomputes_selection_and_rejects_synchronized_forgery(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_identity_semantics",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    def forge(result):
        result["selected_physical_c_sigmas"] = {"C": 1.25, "F": 1.25}
        result["frozen_candidate"]["physical_c_sigma_by_family"] = {
            "C": 1.25,
            "F": 1.25,
        }
        result["frozen_candidate"]["native_sigma_by_family"] = {
            "C": 1.25,
            "F": 2.25,
        }

    generation = _sealed_tune_generation(tmp_path, mutate_result=forge)
    with pytest.raises(confirmation.ConfirmationError, match="reproduce from summaries"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_rejects_blocked_gate_even_when_generation_is_self_consistent(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_identity_semantics",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    def block(result):
        result["baseline_gate"] = {"status": "BLOCK", "blockers": ["forced"]}

    generation = _sealed_tune_generation(tmp_path, mutate_result=block)
    with pytest.raises(confirmation.ConfirmationError, match="primary gates"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_rejects_result_commit_terminal_seal_divergence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_identity_semantics",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    def diverge(result):
        result["terminal_seals"] = dict(result["terminal_seals"])
        result["terminal_seals"]["design"] = {
            "profile": confirmation.TUNE_PROFILE,
            "sha256": "e" * 64,
        }

    generation = _sealed_tune_generation(tmp_path, mutate_result=diverge)
    with pytest.raises(confirmation.ConfirmationError, match="terminal seals"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_rejects_nested_fake_complete_leaf(tmp_path, monkeypatch):
    generation = _sealed_tune_generation(tmp_path)
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_identity_semantics",
        lambda *args, **kwargs: {"status": "PASS"},
    )
    (generation / "cache" / "COMPLETE.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(confirmation.ConfirmationError, match="fixed leaves"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_rejects_self_consistent_but_semantically_weak_closure(tmp_path):
    generation = _sealed_tune_generation(tmp_path)
    with pytest.raises(confirmation.ConfirmationError, match="required source/contract"):
        confirmation._validate_tune_generation(generation, verify_all_outputs=True)


def test_tune_handoff_rejects_byte_identical_generation_copy(tmp_path):
    generation = _sealed_tune_generation(tmp_path)
    copied = tmp_path / "copied-parent" / "copied-tune"
    copied.parent.mkdir()
    shutil.copytree(generation, copied)
    with pytest.raises(
        confirmation.ConfirmationError,
        match="base, cwd, profile, or generation path",
    ):
        confirmation._validate_tune_generation(copied, verify_all_outputs=True)


def test_decision_rule_covers_supported_directional_and_not_supported():
    baseline = _constant_arm(0.40)
    selected = {"C": 0.75, "F": 1.25}

    _, _, supported = confirmation._candidate_analysis(
        baseline, _constant_arm(0.50), selected
    )
    assert supported == {"C": "SUPPORTED", "F": "SUPPORTED"}

    directional_probabilities = {
        confirmation.STRICT_DATES[0]: 0.20,
        **{date: 0.50 for date in confirmation.STRICT_DATES[1:]},
    }
    _, _, directional = confirmation._candidate_analysis(
        baseline, _arm(directional_probabilities), selected
    )
    assert directional == {"C": "DIRECTIONAL_ONLY", "F": "DIRECTIONAL_ONLY"}

    _, _, unsupported = confirmation._candidate_analysis(
        baseline, _constant_arm(0.30), selected
    )
    assert unsupported == {"C": "NOT_SUPPORTED", "F": "NOT_SUPPORTED"}


def test_failed_read_only_preflight_does_not_consume_one_shot(
    tmp_path, monkeypatch
):
    args, _ = _fixture_layout(tmp_path, monkeypatch)
    receipts = {
        "complete": _receipt(Path(args.tune_generation_dir) / "COMPLETE.json"),
        "result": _receipt(
            Path(args.tune_generation_dir) / confirmation.TUNE_RESULT_NAME
        ),
        "selected_physical_c_sigmas": {"C": 0.75, "F": 1.25},
    }
    monkeypatch.setattr(
        confirmation,
        "_validate_tune_generation",
        lambda *args, **kwargs: (
            {"selected_physical_c_sigmas": {"C": 0.75, "F": 1.25}},
            receipts,
        ),
    )
    monkeypatch.setattr(confirmation, "configure_staged_data_root", lambda path: None)
    monkeypatch.setattr(
        confirmation,
        "_strict_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            confirmation.ConfirmationError("fresh audit stopped")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "confirmation-fixture",
            "--repo-root",
            str(Path(args.repo_root).resolve()),
            "--mirror-data-root",
            str(Path(args.mirror_data_root).resolve()),
            "--staged-data-root",
            str(Path(args.staged_data_root).resolve()),
            "--snapshots-root",
            str(Path(args.snapshots_root).resolve()),
            "--tune-generation-dir",
            str(Path(args.tune_generation_dir).resolve()),
            "--fresh-corpus",
            str(Path(args.fresh_corpus).resolve()),
            "--generation-dir",
            str(Path(args.generation_dir).resolve()),
        ],
    )
    with pytest.raises(confirmation.ConfirmationError, match="fresh audit stopped"):
        confirmation.run_confirmation(args)
    marker = Path(args.generation_dir).with_name(
        Path(args.generation_dir).name + ".ATTEMPT.json"
    )
    assert not marker.exists()
    assert not Path(args.generation_dir).exists()


def test_synthetic_one_shot_generation_runs_exactly_two_arms(tmp_path, monkeypatch):
    args, entries = _fixture_layout(tmp_path, monkeypatch)
    tune_complete = _receipt(Path(args.tune_generation_dir) / "COMPLETE.json")
    tune_result_receipt = _receipt(
        Path(args.tune_generation_dir) / confirmation.TUNE_RESULT_NAME
    )
    fresh_receipt = _receipt(Path(args.fresh_corpus))
    selected = {"C": 0.75, "F": 1.25}
    tune_payload = {"selected_physical_c_sigmas": dict(selected)}
    tune_receipts = {
        "complete": tune_complete,
        "result": tune_result_receipt,
        "selected_physical_c_sigmas": dict(selected),
    }
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "source_corpus_hash": "fixture-fresh-corpus",
        "entries": entries,
        "skipped": [],
    }
    panel_evidence = {
        "manifest": fresh_receipt,
        "panel": [
            {"target_date": date, "strict_confirmation_eligible": True}
            for date in confirmation.STRICT_DATES
        ],
        "verification": {"verification_warning_count": 0},
    }
    tune_calls = []

    def fake_tune(path, *, verify_all_outputs):
        tune_calls.append(verify_all_outputs)
        return json.loads(json.dumps(tune_payload)), json.loads(json.dumps(tune_receipts))

    def fake_manifest(path, snapshots_root):
        return (
            json.loads(json.dumps(manifest)),
            json.loads(json.dumps(entries)),
            json.loads(json.dumps(panel_evidence)),
        )

    monkeypatch.setattr(confirmation, "_validate_tune_generation", fake_tune)
    monkeypatch.setattr(confirmation, "_strict_manifest", fake_manifest)
    monkeypatch.setattr(confirmation, "configure_staged_data_root", lambda path: None)
    monkeypatch.setattr(
        confirmation, "validate_staged_daily_inputs", lambda entries, root: None
    )
    arm_calls = []

    def fake_run_partition_arm(**kwargs):
        arm_calls.append(
            (kwargs["arm_name"], kwargs["physical_c_sigma_by_family"])
        )
        return (
            _constant_arm(0.40)
            if kwargs["physical_c_sigma_by_family"] is None
            else _constant_arm(0.50)
        )

    monkeypatch.setattr(confirmation, "run_partition_arm", fake_run_partition_arm)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "confirmation-fixture",
            "--repo-root",
            str(Path(args.repo_root).resolve()),
            "--mirror-data-root",
            str(Path(args.mirror_data_root).resolve()),
            "--staged-data-root",
            str(Path(args.staged_data_root).resolve()),
            "--snapshots-root",
            str(Path(args.snapshots_root).resolve()),
            "--tune-generation-dir",
            str(Path(args.tune_generation_dir).resolve()),
            "--fresh-corpus",
            str(Path(args.fresh_corpus).resolve()),
            "--generation-dir",
            str(Path(args.generation_dir).resolve()),
        ],
    )
    payload, commit = confirmation.run_confirmation(args)

    assert tune_calls == [True, False]
    assert arm_calls == [
        ("fresh-w0", None),
        ("single-mixed-family-candidate", selected),
    ]
    assert payload["one_shot"]["fresh_w0_arms"] == 1
    assert payload["one_shot"]["candidate_arms"] == 1
    assert payload["one_shot"]["alternative_candidates_scored"] == 0
    assert payload["one_shot"]["reselection_performed"] is False
    attempt_marker = Path(args.generation_dir).with_name(
        Path(args.generation_dir).name + ".ATTEMPT.json"
    )
    assert attempt_marker.is_file()
    assert payload["one_shot"]["attempt_marker"]["sha256"] == hashlib.sha256(
        attempt_marker.read_bytes()
    ).hexdigest()
    assert payload["dispositions"] == {"C": "SUPPORTED", "F": "SUPPORTED"}
    assert payload["closure_profile_gate"]["status"] == "PASS"
    labels = {
        row["label"] for row in payload["execution_identity"]["start"]["identity"]["bindings"]
    }
    assert "contract:sitecustomize" in labels
    assert "contract:weather_import_shim" in labels
    assert len(payload["cache_records"]) == 2
    baseline_record, candidate_record = payload["cache_records"]
    assert baseline_record["fresh_w0_cache_sha256"] is None
    assert candidate_record["fresh_w0_cache_sha256"] == baseline_record["sha256"]
    assert payload["tune_candidate"]["reselected_after_fresh_scores"] is False
    assert payload["promotion_authorized"] is False
    assert commit["status"] == "COMPLETE"
    assert (Path(args.generation_dir) / "COMPLETE.json").is_file()
    assert len([row for row in commit["outputs"] if row["name"].startswith("cache/")]) == 2
    with pytest.raises(confirmation.ConfirmationError, match="already consumed"):
        confirmation.validate_paths(args)


def test_schemas_are_registered():
    assert confirmation.SCHEMA_VERSION == "ordinal_smoothing_physical_confirmation_v0.1"
    assert (
        confirmation.GENERATION_SCHEMA_VERSION
        == "ordinal_smoothing_physical_confirmation_generation_commit_v0.1"
    )
