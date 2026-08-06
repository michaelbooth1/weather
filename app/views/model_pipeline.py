"""Presentation-only rendering for one model distribution pipeline run."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.table_utils import arrow_safe_records


# This is the execution order in model_distribution. Entries whose implementation
# does not emit a snapshot stay in the table as explicitly unavailable; the view
# never invents an intermediate distribution.
PIPELINE_STAGE_CATALOG = (
    ("climatology_prior", "Base climatology"),
    ("__feature_model__", "Feature-model distribution"),
    ("feature_blend", "Feature-model blend"),
    ("empirical_weighted", "Empirical weighted blend"),
    ("bucket_transition_blend", "Bucket-transition blend"),
    ("post_live_signals", "Live-signal adjustment"),
    ("trusted_observed_high_floor", "Trusted observed-high floor"),
    ("intraday_tail", "Intraday tail shaping"),
    ("plausible_cap", "Plausible-cap shaping"),
    ("forecast_pull", "Forecast floor / pull"),
    ("ramp_warm_tail_dampening", "Ramp warm-tail dampening"),
    ("afternoon_residual_centering", "Afternoon residual centering"),
    ("validated_current_max_floor", "Validated current-max floor"),
    ("settlement_lag_adjusted", "Settlement-lag adjustment"),
    ("current_observed_floor", "Current-observation floor"),
    ("wu_floor_residual", "WU floor residual"),
    ("late_day_continuation_blend", "Late-day continuation blend"),
    ("high_has_stood_lockin", "High-has-stood lock-in"),
    ("expanded_late_day_lockin", "Expanded late-day lock-in"),
    ("standing_high_partial_lockin", "Standing-high partial lock-in"),
    ("late_day_lockin", "Late-day lock-in"),
    ("pre_calibration_model", "Pre-calibration model"),
    ("overconfidence_calibration", "Probability calibration"),
    ("current_max_boundary_guard", "Current-max boundary guard"),
    ("final_model", "Final served distribution"),
)

UNSNAPSHOTTED_STAGE_KEYS = {
    "trusted_observed_high_floor",
    "intraday_tail",
    "plausible_cap",
}
STANDALONE_COMPONENT_KEYS = {
    "intraday_high",
    "current_bucket",
    "wind_regime",
    "cloud_regime",
    "forecast_error",
    "forecast_cap",
    "bucket_transition_model",
}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distribution_values(distribution):
    values = {}
    for bucket, probability in (distribution or {}).items():
        bucket_value = _number(bucket)
        probability_value = _number(probability)
        if bucket_value is None or probability_value is None:
            continue
        values[bucket_value] = probability_value
    return values


def _distribution_stats(distribution):
    values = _distribution_values(distribution)
    mass = sum(values.values())
    centre = (
        sum(bucket * probability for bucket, probability in values.items()) / mass
        if mass > 0
        else None
    )
    return values, centre, mass


def floor_binding_summary(component_payload):
    """Describe the recorded hard-floor boundary without fabricating a snapshot."""

    payload = component_payload or {}
    components = payload.get("components") or {}
    floor_bucket = _number(payload.get("observed_floor_bucket"))
    pre_floor = components.get("post_live_signals")
    final = components.get("final_model")
    if floor_bucket is None:
        return {
            "status": "ABSENT",
            "floor_bucket": None,
            "pre_floor_mass_below": None,
            "final_mass_below": None,
            "note": "No trusted observed-high floor was recorded for this build.",
        }
    if not pre_floor:
        return {
            "status": "UNAVAILABLE",
            "floor_bucket": floor_bucket,
            "pre_floor_mass_below": None,
            "final_mass_below": None,
            "note": "The pre-floor post-live-signal snapshot is absent.",
        }
    pre_values = _distribution_values(pre_floor)
    final_values = _distribution_values(final)
    pre_mass = sum(
        probability
        for bucket, probability in pre_values.items()
        if bucket < floor_bucket
    )
    final_mass = (
        sum(
            probability
            for bucket, probability in final_values.items()
            if bucket < floor_bucket
        )
        if final_values
        else None
    )
    return {
        "status": "BINDING" if pre_mass > 1e-9 else "NOT BINDING",
        "floor_bucket": floor_bucket,
        "pre_floor_mass_below": pre_mass,
        "final_mass_below": final_mass,
        "note": (
            "Mass below the trusted floor in the last recorded pre-floor state. "
            "The floor stage does not emit its own distribution snapshot."
        ),
    }


def pipeline_stage_rows(component_payload, *, unit):
    """Return every known stage, retaining absent snapshots as explicit rows."""

    payload = component_payload or {}
    components = payload.get("components") or {}
    floor = floor_binding_summary(payload)
    rows = []
    previous_centre = None
    known_keys = {key for key, _label in PIPELINE_STAGE_CATALOG}
    feature_key = next(
        (key for key in components if str(key).endswith("_feature_model")),
        None,
    )
    if feature_key:
        known_keys.add(feature_key)

    for order, (key, label) in enumerate(PIPELINE_STAGE_CATALOG, start=1):
        if key == "trusted_observed_high_floor":
            floor_mass = floor.get("pre_floor_mass_below")
            rows.append({
                "Order": order,
                "Stage key": key,
                "Stage": label,
                "Snapshot": "Unavailable",
                "Centre": "-",
                "Centre delta": "-",
                "Mass": "-",
                "Detail": (
                    f"{floor['status']}; floor {floor['floor_bucket']:g} {unit}; "
                    f"{floor_mass:.2%} pre-floor mass below boundary"
                    if floor.get("floor_bucket") is not None and floor_mass is not None
                    else floor["note"]
                ),
            })
            continue

        component_key = feature_key if key == "__feature_model__" else key
        distribution = components.get(component_key) if component_key else None
        if not distribution:
            detail = (
                "This stage runs without recording a distribution snapshot."
                if key in UNSNAPSHOTTED_STAGE_KEYS
                else "Stage absent for this model path or cutoff."
            )
            rows.append({
                "Order": order,
                "Stage key": component_key or "active_feature_model",
                "Stage": label,
                "Snapshot": "Absent",
                "Centre": "-",
                "Centre delta": "-",
                "Mass": "-",
                "Detail": detail,
            })
            continue

        _values, centre, mass = _distribution_stats(distribution)
        delta = centre - previous_centre if centre is not None and previous_centre is not None else None
        rows.append({
            "Order": order,
            "Stage key": component_key,
            "Stage": (
                f"{str(component_key).removesuffix('_feature_model').upper()} feature model"
                if key == "__feature_model__"
                else label
            ),
            "Snapshot": "Present",
            "Centre": f"{centre:.2f} {unit}" if centre is not None else "-",
            "Centre delta": f"{delta:+.2f} {unit}" if delta is not None else "baseline",
            "Mass": f"{mass:.6f}",
            "Detail": "Delta is from the previous recorded pipeline state.",
        })
        previous_centre = centre

    # Future pipeline snapshots must remain visible even before this view's label
    # catalog is updated. Standalone input opinions are intentionally left to the
    # existing driver panel.
    for key, distribution in components.items():
        if (
            key in known_keys
            or key in STANDALONE_COMPONENT_KEYS
            or not distribution
        ):
            continue
        _values, centre, mass = _distribution_stats(distribution)
        delta = centre - previous_centre if centre is not None and previous_centre is not None else None
        rows.append({
            "Order": len(rows) + 1,
            "Stage key": key,
            "Stage": str(key).replace("_", " ").title(),
            "Snapshot": "Present (uncatalogued)",
            "Centre": f"{centre:.2f} {unit}" if centre is not None else "-",
            "Centre delta": f"{delta:+.2f} {unit}" if delta is not None else "baseline",
            "Mass": f"{mass:.6f}",
            "Detail": "Recorded by the serving pipeline; label not yet catalogued by the UI.",
        })
        previous_centre = centre
    return rows


def pipeline_distribution_frame(component_payload, *, unit):
    """Build a display matrix from recorded snapshots only; never fill a gap."""

    payload = component_payload or {}
    components = payload.get("components") or {}
    catalog_labels = dict(PIPELINE_STAGE_CATALOG)
    feature_key = next(
        (key for key in components if str(key).endswith("_feature_model")),
        None,
    )
    stage_keys = []
    for key, _label in PIPELINE_STAGE_CATALOG:
        component_key = feature_key if key == "__feature_model__" else key
        if (
            key not in UNSNAPSHOTTED_STAGE_KEYS
            and component_key
            and components.get(component_key)
        ):
            stage_keys.append(component_key)
    for key, distribution in components.items():
        if (
            key in stage_keys
            or key in STANDALONE_COMPONENT_KEYS
            or not distribution
        ):
            continue
        stage_keys.append(key)
    buckets = sorted({
        bucket
        for key in stage_keys
        for bucket in _distribution_values(components.get(key)).keys()
    })
    if not buckets or not stage_keys:
        return pd.DataFrame()
    rows = []
    for bucket in buckets:
        row = {"Bucket": f"{bucket:g} {unit}"}
        for key in stage_keys:
            label = (
                f"{str(key).removesuffix('_feature_model').upper()} feature model"
                if str(key).endswith("_feature_model")
                else catalog_labels.get(key, str(key).replace("_", " ").title())
            )
            row[label] = _distribution_values(components.get(key)).get(bucket)
        rows.append(row)
    return pd.DataFrame(rows).set_index("Bucket")


def _percent(value):
    return f"{value:.2%}" if value is not None else "-"


def render_pipeline_model_view(model, *, market_label, unit):
    """Render the exact recorded pipeline for the current serving build."""

    component_payload = model.get("distribution_components") or {}
    cutoff_hour = component_payload.get("cutoff_hour")
    floor = floor_binding_summary(component_payload)

    st.subheader("Pipeline Centre Movement")
    st.caption(
        f"{market_label}; effective serving cutoff "
        f"{int(cutoff_hour):02d}:00" if cutoff_hour is not None
        else f"{market_label}; effective serving cutoff unavailable"
    )
    st.caption(
        "This is the cutoff that actually ran in the current serving build. "
        "The serving result does not contain alternate historical cutoffs, so the UI does not replay one."
    )

    summary_cols = st.columns(4)
    summary_cols[0].metric(
        "Effective cutoff",
        f"{int(cutoff_hour):02d}:00" if cutoff_hour is not None else "Unavailable",
    )
    summary_cols[1].metric(
        "Trusted floor",
        f"{floor['floor_bucket']:g} {unit}" if floor.get("floor_bucket") is not None else "Absent",
    )
    summary_cols[2].metric("Floor state", floor["status"])
    summary_cols[3].metric(
        "Pre-floor mass truncated",
        _percent(floor.get("pre_floor_mass_below")),
    )

    if not (component_payload.get("components") or {}):
        st.warning(
            "Pipeline stage snapshots are unavailable for this serving result. "
            "No distributions or centre movements were inferred."
        )

    st.markdown("**Stage-by-stage centre**")
    st.caption(
        "Absent stages stay visible. Centre deltas compare recorded states only; "
        "the UI does not interpolate an unrecorded stage."
    )
    st.dataframe(
        arrow_safe_records(pipeline_stage_rows(component_payload, unit=unit)),
        width="stretch",
        hide_index=True,
    )

    frame = pipeline_distribution_frame(component_payload, unit=unit)
    st.markdown("**Recorded stage distributions**")
    if frame.empty:
        st.info("No recorded stage distribution is available for this build.")
    else:
        st.line_chart(frame, width="stretch")
        with st.expander("Distribution values by stage"):
            st.dataframe(frame, width="stretch")

    st.markdown("**Final served distribution vs market implied distribution**")
    market_rows = []
    for row in model.get("model_rows") or []:
        market_rows.append({
            key: row.get(key)
            for key in ("Range", "Model", "Market yes", "Edge", "Market status")
            if key in row
        })
    if market_rows:
        st.dataframe(arrow_safe_records(market_rows), width="stretch", hide_index=True)
    else:
        st.info("No market-implied distribution was returned for this event.")
