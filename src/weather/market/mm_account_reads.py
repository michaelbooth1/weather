"""Fail-closed CLOB account response validation before SDK cursor normalization.

The SDK Page erases the distinction between missing cursors and LTE=. The raw
response hook preserves that distinction; the page walker separately bounds work.
"""
import time
from decimal import Decimal, InvalidOperation

from weather.market.lfc_recording_io import strict_json


class AmbiguousAccountRead(RuntimeError):
    state = 'AMBIGUOUS'
    code = 'AMBIGUOUS'


def order_terminal(row):
    if not isinstance(row, dict):
        return False
    if str(row.get('status') or row.get('official_order_status') or '').upper() not in {
            'CANCELED', 'CANCELLED', 'MATCHED', 'EXPIRED'}:
        return False
    try:
        value = row['size_matched']
        if isinstance(value, bool):
            return False
        matched = Decimal(str(value))
        return matched.is_finite() and matched >= 0
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return False


def validate_account_page(payload):
    if (not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or
            type(payload.get('count')) is not int or payload['count'] != len(payload['data']) or
            type(payload.get('limit')) is not int or not 1 <= payload['limit'] <= 500 or
            len(payload['data']) > payload['limit'] or
            not isinstance(payload.get('next_cursor'), str) or not payload['next_cursor']):
        raise AmbiguousAccountRead('AMBIGUOUS: incomplete_account_page')
    return payload


def validate_account_response(response):
    if (response.request.method != 'GET' or response.url.path not in {'/data/orders', '/data/trades'} or
            response.status_code != 200):
        return
    body = bytearray()
    try:
        for block in response.iter_bytes(chunk_size=65536):
            if len(body) + len(block) > 2_000_000:
                raise AmbiguousAccountRead('AMBIGUOUS: account_response_budget')
            body.extend(block)
        # httpx.Response.read uses this same cache; SDK parsing must see the
        # exact validated bytes after the bounded stream has been consumed.
        response._content = bytes(body)
        validate_account_page(strict_json(bytes(body)))
    except AmbiguousAccountRead:
        raise
    except Exception:
        raise AmbiguousAccountRead('AMBIGUOUS: account_response_unreadable') from None


def install_account_guard(client):
    context = getattr(client, '_ctx', None)
    transport = getattr(context, 'secure_clob', None)
    http = getattr(transport, '_client', None)
    if http is None and type(client).__module__.startswith('polymarket'):
        raise AmbiguousAccountRead('AMBIGUOUS: account_response_guard_missing')
    if http is not None:
        hooks = http.event_hooks['response']
        if validate_account_response not in hooks:
            hooks.append(validate_account_response)


def account_rows(paginator, *, normalize, seconds=None, page_cap=50, row_cap=25000, monotonic=time.monotonic):
    from polymarket import UnexpectedResponseError
    rows, seen = [], set()
    deadline = None if seconds is None else monotonic() + seconds
    try:
        pages = iter(paginator)
        for _ in range(page_cap):
            if deadline is not None and monotonic() > deadline:
                raise AmbiguousAccountRead('AMBIGUOUS: account_read_deadline')
            try:
                page = next(pages)
            except StopIteration:
                raise AmbiguousAccountRead('AMBIGUOUS: account_terminal_missing') from None
            if deadline is not None and monotonic() > deadline:
                raise AmbiguousAccountRead('AMBIGUOUS: account_read_deadline')
            cursor = getattr(page, 'next_cursor', None)
            more = getattr(page, 'has_more', None)
            items = getattr(page, 'items', None)
            if (type(more) is not bool or more != (cursor is not None) or
                    not isinstance(items, (list, tuple)) or
                    (more and (not isinstance(cursor, str) or not cursor or cursor in seen))):
                raise AmbiguousAccountRead('AMBIGUOUS: account_pagination')
            rows.extend(normalize(item) for item in items)
            if len(rows) > row_cap:
                raise AmbiguousAccountRead('AMBIGUOUS: account_row_budget')
            if not more:
                marker = object()
                if next(pages, marker) is not marker:
                    raise AmbiguousAccountRead('AMBIGUOUS: account_page_after_terminal')
                return rows
            seen.add(cursor)
        raise AmbiguousAccountRead('AMBIGUOUS: account_page_budget')
    except TypeError:
        raise AmbiguousAccountRead('AMBIGUOUS: account_paginator_missing') from None
    except (ValueError, KeyError, AttributeError, UnexpectedResponseError):
        raise AmbiguousAccountRead('AMBIGUOUS: account_items_unreadable') from None
