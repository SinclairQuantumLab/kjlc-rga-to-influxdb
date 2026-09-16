"""Execute the relay offline with real library records and a simulated clock."""

from __future__ import annotations

import builtins
import copy
import io
import re
import runpy
import signal
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from influxdb_client import Point, WritePrecision
from kjlc_rga import RGAChannel, RGAError, RGARecord, SweepMode, TimestampMode

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = '''host = "instrument.invalid"
timeout_s = 3
start_mass = 18
stop_mass = 18.4
ppamu = 5
dwell_ms = 32
scan_mode = "periodic"
interval_s = 10
padding_s = 5
'''


def make_record(
    values: tuple[float, ...] = (1e-10, 2e-10, 3e-10),
    *, units: str = "Torr", report_type: str = "Absolute", timestamp_selector: int | None = 1,
) -> RGARecord:
    """Return the public library's record type, without any device connection."""
    return RGARecord(
        {
            1: RGAChannel(
                TimestampMode(), np.array([4294967295], dtype=np.uint32),
                metadata={} if timestamp_selector is None else {"startMassRaw": timestamp_selector},
            ),
            3: RGAChannel(
                SweepMode(18, 18.4, 5, 3, 32),
                np.array([values], dtype=np.float32),
                metadata={"reportUnits": units, "reportType": report_type},
            ),
        },
        scan_numbers=np.array([1], dtype=np.uint64),
    )


