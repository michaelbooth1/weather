"""Generic edge and PnL helpers."""

from __future__ import annotations

import pandas as pd


def pnl_trades(trades):
    """Aggregate per-trade P&L (in [-1, 1] units of one share)."""
    n = len(trades)
    if not n:
        return {"n": 0, "pnl": 0.0, "avg": 0.0, "hit_rate": 0.0}
    total = sum(t for t in trades)
    wins = sum(1 for t in trades if t > 0)
    return {"n": n, "pnl": total, "avg": total / n, "hit_rate": wins / n}


def trade_pnl(model_p, market_yes, market_no, outcome, threshold):
    """P&L of taking model edge on one band, held to resolution."""
    edge = model_p - market_yes
    if edge > threshold:
        return outcome - market_yes
    if edge < -threshold:
        cost_no = market_no if market_no is not None and not pd.isna(market_no) else (1.0 - market_yes)
        return (1 - outcome) - cost_no
    return None


def pnl_for_rows(rows, thresholds):
    out = {}
    for threshold in thresholds:
        trades = [
            trade_pnl(
                row["model_probability"],
                row["market_yes"],
                row.get("market_no"),
                row["outcome"],
                threshold,
            )
            for row in rows
        ]
        out[threshold] = pnl_trades([trade for trade in trades if trade is not None])
    return out


def merge_pnl(parts):
    n = sum(p["n"] for p in parts)
    pnl = sum(p["pnl"] for p in parts)
    return {
        "n": n,
        "pnl": pnl,
        "hit_rate": (sum(p["hit_rate"] * p["n"] for p in parts) / n) if n else 0.0,
        "avg": (pnl / n) if n else 0.0,
    }

