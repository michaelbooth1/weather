# LOW-ASK-1 freeze candidate

This branch owns the paper-only received-input taker process, its input contract,
synthetic witnesses and draft preregistration. It does not configure or start capture.
Read [INPUT_CONTRACT.md](INPUT_CONTRACT.md) when building the F3 export and
[PREREG_LOW_ASK_1.md](PREREG_LOW_ASK_1.md) when reviewing or binding the trial.

Stacked dependency: `origin/claude/weather-expansion-foundations-sq-20261110`
at `78d0aa66`. After T046 lands, merge `origin/master` into
`codex/low-ask-1-20261110`; do not rebase. Runtime adoption belongs to the master.

The candidate is **NOT FROZEN**. The master confirms the stated defaults and
supplies the prerequisite receipts and custodian public key before binding a
freeze. Missing prerequisites refuse accrual. No package installation is needed;
sealing uses Windows CNG. No private key is read by the process.

The separate [synthetic calibration plan](CALIBRATION_PLAN.md) uses the existing
NumPy/SciPy pins under reviewed workstation-heavy admission. It is never loaded
by the paper executable; its smoke tests do not establish size or power.

The canonical entry point is:

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.low_ask --manifest <INPUTS.json> --freeze <freeze.json> --freeze-sha <canonical-freeze-sha256> --public-key <public.json> --out <new-output-directory>
```

Pass `--previous-receipt <previous-output/receipt.json>` on subsequent snapshots.
The frozen absolute `state_root` holds a kernel-owned snapshot lock and public
`HEAD.json`; output directories must be beneath it. HEAD automatically binds
the next snapshot, so omitting the optional previous-receipt flag cannot start
a new cash history. A missing/corrupt previous seal refuses continuation.
The process replays the complete cumulative immutable manifest from the original
virtual cash balance. It seals a new snapshot, never an incremental credit to an
old ledger. A failed or interrupted snapshot consumes no simulated capital; its
output directory is retained and a new directory is required on retry. There are
no partial plaintext checkpoints. The public receipt is written only after the
sealed payload is fsynced. A successful receipt is the checkpoint.

The scheduled invocation, exact paths and public-key custody are the master's
installation work. This branch registers no task. The host must restrict input
and output directories to the pinned unattended process and custodian. Agents
inspect only public receipts and hashes. Do not open `ledger.sealed` with an
unapproved decryptor or feed trial inputs into an interactive interpreter.

The dedicated executable asserts its source import closure and installs a runtime
import boundary denying trading clients, credentials, network and process-spawn
adapters. The library functions return private economic state for synthetic tests
and the pinned process; they are not an agent-facing inspection API.

At the single final look, append `--look --family-file <family.json>` to the
same command. It refuses before the look time and consumes the fixed
`state_root/LOOK_CONSUMED` marker before opening deciding inputs. Retain a
failed look as spent. The family file is exactly `{claimants,pvalues}`:
the frozen full claimant list, and the other claimants' final one-sided
p-values. LOW-ASK-1's p-value is computed internally. A successful look writes
`final_report.json` alongside the seal; never run `--look` as a rehearsal on
real data. Synthetic tests inject clocks without moving the system clock.

Update this package, the input contract, prereg and code pins together before
binding. After freeze, no rule tuning, automatic date slide or second look.
