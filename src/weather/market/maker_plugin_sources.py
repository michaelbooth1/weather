"""Explicit snapshot/forecast/trigger/ledger joins for the offline dry run."""
from collections import Counter, OrderedDict
import hashlib
import json
import re

from weather.market.maker_plugin.inputs import event_identity, timestamp
from weather.market.maker_plugin_capture import MAX_FILE_BYTES, encoded


def reason(exc):
    value = str(exc)
    return value if re.fullmatch(r"[a-zA-Z0-9_ .:-]{1,120}", value) else type(exc).__name__


class Sources:
    def __init__(self, reader):
        self.reader = reader
        self.errors = Counter()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.bad_sources = set()

    def error(self, source, exc):
        key = source + ":" + reason(exc)
        self.errors[key if key in self.errors or len(self.errors) < 64 else "other"] += 1
        self.bad_sources.add(source)

    def table(self, path, source):
        try:
            rows = self.reader.table(path)
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            self.error(source, exc)
            rows = []
        self.reader.coverage[source + ".rows"] += len(rows)
        self.reader.coverage[source + (".files_with_rows" if rows else ".missing_or_empty")] += 1
        return rows

    def for_event(self, slug):
        if slug in self.cache:
            self.cache.move_to_end(slug)
            return self.cache[slug][1]
        self.bad_sources = set()
        spec, target = event_identity(slug)  # Registered canonical slug only.
        root = self.reader.root / "snapshots" / slug
        snapshots = self.table(root / "snapshots_long.csv", "snapshots")
        forecasts = self.table(root / "forecasts_long.csv", "forecasts")
        explanations = self.table(root / "snapshot_explanations.jsonl", "explanations")
        manifests = self.table(root / "forecast_payloads.jsonl", "nbp_manifests")
        observation_sources = self.table(root / "observation_payloads.jsonl", "observation_sources")
        bulletins, hashes, size = [], set(), 0
        for row in sorted(manifests, key=lambda r: r.get("captured_at_utc", "")):
            self.reader.check()
            if row.get("source") != "nbm_probabilistic_tmax":
                continue
            try:
                key = row["payload_hash"]
                if not re.fullmatch(r"[0-9a-f]{64}", key):
                    raise ValueError("invalid_retained_payload_hash")
                if key in hashes:
                    continue
                # Derive the local CAS path, never follow an arbitrary raw_payload_path.
                path = root / "forecast_payloads" / "sha256" / key[:2] / (key + ".json")
                raw = self.reader.read(self.reader.variant(path))
                if hashlib.sha256(raw.removesuffix(b"\n")).hexdigest() != key:
                    raise ValueError("retained_payload_hash_mismatch")
                payload = json.loads(raw)
                if payload.get("station_id") != spec.icao or payload.get("target_date") != target.isoformat():
                    raise ValueError("retained_payload_identity_mismatch")
                # The manifest's capture is an additional availability bound.
                fetched = max(timestamp(payload["fetched_at"]), timestamp(row["captured_at_utc"]))
                payload["fetched_at"] = fetched.isoformat()
                size += len(raw)
                if size > MAX_FILE_BYTES:
                    raise ValueError("bulletin_memory_limit")
                bulletins.append(payload)
                hashes.add(key)
            except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
                self.error("nbp", exc)
        self.reader.coverage["nbp.rows"] += len(bulletins)
        events = self.table(self.reader.root / "snapshots" / "observation_triggers.jsonl", "triggers")
        triggers = []
        for row in events:
            self.reader.check()
            if row.get("event_slug") == slug:
                triggers.extend(row.get("trigger_context", {}).get("triggers", [row]))
        ledger = self.table(self.reader.root / "settlements" / spec.id / "ledger.jsonl", "settlements")
        # Source payload manifests carry captured release fields. In production
        # release_calibration_method may be absent: never fabricate that projection.
        result = dict(snapshots=snapshots, source_rows=manifests + observation_sources, forecasts=forecasts,
                           explanations=explanations, bulletins=bulletins, triggers=triggers,
                           ledger_rows=[r for r in ledger if r.get("event_slug") == slug],
                           bad_sources=sorted(self.bad_sources))
        size = 0
        for rows in result.values():
            for row in rows:
                self.reader.check()
                size += len(encoded(row))
        if size <= MAX_FILE_BYTES:
            while self.cache and self.cache_bytes + size > MAX_FILE_BYTES:
                _, (old_size, _) = self.cache.popitem(last=False)
                self.cache_bytes -= old_size
            self.cache[slug] = (size, result)
            self.cache_bytes += size
        return result
