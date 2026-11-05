#!/usr/bin/env python3
"""Generate, inspect, replay, export, or explicitly transmit synthetic K-Pro telemetry."""

import argparse
from dataclasses import dataclass, asdict
from decimal import Decimal
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
import time

from kpro_can import FrameDecodeError, SignalTracker, decode_frame
from kpro_workload import (
    MAX_FRAME_RATE_HZ,
    MAX_GENERATED_FRAMES,
    ScenarioError,
    iter_scheduled_frames,
    scenario_summary,
    validate_scenario,
)
from powertune_udp import PowerTunePublisher


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = Path(__file__).with_name("pt-usb-can.py")


@dataclass
class WorkloadMetrics:
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
    udp_records_would_send: int = 0
    stale_transitions: int = 0
    invalid_transitions: int = 0
    elapsed_seconds: float = 0.0

    def summary(self):
        result = asdict(self)
        elapsed = self.elapsed_seconds
        frame_count = (
            self.received_can_frames
            or self.transmitted_can_frames
            or self.generated_can_frames
        )
        result["effective_frame_rate_hz"] = (
            frame_count / elapsed if elapsed > 0 else 0.0
        )
        result["effective_udp_publication_rate_hz"] = (
            self.udp_records_sent / elapsed if elapsed > 0 else 0.0
        )
        return result


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"cannot load scenario {path}: {exc}") from exc
    return validate_scenario(data)


def _load_script(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _frames(scenario, frame_rate):
    return iter_scheduled_frames(scenario, frame_rate)


def _sleep_for_schedule(previous_virtual_time, virtual_time, speed, sleep=time.sleep):
    if speed <= 0 or previous_virtual_time is None:
        return
    delay = (virtual_time - previous_virtual_time) / speed
    if delay > 0:
        sleep(delay)


def replay_scenario(
    scenario,
    udp_host="127.0.0.1",
    udp_port=45454,
    send_udp=True,
    speed=0.0,
    frame_rate=None,
    stale_after=2.0,
    diagnostic=False,
    capture_packets=False,
    socket_factory=socket.socket,
    sleep=time.sleep,
    clock=time.monotonic,
):
    if not 0 <= udp_port <= 65535:
        raise ScenarioError("UDP port must be between 0 and 65535")
    if not math.isfinite(speed) or speed < 0:
        raise ScenarioError("speed must be a finite nonnegative number")
    if not math.isfinite(stale_after) or stale_after <= 0:
        raise ScenarioError("stale-after must be greater than zero")
    metrics = WorkloadMetrics()
    tracker = SignalTracker(scenario.profile)
    started = clock()
    previous_virtual_time = None
    emitted = []
    udp_socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM) if send_udp else None
    sender = udp_socket.sendto if udp_socket else lambda *_args: None
    publisher = PowerTunePublisher(
        sender,
        (udp_host, udp_port),
        epsilon=scenario.publication_epsilon,
    )
    try:
        for frame in _frames(scenario, frame_rate):
            virtual_time = frame.timestamp or 0.0
            _sleep_for_schedule(previous_virtual_time, virtual_time, speed, sleep)
            previous_virtual_time = virtual_time
            stale_names = tracker.mark_stale(virtual_time, stale_after)
            metrics.stale_transitions += len(stale_names)
            if diagnostic:
                for name in stale_names:
                    print(f"{virtual_time:9.3f}s {name} stale")
            metrics.generated_can_frames += 1
            metrics.received_can_frames += 1
            signals = decode_frame(frame, scenario.profile)
            if not signals:
                metrics.ignored_frames += 1
                continue
            metrics.decoded_frames += 1
            for signal in signals:
                metrics.decoded_signal_updates += 1
                changed = tracker.update(signal, virtual_time, virtual_time)
                if not signal.valid:
                    if changed:
                        metrics.invalid_transitions += 1
                    continue
                if changed:
                    metrics.valid_signal_changes += 1
                is_mapped = (
                    signal.valid
                    and signal.value is not None
                    and signal.name in publisher.identifier_map
                )
                packet = publisher.publish(signal)
                if packet is not None:
                    metrics.udp_records_would_send += 1
                    if capture_packets:
                        emitted.append(packet)
                    if udp_socket:
                        metrics.udp_records_sent += 1
                elif is_mapped:
                    metrics.unchanged_signal_suppressions += 1
                if diagnostic and changed:
                    print(
                        f"{virtual_time:9.3f}s CAN 0x{frame.can_id:03X} "
                        f"{signal.name}={signal.value} {signal.unit}"
                    )
        stale = tracker.mark_stale(float(scenario.duration), stale_after)
        metrics.stale_transitions += len(stale)
        if diagnostic:
            for name in stale:
                print(f"{float(scenario.duration):9.3f}s {name} stale")
    except FrameDecodeError:
        metrics.malformed_frames += 1
        raise
    finally:
        metrics.elapsed_seconds = max(0.0, clock() - started)
        if udp_socket:
            udp_socket.close()
    return metrics, emitted


