# Test Instructions

Tests mirror owner packages under `tests/app`, `backtesting`, `calibration`,
`collection`, `market`, `model`, `operations`, `reporting`, and `sources`.

- Tests must not depend on the developer's ignored `data/` tree or active
  network services. Build data layouts under `tmp_path` or use small reviewed
  files under `tests/fixtures/`.
- `pytest.ini` intentionally collects only `tests/`; scripts under `scratch/`
  may hit the network and are not tests.
- Preserve architecture ratchets. New package edges, compatibility calls, large
  facades, schema literals, or canonical-doc commands may need explicit owner
  documentation as well as tests.
- Prefer focused behavioral tests over snapshots of large generated reports.
  Assert fail-closed behavior for evidence, promotion, release, and live gates.
- If changing native-unit or model features, cover Celsius and Fahrenheit paths
  and verify training/serving parity where applicable.

Run the narrow directory or file first, then the full suite:

```powershell
.\venv\Scripts\python.exe -m pytest tests\<owner> -q
.\venv\Scripts\python.exe -m pytest -q
```

## Update this file when

Update when test layout, fixture policy, collection rules, or repository-wide
test invariants change.
