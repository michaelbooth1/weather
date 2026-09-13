"""A killed writer leaves the previous authoritative audit complete."""

import os
from pathlib import Path
import subprocess
import sys
import time

from weather.reporting.source_gates import settlement_source_audit as audit


def test_process_termination_during_streaming_keeps_previous_output(tmp_path):
    output = tmp_path / "audit.json"
    report = tmp_path / "audit.md"
    output.write_bytes(b'{"status":"PASS","rows":[]}\n')
    report.write_bytes(b"previous complete report\n")
    previous = (output.read_bytes(), report.read_bytes())
    ready = tmp_path / "partial-write-started"
    child = tmp_path / "writer.py"
    child.write_text('''
from pathlib import Path
import sys
import time
from weather.reporting.source_gates.settlement_source_audit import write_outputs

root = Path(sys.argv[1])
class PausingRows:
    is_spilled_rows = True
    def __iter__(self):
        yield {"event_slug": "first", "note": "p" * (256 * 1024)}
        (root / "partial-write-started").write_text("ready")
        while True:
            time.sleep(1)

write_outputs({"status": "PASS", "rows": PausingRows()},
              root / "audit.json", root / "audit.md")
''', encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(audit.__file__).resolve().parents[3])
    with (tmp_path / "child-stderr.log").open("wb") as errors:
        process = subprocess.Popen([sys.executable, str(child), str(tmp_path)],
                                   cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=errors)
        try:
            deadline = time.monotonic() + 30
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.exists(), (tmp_path / "child-stderr.log").read_text()
            assert any(path.stat().st_size > 0 for path in tmp_path.glob(".settlement-audit-*/*.tmp"))
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    assert (output.read_bytes(), report.read_bytes()) == previous
    # Abrupt termination can leave an attempt-local partial file, but it never
    # occupies the canonical filename or becomes a gate input.
    assert list(tmp_path.glob(".settlement-audit-*"))