def export_candump(scenario, output, interface="synthetic", frame_rate=None):
    frames = list(_frames(scenario, frame_rate))
    with open(output, "w", encoding="ascii", newline="\n") as file:
        for frame in frames:
            timestamp = frame.timestamp or 0.0
            payload = frame.data.hex().upper()
            file.write(f"({timestamp:.6f}) {interface} {frame.can_id:03X}#{payload}\n")
    return len(frames)


def transmit_scenario(
    scenario,
    device=None,
    can_bitrate=None,
    serial_baud=2_000_000,
    speed=1.0,
    frame_rate=None,
    adapter=None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    if not math.isfinite(speed) or speed <= 0:
        raise ScenarioError("physical transmit speed must be finite and greater than zero")
    effective_rate = scenario.frame_rate_hz if frame_rate is None else frame_rate
    if isinstance(effective_rate, bool) or not isinstance(effective_rate, int):
        raise ScenarioError("frame rate must be an integer")
    if not 0 <= effective_rate <= MAX_FRAME_RATE_HZ:
        raise ScenarioError(f"frame rate must be from 0 through {MAX_FRAME_RATE_HZ} Hz")
    if Decimal(effective_rate) * scenario.duration > MAX_GENERATED_FRAMES:
        raise ScenarioError(
            f"scenario exceeds the {MAX_GENERATED_FRAMES}-frame safety limit"
        )
    if not scenario.active_specs or effective_rate == 0:
        return WorkloadMetrics(), None
    adapter = adapter or _load_script(ADAPTER_PATH, "pt_usb_can_workload_helper")
    _, list_ports = adapter.get_serial_modules()
    resolved_device = adapter.resolve_device(list_ports.comports(), device)
    bitrate = scenario.can_bitrate if can_bitrate is None else can_bitrate
    adapter.validate_bitrate(bitrate)
    if scenario.profile == "aim" and bitrate != 1_000_000:
        raise ScenarioError("the documented AiM profile requires 1000000 bit/s")
    if scenario.profile == "hondata-motec" and bitrate not in (250_000, 500_000, 1_000_000):
        raise ScenarioError(
            "the documented Hondata/MoTeC profile supports 250000, 500000, "
            "or 1000000 bit/s"
        )
    metrics = WorkloadMetrics()
    started = clock()
    previous_virtual_time = None
    with adapter.open_adapter(resolved_device, serial_baud) as port:
        adapter.configure_adapter(port, bitrate, "standard")
        for frame in _frames(scenario, frame_rate):
            virtual_time = frame.timestamp or 0.0
            _sleep_for_schedule(previous_virtual_time, virtual_time, speed, sleep)
            previous_virtual_time = virtual_time
            packet = adapter.build_data_frame(frame.can_id, frame.data, frame.extended)
            port.write(packet)
            metrics.generated_can_frames += 1
            metrics.transmitted_can_frames += 1
        port.flush()
    metrics.elapsed_seconds = max(0.0, clock() - started)
    return metrics, resolved_device


def _add_scenario_argument(parser):
    parser.add_argument("--scenario", required=True, help="scenario JSON file")


def make_parser():
    parser = argparse.ArgumentParser(
        description="Deterministic synthetic Hondata K-Pro workload utility."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="validate and summarize a scenario")
    _add_scenario_argument(inspect)
    inspect.add_argument("--frame-rate-hz", type=int)

    replay = subparsers.add_parser("replay", help="run generated frames through the decoder/publisher")
    _add_scenario_argument(replay)
    replay.add_argument("--udp-host", default="127.0.0.1")
    replay.add_argument("--udp-port", type=int, default=45454)
    replay.add_argument("--diagnostic", action="store_true")
    replay.add_argument("--summary", action="store_true")
    replay.add_argument("--speed", type=float, default=0.0,
                        help="wall-clock pacing multiplier; 0 runs as fast as possible")
    replay.add_argument("--frame-rate-hz", type=int)
    replay.add_argument("--stale-after", type=float, default=2.0)
    replay.add_argument("--no-udp", action="store_true",
                        help="decode/publish in-process without sending UDP")

    transmit = subparsers.add_parser("transmit", help="send scenario frames through Waveshare USB-CAN-A")
    _add_scenario_argument(transmit)
    transmit.add_argument("--can-bitrate", type=int)
    transmit.add_argument("--device", help="explicit matching 1a86:7523 adapter")
    transmit.add_argument("--serial-baud", type=int, default=2_000_000)
    transmit.add_argument("--speed", type=float, default=1.0)
    transmit.add_argument("--frame-rate-hz", type=int)
    transmit.add_argument("--summary", action="store_true")

    export = subparsers.add_parser("export", help="export deterministic candump-format frames")
    _add_scenario_argument(export)
    export.add_argument("--output", required=True)
    export.add_argument("--interface", default="synthetic")
    export.add_argument("--frame-rate-hz", type=int)

    return parser


def _print_summary(metrics):
    print(json.dumps(metrics.summary(), indent=2, sort_keys=True))


def run(argv=None):
    args = make_parser().parse_args(argv)
    scenario = _load_json(args.scenario)
    frame_rate = getattr(args, "frame_rate_hz", None)
    if args.command == "inspect":
        print(json.dumps(
            scenario_summary(scenario, frame_rate_hz=frame_rate),
            indent=2,
            sort_keys=True,
        ))
        return 0
    if args.command == "export":
        count = export_candump(
            scenario, args.output, args.interface, frame_rate
        )
        print(f"Exported {count} frames to {args.output}")
        return 0
    if args.command == "replay":
        metrics, _ = replay_scenario(
            scenario,
            args.udp_host,
            args.udp_port,
            send_udp=not args.no_udp,
            speed=args.speed,
            frame_rate=frame_rate,
            stale_after=args.stale_after,
            diagnostic=args.diagnostic,
            capture_packets=False,
        )
        if args.summary:
            _print_summary(metrics)
        return 0
    metrics, device = transmit_scenario(
        scenario,
        device=args.device,
        can_bitrate=args.can_bitrate,
        serial_baud=args.serial_baud,
        speed=args.speed,
        frame_rate=frame_rate,
    )
    if device is not None:
        print(f"Transmitted {metrics.transmitted_can_frames} frames via {device}")
    else:
        print("P0: no frames generated; Waveshare adapter was not opened.")
    if args.summary:
        _print_summary(metrics)
    return 0


def main(argv=None):
    try:
        return run(argv)
    except KeyboardInterrupt:
        print("Stopped; open adapter handles were closed.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ScenarioError, ValueError, json.JSONDecodeError) as exc:
        print(f"kpro-workload: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
