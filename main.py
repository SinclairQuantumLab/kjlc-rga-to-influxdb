"""Acquire complete KJLC RGA sweeps and relay mass-resolved values to InfluxDB."""

from __future__ import annotations

import argparse
import math
import signal
import time
import tomllib
from pathlib import Path

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from kjlc_rga import ChannelSettings, RGAClient, RGAError, SweepMode, TimestampMode

from supervisor.supervisor_helper import log, log_error, log_warn

print()
print("----- KJLC RGA -> InfluxDB uploader -----")
print()


# >>>>> app configuration >>>>>

MEASUREMENT = "kjlc-rga"
EX_THRESHOLD = 3

# >>> load & parse config files >>>
PARSER = argparse.ArgumentParser(description="Relay KJLC RGA scans to InfluxDB")
PARSER.add_argument("--settings", type=Path, default=Path("settings.toml"))
PARSER.add_argument("--once", action="store_true", help="Acquire one complete scan and exit")
PARSER.add_argument("--dry-run", action="store_true", help="Operate the RGA but do not upload")
ARGS = PARSER.parse_args()

SETTINGS_PATH = ARGS.settings.expanduser().resolve()
with SETTINGS_PATH.open("rb") as f:
    SETTINGS = tomllib.load(f)

SCAN_MODE = SETTINGS["scan_mode"]
VALUE_FIELD = SETTINGS.get("value_field", "Pressure[Torr]")
if not isinstance(VALUE_FIELD, str) or not VALUE_FIELD.strip():
    raise ValueError("value_field must be a nonempty string")
if VALUE_FIELD in {
    "ScanElapsedTime[ms]", "source", "Serial number", "channel", "amu",
    "time", "_field", "_measurement", "_time",
}:
    raise ValueError("value_field conflicts with a timestamp, tag, or reserved name")
if SCAN_MODE not in ("periodic", "fixed_padding", "continuous"):
    raise ValueError("scan_mode must be periodic, fixed_padding, or continuous")

INTERVAL_s = SETTINGS["interval_s"] if SCAN_MODE == "periodic" else 0
PADDING_s = SETTINGS["padding_s"] if SCAN_MODE == "fixed_padding" else 0
for NAME, VALUE in (("interval_s", INTERVAL_s), ("padding_s", PADDING_s)):
    if isinstance(VALUE, bool) or not math.isfinite(VALUE) or VALUE < 0:
        raise ValueError(f"{NAME} must be finite and nonnegative")
if SCAN_MODE == "periodic" and INTERVAL_s == 0:
    raise ValueError("interval_s must be positive; use continuous for no pause")

CHANNELS = {
    1: ChannelSettings(TimestampMode()),
    3: ChannelSettings(SweepMode(
        start_mass=SETTINGS["start_mass"],
        stop_mass=SETTINGS["stop_mass"],
        ppamu=SETTINGS["ppamu"],
        pts_per_chan=round((SETTINGS["stop_mass"] - SETTINGS["start_mass"]) * SETTINGS["ppamu"]) + 1,
        dwell=SETTINGS["dwell_ms"],
    )),
}
# <<< load & parse config files <<<

print(f"Scan mode = {SCAN_MODE}; interval = {INTERVAL_s} s; padding = {PADDING_s} s.")
print(f"KJLC RGA = {SETTINGS['host']}.")
print(f"Settings file = {SETTINGS_PATH}.")
print(f"InfluxDB upload = {'disabled (dry-run)' if ARGS.dry_run else 'enabled'}.")
print(f"Spectrum value field = {VALUE_FIELD}.")
print()

# <<<<< app configuration <<<<<


# >>> load IMAQ secret >>>
if not ARGS.dry_run:
    with open("imaq-secret/auth.toml", "rb") as f:
        AUTH = tomllib.load(f)
# <<< load IMAQ secret <<<


# Use Python's normal Ctrl+C exception path for both termination signals.
for SIGNAL_NUMBER in (signal.SIGINT, signal.SIGTERM):
    signal.signal(SIGNAL_NUMBER, signal.default_int_handler)

INFLUXDB_CLIENT = None
INFLUXDB_WRITE_API = None
INFLUXDB_ORG = None
INFLUXDB_BUCKET = None
RGA = None
exit_code = 0

