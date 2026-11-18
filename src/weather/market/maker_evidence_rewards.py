"""88a reward records by change trigger, with the VR-4 ``/rewards/markets/current`` sweep.

Data layer v2 S9 (docs/operations/DATA_LAYER_V2_PLAN.md S2+S9 row). Before S9 the core
recorder read ``/rewards/markets/<condition>`` for every selected band every minute, about
83% of its public REST. Selection never used those replies (ranking uses Gamma terms), so the
record is retained on change instead:

* **Sweep.** One paged pass over ``/rewards/markets/current`` at most every
  ``SWEEP_SECONDS``, read a few pages per cycle. Each page is journaled as a bounded
  projection (row count, cursor, hash of its canonical rows) and the per-condition sweep
  rows of selected bands are journaled change-only (``rewards_current`` rows, a full baseline
  at the start of each segment). A ``rewards_sweep`` event closes each completed pass.
* **Trigger.** A selected band's full per-condition record is read when it is first
  selected, when its Gamma terms change, when its sweep row changes, every
  ``STALE_RECHECK_SECONDS`` while the sweep is stale or switched off, and at the latest
  every ``BACKSTOP_SECONDS``. Due reads are ordered by reason, then age, and capped per
  cycle; built-in bands are served before recorder-only pilot bands.

Sweep failures are isolated: they are journaled and counted and never fail a cycle; the
trigger falls back to the stale-recheck cadence. Every request still goes through the
journaling ``PublicReader``.
"""
from __future__ import annotations

import time

from weather.market.maker_evidence_public import CLOB, REWARDS_CURRENT_PATH, reward_record, reward_rate
from weather.market.maker_evidence_store import digest, encoded

SWEEP_SECONDS = 900
SWEEP_PAGES_PER_CYCLE = 10
MAX_SWEEP_PAGES = 120
SWEEP_STALE_SECONDS = 1800
STALE_RECHECK_SECONDS = 900
BACKSTOP_SECONDS = 3600
MAX_TRIGGERED_READS_PER_CYCLE = 20
# Public REST budget of the core recorder after S9 (0.4 req/s; the plan's acceptance bound).
REQUEST_BUDGET_PER_HOUR = 1440
TERMINAL_CURSORS = ("", "LTE=", "-1")
REASONS = ("first", "terms_changed", "sweep_changed", "sweep_stale", "backstop")


def sweep_row(row):
    """The sweep's per-condition content that triggers a re-read (documented reward fields)."""
    return {key: row.get(key) for key in ("condition_id", "rewards_max_spread", "rewards_min_size",
                                          "total_daily_rate", "rewards_config")}


def page_projection(payload):
    rows = payload["data"]
    if not isinstance(rows, list):
        raise ValueError("rewards sweep page data is not a list")
    return {"next_cursor": payload.get("next_cursor"), "rows": len(rows),
            "rows_sha256": digest(encoded([sweep_row(row) for row in rows])),
            "representation": "rewards_sweep_page_projection"}


class RewardSweep:
    """Incremental paged pass; the committed state changes only at a terminal cursor."""

    def __init__(self, reader, *, clock=time.monotonic):
        self.reader, self.clock = reader, clock
        self.state, self.rows, self.completed_at, self.generation = {}, {}, None, 0
        self.cursor, self.partial, self.pages, self.seen_cursors = None, None, 0, set()
        self.errors, self.pages_read, self.last_error = 0, 0, None
        self.last_changed, self.last_removed = 0, 0
        self.retry_at = None

    def due(self):
        if self.partial is not None:
            return True
        if self.retry_at is not None and self.clock() < self.retry_at:
            return False
        return self.completed_at is None or self.clock() - self.completed_at >= SWEEP_SECONDS

    def fresh(self):
        return self.completed_at is not None and self.clock() - self.completed_at <= SWEEP_STALE_SECONDS

    def age_seconds(self):
        return None if self.completed_at is None else self.clock() - self.completed_at

    def _reset(self):
        self.cursor, self.partial, self.pages, self.seen_cursors = None, None, 0, set()

    def step(self, *, max_pages=SWEEP_PAGES_PER_CYCLE):
        """Read up to ``max_pages``; returns ``{condition: sweep_row}`` on a completed pass, else None."""
        if not self.due():
            return None
        if self.partial is None:
            self.partial = {}
        try:
            for _ in range(max_pages):
                page = self.reader.read(CLOB + REWARDS_CURRENT_PATH,
                                        params={"next_cursor": self.cursor} if self.cursor else None,
                                        kind="rewards_sweep_page", projection=page_projection)
                self.pages += 1
                self.pages_read += 1
                for row in page["data"]:
                    cid = str(row["condition_id"]).lower()
                    value = sweep_row({**row, "condition_id": cid})
                    if cid in self.partial and self.partial[cid] != value:
                        raise ValueError("conflicting duplicate condition in rewards sweep")
                    self.partial[cid] = value
                cursor = page.get("next_cursor") or ""
                if cursor in TERMINAL_CURSORS:
                    return self._commit()
                if cursor in self.seen_cursors or self.pages >= MAX_SWEEP_PAGES:
                    raise ValueError("rewards sweep pagination exceeded bound")
                self.seen_cursors.add(cursor)
                self.cursor = cursor
        except Exception as exc:
            self.errors += 1
            self.last_error = type(exc).__name__ + ": " + str(exc)[:200]
            self.reader.store.event("rewards_sweep_error", {"error": self.last_error, "pages": self.pages})
            self._reset()
            # Back off one interval; meanwhile the trigger uses the stale recheck once the pass ages out.
            self.retry_at = self.clock() + SWEEP_SECONDS
            return None
        return None

    def _commit(self):
        new = {cid: digest(encoded(value)) for cid, value in self.partial.items()}
        changed = sorted(cid for cid, value in new.items() if self.state.get(cid) != value)
        removed = sorted(set(self.state) - set(new))
        rows, pages = self.partial, self.pages
        self.state, self.rows, self.completed_at, self.retry_at = new, rows, self.clock(), None
        self.generation += 1
        self.last_changed, self.last_removed = len(changed), len(removed)
        self._reset()
        self.reader.store.event("rewards_sweep", {
            "generation": self.generation, "pages": pages, "conditions": len(new),
            "changed_count": len(changed), "removed_count": len(removed),
            "changed": changed[:200], "removed": removed[:200],
            "state_sha256": digest(encoded(sorted(new.items())))})
        return rows

    def metrics(self):
        return {"generation": self.generation, "conditions": len(self.state), "pages_read": self.pages_read,
                "errors": self.errors, "last_error": self.last_error, "age_seconds": self.age_seconds(),
                "fresh": self.fresh(), "in_progress": self.partial is not None,
                "last_changed": self.last_changed, "last_removed": self.last_removed}


