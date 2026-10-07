"""Repository ratchet: no WU page token and no WU API URL with a query string in any tracked file.

Spec: D-shadow-gate-spec-v3.1 §4.8 rule 6, with the patterns of v3.2 §5.2 (``maker_core.shadow.secrets``) and the
value-shape rule that replaces the placeholder exemption. v3.2 §5.3: **no allowlist**, and test files are never
allowlisted: every token-bearing mutant builds its token at run time, so this file and every other test pass the
scan as committed.
"""
import re
import secrets as std_secrets
import subprocess
from pathlib import Path

from maker_core.shadow.secrets import scan

REPO = Path(__file__).resolve().parents[2]
WU_API_URL_WITH_QUERY = re.compile(rb"(?i)api\.weather\.com/[^\s\"'<>]*\?[^\s\"'<>]")


def tracked_files(root):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [root / name for name in out.decode("utf-8").split("\0") if name]


def findings(paths, root):
    found = {}
    for path in paths:
        if not path.is_file():
            continue  # a tracked file deleted in the working tree
        data = path.read_bytes()
        ids = sorted({hit.pattern_id for hit in scan(data)})
        if WU_API_URL_WITH_QUERY.search(data):
            ids.append("wu_api_url_with_query")
        if ids:
            found[path.relative_to(root).as_posix()] = ids  # path and pattern ids only, never the bytes
    return found


def test_no_tracked_file_holds_a_token_or_wu_query_url():
    paths = tracked_files(REPO)
    assert len(paths) > 100, "ratchet is vacuous"
    assert findings(paths, REPO) == {}


def test_ratchet_catches_planted_run_time_tokens(tmp_path):
    token = std_secrets.token_hex(16)
    plants = {
        "a.py": f"URL = 'https://api.example.invalid/v1?apiKey={token}'\n",
        "b.json": f'{{"API_KEY":"{token}"}}',
        "c.md": f"api_key%253D{token}\n",
        "d.txt": "https://api.weather.com/v1/location/X/observations/historical.json?units=e\n",
        "clean.py": "PARAM = 'apiKey'  # value supplied at run time\nx = 'apiKey=<redacted>'\n",
    }
    for name, text in plants.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    found = findings([tmp_path / name for name in plants], tmp_path)
    assert set(found) == {"a.py", "b.json", "c.md", "d.txt"}
    assert all(token not in "".join(ids) for ids in found.values())
