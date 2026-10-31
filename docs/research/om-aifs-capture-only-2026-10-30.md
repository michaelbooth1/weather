# Open-Meteo AIFS rename: capture-only branch note (2026-10-30)

Branch `claude/om-aifs-model-id-20261030`. Lane L2, defect from L3's replay-input sweep.

## Defect

Every le0929 replay record had null `ecmwf_aifs025` and `gfs_graphcast025` daily
highs. Open-Meteo answers an id it no longer serves with an all-null column, not
an HTTP error. A live read-only probe at KLGA on 2026-10-30 counted non-null hours
out of 48 for each id:

| Id | Non-null hours |
| --- | --- |
| `ecmwf_aifs025` | 0 |
| `ecmwf_aifs025_single` | 48 |
| `gfs_graphcast025` | 0 |
| `ecmwf_ifs025` | 48 |
| `ncep_aigfs025` | 48 |

The probe script is `C:\t\l2\dst_probes\l2_om_model_ids_probe.py`, sha256
`1081d6d740e33277144616cb9dccd0bc9d5a0decf9f3e2aee0f8d5b4d3d6706a`.

## What changed (master ruling: capture-only, record-first)

- `ecmwf_aifs025_single` is requested **in addition** to the existing ids. It is
  recorded only under the new payload key `capture_only_models`. It never enters
  `day_model_highs`, `day_max_native`, `rows`/`day_rows` or any served feature.
- The served `ecmwf_aifs025` key still reads the old id. Everything derived from
  it is unchanged: `day_max_native`, the aifs delta, and the ifs/aifs
  disagreement.
- `gfs_graphcast025` is no longer requested and is listed in
  `retired_model_members`. The parser still reads its column whenever a response
  has one, so served output from any captured response is unchanged.
- The parser contract is bumped to `open-meteo-global-models-parser-v2`. The only
  reason is the payload schema change: the new keys `capture_only_models` and
  `retired_model_members`. Served semantics did not change.
- `src/weather/sources/open_meteo_archives.py` is untouched; the interim cache
  rule covers it.
- Serving AIFS to the model is a separate, untested lever and is not part of this
  branch.

## Parity proof

- `tests/model/test_open_meteo_global_models_capture_only.py` keeps a frozen copy
  of the v1 parser. It replays six provider-response shapes through both parsers
  and asserts that three things are byte-identical:
  - the served payload (every key except the two new ones);
  - `extract_live_features`;
  - `estimate_distribution`.

  A control test shows that leaking the AIFS high into `day_max_native` does move
  the distribution, so the comparison is not vacuous.
- A sampled replay of captured records was run through both parsers: 240 le0929
  records from 40 files, each fed once as the v1 response and once as the new
  request's response, for 480 comparisons. All 480 matched on the served payload
  and on the features. `payload_hash` and `raw_payload` were left out of the
  comparison because they follow the response bytes in any live run. The script
  is `C:\t\l2\aifs_replay\l2_aifs_capture_replay.py`, sha256
  `9828e20667c5df6e7710411a54382027573153ec49bc9c724dd89bd8145bd83a`.

## Landing

This is loop-imported capture code, so it is roll-sensitive. Master runs the B
guard and the roll verdict on the tip, and it lands in a quiet-window night.
