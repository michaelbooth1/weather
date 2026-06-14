"""Replay corpus engine: re-run the model over captured snapshot inputs.

Each captured snapshot persists its full merged ``sources`` and the exact build
``now`` (see ``snapshot_tracker.write_replay_input``). ``estimate_distribution``
is pure given ``(sources, now)`` plus the loaded artifacts, so *any* version of
the model code can be re-run over the corpus and scored against the realized
settlement. That converts every captured day into a permanent, replayable test
case and makes model changes measurable instead of hand-validated.

This module is the pure engine (no scoring, no I/O beyond reading the corpus);
``replay_backtest`` drives it and scores the output.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import date_from_event_slug, market_id_from_slug
from market_registry import DEFAULT_MARKET_ID
from model_identity import identity_hash, model_replay_identity
from model_constants import TORONTO_TZ

# Captured records (real inputs, byte-faithfully replayable) are committed.
REPLAY_INPUTS_FILENAME = "replay_inputs.jsonl"
# Reconstructed records (approximate, regenerable from snapshots.jsonl) are kept
# separate and git-ignored, so they never bloat the committed corpus.
RECONSTRUCTED_FILENAME = "replay_inputs_reconstructed.jsonl"


# --- Corpus loading ---------------------------------------------------------

def _read_jsonl(path):
    records = []
    if not Path(path).exists():
        return records
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_replay_records(folder):
    """Read one market day's replay corpus: captured records first, then any
    reconstructed records for snapshots not already captured (captured always
    wins, so a real input never loses to an approximate reconstruction)."""
    folder = Path(folder)
    captured = _read_jsonl(folder / REPLAY_INPUTS_FILENAME)
    seen = {str(record.get("snapshot_id")) for record in captured}
    merged = list(captured)
    for record in _read_jsonl(folder / RECONSTRUCTED_FILENAME):
        snapshot_id = str(record.get("snapshot_id"))
        if snapshot_id not in seen:
            merged.append(record)
            seen.add(snapshot_id)
    return merged


def index_records_by_snapshot(records):
    """snapshot_id -> record. Later duplicates win (a re-run overwrites)."""
    return {str(record.get("snapshot_id")): record for record in records}


def parse_built_at(record):
    """The exact ``now`` the build used, as a tz-aware datetime."""
    value = record.get("built_at") or record.get("captured_at_local")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TORONTO_TZ)
    return parsed


def record_target_date(record):
    value = record.get("target_date")
    if value:
        try:
            return datetime.fromisoformat(str(value)).date()
        except ValueError:
            pass
    slug = record.get("event_slug")
    if slug:
        return date_from_event_slug(slug)
    return None


def is_reconstructed(record):
    return (record.get("source") or "").lower() == "reconstructed"


# --- Distribution helpers ---------------------------------------------------

def as_int_distribution(distribution):
    """Normalize a distribution to ``{int: float}`` (JSON round-trips int keys
    to strings, and the recorded distribution and a freshly replayed one must be
    comparable)."""
    out = {}
    for bucket, probability in (distribution or {}).items():
        try:
            out[int(bucket)] = float(probability)
        except (TypeError, ValueError):
            continue
    return out


def distribution_l1(left, right):
    """Sum of absolute per-bucket probability differences (0 == identical).

    The replay fidelity canary: replaying a record with the *same* code version
    that produced it must reproduce its recorded distribution (L1 ~ 0).
    """
    a = as_int_distribution(left)
    b = as_int_distribution(right)
    keys = set(a) | set(b)
    return sum(abs(a.get(key, 0.0) - b.get(key, 0.0)) for key in keys)


# --- Replay -----------------------------------------------------------------

def replay_distribution(model, record):
    """Re-run ``estimate_distribution`` for one captured snapshot with ``model``'s
    current code.

    Sets the model's target date to the record's day first (the distribution
    depends on the target-date climatology window) and threads the exact build
    ``now`` (its hour drives the cutoff, the late-day lock-in, and every
    time-weighted signal). Returns the freshly computed ``{int: float}``
    distribution. ``model.active_model_kind`` and the calibration context are
    left set as a side effect, so ``band_model_probability`` can be called next.
    """
    sources = record.get("sources") or {}
    if not sources:
        return {}
    target_date = record_target_date(record)
    if target_date is not None:
        model.set_target_date(target_date)
    return model.estimate_distribution(sources, now=parse_built_at(record))


def band_bin_data(band):
    """Translate a recorded ``snapshots_long`` row into the ``bin_data`` shape
    that ``bin_probability`` consumes. ``value_hi`` must be recovered from the
    range label: tapes store only the band's lower value, and without it
    bin_probability scores an F range band ("90-91") as its lower bucket
    alone -- which silently zeroed the replayed probability whenever the model
    correctly concentrated on the band's UPPER bucket."""
    value = band.get("bin_value_c")
    label = band.get("range_label")
    numbers = re.findall(r"\d+", str(label or ""))
    value_hi = int(numbers[-1]) if len(numbers) >= 2 else value
    return {
        "kind": band.get("bin_kind"),
        "value": value,
        "value_hi": value_hi,
        "label": label,
        "market_yes": band.get("market_yes"),
        "market_no": band.get("market_no"),
    }


