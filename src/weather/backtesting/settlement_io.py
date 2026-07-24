"""Settlement labels, daily summaries, and native market-band outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import stat
from pathlib import Path

from weather.paths import data_path

import pandas as pd

from weather.backtesting.settlement_ledger import (
    current_ledger_label,
    ledger_path_for_market,
    resolve_ledger_root,
    settlement_from_sources as ledger_settlement_from_sources,
    verify_ledger_history,
)
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.scoring.metrics import missing, safe_float
from weather.sources.daily_summary import native_bucket
from weather.units import round_half_up


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_DAILY_SUMMARY = data_path() / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
COMPLETE_DAY_MIN_ROWS = 18
LEDGER_AUTHORITY_STATUS = "ledger_authority"
SIDECAR_FALLBACK_STATUS = "sidecar_fallback_no_ledger_row"


class SettlementAuthorityError(RuntimeError):
    """The relevant ledger cannot safely establish absence or authority."""


def canonical_winning_band(value):
    """Return one stable spelling for ledger and tape temperature bands."""

    text = str(value or "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00b0", " ")
    text = text.replace("\u2103", " C").replace("\u2109", " F")
    text = text.replace("\u00ba", " ").replace("\u00c2", "")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(
        r"(?<=\d)\s*([cf])\b",
        lambda match: f" {match.group(1).upper()}",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


def band_value_hi(range_label, value, explicit=None):
    """Upper value of a band from its label ('76-77F' -> 77); single bands -> value."""
    explicit_value = safe_float(explicit)
    if explicit_value is not None:
        return int(explicit_value) if abs(explicit_value - round(explicit_value)) < 1e-9 else explicit_value
    numbers = re.findall(r"\d+", str(range_label or ""))
    return int(numbers[-1]) if len(numbers) >= 2 else value


def row_band_value_hi(row):
    explicit = row.get("bin_value_hi_c")
    if missing(explicit) or explicit == "":
        explicit = row.get("bin_value_hi")
    return band_value_hi(row.get("range_label"), row.get("bin_value_c"), explicit=explicit)


def resolve_outcome(kind, value, settlement_bucket, value_hi=None):
    """Resolve whether a native-unit market band settled YES (1) or NO (0)."""
    if settlement_bucket is None or kind is None or value is None:
        return None
    value = int(value)
    settlement_bucket = int(settlement_bucket)
    value_hi = int(value_hi) if value_hi is not None else value
    if kind == "lte":
        return 1 if settlement_bucket <= value else 0
    if kind == "gte":
        return 1 if settlement_bucket >= value else 0
    return 1 if value <= settlement_bucket <= value_hi else 0


def load_daily_summary(path):
    """date -> (native settlement bucket, row_count) from WU daily summary."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            bucket = native_bucket(row)
            if not d or bucket is None:
                continue
            try:
                index[d] = (int(bucket), int(row.get("row_count") or 0))
            except (TypeError, ValueError):
                continue
    return index


def _ledger_authority_error(event_slug, detail):
    return SettlementAuthorityError(
        "settlement ledger authority violation: "
        f"{detail} for {event_slug}"
    )


