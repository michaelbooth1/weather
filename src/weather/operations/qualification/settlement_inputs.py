"""Prepare the audit's full read-only dependency set without changing its gates.

The small SQLite preparation index reproduces only input encounter/overlay
selection for lineage discovery. The candidate audit remains the authority for
its row classifications and consumer gates; parity tests compare both paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat

from .contracts import record, sequence, text
from .inputs import (MAX_INPUT_FILES, SourceRoots, Stager, _regular,
                     label_rows, ledger_rows, verified_input)
from .records import digest, distinct_paths, fields, identifier, integer, require, timestamp


def lineage_paths(row):
    """Exactly the five source choices read by settlement_source_audit._lineage."""
    values = [row.get("daily_summary_path"), row.get("snapshot_tape_path"), row.get("ledger_path")]
    for names in (("weather_com_raw_payload_path", "weather_com_payload_path"),
                  ("market_resolution_payload_path", "gamma_event_payload_path")):
        values.append(next((row.get(name) for name in names if row.get(name) not in (None, "")), None))
    for value in values:
        if value not in (None, ""):
            text(value, maximum=4096)
            yield value


def market_directories(root, markets):
    require(type(markets) is list and 0 < len(markets) <= 256, "reviewed registry markets required")
    distinct_paths(markets)
    for market in markets:
        identifier(market)
    _regular(root.lstat(), directory=True)
    observed = []
    with os.scandir(root) as entries:
        count = 0
        for entry in entries:
            count += 1
            require(count <= 4096, "settlement root exceeds bounded directory inventory")
            info = entry.stat(follow_symlinks=False)
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                    "redirected settlement input topology")
            if stat.S_ISDIR(info.st_mode):
                # A directory is a ledger dependency when it is required by the
                # registry or contains the ledger filename the audit would glob.
                if entry.name in markets or (Path(entry.path) / "ledger.jsonl").exists():
                    observed.append(entry.name)
    require(sorted(observed) == sorted(markets), "missing or unapproved extra market ledger directory")
    return sorted(observed)


def _index_rows(connection, kind, rows, *, budget, canonical_ledger=None):
    count = 0
    for row in rows:
        count += 1
        require(count <= 2_000_000, "input row count exceeds preparation bound")
        budget.charge()
        if canonical_ledger is not None:
            row = {**row}
            row.setdefault("ledger_path", canonical_ledger)
        slug = row.get("event_slug")
        if not slug:
            continue
        text(slug, maximum=4096)
        connection.execute("INSERT INTO rows(kind, slug, body) VALUES (?, ?, ?) "
                           "ON CONFLICT(kind, slug) DO UPDATE SET body = excluded.body",
                           (kind, slug, json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
    return count


def merged_rows(connection):
    previous, merged = None, {}
    cursor = connection.execute("SELECT kind, slug, body FROM rows ORDER BY slug, CASE kind WHEN 'ledger' THEN 0 ELSE 1 END")
    for kind, slug, body in cursor:
        if previous is not None and slug != previous:
            yield merged
            merged = {}
        row = json.loads(body)
        if kind == "ledger":
            merged = row
        else:
            merged.update({key: value for key, value in row.items() if value not in (None, "")})
        previous = slug
    if previous is not None:
        yield merged


def prepare(stager: Stager, *, labels_identity, ledger_root_identity, markets):
    """Read every label/ledger row, then stage only actual merged-row lineage."""
    root_name, root_path = stager.sources.locate(ledger_root_identity)
    ledger_root = stager.sources.roots[root_name] / root_path
    topology = market_directories(ledger_root, markets)
    index_path = stager.root / "lineage-preparation.sqlite"
    # Reserve the index namespace before SQLite can create or reopen anything.
    with index_path.open("xb"):
        pass
    counts = {"labels": 0, "ledgers": {}, "merged_rows": 0}
    connection = sqlite3.connect(index_path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA cache_size=-4096")
        connection.execute("CREATE TABLE rows (kind TEXT NOT NULL, slug TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind, slug)) WITHOUT ROWID")
        labels = stager.stage(labels_identity, mandatory=True, kind="labels")
        counts["labels"] = _index_rows(connection, "labels", label_rows(stager.root, labels["staged"], stager.budget), budget=stager.budget)
        for market in topology:
            original = str(ledger_root / market / "ledger.jsonl")
            entry = stager.stage(original, mandatory=True, kind="ledger")
            counts["ledgers"][market] = _index_rows(connection, "ledger", ledger_rows(stager.root, entry["staged"], stager.budget),
                                                    budget=stager.budget, canonical_ledger=original)
        connection.commit()
        for row in merged_rows(connection):
            counts["merged_rows"] += 1
            stager.budget.charge()
            for identity in lineage_paths(row):
                stager.stage(identity)
    finally:
        connection.close()
    require(market_directories(ledger_root, markets) == topology, "settlement topology changed during preparation")
    stager.revalidate()
    return {"labels_identity": labels_identity, "ledger_root_identity": ledger_root_identity,
            "markets": topology, "counts": counts, "index_bytes": index_path.stat().st_size}


def load_entries(graph, ref):
    value = record(graph.get(ref), "qualification_inputs_v2", {"pages", "file_count", "staged_bytes", "validation"})
    validation = fields(value["validation"], {"started_at", "completed_at", "read_bytes"})
    require(timestamp(validation["started_at"]) <= timestamp(validation["completed_at"]), "reversed input validation interval")
    integer(validation["read_bytes"])
    entries, paths, staged_paths, total = [], set(), set(), 0
    for page in sequence(value["pages"], minimum=1, maximum=160):
        content = record(graph.get(page), "qualification_input_entries_v2", {"entries"})
        for entry in sequence(content["entries"], minimum=1, maximum=128):
            fields(entry, {"root", "path", "identities", "kind", "mandatory", "present", "missing_reason",
                           "generation", "staged", "started_at", "completed_at"})
            distinct_paths([entry["path"]])
            key = (identifier(entry["root"]), entry["path"].casefold())
            require(timestamp(entry["started_at"]) <= timestamp(entry["completed_at"]), "reversed input read interval")
            require(key not in paths, "duplicate input generation identity")
            paths.add(key)
            distinct_paths([entry["path"]])
            require(type(entry["present"]) is bool and type(entry["mandatory"]) is bool and
                    entry["kind"] in {"ledger", "labels", "payload", "config"}, "invalid input disposition")
            for identity in sequence(entry["identities"], minimum=1, maximum=256):
                text(identity, maximum=4096)
            if entry["present"]:
                staged = fields(entry["staged"], {"path", "sha256", "size"})
                distinct_paths([staged["path"]])
                require(staged["path"].startswith("files/"), "staged input escaped its file root")
                require(staged["path"].casefold() not in staged_paths, "staged bytes aliased by distinct source generations")
                staged_paths.add(staged["path"].casefold())
                digest(staged["sha256"])
                generation = fields(entry["generation"], {"device", "file_id", "size", "mtime_ns", "ctime_ns"})
                for name in ("device", "file_id"):
                    raw = generation[name]
                    require(type(raw) is str and len(raw) <= 40 and raw.isascii() and raw.isdigit(), "invalid filesystem generation identity")
                for name in ("size", "mtime_ns", "ctime_ns"):
                    integer(generation[name])
                require(generation["size"] == staged["size"], "source/staged generation byte count mismatch")
                total += integer(staged["size"], maximum=64 * 1024**3)
                require(entry["missing_reason"] is None and type(entry["generation"]) is dict,
                        "present input lacks generation proof")
            else:
                require(not entry["mandatory"] and entry["staged"] is None and entry["generation"] is None and
                        entry["missing_reason"] == "path_not_found", "required input was downgraded to optional absence")
            entries.append(entry)
            require(len(entries) <= MAX_INPUT_FILES, "input entry count exceeded")
    require(integer(value["file_count"]) == len(entries) and integer(value["staged_bytes"]) == total,
            "input manifest totals contradict dependency pages")
    return entries


class SealedAuditReader:
    """Resolve only declared staged bytes while retaining original lineage names.

    The caller revalidates the staged set after the audit; the per-invocation
    hash cache never applies to production paths or survives this reader.
    """

    def __init__(self, graph, inputs_ref, sources: SourceRoots, budget):
        self.root, self.sources, self.budget = graph.root, sources, budget
        self.entries = load_entries(graph, inputs_ref)
        self.by_key, self.hashed = {}, set()
        for entry in self.entries:
            require(entry["root"] in sources.roots, "input root has no adopted source binding")
            key = entry["root"], entry["path"].casefold()
            for identity in entry["identities"]:
                name, path = sources.locate(identity)
                require((name, path.casefold()) == key, "input identity alias points to another source")
            self.by_key[key] = entry

    def _entry(self, identity):
        name, path = self.sources.locate(str(identity))
        key = name, path.casefold()
        require(key in self.by_key, "audit attempted an unsealed dependency")
        return self.by_key[key]

    def _verify(self, entry):
        ref = entry["staged"]
        with verified_input(self.root, ref, self.budget) as handle:
            while handle.read(1024 * 1024):
                pass
        self.hashed.add((entry["root"], entry["path"].casefold()))

    def lineage(self, name, identity, missing_reason):
        if not identity:
            return {"source": name, "path": "", "sha256": "", "missing_payload_reason": missing_reason,
                    "status": "MISSING_WITH_REASON"}
        entry = self._entry(identity)
        if not entry["present"]:
            return {"source": name, "path": str(Path(identity)), "sha256": "", "missing_payload_reason": "path_not_found",
                    "status": "MISSING_WITH_REASON"}
        key = entry["root"], entry["path"].casefold()
        if key not in self.hashed:
            self._verify(entry)
        return {"source": name, "path": str(Path(identity)), "sha256": entry["staged"]["sha256"],
                "missing_payload_reason": "", "status": "HASHED"}

    def labels(self, identity):
        entry = self._entry(identity)
        require(entry["kind"] == "labels" and entry["mandatory"] and entry["present"], "audit labels are not mandatory sealed input")
        return label_rows(self.root, entry["staged"], self.budget)

    def ledgers(self, root_identity):
        name, root = self.sources.locate(str(root_identity))
        selected = [entry for entry in self.entries if entry["kind"] == "ledger"]
        require(selected, "audit ledger inventory is empty")
        for entry in sorted(selected, key=lambda item: item["path"]):
            require(entry["root"] == name and entry["path"].startswith(root + "/") and entry["mandatory"] and entry["present"],
                    "audit ledger escaped declared mandatory root")
            for row in ledger_rows(self.root, entry["staged"], self.budget):
                row = {**row}
                row.setdefault("ledger_path", str(self.sources.roots[name] / entry["path"]))
                yield row

    def verify_staged(self):
        for entry in self.entries:
            if entry["present"]:
                self._verify(entry)
        return True
