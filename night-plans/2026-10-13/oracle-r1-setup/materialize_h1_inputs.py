"""Write the H1 r1 cut inputs on the capture host from git objects, byte-exact.

Run with the operator account: ``python -I materialize_h1_inputs.py --repo <PROD_CLONE> --ops <OPS_DIR>``.
Every file is read from the git object store by its blob id (no checkout, so no CRLF conversion), checked against
its SHA-256 and written to a path that must not exist. The frozen spec copies go to
``C:\\wt\\workstation-chat\\l-data\\swarm-m\\h1-frozen-20261007``: the plan's ``spec_source_dir`` is relative
(``../../wt/...``), so the plan must sit two levels below ``C:\\`` (``<OPS_DIR>\\plan``) and the plan bytes stay
unchanged, which keeps the manifest binding. Stdlib only; refuses on any mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = Path(r"C:\wt\workstation-chat\l-data\swarm-m\h1-frozen-20261007")

# (blob id, sha256, destination relative to --ops, or absolute)
ROWS = [
    # cut tool at claude/oracle-handout-h1-20261012 (cf7b0d533 and later; unchanged since 6ca59743d)
    ("04469bf0e3d027c5e8eaf928338e3ad75484b73e",
     "34a9161f714db39227062c8ec2657f6d12fcc3c117b74b6d3c546e73a07ac242", "tool/maker_replay_v2_h1_cut.py"),
    # r1 plan (claude/night-plans, this folder)
    ("bd30d0aaabd94fa5aa3caa8ec99b4bf7a3a68927",
     "e75ed9de176e9775009bf64b8162048a703c1f91a9a102695f84b63a7087fc56", "plan/plan.json"),
    # frozen spec sources (origin/claude/scratch-h1-sources-20261007 @ 9043217c2; SHA256SUMS there)
    ("ecae7fb816aa97685368b42a8de7c53721e2d40a",
     "36120634030de0cdef91b5a7b4470390685d92be6d496c580c38dbf26e8940f9", FROZEN / "D-shadow-gate-spec-v3.3.md"),
    ("6e979d3278c2d27d1069d711f99b67f3ff76d232",
     "e7359abef77cd3b583e772203688edc42142f972c872a93a0257b1ad5d7ce2ab", FROZEN / "D-shadow-gate-spec-v3.2.md"),
    ("30df99c4c07983cce6a8cfe2f050b6fce145866c",
     "f0729884291142d25ea773a9d81f83ef80422a0aaf60898ef68089b694398f29", FROZEN / "D-shadow-gate-spec-v3.1.md"),
    ("e52a59dd71d460ac94a47cd27c5610a46b8240c0",
     "2bd3942ec7994a83a627574204024fc3cc3a38d311a4394df218654359bc0a9c", FROZEN / "D-shadow-gate-spec-v3.md"),
    ("759abf6dfe5d01460464fec33bdb960ccd774e64",
     "58484328bb3675bbbd2b7f9175ce9b0ad9648642a400aa714d993a723db05ca6", FROZEN / "D-shadow-gate-spec-v2.md"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--ops", required=True, type=Path)
    a = ap.parse_args()
    if a.ops.resolve().parent != Path(a.ops.resolve().anchor):
        print("REFUSED: --ops must be a top-level folder (the plan's relative spec_source_dir needs it)")
        return 2
    for blob, sha, dest in ROWS:
        out = Path(dest) if Path(dest).is_absolute() else a.ops / dest
        if out.exists():
            print(f"REFUSED: {out} exists")
            return 2
        r = subprocess.run(["git", "-C", str(a.repo), "cat-file", "blob", blob], capture_output=True)
        if r.returncode != 0:
            print(f"REFUSED: blob {blob} not in {a.repo} (fetch the four branches first)")
            return 2
        got = hashlib.sha256(r.stdout).hexdigest()
        if got != sha:
            print(f"REFUSED: {blob} sha256 {got} != {sha}")
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.stdout)
        print(f"ok {sha[:12]} {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
