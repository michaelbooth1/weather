"""Row 28 launcher smoke child v1 (lane L59). It reads nothing. It writes only the two files the launcher names
(--out-json, --out-csv) and exits 0: walk.json binds the stage and the launcher's --expect-sha so that runner v6's
verify_prev can be exercised in full on the receipt."""
import json, sys
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
with open(a["--out-json"], "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps({"runner_sha256": a["--expect-sha"], "stage": a["--stage"], "status": "PASS"}, sort_keys=True) + "\n")
with open(a["--out-csv"], "w", encoding="utf-8", newline="\n") as f:
    f.write("path,sha256\n")
