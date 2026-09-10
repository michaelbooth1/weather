"""One workstation-first archive batch through qualified repository owners."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
from functools import partial
import json
import hashlib
from pathlib import Path
import time

from weather.operations import production_cold_archive_stage as archive
from weather.operations import production_cold_archive_stage_cli as staging
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_campaign_state as state
from weather.operations import cold_archive_campaign_reconcile as reconcile
from weather.operations.cold_archive_campaign_requests import Requests

LIMITS = {"stage": 300, "copy": 300, "encrypt": 600, "upload": 900, "download": 900,
          "restore": 600, "publish": 300, "recovery": 60, "workstation_cleanup": 600,
          "reclaim": 300, "backup": 180}
REMOTE_PHASES = {"encrypt", "upload", "download", "restore", "recovery", "workstation_cleanup", "backup"}


def flags(module, mode, values, positional=()):
    result = ["-m", "weather.operations." + module, mode, "--archive-unattended", *positional]
    for key, value in values.items():
        if value is not None:
            result.extend(["--" + key.replace("_", "-"), str(value)])
    return result


class Steps:
    def __init__(self, config, archive_id, chunk, transport):
        self.config, self.aid, self.chunk, self.transport = config, archive_id, chunk, transport
        self.requests = Requests(config, archive_id, chunk)
        self.meta, self.root, self.ws = self.requests.meta, self.requests.root, self.requests.ws
        self.campaign = config["campaign_id"]

    def doc(self, completed, phase, name="result"):
        return completed[phase]["evidence"]["documents"][name]

    def value(self, completed, phase, name="result"):
        return io.load_spec(self.doc(completed, phase, name))

    def admit(self, phase, completed):
        window = state.active_window(self.config, datetime.now(timezone.utc))
        if phase in REMOTE_PHASES or phase == "backup":
            return
        plan, reserve = staging.load_plan_with_reserve(
            Path(self.config["plan"]["path"]), self.config["plan"]["sha256"],
            owner_approved_exception=window["owner_exception"])
        gate = staging.resource_policy.AdmissionStartWindow()
        end = time.monotonic() + staging.resource_policy.MAX_ADMISSION_WAIT_SECONDS
        while time.monotonic() < end:
            if (self.meta.parent / "STOP").exists():
                raise state.CampaignPaused("stop requested during admission wait")
            if datetime.now(timezone.utc) >= staging._utc(self.config["expires_at_utc"]):
                raise state.CampaignPaused("campaign authority window ended before admission")
            window = state.active_window(self.config, datetime.now(timezone.utc))
            observed = staging.observe_capture_admission(
                self.root, partial(staging.check_resources, output_reservation=0,
                                   source_reserve_bytes=reserve,
                                   owner_approved_exception=window["owner_exception"]),
                memory_reader=staging.resource_policy.read_host_memory)
            if gate.observe(observed):
                return
            time.sleep(staging.resource_policy.START_SAMPLE_SECONDS)
        raise state.CampaignPaused("capture admission remains unavailable; no phase was started")

    def verify(self, phase, evidence):
        if evidence.get("phase") != phase or not isinstance(evidence.get("documents"), dict):
            raise ValueError("phase evidence binding differs")
        documents = {name: io.load_spec(spec) for name, spec in evidence["documents"].items()}
        proof = documents["job" if phase in REMOTE_PHASES else "wrapper"]
        if proof.get("teardown_proved") is not True:
            raise state.CampaignPaused("phase child-tree teardown is not proved")
        if phase == "reclaim" and "reconciliation" in documents:
            checked = reconcile.committed_reclaim(
                wrapper=evidence["documents"]["wrapper"], receipt=evidence["documents"]["reclaim"],
                progress=evidence["documents"]["progress"]["path"], entry_sha256=documents["reclaim"]["entry_sha256"],
                archive_id=self.aid, approval_sha256=self.config["owner_approval"]["sha256"],
                production_root=self.root)
            if not all(documents["reconciliation"].get(key) == value for key, value in checked.items()):
                raise ValueError("reclaim reconciliation binding differs")
        elif proof.get("status") != "PASS":
            raise state.CampaignPaused("phase completion is not proved")
        if phase in REMOTE_PHASES:
            if proof.get("source_tip") != self.config["workstation_source_tip"]:
                raise ValueError("remote source tip differs")
            result = documents["result"]
            expected = "PUBLISHED_RECOVERY" if phase == "recovery" else "PASS"
            if result.get("status") != expected:
                raise state.CampaignPaused("phase result is not qualified")
            if phase not in {"workstation_cleanup", "backup"} and result.get("archive_id") != self.aid:
                raise ValueError("phase archive identity differs")
            if phase in {"encrypt", "upload", "download", "restore"} and (
                    result.get("plan_sha256") != self.config["plan"]["sha256"]
                    or result.get("chunk_id") != self.chunk["chunk_id"]):
                raise ValueError("remote plan or chunk differs")
            if phase == "backup" and (result.get("independent_download_verified") is not True
                    or result.get("bundle_sha256") != io.spec(self.meta / "recovery-bundle.json")["sha256"]):
                raise ValueError("independent recovery backup is not proved")
            if phase in {"encrypt", "restore"} and result["tool_identity"]["git_commit"] != self.config["workstation_source_tip"]:
                raise ValueError("archive tool source differs")
        else:
            request = io.spec(self.meta / (phase + "-request.json"))
            if (proof.get("source_git_sha") != self.config["production_source_tip"]
                    or proof.get("operation") != phase or proof.get("request_sha256") != request["sha256"]):
                raise ValueError("production source or request differs")

    def common_crypt(self):
        c, r = self.config, self.requests
        proof = r.production_evidence()
        return {
            "production_manifest": r.ws_in + "/manifest.json",
            "production_manifest_sha256": proof["production_manifest_sha256"],
            "production_receipt": r.ws_in + "/receipt.json",
            "production_receipt_sha256": proof["production_receipt_sha256"],
            "plan_sha256": c["plan"]["sha256"], "archive_id": self.aid,
            "rclone_executable": c["rclone_executable"], "rclone_config": c["crypt_config"],
            "dpapi_secret": c["crypt_secret"], "crypt_remote_name": c["crypt_remote_name"],
            "ciphertext_root": c["ciphertext_root"]}

    def remote_spec(self, phase, completed):
        c, r, aid = self.config, self.requests, self.aid
        crypt_path = self.ws + "/scratch/ac-enc/" + aid + "/receipt.json"
        transport_root = self.ws + "/scratch/production_cold_archive_transport/"
        if phase == "encrypt":
            args = flags("workstation_cold_archive_stage", "--production-chunk", {
                **self.common_crypt(), "archive_file": r.ws_in + "/archive.tar.gz",
                "output_root": self.ws + "/scratch/ac-enc"})
            output = "scratch/ac-enc/" + aid + "/receipt.json"
        elif phase in {"upload", "download"}:
            proof = r.production_evidence()
            values = {
                "attempt_id": aid + ("wu1" if phase == "upload" else "wd1"),
                "expected_source_tip": c["workstation_source_tip"],
                "crypt_receipt_path": crypt_path, "crypt_receipt_sha256": self.doc(completed, "encrypt")["sha256"],
                "production_manifest_path": r.ws_in + "/manifest.json",
                "production_manifest_sha256": proof["production_manifest_sha256"],
                "production_receipt_path": r.ws_in + "/receipt.json",
                "production_receipt_sha256": proof["production_receipt_sha256"],
                "plan_sha256": c["plan"]["sha256"], "archive_id": aid,
                **{key: c[key] for key in ("rclone_executable", "drive_remote_name", "drive_root_folder_id")},
                "rclone_config": c["drive_config"], "dpapi_secret": c["drive_secret"]}
            if phase == "upload":
                values["ciphertext_path"] = c["ciphertext_root"] + "/" + self.value(completed, "encrypt")["ciphertext"]["path_relative_to_ciphertext_root"]
            else:
                values.update(upload_receipt_path=transport_root + aid + "wu1/transfer/receipt.json",
                              upload_receipt_sha256=self.doc(completed, "upload")["sha256"])
            args = flags("workstation_cold_archive_stage", "--production-transfer", values,
                         ("upload_only" if phase == "upload" else "download_and_verify",))
            output = "scratch/production_cold_archive_transport/" + values["attempt_id"] + "/transfer/receipt.json"
        elif phase == "restore":
            args = flags("workstation_cold_archive_restore", "--production-chunk", {
                **self.common_crypt(), "output_root": self.ws + "/scratch/ac-rest", "restore_id": aid + "wr1",
                "crypt_receipt": crypt_path, "crypt_receipt_sha256": self.doc(completed, "encrypt")["sha256"],
                "transport_receipt": transport_root + aid + "wd1/transfer/receipt.json",
                "transport_receipt_sha256": self.doc(completed, "download")["sha256"],
                "downloaded_file": transport_root + aid + "wd1/transfer/downloaded-" + aid + ".rclone.bin"})
            output = "scratch/ac-rest/" + aid + "wr1/receipt.json"
        elif phase == "recovery":
            args = flags("workstation_cold_archive_restore", "--publish-recovery", {
                "entry_path": r.ws_in + "/catalog-entry.json",
                "entry_sha256": self.doc(completed, "publish", "entry")["sha256"],
                "transport_receipt": transport_root + aid + "wd1/transfer/receipt.json",
                "transport_receipt_sha256": self.doc(completed, "download")["sha256"],
                "restore_receipt": self.ws + "/scratch/ac-rest/" + aid + "wr1/receipt.json",
                "restore_receipt_sha256": self.doc(completed, "restore")["sha256"],
                "key_custody": c["key_custody"]["path"], "key_custody_sha256": c["key_custody"]["sha256"],
                "recovery_data_root": self.ws + "/scratch/production_cold_archive_recovery/" + self.campaign + "/data",
                "attempt_id": aid + "wp1"})
            output = "scratch/production_cold_archive_recovery/" + self.campaign + "/handbacks/" + aid + "wp1/receipt.json"
        elif phase == "workstation_cleanup":
            recovery = self.value(completed, "recovery")
            values = {name: recovery[source]["path"] for name, source in (
                ("entry_path", "catalog_entry"), ("restore_record", "restore_record"), ("custody_record", "custody_record"))}
            values.update({name: recovery[source]["sha256"] for name, source in (
                ("entry_sha256", "catalog_entry"), ("restore_record_sha256", "restore_record"), ("custody_record_sha256", "custody_record"))})
            args = flags("workstation_cold_archive_restore", "--cleanup-verified", {
                **values, "ciphertext_root": c["ciphertext_root"], "attempt_id": aid + "wc1",
                "expected_source_tip": c["workstation_source_tip"]})
            output = "scratch/ac-clean/" + aid + "wc1/receipt.json"
        elif phase == "backup":
            args = flags("workstation_cold_archive_stage", "--backup-recovery", {
                "attempt_id": aid + "b1", "expected_source_tip": c["workstation_source_tip"],
                "bundle_path": self.ws + "/scratch/ac-control/" + self.campaign + "/" + aid + "-recovery.json",
                "bundle_sha256": io.spec(self.meta / "recovery-bundle.json")["sha256"],
                **{key: c[key] for key in ("rclone_executable", "drive_remote_name", "drive_root_folder_id")},
                "rclone_config": c["drive_config"], "dpapi_secret": c["drive_secret"]})
            output = "scratch/ac-backup/" + aid + "b1/receipt.json"
        else:
            raise ValueError("unknown remote phase")
        request = {
            "arguments": args, "python": c["workstation_python"], "seconds": LIMITS[phase] + 15,
            "receipt": "scratch/ac-control/" + self.campaign + "/" + aid + "-" + phase.replace("_", "-") + ".json"}
        return request, output

    def production_paths(self, phase):
        suffix = {"stage": "s1", "copy": "o1", "publish": "p1", "reclaim": "r1"}[phase]
        family = {"stage": "production_cold_archive", "copy": "production_cold_archive_copy",
                  "publish": "production_cold_archive_transfer", "reclaim": "production_cold_archive_reclaim"}[phase]
        return self.root / "scratch" / family / (self.aid + suffix)

    def collect(self, phase, completed):
        docs = {}
        if phase in REMOTE_PHASES:
            request, output = self.remote_spec(phase, completed)
            job = self.transport.read_remote(request["receipt"], self.meta / (phase + "-job.json"), missing_ok=True)
            if job is None:
                return None
            proof = io.load_spec(job)
            if proof.get("request_sha256") != hashlib.sha256(archive._canonical(request)).hexdigest():
                raise ValueError("remote completion request differs")
            docs["job"] = job
            docs["result"] = self.transport.read_remote(output, self.meta / (phase + ".json"))
            if phase == "recovery":
                recovery = io.load_spec(docs["result"])
                for name in ("restore_record", "custody_record"):
                    path = recovery[name]["path"].replace("\\", "/")
                    if not path.startswith(self.ws + "/"):
                        raise ValueError("recovery metadata escaped workstation")
                    docs[name] = self.transport.read_remote(path[len(self.ws) + 1:], self.meta / (name + ".json"))
                    if docs[name]["sha256"] != recovery[name]["sha256"]:
                        raise ValueError("recovery publication hash differs")
            elapsed = proof["elapsed_seconds"]
        else:
            output = self.production_paths(phase)
            if not (output / "wrapper-result.json").exists():
                return None
            docs["wrapper"] = io.spec(output / "wrapper-result.json")
            if (output / "result.json").exists():
                docs["result"] = io.spec(output / "result.json")
            proof = io.load_spec(docs["wrapper"])
            elapsed = (staging._utc(proof["completed_at_utc"]) - staging._utc(proof["started_at_utc"])).total_seconds()
            if phase == "stage":
                docs.update(manifest=io.spec(self.requests.stage / "manifest.json"),
                            stage_receipt=io.spec(self.requests.stage / "receipt.json"))
            elif phase == "publish":
                entry = self.root / "data/cold_archive/catalog/archives" / self.aid / "upload.json"
                docs["entry"] = io.spec(entry)
            elif phase == "reclaim":
                receipt = Path(self.config["progress_path"]).parent / (self.aid + "r1") / "receipt.json"
                docs["reclaim"] = io.spec(receipt)
                if proof.get("status") != "PASS":
                    entry = self.doc(completed, "publish", "entry")
                    result = reconcile.committed_reclaim(
                        wrapper=docs["wrapper"], receipt=docs["reclaim"], progress=self.config["progress_path"],
                        entry_sha256=entry["sha256"], archive_id=self.aid,
                        approval_sha256=self.config["owner_approval"]["sha256"], production_root=self.root)
                    progress = Path(self.config["progress_path"])
                    docs["progress"] = io.write_bytes(self.meta / "reclaim-progress.json", progress.read_bytes())
                    if docs["progress"]["sha256"] != result["progress_sha256"]:
                        raise ValueError("progress changed during reconciliation")
                    docs["reconciliation"] = reconcile.retain(self.meta / "reclaim-reconciliation.json", result)
        evidence = {"phase": phase, "documents": docs, "elapsed_seconds": elapsed,
                    "deadline_seconds": LIMITS[phase]}
        self.verify(phase, evidence)
        return evidence

    def recover(self, phase, claim, completed):
        # The exact immutable job/result receipt is the only retry authority.
        # A missing or failed receipt never causes dispatch to be repeated.
        return self.collect(phase, completed)

    def execute(self, phase, claim, completed):
        print(json.dumps({"archive_id": self.aid, "phase": phase, "status": "STARTED"}), flush=True)
        if phase in REMOTE_PHASES:
            if phase == "recovery":
                entry = self.doc(completed, "publish", "entry")
                self.transport.push_metadata(entry["path"], "scratch/ac-in/" + self.aid + "/catalog-entry.json")
            if phase == "backup":
                records = []
                for prior in completed.values():
                    for item in prior["evidence"]["documents"].values():
                        path = Path(item["path"])
                        raw = archive._safe_path(path).read_bytes()
                        records.append({"path": str(path), "sha256": item["sha256"],
                                        "base64": base64.b64encode(raw).decode("ascii")})
                for path in (Path(self.config["progress_path"]), self.root / "data/cold_archive/WHERE_DATA_IS.md"):
                    item = io.spec(path)
                    raw = path.read_bytes()
                    records.append({**item, "base64": base64.b64encode(raw).decode("ascii")})
                bundle = {"archive_id": self.aid, "contains_archive_payload": False,
                          "contains_credential_values": False, "records": records}
                io.write_bytes(self.meta / "recovery-bundle.json", archive._canonical(bundle) + b"\n")
                self.transport.push_metadata(
                    self.meta / "recovery-bundle.json",
                    "scratch/ac-control/" + self.campaign + "/" + self.aid + "-recovery.json")
            request, _ = self.remote_spec(phase, completed)
            self.transport.rpc("run", request, seconds=LIMITS[phase] + 45)
        else:
            if phase == "stage":
                request = self.requests.base()
            elif phase == "copy":
                request = self.requests.copy()
            elif phase == "publish":
                request = self.requests.publish(self.doc(completed, "encrypt"), self.doc(completed, "upload"))
            else:
                request = self.requests.reclaim(
                    self.doc(completed, "publish", "entry"), self.doc(completed, "recovery", "restore_record"),
                    self.doc(completed, "recovery", "custody_record"))
            request_spec = io.write_bytes(self.meta / (phase + "-request.json"), archive._canonical(request) + b"\n")
            args = [self.transport.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                    str(self.transport.source / "scripts/ops/production_cold_archive_run.ps1"),
                    "-ProductionRepoRoot", str(self.root), "-RequestPath", request_spec["path"],
                    "-RequestSHA256", request_spec["sha256"], "-OutputRoot", str(self.production_paths(phase)),
                    "-ExpectedSourceTip", self.config["production_source_tip"], "-Operation", phase]
            exception = state.active_window(self.config, datetime.now(timezone.utc))["owner_exception"]
            if exception:
                args.extend(["-OwnerApprovedException", exception])
            self.transport.run(args, LIMITS[phase] + 30)
        result = self.collect(phase, completed)
        if result is None:
            raise state.CampaignPaused("started phase has no terminal receipt")
        print(json.dumps({"archive_id": self.aid, "phase": phase, "status": "PASS",
                          "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
        return result
