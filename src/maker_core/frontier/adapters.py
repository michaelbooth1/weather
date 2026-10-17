"""Real-object adapters for the frontier runner (item 330 build 4): build 1's fill v3, build 2's fill cost, and
the counterfactual-tape context the fill cost reads.

Each adapter refuses a version or digest it was not built for, so a later change in build 1, build 2 or the tape
cannot be scored silently under an older binding.

``fill_v3_model()``
    A ``seams.QueueFillModel`` bound to the real ``maker_core.replay.fill_v3`` kernel (``VERSION`` and ``LABEL``
    checked). ``FILL_V3_BINDING`` is its ``seams.binding`` string, the value of the preregistration's
    ``Fill model:`` line.

``RecordingFillCost``
    Wraps build 2's real ``TableFillCostProvider`` (exact type, ``TABLE_VERSION`` and table digest checked). The
    runner asks it once per decision with a ``CostQuery`` (both legs' ``FillContext``); it estimates each leg,
    keeps the stricter one (largest markout upper bound; a veto on either leg vetoes) and records every decision:
    status, veto and the action taken. The only veto action the runner models is ``cancel`` (the quote is
    withdrawn); ``widen`` is refused, because a widened quote is another grid width, already on the grid.

``CfTapeContexts``
    The runner's ``context_builder``. It reads the counterfactual tape's ``cf_minutes`` Parquet (schema of
    ``weather.market.maker_counterfactual_tape`` tape revision 1, read from its file layout, never imported:
    core may not import ``weather``) for a ``strictly_through`` backlog only. Per UTC day it checks the frontier
    embargo on the day **before** opening anything, then the day receipt (name, revisions, basis, fill rule,
    ``match``), the Parquet file's size and SHA-256 against the receipt, and the schema and metadata against
    ``CF_MINUTES_SCHEMA``. For a decision at ``at`` it uses, per leg side, the latest tape context at or before
    ``at`` and no older than ``BOOK_MAX_AGE_S``; with neither leg found it returns None (the runner counts that
    decision in ``cost_unavailable`` and the 0.0043 floor applies).
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from maker_core.contracts import Unavailable
from maker_core.evidence.journal import digest
from maker_core.frontier import embargo
from maker_core.frontier.seams import CONSTANT_ADVERSE_MARKOUT, QueueFillModel, binding
from maker_core.quoting import fill_cost
from maker_core.replay import fill_v3

FILL_V3_VERSION = "fill-v3.0"
FILL_V3_LABEL = "queue_aware"
FILL_V3_NAME = "v3-queue"
TABLE_VERSION = "maker_core.toxicity_table.v0.1"

TAPE_NAME = "maker_counterfactual_tape"
TAPE_REVISION = 1
DAY_RECEIPT_NAME = "cf_tape_day_receipt"
RECEIPT_REVISION = 1
BASIS = "counterfactual"
FILL_RULE = "strictly_through"
MINUTES_TABLE = "cf_minutes"
BOOK_MAX_AGE_S = 120
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_TS = "timestamp[us, tz=UTC]"
CF_MINUTES_SCHEMA = (
    ("utc_day", "string"), ("condition_id", "string"), ("market_id", "string"), ("station", "string"),
    ("event_slug", "string"), ("event_date", "date32[day]"), ("token_id", "string"), ("maker_side", "string"),
    ("minute_utc", _TS), ("quote_price", "double"), ("quote_ask", "double"), ("quote_snapshot_at_utc", _TS),
    ("ctx_at_utc", _TS), ("ctx_horizon_days", "int32"), ("ctx_minutes_to_close", "double"),
    ("ctx_minutes_from_scheduled_print", "double"), ("ctx_minutes_since_model_cycle", "double"),
    ("ctx_decided_probability", "double"), ("ctx_book_imbalance", "double"), ("ctx_depth_shares", "double"),
    ("ctx_last_print_size", "double"), ("ctx_burst_prints", "int32"), ("ctx_sweep_bands", "int32"),
    ("ctx_ft_info_clock", _TS), ("ctx_ft_book", _TS), ("ctx_ft_prints", _TS), ("basis", "string"),
)
CF_MINUTES_METADATA = {"tape": TAPE_NAME, "tape_revision": str(TAPE_REVISION), "basis": BASIS,
                       "table": MINUTES_TABLE}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AdapterRefused(ValueError):
    """An injected object or input is not the version, digest or schema this adapter was built for."""


# -- build 1: fill v3 --------------------------------------------------------------------------------------
def fill_v3_model(kernel=fill_v3) -> QueueFillModel:
    """The queue-aware fill model on the real fill-v3 kernel; refuses any other kernel or version."""
    if kernel is not fill_v3:
        raise AdapterRefused("fill_kernel_is_not_maker_core.replay.fill_v3")
    if getattr(kernel, "VERSION", None) != FILL_V3_VERSION or getattr(kernel, "LABEL", None) != FILL_V3_LABEL:
        raise AdapterRefused("fill_kernel_version_mismatch")
    return QueueFillModel(kernel, name=FILL_V3_NAME)


FILL_V3_BINDING = binding(fill_v3_model())


# -- build 2: the fill cost ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class CostQuery:
    """What the runner's context builder hands the cost adapter for one decision."""
    condition_id: str
    at: datetime
    strategy: str
    contexts: tuple  # FillContext per maker side found (YES and/or NO leg)


