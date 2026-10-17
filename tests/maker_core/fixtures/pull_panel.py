"""Invented prices/resting states only; no recorded market or account inputs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from maker_core.quoting.policy import Book, QuoteLeg
from maker_core.replay.engine import ReplayConfig, ReplayResult, Span


def panel(*, days=1, markets=1, informed_pulls=(0, 1), clock_pulls=(2, 3), mids=None):
    mids = mids or [".5"] * 5 + [".55"] * 3 + [".5"] * 3
    books, left, right = [], [], []
    leg = QuoteLeg("YES", D(".48"), D(20))
    for day in range(days):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
        for market in range(markets):
            cid, mid = f"c{day}-{market}", f"market{market}"
            for minute, price in enumerate(mids):
                at, price = start + timedelta(minutes=minute), D(price)
                book = Book(at, ((price-D(".01"), D(75)),), ((price+D(".01"), D(75)),),
                            ((1-price-D(".01"), D(75)),), ((1-price+D(".01"), D(75)),))
                books.append((at, cid, book))
                for spans, pulls in ((left, informed_pulls), (right, clock_pulls)):
                    spans.append(Span(at, at+timedelta(minutes=1), cid, mid, True, "FIXTURE",
                                      () if minute in pulls else (leg,), 0., D(0), D(0), D(0), False))
    result = ReplayResult(ReplayConfig(hazard_per_minute=0), (), tuple(left), (), (), {}, D(100), {}, tuple(books))
    return result, replace(result, config=replace(result.config, policy="clock_only"), spans=tuple(right))