def _candidate_ledger_paths(event_slug):
    root = resolve_ledger_root()
    spec = spec_for_slug(event_slug)
    if spec is not None:
        return [(ledger_path_for_market(spec.id, root), spec.id)]

    try:
        root_stat = root.stat()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _ledger_authority_error(
            event_slug,
            f"ledger root is unreadable: {root}",
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise _ledger_authority_error(
            event_slug,
            f"ledger root is not a directory: {root}",
        )
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise _ledger_authority_error(
            event_slug,
            f"ledger root cannot be enumerated: {root}",
        ) from exc

    paths = []
    for child in children:
        try:
            child_stat = child.stat()
        except OSError as exc:
            raise _ledger_authority_error(
                event_slug,
                f"ledger market path is unreadable: {child}",
            ) from exc
        if stat.S_ISDIR(child_stat.st_mode):
            paths.append((child / "ledger.jsonl", child.name))
    return paths


def _strict_ledger_history(path, event_slug):
    try:
        path_stat = path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _ledger_authority_error(
            event_slug,
            f"relevant market ledger is unreadable: {path}",
        ) from exc
    if not stat.S_ISREG(path_stat.st_mode):
        raise _ledger_authority_error(
            event_slug,
            f"relevant market ledger is not a regular file: {path}",
        )

    history = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                def reject_duplicate_keys(pairs):
                    row = {}
                    for key, value in pairs:
                        if key in row:
                            raise _ledger_authority_error(
                                event_slug,
                                "relevant market ledger has duplicate JSON key "
                                f"{key!r} at line {line_number}: {path}",
                            )
                        row[key] = value
                    return row

                def reject_non_finite(value):
                    raise _ledger_authority_error(
                        event_slug,
                        "relevant market ledger has non-finite JSON constant "
                        f"{value!r} at line {line_number}: {path}",
                    )

                try:
                    row = json.loads(
                        line,
                        object_pairs_hook=reject_duplicate_keys,
                        parse_constant=reject_non_finite,
                    )
                except json.JSONDecodeError as exc:
                    raise _ledger_authority_error(
                        event_slug,
                        "relevant market ledger has invalid JSON at line "
                        f"{line_number}: {path}",
                    ) from exc
                if not isinstance(row, dict):
                    raise _ledger_authority_error(
                        event_slug,
                        "relevant market ledger line "
                        f"{line_number} is not an object: {path}",
                    )
                history.append(row)
    except SettlementAuthorityError:
        raise
    except UnicodeDecodeError as exc:
        raise _ledger_authority_error(
            event_slug,
            f"relevant market ledger is not valid UTF-8: {path}",
        ) from exc
    except OSError as exc:
        raise _ledger_authority_error(
            event_slug,
            f"relevant market ledger is unreadable: {path}",
        ) from exc
    return history


def _strict_ledger_label_for_slug(event_slug):
    selected = []
    for path, expected_market_id in _candidate_ledger_paths(event_slug):
        history = _strict_ledger_history(path, event_slug)
        if history is None:
            continue

        try:
            verification = verify_ledger_history(history)
            label = current_ledger_label(history, event_slug)
        except Exception as exc:
            raise _ledger_authority_error(
                event_slug,
                f"relevant market ledger history verification failed: {path}",
            ) from exc
        if verification.get("status") != "PASS":
            codes = ",".join(
                str(item.get("code") or "unknown")
                for item in verification.get("blockers") or ()
            )
            raise _ledger_authority_error(
                event_slug,
                "relevant market ledger history integrity failure: "
                f"{codes or 'unknown'}",
            )
        if label is None:
            continue
        if label.get("market_id") != expected_market_id:
            raise _ledger_authority_error(
                event_slug,
                "ledger row exists but its market_id is invalid; "
                f"expected {expected_market_id!r}, "
                f"observed {label.get('market_id')!r}",
            )
        selected.append(label)

    if len(selected) > 1:
        raise _ledger_authority_error(
            event_slug,
            "multiple market ledgers contain a current row",
        )
    return selected[0] if selected else None


def settlement_for_tape(df, target_date, daily_index, overrides):
    """Return (bucket, source, note) for a settlement-scored snapshot tape."""
    event_slug = None
    if "event_slug" in df:
        values = df["event_slug"].dropna().astype(str)
        event_slug = next((value for value in values if value), None)
    iso = target_date.isoformat() if target_date else None
    if event_slug and iso not in (overrides or {}) and event_slug not in (overrides or {}):
        spec = spec_for_slug(event_slug)
        market_key = f"{spec.id}:{iso}" if spec and iso else None
        if not market_key or market_key not in (overrides or {}):
            label = _strict_ledger_label_for_slug(event_slug)
            if label and label.get("settlement_bucket") is not None:
                source = label.get("settlement_source") or "unknown"
                status = label.get("reconciliation_status") or "unknown"
                note = label.get("note") or ""
                if status and status != "not_requested":
                    note = f"{note}; polymarket_reconciliation={status}" if note else f"polymarket_reconciliation={status}"
                return int(label["settlement_bucket"]), f"settlement_ledger:{source}", note

    ledger_result = ledger_settlement_from_sources(
        df,
        target_date,
        daily_index,
        overrides=overrides,
        spec=spec_for_slug(event_slug),
        event_slug=event_slug,
    )
    if ledger_result["bucket"] is not None or ledger_result["source"] == "none":
        return ledger_result["bucket"], ledger_result["source"], ledger_result["note"]

    snapshot_high = None
    if "wu_history_high_c" in df:
        snapshot_high = round_half_up(pd.to_numeric(df["wu_history_high_c"], errors="coerce").max())
    summary = daily_index.get(iso)

    note_bits = []
    if summary is not None and snapshot_high is not None and summary[0] != snapshot_high:
        note_bits.append(
            f"daily_summary={summary[0]} (rows={summary[1]}) disagrees with snapshot high={snapshot_high}"
        )

    if iso in overrides:
        return overrides[iso], "override", "; ".join(note_bits) or "manual override"
    if summary is not None and summary[1] >= COMPLETE_DAY_MIN_ROWS:
        return summary[0], "daily_summary", "; ".join(note_bits)
    if snapshot_high is not None:
        reason = "snapshot wu_history_high (daily summary missing/incomplete)"
        return snapshot_high, "snapshot_high", "; ".join(note_bits) or reason
    if summary is not None:
        return summary[0], "daily_summary(sparse)", "; ".join(note_bits)
    return None, "none", "no settlement available"


def _snapshot_tape_sha256(label):
    evidence = label.get("evidence")
    raw_hashes = (
        evidence.get("raw_resolution_hashes")
        if isinstance(evidence, dict)
        else None
    )
    revision = label.get("revision_provenance")
    revision_hashes = (
        revision.get("raw_resolution_hashes")
        if isinstance(revision, dict)
        else None
    )
    for value in (
        label.get("snapshot_tape_sha256"),
        (raw_hashes or {}).get("snapshot_tape_sha256"),
        (revision_hashes or {}).get("snapshot_tape_sha256"),
    ):
        if value not in (None, ""):
            return str(value).strip().lower()
    return None


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_tape_path(value):
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        return None
    while text.startswith("./"):
        text = text[2:]
    if text.lower().startswith("data/"):
        text = text[5:]
    return text.casefold()


def ledger_label_matches_folder(label, folder, *, snapshot_tape_sha256=None):
    expected_tape = Path(folder) / "snapshots_long.csv"
    recorded_sha256 = _snapshot_tape_sha256(label)
    if recorded_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", recorded_sha256):
            return False
        try:
            actual_sha256 = (
                str(snapshot_tape_sha256).strip().lower()
                if snapshot_tape_sha256 is not None
                else _file_sha256(expected_tape)
            )
        except OSError:
            return False
        return actual_sha256 == recorded_sha256

    portable_path = label.get("snapshot_tape_repo_relative_path")
    if portable_path not in (None, ""):
        expected = f"snapshots/{Path(folder).name}/snapshots_long.csv".casefold()
        return _portable_tape_path(portable_path) == expected

    tape_path = label.get("snapshot_tape_path")
    if not tape_path:
        return False
    portable_path = _portable_tape_path(tape_path)
    if portable_path is not None:
        expected = f"snapshots/{Path(folder).name}/snapshots_long.csv".casefold()
        return portable_path == expected
    return False


def authoritative_ledger_label(folder, *, snapshot_tape_sha256=None):
    slug = Path(folder).name
    label = _strict_ledger_label_for_slug(slug)
    if label is None:
        return None
    target_date = date_from_event_slug(slug)
    recorded_date = str(label.get("target_date") or "")
    if target_date is None or recorded_date != target_date.isoformat():
        raise SettlementAuthorityError(
            "settlement ledger authority violation: ledger row exists but its "
            f"target_date is invalid for {slug}"
        )
    if not ledger_label_matches_folder(
        label,
        folder,
        snapshot_tape_sha256=snapshot_tape_sha256,
    ):
        raise SettlementAuthorityError(
            "settlement ledger authority violation: ledger row exists but its "
            f"snapshot tape binding is invalid for {slug}"
        )
    return label


def resolve_market_day_label(folder):
    label = authoritative_ledger_label(folder)
    if label is not None:
        return {
            "label": label,
            "authority": {
                "status": LEDGER_AUTHORITY_STATUS,
                "ledger_row_exists": True,
                "sidecar_fallback": False,
            },
        }
    path = Path(folder) / "settlement.json"
    if not path.exists():
        return {
            "label": None,
            "authority": {
                "status": "no_ledger_row_no_sidecar",
                "ledger_row_exists": False,
                "sidecar_fallback": False,
            },
        }
    try:
        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "label": None,
            "authority": {
                "status": "no_ledger_row_unreadable_sidecar",
                "ledger_row_exists": False,
                "sidecar_fallback": False,
            },
        }
    return {
        "label": sidecar,
        "authority": {
            "status": SIDECAR_FALLBACK_STATUS,
            "ledger_row_exists": False,
            "sidecar_fallback": True,
        },
    }


def load_market_day_label(folder):
    return resolve_market_day_label(folder)["label"]
