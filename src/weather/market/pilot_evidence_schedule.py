"""Request-boundary book priority, staggered terms and explicit capacity receipts."""
from dataclasses import dataclass, field
import hashlib
import math
import time

from weather.market.pilot_evidence_public import RetryPending


@dataclass
class Job:
    key: str
    interval: float
    action: object
    due: float
    last_success: float | None = None
    max_interval: float = 0
    intervals: list = field(default_factory=list)
    late_open: bool = False
    calls: int = 0


def capacity(bands, events=4, *, terms=60, fees=180, metadata=180,
             fee_rates=180, rps=2, book_target=5, batches=1):
    lower = bands / terms + bands / fees + 2 * bands / fee_rates + events / metadata + 1 / 60 + 1 / 9
    available = rps - lower - 0.05  # Headroom for control changes, not an IP quota claim.
    achievable = max(book_target, batches / available) if available > 0 else None
    return {"bands": bands, "tokens": 2 * bands, "events": events,
            "nonbook_starts_per_second_including_ping": lower,
            "configured_book_target_seconds": book_target,
            "capacity_book_interval_seconds": achievable,
            "nominal_starts_per_second": lower + batches / achievable if achievable else None,
            "feasible": achievable is not None and achievable <= 30,
            "assumptions": "one reward page, serial HTTP <=0.5s, stable universe, no throttling; not an upper bound"}


class Scheduler:
    def __init__(self, store, gate, *, clock=time.monotonic, sleep=None):
        self.store, self.gate, self.clock = store, gate, clock
        self.anchor, self.jobs = clock(), {}
        self.sleep = sleep or store.stop.wait

    def add(self, key, interval, action, *, immediate=False):
        if key in self.jobs:
            return
        # Stable identity hash distributes first and subsequent per-band requests.
        phase = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 2 ** 32 * interval
        due = self.clock() if immediate else self.anchor + phase
        while due < self.clock() and not immediate:
            due += interval
        self.jobs[key] = Job(key, interval, action, due)

    def next_job(self):
        now = self.clock()
        book = self.jobs.get("books")
        if book and book.due <= now:
            return book
        return min(self.jobs.values(), key=lambda job: job.due)

    def spread(self):
        """Evenly space unstarted lower-priority work; avoid hash-phase clusters."""
        groups = {}
        for job in self.jobs.values():
            if job.key in ("books", "ping") or job.key.startswith("event:") and not job.calls:
                continue
            groups.setdefault(job.interval, []).append(job)
        for group_index, (period, jobs) in enumerate(sorted(groups.items())):
            ordered = sorted(jobs, key=lambda job: job.key)
            step = period / len(ordered)
            for index, job in enumerate(ordered):
                if job.calls:
                    continue
                due = self.anchor + (index + (0.25 if group_index % 2 == 0 else 0.75)) * step
                while due < self.clock():
                    due += period
                job.due = due

    def service(self):
        job, now = self.next_job(), self.clock()
        if job.due > now:
            self.sleep(min(0.2, job.due - now))
            return
        threshold = max(2 * self.gate.interval, 0.1 * job.interval)
        late = now - job.due > threshold
        if late and not job.late_open:
            self.store.gap("rest_cadence_lag", job=job.key, due_monotonic=job.due,
                           detected_monotonic=now, threshold_seconds=threshold)
            job.late_open = True
        elif not late and job.late_open:
            self.store.write("cadence_gap_end", {"job": job.key, "recovered_monotonic": now})
            job.late_open = False
        try:
            completed = job.action()
        except RetryPending:
            job.due = max(self.clock() + self.gate.interval, self.gate.next_at)
            return
        except (ValueError, OSError) as exc:
            self.store.gap("reconciliation_failed", job=job.key, error=type(exc).__name__)
            completed = True
        finish = self.clock()
        job.calls += 1
        if completed is False:  # A paginated walk yields at every request boundary.
            job.due = finish + self.gate.interval
            return
        if job.last_success is not None:
            delta = finish - job.last_success
            job.max_interval = max(job.max_interval, delta)
            job.intervals.append(delta)
            job.intervals = job.intervals[-2048:]
        job.last_success = finish
        # Keep the phase instead of drifting every due time by HTTP latency.
        skipped = max(0, math.floor((finish - job.due) / job.interval))
        if skipped:
            self.store.gap("rest_periods_missed", job=job.key, periods=skipped,
                           from_monotonic=job.due, to_monotonic=finish)
        job.due += (skipped + 1) * job.interval

    def snapshot(self):
        book = self.jobs.get("books")
        values = sorted(book.intervals) if book else []
        return {"jobs": len(self.jobs), "open_cadence_gaps": sum(j.late_open for j in self.jobs.values()),
                "book_polls": book.calls if book else 0,
                "book_interval_samples": len(values),
                "book_interval_p95_seconds": values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)] if values else None,
                "book_interval_max_seconds": book.max_interval if book else None,
                "book_interval_mean_seconds": sum(values) / len(values) if values else None}
