"""Markdown renderers for replay-cache retention artifacts."""

from __future__ import annotations

from typing import Any

from weather.reporting.formatting import markdown_table


def render_plan(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    quota = payload.get("quota") or {}
    lines = [
        "# Replay Cache Retention Dry Run",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Cache root: `{payload.get('root')}`",
        f"Apply required: `{payload.get('apply_required')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Reachable entries", summary.get("reachable_count")],
                ["Reachable bytes", summary.get("reachable_bytes")],
                ["Selected entries", summary.get("selected_count")],
                ["Selected bytes", summary.get("selected_bytes")],
                ["Ambiguities", summary.get("ambiguity_count")],
                ["Quota bytes", quota.get("bytes")],
                ["Reachable exceeds quota", quota.get("reachable_exceeds_quota")],
                ["Selection policy", quota.get("selection_policy")],
            ],
        ),
        "",
        "## Exact Candidates",
        "",
        *markdown_table(
            ["Path", "Bytes", "SHA-256", "Identity", "Reason"],
            [
                [
                    row.get("path"),
                    row.get("bytes"),
                    row.get("sha256"),
                    row.get("identity"),
                    row.get("reason"),
                ]
                for row in payload.get("candidates") or []
            ],
        ),
    ]
    if payload.get("blockers"):
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{item}`" for item in payload["blockers"])
    if payload.get("ambiguities"):
        lines.extend(["", "## Retained Ambiguities", ""])
        lines.extend(
            f"- `{row.get('path')}`: {row.get('reason')}"
            for row in payload["ambiguities"]
        )
    lines.extend(
        [
            "",
            "No age, modification time, or LRU signal participates in selection.",
            "",
        ]
    )
    return "\n".join(lines)


def render_apply_receipt(payload: dict[str, Any]) -> str:
    lines = [
        "# Replay Cache Retention Apply Receipt",
        "",
        f"Status: **{payload.get('status')}**",
        f"Manifest: `{payload.get('manifest_path')}`",
        f"Manifest SHA-256: `{payload.get('manifest_sha256')}`",
        f"Cache root: `{payload.get('root')}`",
        "",
        *markdown_table(
            ["Path", "Status", "Bytes", "Error"],
            [
                [
                    row.get("path"),
                    row.get("status"),
                    row.get("bytes"),
                    row.get("error") or "-",
                ]
                for row in payload.get("actions") or []
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def render_rebuild_one(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Replay Cache Rebuild-One Parity",
            "",
            f"Status: **{payload.get('status')}**",
            f"Cache entry: `{(payload.get('cache_entry') or {}).get('path')}`",
            f"Rebuilt payload: `{(payload.get('rebuilt_payload') or {}).get('path')}`",
            "",
            *markdown_table(
                [
                    "Field",
                    "Status",
                    "Structural",
                    "Maximum numeric difference",
                    "Reason",
                ],
                [
                    [
                        row.get("field"),
                        row.get("status"),
                        row.get("structural"),
                        row.get("max_numeric_diff"),
                        row.get("reason") or "-",
                    ]
                    for row in payload.get("checks") or []
                ],
            ),
            "",
        ]
    )
