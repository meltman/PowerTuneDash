#!/usr/bin/env python3
"""Send development-only UDP values to a local PowerTuneDash receiver."""

import argparse
import json
import socket
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 45454
MIN_INTERVAL_MS = 10
MAX_INTERVAL_MS = 60_000
MAX_SCENARIO_SIGNALS = 64
MAX_SCENARIO_VALUES = 10_000
MAX_SCENARIO_EVENTS = 100_000
MAX_SWEEP_VALUES = 10_000
MAX_VALUE_CHARS = 64

PRESETS = {
    "rpm": (179, "rpm"),
    "map": (155, "MAP"),
    "speed": (199, "speed"),
    "coolant": (221, "Watertemp"),
    "tps": (210, "TPS"),
}


def parse_identifier(value):
    try:
        identifier = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("identifier must be an integer") from exc
    if not -(2**31) <= identifier < 2**31:
        raise argparse.ArgumentTypeError("identifier must fit a signed 32-bit integer")
    return identifier


def numeric_decimal(value):
    text = str(value)
    if len(text) > MAX_VALUE_CHARS:
        raise ValueError(f"value exceeds {MAX_VALUE_CHARS} characters")
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a numeric value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"value must be finite: {value!r}")
    if abs(result.adjusted()) > MAX_VALUE_CHARS:
        raise ValueError(f"value magnitude exceeds supported range: {value!r}")
    return result


def numeric_text(value):
    numeric_decimal(value)
    return str(value)


def serialize_record(identifier, value):
    payload = f"{identifier},{numeric_text(value)}"
    try:
        return payload.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("record must be ASCII") from exc


def resolve_signal(identifier, signal):
    if signal is not None:
        try:
            return PRESETS[signal]
        except KeyError as exc:
            raise ValueError(f"unknown signal preset: {signal}") from exc
    return identifier, f"identifier {identifier}"


def sweep_values(minimum, maximum, step, bounce=False):
    low = numeric_decimal(minimum)
    high = numeric_decimal(maximum)
    increment = numeric_decimal(step)
    if increment <= 0:
        raise ValueError("step must be greater than zero")
    if low > high:
        raise ValueError("min must not be greater than max")

    values = []
    current = low
    while current <= high:
        if len(values) >= MAX_SWEEP_VALUES:
            raise ValueError(f"sweep may contain at most {MAX_SWEEP_VALUES} values")
        values.append(format(current, "f"))
        current += increment
    if numeric_decimal(values[-1]) != high:
        if len(values) >= MAX_SWEEP_VALUES:
            raise ValueError(f"sweep may contain at most {MAX_SWEEP_VALUES} values")
        values.append(format(high, "f"))
    if bounce:
        values.extend(values[-2:0:-1])
    return values


def load_scenario(path):
    try:
        with Path(path).open(encoding="utf-8") as scenario_file:
            scenario = json.load(scenario_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read scenario: {exc}") from exc

    if not isinstance(scenario, dict):
        raise ValueError("scenario must be a JSON object")
    interval_ms = scenario.get("interval_ms", 100)
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int):
        raise ValueError("scenario interval_ms must be an integer")
    validate_interval(interval_ms)

    signals = scenario.get("signals")
    if not isinstance(signals, dict) or not signals:
        raise ValueError("scenario signals must be a non-empty object")
    if len(signals) > MAX_SCENARIO_SIGNALS:
        raise ValueError(f"scenario may contain at most {MAX_SCENARIO_SIGNALS} signals")

    records = []
    total_values = 0
    for name, values in signals.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"scenario signal {name!r} must have a non-empty value list")
        total_values += len(values)
        if total_values > MAX_SCENARIO_VALUES:
            raise ValueError(f"scenario may contain at most {MAX_SCENARIO_VALUES} values")
        try:
            identifier, label = resolve_signal(None, name) if name in PRESETS else (
                parse_identifier(name),
                f"identifier {name}",
            )
        except (ValueError, argparse.ArgumentTypeError) as exc:
            raise ValueError(f"invalid scenario signal {name!r}: {exc}") from exc
        for value in values:
            try:
                numeric_text(value)
            except ValueError as exc:
                raise ValueError(f"invalid value for scenario signal {name!r}: {exc}") from exc
        records.append((identifier, label, values))
    return interval_ms, records


