"""Per-order and per-market report over a verified manual order journal.

Everything here is ``owner-discretionary``: it measures the owner's manual
orders and never feeds automated campaign data. Definitions (reward allocation,
cash-days, the two-sided baseline) are in docs/operations/manual-order-journal.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from weather.market.order_journal import SCOPE
from weather.market.order_journal_sources import dec, text
from weather.schema_registry import schema_version

MAX_GAP_SECONDS = 900
TWO_SIDED_REWARD_MULTIPLE = 3
ONE_SIDED_MID_BAND = (Decimal("0.10"), Decimal("0.90"))
HORIZONS = ("5m", "30m", "settlement")


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _sum(values):
    values = [dec(v) for v in values]
    return text(sum(values, Decimal(0)))


def build_report(records):
    orders, fills, markouts, earnings, share_path = {}, {}, {}, {}, {}
    size_seconds = {}
    unobserved = Decimal(0)
    for index, row in enumerate(records):
        at = ts(row["recorded_at_utc"])
        nxt = ts(records[index + 1]["recorded_at_utc"]) if index + 1 < len(records) else at
        span = min(nxt - at, MAX_GAP_SECONDS)
        unobserved += Decimal(str(max(0, nxt - at - MAX_GAP_SECONDS)))
        day = row["recorded_at_utc"][:10]
        for order in row.get("open_orders") or []:
            item = orders.setdefault(order["order_id"], dict(
                {k: order[k] for k in ("order_id", "condition_id", "token_id", "side", "outcome", "price",
                                       "original_size")},
                first_seen=row["recorded_at_utc"], cash_seconds=Decimal(0), mids=[], outside_one_sided_band=0,
                observations=0))
            item.update(last_seen=row["recorded_at_utc"], size_matched=order["size_matched"])
            item["observations"] += 1
            remaining = dec(order["original_size"]) - dec(order["size_matched"])
            if order["side"] == "BUY":
                item["cash_seconds"] += dec(order["price"]) * remaining * Decimal(str(span))
            key = (order["condition_id"], day)
            size_seconds.setdefault(key, {}).setdefault(order["order_id"], Decimal(0))
            size_seconds[key][order["order_id"]] += remaining * Decimal(str(span))
            mid = ((row.get("books") or {}).get(order["token_id"]) or {}).get("mid")
            if mid is not None:
                item["mids"].append(mid)
                if not ONE_SIDED_MID_BAND[0] <= dec(mid) <= ONE_SIDED_MID_BAND[1]:
                    item["outside_one_sided_band"] += 1
        for fill in row.get("fills") or []:
            fills[fill["fill_key"]] = dict(fill, recorded_at_utc=row["recorded_at_utc"])
        for mark in row.get("markouts") or []:
            markouts.setdefault(mark["fill_key"], {})[mark["horizon"]] = mark
        for view in row.get("rewards") or []:
            for condition, value in (view.get("by_condition") or {}).items():
                earnings[(condition, view["date"])] = value  # latest observation wins
            if view.get("date") == day:
                for condition, pct in (view.get("percentages") or {}).items():
                    path = share_path.setdefault(condition, [])
                    if not path or path[-1][1] != pct:
                        path.append((row["recorded_at_utc"], pct))

    order_rewards = {}
    for (condition, day), value in earnings.items():
        weights = size_seconds.get((condition, day)) or {}
        total = sum(weights.values(), Decimal(0))
        for order_id, weight in weights.items():
            if total > 0:
                order_rewards[order_id] = order_rewards.get(order_id, Decimal(0)) + dec(value) * weight / total

    fill_rows = []
    for key, fill in sorted(fills.items(), key=lambda kv: (kv[1]["fill_time"], kv[0])):
        marks = markouts.get(key, {})
        mid = fill.get("reference_mid")
        edge = None
        if mid is not None:
            edge = dec(mid) - dec(fill["price"]) if fill["side"] == "BUY" else dec(fill["price"]) - dec(mid)
        end = (ts(marks["settlement"]["mark_time"]) if "settlement" in marks and marks["settlement"]["mark_time"]
               else ts(records[-1]["recorded_at_utc"]))
        cost = dec(fill["price"]) * dec(fill["size"]) if fill["side"] == "BUY" else Decimal(0)
        fill_rows.append(dict(
            fill_key=key, order_id=fill.get("order_id"), condition_id=fill["condition_id"], token_id=fill["token_id"],
            side=fill["side"], price=fill["price"], size=fill["size"], liquidity_role=fill.get("liquidity_role"),
            source=fill["source"], fill_time_utc=datetime.fromtimestamp(fill["fill_time"], timezone.utc).isoformat(),
            reference_mid=mid, distance_from_mid=text(edge) if edge is not None else None,
            markouts={h: (marks[h]["pusd"] if h in marks else None) for h in HORIZONS},
            markout_status={h: (marks[h]["status"] if h in marks else "pending") for h in HORIZONS},
            position_cash_days=text(cost * Decimal(str(max(0, end - fill["fill_time"]))) / 86400), scope=SCOPE))

    def rollup(key_name, key_value, fill_list, reward, cash_days, extra):
        settled = [f["markouts"]["settlement"] for f in fill_list]
        complete = all(v is not None for v in settled)
        best = [next((f["markouts"][h] for h in reversed(HORIZONS) if f["markouts"][h] is not None), None)
                for f in fill_list]
        edges = [f["distance_from_mid"] for f in fill_list]
        fill_part = (text(sum((2 * dec(e) * dec(f["size"]) for e, f in zip(edges, fill_list)), Decimal(0)))
                     if all(e is not None for e in edges) else None)
        reward = dec(reward)
        return dict(
            {key_name: key_value, **extra}, scope=SCOPE, reward_accrued_pusd=text(reward), fills=len(fill_list),
            filled_size=_sum(f["size"] for f in fill_list),
            markouts_pusd={h: (_sum(f["markouts"][h] for f in fill_list)
                               if all(f["markouts"][h] is not None for f in fill_list) else None) for h in HORIZONS},
            cash_days=text(cash_days + sum((dec(f["position_cash_days"]) for f in fill_list), Decimal(0))),
            net_pusd=text(reward + sum((dec(v) for v in settled), Decimal(0))) if complete else None,
            net_status="no_fills" if not fill_list else "settled" if complete else "pending_settlement",
            net_provisional_pusd=(text(reward + sum((dec(v) for v in best), Decimal(0)))
                                  if all(v is not None for v in best) else None),
            two_sided_baseline=dict(
                reward_pusd=text(reward * TWO_SIDED_REWARD_MULTIPLE),
                symmetric_fill_pusd=fill_part,
                net_pusd=text(reward * TWO_SIDED_REWARD_MULTIPLE + dec(fill_part)) if fill_part is not None else None,
                assumption="mirror order at equal distance fills the same size at the same time; settlement cancels"))

    order_rows = []
    for order_id, item in sorted(orders.items(), key=lambda kv: (kv[1]["first_seen"], kv[0])):
        order_rows.append(rollup(
            "order_id", order_id, [f for f in fill_rows if f["order_id"] == order_id],
            order_rewards.get(order_id, Decimal(0)), item["cash_seconds"] / 86400,
            dict({k: item[k] for k in ("condition_id", "token_id", "side", "outcome", "price", "original_size",
                                       "size_matched", "first_seen", "last_seen", "observations",
                                       "outside_one_sided_band")},
                 reward_allocation="size_seconds_pro_rata_within_condition_day")))
    conditions = sorted({o["condition_id"] for o in orders.values()} | {f["condition_id"] for f in fill_rows}
                        | {c for c, _ in earnings if c != "unattributed"})
    market_rows = []
    for condition in conditions:
        cash = sum((o["cash_seconds"] for o in orders.values() if o["condition_id"] == condition), Decimal(0)) / 86400
        reward = sum((dec(v) for (c, d), v in earnings.items() if c == condition and (c, d) in size_seconds),
                     Decimal(0))
        market_rows.append(rollup(
            "condition_id", condition, [f for f in fill_rows if f["condition_id"] == condition], reward, cash,
            dict(orders=sorted(o for o, v in orders.items() if v["condition_id"] == condition),
                 reward_share_path=[dict(at=a, pct=p) for a, p in share_path.get(condition, [])])))
    unattributed = sum((dec(v) for (c, _), v in earnings.items() if c == "unattributed"), Decimal(0))
    # Earnings on a condition-day with no journal observation predate the journal or its gaps.
    outside = sum((dec(v) for (c, d), v in earnings.items() if c != "unattributed" and (c, d) not in size_seconds),
                  Decimal(0))
    return dict(
        schema_version=schema_version("manual_order_journal_report"), scope=SCOPE,
        records=len(records), first_record_utc=records[0]["recorded_at_utc"] if records else None,
        last_record_utc=records[-1]["recorded_at_utc"] if records else None,
        unobserved_seconds=text(unobserved), unattributed_reward_pusd=text(unattributed),
        reward_outside_observation_pusd=text(outside),
        orders=order_rows, markets=market_rows, fills=fill_rows,
        caveats=["owner-discretionary manual orders; never automated campaign data",
                 "reward earnings are account reads, not payment verification",
                 "5m/30m marks are public price-history points, not executable prices",
                 "two-sided baseline is hypothetical: x3 reward (Q_min, mid inside 0.10-0.90) and mirrored fills"])


def markdown(report):
    lines = [f"# Manual order journal report ({report['scope']})", "",
             f"Records {report['records']} from {report['first_record_utc']} to {report['last_record_utc']}; "
             f"unobserved {report['unobserved_seconds']} s; unattributed reward {report['unattributed_reward_pusd']} pUSD; "
             f"reward outside observed condition-days {report['reward_outside_observation_pusd']} pUSD.",
             "", "## Markets", "",
             "| condition | reward | fills | mk 5m | mk 30m | mk settle | cash-days | net | 2-sided net |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["markets"]:
        m = row["markouts_pusd"]
        lines.append(f"| `{row['condition_id'][:12]}` | {row['reward_accrued_pusd']} | {row['fills']} | {m['5m']} | "
                     f"{m['30m']} | {m['settlement']} | {row['cash_days']} | {row['net_pusd']} ({row['net_status']}) | "
                     f"{row['two_sided_baseline']['net_pusd']} |")
    lines += ["", "## Orders", "",
              "| order | side | outcome | price | size | matched | reward | fills | net | provisional |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["orders"]:
        lines.append(f"| `{row['order_id'][:12]}` | {row['side']} | {row['outcome']} | {row['price']} | "
                     f"{row['original_size']} | {row['size_matched']} | {row['reward_accrued_pusd']} | {row['fills']} | "
                     f"{row['net_pusd']} | {row['net_provisional_pusd']} |")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in report["caveats"]]
    return "\n".join(lines) + "\n"


def write_report(report, *, json_path=None, markdown_path=None):
    if json_path:
        Path(json_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_path:
        Path(markdown_path).write_text(markdown(report), encoding="utf-8")
    if not json_path and not markdown_path:
        print(markdown(report), end="")
