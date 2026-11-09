#!/usr/bin/env python3
"""Read K-Pro4 CAN telemetry and publish verified PowerTune UDP records."""

import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
import json
import math
import re
import socket
import struct
import sys
import time

from kpro_can import (
    CanFrame,
    FrameDecodeError,
    PROFILES,
    SignalTracker,
    decode_frame,
    encode_signals,
)
from powertune_udp import PowerTunePublisher


CAN_RAW = getattr(socket, "CAN_RAW", 1)
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_FRAME = struct.Struct("=IB3x8s")
CAN_DUMP_FRAME = re.compile(
    r"^(?P<canid>[0-9A-Fa-f]{1,8})#(?P<data>(?:[0-9A-Fa-f]{2})*|R[0-8])$"
)
CAN_DUMP_TIMESTAMP = re.compile(r"^\((?P<timestamp>\d+(?:\.\d+)?)\)$")


@dataclass
class BridgeMetrics:
    generated_can_frames: int = 0
    transmitted_can_frames: int = 0
    received_can_frames: int = 0
    decoded_frames: int = 0
    ignored_frames: int = 0
    malformed_frames: int = 0
    decoded_signal_updates: int = 0
    valid_signal_changes: int = 0
    unchanged_signal_suppressions: int = 0
    udp_records_sent: int = 0
    stale_transitions: int = 0
    invalid_transitions: int = 0
    elapsed_seconds: float = 0.0

    def summary(self):
        result = asdict(self)
        result["effective_frame_rate_hz"] = (
            self.received_can_frames / self.elapsed_seconds
            if self.elapsed_seconds > 0 else 0.0
        )
        result["effective_udp_publication_rate_hz"] = (
            self.udp_records_sent / self.elapsed_seconds
            if self.elapsed_seconds > 0 else 0.0
        )
        return result


class SocketCanSource:
    """Read-only SocketCAN source requiring an explicit interface name."""

    def __init__(self, interface, socket_factory=None):
        if not interface:
            raise ValueError("an explicit --can-interface is required")
        self.interface = interface
        self.socket_factory = socket_factory or socket.socket
        self.socket = None

    def __enter__(self):
        if not hasattr(socket, "PF_CAN"):
            raise RuntimeError("live SocketCAN input is only available on Linux")
        can_socket = self.socket_factory(socket.PF_CAN, socket.SOCK_RAW, CAN_RAW)
        try:
            can_socket.bind((self.interface,))
        except Exception:
            can_socket.close()
            raise
        can_socket.settimeout(0.25)
        self.socket = can_socket
        return self

    def __exit__(self, *_):
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def receive(self):
        try:
            raw_frame = self.socket.recv(CAN_FRAME.size)
        except socket.timeout:
            return None
        if len(raw_frame) != CAN_FRAME.size:
            raise ValueError("received an invalid SocketCAN frame length")
        can_id, dlc, payload = CAN_FRAME.unpack(raw_frame)
        if dlc > 8:
            return None
        extended = bool(can_id & CAN_EFF_FLAG)
        remote = bool(can_id & CAN_RTR_FLAG)
        identifier = can_id & (0x1FFFFFFF if extended else 0x7FF)
        return CanFrame(identifier, b"" if remote else payload[:dlc], extended, remote)