def band_model_probability(model, distribution, band):
    """Model probability for one market band from a replayed distribution,
    computed exactly as production records it: ``bin_probability`` applies the
    same market-bin calibration using the context ``estimate_distribution`` just
    set on the model."""
    return model.bin_probability(distribution, band_bin_data(band))


def replay_model_version(model):
    """The model-kind version the *replay* just produced (set as a side effect
    of ``replay_distribution``)."""
    try:
        return model.get_model_version_string()
    except Exception:  # noqa: BLE001 - defensive; version string is cosmetic
        return None


def replay_model_identity(model):
    """The replay identity the freshly computed distribution used.

    This is stricter than the human version label: it includes active model
    kind, market id, distribution-code fingerprints, and per-market artifact
    fingerprints.
    """
    try:
        return model_replay_identity(model)
    except Exception:  # noqa: BLE001 - defensive; fidelity can fall back
        return None


def replay_identity_hash(model):
    return identity_hash(replay_model_identity(model))


# --- Reconstruction bootstrap ----------------------------------------------
# The replay corpus is forward-looking: only snapshots captured by code that
# writes replay_inputs.jsonl are fully, faithfully replayable. To make the
# already-captured days usable immediately we reconstruct an *approximate*
# sources dict from what older snapshots did store -- the live feature vector
# and the source-value scalars. These reconstructed records are labelled
# ``source="reconstructed"`` so the backtest reports them separately, scores the
# fidelity gap, and never gates on them.

# Inverse maps: a representative raw value that ``wind_group``/``cloud_group``
# map back to, so the reconstructed feature vector reproduces the stored groups.
_WIND_GROUP_REP = {
    "E-SE/onshore-ish": "E",
    "S-SW": "SW",
    "W-NW": "W",
    "N-NE": "N",
    "SSE": "SSE",
    "Other/variable": "VAR",
}
_CLOUD_GROUP_REP = {
    "Precip": "rain",
    "Fog/haze": "fog",
    "Fair/clear": "fair",
    "Partly cloudy": "partly cloudy",
    "Mostly cloudy/overcast": "overcast",
    "Other": "other",
}


