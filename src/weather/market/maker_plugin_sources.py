"""Explicit snapshot/forecast/trigger/ledger joins for the offline dry run.

Every supporting file is read at most once per run. Per-event files are kept
for the whole run inside an explicit, reported memory budget; shared files
(the observation-trigger journal and each market's settlement ledger) are
streamed once and indexed by event. Rows that cannot be point-in-time for any
minute of the run date are dropped at load, so a full day stays bounded.
"""
from bisect import bisect_right
from collections import Counter, OrderedDict
import codecs
import csv
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import re

from weather.collection.forecast_payload_cas import (
    RAW_BYTES_HASH_ALGORITHM,
    SHARED_FORECAST_PAYLOAD_CAS_KIND,
    SHARED_FORECAST_PAYLOAD_SCOPE,
    ForecastPayloadCASIntegrityError,
    shared_payload_ref,
    validate_nbm_shared_manifest_identity,
)
from weather.forecast_payload_contracts import NBM_NBP_ENCODING, NBM_NBP_MEDIA_TYPE, NBM_NBP_SOURCE
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.maker_plugin.inputs import band, event_identity, timestamp
from weather.market.maker_plugin.nbp import issue_time
from weather.market.maker_plugin_capture import MAX_FILE_BYTES, MAX_ROWS, encoded

LOAD_ERRORS = (ValueError, KeyError, TypeError, AttributeError, OSError, EOFError, csv.Error)
BAND_FIELDS = ("event_slug", "captured_at_utc", "condition_id", "bin_kind", "bin_value_c", "bin_value_hi_c")
NBP_HEADER = re.compile(rb"^\s*(\w+)\s+NBM\s+V\S+\s+NBP\s+GUIDANCE")
TOKEN_FILES = ("clob_tokens.jsonl", "clob_tokens.csv")
MAX_TOKEN_BATCHES = 64
# source_coverage name -> (time field, identity rule) exactly as the runner reports it.
COVERAGE_KEYS = (("snapshots", "captured_at_utc"), ("source_rows", "captured_at_utc"),
                 ("forecasts", "captured_at_utc"), ("explanations", "captured_at_utc"),
                 ("bulletins", "fetched_at"), ("triggers", "current_captured_at_utc"),
                 ("ledger_rows", "recorded_at_utc"))


def reason(exc):
    value = str(exc)
    return value if re.fullmatch(r"[a-zA-Z0-9_ .:-]{1,120}", value) else type(exc).__name__


def optional_time(value):
    try:
        return timestamp(value)
    except (ValueError, TypeError, AttributeError):
        return None  # Providers own refusal of malformed clocks; never guess here.


def compress_bands(rows):
    """Project band rows and drop captures identical to the previous capture.

    ``WeatherUniverse.bands`` uses only the latest capture at or before the
    decision time, so dropping an unchanged repeat cannot change any result.
    Rows without a parseable capture clock are kept verbatim for refusal.
    """
    groups, loose = {}, []
    for row in rows:
        when = optional_time(row.get("captured_at_utc"))
        if when is None:
            loose.append(row)
            continue
        groups.setdefault(when, []).append({k: row[k] for k in BAND_FIELDS if k in row})
    result, previous = [], None
    for when in sorted(groups):
        content = sorted(encoded({k: v for k, v in r.items() if k != "captured_at_utc"}) for r in groups[when])
        if content != previous:
            result.extend(groups[when])
            previous = content
    return result + loose


