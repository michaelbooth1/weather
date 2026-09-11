"""Every generated workstation phase must parse through its actual public CLI."""
import json
from pathlib import Path
import pytest
from weather.operations import cold_archive_campaign_steps as steps
from weather.operations import cold_archive_campaign_io as io
from weather.operations import bulk_cold_archive_crypt as crypt
from weather.operations import workstation_cold_archive_stage as stage
from weather.operations import workstation_cold_archive_restore as restore
from weather.operations import workstation_cold_archive_transfer as transfer
from weather.operations import workstation_cold_archive_cleanup as cleanup
from weather.operations import workstation_cold_archive_backup as backup
from weather.operations import cold_archive_recovery_publication as publication


@pytest.fixture
def adapter(tmp_path):
    cfg = dict(production_root=str(tmp_path), campaign_id="fixture", workstation_root="C:/remote",
               workstation_source_tip="a" * 40, plan={"sha256": "b" * 64},
               rclone_executable="C:/private/rclone.exe", crypt_config="C:/private/crypt.conf",
               crypt_secret="C:/private/crypt.dpapi", crypt_remote_name="crypt",
               ciphertext_root="C:/remote/scratch/production_cold_archive_ciphertext/fixture",
               drive_remote_name="drive", drive_root_folder_id="private_root_1234",
               drive_config="C:/private/drive.conf", drive_secret="C:/private/drive.dpapi",
               key_custody={"path": "C:/remote/scratch/ac-in/key-custody.json", "sha256": "c" * 64},
               workstation_python="C:/python/python.exe")
    (tmp_path / "scratch/ac-control/fixture").mkdir(parents=True)
    obj = steps.Steps(cfg, "archive001", {"chunk_id": "chunk-00003"}, None)
    obj.requests.stage.mkdir(parents=True)
    for name in ("manifest.json", "receipt.json"):
        (obj.requests.stage / name).write_text("{}")
    completed = {}
    for phase in steps.REMOTE_PHASES | {"publish"}:
        value = {"status": "PASS"}
        if phase == "encrypt":
            value["ciphertext"] = {"path_relative_to_ciphertext_root": "d/o"}
        if phase == "recovery":
            value.update({name: {"path": "C:/remote/scratch/ac-in/archive001/" + name + ".json",
                                "sha256": "d" * 64} for name in ("catalog_entry", "restore_record", "custody_record")})
        path = obj.meta / (phase + ".json"); path.write_text(json.dumps(value))
        completed[phase] = {"evidence": {"documents": {"result": io.spec(path), "entry": io.spec(path)}}}
    (obj.meta / "recovery-bundle.json").write_text("{}")
    return obj, completed


@pytest.mark.parametrize("phase", sorted(steps.REMOTE_PHASES))
def test_generated_arguments_parse_through_canonical_entrypoints(adapter, monkeypatch, phase):
    obj, completed = adapter
    seen = []
    def result(*args, **kwargs):
        seen.append((args, kwargs))
        return dict(status="PASS", archive_id="archive001", attempt_id="a1", receipt_hash="a" * 64,
                    receipt_path="receipt.json", receipt_sha256="b" * 64, bundle_sha256="c" * 64,
                    deleted_files=1, removed_allocated_bytes=1,
                    catalog_entry={}, restore_record={}, custody_record={})
    monkeypatch.setattr(crypt, "run", result)
    monkeypatch.setattr(transfer, "run", result)
    monkeypatch.setattr(cleanup, "run_cleanup", result)
    monkeypatch.setattr(publication, "run_publication", result)
    monkeypatch.setattr(backup, "run", result)
    request, output = obj.remote_spec(phase, completed)
    args = request["arguments"]
    tokens = [arg for arg in args[2:] if arg != "--archive-unattended"]
    entrypoint = stage.main if args[1].endswith("_stage") else restore.main
    assert entrypoint(tokens) == 0
    assert len(seen) == 1
    assert output.endswith("/receipt.json")
    assert request["seconds"] == steps.LIMITS[phase] + 15


def test_wrong_remote_completion_request_is_rejected(adapter, monkeypatch):
    obj, completed = adapter
    request, _ = obj.remote_spec("upload", completed)
    job = obj.meta / "fake-job.json"
    job.write_text(json.dumps({"status": "PASS", "request_sha256": "0" * 64}))
    class Transport:
        def read_remote(self, *args, **kwargs):
            return io.spec(job)
    obj.transport = Transport()
    with pytest.raises(ValueError, match="request differs"):
        obj.collect("upload", completed)