def _f(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ok(data):
    return {"ok": True, "stale": False, "fetched_at": None, "data": data}


def reconstruct_sources(snapshot, target_date):
    """Rebuild an approximate ``sources`` dict from a stored snapshot record.

    Uses the live feature vector (the exact features fed to the model) and the
    source-value scalars to fabricate just enough of each source that
    ``estimate_distribution`` reproduces the feature-model path and the floor
    pipeline. ``local_history`` is read fresh from the snapshot's own market's
    daily summary (a deterministic, network-free file read), so the climatology
    prior is exact -- and not Toronto's for the 11 US markets.
    """
    from toronto_model import TorontoHighTempModel  # lazy: avoids any import cycle

    market_id = market_id_from_slug(snapshot.get("event_slug")) or DEFAULT_MARKET_ID

    features = snapshot.get("feature_vector") or {}
    values = snapshot.get("source_values") or {}
    cutoff_hour = features.get("cutoff_hour")
    try:
        cutoff_hour = int(cutoff_hour)
    except (TypeError, ValueError):
        captured = parse_built_at({"built_at": snapshot.get("captured_at_local")})
        cutoff_hour = captured.hour if captured else 12

    high_so_far = _f(features.get("high_so_far"))
    current_temp = _f(features.get("current_temp"))
    rise = _f(features.get("rise_from_7am"))
    dewpoint = _f(features.get("dewpoint_c"))
    humidity = _f(features.get("humidity"))
    pressure = _f(features.get("pressure"))
    pressure_trend = _f(features.get("pressure_trend_3h"))
    wind_speed = _f(features.get("wind_speed_kmh"))
    forecast_high = _f(features.get("forecast_high"))
    wind_rep = _WIND_GROUP_REP.get(features.get("wind_group"))
    cloud_rep = _CLOUD_GROUP_REP.get(features.get("cloud_group"))

    history_high = _f(values.get("wu_history_high_c"))
    if current_temp is None:
        current_temp = _f(values.get("wu_current_c")) or high_so_far or history_high

    rows = []
    # 7am anchor so rise_from_7am reconstructs.
    if rise is not None and current_temp is not None:
        rows.append({"time": "07:00", "temp_c": current_temp - rise})
    # 3h-before-cutoff anchor so pressure_trend_3h reconstructs.
    if pressure is not None and pressure_trend is not None and cutoff_hour - 3 >= 0:
        rows.append({"time": f"{cutoff_hour - 3:02d}:00", "pressure": pressure - pressure_trend})
    # The day's peak (if it was reached before the current reading).
    if high_so_far is not None and (current_temp is None or high_so_far > current_temp):
        peak_hour = max(0, min(cutoff_hour - 1, 14))
        rows.append({"time": f"{peak_hour:02d}:00", "temp_c": high_so_far})
    # The latest (cutoff) observation carries the point-in-time features.
    latest = {
        "time": f"{max(0, min(cutoff_hour, 23)):02d}:00",
        "temp_c": current_temp,
        "dewpoint_c": dewpoint,
        "humidity": humidity,
        "pressure": pressure,
        "wind_kmh": wind_speed,
        "wind": wind_rep,
        "condition": cloud_rep,
        "clouds": None,
    }
    rows.append(latest)

    history_data = {
        "rows": rows,
        "latest": latest,
        "max_c": history_high if history_high is not None else high_so_far,
        "max_times": [],
    }

    model = TorontoHighTempModel(target_date=target_date, market_id=market_id)
    try:
        local_history = model.fetch_local_history()
    except Exception:  # noqa: BLE001 - local read; degrade to unavailable prior
        local_history = {"available": False}

    return {
        "local_history": _ok(local_history),
        "wu_history": _ok(history_data),
        "wu_current": _ok({
            "temp_c": _f(values.get("wu_current_c")),
            "max_since_7am_c": _f(values.get("wu_max_since_7am_c")),
            "dewpoint_c": dewpoint,
            "humidity": humidity,
            "target_date_match": True,
        }),
        "eccc_swob": _ok({"same_day_max_c": _f(values.get("eccc_swob_max_c")), "rows": []}),
        "eccc_citypage": _ok({"forecast_high_c": _f(values.get("eccc_forecast_high_c"))}),
        "weather_forecast": _ok({"rows": _max_only_rows(_f(values.get("weather_forecast_max_c")))}),
        "open_meteo": _ok({
            "rows": _max_only_rows(_f(values.get("open_meteo_max_c"))),
            "day_max_c": forecast_high,
        }),
        "metar": {"ok": False, "data": {}},
    }


def _max_only_rows(max_temp):
    """A one-row forecast list whose only purpose is to carry the daily max
    (``max_row_temp`` reads the max; the floor pipeline only needs that)."""
    if max_temp is None:
        return []
    return [{"temp_c": max_temp}]


def reconstruct_record(snapshot):
    """Build a labelled ``reconstructed`` replay record from a snapshot record."""
    target_date = record_target_date(snapshot)
    return {
        "schema_version": "toronto_replay_inputs_reconstructed_v0.1",
        "source": "reconstructed",
        "snapshot_id": snapshot.get("snapshot_id"),
        "captured_at_utc": snapshot.get("captured_at_utc"),
        "captured_at_local": snapshot.get("captured_at_local"),
        "event_slug": snapshot.get("event_slug"),
        "target_date": target_date.isoformat() if target_date else snapshot.get("target_date"),
        "model_version": snapshot.get("model_version"),
        "built_at": snapshot.get("captured_at_local"),
        "recorded_distribution": snapshot.get("distribution") or {},
        "sources": reconstruct_sources(snapshot, target_date),
    }


def load_snapshot_records(folder):
    return _read_jsonl(Path(folder) / "snapshots.jsonl")


def reconstruct_corpus_for_folder(folder):
    """Append reconstructed replay records (to the git-ignored
    ``replay_inputs_reconstructed.jsonl``) for any snapshot in ``snapshots.jsonl``
    not already present in the corpus. Returns (added, skipped).

    Captured records are never overwritten -- the full-fidelity corpus always
    wins over a reconstruction.
    """
    folder = Path(folder)
    existing = {str(r.get("snapshot_id")) for r in load_replay_records(folder)}
    snapshots = load_snapshot_records(folder)
    added = 0
    skipped = 0
    out_path = folder / RECONSTRUCTED_FILENAME
    with out_path.open("a", encoding="utf-8") as handle:
        for snapshot in snapshots:
            snapshot_id = str(snapshot.get("snapshot_id"))
            if snapshot_id in existing or snapshot_id == "None":
                skipped += 1
                continue
            try:
                record = reconstruct_record(snapshot)
            except Exception as exc:  # noqa: BLE001 - skip an unreconstructable snapshot
                print(f"    skip {snapshot_id}: {type(exc).__name__}: {exc}")
                skipped += 1
                continue
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            existing.add(snapshot_id)
            added += 1
    return added, skipped


def _reconstruct_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Bootstrap the replay corpus by reconstructing approximate "
                    "inputs from already-captured snapshots."
    )
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under data/snapshots).")
    parser.add_argument("--snapshots-root", default=str(Path("data") / "snapshots"))
    args = parser.parse_args()

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots.jsonl"))
    if not folders:
        print("No snapshot folders found.")
        return

    total_added = 0
    for folder in folders:
        added, skipped = reconstruct_corpus_for_folder(folder)
        total_added += added
        print(f"  {Path(folder).name}: +{added} reconstructed, {skipped} skipped (already present)")
    print(f"Reconstructed {total_added} snapshot input(s) across {len(folders)} folder(s).")


if __name__ == "__main__":
    _reconstruct_main()
