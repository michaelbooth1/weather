"""Build exact existing phase contracts from already verified metadata."""
from pathlib import Path
from weather.operations import production_cold_archive_stage as archive
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_campaign_review as review
from weather.schema_registry import schema_version


class Requests:
    def __init__(self, config, archive_id, chunk):
        self.config, self.aid, self.chunk = config, archive_id, chunk
        self.root = Path(config["production_root"])
        self.ws = config["workstation_root"].rstrip("/")
        self.meta = self.root / "scratch" / "ac-control" / config["campaign_id"] / archive_id
        if not self.meta.exists():
            self.meta.mkdir()
        self.stage = self.root / "scratch" / "production_cold_archive" / (archive_id + "s1") / "stage"
        self.ws_in = self.ws + "/scratch/ac-in/" + archive_id

    def base(self):
        c = self.config
        return {
            "schema_version": schema_version("production_cold_archive_request"),
            "production_repo_root": str(self.root), "execution_host_id": c["execution_host_id"],
            "operation": "stage_only", "approved_by": c["approved_by"],
            "approved_at_utc": c["approved_at_utc"], "expires_at_utc": c["expires_at_utc"],
            "plan_path": c["plan"]["path"], "plan_sha256": c["plan"]["sha256"],
            "chunk_id": self.chunk["chunk_id"], "source_git_sha": c["production_source_tip"]}

    def production_evidence(self):
        result = {}
        for field, path in (("production_manifest", self.stage / "manifest.json"),
                            ("production_receipt", self.stage / "receipt.json")):
            item = io.spec(path)
            result[field + "_path"], result[field + "_sha256"] = item["path"], item["sha256"]
        return result

    def copy(self):
        c = self.config
        manifest = archive._load(self.stage / "manifest.json")[0]
        result = {**self.base(), **self.production_evidence(),
                  "schema_version": schema_version("production_cold_archive_copy_request"),
                  "operation": "copy", "direction": "to_workstation", "archive_id": self.aid,
                  "workstation_root": self.ws}
        for key in ("remote_host", "remote_user", "private_key", "known_hosts", "known_hosts_sha256",
                    "ssh_executable", "scp_executable"):
            result[key] = c[key]
        result["files"] = []
        for name in ("archive.tar.gz", "manifest.json", "receipt.json"):
            path = self.stage / name
            sha = manifest["archive_sha256"] if name == "archive.tar.gz" else io.spec(path)["sha256"]
            result["files"].append({"local": str(path), "remote": self.ws_in + "/" + name,
                                    "bytes": path.stat().st_size, "sha256": sha})
        return result

    def publish(self, crypt, uploaded):
        return {**self.base(), **self.production_evidence(),
                "schema_version": schema_version("production_cold_archive_transfer_request"),
                "operation": "publish_uploaded", "archive_id": self.aid,
                "drive_root_folder_id": self.config["drive_root_folder_id"],
                "crypt_receipt_path": crypt["path"], "crypt_receipt_sha256": crypt["sha256"],
                "upload_receipt_path": uploaded["path"], "upload_receipt_sha256": uploaded["sha256"],
                "publish_catalog": True}

    def reclaim(self, entry, restored, custody):
        entry_value = io.load_spec(entry)
        reviewed = review.review_sources(
            production_root=self.root, entry=entry_value, entry_sha256=entry["sha256"],
            output_root=self.meta / "source-review")
        stage_path = self.stage / "archive.tar.gz"
        manifest = archive._load(self.stage / "manifest.json")[0]
        with bridge._file_pin(stage_path) as pin:
            identity = pin.metadata()
        inventory = archive._seal({
            "schema_version": schema_version("cold_archive_spool_inventory"),
            "archive_id": self.aid, "entry_sha256": entry["sha256"],
            "files": [{"role": "staged_archive", "path": stage_path.relative_to(self.root).as_posix(),
                       "sha256": manifest["archive_sha256"], **identity}]}, "receipt_hash")
        archive._write(self.meta / "spool-inventory.json", inventory)
        request = {key: value for key, value in self.base().items()
                   if key not in {"plan_path", "plan_sha256", "chunk_id"}}
        request.update(
            schema_version=schema_version("production_cold_archive_reclaim_request"), operation="reclaim",
            attempt_id=self.aid + "r1", catalog_entry={k: entry[k] for k in ("path", "sha256")},
            source_review=reviewed, restore_record={k: restored[k] for k in ("path", "sha256")},
            custody_record={k: custody[k] for k in ("path", "sha256")},
            spool_inventory=io.spec(self.meta / "spool-inventory.json"))
        for name in ("owner_approval", "proposal", "selection", "plan"):
            request[name] = self.config[name]
        return request