class RewardTrigger:
    """Per-condition record reads on change, recheck and backstop; one instance per recorder.

    A due read that the per-cycle cap defers keeps its reason and is served first next cycle;
    a band without a record yet carries ``clob_reward_content_sha256: null`` in its universe row.
    """

    def __init__(self, reader, *, clock=time.monotonic, max_reads=MAX_TRIGGERED_READS_PER_CYCLE):
        self.reader, self.clock, self.max_reads = reader, clock, max_reads
        self.records, self.remaining = {}, max_reads
        self.reads, self.deferred, self.errors = 0, 0, 0
        self.reasons = {reason: 0 for reason in REASONS}

    def due(self, row, sweep_state, sweep_fresh):
        prior = self.records.get(row["condition_id"])
        if prior is None:
            return "first"
        age = self.clock() - prior["read_at"]
        if prior["terms_sha256"] != digest(encoded(row.get("reward"))):
            return "terms_changed"
        if sweep_fresh and sweep_state.get(row["condition_id"]) != prior["sweep_sha256"]:
            return "sweep_changed"
        if not sweep_fresh and age >= STALE_RECHECK_SECONDS:
            return "sweep_stale"
        if age >= BACKSTOP_SECONDS:
            return "backstop"
        return None

    def begin_cycle(self):
        """One read budget per cycle, shared by the lanes in the order they refresh (core first)."""
        self.remaining = self.max_reads
        for cid in [cid for cid, prior in self.records.items()
                    if self.clock() - prior["selected_at"] > BACKSTOP_SECONDS]:
            del self.records[cid]  # Unselected for an hour: a later selection reads it as new.

    def plan(self, lanes, sweep_state, sweep_fresh):
        """``lanes`` is ``[(partition, rows), ...]`` in service order; returns ``[(partition, row, reason)]``."""
        due = []
        for lane_order, (partition, rows) in enumerate(lanes):
            for row in rows:
                reason = self.due(row, sweep_state, sweep_fresh)
                if reason:
                    prior = self.records.get(row["condition_id"])
                    due.append((lane_order, REASONS.index(reason), prior["read_at"] if prior else float("-inf"),
                                row["condition_id"], partition, row, reason))
        due.sort(key=lambda item: item[:4])
        take = max(0, self.remaining)
        self.deferred += max(0, len(due) - take)
        return [(partition, row, reason) for *_, partition, row, reason in due[:take]]

    def refresh(self, lanes, sweep_state, sweep_fresh, *, today):
        """Read due records (errors propagate as cycle errors) and annotate every selected row."""
        for partition, row, reason in self.plan(lanes, sweep_state, sweep_fresh):
            self.remaining -= 1
            record = reward_record(self.reader, row["condition_id"], partition=partition)
            self.records[row["condition_id"]] = {
                "selected_at": self.clock(),
                "read_at": self.clock(), "reason": reason, "terms_sha256": digest(encoded(row.get("reward"))),
                "sweep_sha256": sweep_state.get(row["condition_id"]),
                "clob_reward_content_sha256": digest(encoded(record)),
                "clob_daily_rate": reward_rate(record, today) if record else 0.}
            self.reads += 1
            self.reasons[reason] += 1
        for _, rows in lanes:
            for row in rows:
                prior = self.records.get(row["condition_id"], {})
                if prior:
                    prior["selected_at"] = self.clock()
                row["clob_reward_content_sha256"] = prior.get("clob_reward_content_sha256")
                row["clob_reward_age_seconds"] = (self.clock() - prior["read_at"]) if prior else None
                row["clob_reward_reason"] = prior.get("reason")

    def metrics(self):
        return {"records": len(self.records), "reads": self.reads, "deferred": self.deferred,
                "reads_by_reason": dict(self.reasons), "max_reads_per_cycle": self.max_reads,
                "backstop_seconds": BACKSTOP_SECONDS, "stale_recheck_seconds": STALE_RECHECK_SECONDS}
