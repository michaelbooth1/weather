"""Closed-manifest reader: bounded immutable captured inputs, never a directory scan."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import (CAPS, CITIES, FIRST, LAST, MAX_INPUT_BYTES, MAX_ROWS, ROLES,
                        canonical, digest, exact, identity, instant, json_bytes, local_cut,
                        number, require, sha)
from .core import event_check

FIELDS = {
    "observations": "event_id received_utc observed_utc source station report_key source_sequence raw "
                    "raw_sha256 native_value status parser_sha256",
    "books": "event_id received_utc response_utc exchange_utc yes_token book_id full active integrity_ok asks",
    "heartbeats": "event_id received_utc yes_token ok",
    "resolutions": "event_id received_utc effective_utc yes_token revision final payout_per_share treatment evidence_sha256",
    "integrity": "event_id received_utc book_id ok evidence_sha256",
}


def validate_row(role: str, row: dict) -> None:
    if role == "events":
        event_check(row)
        return
    exact(row, FIELDS[role] + " sequence previous_sha256")
    require(isinstance(row["event_id"], str) and bool(row["event_id"]), "event_id")
    instant(row["received_utc"])
    require(type(row["sequence"]) is int and row["sequence"] >= 1, "sequence")
    sha(row["previous_sha256"])
    if role == "observations":
        instant(row["observed_utc"])
        require(instant(row["observed_utc"]) <= instant(row["received_utc"]), "future_observation")
        require(type(row["source_sequence"]) is int and row["source_sequence"] >= 0, "source_sequence")
        require(isinstance(row["raw"], str) and len(row["raw"]) <= 16_384, "raw_report")
        require(digest(row["raw"].encode("utf-8")) == sha(row["raw_sha256"]), "report_hash")
        sha(row["parser_sha256"])
        require(row["source"] in {"metar_routine", "wu_intraday"}, "source")
        require(isinstance(row["station"], str) and row["station"], "station")
        require(row["status"] in {"valid", "defect", "withdrawn"}, "observation_status")
        if row["native_value"] is not None:
            number(row["native_value"])
    elif role == "books":
        instant(row["response_utc"])
        instant(row["exchange_utc"])
        require(all(type(row[k]) is bool for k in ("full", "active", "integrity_ok")), "book_boolean")
        require(isinstance(row["asks"], list) and len(row["asks"]) <= 1000, "asks")
        prices = []
        for level in row["asks"]:
            require(isinstance(level, list) and len(level) == 2, "depth_level")
            price, size = map(number, level)
            require(0 < price < 1 and size > 0, "depth_range")
            prices.append(price)
        require(prices == sorted(set(prices)), "depth_order")
        require(isinstance(row["book_id"], str) and bool(row["book_id"]), "book_id")
    elif role == "resolutions":
        instant(row["effective_utc"])
        require(type(row["revision"]) is int and row["revision"] >= 1, "resolution_revision")
        require(type(row["final"]) is bool, "resolution_finality")
        require(0 <= number(row["payout_per_share"]) <= 1, "resolution_payout")
        require(row["treatment"] in {"normal", "void", "refund"}, "resolution_treatment")
        if row["treatment"] == "normal" and row["final"]:
            require(number(row["payout_per_share"]) in (0, 1), "normal_payout")
        sha(row["evidence_sha256"])
    else:
        require(type(row["ok"]) is bool, "integrity_boolean")
        if role == "integrity":
            sha(row["evidence_sha256"])
    if "yes_token" in row:
        require(isinstance(row["yes_token"], str) and bool(row["yes_token"]), "token")


def safe_file(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative) and "\\" not in relative, "input_path")
    parts = relative.split("/")
    require(all(p not in {"", ".", ".."} and ":" not in p for p in parts), "input_path")
    path = root
    for part in parts:
        path = path / part
        require(not path.is_symlink() and not (getattr(path.stat(), "st_file_attributes", 0) & 0x400), "input_reparse")
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file(), "input_path")
    return path


def bounded_bytes(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    require(len(data) <= limit, "input_budget")
    return data


def load_pack(manifest_path: Path, previous: dict | None = None) -> tuple[dict, dict]:
    """Validate all bytes/row chains before policy evaluation; any error stays value-safe.

    Every replacement manifest contains all earlier physical files unchanged.
    New files cannot backdate their receipt ranges behind the previous as-of.
    This prevents a restart from changing an already sealed decision.
    """
    raw_manifest = bounded_bytes(manifest_path, 2 * 1024 * 1024)
    manifest = json_bytes(raw_manifest)
    exact(manifest, "schema_version trial platform first_date last_date as_of_utc producer_id reader_sha256 "
          "transform_sha256 timezone_sha256 timezone_version latency_receipt capital files previous_receipt_sha256")
    require(manifest["schema_version"] == "low_ask_inputs_v1" and manifest["trial"] == "LOW-ASK-1", "manifest_schema")
    require(manifest["platform"] == "polymarket_international", "platform_scope")
    require((manifest["first_date"], manifest["last_date"]) == (FIRST.isoformat(), LAST.isoformat()), "manifest_scope")
    as_of = instant(manifest["as_of_utc"])
    require(isinstance(manifest["producer_id"], str) and bool(manifest["producer_id"]), "producer")
    for key in ("reader_sha256", "transform_sha256", "timezone_sha256"):
        sha(manifest[key])
    require(isinstance(manifest["timezone_version"], str) and bool(manifest["timezone_version"]), "timezone_version")
    require(manifest["capital"] == CAPS, "capital_binding")
    latency = manifest["latency_receipt"]
    exact(latency, "p95_seconds frozen_L_seconds samples deployed_path_sha256 evidence_sha256 synthetic")
    require(latency["synthetic"] is True and type(latency["samples"]) is int and latency["samples"] >= 100, "latency_receipt")
    require(number(latency["p95_seconds"]) >= 0 and number(latency["frozen_L_seconds"]) == max(30, number(latency["p95_seconds"])), "latency_binding")
    sha(latency["deployed_path_sha256"])
    sha(latency["evidence_sha256"])
    require(isinstance(manifest["files"], list) and len(manifest["files"]) <= 10_000, "manifest_files")
    files = {}
    rows = {role: [] for role in ROLES}
    total, count = 0, 0
    tails, sequences = {}, {}
    previous_files = {} if previous is None else previous["files"]
    if previous is None:
        require(manifest["previous_receipt_sha256"] is None, "receipt_chain")
    else:
        require(manifest["previous_receipt_sha256"] == digest(canonical(previous)), "receipt_chain")
        require(as_of > instant(previous["as_of_utc"]), "as_of_order")
    for spec in manifest["files"]:
        exact(spec, "path role bytes sha256 schema_version receipt_min_utc receipt_max_utc source_files "
              "chain_id first_sequence previous_sha256 last_sha256")
        path = spec["path"]
        require(path not in files and spec["role"] in ROLES, "file_role_duplicate")
        role = spec["role"]
        require(spec["schema_version"] == "low_ask_rows_v1", "row_schema")
        require(type(spec["bytes"]) is int and spec["bytes"] >= 0, "file_bytes")
        sha(spec["sha256"])
        lower, upper = instant(spec["receipt_min_utc"]), instant(spec["receipt_max_utc"])
        require(lower <= upper <= as_of, "receipt_range")
        if path in previous_files:
            require(spec == previous_files[path], "immutable_input")
        elif previous is not None:
            require(lower > instant(previous["as_of_utc"]), "backdated_input")
        require(isinstance(spec["source_files"], list) and bool(spec["source_files"]), "source_lineage")
        for source in spec["source_files"]:
            exact(source, "physical_path bytes sha256")
            require(isinstance(source["physical_path"], str) and bool(source["physical_path"]), "source_path")
            require(type(source["bytes"]) is int and source["bytes"] >= 0, "source_bytes")
            sha(source["sha256"])
        total += spec["bytes"]
        require(total <= MAX_INPUT_BYTES, "pack_budget")
        data = bounded_bytes(safe_file(manifest_path.parent, path), spec["bytes"])
        require(len(data) == spec["bytes"] and digest(data) == spec["sha256"], "file_hash")
        chain = (role, spec["chain_id"])
        sha(spec["previous_sha256"])
        sha(spec["last_sha256"])
        require(type(spec["first_sequence"]) is int and spec["first_sequence"] >= 1, "chain_sequence")
        require(spec["previous_sha256"] == tails.get(chain, "0" * 64), "chain_anchor")
        require(spec["first_sequence"] == sequences.get(chain, 0) + 1, "chain_sequence")
        tail, seq = spec["previous_sha256"], spec["first_sequence"] - 1
        for line in data.splitlines():
            require(bool(line) and len(line) <= 1024 * 1024, "row_bytes")
            row = json_bytes(line)
            validate_row(role, row)
            received = instant(row["received_utc"])
            require(lower <= received <= upper, "row_receipt_range")
            seq += 1
            if role != "events":
                require(row["previous_sha256"] == tail and row["sequence"] == seq, "row_chain")
            tail = digest(canonical(row))
            rows[role].append(row)
            count += 1
            require(count <= MAX_ROWS, "row_budget")
        require(tail == spec["last_sha256"], "chain_tail")
        tails[chain], sequences[chain] = tail, seq
        files[path] = spec
    require(set(previous_files).issubset(files), "missing_prior_input")
    require({s["role"] for s in files.values()} == set(ROLES), "missing_role")
    event_map = {}
    event_rows = {}
    tokens = {}
    token_owners = set()
    for event in rows["events"]:
        require(event["event_id"] not in event_map, "duplicate_event")
        event_map[event["event_id"]] = identity(event)
        event_rows[event["event_id"]] = event
        tokens[event["event_id"]] = {b["yes_token"] for b in event["bins"]}
        require(not token_owners.intersection(tokens[event["event_id"]]), "token_aliased_across_events")
        token_owners.update(tokens[event["event_id"]])
    book_ids = set()
    for role in ROLES[1:]:
        for row in rows[role]:
            require(row["event_id"] in event_map, "unknown_event")
            if role == "observations":
                event = event_rows[row["event_id"]]
                _, day = event_map[row["event_id"]]
                require(instant(row["observed_utc"]).astimezone(ZoneInfo(event["zone"])).date() == day
                        and instant(row["received_utc"]) <= local_cut(day, event["zone"], 18), "observation_scope")
            if role == "books":
                event = event_rows[row["event_id"]]
                _, day = event_map[row["event_id"]]
                received = instant(row["received_utc"])
                latency_seconds = float(number(manifest["latency_receipt"]["frozen_L_seconds"]))
                starts = [local_cut(day, event["zone"], h) + timedelta(seconds=latency_seconds) for h in (17, 18)]
                require(any(start <= received <= start + timedelta(seconds=60) for start in starts), "book_window_scope")
            if "yes_token" in row:
                require(row["yes_token"] in tokens[row["event_id"]], "token_binding")
            if role == "books":
                require(row["book_id"] not in book_ids, "duplicate_book")
                book_ids.add(row["book_id"])
    receipt = {"as_of_utc": manifest["as_of_utc"], "manifest_sha256": digest(raw_manifest),
               "files": files, "row_counts": {r: len(rows[r]) for r in ROLES}}
    return manifest, {"rows": rows, "receipt": receipt}