@dataclass(frozen=True)
class CombinedEstimate:
    """The stricter leg: duck-typed to ``FillCostEstimate`` for ``seams.fill_cost_terms``."""
    adverse_markout_upper: float
    veto: str | None
    status: str
    table_digest: str
    sides: tuple


UNAVAILABLE_STATUSES = ("NO_CONTEXT", "UNAVAILABLE")


class RecordingFillCost:
    """Build 2's real table provider behind a version/digest check, recording each decision (module doc)."""

    def __init__(self, provider, *, expected_table_digest: str, expected_table_version: str = TABLE_VERSION,
                 veto_action: str = "cancel"):
        if type(provider) is not fill_cost.TableFillCostProvider:
            raise AdapterRefused("fill_cost_provider_is_not_TableFillCostProvider")
        if (fill_cost.TABLE_VERSION != expected_table_version
                or provider.table.get("table_version") != expected_table_version):
            raise AdapterRefused("toxicity_table_version_mismatch")
        if not isinstance(expected_table_digest, str) or provider.digest != expected_table_digest:
            raise AdapterRefused("toxicity_table_digest_mismatch")
        if veto_action not in fill_cost.VETO_ACTIONS:
            raise AdapterRefused("unknown_veto_action")
        if veto_action != "cancel":
            raise AdapterRefused("veto_action_widen_not_modelled_by_the_frontier_runner")
        self.provider, self.table_digest, self.veto_action = provider, provider.digest, veto_action
        self.decisions = []
        self._cache = {}

    def _side(self, context):
        key = (context.maker_side, context.at_utc, digest(context.as_dict()))
        if key not in self._cache:
            self._cache[key] = self.provider.estimate(context)
        return self._cache[key]

    def estimate(self, query):
        if query is None:
            self.decisions.append((None, None, None, "NO_CONTEXT", None, "quote", None))
            return None
        if not isinstance(query, CostQuery):
            raise AdapterRefused("cost_query_required")
        if not query.contexts:  # the tape had no fresh row: traceable to (at, condition_id), floor applies
            self.decisions.append((query.at.isoformat(), query.condition_id, query.strategy, "NO_CONTEXT", None,
                                   "quote", None))
            return None
        sides, markouts, vetoes, statuses = [], [], [], []
        for context in query.contexts:
            estimate = self._side(context)
            if isinstance(estimate, fill_cost.FillCostEstimate):
                if estimate.table_digest != self.table_digest:
                    raise AdapterRefused("toxicity_table_digest_mismatch")
                markouts.append(estimate.adverse_markout_upper)
                statuses.append(estimate.status)
                if estimate.veto:
                    vetoes.append(estimate.veto)
                sides.append((context.maker_side, estimate.status, estimate.veto, estimate.adverse_markout_upper))
            elif isinstance(estimate, Unavailable):
                sides.append((context.maker_side, "UNAVAILABLE", None, None))
            else:
                raise AdapterRefused("unexpected_fill_cost_result")
        veto = "SWEEP" if "SWEEP" in vetoes else ("BURST" if vetoes else None)
        if not markouts:
            result, status, markout = None, "UNAVAILABLE", None
        else:
            markout = max(max(markouts), CONSTANT_ADVERSE_MARKOUT)
            if not math.isfinite(markout):
                raise AdapterRefused("nonfinite_markout")
            status = "OK" if set(statuses) == {"OK"} and len(markouts) == len(query.contexts) else (
                "PARTIAL" if len(markouts) < len(query.contexts) else "UNDERPOWERED")
            result = CombinedEstimate(markout, veto, status, self.table_digest, tuple(sides))
        self.decisions.append((query.at.isoformat(), query.condition_id, query.strategy, status, veto,
                               self.veto_action if veto else "quote", markout))
        return result

    def unavailable(self) -> tuple[int, int]:
        """(decisions without a provider markout, all decisions): the former fall back to the 0.0043 floor."""
        missing = sum(1 for d in self.decisions if d[3] in UNAVAILABLE_STATUSES)
        return missing, len(self.decisions)

    def summary(self) -> dict:
        counts = {}
        for _, _, _, status, veto, action, _ in self.decisions:
            key = "%s|%s|%s" % (status, veto or "-", action)
            counts[key] = counts.get(key, 0) + 1
        missing, total = self.unavailable()
        return {"provider": "maker_core.quoting.fill_cost.TableFillCostProvider", "table_version": TABLE_VERSION,
                "table_digest": self.table_digest, "veto_action": self.veto_action, "decisions": total,
                "cost_unavailable": missing, "cost_unavailable_share": missing / total if total else 0.0,
                "by_status_veto_action": dict(sorted(counts.items())),
                "decision_log_digest": digest([list(d) for d in self.decisions])}