def token_batch(rows, slug):
    """One complete CLOB token capture -> one native-unit band row per condition."""
    when = rows[0].get("captured_at_utc")
    pairs = {}
    for row in rows:
        if row.get("event_slug") != slug:
            raise ValueError("token_event_mismatch")
        cid = str(row.get("condition_id") or "").lower()
        if not re.fullmatch(r"0x[0-9a-f]{64}", cid):
            raise ValueError("token_condition_invalid")
        # The capture's label parser reads unsigned digits: refuse negative labels.
        if re.search(r"(?:^|[^0-9])-[0-9]", str(row.get("range_label") or "").replace(" ", "")):
            raise ValueError("token_negative_label_unsupported")
        meta = (row.get("bin_kind"), row.get("bin_value"), row.get("bin_value_hi"))
        edges = band({"bin_kind": meta[0], "bin_value_c": meta[1], "bin_value_hi_c": meta[2]})
        outcome = row.get("outcome")
        if outcome not in ("Yes", "No") or outcome in pairs.setdefault(cid, {}):
            raise ValueError("token_outcome_invalid")
        token = str(row.get("clob_token_id") or "")
        if not re.fullmatch(r"[0-9]{1,100}", token):
            raise ValueError("token_id_invalid")
        pairs[cid][outcome] = (meta, edges, token)
    result = []
    for cid, sides in sorted(pairs.items()):
        if set(sides) != {"Yes", "No"} or sides["Yes"][1] != sides["No"][1]:
            raise ValueError("token_band_incomplete_pair")
        kind, value, hi = sides["Yes"][0]
        result.append({"event_slug": slug, "captured_at_utc": when, "condition_id": cid,
                       "bin_kind": kind, "bin_value_c": value, "bin_value_hi_c": hi,
                       "tokens": {"YES": sides["Yes"][2], "NO": sides["No"][2]}})
    return result