class Scenario:
    """Own simulated acquisition, upload, signal, and elapsed-time boundaries."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits = []
        self.starts = []
        self.calls = []
        self.writes = []
        self.signals = {}
        self.scan_durations = [3.0, 3.0]
        self.upload_duration = 1.0
        self.record = make_record()
        self.settings = SETTINGS
        self.args = []
        self.source_error = None
        self.upload_errors = set()
        self.signal_in_scan = None
        self.signal_in_upload = None
        self.stop_in_wait = False
        self.read_auth = 0
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.exit_code = 0
        self.wall_times = []
        self.source = Mock()
        self.source.get.return_value = "TEST-RGA"
        self.source.measure.side_effect = self.measure
        self.writer = Mock()
        self.writer.write.side_effect = self.write
        self.influx = Mock()
        self.influx.write_api.return_value = self.writer

    def sleep(self, seconds: float) -> None:
        """Advance time without sleeping, or simulate interruption during padding."""
        self.waits.append(seconds)
        self.now += seconds
        if self.stop_in_wait:
            self.signals[signal.SIGTERM](signal.SIGTERM, None)

    def measure(self, channels: dict, **kwargs: object) -> RGARecord:
        """Finish each simulated scan before allowing upload or another start."""
        index = len(self.starts)
        if index >= len(self.scan_durations):
            raise AssertionError("Unexpected extra scan")
        self.starts.append(self.now)
        self.calls.append((channels, kwargs))
        self.now += self.scan_durations[index]
        if self.signal_in_scan is not None:
            self.signals[self.signal_in_scan](self.signal_in_scan, None)
        if self.source_error is not None:
            raise self.source_error
        return self.record

    def write(self, **kwargs: object) -> None:
        """Capture a full batch and account for synchronous upload time."""
        if self.signal_in_upload is not None:
            self.signals[self.signal_in_upload](self.signal_in_upload, None)
        self.writes.append(copy.deepcopy(kwargs))
        self.now += self.upload_duration
        if len(self.writes) in self.upload_errors:
            raise OSError("simulated upload failure")
        if "--once" not in self.args and len(self.starts) == len(self.scan_durations):
            # End bounded continuous tests through the real shutdown exception path.
            self.signals[signal.SIGTERM](signal.SIGTERM, None)

    def wall_time(self) -> int:
        """Return host nanoseconds independently of the scheduling clock."""
        if self.wall_times:
            return self.wall_times.pop(0)
        return 1_800_000_000_000_000_000 + int(self.now * 1e9)

    def run(self) -> Scenario:
        """Execute the production script; intercept credentials and all external I/O."""
        original_open = builtins.open

        def open_file(file: object, *args: object, **kwargs: object) -> object:
            """Provide fake auth without opening any real credential file."""
            if str(file) == "imaq-secret/auth.toml":
                self.read_auth += 1
                return io.BytesIO(
                    b'[influxdb]\nurl="http://influx.invalid"\n'
                    b'token="test-only"\norg="test-org"\nbucket="test-bucket"\n'
                )
            return original_open(file, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            settings = Path(directory) / "settings.toml"
            settings.write_text(self.settings, encoding="utf-8")
            stack.enter_context(redirect_stdout(self.stdout))
            stack.enter_context(redirect_stderr(self.stderr))
            stack.enter_context(patch("builtins.open", side_effect=open_file))
            self.source_factory = stack.enter_context(patch("kjlc_rga.RGAClient", return_value=self.source))
            self.influx_factory = stack.enter_context(patch("influxdb_client.InfluxDBClient", return_value=self.influx))
            stack.enter_context(patch("time.sleep", side_effect=self.sleep))
            stack.enter_context(patch("time.monotonic", side_effect=lambda: self.now))
            stack.enter_context(patch("time.time_ns", side_effect=self.wall_time))
            stack.enter_context(patch("signal.signal", side_effect=self.signals.__setitem__))
            stack.enter_context(patch("sys.argv", [str(ROOT / "main.py"), "--settings", str(settings), *self.args]))
            try:
                runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
            except SystemExit as exc:
                self.exit_code = exc.code
        return self


class RelayTests(unittest.TestCase):
    """Check observable scan scheduling, schema, failure, and cleanup contracts."""

    def test_periodic_subtracts_acquisition_and_upload(self) -> None:
        s = Scenario().run()
        self.assertEqual(s.exit_code, 130, s.stderr.getvalue())
        self.assertEqual(s.starts, [0, 10])
        self.assertEqual(s.waits, [6])
        self.assertEqual(s.calls[0][1], {"scan_count": 1, "capacity": 1, "timeout": None, "force": True})
        self.assertEqual(s.calls[0][0][3].mode.mass_axis().tolist(), [18, 18.2, 18.4])

    def test_overrun_finishes_scan_warns_and_starts_immediately(self) -> None:
        s = Scenario()
        s.scan_durations = [15, 3, 3]
        s.run()
        self.assertEqual(s.starts, [0, 16, 26])
        self.assertEqual(s.waits, [6])
        self.assertIn("exceeding interval_s=10 by 6.000 s", s.stderr.getvalue())

    def test_upload_can_cause_periodic_overrun(self) -> None:
        s = Scenario()
        s.upload_duration = 12
        s.run()
        self.assertEqual(s.starts, [0, 15])
        self.assertEqual(s.waits, [])
        self.assertIn("exceeding", s.stderr.getvalue())

    def test_exact_period_does_not_sleep_or_warn(self) -> None:
        s = Scenario()
        s.scan_durations = [9, 9]
        s.run()
        self.assertEqual(s.starts, [0, 10])
        self.assertEqual(s.waits, [])
        self.assertNotIn("exceeding", s.stderr.getvalue())

    def test_fixed_padding_is_measured_from_scan_return(self) -> None:
        s = Scenario()
        s.settings = SETTINGS.replace('"periodic"', '"fixed_padding"')
        s.run()
        self.assertEqual(s.starts, [0, 8])
        self.assertEqual(s.waits, [4])
        self.assertNotIn("exceeding", s.stderr.getvalue())

    def test_slow_upload_consumes_all_padding(self) -> None:
        s = Scenario()
        s.settings = SETTINGS.replace('"periodic"', '"fixed_padding"')
        s.upload_duration = 7
        s.run()
        self.assertEqual(s.starts, [0, 10])
        self.assertEqual(s.waits, [])

    def test_continuous_has_no_added_pause(self) -> None:
        s = Scenario()
        s.settings = SETTINGS.replace('"periodic"', '"continuous"')
        s.run()
        self.assertEqual(s.starts, [0, 4])
        self.assertEqual(s.waits, [])

    def test_once_never_waits_in_any_mode(self) -> None:
        for mode in ("periodic", "fixed_padding", "continuous"):
            with self.subTest(mode=mode):
                s = Scenario()
                s.settings = SETTINGS.replace('"periodic"', f'"{mode}"')
                s.args = ["--once"]
                s.run()
                self.assertEqual(s.exit_code, 0, s.stderr.getvalue())
                self.assertEqual(s.starts, [0])
                self.assertEqual(s.waits, [])

    def test_batch_has_distinct_masses_and_one_host_timestamp(self) -> None:
        s = Scenario().run()
        batch = s.writes[0]
        self.assertEqual(batch["write_precision"], WritePrecision.NS)
        records = batch["record"]
        self.assertEqual([r["tags"]["amu"] for r in records], ["18", "18.2", "18.4"])
        self.assertEqual({r["time"] for r in records}, {1_800_000_003_000_000_000})
        self.assertEqual(records[0]["tags"], {
            "source": "KJLC RGA", "Serial number": "TEST-RGA", "channel": "3",
            "amu": "18",
        })
        self.assertEqual(records[0]["measurement"], "kjlc-rga")
        self.assertIs(type(records[0]["fields"]["Pressure[Torr]"]), float)
        self.assertEqual(set(records[0]["fields"]), {"Pressure[Torr]", "ScanElapsedTime[ms]"})
        self.assertEqual(records[0]["fields"]["ScanElapsedTime[ms]"], 4294967295)
        lines = [Point.from_dict(r).to_line_protocol() for r in records]
        self.assertEqual(len({re.split(r"(?<!\\) ", line, maxsplit=1)[0] for line in lines}), 3)
        self.assertIn("ScanElapsedTime[ms]=4294967295i", lines[0])
        self.assertIn("Pressure[Torr]=", lines[0])
        self.assertGreater(s.writes[1]["record"][0]["time"], records[0]["time"])

    def test_clock_rollback_cannot_overwrite_previous_scan(self) -> None:
        s = Scenario()
        s.wall_times = [200, 100]
        s.run()
        self.assertEqual([b["record"][0]["time"] for b in s.writes], [200, 201])
        self.assertIn("Host clock did not advance", s.stderr.getvalue())

    def test_json_sentinel_is_preserved(self) -> None:
        s = Scenario()
        s.record = make_record((-9.999999e-31, 0, -1e-12))
        s.run()
        self.assertEqual(s.writes[0]["record"][0]["fields"]["Pressure[Torr]"], float(np.float32(-9.999999e-31)))

    def test_default_rejects_current_unknown_or_relative_pressure(self) -> None:
        for units, report_type in (("Current", "Absolute"), ("Pressure", "Absolute"), ("Torr", "Relative")):
            with self.subTest(units=units, report_type=report_type):
                s = Scenario()
                s.record = make_record(units=units, report_type=report_type)
                s.run()
                self.assertEqual(s.exit_code, 1)
                self.assertEqual(s.writes, [])
                self.assertIn("Pressure[Torr] requires", s.stderr.getvalue())

    def test_custom_field_preserves_value_and_logs_reporting_metadata(self) -> None:
        s = Scenario()
        s.settings = 'value_field = "Signal"\n' + SETTINGS
        s.record = make_record(units="Current")
        s.run()
        self.assertEqual(s.exit_code, 130, s.stderr.getvalue())
        point = s.writes[0]["record"][0]
        self.assertNotIn("report_units", point["tags"])
        self.assertNotIn("report_type", point["tags"])
        self.assertIn("report_units=Current, report_type=Absolute", s.stdout.getvalue())
        self.assertEqual(point["fields"]["Signal"], float(np.float32(1e-10)))
        self.assertNotIn("Pressure[Torr]", point["fields"])

    def test_elapsed_time_requires_verified_schedule_timer(self) -> None:
        for selector in (0, None):
            with self.subTest(selector=selector):
                s = Scenario()
                s.record = make_record(timestamp_selector=selector)
                s.run()
                self.assertEqual(s.exit_code, 1)
                self.assertEqual(s.writes, [])
                self.assertIn("ScanElapsedTime[ms] requires", s.stderr.getvalue())
                s.source.close.assert_called_once()

    def test_field_override_cannot_overwrite_elapsed_time_or_tags(self) -> None:
        for field in ("ScanElapsedTime[ms]", "amu", "_field", ""):
            with self.subTest(field=field):
                s = Scenario()
                s.settings = f'value_field = "{field}"\n' + SETTINGS
                with self.assertRaises(ValueError):
                    s.run()
                s.source_factory.assert_not_called()

    def test_nonfinite_spectrum_is_not_partially_uploaded(self) -> None:
        s = Scenario()
        s.record = make_record((1, float("nan"), 3))
        s.run()
        self.assertEqual(s.exit_code, 1)
        self.assertEqual(s.writes, [])
        self.assertEqual(s.starts, [0])
        s.source.close.assert_called_once()

    def test_empty_record_is_not_uploaded(self) -> None:
        s = Scenario()
        s.record = RGARecord({}, scan_numbers=np.array([], dtype=np.uint64))
        s.run()
        self.assertEqual(s.exit_code, 1)
        self.assertEqual(s.writes, [])

    def test_acquisition_failure_is_not_retried(self) -> None:
        s = Scenario()
        s.source_error = RGAError("cursor response lost")
        s.run()
        self.assertEqual(s.exit_code, 1)
        self.assertEqual(s.starts, [0])
        self.assertEqual(s.writes, [])
        s.source.close.assert_called_once()
        s.writer.close.assert_called_once()
        s.influx.close.assert_called_once()

    def test_upload_failure_count_is_lifetime_not_consecutive(self) -> None:
        s = Scenario()
        s.scan_durations = [1] * 8
        s.upload_errors = {1, 3, 5}
        s.run()
        self.assertEqual(s.exit_code, 1)
        self.assertEqual(len(s.starts), 5)
        self.assertEqual(len(s.writes), 5)
        self.assertIn("3/3 lifetime", s.stderr.getvalue())
        s.source_factory.assert_called_once()

    def test_once_upload_failure_exits_immediately(self) -> None:
        s = Scenario()
        s.args = ["--once"]
        s.upload_errors = {1}
        s.run()
        self.assertEqual(s.exit_code, 1)
        self.assertEqual(len(s.starts), 1)

    def test_dry_run_measures_but_never_opens_credentials(self) -> None:
        s = Scenario()
        s.args = ["--once", "--dry-run"]
        s.run()
        self.assertEqual(s.exit_code, 0)
        self.assertEqual(s.read_auth, 0)
        self.assertEqual(len(s.starts), 1)
        s.influx_factory.assert_not_called()
        self.assertIn("Dry-run records", s.stdout.getvalue())
        self.assertIn("report_units=Torr, report_type=Absolute", s.stdout.getvalue())
        self.assertIn("'ScanElapsedTime[ms]': 4294967295", s.stdout.getvalue())
        self.assertNotIn("'report_units':", s.stdout.getvalue())
        self.assertNotIn("'report_type':", s.stdout.getvalue())
        self.assertNotIn("device_timestamp_raw", s.stdout.getvalue())

    def test_first_signal_interrupts_scan_and_closes_resources(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                s = Scenario()
                s.signal_in_scan = signum
                s.run()
                self.assertIs(s.signals[signum], signal.default_int_handler)
                self.assertEqual(s.exit_code, 130)
                self.assertEqual(s.writes, [])
                self.assertEqual(s.waits, [])
                s.source.close.assert_called_once()
                s.writer.close.assert_called_once()
                s.influx.close.assert_called_once()

    def test_signal_during_upload_closes_without_retry(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                s = Scenario()
                s.signal_in_upload = signum
                s.run()
                self.assertEqual(s.exit_code, 130)
                self.assertEqual(s.starts, [0])
                self.assertEqual(s.waits, [])
                s.source.close.assert_called_once()
                s.writer.close.assert_called_once()
                s.influx.close.assert_called_once()

    def test_stop_during_wait_does_not_start_another_scan(self) -> None:
        s = Scenario()
        s.stop_in_wait = True
        s.run()
        self.assertEqual(s.exit_code, 130)
        self.assertEqual(s.starts, [0])

    def test_cleanup_failure_is_nonzero_and_other_clients_close(self) -> None:
        s = Scenario()
        s.args = ["--once"]
        s.source.close.side_effect = RGAError("stop failed")
        s.run()
        self.assertEqual(s.exit_code, 1)
        s.writer.close.assert_called_once()
        s.influx.close.assert_called_once()

    def test_initialization_failure_closes_already_open_influx(self) -> None:
        s = Scenario()
        s.influx.write_api.side_effect = RuntimeError("writer init failed")
        s.run()
        self.assertEqual(s.exit_code, 1)
        s.influx.close.assert_called_once()
        s.source_factory.assert_not_called()

    def test_invalid_schedule_fails_before_connecting(self) -> None:
        for old, new in (
            ('"periodic"', '"typo"'), ("interval_s = 10", "interval_s = -1"),
            ("interval_s = 10", "interval_s = 0"), ("interval_s = 10", "interval_s = nan"),
            ("interval_s = 10", "interval_s = inf"), ("interval_s = 10", "interval_s = true"),
        ):
            with self.subTest(new=new):
                s = Scenario()
                s.settings = SETTINGS.replace(old, new)
                with self.assertRaises(ValueError):
                    s.run()
                s.source_factory.assert_not_called()
                s.influx_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
