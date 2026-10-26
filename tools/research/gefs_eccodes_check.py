"""Lane L11 R-O probe check: the pure-numpy GEFS decoder against eccodes, bit-exact (scratch venv only).

Run with an interpreter that has eccodes (for example ``C:\\swarm\\venv``); never the production venv. For every raw
probe message it compares the full decoded field (max abs diff must be 0.0), the grid-point latitudes and longitudes
of every station's four corners, and the identity keys (perturbation number, forecast hour, level).
"""
import importlib.util
import json
import sys
from pathlib import Path

import eccodes
import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gefs_fetch", HERE / "gefs_member_point_fetch.py")
gf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gf)


def main(raw_dir, corners_json, out_json):
    corners = json.loads(Path(corners_json).read_text())["corners"]
    worst, n, bad, ident_bad, latlon_bad = 0.0, 0, [], 0, 0
    for p in sorted(Path(raw_dir).glob("*.grib2")):
        blob = p.read_bytes()
        meta, field = gf.decode_field(blob)
        h = eccodes.codes_new_from_message(blob)
        try:
            ref = eccodes.codes_get_values(h).reshape(eccodes.codes_get(h, "Nj"), eccodes.codes_get(h, "Ni"))
            pert = eccodes.codes_get(h, "perturbationNumber")
            step = eccodes.codes_get(h, "step")
            level = eccodes.codes_get(h, "level")
            if n == 0:
                lats = eccodes.codes_get_array(h, "latitudes").reshape(ref.shape)
                lons = eccodes.codes_get_array(h, "longitudes").reshape(ref.shape)
                for m, c in corners.items():
                    for j, i in ((c["j0"], c["i0"]), (c["j1"], c["i1"])):
                        want_lat = 90.0 - 0.25 * j
                        want_lon = 0.25 * i
                        if abs(lats[j, i] - want_lat) > 1e-9 or abs(lons[j, i] - want_lon) > 1e-9:
                            latlon_bad += 1
        finally:
            eccodes.codes_release(h)
        d = float(np.max(np.abs(field - ref)))
        worst = max(worst, d)
        if d != 0.0:
            bad.append([p.name, d])
        if pert != meta["perturbation"] or step != meta["fh"] or level != 2:
            ident_bad += 1
        n += 1
    res = {"messages": n, "max_abs_diff": worst, "nonzero_messages": bad[:20], "n_nonzero": len(bad),
           "identity_mismatches": ident_bad, "corner_latlon_mismatches": latlon_bad,
           "eccodes_version": eccodes.codes_get_api_version(),
           "bit_exact": n > 0 and worst == 0.0 and ident_bad == 0 and latlon_bad == 0}
    Path(out_json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res))
    return 0 if res["bit_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
