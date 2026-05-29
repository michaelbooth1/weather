import argparse
import math
import re
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter


SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_EDGE_THRESHOLD = 0.05
DEFAULT_ACTIVE_THRESHOLD = 0.01

REQUIRED_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "model_probability",
    "market_yes",
    "edge",
]

NUMERIC_COLUMNS = [
    "top_temp_c",
    "top_probability",
    "bin_value_c",
    "model_probability",
    "market_yes",
    "market_no",
    "edge",
    "best_bid",
    "best_ask",
    "last_trade_price",
    "volume",
    "liquidity",
    "wu_history_high_c",
    "wu_current_c",
    "wu_max_since_7am_c",
    "eccc_swob_max_c",
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "eccc_forecast_high_c",
]

WEATHER_MARKERS = [
    ("wu_history_high_c", "WU printed high"),
    ("wu_current_c", "Weather.com current"),
    ("wu_max_since_7am_c", "Weather.com max since 7 AM"),
    ("eccc_swob_max_c", "ECCC SWOB max"),
    ("weather_forecast_max_c", "Weather.com forecast max"),
    ("open_meteo_max_c", "Open-Meteo forecast max"),
    ("eccc_forecast_high_c", "ECCC forecast high"),
]


def analyze_snapshot_folder(
    folder_path,
    edge_threshold=DEFAULT_EDGE_THRESHOLD,
    active_threshold=DEFAULT_ACTIVE_THRESHOLD,
    write_plots=True,
):
    folder = Path(folder_path)
    csv_path = folder / "snapshots_long.csv"
    if not csv_path.exists():
        print(f"No snapshots_long.csv found in {folder}")
        return None

    print(f"Analyzing {csv_path}...")
    df = load_snapshot_frame(csv_path)
    if df.empty:
        print(f"Empty data in {csv_path}")
        return None

    first_rows = snapshot_first_rows(df)
    band_metrics = build_band_metrics(df, edge_threshold)
    active_labels = [
        row["range_label"]
        for row in band_metrics
        if (
            row["max_model_probability"] >= active_threshold
            or row["max_market_yes"] >= active_threshold
            or abs(row["max_edge"]) >= edge_threshold
            or abs(row["min_edge"]) >= edge_threshold
        )
    ]

    plot_paths = {}
    if write_plots:
        plot_paths = write_plots_for_folder(
            df,
            first_rows,
            folder,
            active_labels,
            edge_threshold,
        )

    report_path = folder / "analytics_report.md"
    report_text = build_report(
        folder,
        csv_path,
        df,
        first_rows,
        band_metrics,
        plot_paths,
        edge_threshold,
    )
    report_path.write_text(report_text, encoding="utf-8")
    print(f"Saved report to {report_path}")
    return {
        "folder": str(folder),
        "report_path": str(report_path),
        "plot_paths": {key: str(value) for key, value in plot_paths.items()},
        "snapshot_count": int(df["snapshot_id"].nunique()),
        "row_count": int(len(df)),
    }


def load_snapshot_frame(csv_path):
    df = pd.read_csv(csv_path)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{csv_path} is missing required columns: {', '.join(missing)}")

    df = df.copy()
    df["captured_at_local"] = pd.to_datetime(df["captured_at_local"], errors="coerce")
    df["captured_at_utc"] = pd.to_datetime(
        df["captured_at_utc"], errors="coerce", utc=True
    )
    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.sort_values(["captured_at_local", "snapshot_id", "range_label"])
    return df


def snapshot_first_rows(df):
    return (
        df.sort_values(["captured_at_local", "snapshot_id"])
        .drop_duplicates("snapshot_id", keep="first")
        .sort_values("captured_at_local")
    )


