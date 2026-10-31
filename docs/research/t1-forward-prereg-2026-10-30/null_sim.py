"""T+1 prereg rev 8: false-PASS rate of the rule as applied, at the null (mean 0), rho 0.28 and the 0.5 stress.

Reuses ``power_sim.power`` (same futility path, same AR(1)/VIF deciding interval with floor 1.78) with DELTA = 0.
No data is read. Usage: python -I null_sim.py OUT.json  (run from any directory; imports power_sim beside it).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import power_sim as ps  # noqa: E402

N, K, PATHS = 75, 1.07, 400_000


def main(out):
    ps.DELTA, ps.PATHS = 0.0, PATHS
    res = {"n": N, "k": K, "paths": PATHS, "seed": ps.SEED, "nominal": 0.025,
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "power_sim_sha256": hashlib.sha256(Path(ps.__file__).read_bytes()).hexdigest(), "cases": []}
    for rho in (0.28, 0.5):
        ps.RHO = rho
        row = ps.power(N, K)
        res["cases"].append({"rho": rho, "false_pass": row["power"],
                             "false_pass_no_futility": row["power_no_futility"], "stopped": row["stopped"],
                             "median_vif_look": row["median_vif_look"]})
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