try:
    # >>> InfluxDB configuration >>>
    if not ARGS.dry_run:
        INFLUXDB_CLIENT = influxdb_client.InfluxDBClient(**AUTH["influxdb"])
        INFLUXDB_WRITE_API = INFLUXDB_CLIENT.write_api(write_options=SYNCHRONOUS)
        INFLUXDB_ORG = AUTH["influxdb"]["org"]
        INFLUXDB_BUCKET = AUTH["influxdb"]["bucket"]
        print(
            f"InfluxDB client initialized for org='{INFLUXDB_ORG}', "
            f"bucket='{INFLUXDB_BUCKET}'."
        )
        print()
    # <<< InfluxDB configuration <<<

    # >>> KJLC RGA connection >>>
    RGA = RGAClient(
        SETTINGS["host"], port=SETTINGS.get("port"), timeout=SETTINGS["timeout_s"]
    )
    # Force control once at startup, following the library demo.
    # Later measurements use ordinary requests: another user's takeover must
    # produce an acquisition error instead of triggering a forced takeover here.
    RGA.request_control(force=True)
    SERIAL_NUMBER = RGA.get("/mmsp/electronicsInfo/serialNumber")
    if not isinstance(SERIAL_NUMBER, str) or not SERIAL_NUMBER.strip():
        raise ValueError("The RGA did not report a nonempty electronics serial number")
    # <<< KJLC RGA connection <<<

    # Acquisition and upload failures share this counter; success does not reset it.
    lifetime_exception_count = 0
    iteration = 1
    last_timestamp_ns = 0
    print("Entering scan loop...")
    print()

    while True:
        msg_il = f"Iteration {iteration}: "
        cycle_started = time.monotonic()

        # A scan is an active acquisition, not an idempotent snapshot query.
        # Do not reconnect or retry a failed source call within this cycle.
        # The library waits for actual completion, using device timing estimates.
        # interval_s is never passed as a scan timeout.
        try:
            record = RGA.measure(CHANNELS, scan_count=1, capacity=1, timeout=None)
        except RGAError as ex:
            scan_returned = time.monotonic()
            if ARGS.once:
                raise
            lifetime_exception_count += 1
            log_error(
                f"{msg_il}Acquisition failed ({lifetime_exception_count}/{EX_THRESHOLD} lifetime): "
                f"{type(ex).__name__}: {ex}."
            )
            if lifetime_exception_count >= EX_THRESHOLD:
                log_error("Exception threshold reached. Raising to supervisor.")
                raise
        else:
            scan_returned = time.monotonic()
            observed_ns = time.time_ns()
            if observed_ns <= last_timestamp_ns:
                log_warn(msg_il + "Host clock did not advance; advancing the scan timestamp by 1 ns.")
                observed_ns = last_timestamp_ns + 1
            last_timestamp_ns = observed_ns

            if record.state != "complete" or len(record) != 1:
                raise ValueError("Expected exactly one complete scan; no partial spectrum uploaded")
            sweep = record.channels[3]
            if not isinstance(sweep.mode, SweepMode):
                raise ValueError("Channel 3 did not return a Sweep")
            masses = sweep.mode.mass_axis()
            values = sweep.values[0]
            if len(values) != len(masses) or not all(math.isfinite(float(v)) for v in values):
                raise ValueError("Invalid spectrum; no partial spectrum uploaded")

            # Use the actual readback. Sweep values may be Current, not pressure.
            report_units = sweep.metadata["reportUnits"]
            report_type = sweep.metadata["reportType"]
            if not isinstance(report_units, str) or not report_units:
                raise ValueError("Missing reportUnits in channel readback")
            if not isinstance(report_type, str) or not report_type:
                raise ValueError("Missing reportType in channel readback")
            if VALUE_FIELD == "Pressure[Torr]" and (
                report_units.casefold() != "torr" or report_type.casefold() != "absolute"
            ):
                raise ValueError(
                    "Pressure[Torr] requires reportUnits=Torr and reportType=Absolute; "
                    f"got {report_units!r}/{report_type!r}. Raw current requires a verified "
                    "library calibration before pressure upload. An explicit value_field "
                    "can label unconverted readings; renaming does not convert units."
                )
            timestamp = record.channels[1]
            if not isinstance(timestamp.mode, TimestampMode) or timestamp.metadata.get("startMassRaw") != 1:
                raise ValueError("ScanElapsedTime[ms] requires the Timestamp schedule timer (startMassRaw=1)")
            scan_elapsed_ms = int(timestamp.values[0])
            influxdb_records = []
            for mass, value in zip(masses, values, strict=True):
                # Live device grids are exact hundredths of an AMU. Formatting avoids
                # float artifacts creating extra series (e.g. 18.200000000000003).
                amu = f"{float(mass):.2f}".rstrip("0").rstrip(".")
                influxdb_records.append({
                    "measurement": MEASUREMENT,
                    "tags": {
                        "source": "KJLC RGA",
                        "Serial number": SERIAL_NUMBER,
                        "channel": "3",
                        "amu": amu,
                    },
                    "fields": {
                        VALUE_FIELD: float(value),
                        "ScanElapsedTime[ms]": scan_elapsed_ms,
                    },
                    "time": observed_ns,
                })

            if ARGS.dry_run:
                log(
                    msg_il + f"Dry-run records, not uploaded; "
                    f"report_units={report_units}, report_type={report_type}: {influxdb_records!r}"
                )
            else:
                try:
                    INFLUXDB_WRITE_API.write(
                        bucket=INFLUXDB_BUCKET,
                        org=INFLUXDB_ORG,
                        record=influxdb_records,
                        write_precision=influxdb_client.WritePrecision.NS,
                    )
                    log(
                        f"{msg_il}Uploaded {len(influxdb_records)} mass points; "
                        f"report_units={report_units}, report_type={report_type}, "
                        f"acquisition={scan_returned - cycle_started:.3f} s."
                    )
                except Exception as ex:
                    if ARGS.once:
                        raise
                    lifetime_exception_count += 1
                    log_error(
                        f"{msg_il}Upload failed ({lifetime_exception_count}/{EX_THRESHOLD} lifetime): "
                        f"{type(ex).__name__}: {ex}. This scan is not queued for replay."
                    )
                    if lifetime_exception_count >= EX_THRESHOLD:
                        log_error("Exception threshold reached. Raising to supervisor.")
                        raise

        if ARGS.once:
            break

        now = time.monotonic()
        if SCAN_MODE == "periodic":
            remaining = cycle_started + INTERVAL_s - now
            if remaining < 0:
                log_warn(
                    f"{msg_il}Cycle took {now - cycle_started:.3f} s, exceeding "
                    f"interval_s={INTERVAL_s} by {-remaining:.3f} s; starting next scan without waiting."
                )
        elif SCAN_MODE == "fixed_padding":
            # Upload/serialization may use the padding time. Never overlap scans
            # or add a second full pause after a slow upload.
            remaining = scan_returned + PADDING_s - now
        else:
            remaining = 0
        if remaining > 0:
            time.sleep(remaining)
        iteration += 1

except KeyboardInterrupt:
    log_warn("Acquisition interrupted; closing the RGA session.")
    exit_code = 130
except Exception as ex:
    log_error(f"Fatal collector error: {type(ex).__name__}: {ex}")
    exit_code = 1
finally:
    log("Shutting down gracefully...")
    try:
        if RGA is not None:
            RGA.close()
    except Exception as ex:
        log_error(f"RGA cleanup failed: {type(ex).__name__}: {ex}")
        exit_code = exit_code or 1
    try:
        if INFLUXDB_WRITE_API is not None:
            INFLUXDB_WRITE_API.close()
    except Exception as ex:
        log_error(f"InfluxDB write API cleanup failed: {type(ex).__name__}: {ex}")
        exit_code = exit_code or 1
    try:
        if INFLUXDB_CLIENT is not None:
            INFLUXDB_CLIENT.close()
    except Exception as ex:
        log_error(f"InfluxDB client cleanup failed: {type(ex).__name__}: {ex}")
        exit_code = exit_code or 1
    log("Done")

if exit_code:
    raise SystemExit(exit_code)
