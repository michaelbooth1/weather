"""Fixed offline gh invocation; launched only by the contained trusted parent.

Stdout and stderr are separate bounded files. This script uses only the pinned
base interpreter's standard library and never imports an evidence/candidate path.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


CAP = 2 * 1024**2


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def main():
    require(sys.flags.isolated and sys.flags.no_site, "isolated no-site bootstrap required")
    require(len(sys.argv) == 3, "exact request path and byte digest required")
    request_path = Path(sys.argv[1])
    require(request_path.is_absolute(), "absolute verifier request required")
    with request_path.open("rb") as handle:
        raw = handle.read(16385)
    require(len(raw) <= 16384 and hashlib.sha256(raw).hexdigest() == sys.argv[2], "verifier request bytes differ")
    request = json.loads(raw)
    require(type(request) is dict and set(request) == {"command", "gh_sha256", "output", "stderr", "result"},
            "unsupported trusted verifier request")
    command = request["command"]
    require(type(command) is list and len(command) == 25 and all(type(x) is str and "\0" not in x for x in command),
            "fixed verifier argv required")
    require(command[1:3] == ["attestation", "verify"] and command[18] == "--deny-self-hosted-runners",
            "only offline attestation verification supported")
    # Parse the exact fixed command shape rather than accepting arbitrary gh flags.
    require(command[4::2][:8] == ["--repo", "--bundle", "--custom-trusted-root", "--signer-workflow",
                                 "--signer-digest", "--source-digest", "--cert-oidc-issuer", "--deny-self-hosted-runners"],
            "verifier command shape differs")
    require(command[-4:] == ["--predicate-type", "https://slsa.dev/provenance/v1", "--format", "json"] and
            command[17] == "https://token.actions.githubusercontent.com" and command[19:21] == ["--hostname", "github.com"],
            "verifier trust options differ")
    gh = Path(command[0])
    require(gh.is_absolute() and gh.is_file(), "absolute reviewed gh required")
    with gh.open("rb") as handle:
        require(hashlib.file_digest(handle, "sha256").hexdigest() == request["gh_sha256"], "native gh changed")
    paths = [Path(request[key]) for key in ("output", "stderr", "result")]
    require(all(path.is_absolute() and path.parent == request_path.parent for path in paths) and len(set(paths)) == 3,
            "verifier outputs must be distinct in the request namespace")
    environment = dict(os.environ)
    require(not any("TOKEN" in key.upper() or "PASSWORD" in key.upper() or "SECRET" in key.upper() or
                    key.upper().startswith(("GH_", "AWS_", "AZURE_", "OPENAI_")) for key in environment),
            "verifier inherited credential authority")
    environment.update(GH_CONFIG_DIR=str(request_path.parent / "empty-gh"), GH_PROMPT_DISABLED="1", NO_COLOR="1")
    Path(environment["GH_CONFIG_DIR"]).mkdir()
    errors = []
    stop = threading.Event()

    def copy(pipe, target):
        count = 0
        try:
            with target.open("xb") as output:
                while block := pipe.read(65536):
                    count += len(block)
                    require(count <= CAP, "offline verifier output limit")
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            errors.append("offline verifier stream failed or exceeded limit")
            stop.set()
        finally:
            pipe.close()

    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=environment, cwd=request_path.parent)
    threads = [threading.Thread(target=copy, args=(pipe, path), daemon=True)
               for pipe, path in zip((child.stdout, child.stderr), paths)]
    for thread in threads:
        thread.start()
    edge = time.monotonic() + 30
    try:
        while child.poll() is None:
            require(not stop.is_set() and time.monotonic() < edge, "offline verifier timed out or lost output")
            time.sleep(0.01)
        for thread in threads:
            thread.join(max(0, edge - time.monotonic()))
        require(not errors and all(not thread.is_alive() for thread in threads), "offline verifier output incomplete")
        with paths[2].open("xb") as output:
            output.write((json.dumps({"exit_code": child.returncode}) + "\n").encode())
            output.flush()
            os.fsync(output.fileno())
        return child.returncode
    finally:
        if child.poll() is None:
            child.kill()
        # The outer native Job/subreaper owns descendant and EOF teardown proof.


if __name__ == "__main__":
    raise SystemExit(main())