def parse_candump_line(line):
    """Parse classic candump text: '(time) interface ID#hexdata'."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    tokens = stripped.split()
    timestamp = None
    timestamp_match = CAN_DUMP_TIMESTAMP.fullmatch(tokens[0]) if tokens else None
    if timestamp_match:
        timestamp = float(timestamp_match.group("timestamp"))
        tokens.pop(0)
    if not tokens:
        return None

    match = CAN_DUMP_FRAME.fullmatch(tokens[-1])
    if match is None:
        if "##" in tokens[-1]:
            raise ValueError("CAN FD candump records are not supported")
        raise ValueError(f"invalid classic candump record: {stripped}")
    can_id_text = match.group("canid")
    data_text = match.group("data")
    can_id = int(can_id_text, 16)
    extended = len(can_id_text) > 3
    maximum_id = 0x1FFFFFFF if extended else 0x7FF
    if can_id > maximum_id:
        raise ValueError(f"candump CAN ID is outside the {'extended' if extended else 'standard'} range")
    if data_text.startswith("R"):
        return CanFrame(can_id, b"", extended, True, timestamp)
    if len(data_text) > 16:
        raise ValueError("classic CAN candump payload cannot exceed 8 bytes")
    return CanFrame(can_id, bytes.fromhex(data_text), extended, False, timestamp)


def iter_replay(lines, speed=1.0, sleep=time.sleep):
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("replay speed must be a finite nonnegative number")
    previous_timestamp = None
    for line in lines:
        frame = parse_candump_line(line)
        if frame is None:
            continue
        if speed > 0 and frame.timestamp is not None and previous_timestamp is not None:
            delay = max(0.0, frame.timestamp - previous_timestamp) / speed
            if delay:
                sleep(delay)
        if frame.timestamp is not None:
            previous_timestamp = frame.timestamp
        yield frame


def iter_scenario(scenario, speed=1.0, sleep=time.sleep, default_profile="hondata-motec"):
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("scenario replay speed must be a finite nonnegative number")
    if not isinstance(scenario, dict) or not isinstance(scenario.get("events"), list):
        raise ValueError("scenario must contain an events array")
    profile = scenario.get("profile", default_profile)
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError(f"unknown scenario profile: {profile}")

    previous_ms = None
    for event in scenario["events"]:
        if not isinstance(event, dict) or "at_ms" not in event:
            raise ValueError("each scenario event must contain at_ms and signals")
        at_ms = event["at_ms"]
        if isinstance(at_ms, bool) or not isinstance(at_ms, int):
            raise ValueError("scenario at_ms values must be integers")
        if at_ms < 0 or (previous_ms is not None and at_ms < previous_ms):
            raise ValueError("scenario at_ms values must be nonnegative and ordered")
        if speed > 0 and previous_ms is not None:
            delay = (at_ms - previous_ms) / 1000.0 / speed
            if delay:
                sleep(delay)
        signals = event.get("signals")
        if not isinstance(signals, dict):
            raise ValueError("scenario event signals must be an object")
        for frame in encode_signals(signals, profile):
            yield CanFrame(
                frame.can_id, frame.data, frame.extended, frame.remote, at_ms / 1000.0
            )
        previous_ms = at_ms


class DiagnosticLimiter:
    def __init__(self, emit, now=time.monotonic, max_per_second=10):
        self.emit = emit
        self.now = now
        self.max_per_second = max_per_second
        self.window = None
        self.emitted = 0
        self.suppressed = 0

    def write(self, message):
        current_window = int(self.now())
        if current_window != self.window:
            previous_suppressed = self.suppressed
            self.window = current_window
            self.emitted = 0
            self.suppressed = 0
            if previous_suppressed and self.max_per_second:
                self.emit(f"diagnostic output suppressed: {previous_suppressed} messages")
                self.emitted = 1
        if self.emitted >= self.max_per_second:
            self.suppressed += 1
            return
        self.emit(message)
        self.emitted += 1


def make_parser():
    parser = argparse.ArgumentParser(
        description="Read documented Hondata K-Pro4 CAN output and publish PowerTune records."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--can-interface", help="explicit SocketCAN interface name")
    source.add_argument("--replay", metavar="CAN_DUMP", help="replay classic candump text")
    source.add_argument("--scenario", metavar="JSON", help="replay a deterministic signal scenario")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="hondata-motec")
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=45454)
    parser.add_argument("--replay-speed", type=float, default=1.0,
                        help="timing multiplier; 0 replays without delays")
    parser.add_argument("--stale-after", type=float, default=2.0,
                        help="mark a signal stale after this many seconds (default: 2)")
    parser.add_argument("--diagnostic", action="store_true",
                        help="show decoded values, validity changes, and UDP records")
    parser.add_argument("--no-udp", action="store_true",
                        help="offline replay/scenario analysis without opening or sending UDP")
    parser.add_argument("--summary", action="store_true",
                        help="print bounded processing metrics on exit")
    return parser


@contextmanager
def open_udp_socket(socket_factory=socket.socket):
    udp_socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        yield udp_socket
    finally:
        udp_socket.close()


def _process_frame(
    frame, profile, tracker, publisher, now, diagnostics=None, metrics=None, no_udp=False
):
    try:
        signals = decode_frame(frame, profile)
    except FrameDecodeError as exc:
        if metrics:
            metrics.malformed_frames += 1
        if diagnostics:
            diagnostics.write(f"invalid frame: {exc}")
        return
    if not signals:
        if metrics:
            metrics.ignored_frames += 1
        return
    if metrics:
        metrics.decoded_frames += 1

    for signal in signals:
        if metrics:
            metrics.decoded_signal_updates += 1
        changed = tracker.update(signal, now, frame.timestamp)
        if metrics and changed and signal.valid:
            metrics.valid_signal_changes += 1
        if metrics and changed and not signal.valid:
            metrics.invalid_transitions += 1
        if diagnostics and changed:
            value = "invalid" if not signal.valid else str(signal.value)
            diagnostics.write(
                f"decoded {signal.name}={value} {signal.unit} "
                f"CAN ID 0x{signal.can_id:03X}"
            )
        is_mapped = signal.valid and signal.value is not None and signal.name in publisher.identifier_map
        packet = publisher.publish(signal)
        if metrics and packet is not None and not no_udp:
            metrics.udp_records_sent += 1
        elif metrics and is_mapped and packet is None:
            metrics.unchanged_signal_suppressions += 1
        if packet is not None and diagnostics:
            diagnostics.write(
                f"{'would publish' if no_udp else 'UDP'} {packet.decode('ascii')} -> "
                f"{publisher.destination[0]}:{publisher.destination[1]}"
            )


def run_bridge(args, socket_factory=socket.socket, sleep=time.sleep, now=time.monotonic):
    if args.no_udp and not (args.replay or args.scenario):
        raise ValueError("--no-udp is restricted to replay or scenario input")
    if not math.isfinite(args.replay_speed) or args.replay_speed < 0:
        raise ValueError("--replay-speed must be a finite nonnegative number")
    if not math.isfinite(args.stale_after) or args.stale_after <= 0:
        raise ValueError("--stale-after must be a finite number greater than zero")
    if not 1 <= args.udp_port <= 65535:
        raise ValueError("--udp-port must be between 1 and 65535")

    tracker = SignalTracker(args.profile)
    emit = print
    diagnostics = (
        DiagnosticLimiter(emit, now=now) if args.diagnostic else None
    )
    destination = (args.udp_host, args.udp_port)
    metrics = BridgeMetrics()
    started = now()

    try:
        udp_context = nullcontext(None) if args.no_udp else open_udp_socket(socket_factory)
        with udp_context as udp_socket:
            sendto = (lambda _packet, _destination: None) if args.no_udp else udp_socket.sendto
            publisher = PowerTunePublisher(sendto, destination)
            if args.replay:
                with open(args.replay, encoding="ascii") as replay_file:
                    frames = iter_replay(replay_file, args.replay_speed, sleep)
                    for frame in frames:
                        current = now()
                        metrics.received_can_frames += 1
                        stale = tracker.mark_stale(current, args.stale_after)
                        metrics.stale_transitions += len(stale)
                        for signal_name in stale:
                            if diagnostics:
                                diagnostics.write(f"signal {signal_name} stale")
                        _process_frame(
                            frame, args.profile, tracker, publisher, current,
                            diagnostics, metrics, args.no_udp,
                        )
                return

            if args.scenario:
                with open(args.scenario, encoding="utf-8") as scenario_file:
                    scenario = json.load(scenario_file)
                profile = scenario.get("profile", args.profile)
                tracker = SignalTracker(profile)
                for frame in iter_scenario(
                    scenario, args.replay_speed, sleep, default_profile=args.profile
                ):
                    current = now()
                    metrics.received_can_frames += 1
                    stale = tracker.mark_stale(current, args.stale_after)
                    metrics.stale_transitions += len(stale)
                    for signal_name in stale:
                        if diagnostics:
                            diagnostics.write(f"signal {signal_name} stale")
                    _process_frame(
                        frame, profile, tracker, publisher, current,
                        diagnostics, metrics, args.no_udp,
                    )
                return

            with SocketCanSource(args.can_interface, socket_factory) as source:
                if diagnostics:
                    diagnostics.write(
                        f"listening on SocketCAN interface {args.can_interface}; "
                        f"PowerTune UDP destination {destination[0]}:{destination[1]}"
                    )
                while True:
                    frame = source.receive()
                    current = now()
                    stale = tracker.mark_stale(current, args.stale_after)
                    metrics.stale_transitions += len(stale)
                    for signal_name in stale:
                        if diagnostics:
                            diagnostics.write(f"signal {signal_name} stale")
                    if frame is not None:
                        metrics.received_can_frames += 1
                        _process_frame(
                            frame, args.profile, tracker, publisher, current,
                            diagnostics, metrics,
                        )
    finally:
        metrics.elapsed_seconds = max(0.0, now() - started)
        if args.summary:
            print(json.dumps(metrics.summary(), indent=2, sort_keys=True))


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        run_bridge(args)
        return 0
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"kpro-powertune-bridge: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