class Sources:
    def __init__(self, reader, day, markets, max_cache_bytes=512 * 1024**2):
        self.reader = reader
        start = datetime.combine(datetime.strptime(day, "%Y-%m-%d").date(), time(), timezone.utc)
        self.day_end = start + timedelta(days=1)
        # A daily-high forecast or NBP issue is eligible for at most 24 hours
        # after issue, and issue precedes capture; 48 hours is a safe margin.
        self.lookback_start = start - timedelta(days=2)
        self.markets = set(markets)
        self.target_window = (start.date() - timedelta(days=1), start.date() + timedelta(days=3))
        self.max_cache_bytes = max_cache_bytes
        self.errors = Counter()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.loaded = set()
        self.bad_sources = set()
        self.blobs = {}
        self.triggers_by_event = None
        self.trigger_error = False
        self.ledgers = {}
        self.pools = {}

    def error(self, source, exc):
        key = source + ":" + reason(exc)
        self.errors[key if key in self.errors or len(self.errors) < 64 else "other"] += 1
        self.bad_sources.add(source)

    def wanted(self, slug):
        try:
            spec, target = event_identity(slug)
        except (ValueError, TypeError, AttributeError):
            return False
        return spec.id in self.markets and self.target_window[0] <= target <= self.target_window[1]

    def keep(self, row, key, lookback=False):
        when = optional_time(row.get(key))
        if when is None:
            return True
        return when <= self.day_end and (not lookback or when >= self.lookback_start)

    def table(self, path, source, key="captured_at_utc", lookback=False):
        try:
            rows = self.reader.table(path, source)
        except LOAD_ERRORS as exc:
            self.error(source, exc)
            rows = []
        kept = [row for row in rows if self.keep(row, key, lookback)]
        self.reader.coverage[source + ".rows"] += len(kept)
        self.reader.coverage[source + ".rows_outside_run_window"] += len(rows) - len(kept)
        self.reader.coverage[source + (".files_with_rows" if rows else ".missing_or_empty")] += 1
        return kept

    def stream(self, path, source, visit):
        path = self.reader.variant(path)
        if not path.is_file():
            self.reader.coverage[source + ".missing_or_empty"] += 1
            return False
        self.reader.lines(path, visit, source)
        return True

    def triggers(self, slug):
        if self.triggers_by_event is None:
            self.triggers_by_event = {}
            def visit(line):
                if not line.strip():
                    return False
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record_not_object")
                if not self.wanted(row.get("event_slug")):
                    return False
                items = [r for r in row.get("trigger_context", {}).get("triggers", [row])
                         if not isinstance(r, dict) or self.keep(r, "current_captured_at_utc")]
                self.triggers_by_event.setdefault(row["event_slug"], []).extend(items)
                self.reader.coverage["triggers.rows"] += len(items)
                if self.reader.coverage["triggers.rows"] > MAX_ROWS:
                    raise ValueError("file_row_limit")
                return False
            try:
                self.stream(self.reader.root / "snapshots" / "observation_triggers.jsonl", "triggers", visit)
            except LOAD_ERRORS as exc:
                self.error("triggers", exc)
                self.trigger_error = True
                self.triggers_by_event = {}
        if self.trigger_error:
            self.bad_sources.add("triggers")
        return list(self.triggers_by_event.get(slug, []))

    def ledger(self, spec, slug):
        if spec.id not in self.ledgers:
            rows = {}
            def visit(line):
                if not line.strip():
                    return False
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record_not_object")
                # Later revisions can never be point in time for this run date.
                if self.wanted(row.get("event_slug")) and self.keep(row, "recorded_at_utc"):
                    rows.setdefault(row["event_slug"], []).append(row)
                    self.reader.coverage["settlements.rows"] += 1
                    if self.reader.coverage["settlements.rows"] > MAX_ROWS:
                        raise ValueError("file_row_limit")
                return False
            try:
                self.stream(self.reader.root / "settlements" / spec.id / "ledger.jsonl", "settlements", visit)
            except LOAD_ERRORS as exc:
                self.error("settlements", exc)
                rows = {}
            self.ledgers[spec.id] = rows
        return list(self.ledgers[spec.id].get(slug, []))

    def token_bands(self, root, slug):
        """First complete CLOB token batch, streamed; never a whole-file load."""
        for name in TOKEN_FILES:
            path = self.reader.variant(root / name)
            if not path.is_file():
                continue
            found, batch, header, scanned = [], [], None, 0
            def finish():
                nonlocal scanned
                scanned += 1
                self.reader.coverage["band_tokens.batches_scanned"] += 1
                try:
                    found.extend(token_batch(batch, slug))
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    self.error("band_tokens", exc)
                return bool(found) or scanned >= MAX_TOKEN_BATCHES
            def visit(line):
                nonlocal header, batch
                if not line.strip():
                    return False
                text = line.decode("utf-8-sig")
                if name.endswith(".csv"):
                    values = next(csv.reader([text]))
                    if header is None:
                        header = values
                        return False
                    if len(values) != len(header):
                        raise ValueError("token_csv_shape")
                    row = dict(zip(header, values))
                else:
                    row = json.loads(text)
                    if not isinstance(row, dict):
                        raise ValueError("record_not_object")
                if batch and row.get("captured_at_utc") != batch[0].get("captured_at_utc"):
                    if finish():
                        return True
                    batch = []
                if optional_time(row.get("captured_at_utc")) is None:
                    return True  # Unordered capture: stop, never guess.
                # A batch after the run date still carries the conditions'
                # immutable bands; the universe uses it only as identity.
                batch.append(row)
                return False
            try:
                self.reader.lines(path, visit, "band_tokens")
                if batch and not found and scanned < MAX_TOKEN_BATCHES:
                    finish()
            except LOAD_ERRORS as exc:
                self.error("band_tokens", exc)
            self.reader.coverage["band_tokens.events_with_batch" if found else "band_tokens.events_without_batch"] += 1
            return found
        self.reader.coverage["band_tokens.missing_file"] += 1
        return []

    def blob(self, key, expected_bytes, stations):
        """Hash-verify one shared CAS blob once per run; retain only station blocks."""
        if key in self.blobs:
            if "error" in self.blobs[key]:
                raise ValueError(self.blobs[key]["error"])  # Never reread a refused blob.
            return self.blobs[key]
        try:
            return self._verified_blob(key, expected_bytes, stations)
        except LOAD_ERRORS as exc:
            self.blobs[key] = {"error": reason(exc)}
            raise

    def _verified_blob(self, key, expected_bytes, stations):
        path = self.reader.root / "forecast_payload_cas" / shared_payload_ref(key)
        digest, decoder, size = hashlib.sha256(), codecs.getincrementaldecoder(NBM_NBP_ENCODING)(), 0
        blocks, active = {}, None
        def on_chunk(chunk):
            nonlocal size
            digest.update(chunk)
            decoder.decode(chunk)  # Strict UTF-8, exactly like the canonical replay.
            size += len(chunk)
        def visit(line):
            nonlocal active
            header = NBP_HEADER.match(line)
            if header:
                station = header.group(1).decode("ascii", "replace")
                active = station if station in stations else None
            if active is not None:
                blocks.setdefault(active, []).append(line.decode(NBM_NBP_ENCODING))
            return False
        self.reader.lines(path, visit, "nbp_blobs", on_chunk=on_chunk)
        decoder.decode(b"", final=True)
        if digest.hexdigest() != key:
            raise ValueError("retained_payload_hash_mismatch")
        if expected_bytes is not None and size != expected_bytes:
            raise ValueError("retained_payload_byte_count_mismatch")
        result = {station: "\n".join(lines) + "\n" for station, lines in blocks.items()}
        self.blobs[key] = result
        self.reader.coverage["nbp_blobs.verified"] += 1
        return result

    def shared_bulletin(self, row, spec, target):
        key = row["payload_hash"]
        if (row.get("payload_cas_kind") != SHARED_FORECAST_PAYLOAD_CAS_KIND
                or row.get("payload_hash_algorithm") != RAW_BYTES_HASH_ALGORITHM
                or str(row.get("payload_encoding") or "").lower() != NBM_NBP_ENCODING
                or row.get("payload_media_type") != NBM_NBP_MEDIA_TYPE):
            raise ValueError("shared_payload_contract_mismatch")
        if row.get("raw_payload_retained") is not True:
            raise ValueError("shared_payload_not_retained")
        if row.get("payload_ref") != shared_payload_ref(key):
            raise ValueError("shared_payload_ref_mismatch")
        try:
            identity = validate_nbm_shared_manifest_identity(row, expected_station_id=spec.icao)
        except ForecastPayloadCASIntegrityError:
            raise ValueError("shared_payload_identity_invalid") from None
        if identity["target_date"] != target.isoformat():
            raise ValueError("retained_payload_identity_mismatch")
        expected = row.get("payload_bytes")
        stations = {s.icao for s in BUILTIN_SPECS if s.id in self.markets}
        text = self.blob(key, int(expected) if expected not in (None, "") else None, stations).get(spec.icao, "")
        # The provider receives the verified station extract; the national blob
        # hash is retained as lineage. Parsing an extract equals parsing the blob.
        return {"source": NBM_NBP_SOURCE, "station_id": identity["station_id"], "target_date": identity["target_date"],
                "source_url": row.get("source_url"), "fetched_at": row.get("fetched_at") or row["captured_at_utc"],
                "payload_hash": hashlib.sha256(text.encode()).hexdigest(), "text": text,
                "source_payload_hash": key, "payload_ref": row["payload_ref"]}

    def legacy_bulletin(self, row, root, spec, target):
        key = row["payload_hash"]
        # Derive the market-local CAS path, never follow an arbitrary raw_payload_path.
        path = root / "forecast_payloads" / "sha256" / key[:2] / (key + ".json")
        raw = self.reader.read(self.reader.variant(path), source="nbp_legacy")
        if hashlib.sha256(raw.removesuffix(b"\n")).hexdigest() != key:
            raise ValueError("retained_payload_hash_mismatch")
        payload = json.loads(raw)
        if payload.get("station_id") != spec.icao or payload.get("target_date") != target.isoformat():
            raise ValueError("retained_payload_identity_mismatch")
        return payload

    def window_slugs(self, spec):
        first, last = self.target_window
        return [event_slug_for_date(first + timedelta(days=n), spec.id) for n in range((last - first).days + 1)]

    def market_bulletins(self, spec):
        """One station's NBP bulletins from every run-window event folder of its market.

        Snapshot capture is local-T+0 only (``snapshot_tracker`` pre-local-day
        guard), so a T+1/T+2 event folder holds no rows before its local day.
        An NBP bulletin is a national cycle product: the copy captured for the
        T+0 event also carries later targets' maxima. Each manifest is verified
        against the event it was captured for; the provider then selects the
        slot for its own target and skips a cycle that does not hold it.
        """
        if spec.id not in self.pools:
            manifests, errors = [], []
            for slug in self.window_slugs(spec):
                root = self.reader.root / "snapshots" / slug
                before = set(self.bad_sources)
                rows = self.table(root / "forecast_payloads.jsonl", "nbp_pool_manifests", lookback=True)
                if "nbp_pool_manifests" in self.bad_sources - before:
                    errors.append({"captured_at_utc": None})  # Unreadable: availability unknown.
                self.bad_sources = before
                manifests.extend((root, slug, row) for row in rows if row.get("source") == NBM_NBP_SOURCE)
            bulletins, nbp_errors = self.bulletins(manifests, spec)
            self.fetch_lateness(bulletins)
            self.pools[spec.id] = (bulletins, errors + nbp_errors)
        return self.pools[spec.id]

    def fetch_lateness(self, bulletins):
        """Earliest capture of each station extract against its expected availability.

        A cycle's expected availability (issue + 1 h, pre-registered) is also the
        previous cycle's expiry, so a late capture is a gap with no eligible issue.
        """
        for bulletin in bulletins:
            try:
                issue = issue_time(bulletin["text"].partition("\n")[0])
            except ValueError:
                continue
            late = (timestamp(bulletin["fetched_at"]) - issue - timedelta(hours=1)).total_seconds() / 60
            bucket = next((name for limit, name in ((0, "on_time"), (15, "late_0_15m"), (30, "late_15_30m"),
                                                    (60, "late_30_60m")) if late <= limit), "late_over_60m")
            self.reader.coverage["nbp_capture_vs_expected_availability." + bucket] += 1

    def bulletins(self, manifests, spec):
        found, seen, size, nbp_errors = {}, set(), 0, []
        for root, slug, row in sorted(manifests, key=lambda m: str(m[2].get("captured_at_utc", ""))):
            self.reader.check()
            captured, fetched = optional_time(row.get("captured_at_utc")), optional_time(row.get("fetched_at"))
            if captured is not None and captured < self.lookback_start and (fetched is None or fetched < self.lookback_start):
                self.reader.coverage["nbp.rows_before_lookback"] += 1
                continue  # Issue <= fetch <= capture: expired before the run date.
            try:
                key = row["payload_hash"]
                if not re.fullmatch(r"[0-9a-f]{64}", str(key)):
                    raise ValueError("invalid_retained_payload_hash")
                if row.get("event_slug") not in (None, "", slug):
                    raise ValueError("retained_payload_identity_mismatch")
                _, captured_for = event_identity(slug)
                if (key, slug) in seen:
                    continue
                if row.get("payload_storage_scope") == SHARED_FORECAST_PAYLOAD_SCOPE:
                    payload = self.shared_bulletin(row, spec, captured_for)
                else:
                    payload = self.legacy_bulletin(row, root, spec, captured_for)
                # The manifest's capture is an additional availability bound.
                fetched = max(timestamp(payload["fetched_at"]), timestamp(row["captured_at_utc"]))
                payload["fetched_at"] = fetched.isoformat()
                payload["captured_for_target_date"] = payload.pop("target_date")
                seen.add((key, slug))
                # One station extract per text; its earliest availability wins.
                prior = found.get(payload["payload_hash"])
                if prior is None:
                    size += len(payload["text"])
                    if size > MAX_FILE_BYTES:
                        raise ValueError("bulletin_memory_limit")
                if prior is None or fetched < timestamp(prior["fetched_at"]):
                    found[payload["payload_hash"]] = payload
            except LOAD_ERRORS as exc:
                self.error("nbp", exc)
                nbp_errors.append({"captured_at_utc": row.get("captured_at_utc")})
        self.reader.coverage["nbp.rows"] += len(found)
        return list(found.values()), nbp_errors

    def coverage_times(self, result, slug, spec, target):
        """Sorted identity-matched clocks, so per-minute coverage is a bisection."""
        times = {}
        for name, key in COVERAGE_KEYS:
            found = []
            for row in result[name]:
                identity = (row.get("station_id") == spec.icao and row.get("target_date") == target.isoformat()
                            if name == "bulletins" else row.get("event_slug") == slug)
                when = optional_time(row.get(key)) if identity else None
                if when is not None:
                    found.append(when)
            times[name] = sorted(found)
        return times

    def for_event(self, slug):
        if slug in self.cache:
            self.cache.move_to_end(slug)
            self.reader.coverage["cache.hits"] += 1
            return self.cache[slug][1]
        self.reader.coverage["cache.reloads" if slug in self.loaded else "cache.loads"] += 1
        self.bad_sources = set()
        spec, target = event_identity(slug)  # Registered canonical slug only.
        root = self.reader.root / "snapshots" / slug
        snapshots = self.table(root / "snapshots_long.csv", "snapshots")
        forecasts = self.table(root / "forecasts_long.csv", "forecasts", lookback=True)
        explanations = self.table(root / "snapshot_explanations.jsonl", "explanations")
        manifests = self.table(root / "forecast_payloads.jsonl", "nbp_manifests")
        observation_sources = self.table(root / "observation_payloads.jsonl", "observation_sources")
        pool, nbp_errors = self.market_bulletins(spec)
        # Station extracts are target-independent; the provider selects this
        # event's slot and refuses a cycle that does not hold its maximum.
        bulletins = [dict(b, target_date=target.isoformat()) for b in pool]
        triggers = self.triggers(slug)
        ledger = self.ledger(spec, slug)
        identity = self.token_bands(root, slug)
        if identity and optional_time(identity[0]["captured_at_utc"]) > self.day_end:
            self.reader.coverage["band_tokens.batch_after_run_date"] += 1
        snapshot_times = {optional_time(r.get("captured_at_utc")) for r in snapshots}
        tokens = [r for r in identity if optional_time(r["captured_at_utc"]) not in snapshot_times
                  and optional_time(r["captured_at_utc"]) <= self.day_end]
        # Source payload manifests carry captured release fields. In production
        # release_calibration_method may be absent: never fabricate that projection.
        result = dict(snapshots=snapshots, source_rows=manifests + observation_sources, forecasts=forecasts,
                      explanations=explanations, bulletins=bulletins, triggers=triggers,
                      ledger_rows=[r for r in ledger if r.get("event_slug") == slug],
                      band_rows=compress_bands(snapshots + tokens), identity_band_rows=identity,
                      band_token_batch_utc=identity[0]["captured_at_utc"] if identity else None,
                      bad_sources=sorted(self.bad_sources - {"nbp"}), nbp_errors=nbp_errors)
        result["coverage_times"] = self.coverage_times(result, slug, spec, target)
        result["loaded_rows"] = {name: len(result[name]) for name, _ in COVERAGE_KEYS}
        size = 0
        for name in ("snapshots", "source_rows", "forecasts", "explanations", "bulletins", "triggers",
                     "ledger_rows", "band_rows", "identity_band_rows"):
            for row in result[name]:
                self.reader.check()
                size += len(encoded(row))
        self.loaded.add(slug)
        while self.cache and self.cache_bytes + size > self.max_cache_bytes:
            _, (old_size, _) = self.cache.popitem(last=False)
            self.cache_bytes -= old_size
            self.reader.coverage["cache.evictions"] += 1
        if size <= self.max_cache_bytes:
            self.cache[slug] = (size, result)
            self.cache_bytes += size
            peak = self.reader.coverage["cache.bytes_peak"]
            self.reader.coverage["cache.bytes_peak"] = max(peak, self.cache_bytes)
        else:
            self.reader.coverage["cache.event_over_budget"] += 1
        return result


def point_in_time_count(times, now):
    return bisect_right(times, now)
