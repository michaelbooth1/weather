"""Read-only scan for persisted Weather Underground page access tokens.

Owner decision OD15 (2026-10-06) allows the free WU history access that uses the
token scraped from the public history page, but the token must never be
persisted in logs, tapes, error rows, commits or anything pushed. This CLI walks
the given roots and reports *where* a token-shaped value appears, never *what*
it is: the output carries only file paths, per-pattern match counts and the
byte offset of the first match.

Exit codes: 0 clean (every eligible file scanned), 1 at least one finding,
2 error or incomplete scan (a cap was hit, a root is missing, a file could not be
read, or ``--token-from-env`` names an unusable variable). A capped scan is
never reported clean.

The walk never follows symlinks or junctions and is bounded by ``--max-files``,
``--max-file-bytes`` and ``--max-total-bytes``. Files are streamed in chunks, so
memory stays flat however large a tape is. Compressed files are scanned as raw
bytes and are not decompressed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "wu_token_scan_v1"

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_ERROR = 2

DEFAULT_MAX_FILES = 500_000
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
DEFAULT_EXCLUDED_DIR_NAMES = (".git", "__pycache__", "venv", ".venv", "node_modules")
CHUNK_BYTES = 1024 * 1024
# Longest match any pattern can produce; a match straddling two chunks is always
# whole inside the overlap.
OVERLAP_BYTES = 4096
MIN_ENV_TOKEN_CHARS = 8
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# A token value: WU page keys are 32 hex characters; anything alphanumeric of 16+
# characters is treated as token-shaped so ``api_key=None`` or ``<redacted>`` never match.
_VALUE = rb"[A-Za-z0-9]{16,128}"
_QUOTE = rb"(?:\\?[\"']|&quot;|&q;|&#34;|&#x22;)"

PATTERNS = {
    # apiKey=<value> in a URL, a log line or an error row (also URL-encoded ``=``).
    "apikey_query_param": re.compile(rb"(?i)\bapi_?key(?:=|%3D)" + _VALUE),
    # apiKey:<value> in key style: JSON "apiKey":"<value>" (also a JSON string nested
    # in JSON), a Python dict repr 'apiKey': '<value>', or a JS/log apiKey: <value>.
    "apikey_colon_field": re.compile(
        rb"(?i)\bapi_?key" + _QUOTE + rb"?\s*:\s*" + _QUOTE + rb"?" + _VALUE
    ),
    # The WU page runtime global: "API_KEY":"<value>" (raw, HTML-escaped or Angular
    # &q; transfer state) or a JS ``API_KEY = '<value>'`` assignment.
    "wu_page_api_key_block": re.compile(
        rb"\bAPI_KEY" + _QUOTE + rb"?\s*[:=]\s*" + _QUOTE + rb"?" + _VALUE
    ),
    # A bare 32-hex string within 64 bytes after an apiKey/API_KEY name.
    "hex32_near_apikey": re.compile(
        rb"(?is)api_?key.{0,64}?(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])"
    ),
}
EXACT_TOKEN_PATTERN = "exact_env_token"


@dataclass
class ScanResult:
    findings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped_oversize: list = field(default_factory=list)
    skipped_links: int = 0
    files_scanned: int = 0
    bytes_scanned: int = 0
    truncated_reason: str | None = None


def _is_link_or_junction(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0) or 0
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def iter_files(roots, excluded_dir_names=DEFAULT_EXCLUDED_DIR_NAMES, result=None):
    """Yield ``(path, size)`` for regular files under ``roots``; links are never followed."""
    excluded = {name.casefold() for name in excluded_dir_names}
    for root in roots:
        root = Path(root)
        try:
            root_info = os.lstat(root)
        except OSError as exc:
            if result is not None:
                result.errors.append({"path": str(root), "error": type(exc).__name__})
            continue
        if stat.S_ISLNK(root_info.st_mode):
            if result is not None:
                result.skipped_links += 1
            continue
        if stat.S_ISREG(root_info.st_mode):
            yield root, root_info.st_size
            continue
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    children = sorted(entries, key=lambda item: item.name)
            except OSError as exc:
                if result is not None:
                    result.errors.append({"path": str(directory), "error": type(exc).__name__})
                continue
            subdirectories = []
            for entry in children:
                if _is_link_or_junction(entry):
                    if result is not None:
                        result.skipped_links += 1
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() not in excluded:
                            subdirectories.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    if result is not None:
                        result.errors.append({"path": entry.path, "error": type(exc).__name__})
                    continue
                yield Path(entry.path), size
            stack.extend(reversed(subdirectories))


def scan_file(path, patterns):
    """Return ``{pattern: (count, first_offset)}`` for one file, streaming in chunks."""
    hits = {}
    base = 0
    counted_until = 0
    carry = b""
    with open(path, "rb") as handle:
        remaining = os.fstat(handle.fileno()).st_size
        while True:
            # Size the read to the file: a full-chunk read() allocates CHUNK_BYTES per
            # call, which dominates the cost of scanning many small files on Windows.
            # A file that grows while it is read continues in 64 KiB reads.
            chunk = handle.read(min(CHUNK_BYTES, remaining) if remaining else 64 * 1024)
            remaining = max(0, remaining - len(chunk))
            eof = not chunk
            buffer = carry + chunk
            if not buffer:
                break
            limit = len(buffer) if eof else max(0, len(buffer) - OVERLAP_BYTES)
            lowered = buffer.lower()
            key_named = b"apikey" in lowered or b"api_key" in lowered
            for name, pattern in patterns.items():
                # Every built-in pattern is anchored on an apiKey/API_KEY name; a chunk
                # without one cannot match, so skip the (slow, case-insensitive) regex.
                if name in PATTERNS and not key_named:
                    continue
                for match in pattern.finditer(buffer):
                    start = base + match.start()
                    if start < counted_until or (not eof and match.start() >= limit):
                        continue
                    count, first = hits.get(name, (0, None))
                    hits[name] = (count + 1, start if first is None else first)
            if eof:
                break
            counted_until = base + limit
            carry = buffer[limit:]
            base += limit
    return hits


def scan(
    roots,
    *,
    exact_token: bytes | None = None,
    max_files=DEFAULT_MAX_FILES,
    max_file_bytes=DEFAULT_MAX_FILE_BYTES,
    max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
    excluded_dir_names=DEFAULT_EXCLUDED_DIR_NAMES,
    files=None,
):
    """Scan ``roots`` (or an explicit ``files`` list of paths) and return a :class:`ScanResult`."""
    patterns = dict(PATTERNS)
    if exact_token:
        patterns[EXACT_TOKEN_PATTERN] = re.compile(re.escape(exact_token))
    result = ScanResult()
    if files is not None:
        candidates = []
        for path in files:
            try:
                info = os.lstat(path)
            except OSError as exc:
                result.errors.append({"path": str(path), "error": type(exc).__name__})
                continue
            if stat.S_ISLNK(info.st_mode):
                result.skipped_links += 1
            elif stat.S_ISREG(info.st_mode):
                candidates.append((Path(path), info.st_size))
    else:
        candidates = iter_files(roots, excluded_dir_names, result)
    for path, size in candidates:
        if result.files_scanned >= max_files:
            result.truncated_reason = "max_files"
            break
        if size > max_file_bytes:
            result.skipped_oversize.append({"path": str(path), "size_bytes": size})
            continue
        if result.bytes_scanned + size > max_total_bytes:
            result.truncated_reason = "max_total_bytes"
            break
        try:
            hits = scan_file(path, patterns)
        except OSError as exc:
            result.errors.append({"path": str(path), "error": type(exc).__name__})
            continue
        result.files_scanned += 1
        result.bytes_scanned += size
        if hits:
            result.findings.append({
                "path": str(path),
                "size_bytes": size,
                "matches": {name: count for name, (count, _first) in sorted(hits.items())},
                "first_match_offset": {name: first for name, (_count, first) in sorted(hits.items())},
            })
    return result


def exit_code_for(result: ScanResult) -> int:
    if result.findings:
        return EXIT_FOUND
    if result.errors or result.skipped_oversize or result.truncated_reason:
        return EXIT_ERROR
    return EXIT_CLEAN


def report(result: ScanResult, roots, *, exact_token_env=None, caps=None) -> dict:
    code = exit_code_for(result)
    status = {EXIT_CLEAN: "CLEAN", EXIT_FOUND: "FOUND", EXIT_ERROR: "INCOMPLETE"}[code]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "exit_code": code,
        "roots": [str(root) for root in roots],
        "patterns": sorted(PATTERNS) + ([EXACT_TOKEN_PATTERN] if exact_token_env else []),
        "exact_token_env": exact_token_env,
        "caps": caps or {},
        "files_scanned": result.files_scanned,
        "bytes_scanned": result.bytes_scanned,
        "finding_file_count": len(result.findings),
        "findings": result.findings,
        "skipped_links": result.skipped_links,
        "skipped_oversize": result.skipped_oversize,
        "truncated_reason": result.truncated_reason,
        "errors": result.errors,
        "matched_text_reported": False,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m weather.operations.wu_token_scan",
        description=(
            "Read-only scan for persisted WU page access tokens. Reports paths, per-pattern "
            "counts and first-match byte offsets only; never the matched text."
        ),
    )
    parser.add_argument("roots", nargs="+", help="Files or directories to scan.")
    parser.add_argument(
        "--token-from-env",
        metavar="NAME",
        help="Also scan for the exact token held in environment variable NAME (never echoed).",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        metavar="NAME",
        help="Directory name to skip (repeatable). Defaults: " + ", ".join(DEFAULT_EXCLUDED_DIR_NAMES),
    )
    parser.add_argument("--json-out", help="Also write the JSON report to this path.")
    return parser


def _error_report(message, roots):
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ERROR",
        "exit_code": EXIT_ERROR,
        "roots": [str(root) for root in roots],
        "error": message,
        "matched_text_reported": False,
    }


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    exact_token = None
    if args.token_from_env:
        value = os.environ.get(args.token_from_env, "")
        if len(value.strip()) < MIN_ENV_TOKEN_CHARS:
            payload = _error_report(
                f"environment variable {args.token_from_env} is unset or shorter than "
                f"{MIN_ENV_TOKEN_CHARS} characters",
                args.roots,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return EXIT_ERROR
        exact_token = value.strip().encode("utf-8")
    caps = {
        "max_files": args.max_files,
        "max_file_bytes": args.max_file_bytes,
        "max_total_bytes": args.max_total_bytes,
        "excluded_dir_names": list(args.exclude_dir or DEFAULT_EXCLUDED_DIR_NAMES),
    }
    try:
        result = scan(
            args.roots,
            exact_token=exact_token,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
            excluded_dir_names=args.exclude_dir or DEFAULT_EXCLUDED_DIR_NAMES,
        )
    except Exception as exc:  # noqa: BLE001 - report the class only; a message could quote file text.
        payload = _error_report(f"scan failed: {type(exc).__name__}", args.roots)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_ERROR
    finally:
        exact_token = None
    payload = report(result, args.roots, exact_token_env=args.token_from_env, caps=caps)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return payload["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
