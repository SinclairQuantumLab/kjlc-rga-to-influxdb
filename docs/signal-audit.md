# Local Projects signal-shutdown audit

Reviewed on 2026-09-16 in `C:\Users\Joon\Projects`, at the user's request.
This is a focused audit of Python signal handling and Event usage in local
relays and instrument-control projects, not a full protocol or deployment audit.

## Changed and validated

The six synchronous relays now register `signal.default_int_handler` for both
SIGINT and SIGTERM. The first signal raises `KeyboardInterrupt` during current
work, skips ordinary retry handlers, and reaches the existing `finally` cleanup
with exit code 130. Their waits use `time.sleep` instead of `threading.Event`.
The handler does not forward an OS signal or create a thread. Normal polling
schedules, source protocols, schemas, and failure budgets are preserved.

For KJLC this explicitly replaces the previous finish-first/second-signal policy.
An incomplete scan is not uploaded. In every relay, interrupting an upload can
leave its server-side outcome unknown; shutdown does not retry the upload.

| Repository | Offline tests | Publication |
| --- | ---: | --- |
| `arroyo-to-influxdb` | 21 | Pushed `main`: [bdfce45](https://github.com/SinclairQuantumLab/arroyo-to-influxdb/commit/bdfce45a34ed7b9983657882f6a98c8785c56b5f) |
| `hicube-neo-to-influxdb` | 89 | Pushed `main`: [0a46ae9](https://github.com/SinclairQuantumLab/hicube-neo-to-influxdb/commit/0a46ae9114c2ee7f2fa6f0f4aea2a589e410e0cf) |
| `seas-neg-power-to-influxdb` | 34 | Pushed `main`: [aecaa32](https://github.com/SinclairQuantumLab/seas-neg-power-to-influxdb/commit/aecaa32967b9fb680f897f8f060cd5ae1cdcd546) |
| `seas-sip-power-to-influxdb` | 24 | Pushed `main`: [3895a74](https://github.com/SinclairQuantumLab/seas-sip-power-to-influxdb/commit/3895a74437a7db4ae3fb965677412425d54761a4) |
| `siglent-spd3000-to-influxdb` | 38 | Pushed `main`: [96b4ce9](https://github.com/SinclairQuantumLab/siglent-spd3000-to-influxdb/commit/96b4ce93727e0baca7c33c91273251336d9fd305) |
| `kjlc-rga-to-influxdb` | 26 | Included in this project's initial local commit; no remote configured |

Total: 232 passing offline tests. The five existing relay suites passed before
the change (15, 83, 28, 18, and 32 tests respectively). Each gained six cases
that invoke its registered handlers during acquisition, upload, and sleep.
They verify interruption, resource cleanup, no further cycle, and no source
retry. KJLC's existing signal tests were revised for first-signal interruption,
including both signals during acquisition and upload. Its scheduling and
serialization tests still run against real public library record types.

Checks used each repository's existing environment and test configuration:

- Sibling tests: `uv run --no-sync python -m pytest -q`.
- KJLC tests: `uv run --no-sync python -W error -m unittest discover -s tests -v`.
- Ruff passes. Arroyo preserves its documented literal-bootstrap exceptions:
  `ruff check tests supervisor` and `ruff check main.py --ignore E402,I001,E702`.
- Siglent and NEG changed test files pass Ruff formatting checks. All staged
  changes pass `git diff --cached --check`.
- A separate Python subprocess installed the standard handler and called
  `signal.raise_signal` for SIGINT and SIGTERM; both raised `KeyboardInterrupt`
  and executed `finally`. This is not a test of Supervisor signal delivery.

## Reviewed and retained

| Local project / source | Finding and reason for no change |
| --- | --- |
| `iqair-to-influxdb` | Uses `asyncio.Event` with `loop.add_signal_handler`, appropriate for its asynchronous lifecycle. Unsupported loop signal registration is skipped, so Windows service termination still requires separate qualification. |
| `py-siglent-spd3000` | Gateway CLI already maps SIGTERM (and Windows SIGBREAK) to `signal.default_int_handler` and restores previous handlers. Gateway `_PhysicalOwner` uses Event to return work results across actual worker threads. |
| `siglent-spd3000-to-influxdb/py-siglent-spd3000` | Its pinned gateway source also uses Event for real queued work. The relay change does not update the driver pin. |
| `dispenser-conditioning-plugin/mcp-server` and its driver dependency | Dependency CLI already has standard termination handling. Worker completion Events and server synchronization are not synchronous relay stop flags. Existing unrelated parent edits were left intact. |
| `cavilinq` | GUI stop Event coordinates the actual acquisition worker with the UI. Retained, including unrelated local edits. |
| `cavilinq_brandon` | GUI Event stops an acquisition thread. Retained; no unrelated files were committed. |
| `zemax-control` | Event stops the operation worker's heartbeat thread. Retained. |
| `dataq_influxdb` | Relay has no Event-based signal handler. `connection_test.py` uses Event for Socket.IO acknowledgement callbacks; retained and not run against hardware. |
| `sensorpush-to-influxdb` | SIGALRM handler is a POSIX iteration-timeout watchdog, not a threading-based shutdown handler. Retained. |
| `pico-tc08-to-influxdb` | No matching Event-based signal-shutdown code found. |
| `kjlc-rga-to-influxdb/py-kjlc-rga` | Reusable library owns data/control resources, not relay process signal policy. No matching signal/Event shutdown replacement; driver checkout and pin unchanged. |
| `arroyo-to-influxdb/pyarroyo` | No matching signal/Event shutdown replacement. Driver checkout and pin unchanged. |
| `imaq-pyopticl-test`, `pyopticl-setups`, `zemax-agent`, `codex-zemax-plugin` | No matching Python Event-based signal-shutdown code found. |
| `multivisor/git-main`, `git-develop`, `git-feature-masonry-card-layout` | RPC Events coordinate actual supervisor-status worker threads. Retained; these are process-management infrastructure. |
| `supervisor-win` and other local Supervisor workspaces | Signal forwarding/process supervision is their purpose. It must not be replaced with a relay's KeyboardInterrupt policy. No relevant Event-in-signal-handler replacement was identified in maintained code. |

`seas-neg-power-mini-to-influxdb` is a junction to `seas-neg-power-to-influxdb`,
not another checkout. `opcua-pumpingstation-to-influxdb` is an empty old folder.
`labscript-remote-device` contains a manual, not a device-control implementation.
Virtual environments, dependency caches, temporary staging/build output,
archives, and credential contents were excluded from maintained-source review.

## Publication boundaries and remaining decisions

- All five existing origins accepted normal fast-forward pushes. Their local
  `main` and `origin/main` matched after pushing. NEG and SIP first incorporated
  existing remote startup-script updates by fast-forward; those updates were
  not rewritten. No branch was force-pushed.
- HiCube already had a dirty `imaq-secret` submodule. Its contents were not read
  or staged; that unrelated local state remains outside the published commit.
- KJLC had an unborn branch and staged project scaffolding. The requested relay
  implementation, tests, documentation, and existing submodule pins belong in
  its initial local commit. Publication remains pending a remote repository
  destination and visibility; this audit does not create a GitHub repository.
- No live acquisition, instrument command, InfluxDB upload, startup-wrapper
  execution, service restart, or deployed configuration change was performed.
  Deployment-level shutdown validation requires a separate operational run.

Python runs handlers on the main interpreter thread and warns against locking
inside them. The standard exception path is appropriate for the interrupt
semantics selected here, but does not promise immediate cancellation of every
native blocking call or cleanup after a forced process kill. Windows service
signal delivery is a separate concern from installing a Python handler.
See the [Python signal documentation](https://docs.python.org/3/library/signal.html#signals-and-threads)
and its [exception caveat](https://docs.python.org/3/library/signal.html#note-on-signal-handlers-and-exceptions).
