"""Per-token socket coverage of the 88a public streams, from journaled rows only.

Darkness is judged per **token**: the time a token was wanted while no connected
socket on the channel subscribed it, over the union of every session whose
subscription included it.  Keying darkness by subscription instead inflated it:
each token-set swap creates a new subscription key, so the old key stayed "dark"
until an unrelated reconnect (2026-09-29: 53,760 reported against 283 real
seconds with no trade socket at all).

When to count a token as *wanted*:

* ``stream_tokens`` rows (written by the stream at every token-set change and stop)
  name the wanted subscriptions exactly; a crash leaves the last set wanted until
  the restarted worker journals its first set.
* Journals written before those rows existed are inferred from sessions: after a
  token's coverage ends, it is still wanted if it is covered again in the channel's
  next connect round (connects within ``CONNECT_ROUND_SECONDS`` of the first one);
  otherwise a deliberate stop is taken as its removal, and a failure as dark until
  that round began.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

CONNECT_ROUND_SECONDS = 10.0


def merge(intervals):
    """Sorted, disjoint union of (start, end) pairs."""
    merged = []
    for start, end in sorted(interval[:2] for interval in intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        elif end > start:
            merged.append([start, end])
    return [tuple(item) for item in merged]


def subtract(base, cover):
    """Parts of the disjoint, sorted ``base`` not inside the disjoint, sorted ``cover``."""
    result, index = [], 0
    for start, end in base:
        cursor = start
        while index < len(cover) and cover[index][1] <= cursor:
            index += 1
        probe = index
        while probe < len(cover) and cover[probe][0] < end:
            if cover[probe][0] > cursor:
                result.append((cursor, cover[probe][0]))
            cursor = max(cursor, cover[probe][1])
            probe += 1
        if cursor < end:
            result.append((cursor, end))
    return result


def clip(intervals, start, end):
    return [(max(a, start), min(b, end)) for a, b in intervals if b > start and a < end]


def seconds(intervals):
    return sum((b - a).total_seconds() for a, b in intervals)


def sessions(rows, wanted_changes, data_end):
    """Connected intervals per subscription key as (start, end, end cause, key), plus unterminated count.

    ``rows`` are one channel's lifecycle and gap rows.  A connected row with no
    disconnected row (a killed worker) ends at the next row on its key, else at the
    first later ``stream_tokens`` change that drops its key, else at ``data_end``.
    """
    by_key = defaultdict(list)
    for row in rows:
        by_key[(row["body"].get("subscription") or {}).get("sha256", "")].append(row)
    intervals, unterminated = [], 0
    for key, key_rows in by_key.items():
        key_rows.sort(key=lambda row: (row["at"], row["kind"] == "stream_gap", row["segment"], row["sequence"]))
        opened = last = None
        for row in key_rows:
            state = row["body"].get("state") if row["kind"] == "stream_lifecycle" else "gap"
            if opened is not None and state != "disconnected":
                intervals.append([opened, row["at"], "unterminated", key])
                unterminated, opened = unterminated + 1, None
            if state == "connected":
                opened, last = row["at"], None
            elif state == "disconnected" and opened is not None:
                last = [opened, row["at"], "orderly_stop", key]
                intervals.append(last)
                opened = None
            elif state == "gap" and last is not None:
                last[2] = row.get("cause", "other")  # The gap row of the session that just ended.
                last = None
        if opened is not None:
            end = next((at for at, keys in wanted_changes if at > opened and key not in keys), data_end)
            intervals.append([opened, max(opened, end), "unterminated", key])
            unterminated += 1
    return [tuple(item) for item in intervals], unterminated


def wanted_from_changes(changes, subscriptions, data_end):
    """Token -> wanted intervals from ``stream_tokens`` rows; also unresolved subscription count."""
    wanted, opened, current, unresolved = defaultdict(list), {}, set(), 0
    for at, keys in changes:
        tokens = set()
        for key in keys:
            if key not in subscriptions:
                unresolved += 1
            tokens |= subscriptions.get(key, frozenset())
        for token in current - tokens:
            wanted[token].append((opened.pop(token), at))
        for token in tokens - current:
            opened[token] = at
        current = tokens
    for token, start in opened.items():
        if data_end > start:
            wanted[token].append((start, data_end))
    return wanted, unresolved


class EndCauses:
    """Why a token's coverage ended at a time; a failure wins over an orderly stop at the same instant."""

    def __init__(self, covered):
        self.causes = {}
        for _, end, cause, _ in covered:
            if self.causes.get(end) in (None, "orderly_stop"):
                self.causes[end] = cause
        self.ends = sorted(self.causes)

    def at(self, moment, *, earlier=False):
        """The cause of an end exactly at ``moment`` or, with ``earlier``, the latest end before it."""
        if moment in self.causes:
            return self.causes[moment]
        index = bisect_right(self.ends, moment)
        return self.causes[self.ends[index - 1]] if earlier and index else None


