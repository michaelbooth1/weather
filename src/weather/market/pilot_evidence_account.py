"""Raw public Data API v2 walks; no account authentication or venue mutations."""
from __future__ import annotations

from weather.market.pilot_evidence_public import DATA


def walk_pages(http, store, path, params, *, label, max_pages):
    """Filters are identical on every page. A cursor is never treated as a URL."""
    cursor, seen, rows = None, set(), 0
    for page_index in range(max_pages):
        request = dict(params)
        if cursor is not None:
            request["cursor"] = cursor
        page = http.read(DATA + path, params=request)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise ValueError("account page data missing")
        pagination = page.get("pagination")
        if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
            raise ValueError("account pagination missing")
        if "next_cursor" not in pagination:
            raise ValueError("account terminal cursor missing")
        next_cursor = pagination["next_cursor"]
        more = pagination["has_more"]
        if (more and (not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen) or
                not more and next_cursor is not None):
            raise ValueError("account cursor repeated or inconsistent")
        rows += len(page["data"])
        store.write("account_page", {"dataset": label, "page_index": page_index,
                                     "request_params": request, "cursor_in": cursor,
                                     "cursor_out": next_cursor, "has_more": more,
                                     "rows": len(page["data"])})
        if not more:
            store.write("account_walk_complete", {"dataset": label, "pages": page_index + 1,
                                                  "rows": rows, "terminal_cursor": None})
            return
        seen.add(next_cursor)
        cursor = next_cursor
    raise ValueError("account page cap reached")


def account_flow(args, store, http, end_epoch):
    user = {"user": args.wallet.lower(), "limit": args.page_size}
    window = {**user, "start": int(args.from_utc.timestamp()), "end": end_epoch}
    datasets = [
        ("trades", "/v2/trades", {**window, "taker_only": "false", "filter_amount": "0.000000000000000001"}),
        ("activity_all_default_types", "/v2/activity",
         {**window, "exclude_deposits_withdrawals": "false", "sort_by": "TIMESTAMP", "sort_direction": "ASC"}),
        ("activity_tip", "/v2/activity",
         {**window, "type": "TIP", "exclude_deposits_withdrawals": "false",
          "sort_by": "TIMESTAMP", "sort_direction": "ASC"}),
    ]
    for status in ("OPEN", "REDEEMABLE", "REDEEMABLE_LOST", "CLOSED"):
        params = {**user, "status": status, "filter_amount": "0"}
        if status != "CLOSED":
            params["include_archived"] = "true"
        datasets.append(("positions_" + status.lower(), "/v2/positions", params))
    incomplete = False
    for label, path, params in datasets:
        try:
            walk_pages(http, store, path, params, label=label, max_pages=args.max_pages)
        except (ValueError, OSError) as exc:
            incomplete = True
            store.gap("account_walk_incomplete", dataset=label, error=type(exc).__name__)
    store.write("account_export_result", {
        "pagination_complete": not incomplete, "account_cash_reconciliation_proven": False,
        "private_fill_finality_proven": False, "positions_are_atomic_snapshot": False,
        "limitations": ["Public API indexed activity only; not a chain cash-balance proof",
                        "Trades below the explicit public API filter floor may be omitted",
                        "Positions API excludes inactive markets; overlapping statuses are retained",
                        "Position pages can change during pagination; repeat immutable exports"],
    })
    return "account_incomplete" if incomplete else "account_export_complete"