def load_timed_scenario(path):
    try:
        with Path(path).open(encoding="utf-8") as scenario_file:
            scenario = json.load(scenario_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read scenario: {exc}") from exc
    if not isinstance(scenario, dict) or scenario.get("format") != "powertune-udp-events-v1":
        return None

    duration_ms = scenario.get("duration_ms")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise ValueError("timed scenario duration_ms must be a positive integer")
    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("timed scenario events must be a non-empty list")
    if len(events) > MAX_SCENARIO_EVENTS:
        raise ValueError(f"timed scenario may contain at most {MAX_SCENARIO_EVENTS} events")

    parsed = []
    previous_time = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"timed scenario event {index} must be an object")
        try:
            at_ms = numeric_decimal(event["at_ms"])
            identifier = parse_identifier(str(event["identifier"]))
            value = numeric_text(event["value"])
        except (KeyError, ValueError, argparse.ArgumentTypeError) as exc:
            raise ValueError(f"invalid timed scenario event {index}: {exc}") from exc
        if at_ms < 0 or at_ms > duration_ms:
            raise ValueError(f"timed scenario event {index} is outside duration_ms")
        if previous_time is not None and at_ms < previous_time:
            raise ValueError("timed scenario events must be ordered by at_ms")
        previous_time = at_ms
        parsed.append((at_ms, identifier, value))
    return duration_ms, parsed


def send_timed_events(sock, duration_ms, events, clock=time.monotonic, sleep=time.sleep):
    started = clock()
    for at_ms, identifier, value in events:
        target = started + float(at_ms / 1000)
        delay = target - clock()
        if delay > 0:
            sleep(delay)
        announce_and_send(sock, identifier, value, f"identifier {identifier}")
    remaining = started + duration_ms / 1000 - clock()
    if remaining > 0:
        sleep(remaining)


def validate_interval(interval_ms):
    if not MIN_INTERVAL_MS <= interval_ms <= MAX_INTERVAL_MS:
        raise ValueError(
            f"interval must be between {MIN_INTERVAL_MS} and {MAX_INTERVAL_MS} ms"
        )


def announce_and_send(sock, identifier, value, label):
    payload = serialize_record(identifier, value)
    print(
        f"TX {label} -> {DEFAULT_HOST}:{DEFAULT_PORT} "
        f"{payload.decode('ascii')}",
        flush=True,
    )
    sock.sendto(payload, (DEFAULT_HOST, DEFAULT_PORT))


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Send development UDP records to PowerTuneDash on localhost "
            "(127.0.0.1:45454)."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--id", dest="identifier", type=parse_identifier)
    source.add_argument("--signal", choices=sorted(PRESETS))
    parser.add_argument("--value", help="send one value")
    parser.add_argument("--min", dest="minimum", help="sweep lower endpoint")
    parser.add_argument("--max", dest="maximum", help="sweep upper endpoint")
    parser.add_argument("--step", help="positive sweep increment")
    parser.add_argument(
        "--interval-ms", type=int, default=100,
        help=f"minimum interval between datagrams (default: 100; range: "
             f"{MIN_INTERVAL_MS}-{MAX_INTERVAL_MS})",
    )
    parser.add_argument(
        "--bounce", action="store_true",
        help="repeat a sweep continuously, reversing at each endpoint",
    )
    parser.add_argument("--scenario", help="play a JSON scenario once")
    return parser


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_interval(args.interval_ms)
    except ValueError as exc:
        parser.error(str(exc))

    if args.scenario:
        if any((args.identifier is not None, args.signal, args.value is not None,
                args.minimum is not None, args.maximum is not None,
                args.step is not None, args.bounce)):
            parser.error("--scenario cannot be combined with signal, value, or sweep options")
        return args

    if args.identifier is None and args.signal is None:
        parser.error("specify --id or --signal, or use --scenario")
    if args.value is not None:
        if any(v is not None for v in (args.minimum, args.maximum, args.step)) or args.bounce:
            parser.error("--value cannot be combined with sweep options")
        try:
            numeric_text(args.value)
        except ValueError as exc:
            parser.error(str(exc))
        return args

    if any(v is None for v in (args.minimum, args.maximum, args.step)):
        parser.error("provide --value or all of --min, --max, and --step")
    try:
        sweep_values(args.minimum, args.maximum, args.step, args.bounce)
    except (ValueError, InvalidOperation) as exc:
        parser.error(str(exc))
    return args


def run(argv=None):
    args = parse_args(argv)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if args.scenario:
            timed_scenario = load_timed_scenario(args.scenario)
            if timed_scenario is not None:
                duration_ms, events = timed_scenario
                send_timed_events(sock, duration_ms, events)
                return
            interval_ms, signals = load_scenario(args.scenario)
            delay = interval_ms / 1000
            for index in range(max(len(values) for _, _, values in signals)):
                for identifier, label, values in signals:
                    if index < len(values):
                        announce_and_send(sock, identifier, values[index], label)
                        time.sleep(delay)
            return

        identifier, label = resolve_signal(args.identifier, args.signal)
        if args.value is not None:
            announce_and_send(sock, identifier, args.value, label)
            return

        values = sweep_values(
            args.minimum, args.maximum, args.step, args.bounce
        )
        delay = args.interval_ms / 1000
        if args.bounce:
            while True:
                for value in values:
                    announce_and_send(sock, identifier, value, label)
                    time.sleep(delay)
        else:
            for value in values:
                announce_and_send(sock, identifier, value, label)
                time.sleep(delay)


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
