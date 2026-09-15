"""Command entry for the pinned hosted producer; no production-host commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from . import archive, environment, installation, process, producer, publisher, remote, source, workflow
from .contracts import Graph, PLATFORMS, record, validate_trust
from .records import checked_root, decode, digest, integer, open_record, read, require
from .transport import Github


def _hosted(trusted_root):
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
            "this entry point requires the reviewed hosted workflow")
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            machine, _ = winreg.QueryValueEx(key, "MachineGuid")
        machine_id = hashlib.sha256(("international_live_execution_host_v2\0" + str(machine).strip().lower()).encode("utf-8")).hexdigest()
        config = trusted_root / "config/international_live_execution_host.json"
        require(machine_id != decode(config.read_bytes())["dedicated_capture_execution_host_id"],
                "hosted producer is forbidden on the dedicated capture installation")


def _ref(value):
    from .records import reference
    return reference(decode(value.encode("utf-8")))


def _copy_data(source_root, destination):
    require(not destination.exists(), "data export destination spent")
    checked_root(destination.parent)
    destination.mkdir()
    _merge_data(source_root, destination)


def _merge_data(source_root, destination):
    total = 0
    for name in environment.enumerate_files(source_root):
        if Path(name).suffix not in archive.DATA_SUFFIXES:
            continue
        item = environment.file_identity(source_root, name, maximum=archive.MAX_MEMBER_BYTES)
        if item["size"] == 0:
            continue
        total += item["size"]
        require(total <= archive.MAX_EXPANDED_BYTES, "data export exceeds bound")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_root(target.parent)
        if target.exists():
            require(environment.file_identity(destination, name) == item, "native bundles disagree on shared evidence")
            continue
        hasher, count = hashlib.sha256(), 0
        with open_record(source_root, name) as original, target.open("xb") as output:
            while block := original.read(1024 * 1024):
                count += len(block)
                require(count <= item["size"], "data export grew")
                hasher.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        require(count == item["size"] and hasher.hexdigest() == item["sha256"], "data export bytes differ")


def _artifact_pin(client, artifact_id, expected_sha):
    raw = client.json("/repos/" + client.repository + "/actions/artifacts/" + artifact_id)
    value = decode(raw)
    require(remote.api_id(value.get("id")) == artifact_id and value.get("expired") is False and
            value.get("digest") == "sha256:" + digest(expected_sha), "selected input artifact digest differs")
    return {"id": artifact_id, "sha256": expected_sha, "size": integer(value.get("size_in_bytes"), minimum=1)}


def _native_install(*, profile, graph, root, client, trusted, candidate):
    value = installation.lock(graph.get(profile["dependency_lock"]))
    selected = profile["wheel_artifact"]
    _artifact_pin(client, selected["id"], selected["sha256"])
    raw = client.artifact(selected["id"], root=root, name="wheels.zip", sha256=selected["sha256"], size=selected["size"])
    wheels = workflow.extract_wheels(root, raw, destination=root / "wheels", lock_value=value)
    target = Path(profile["environment_bindings"]["installation"])
    require(target.name == "prefix" and target.is_absolute(), "installation profile requires the exact isolated prefix layout")
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    executable = profile["executables"]["python"]
    python = Path(executable["root"]) / executable["path"]
    sites = installation.verify_installer(graph, profile["installer"], candidate=checked_root(candidate))
    require(python.is_relative_to(Path(profile["installer"]["root"])), "installer interpreter outside reviewed closure")
    argv = installation.prepare(value, wheel_root=wheels, destination=target.parent, python_path=python, installer_sites=sites)
    scratch = root / "installation"
    scratch.mkdir()
    tools = {name: Path(item["root"]) / item["path"] for name, item in profile["executables"].items()}
    env = process.clean_environment(scratch=scratch, executable_paths=list(tools.values()))
    options = dict(cwd=trusted, env=env, transcript=scratch / "installer.log", seconds=600, teardown_seconds=30,
                   memory_bytes=4 * 1024**3, output_bytes=16 * 1024**2, minimum_disk_bytes=2 * 1024**3)
    if os.name == "nt":
        result = process.windows_run(argv, powershell=tools["powershell"], dispatcher=trusted / "scripts/ops/qualification_offhost_process.ps1",
                                     scratch=scratch, **options)
    else:
        result = process.linux_run(argv, **options)
    from .runner import native_result
    native_result(result, platform="windows" if os.name == "nt" else "linux")
    installation.verify_installer(graph, profile["installer"], candidate=checked_root(candidate))
    return wheels, value


def _publish_native(client, *, evidence_root, authority, run_identity, scratch):
    listing = decode(client.json(remote.endpoints(run_identity)["artifacts"]))
    artifacts = remote._complete_page(listing, "artifacts", maximum=10)
    for platform in PLATFORMS:
        name = "qualification-native-" + run_identity["run_id"] + "-" + run_identity["attempt"] + "-" + platform
        found = [item for item in artifacts if item.get("name") == name]
        require(len(found) == 1 and found[0].get("expired") is False, "required native artifact absent")
        artifact = found[0]
        require(artifact.get("workflow_run", {}).get("head_sha") == run_identity["revision"], "native artifact producer differs")
        sha = artifact.get("digest", "")
        require(sha.startswith("sha256:"), "native artifact lacks authenticated digest")
        ref = client.artifact(remote.api_id(artifact["id"]), root=scratch, name=platform + ".zip",
                              sha256=sha[7:], size=artifact["size_in_bytes"])
        destination = scratch / platform
        archive.extract(scratch, ref, destination)
        _merge_data(destination, evidence_root)
    graph = Graph(evidence_root)
    jobs = []
    for platform in PLATFORMS:
        item = environment.file_identity(evidence_root, platform + "-job.json")
        jobs.append({key: item[key] for key in ("path", "sha256", "size")})
    publisher_id = workflow.select_job(client, run_identity=run_identity, platform="publisher")
    return publisher.seal(graph, client=client, policy_ref=authority["policy"], review_ref=authority["review"],
                          run_identity=run_identity, job_refs=jobs, publisher_job_id=publisher_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("job", "publish"))
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--preparation-artifact", required=True)
    parser.add_argument("--preparation-sha256", required=True)
    parser.add_argument("--authority", type=_ref, required=True, help="independently reviewed {path,sha256,size} JSON")
    args = parser.parse_args(argv)
    trusted = checked_root(args.trusted_root)
    _hosted(trusted)
    revision = digest(os.environ["GITHUB_WORKFLOW_SHA"], git=True)
    repository = os.environ["GITHUB_REPOSITORY"]
    require(os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and os.environ["GITHUB_SHA"] == revision,
            "producer requires its pinned workflow_dispatch revision")
    run_identity = {"repository": repository, "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                    "event": "workflow_dispatch", "workflow": ".github/workflows/qualification.yml", "revision": revision}
    client = Github(repository, os.environ["GH_TOKEN"], deadline_seconds=600)
    artifact = _artifact_pin(client, remote.remote_id(args.preparation_artifact), args.preparation_sha256)
    root, authority = workflow.prepare_bundle(client, root=args.root, artifact=artifact, authority_ref=args.authority,
                                              producer_revision=revision, run_identity=run_identity)
    platform = "windows" if os.name == "nt" else "linux"
    if args.mode == "job":
        require(args.candidate is not None, "native job requires candidate checkout")
        profile = authority["profiles"][platform]
        graph = Graph(root)
        policy, reviewed, _ = validate_trust(graph, authority["policy"], authority["review"])
        require(installation.lock(graph.get(profile["dependency_lock"]))["platform"] == platform, "wrong native dependency platform")
        tools = profile["executables"]
        expected_environment = graph.get(reviewed["environments"][platform])
        for name in ("python", "git", *(["powershell"] if platform == "windows" else [])):
            expected_sha = expected_environment[name]["executable_sha256" if name == "python" else "sha256"]
            require(tools[name]["sha256"] == expected_sha, "installation tool differs from reviewed environment")
            actual = environment.file_identity(Path(tools[name]["root"]), tools[name]["path"], native_installation=True)
            require(actual["sha256"] == expected_sha and actual["size"] == tools[name]["size"], "installation executable bytes differ")
        git_path = Path(tools["git"]["root"]) / tools["git"]["path"]
        source_head = source.git_output(git_path, trusted, "rev-parse", "HEAD").decode("ascii").strip()
        require(source_head == revision, "trusted producer is not workflow revision")
        job_id = workflow.select_job(client, run_identity=run_identity, platform=platform)
        wheels, lock_value = _native_install(profile=profile, graph=graph, root=args.root, client=client, trusted=trusted, candidate=args.candidate)
        scratch = args.root / "native-scratch"
        scratch.mkdir()
        runner = workflow.make_runner(trusted_root=trusted, candidate=args.candidate, evidence_root=root, scratch=scratch,
                                      profile=profile, producer_revision=revision, git_path=git_path)
        result = producer.run_job(runner, policy_ref=authority["policy"], review_ref=authority["review"],
                                  run_identity=run_identity, job_id=job_id,
                                  environment_bindings=profile["environment_bindings"], wheel_root=wheels, wheels=lock_value["wheels"])
    else:
        scratch = args.root / "native-artifacts"
        scratch.mkdir()
        result = _publish_native(client, evidence_root=root, authority=authority, run_identity=run_identity, scratch=scratch)
    _copy_data(root, args.root / "export")
    print(json.dumps({"record": result, "export": str(args.root / "export")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
