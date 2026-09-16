# kjlc-rga-to-influxdb

Use the canonical `to-influxdb-development` skill for relay work. Read README.md
and docs/provenance.md, refresh the skill source and repository corpus, and
inspect staged and unstaged work before editing. Do not copy the skill here.
Read its author-preferences reference before drafting README changes. Before
maintaining the skill, read the canonical Sinclair-Agent-Skills root AGENTS.md;
use its persistent feature/to-influxdb-development branch and publication rules.
Promote eligible reusable corrections during the task, not only at handoff.

- Keep the direct sequential main.py and public kjlc_rga API boundary. The
  library is an independent Git submodule and editable uv workspace member.
  Read its AGENTS.md before changing its code or revision. Do not duplicate
  its HTTP protocol, timing estimates, pressure conversion, or control logic.
- Preserve the three documented scheduling contracts. Use a monotonic clock
  and complete scans; a polling period is never a scan timeout.
- SIGINT/SIGTERM use signal.default_int_handler and the KeyboardInterrupt /
  finally cleanup path. The first signal interrupts current work; do not add
  a finish-first policy or threading synchronization inside signal handlers.
- Continuous means successive finite acquisitions with no added pause. Do not
  silently substitute an unbounded in-memory indefinite library record.
- A cursor read or scan start must not be automatically retried by the relay.
  Never force control or change emission/detector settings implicitly.
- Keep AMU tags canonical and one host timestamp per spectrum. Validate report
  units/type from actual channel readback and log them; do not upload them as tags.
  ScanElapsedTime[ms] stores channel 1's schedule timer unchanged as an integer;
  verify Timestamp mode and startMassRaw=1. It is not uptime or a UTC timestamp.
- Default spectrum field is Pressure[Torr], with value_field normally commented
  out in settings. Require absolute Torr readback for that name. A custom name
  changes labeling only; it must never silently perform a unit conversion.
- settings.toml and credential contents are local deployment data. Never read
  imaq-secret for repository research, log credentials, or commit local values.
- Tests execute main.py with runpy and mocked I/O, using real library models.
  Run `uv run python -W error -m unittest discover -s tests -v`,
  `uv run ruff check .`, and `git diff --check` after relevant changes.
- Startup wrappers use the prepared interpreter; do not launch acquisition or
  upload during agent verification without an explicit live-test request.
- Update README and provenance with behavior/validation changes. Keep task-only
  output under ignored tmp/. Preserve unrelated staged or untracked work.