def build_report(
    folder,
    csv_path,
    df,
    first_rows,
    band_metrics,
    plot_paths,
    edge_threshold,
):
    event_name = folder.name
    snapshot_count = df["snapshot_id"].nunique()
    band_count = df["range_label"].nunique()
    latest_snapshot = first_rows.iloc[-1]
    latest_id = latest_snapshot["snapshot_id"]
    latest_df = df[df["snapshot_id"] == latest_id].copy()
    latest_df = latest_df.sort_values(
        by=["range_label"], key=lambda s: s.map(label_sort_key)
    )

    lines = [
        "# Snapshot Analytics Report",
        "",
        f"**Event:** `{event_name}`  ",
        f"**Source CSV:** `{csv_path.as_posix()}`  ",
        f"**Report Generated:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  ",
        (
            f"**Analyzed Snapshots:** {snapshot_count} snapshots, {len(df)} band rows, "
            f"{band_count} bands  "
        ),
        (
            f"**Capture Window:** `{fmt_time(first_rows['captured_at_local'].iloc[0])}` "
            f"to `{fmt_time(first_rows['captured_at_local'].iloc[-1])}` local time  "
        ),
        f"**Edge Threshold:** {fmt_pct(edge_threshold)}",
        "",
        "## Detailed Design",
        "",
        (
            "This report treats `snapshots_long.csv` as the immutable tape of "
            "model, market, and source-state observations."
        ),
        "",
        "- Validate schema, duplicated snapshot-band rows, expected row coverage, and capture cadence.",
        "- Summarize each price band by model movement, market movement, edge extremes, and persistence.",
        "- Surface latest positive and negative edges separately from historical edge episodes.",
        "- Track realized/live weather markers alongside market snapshots so forecast and observed-temperature context stays auditable.",
        "- Emit stable artifacts: `analytics_report.md`, `snapshots_analytics.png`, `weather_markers.png`, and `edge_heatmap.png`.",
        "",
        "## Data Quality",
        "",
        markdown_table(
            ["Check", "Result", "Detail"],
            build_quality_rows(df, first_rows, band_count),
        ),
        "",
        "## Latest Snapshot",
        "",
        f"Latest snapshot `{latest_id}` was captured at `{fmt_time(latest_snapshot['captured_at_local'])}`.",
        "",
        markdown_table(
            [
                "Range",
                "Model",
                "Market Yes",
                "Edge",
                "Best Bid",
                "Best Ask",
                "Last",
            ],
            [
                [
                    row["range_label"],
                    fmt_pct(row.get("model_probability")),
                    fmt_pct(row.get("market_yes")),
                    fmt_signed_pct(row.get("edge")),
                    fmt_pct(row.get("best_bid")),
                    fmt_pct(row.get("best_ask")),
                    fmt_pct(row.get("last_trade_price")),
                ]
                for _, row in latest_df.iterrows()
            ],
        ),
        "",
        "## Weather Markers",
        "",
        markdown_table(
            ["Marker", "Latest", "First", "Max", "Max Time", "Min"],
            build_weather_marker_rows(first_rows),
        ),
        "",
        "## Bucket Summary",
        "",
        markdown_table(
            [
                "Range",
                "First Model",
                "Last Model",
                "Model Move",
                "First Market",
                "Last Market",
                "Market Move",
                "Max Edge",
                "Min Edge",
                "Longest +Edge",
                "Longest Threshold Edge",
                "Crossings",
            ],
            [
                [
                    row["range_label"],
                    fmt_pct(row["first_model_probability"]),
                    fmt_pct(row["last_model_probability"]),
                    fmt_signed_pct(row["model_move"]),
                    fmt_pct(row["first_market_yes"]),
                    fmt_pct(row["last_market_yes"]),
                    fmt_signed_pct(row["market_move"]),
                    fmt_signed_pct(row["max_edge"]),
                    fmt_signed_pct(row["min_edge"]),
                    fmt_run(row["longest_positive_run"]),
                    fmt_run(row["longest_threshold_run"]),
                    row["threshold_crossings"],
                ]
                for row in band_metrics
            ],
        ),
        "",
        "## Edge Episodes",
        "",
    ]

    episodes = build_edge_episodes(df, edge_threshold)
    if episodes:
        lines.extend(
            [
                markdown_table(
                    [
                        "Range",
                        "Direction",
                        "Start",
                        "End",
                        "Duration",
                        "Observations",
                        "Peak Edge",
                        "Peak Time",
                    ],
                    [
                        [
                            row["range_label"],
                            row["direction"],
                            fmt_time(row["start_time"], time_only=True),
                            fmt_time(row["end_time"], time_only=True),
                            fmt_minutes(row["duration_minutes"]),
                            row["count"],
                            fmt_signed_pct(row["peak_edge"]),
                            fmt_time(row["peak_time"], time_only=True),
                        ]
                        for row in episodes[:12]
                    ],
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"No contiguous edge episodes crossed {fmt_pct(edge_threshold)}.",
                "",
            ]
        )

    crossings = build_threshold_crossings(df, edge_threshold)
    lines.extend(["## Threshold Crossings", ""])
    if crossings:
        lines.extend(
            [
                markdown_table(
                    ["Time", "Range", "Direction", "Previous Edge", "Current Edge"],
                    [
                        [
                            fmt_time(row["time"], time_only=True),
                            row["range_label"],
                            row["direction"],
                            fmt_signed_pct(row["previous_edge"]),
                            fmt_signed_pct(row["edge"]),
                        ]
                        for row in crossings[:20]
                    ],
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"No new threshold crossings above {fmt_pct(edge_threshold)} were detected.",
                "",
            ]
        )

    lines.extend(["## Charts", ""])
    for title, key in [
        ("Odds and Edge Timeline", "timeline"),
        ("Weather Marker Timeline", "weather"),
        ("Edge Heatmap", "heatmap"),
    ]:
        path = plot_paths.get(key)
        if path:
            lines.extend([f"### {title}", "", f"![{title}]({path.name})", ""])

    lines.extend(["## Automated Takeaways", ""])
    lines.extend(build_takeaways(band_metrics, episodes, edge_threshold))
    lines.append("")
    return "\n".join(lines)


def build_quality_rows(df, first_rows, band_count):
    snapshot_count = df["snapshot_id"].nunique()
    expected_rows = snapshot_count * band_count
    duplicate_rows = int(df.duplicated(["snapshot_id", "range_label"]).sum())
    missing_rows = max(0, expected_rows - len(df))
    null_edges = int(df["edge"].isna().sum())
    null_market = int(df["market_yes"].isna().sum())
    null_model = int(df["model_probability"].isna().sum())
    null_times = int(df["captured_at_local"].isna().sum())
    intervals = (
        first_rows["captured_at_local"]
        .sort_values()
        .diff()
        .dt.total_seconds()
        .div(60.0)
        .dropna()
    )
    if intervals.empty:
        cadence_detail = "Only one snapshot."
    else:
        cadence_detail = (
            f"median {intervals.median():.1f}m, max gap {intervals.max():.1f}m"
        )

    return [
        [
            "Required columns",
            "PASS",
            f"All {len(REQUIRED_COLUMNS)} required columns are present.",
        ],
        [
            "Snapshot-band coverage",
            "PASS" if missing_rows == 0 else "WARN",
            f"{len(df)} rows observed; {expected_rows} expected from {snapshot_count} snapshots x {band_count} bands.",
        ],
        [
            "Duplicate snapshot-band rows",
            "PASS" if duplicate_rows == 0 else "WARN",
            str(duplicate_rows),
        ],
        [
            "Missing numeric values",
            "PASS" if null_edges == 0 and null_market == 0 and null_model == 0 else "WARN",
            f"edge={null_edges}, market_yes={null_market}, model_probability={null_model}",
        ],
        [
            "Timestamp parsing",
            "PASS" if null_times == 0 else "FAIL",
            f"{null_times} rows failed timestamp parsing.",
        ],
        ["Capture cadence", "INFO", cadence_detail],
    ]


def build_weather_marker_rows(first_rows):
    rows = []
    for column, label in WEATHER_MARKERS:
        if column not in first_rows.columns:
            rows.append([label, "-", "-", "-", "-", "-"])
            continue
        series = first_rows[["captured_at_local", column]].dropna(subset=[column])
        if series.empty:
            rows.append([label, "-", "-", "-", "-", "-"])
            continue
        max_idx = series[column].idxmax()
        rows.append(
            [
                label,
                fmt_temp(series[column].iloc[-1]),
                fmt_temp(series[column].iloc[0]),
                fmt_temp(series.loc[max_idx, column]),
                fmt_time(series.loc[max_idx, "captured_at_local"], time_only=True),
                fmt_temp(series[column].min()),
            ]
        )
    return rows


def build_band_metrics(df, edge_threshold):
    metrics = []
    labels = sorted(df["range_label"].dropna().unique(), key=label_sort_key)
    for label in labels:
        sub = df[df["range_label"] == label].sort_values("captured_at_local").copy()
        if sub.empty:
            continue
        edges = sub["edge"].dropna()
        positive_run = longest_run(sub, lambda edge: edge > 0)
        threshold_run = longest_run(sub, lambda edge: abs(edge) >= edge_threshold)
        crossings = build_threshold_crossings(sub, edge_threshold)
        metrics.append(
            {
                "range_label": label,
                "first_model_probability": first_valid(sub["model_probability"]),
                "last_model_probability": last_valid(sub["model_probability"]),
                "model_move": (
                    last_valid(sub["model_probability"])
                    - first_valid(sub["model_probability"])
                ),
                "first_market_yes": first_valid(sub["market_yes"]),
                "last_market_yes": last_valid(sub["market_yes"]),
                "market_move": last_valid(sub["market_yes"]) - first_valid(sub["market_yes"]),
                "max_edge": float(edges.max()) if not edges.empty else math.nan,
                "min_edge": float(edges.min()) if not edges.empty else math.nan,
                "max_model_probability": max_valid(sub["model_probability"]),
                "max_market_yes": max_valid(sub["market_yes"]),
                "longest_positive_run": positive_run,
                "longest_threshold_run": threshold_run,
                "threshold_crossings": len(crossings),
            }
        )
    return metrics


def build_edge_episodes(df, edge_threshold):
    episodes = []
    labels = sorted(df["range_label"].dropna().unique(), key=label_sort_key)
    for label in labels:
        sub = df[df["range_label"] == label].sort_values("captured_at_local")
        episodes.extend(find_runs(sub, lambda edge: edge >= edge_threshold, "positive"))
        episodes.extend(find_runs(sub, lambda edge: edge <= -edge_threshold, "negative"))
    episodes.sort(
        key=lambda row: (
            abs(row["peak_edge"]),
            row["duration_minutes"],
            row["count"],
        ),
        reverse=True,
    )
    return episodes


def build_threshold_crossings(df, edge_threshold):
    crossings = []
    for label, sub in df.groupby("range_label", sort=False):
        sub = sub.sort_values("captured_at_local")
        previous_edge = math.nan
        previous_state = "none"
        for _, row in sub.iterrows():
            edge = row.get("edge")
            if pd.isna(edge):
                continue
            if edge >= edge_threshold:
                state = "positive"
            elif edge <= -edge_threshold:
                state = "negative"
            else:
                state = "none"
            if state != "none" and state != previous_state:
                crossings.append(
                    {
                        "time": row["captured_at_local"],
                        "range_label": label,
                        "direction": state,
                        "previous_edge": previous_edge,
                        "edge": float(edge),
                    }
                )
            previous_state = state
            previous_edge = float(edge)
    crossings.sort(key=lambda row: row["time"])
    return crossings


def longest_run(sub, predicate):
    runs = find_runs(sub, predicate, "run")
    if not runs:
        return None
    runs.sort(key=lambda row: (row["count"], row["duration_minutes"], abs(row["peak_edge"])), reverse=True)
    return runs[0]


def find_runs(sub, predicate, direction):
    sub = sub.sort_values("captured_at_local").reset_index(drop=True)
    runs = []
    start = None
    for pos, row in sub.iterrows():
        edge = row.get("edge")
        active = False if pd.isna(edge) else bool(predicate(float(edge)))
        if active and start is None:
            start = pos
        if (not active or pos == len(sub) - 1) and start is not None:
            end = pos if active and pos == len(sub) - 1 else pos - 1
            if end >= start:
                runs.append(run_from_slice(sub.iloc[start : end + 1], direction))
            start = None
    return runs


def run_from_slice(run, direction):
    if direction == "negative":
        peak_idx = run["edge"].idxmin()
    else:
        peak_idx = run["edge"].abs().idxmax() if direction == "run" else run["edge"].idxmax()
    start_time = run["captured_at_local"].iloc[0]
    end_time = run["captured_at_local"].iloc[-1]
    return {
        "range_label": run["range_label"].iloc[0],
        "direction": direction,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": minutes_between(start_time, end_time),
        "count": int(len(run)),
        "peak_edge": float(run.loc[peak_idx, "edge"]),
        "peak_time": run.loc[peak_idx, "captured_at_local"],
    }


def write_plots_for_folder(df, first_rows, folder, active_labels, edge_threshold):
    plot_paths = {}
    if active_labels:
        plot_paths["timeline"] = write_timeline_plot(
            df, folder / "snapshots_analytics.png", active_labels, edge_threshold
        )
    weather_path = write_weather_plot(first_rows, folder / "weather_markers.png")
    if weather_path:
        plot_paths["weather"] = weather_path
    heatmap_path = write_edge_heatmap(df, folder / "edge_heatmap.png")
    if heatmap_path:
        plot_paths["heatmap"] = heatmap_path
    return plot_paths


def write_timeline_plot(df, output_path, active_labels, edge_threshold):
    fig, axes = plt.subplots(3, 1, figsize=(13, 12), sharex=True)
    colors = plt.cm.tab20(np.linspace(0, 1, max(1, len(active_labels))))
    for color, label in zip(colors, active_labels):
        sub = df[df["range_label"] == label].sort_values("captured_at_local")
        axes[0].plot(sub["captured_at_local"], sub["model_probability"], label=label, color=color, linewidth=1.8)
        axes[1].plot(sub["captured_at_local"], sub["market_yes"], label=label, color=color, linewidth=1.8)
        axes[2].plot(sub["captured_at_local"], sub["edge"], label=label, color=color, linewidth=1.8)

    axes[0].set_title("Model Probability Over Time")
    axes[1].set_title("Market YES Price Over Time")
    axes[2].set_title("Model Edge Over Time")
    axes[2].axhline(0, color="black", linewidth=0.9)
    axes[2].axhline(edge_threshold, color="darkgreen", linewidth=0.8, linestyle="--")
    axes[2].axhline(-edge_threshold, color="darkred", linewidth=0.8, linestyle="--")

    for ax in axes:
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[0].legend(loc="upper left", ncols=2, fontsize=8)
    axes[2].set_xlabel("Local capture time")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot to {output_path}")
    return output_path


def write_weather_plot(first_rows, output_path):
    available = [
        (column, label)
        for column, label in WEATHER_MARKERS
        if column in first_rows.columns and first_rows[column].notna().any()
    ]
    if not available:
        return None

    fig, ax = plt.subplots(figsize=(13, 5))
    colors = plt.cm.tab10(np.linspace(0, 1, len(available)))
    for color, (column, label) in zip(colors, available):
        ax.plot(
            first_rows["captured_at_local"],
            first_rows[column],
            marker="o",
            markersize=3,
            linewidth=1.6,
            label=label,
            color=color,
        )
    ax.set_title("Weather and Forecast Markers Over Time")
    ax.set_ylabel("Temperature C")
    ax.set_xlabel("Local capture time")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot to {output_path}")
    return output_path


def write_edge_heatmap(df, output_path):
    labels = sorted(df["range_label"].dropna().unique(), key=label_sort_key)
    if not labels or df["snapshot_id"].nunique() < 2:
        return None
    pivot = df.pivot_table(
        index="captured_at_local",
        columns="range_label",
        values="edge",
        aggfunc="last",
    )
    pivot = pivot.reindex(columns=labels).sort_index()
    if pivot.empty:
        return None

    fig, ax = plt.subplots(figsize=(13, max(4, len(pivot) * 0.22)))
    vmax = max(0.10, float(np.nanmax(np.abs(pivot.to_numpy()))))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_title("Edge Heatmap by Snapshot and Band")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    y_positions = np.linspace(0, len(pivot.index) - 1, min(12, len(pivot.index))).astype(int)
    ax.set_yticks(y_positions)
    ax.set_yticklabels([fmt_time(pivot.index[pos], time_only=True) for pos in y_positions])
    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot to {output_path}")
    return output_path


def build_takeaways(band_metrics, episodes, edge_threshold):
    lines = []
    positive = [row for row in band_metrics if row["max_edge"] >= edge_threshold]
    negative = [row for row in band_metrics if row["min_edge"] <= -edge_threshold]
    positive.sort(key=lambda row: row["max_edge"], reverse=True)
    negative.sort(key=lambda row: row["min_edge"])

    if positive:
        best = positive[0]
        lines.append(
            f"- Largest positive edge: **{best['range_label']}** at {fmt_signed_pct(best['max_edge'])}."
        )
    else:
        lines.append(f"- No positive edge reached {fmt_pct(edge_threshold)}.")

    if negative:
        worst = negative[0]
        lines.append(
            f"- Largest negative edge: **{worst['range_label']}** at {fmt_signed_pct(worst['min_edge'])}."
        )
    else:
        lines.append(f"- No negative edge reached -{fmt_pct(edge_threshold)}.")

    if episodes:
        longest = sorted(episodes, key=lambda row: (row["count"], row["duration_minutes"]), reverse=True)[0]
        lines.append(
            (
                f"- Longest threshold episode: **{longest['range_label']}** "
                f"({longest['direction']}) for {fmt_minutes(longest['duration_minutes'])} "
                f"across {longest['count']} snapshots."
            )
        )

    movers = sorted(
        band_metrics,
        key=lambda row: abs(row["market_move"]),
        reverse=True,
    )
    if movers:
        top = movers[0]
        lines.append(
            f"- Largest market move: **{top['range_label']}** moved {fmt_signed_pct(top['market_move'])}."
        )
    return lines


def label_sort_key(label):
    text = str(label or "")
    numbers = [int(value) for value in re.findall(r"-?\d+", text)]
    value = numbers[0] if numbers else 10_000
    lower = text.lower()
    if "below" in lower or "under" in lower:
        return (0, value)
    if "higher" in lower or "above" in lower:
        return (2, value)
    return (1, value)


def first_valid(series):
    values = series.dropna()
    return float(values.iloc[0]) if not values.empty else math.nan


def last_valid(series):
    values = series.dropna()
    return float(values.iloc[-1]) if not values.empty else math.nan


def max_valid(series):
    values = series.dropna()
    return float(values.max()) if not values.empty else math.nan


def minutes_between(start, end):
    if pd.isna(start) or pd.isna(end):
        return math.nan
    return (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 60.0


def fmt_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"


def fmt_signed_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:+.1f}%"


def fmt_temp(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1f} C"


def fmt_minutes(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1f}m"


def fmt_run(run):
    if not run:
        return "-"
    return f"{run['count']} obs / {fmt_minutes(run['duration_minutes'])}"


def fmt_time(value, time_only=False):
    if value is None or pd.isna(value):
        return "-"
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%H:%M:%S") if time_only else timestamp.strftime("%Y-%m-%d %H:%M:%S %z")


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_md(value) for value in row) + " |")
    return "\n".join(lines)


def escape_md(value):
    if value is None:
        return "-"
    text = str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    return text if text else "-"


def discover_snapshot_folders(root):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / "snapshots_long.csv").exists()
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate analytics reports for weather market snapshot tapes."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="Specific snapshot event folder. Defaults to every folder under data/snapshots.",
    )
    parser.add_argument(
        "--root",
        default=str(SNAPSHOTS_ROOT),
        help="Root containing snapshot event folders.",
    )
    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=DEFAULT_EDGE_THRESHOLD,
        help="Absolute edge threshold used for episodes and crossings.",
    )
    parser.add_argument(
        "--active-threshold",
        type=float,
        default=DEFAULT_ACTIVE_THRESHOLD,
        help="Minimum model/market probability for a band to be included in the main timeline plot.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Write Markdown only.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.folder:
        folders = [Path(args.folder)]
    else:
        folders = discover_snapshot_folders(args.root)

    if not folders:
        print(f"No snapshot folders found under {args.root}")
        return 1

    for folder in folders:
        analyze_snapshot_folder(
            folder,
            edge_threshold=args.edge_threshold,
            active_threshold=args.active_threshold,
            write_plots=not args.no_plots,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
