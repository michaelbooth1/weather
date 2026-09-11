"""Local interactive what-if view; imports only the offline domain simulator."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

import pandas as pd
import streamlit as st

from weather.market.maker_opportunity_capture import MAX_PACKET_BYTES, parse_json_bytes
from weather.market.maker_reward_simulation import Simulation, capture_presets, simulate


def _number(label, key, defaults, identity, *, minimum=0.0, maximum=100000.0, step=0.01):
    value = st.number_input(label, min_value=minimum, max_value=maximum,
                            value=float(defaults[key]), step=step, key=identity + ":" + key)
    return str(value)


def render_liquidity_simulator_page():
    st.title("Liquidity reward simulator")
    st.caption("Local what-if calculations using Polymarket's published formula. Inputs can be changed without placing orders.")
    defaults, identity, source = asdict(Simulation()), "synthetic", None
    with st.expander("Use a captured market as a starting point"):
        upload = st.file_uploader("Maker opportunity capture JSON", type=["json"])
        if upload is not None:
            raw = upload.getvalue()
            try:
                if len(raw) > MAX_PACKET_BYTES:
                    raise ValueError("capture:file_too_large")
                presets = capture_presets(parse_json_bytes(raw))
                if not presets:
                    raise ValueError("capture:no_supported_single_reward_asset_preset")
                chosen = st.selectbox("Captured market", presets, format_func=lambda item: item["label"])
                defaults.update(chosen["seed"])
                identity = hashlib.sha256(raw).hexdigest() + chosen["condition_id"]
                source = {**chosen, "capture_sha256": hashlib.sha256(raw).hexdigest()}
                st.caption("Captured " + chosen["observed_at"] + ". These are historical book/term observations. Midpoint and daily pool remain assumptions.")
            except (ValueError, KeyError, TypeError) as exc:
                st.error("Capture could not be used: " + str(exc))
                return
    st.caption("Starting point: " + (source["label"] if source else "synthetic example") + ". Adjusted midpoint, competition, pool and fills are assumed.")
    values = {}
    left, right = st.columns(2)
    with left:
        values["plan"] = st.selectbox("Buy plan", ["YES", "NO", "BOTH"], key=identity + ":plan")
        values["midpoint"] = _number("Assumed adjusted YES midpoint", "midpoint", defaults, identity, maximum=1.0)
        values["yes_price"] = _number("YES buy price", "yes_price", defaults, identity, minimum=0.001, maximum=0.999, step=0.001)
        values["no_price"] = _number("NO buy price", "no_price", defaults, identity, minimum=0.001, maximum=0.999, step=0.001)
        values["yes_shares"] = _number("YES shares", "yes_shares", defaults, identity, minimum=0.01)
        values["no_shares"] = _number("NO shares", "no_shares", defaults, identity, minimum=0.01)
    with right:
        values["pool"] = _number("Assumed whole-day reward pool (reward tokens)", "pool", defaults, identity, minimum=0.01)
        values["other_q"] = _number("Other makers' combined Q-min", "other_q", defaults, identity, maximum=100000000.0, step=1.0)
        values["participation"] = str(st.slider("Participation in selected hours", 0.0, 1.0, 1.0, 0.01, key=identity + ":participation"))
        values["yes_remaining"] = str(st.slider("YES shares remaining after fills", 0.0, 1.0, 1.0, 0.01, key=identity + ":yes_remaining"))
        values["no_remaining"] = str(st.slider("NO shares remaining after fills", 0.0, 1.0, 1.0, 0.01, key=identity + ":no_remaining"))
    with st.expander("Book, eligibility, capital and cost assumptions"):
        columns = st.columns(2)
        fields = (
            ("YES best bid", "yes_best_bid", 0.0, 1.0), ("YES best ask", "yes_best_ask", 0.0, 1.0),
            ("NO best bid", "no_best_bid", 0.0, 1.0), ("NO best ask", "no_best_ask", 0.0, 1.0),
            ("Price tick", "tick", 0.0001, 0.1), ("Exchange minimum (shares)", "exchange_minimum", 0.01, 100000.0),
            ("Reward minimum (shares)", "reward_minimum", 0.01, 100000.0), ("Maximum reward distance (cents)", "max_spread_cents", 0.01, 100.0),
            ("Backed wallet (pUSD)", "wallet", 0.0, 100000.0), ("Per-order ceiling (pUSD)", "order_cap", 0.0, 100000.0),
            ("Cleanup reserve (pUSD)", "cleanup", 0.0, 100000.0), ("Operating cost per scenario (pUSD)", "operating_cost", 0.0, 100000.0),
            ("All-in exit loss per filled share (pUSD)", "exit_loss_per_filled_share", 0.0, 1.0),
            ("Assumed pUSD per reward token", "reward_to_collateral", 0.0001, 100.0),
            ("Assumed completed-day minimum (reward tokens)", "payout_minimum", 0.0, 100000.0),
        )
        for index, (label, key, lower, upper) in enumerate(fields):
            with columns[index % 2]:
                values[key] = _number(label, key, defaults, identity, minimum=lower, maximum=upper,
                                      step=0.0001 if key == "tick" else 0.01)
        st.caption("Reward token: Polygon USDC.e (0x2791...). Collateral: pUSD (0xc011...). The conversion above is an explicit scenario assumption. Daily minimum assumes this is the account's only reward income.")
    try:
        result = simulate(Simulation(**values))
    except (ValueError, ArithmeticError) as exc:
        st.error("Adjust the inputs: " + str(exc))
        return
    result["starting_observation"] = source
    if not result["modeled_feasible"]:
        st.warning("Plan fails the chosen assumptions: " + "; ".join(code for group in result["blockers"].values() for code in group))
    metrics = st.columns(3)
    metrics[0].metric("Remaining Q-min", f'{float(result["remaining_q_min"]):.4f}')
    metrics[1].metric("Collateral including cleanup", f'{float(result["capital"]["total_with_cleanup"]):.2f} pUSD')
    share = result["horizons"][0]["sample_share"]
    metrics[2].metric("Share during participating samples", f'{float(share):.2%}')
    records = [{
        "Hours": float(row["hours"]),
        "Gross reward (tokens)": None if row["gross_reward"] is None else float(row["gross_reward"]),
        "Modeled day payout (tokens)": None if row["modeled_day_payout"] is None else float(row["modeled_day_payout"]),
        "After costs (pUSD)": None if row["net_collateral"] is None else float(row["net_collateral"]),
        "Zero-payment result (pUSD)": float(row["zero_payment_net_collateral"]),
    } for row in result["horizons"]]
    frame = pd.DataFrame(records)
    st.line_chart(frame, x="Hours", y=["After costs (pUSD)", "Zero-payment result (pUSD)"],
                  x_label="Hours participating in a hypothetical day", y_label="Scenario net (pUSD)")
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption("Each row is a separate completed-day scenario. Outside the chosen hours we earn nothing. Below-minimum daily earnings are not carried forward.")
    with st.expander("Formula and assumptions"):
        st.latex(r"q = size\left(1-\frac{s}{v}\right)^2;\quad share=\frac{Q_{min,ours}}{Q_{min,ours}+Q_{min,others}}")
        st.write("At midpoints 0.10 through 0.90, Q-min is max(min(Q1,Q2), max(Q1,Q2)/3). Outside that range it is min(Q1,Q2). Orders below minimum size or at/beyond the maximum distance score zero.")
        st.json(result["assumptions"])
        st.markdown("[Official scoring formula](https://docs.polymarket.com/programs/liquidity-rewards) · [Daily payout rules](https://help.polymarket.com/en/articles/13364466-liquidity-rewards)")
    st.download_button("Save scenario JSON", json.dumps(result, indent=2, default=str, allow_nan=False),
                       file_name="liquidity-reward-scenario.json", mime="application/json")
