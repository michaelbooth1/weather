"""Fixed reviewed workflow preparation; only data may cross into publisher.

Inputs are a source-control principal's exact artifact/authority references.
Candidate code cannot rewrite the authority or select a producer revision.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import zipfile

from . import archive, environment, installation, process, remote, source
from .contracts import Graph, PLATFORMS, fields, record, remote_id, sequence, validate_trust
from .records import checked_root, digest, integer, open_record, publish, read, reference, relative_path, require
from .runner import Runner, TRUSTED_PYTHON, TRUSTED_WINDOWS


def dispatch(value, *, producer_revision, repository):
    value = record(value, "qualification_dispatch_v2", {"source", "baseline", "policy", "review", "profiles"})
    digest(value["source"], git=True)
    digest(value["baseline"], git=True)
    reference(value["policy"])
    reference(value["review"])
    fields(value["profiles"], set(PLATFORMS))
    for platform, profile in value["profiles"].items():
        fields(profile, {"environment_bindings", "dependency_lock", "wheel_artifact", "executables", "site_roots", "installer"})
        reference(profile["dependency_lock"])
        installer = fields(profile["installer"], {"root", "files", "exclusions", "sites"})
        reference(installer["files"])
        for path in sequence(installer["sites"], minimum=1, maximum=4):
            relative_path(path)
        for path in sequence(installer["exclusions"], maximum=32):
            relative_path(path)
        artifact = fields(profile["wheel_artifact"], {"id", "sha256", "size"})
        remote_id(artifact["id"])
        digest(artifact["sha256"])
        integer(artifact["size"], minimum=1, maximum=512 * 1024**2)
    digest(producer_revision, git=True)
    require(type(repository) is str and repository.count("/") == 1, "repository required")
    return value


def extract_wheels(root, archive_ref, *, destination, lock_value):
    """A separate reviewed wheel lane; certificate extraction stays data-only."""
    lock_value = installation.lock(lock_value)
    expected = {item["filename"]: item for item in lock_value["wheels"]}
    destination = Path(destination)
    checked_root(destination.parent)
    require(not destination.exists(), "wheel destination spent")
    Graph(root).blob(archive_ref, maximum=512 * 1024**2)
    with open_record(root, archive_ref["path"]) as handle, zipfile.ZipFile(handle) as packed:
        members = packed.infolist()
        require(len(members) == len(expected) and len({m.filename for m in members}) == len(members) and
                {m.filename for m in members} == set(expected), "wheel archive differs from reviewed complete set")
        for member in members:
            mode = member.external_attr >> 16
            require(not member.is_dir() and member.orig_filename == member.filename and
                    stat.S_IFMT(mode) in {0, stat.S_IFREG} and not mode & 0o111 and not member.flag_bits & 1 and
                    member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and
                    member.file_size == expected[member.filename]["size"], "unsafe wheel archive member")
        require(sum(m.file_size for m in members) <= 2 * 1024**3, "expanded wheel archive exceeds bound")
        destination.mkdir()
        for member in members:
            hasher, count = hashlib.sha256(), 0
            with packed.open(member) as original, (destination / member.filename).open("xb") as output:
                while block := original.read(min(1024 * 1024, member.file_size + 1 - count)):
                    count += len(block)
                    require(count <= member.file_size, "expanded wheel grew")
                    hasher.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            require(count == member.file_size and hasher.hexdigest() == expected[member.filename]["sha256"], "expanded wheel differs")
    return destination


def select_job(client, *, run_identity, platform):
    from .records import decode
    require(platform in {*PLATFORMS, "publisher"}, "unexpected job role")
    listing = decode(client.json(remote.endpoints(run_identity)["jobs"]))
    jobs = remote._complete_page(listing, "jobs", maximum=3)
    selected = [item for item in jobs if item.get("name") == "qualification-" + platform]
    require(len(selected) == 1, "exact running job missing or ambiguous")
    job = selected[0]
    require(job.get("status") == "in_progress" and job.get("conclusion") is None and
            remote.api_id(job.get("run_id")) == run_identity["run_id"] and job.get("head_sha") == run_identity["revision"],
            "job is not in the reviewed producer invocation")
    return remote.api_id(job["id"])


def prepare_bundle(client, *, root, artifact, authority_ref, producer_revision, run_identity):
    root = Path(root)
    checked_root(root.parent)
    require(not root.exists(), "workflow preparation namespace spent")
    root.mkdir()
    ref = client.artifact(artifact["id"], root=root, name="preparation.zip", sha256=artifact["sha256"], size=artifact["size"])
    destination = root / "evidence"
    archive.extract(root, ref, destination)
    graph = Graph(destination)
    authority = dispatch(graph.get(authority_ref), producer_revision=producer_revision, repository=client.repository)
    policy, reviewed, _ = validate_trust(graph, authority["policy"], authority["review"])
    require(policy["repository"] == client.repository and policy["producer"]["revision"] == producer_revision and
            authority["source"] == reviewed["source"]["commit"] and authority["baseline"] == reviewed["source"]["baseline"],
            "dispatch source/review/producer differs")
    from .contracts import run
    run(run_identity, policy)
    graph.fresh()
    return destination, authority


def launch_pins(trusted_root, *, platform, inventory_value):
    """Derive closure pins from already proved Git P bytes, never candidate S."""
    indexed = {item["path"]: item for item in inventory_value["files"]}
    names = set(TRUSTED_PYTHON.values()) | (set(TRUSTED_WINDOWS) if platform == "windows" else set())
    require(names <= set(indexed), "trusted producer closure incomplete")
    result = {}
    for name in names:
        item = environment.file_identity(trusted_root, name)
        require(item["sha256"] == indexed[name]["sha256"], "trusted producer working bytes differ")
        result[name] = {key: item[key] for key in ("sha256", "size")}
    return result


def make_runner(*, trusted_root, candidate, evidence_root, scratch, profile, producer_revision, git_path):
    actual_head = source.git_output(git_path, trusted_root, "rev-parse", "HEAD").decode("ascii").strip()
    require(actual_head == producer_revision, "trusted producer checkout is another revision")
    platform = "windows" if os.name == "nt" else "linux"
    trusted_inventory = source.inventory(git_path, trusted_root, producer_revision, verify_working=True)
    return Runner(trusted_root=trusted_root, candidate_root=candidate, output_root=evidence_root, scratch_root=scratch,
                  trusted_files=launch_pins(trusted_root, platform=platform, inventory_value=trusted_inventory),
                  executables=profile["executables"], site_roots=profile["site_roots"])


def data_archive(root, destination):
    """Create a bounded data-only transport archive; never include claims/code."""
    checked_root(root)
    destination = Path(destination)
    require(destination.is_absolute() and not destination.is_relative_to(root), "archive must be outside source data root")
    checked_root(destination.parent)
    paths = [path for path in environment.enumerate_files(root) if Path(path).suffix in archive.DATA_SUFFIXES]
    require(0 < len(paths) <= archive.MAX_MEMBERS, "data archive member bound")
    total = 0
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED) as packed:
        for name in paths:
            identity = environment.file_identity(root, name, maximum=archive.MAX_MEMBER_BYTES)
            if identity["size"] == 0:
                continue
            total += identity["size"]
            require(total <= archive.MAX_ARCHIVE_BYTES - 16 * 1024**2, "data transport archive exceeds bound")
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            with open_record(root, name) as original, packed.open(info, "w") as output:
                hasher, count = hashlib.sha256(), 0
                while block := original.read(1024 * 1024):
                    count += len(block)
                    require(count <= identity["size"], "data member grew while archiving")
                    hasher.update(block)
                    output.write(block)
                require(count == identity["size"] and hasher.hexdigest() == identity["sha256"], "data member changed while archiving")
    identity = environment.file_identity(destination.parent, destination.name, maximum=archive.MAX_ARCHIVE_BYTES)
    return {key: identity[key] for key in ("path", "sha256", "size")}