def inferred_wanted(covered, connects):
    """Legacy rule: wanted intervals for one token from its own coverage and the channel's connects."""
    blocks, causes = merge(covered), EndCauses(covered)
    wanted = list(blocks)
    for index, (_, end) in enumerate(blocks):
        cause = causes.at(end) or "orderly_stop"
        position = bisect_left(connects, end)
        if position == len(connects):
            continue
        first = connects[position]
        following = blocks[index + 1][0] if index + 1 < len(blocks) else None
        if following is not None and (following - first).total_seconds() <= CONNECT_ROUND_SECONDS:
            wanted.append((end, following))
        elif cause != "orderly_stop":
            wanted.append((end, first))
    return merge(wanted)


def channel_coverage(rows, subscriptions, changes, *, window_start, window_end, data_end):
    """Per-token dark time and all-sockets-down time for one channel inside the window."""
    intervals, unterminated = sessions(rows, changes, data_end)
    by_token = defaultdict(list)
    unresolved_sessions = 0
    for interval in intervals:
        if interval[3] not in subscriptions:
            unresolved_sessions += 1
        for token in subscriptions.get(interval[3], ()):
            by_token[token].append(interval)
    if changes:
        basis = "stream_tokens_rows"
        wanted, unresolved = wanted_from_changes(changes, subscriptions, data_end)
    else:
        basis = "inferred_from_session_rows"
        connects = sorted(row["at"] for row in rows
                          if row["kind"] == "stream_lifecycle" and row["body"].get("state") == "connected")
        wanted = {token: inferred_wanted(covered, connects) for token, covered in by_token.items()}
        unresolved = 0
    per_token, by_cause, gaps = {}, Counter(), []
    for token, spans in wanted.items():
        spans = clip(merge(spans), window_start, window_end)
        if not spans:
            continue
        covered = by_token.get(token, [])
        dark, causes = subtract(spans, merge(covered)), EndCauses(covered)
        per_token[token] = seconds(dark)
        for start, end in dark:
            # A gap opens where a session ended, or where the token became wanted (awaiting its connect).
            cause = causes.at(start, earlier=start == window_start) or "awaiting_connect"
            by_cause[cause] += (end - start).total_seconds()
            gaps.append((end - start).total_seconds())
    if changes:
        active = merge(span for spans in wanted.values() for span in spans)
    else:
        times = [row["at"] for row in rows]
        active = [(min(times), max(times))] if times else []
    active = clip(active, window_start, window_end)
    down = subtract(active, merge(intervals))
    return {
        "wanted_basis": basis,
        "tokens_wanted": len(per_token),
        "token_dark_seconds_total": round(sum(per_token.values()), 3),
        "token_dark_seconds_by_cause": {cause: round(value, 3) for cause, value in sorted(by_cause.items())},
        "token_dark_gap_seconds": gaps,
        "per_token_dark_seconds": per_token,
        "active_seconds": round(seconds(active), 3),
        "all_sockets_down_seconds": round(seconds(down), 3),
        "all_sockets_down_gap_seconds": [(end - start).total_seconds() for start, end in down],
        "unterminated_sessions": unterminated,
        "unresolved_subscriptions": unresolved + unresolved_sessions,
    }
