# kjlc-rga-to-influxdb

Acquire one complete KJLC RGA mass sweep at a time with `py-kjlc-rga`, then write
one InfluxDB point per sampled AMU. Select periodic acquisition, fixed padding
after scan return, or successive scans with no added pause.

## Requirements

- [`uv`](https://docs.astral.sh/uv/)

## Installation

1. Clone the repository and its submodules:

   ```bash
   cd "$HOME/Projects"
   git clone --recursive https://github.com/SinclairQuantumLab/kjlc-rga-to-influxdb.git
   cd kjlc-rga-to-influxdb
   ```

   `--recursive` includes the `py-kjlc-rga` library and `imaq-secret`
   credential submodule at their expected locations.

2. Set up the project environment:

   ```bash
   uv sync
   ```

3. Create and edit the local configuration:

   ```powershell
   Copy-Item settings.toml.template settings.toml
   ```

   On Linux, use `cp settings.toml.template settings.toml`. Edit `host`, review
   the scan settings and select the timing mode. Keep local settings out of Git.

## Usage

Prepare the instrument's filament/emission, detector, calibration and reporting
settings, and confirm that no other scan is running. The relay configures scan
channels and starts acquisition; it does not enable emission or force control.

1. Inspect one scan before enabling upload:

   ```powershell
   uv run python main.py --once --dry-run
   ```

   `--dry-run` **operates the RGA** and prints every proposed mass point, but
   does not open credentials or upload. Check the device serial, mass range,
   reporting units/type and values.

2. Upload one scan, then start the selected repeating mode:

   ```powershell
   uv run python main.py --once
   uv run python main.py
   ```

   Run from the project root. `--settings path/to/file.toml` selects another
   configuration; credentials remain relative to the project root.

The relay has been tested offline. Complete acquisition, real InfluxDB upload,
and unattended service operation still need hardware acceptance.

## Scan configuration and timing

```toml
host = "<HOST>"
# port = 80
timeout_s = 10

# Uncomment exactly one mode block.
# scan_mode = "continuous"

scan_mode = "periodic"
interval_s = 60

# scan_mode = "fixed_padding"
# padding_s = 5

# value_field = "Pressure[Torr]" # Optional override; normally leave commented.

[scan]
start_mass = 1
stop_mass = 200
ppamu = 5 # Points per amu; mass spacing = 1 / ppamu.
dwell_ms = 32 # Milliseconds spent measuring each mass point.
```

Channel 1 records the raw device timestamp, channel 3 records the Sweep, and
channel 2 is disabled. Sweep endpoints are inclusive: `(200 - 1) * 5 + 1 = 996`
mass points. Endpoints must lie on the selected mass grid. The library checks
the device's supported `ppamu` values and verifies actual configuration readback.
There is no automatic half-AMU margin: this example returns masses
`1.0, 1.2, ..., 199.8, 200.0`. To cover the sides of the endpoint peaks, request
a wider range explicitly within the instrument's mass limits. At `ppamu=5`,
shift boundaries by multiples of 0.2 AMU to keep integer mass points on the grid;
a 0.5 AMU shift would miss them. At `ppamu=10`, a half-AMU shift preserves them.

`dwell_ms` is the measurement time at each mass point, not the pause between
scans. A value of 32 requests 32 ms per point; increasing it lengthens the scan.
An existing nonzero device `dwellGlobal` overrides per-channel dwell. Reporting,
calibration and detector settings are retained. See the library's captured
[scan setup API reference](py-kjlc-rga/device-docs/api-guide/text/scanSetup.txt)
for the device definitions.

All modes begin immediately and wait for the **actual complete scan** before
uploading or starting another scan. The library uses the device's first-scan
estimate to schedule result polling, then continues polling if the result is
not ready. A short relay period never truncates a scan. `timeout_s` bounds each
HTTP request, not the full acquisition; there is no total scan-wait deadline.

Let `S` be the start of the acquisition call, `R` its return, and `U` completion
of mapping/upload (including logging). These are host-side boundaries, not
precise physical scan-start timestamps:

| Mode | Next acquisition call | Behavior |
| --- | --- | --- |
| `periodic` | `max(S + interval_s, U)` | Wait only for the remaining period. If the cycle exceeds it, warn and begin immediately. |
| `fixed_padding` | `max(R + padding_s, U)` | Leave at least this much time after scan return. Mapping/upload consumes part or all of the padding. |
| `continuous` | `U` | Begin the next scan with no added pause. |

Each periodic cycle is anchored to its own actual start: an overrun does not
create a catch-up queue. For a 40 s acquisition and 2 s upload: a 60 s period
leaves 18 s of sleep; a 30 s period warns and leaves none; a 5 s padding leaves
3 s of sleep. `interval_s` must be positive; `padding_s` can be zero. Settings
for inactive timing modes are ignored.

`continuous` here means repeated finite `measure(scan_count=1)` calls. Setup,
HTTP and synchronous upload still take time between scans. It is not the
device's indefinite `scan_count=-1` mode, which continues acquiring during
upload and currently grows the library's in-memory record without a bound.

`--once` acquires/uploads one scan in any mode and exits without a final pause.
Ctrl+C (SIGINT) and SIGTERM use Python's `signal.default_int_handler`. The first
signal interrupts acquisition, upload, or sleep through `KeyboardInterrupt`,
then runs `finally` cleanup and exits 130. An incomplete scan is not uploaded.
An interrupted upload may already have reached InfluxDB; shutdown does not retry it.
Normal cleanup stops only this client's unfinished run while still in control
and releases control. It does not change filament/emission settings.

## Data written to InfluxDB

The fixed measurement is **`kjlc-rga`**. Each complete spectrum is submitted as
one synchronous batch containing one point per AMU. Every point in that batch
uses the same host UTC nanosecond timestamp, captured just after acquisition
returns and before upload. It marks receipt of the complete spectrum, not the
individual dwell times. If the host clock stalls or moves backward within one
process, the relay warns and uses the previous timestamp plus 1 ns to avoid
overwriting a previous scan. This safeguard does not persist across restarts.

| Tag | Meaning |
| --- | --- |
| `source` | `KJLC RGA` |
| `Serial number` | `/mmsp/electronicsInfo/serialNumber` read at startup |
| `channel` | Actual Sweep channel ID, currently `3` |
| `amu` | Canonical mass string, e.g. `18`, `18.2`, `18.25` |
| `report_units` | Actual channel `reportUnits` readback |
| `report_type` | Actual channel `reportType` readback |

| Field | Type | Meaning |
| --- | --- | --- |
| `Pressure[Torr]` | float | Default spectrum field; requires absolute Torr readback |
| `device_timestamp_raw` | integer | Channel 1's raw unsigned 32-bit reading, preserved without an assumed epoch or conversion |

**AMU is a tag because it identifies a repeated mass bin.** InfluxDB identifies
points by measurement, tag set and timestamp. With AMU only as a field, equal-time
points for different masses would overwrite each other's values. Fixed mass tags
also make a selected mass's time trace easy to filter. This follows InfluxDB's
[tag/query guidance](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/schema-design/)
and [point identity rules](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/duplicate-points/).

The default grid creates 996 mass tag combinations per device/channel/reporting
combination, reused across scans. Changing grids increases the union of sampled
masses; scan numbers and timestamps are never tags. The default writes 996 points
per scan, about 1.43 million points/day at 60 s intervals.
Retention and downsampling should reflect the desired spectrum history.

The field name defaults to **`Pressure[Torr]`**. Normally leave this optional
top-level setting commented out (before `[scan]`):

```toml
# value_field = "Pressure[Torr]"
```

The default requires actual `reportUnits="Torr"` and `reportType="Absolute"`
readback (case-insensitive); otherwise the relay exits without uploading the
scan. The library's existing device evidence says `Current`, so the pressure
reporting path still needs verification on the instrument. An unknown `Pressure`
label alone is not proof of Torr units. No pressure-reporting API writes or
current-to-pressure conversion are guessed by this application.

To deliberately store another reported quantity, uncomment and rename the field,
for example `value_field = "Signal"` for unconverted current readings. The
`report_units` and `report_type` tags remain mandatory and preserve actual
readback. This option changes only the InfluxDB field name, not acquisition,
calibration or units; the deployer is responsible for a custom name's meaning.
Field names cannot collide with the raw timestamp, tags or reserved names.

Pressure/current values and the JSON nonfinite
sentinel `-9.999999e-31` are preserved as returned (float32 precision); the
sentinel is not a physical negative pressure and is not converted to zero.
No baseline subtraction, peak integration, normalization or pressure conversion
is performed. The points are not a full instrument-configuration archive.

For an InfluxDB 2/Flux time trace of mass 18, filter the device and reporting
combination explicitly:

```flux
from(bucket: "<BUCKET>")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "kjlc-rga" and r._field == "Pressure[Torr]")
  |> filter(fn: (r) => r["Serial number"] == "<SERIAL>" and r.channel == "3")
  |> filter(fn: (r) => r.report_units == "Torr" and r.report_type == "Absolute")
  |> filter(fn: (r) => r.amu == "18")
```

For a spectrum, select **one exact `_time`** and remove the `amu == "18"`
filter. Use `map(fn: (r) => ({r with mass_amu: float(v: r.amu)}))`, then group
the mass series together and sort numerically by `mass_amu`. Selecting one exact
scan timestamp avoids assembling a spectrum from multiple scans with changing
mass grids. Do not sort mass strings lexicographically.

## Failures and deployment

Acquisition, control loss, malformed results or changed settings cause a nonzero
exit after cleanup. The relay does not retry scan starts or cursor-advancing
result requests: a lost HTTP response does not prove the operation did not run.
Reconcile any active instrument run before restarting.

Upload failures count cumulatively; the third exits nonzero, and a successful
upload does not reset the counter. `--once` exits on its first failure. Failed
uploads are logged and **not queued for replay**. A server may have accepted
some or all points before a write error; batch upload is not a transactional or
durable-spooling guarantee. No local measurement archive is created.

`Startup.ps1` and `Startup.sh` run the prepared `.venv` interpreter from the
project root. Run `uv sync` before using them; they do not update dependencies
during service restarts. After successful foreground validation, adapt
`supervisor/kjlc-rga-to-influxdb.windows.conf` or
`supervisor/kjlc-rga-to-influxdb.linux.conf` for your existing Supervisor service.
The templates have `autostart=false`; no service is installed or started by setup.
The templates retain a 3,600 s shutdown deadline. The relay now interrupts on
the first signal rather than waiting for scan completion; size `stopwaitsecs`
for blocking I/O and cleanup in your deployment. A forced process kill cannot
guarantee device stop. Actual Windows service signal delivery needs separate
validation; registering SIGTERM does not make a forced Windows kill catchable.

## Troubleshooting

- Existing checkout missing submodules: run `git submodule update --init --recursive`
  from the project root, then `uv sync`.
- Missing `kjlc_rga`: initialize `py-kjlc-rga` and run `uv sync` from this root.
  The import is `kjlc_rga`, not `py_kjlc_rga`.
- Missing credentials: initialize `imaq-secret` using an account with lab access.
  Acquisition-only `--dry-run` works without it.
- Control refused/already scanning: finish the existing instrument run first.
  The relay does not automatically take control from another user.
- Frequent overrun warnings: increase `interval_s`, reduce acquisition cost, or
  choose `continuous` if no target period is needed. Do not shorten an HTTP
  timeout to enforce a scan period.
- A scan takes longer than its estimate: polling continues until a real result
  or a source error. Ctrl+C interrupts the scan and attempts cleanup.
- Default field rejected: configure and verify absolute Torr reporting, or set
  an explicit custom `value_field` for unconverted data. Changing a field label
  does not convert a current. The default check also applies to dry-run.

## Developer's note

`main.py` is a direct script adapted from the user's SAES SIP relay scaffold.
The complete source survey, deliberate differences and validation scope are in
[docs/provenance.md](docs/provenance.md). Library source edits are immediately
visible through the editable workspace; restart a running process to load them.
Commit library changes in its repository before updating the parent's gitlink.

Offline checks (no hardware or real InfluxDB):

```powershell
uv run python -W error -m unittest discover -s tests -v
uv run python -W error -m unittest discover -s py-kjlc-rga/.agents/tests -v
uv run ruff check .
git diff --check
```
