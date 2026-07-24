import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import weather.reporting.source_gates.source_artifact_binding as artifact_binding
from weather.reporting.source_gates.source_artifact_binding import (
    collect_artifact_feature_names,
    receipt_shape_contract,
    stable_artifact,
    stable_json_artifact,
    verify_current_active_release_binding,
    verify_current_artifact,
    verify_current_json_artifact,
)
from weather.release_artifacts import pointer_content_sha256
from tests.reporting.source_family_contract_fixtures import (
    operational_ablation_payload,
    write_active_release_identity,
)


def test_stable_json_receipt_revalidates_and_detects_replacement(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    payload, receipt = stable_json_artifact(path)

    assert payload == {"status": "PASS"}
    assert receipt_shape_contract(receipt)["status"] == "PASS"
    assert verify_current_json_artifact(receipt)["status"] == "PASS"

    path.write_text(json.dumps({"status": "BLOCK"}), encoding="utf-8")
    result = verify_current_json_artifact(receipt)
    assert result["status"] == "BLOCK"
    assert any("sha256 differs" in value for value in result["blockers"])


def test_stable_json_receipt_rejects_in_read_replacement(tmp_path, monkeypatch):
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    original_open = Path.open

    class ReplaceAfterRead:
        def __init__(self, handle, target):
            self._handle = handle
            self._target = target

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *args):
            return self._handle.__exit__(*args)

        def fileno(self):
            return self._handle.fileno()

        def read(self, *args, **kwargs):
            raw = self._handle.read(*args, **kwargs)
            with original_open(self._target, "ab") as replacement:
                replacement.write(b" ")
            return raw

    def replace_after_read(candidate, *args, **kwargs):
        handle = original_open(candidate, *args, **kwargs)
        if candidate == path.resolve() and args and args[0] == "rb":
            return ReplaceAfterRead(handle, candidate)
        return handle

    monkeypatch.setattr(Path, "open", replace_after_read)

    payload, receipt = stable_json_artifact(path)

    assert payload == {}
    assert receipt["status"] == "BLOCK"
    assert any("changed during stable read" in value for value in receipt["blockers"])


def test_stable_json_rejects_duplicate_keys_and_nonfinite_values(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"status":"PASS","status":"BLOCK"}', encoding="utf-8")
    payload, receipt = stable_json_artifact(path)
    assert payload == {}
    assert receipt["status"] == "BLOCK"
    assert any("duplicate JSON key" in value for value in receipt["blockers"])

    path.write_text('{"delta":NaN}', encoding="utf-8")
    payload, receipt = stable_json_artifact(path)
    assert payload == {}
    assert receipt["status"] == "BLOCK"
    assert any("non-finite JSON constant" in value for value in receipt["blockers"])

    path.write_text('{"delta":1e400}', encoding="utf-8")
    payload, receipt = stable_json_artifact(path)
    assert payload == {}
    assert receipt["status"] == "BLOCK"
    assert any("out-of-range non-finite" in value for value in receipt["blockers"])


def test_receipt_shape_requires_complete_pass_receipt():
    result = receipt_shape_contract(
        {"status": "PASS", "path": "artifact.json", "sha256": "bad"}
    )
    assert result["status"] == "BLOCK"
    assert any("sha256" in value for value in result["blockers"])
    assert any("size_bytes" in value for value in result["blockers"])


def test_binary_receipt_detects_same_size_replacement(tmp_path):
    path = tmp_path / "candidate.pkl"
    path.write_bytes(b"aaaa")
    _raw, receipt = stable_artifact(path)

    path.write_bytes(b"bbbb")

    result = verify_current_artifact(receipt, label="candidate artifact")
    assert result["status"] == "BLOCK"
    assert any("sha256 differs" in value for value in result["blockers"])


def test_feature_imputer_statistics_length_mismatch_fails_closed():
    artifact = {
        "models": {
            "12": {
                "feature_names": ["forecast_high", "nws_grid_high"],
                "imputer": SimpleNamespace(statistics_=[80.0]),
            }
        }
    }

    with pytest.raises(ValueError, match="statistics length mismatch"):
        collect_artifact_feature_names(artifact)


def test_active_release_binding_blocks_pointer_advancement(tmp_path):
    ablation = operational_ablation_payload([{"variant": "open_meteo"}])
    pointer_path = write_active_release_identity(tmp_path, ablation)

    assert verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )["status"] == "PASS"

    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["active_release_id"] = "advanced-release"
    pointer["active_manifest_sha256"] = "a" * 64
    pointer["pointer_sha256"] = pointer_content_sha256(pointer)
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    result = verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )
    assert result["status"] == "BLOCK"
    assert any(
        "canonical trusted serving verification" in value
        for value in result["blockers"]
    )


def test_active_release_binding_rehashes_every_manifest_artifact(tmp_path):
    ablation = operational_ablation_payload([{"variant": "open_meteo"}])
    pointer_path = write_active_release_identity(tmp_path, ablation)
    initial = verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )
    assert initial["status"] == "PASS"
    artifact_path = Path(initial["serving_model"]["path"])
    artifact_path.write_bytes(b"mutated-without-manifest-update")

    result = verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )

    assert result["status"] == "BLOCK"
    assert any(
        "canonical trusted serving verification" in value
        for value in result["blockers"]
    )


def test_active_release_binding_compares_re_read_manifest_bytes_to_bundle(
    tmp_path,
    monkeypatch,
):
    ablation = operational_ablation_payload([{"variant": "open_meteo"}])
    pointer_path = write_active_release_identity(tmp_path, ablation)
    original = artifact_binding.stable_json_artifact

    def forged_manifest_receipt(path):
        payload, receipt = original(path)
        if Path(path).name == "release_manifest.json":
            receipt = {**receipt, "sha256": "0" * 64}
        return payload, receipt

    monkeypatch.setattr(
        artifact_binding,
        "stable_json_artifact",
        forged_manifest_receipt,
    )

    result = verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )

    assert result["status"] == "BLOCK"
    assert any(
        "manifest bytes changed" in value for value in result["blockers"]
    )
