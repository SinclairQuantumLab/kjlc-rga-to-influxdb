# Implementation provenance and validation

## Baseline and survey

Assessed on 2026-09-16. The target was an unborn `main` branch with staged user
scaffolding, an empty README and an unfinished SAES-to-RGA adaptation. There was
no runnable/deployed RGA schema or relay test suite to preserve. Existing staged
work was retained; this task does not publish or create the initial commit.

The skill preflight reported `current-dirty` on
`Sinclair-Agent-Skills/feature/to-influxdb-development` (ahead/behind 0/0).
The skill source was not changed. GitHub organization inventory was refreshed;
all 14 accessible relay repositories were surveyed on their default branches.
Breadth inspection covered trees, main.py, README, applicable AGENTS.md, project
metadata, settings templates, startup/Supervisor files and recent commit history.
No credential repository/submodule contents were opened. Repository metadata
and the imaq-secret branch tip were sufficient for the credential gitlink.

| Repository | Branch | Surveyed HEAD | Relevance |
| --- | --- | --- | --- |
| [seas-neg-power-to-influxdb](https://github.com/SinclairQuantumLab/seas-neg-power-to-influxdb) | `main` | `513fffa8ab66` | Cross-check: synchronous device relay, bounded failure accounting and source-specific recovery. |
| [seas-sip-power-to-influxdb](https://github.com/SinclairQuantumLab/seas-sip-power-to-influxdb) | `main` | `a8e35bd30a04` | Primary: copied scaffold, trusted TOML, synchronous batch writes, CLI, logging and cleanup. |
| [iqair-to-influxdb](https://github.com/SinclairQuantumLab/iqair-to-influxdb) | `main` | `e6d85bc50c73` | Counterexample: asynchronous BLE collector/classes, configurable measurement and reconnect delay. |
| [siglent-spd3000-to-influxdb](https://github.com/SinclairQuantumLab/siglent-spd3000-to-influxdb) | `main` | `5c478e1f1591` | Primary: independent source-library boundary and prepared-environment startup/Supervisor files. |
| [dataq-to-influxdb](https://github.com/SinclairQuantumLab/dataq-to-influxdb) | `main` | `8d9be795e888` | Counterexample: Socket.IO callback streaming and delegated reconnect timing; settings added after the skill snapshot. |
| [hicube-neo-to-influxdb](https://github.com/SinclairQuantumLab/hicube-neo-to-influxdb) | `main` | `25741296ea2b` | Cross-check: complete batch/readback validity and monotonic scheduling; recent local-logging flags are not adopted. |
| [arroyo-to-influxdb](https://github.com/SinclairQuantumLab/arroyo-to-influxdb) | `main` | `6b8dbd57094a` | Cross-check: direct script, library submodule, per-channel mapping and deployment; its unconditional auth bootstrap differs from this target. |
| [koheron_ctl-to-influxdb](https://github.com/SinclairQuantumLab/koheron_ctl-to-influxdb) | `main` | `e8e51435c67f` | Counterexample: parallel multi-device serial reads and expected busy-device skips. |
| [multivisor-to-influxdb](https://github.com/SinclairQuantumLab/multivisor-to-influxdb) | `main` | `cd8d3d8219a9` | HTTP process-state snapshots with session reauthentication and a fixed post-cycle sleep. |
| [LFI3751-to-influxdb](https://github.com/SinclairQuantumLab/LFI3751-to-influxdb) | `master` | `6385a8193bcb` | Older serial snapshot/reconnect loop with a fixed post-cycle sleep. |
| [ULE-Ion-pump-to-influxdb](https://github.com/SinclairQuantumLab/ULE-Ion-pump-to-influxdb) | `main` | `071923275c76` | Older Telnet pressure relay with explicit units and reconnect-on-read failure. |
| [nut-to-influxdb](https://github.com/SinclairQuantumLab/nut-to-influxdb) | `main` | `8794e306f3be` | TCP UPS snapshot, auth boundary, device identity and detailed operator README. |
| [sensorpush-to-influxdb](https://github.com/SinclairQuantumLab/sensorpush-to-influxdb) | `main` | `bc2df19f25e0` | History/cursor/backfill source; its idempotency and rate limits differ from active RGA acquisition. |
| [pico-tc08-to-influxdb](https://github.com/SinclairQuantumLab/pico-tc08-to-influxdb) | `main` | `63c249f69411` | Fork; device logger with configurable measurement/period and optional local logging/upload. |

No included relay is archived or empty. Pico is the only included fork.
The older `seas-pump-to-influxdb` corpus entry is now `seas-sip-power-to-influxdb`;
NEG, Siglent and Arroyo are additions to the dated skill map. The SIP schema
inconsistency in that map was resolved by `02a3d48d32`; it is not a current gap.
Supervisor infrastructure (including archived supervisor-setting), Grafana
hosting, instrument libraries, Labscript/Jupyter, optical/CAD and other
non-relay projects were excluded by purpose after the full organization listing.
No inaccessible relay was reported by the authenticated organization inventory;
unknown repositories outside that account’s visibility cannot be ruled out.
The Pico Windows shortcut is a binary artifact and was excluded from text reads.

## Decisions and source evidence

| Choice | Evidence | Adaptation |
| --- | --- | --- |
| Direct script, CLI and auth/write blocks | Target staged/worktree main.py; SIP `main` at `a8e35bd30a04`, main.py | Preserve `--settings`, `--once`, `--dry-run`, trusted TOML, conditional credentials, synchronous write, fixed measurement and local logging helpers. Move client startup inside cleanup scope. |
| Three scan schedules | Explicit user request; SIP/HiCube/Siglent main.py scheduling as counterexamples | Deliberately replace the reference overrun delay with immediate next acquisition and warning. Fixed padding is measured from return, including elapsed upload time. Use monotonic time. |
| One finite run per iteration | py-kjlc-rga `main` at `d07b176a9da0`, `_client.py:measure/start/wait`, docs/usage.md | Use public measure with one scan, capacity 1 and no collection deadline. Device-estimate polling/keepalive remains library-owned; finite records bound process memory. |
| No source retry or forced control | Library `_client.py`, docs/usage.md and docs/open-questions.md | An active scan start or nextScan cursor read can already have taken effect when the reply is lost. Fail and close instead of copying idempotent snapshot retries. Default library control refusal is retained. |
| Mass-axis schema | Library `_models.py:SweepMode.mass_axis`, captured scanSetup guide; InfluxDB official schema/duplicate-point docs linked in README | One point per canonical AMU tag, same receipt timestamp per spectrum. No scan UUID/tag or dynamic field name. |
| Raw units and time | Library readback metadata and recorded API responses; `_models.py:TimestampMode`; docs/open-questions.md | Preserve value and raw timestamp, tag the actual reportUnits/reportType. Do not invent pressure conversion or a raw-device timestamp epoch. |
| Default spectrum field and override | Explicit user follow-up on 2026-09-16 | Default to Pressure[Torr]; keep value_field commented in settings. Require absolute Torr readback for that name. An explicit custom field stores unconverted readings. Existing device evidence is Current; Torr decoding acceptance is synthetic offline evidence, not a hardware claim. |
| Upload recovery | Target/SIP main.py cumulative exception counter | Keep threshold 3 for uploads and immediate failure for --once. No local replay queue; failed scans are explicitly logged. Acquisition errors are fatal separately. |
| Startup and service templates | Siglent `main` at `5c478e1f1591`, Startup.ps1/Startup.sh and supervisor configs | Copy prepared-interpreter pattern, rename project paths, keep autostart=false; add a documented 3600 s graceful-stop allowance for long scans. |
| Package setup | Existing target pyproject.toml and library README/AGENTS.md | Retain Python 3.14 and editable uv workspace. Add Ruff for relay lint only; standard-library unittest executes the real script with simulated boundaries. |

Library files were not changed. Its moved Git worktree still pointed at the old
`py_kjlc_rga` folder; only `.git/modules/py-kjlc-rga/config` core.worktree was
repaired to `../../../py-kjlc-rga`. The parent now stages the library gitlink
at `d07b176a9da082e5d7483a2749d6df973bad7f6f`. The credential gitlink is pinned
at `e61093fc08e3e3b552905ee0f69a20fabe5b5786` and remains uninitialized.
Existing local host, interval and HTTP timeout values were preserved when adding
mode and scan settings. Local settings are ignored. No sibling library checkout
at the path in the original message was present; the nested checkout is used.

## Validation

- Baseline library: 131 offline tests passed with warnings treated as errors.
- Relay: 26 offline tests passed, executing main.py through runpy with real
  RGARecord/RGAChannel/SweepMode objects and simulated acquisition/write clocks.
  Coverage includes period remainder/overrun/re-anchoring/exact-boundary timing,
  upload latency, padding, continuous mode, once, schema/line-protocol identity,
  raw timestamp range, clock rollback, JSON sentinel, invalid spectra, source
  no-retry, cumulative upload failures, credential-free dry-run, signals and cleanup.
  Field tests cover the pressure default, refusal of current/unknown/relative units,
  explicit custom-field storage, and schema name collisions.
- `uv sync`, import from the editable checkout and `main.py --help` succeeded.
- `uv run ruff check .` passed. Git whitespace, PowerShell/Bash syntax and
  Supervisor configuration parsing were also checked offline.

Current-task hardware evidence: none. No instrument connection/control/scan,
credential read, InfluxDB upload or Supervisor activation was performed.
Historical library evidence is limited to the captured/reference material and
previous authorized read-only inspection described in its docs/open-questions.md;
it is not successful end-to-end relay acceptance.

Remaining qualification: a prepared instrument test window; confirm complete
finite acquisitions/timing/control release, chosen reporting/calibration, actual
InfluxDB schema/write behavior, and service shutdown allowance. Hardware
indefinite streaming, calibrated pressure conversion, durable replay and full
configuration archiving are not implemented by this relay.


## Signal shutdown follow-up (2026-09-16)

The user selected standard interrupt semantics: SIGINT and SIGTERM are both
registered with `signal.default_int_handler`, raise `KeyboardInterrupt`, and
reach `finally` cleanup with exit code 130. The first signal interrupts current
work; the previous finish-first/second-signal policy and signal-handler Event
were removed. Normal mode scheduling and complete-spectrum mapping are unchanged.
The 26 offline tests now include interruption during scan, upload, and sleep.
See [the local Projects audit](signal-audit.md) for sibling changes, validation,
publication status, and the real worker-thread Events intentionally retained.