# -- the counterfactual tape context -----------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _utc(value):
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AdapterRefused("cf_tape_naive_timestamp")
    return value.astimezone(timezone.utc)


class CfTapeContexts:
    """``context_builder`` over a ``strictly_through`` cf tape backlog (module doc). Read-only."""

    def __init__(self, tape_dir, *, purpose: str, now=None, max_age_s: int = BOOK_MAX_AGE_S, conditions=None):
        """``conditions``, when given, is the only bands whose rows are ever read: the Parquet read itself is
        filtered on ``condition_id`` (``pq.read_table(filters=...)``), so another band's row is never
        materialised, and a query for another band refuses. Tape condition IDs are compared as given and
        lower-cased."""
        if purpose not in embargo.PURPOSES or purpose == "fit":
            raise AdapterRefused("cf_tape_purpose")
        self.root, self.purpose, self.now = Path(tape_dir), purpose, now
        self.conditions = None if conditions is None else frozenset(str(c).lower() for c in conditions)
        self._filter_values = None if conditions is None else sorted(
            {str(c) for c in conditions} | {str(c).lower() for c in conditions})
        self.max_age = timedelta(seconds=max_age_s)
        self._days, self.receipts = {}, {}
        self.queried = set()  # (day, condition_id lower) of every query, for ``bands_without_rows``

    def _check(self, *values):
        if self.now is None:
            embargo.check(self.purpose, *values)
        else:
            embargo.check(self.purpose, *values, now=self.now)

    def _load(self, day: date):
        self._check(day)  # before any byte of the day is opened
        receipt_path = self.root / "receipts" / (day.isoformat() + ".json")
        table_path = self.root / "tape" / ("utc_day=" + day.isoformat()) / (MINUTES_TABLE + ".parquet")
        if not receipt_path.is_file() or not table_path.is_file():
            raise AdapterRefused("cf_tape_day_missing: " + day.isoformat())
        raw = receipt_path.read_bytes()
        if len(raw) > MAX_RECEIPT_BYTES:
            raise AdapterRefused("cf_tape_receipt_too_large")
        receipt = json.loads(raw)
        expected = {"receipt": DAY_RECEIPT_NAME, "receipt_revision": RECEIPT_REVISION, "tape": TAPE_NAME,
                    "tape_revision": TAPE_REVISION, "basis": BASIS, "utc_day": day.isoformat(),
                    "fill_rule": FILL_RULE, "match": True}
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise AdapterRefused("cf_tape_receipt_" + key)
        output = (receipt.get("outputs") or {}).get(MINUTES_TABLE) or {}
        sha = output.get("sha256")
        if not isinstance(sha, str) or not _SHA256.match(sha):
            raise AdapterRefused("cf_tape_receipt_sha256")
        if table_path.stat().st_size != output.get("bytes") or _sha256_file(table_path) != sha:
            raise AdapterRefused("cf_tape_minutes_sha256_mismatch")
        import pyarrow.parquet as pq

        # schema, metadata and row count come from the file footer: file checks, not row reads
        footer = pq.ParquetFile(table_path)
        file_schema = footer.schema_arrow
        schema = tuple((f.name, str(f.type)) for f in file_schema)
        if schema != CF_MINUTES_SCHEMA:
            raise AdapterRefused("cf_tape_schema_mismatch")
        metadata = {k.decode(): v.decode() for k, v in (file_schema.metadata or {}).items()}
        if any(metadata.get(k) != v for k, v in CF_MINUTES_METADATA.items()):
            raise AdapterRefused("cf_tape_metadata_mismatch")
        file_rows = footer.metadata.num_rows
        if file_rows != output.get("rows"):
            raise AdapterRefused("cf_tape_row_count_mismatch")
        if self.conditions is None:
            table = pq.read_table(table_path)
        else:
            table = pq.read_table(table_path, filters=[("condition_id", "in", self._filter_values)])
        index = {}
        for row in table.to_pylist():
            if row["utc_day"] != day.isoformat() or row["basis"] != BASIS:
                raise AdapterRefused("cf_tape_row_outside_its_day")
            at = _utc(row["ctx_at_utc"])
            if at is None:
                continue
            index.setdefault((row["condition_id"].lower(), row["maker_side"]), []).append((at, row))
        for key, rows in index.items():
            rows.sort(key=lambda pair: pair[0])
            index[key] = ([r[0] for r in rows], [r[1] for r in rows])
        self.receipts[day.isoformat()] = {"receipt_sha256": hashlib.sha256(raw).hexdigest(), "minutes_sha256": sha,
                                          "rows": file_rows}
        self._days[day] = index
        return index

    def _context(self, row):
        times = {"info_clock": row["ctx_ft_info_clock"], "book": row["ctx_ft_book"], "prints": row["ctx_ft_prints"]}
        times = {k: _utc(v) for k, v in times.items() if v is not None}
        at = _utc(row["ctx_at_utc"])
        self._check(at, *times.values())
        return fill_cost.FillContext(
            at_utc=at, maker_side=row["maker_side"], horizon_days=int(row["ctx_horizon_days"]),
            minutes_to_close=row["ctx_minutes_to_close"],
            minutes_from_scheduled_print=row["ctx_minutes_from_scheduled_print"],
            minutes_since_model_cycle=row["ctx_minutes_since_model_cycle"],
            decided_probability=row["ctx_decided_probability"], book_imbalance=row["ctx_book_imbalance"],
            depth_shares=row["ctx_depth_shares"], last_print_size=row["ctx_last_print_size"],
            burst_prints=int(row["ctx_burst_prints"]), sweep_bands=int(row["ctx_sweep_bands"]),
            feature_times=times)

    def bands_without_rows(self) -> list:
        """[(day ISO, condition_id)] queried on a day whose tape holds no row at all for that band: a coverage
        hole (or a case mismatch the filtered read could not match), never a silent fall back to the floor."""
        missing = []
        for day, cid in sorted(self.queried):
            index = self._days.get(day, {})
            if not any((cid, side) in index for side in ("YES", "NO")):
                missing.append((day.isoformat(), cid))
        return missing

    def __call__(self, *, condition_id, at, band=None, strategy=None):
        at = _utc(at)
        self._check(at)
        if self.conditions is not None and str(condition_id).lower() not in self.conditions:
            raise AdapterRefused("cf_tape_condition_not_kept")
        day = at.date()
        index = self._days.get(day)
        if index is None:
            index = self._load(day)
        self.queried.add((day, str(condition_id).lower()))
        contexts = []
        for side in ("YES", "NO"):
            times, rows = index.get((str(condition_id).lower(), side), ((), ()))
            position = bisect_right(times, at) - 1
            if position >= 0 and at - times[position] <= self.max_age:
                contexts.append(self._context(rows[position]))
        # no fresh row: an empty query, so the recording adapter logs the miss with its instant and band
        return CostQuery(str(condition_id), at, str(strategy), tuple(contexts))
