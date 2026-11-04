#!/usr/bin/env python3
"""Bench utility for Waveshare USB-CAN-A, using its published serial protocol."""

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
import re
import sys


# Protocol reference: Waveshare, "Serial (USB) to CAN Protocol Conversion"
# https://www.waveshare.com/wiki/Secondary_Development_Serial_Conversion_Definition_of_CAN_Protocol
# Device/driver reference: Waveshare, "USB-CAN-A"
# https://www.waveshare.com/wiki/USB-CAN-A
# Configuration framing and Linux serial setup are also documented in
# Waveshare's USB-CAN-A Linux demo: https://files.waveshare.com/wiki/USB-CAN-A/Demo/USB-CAN-A.zip
# The protocol page specifies 8N1; the Linux demo requests two stop bits.
# Follow the protocol specification here; physical serial framing is unverified.

USB_VID = 0x1A86
USB_PID = 0x7523
DEFAULT_SERIAL_BAUD = 2_000_000
DEFAULT_CAN_BITRATE = 500_000
MAX_SERIAL_BAUD = 2_000_000
HEADER = 0xAA
END = 0x55

BITRATE_CODES = {
    1_000_000: 0x01,
    800_000: 0x02,
    500_000: 0x03,
    400_000: 0x04,
    250_000: 0x05,
    200_000: 0x06,
    125_000: 0x07,
    100_000: 0x08,
    50_000: 0x09,
    20_000: 0x0A,
    10_000: 0x0B,
    5_000: 0x0C,
}

FRAME_TYPES = {"standard": 0x01, "extended": 0x02}


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    extended: bool
    data: bytes
    dlc: int
    remote: bool = False


def checksum(data):
    return sum(data) & 0xFF


def validate_bitrate(bitrate):
    if bitrate not in BITRATE_CODES:
        supported = ", ".join(str(rate) for rate in BITRATE_CODES)
        raise ValueError(f"unsupported CAN bitrate {bitrate}; supported: {supported}")
    return bitrate


def build_configuration(bitrate, frame_type="standard"):
    """Build the 20-byte 0x12 variable-protocol normal-mode setup command."""
    validate_bitrate(bitrate)
    if frame_type not in FRAME_TYPES:
        raise ValueError("frame type must be standard or extended")

    # 0x12 selects variable-length communication; filter and block IDs are
    # zeroed (unfiltered); mode 0 is normal; auto-retransmit remains enabled.
    command = bytearray(
        (
            0xAA,
            0x55,
            0x12,
            BITRATE_CODES[bitrate],
            FRAME_TYPES[frame_type],
            0, 0, 0, 0,  # filter ID
            0, 0, 0, 0,  # block/mask ID
            0x00,        # normal mode
            0x00,        # automatic retransmission enabled
            0, 0, 0, 0,  # reserved
        )
    )
    command.append(checksum(command[2:]))
    return bytes(command)


def parse_can_id(value, extended=False):
    try:
        can_id = int(value, 16)
    except ValueError as exc:
        raise ValueError("CAN ID must be hexadecimal (for example 123 or 0x123)") from exc
    maximum = 0x1FFFFFFF if extended else 0x7FF
    if not 0 <= can_id <= maximum:
        kind = "extended" if extended else "standard"
        raise ValueError(f"{kind} CAN ID must be between 0 and 0x{maximum:X}")
    return can_id


def parse_data(value):
    if value == "":
        return b""
    if len(value) % 2:
        raise ValueError("CAN data must contain an even number of hexadecimal digits")
    if len(value) > 16 or re.fullmatch(r"[0-9A-Fa-f]*", value) is None:
        raise ValueError("CAN data must be 0 to 8 bytes of hexadecimal digits")
    return bytes.fromhex(value)


def build_data_frame(can_id, data, extended=False):
    """Build a variable-length CAN data packet as specified by Waveshare."""
    if len(data) > 8:
        raise ValueError("CAN data payload must be at most 8 bytes")
    maximum = 0x1FFFFFFF if extended else 0x7FF
    if not 0 <= can_id <= maximum:
        kind = "extended" if extended else "standard"
        raise ValueError(f"{kind} CAN ID must be between 0 and 0x{maximum:X}")

    info = 0xC0 | (0x20 if extended else 0) | len(data)
    id_length = 4 if extended else 2
    packet = bytearray((HEADER, info))
    packet.extend(can_id.to_bytes(id_length, "little"))
    packet.extend(data)
    packet.append(END)
    return bytes(packet)


def decode_data_frame(packet):
    """Decode one complete variable-length CAN data or remote-frame packet."""
    if len(packet) < 5 or packet[0] != HEADER or packet[-1] != END:
        raise ValueError("invalid CAN packet header, length, or end code")
    info = packet[1]
    if info & 0xC0 != 0xC0:
        raise ValueError("unsupported Waveshare CAN packet type")

    extended = bool(info & 0x20)
    remote = bool(info & 0x10)
    dlc = info & 0x0F
    if dlc > 8:
        raise ValueError("Waveshare CAN packet has invalid DLC")
    id_length = 4 if extended else 2
    expected_length = 1 + 1 + id_length + dlc + 1
    if remote:
        expected_length -= dlc
    if len(packet) != expected_length:
        raise ValueError("Waveshare CAN packet length does not match DLC")

    can_id = int.from_bytes(packet[2:2 + id_length], "little")
    maximum_id = 0x1FFFFFFF if extended else 0x7FF
    if can_id > maximum_id:
        raise ValueError("Waveshare CAN packet contains an out-of-range CAN ID")
    data = packet[2 + id_length:-1]
    return CanFrame(can_id, extended, data, dlc, remote)


def extract_packets(buffer):
    """Return decoded frames and unconsumed bytes from a serial input buffer."""
    frames = []
    pending = bytearray(buffer)
    while pending:
        try:
            start = pending.index(HEADER)
        except ValueError:
            pending.clear()
            break
        if start:
            del pending[:start]
        if len(pending) < 2:
            break

        packet_type = pending[1]
        if packet_type == END:
            packet_length = 20
            if len(pending) < packet_length:
                break
            command = bytes(pending[:packet_length])
            if checksum(command[2:19]) == command[19]:
                del pending[:packet_length]
            else:
                del pending[0]
            continue

        if packet_type & 0xC0 != 0xC0:
            del pending[0]
            continue
        dlc = packet_type & 0x0F
        if dlc > 8:
            del pending[0]
            continue

        id_length = 4 if packet_type & 0x20 else 2
        payload_length = 0 if packet_type & 0x10 else dlc
        packet_length = 1 + 1 + id_length + payload_length + 1
        if len(pending) < packet_length:
            break
        packet = bytes(pending[:packet_length])
        try:
            frame = decode_data_frame(packet)
        except ValueError:
            del pending[0]
            continue
        frames.append(frame)
        del pending[:packet_length]
    return frames, bytes(pending)


def find_matching_devices(ports):
    return [
        port for port in ports
        if getattr(port, "vid", None) == USB_VID
        and getattr(port, "pid", None) == USB_PID
    ]


def resolve_device(ports, explicit_device=None):
    candidates = find_matching_devices(ports)
    if not candidates:
        raise ValueError(
            "no Waveshare USB-CAN-A found (expected USB VID:PID 1a86:7523)"
        )

    if explicit_device is not None:
        for port in candidates:
            device = getattr(port, "device", "")
            if explicit_device == device:
                return device
            try:
                if device and os.path.realpath(explicit_device) == os.path.realpath(device):
                    return device
            except OSError:
                pass
        available = ", ".join(getattr(port, "device", "?") for port in candidates)
        raise ValueError(
            f"--device must identify a Waveshare USB-CAN-A; matching devices: {available}"
        )

    if len(candidates) > 1:
        available = ", ".join(getattr(port, "device", "?") for port in candidates)
        raise ValueError(
            f"multiple Waveshare USB-CAN-A devices found: {available}; "
            "select one with --device"
        )
    return candidates[0].device


def get_serial_modules():
    try:
        import serial
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required; install the Python pyserial package"
        ) from exc
    return serial, list_ports


def discover():
    _, list_ports = get_serial_modules()
    devices = find_matching_devices(list_ports.comports())
    if not devices:
        print("No Waveshare USB-CAN-A found (expected USB VID:PID 1a86:7523).")
        return 1
    for port in devices:
        print(
            f"{port.device}: VID:PID={port.vid:04x}:{port.pid:04x}"
            f" manufacturer={port.manufacturer or 'unknown'}"
            f" product={port.product or 'unknown'}"
        )
    if len(devices) > 1:
        print("Multiple adapters found; specify --device for send or receive.")
    return 0


def open_adapter(device, serial_baud):
    serial, _ = get_serial_modules()
    if not 1 <= serial_baud <= MAX_SERIAL_BAUD:
        raise ValueError(f"serial baud must be between 1 and {MAX_SERIAL_BAUD}")
    return serial.Serial(
        port=device,
        baudrate=serial_baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.1,
        write_timeout=2,
    )


def configure_adapter(port, bitrate, frame_type):
    port.write(build_configuration(bitrate, frame_type))
    port.flush()


def format_frame(frame, timestamp=None):
    timestamp = timestamp or datetime.now().astimezone().isoformat(
        timespec="milliseconds"
    )
    frame_kind = "Extended" if frame.extended else "Standard"
    id_width = 8 if frame.extended else 3
    payload = " ".join(f"{byte:02X}" for byte in frame.data) or (
        "(none)" if frame.remote else "(empty)"
    )
    return (
        f"{timestamp} {frame_kind} "
        f"{'remote' if frame.remote else 'data'} ID 0x{frame.can_id:0{id_width}X} "
        f"DLC {frame.dlc} payload {payload}"
    )


def receive_frames(port):
    buffer = b""
    while True:
        chunk = port.read(256)
        if not chunk:
            continue
        frames, buffer = extract_packets(buffer + chunk)
        for frame in frames:
            print(format_frame(frame), flush=True)


def make_parser():
    parser = argparse.ArgumentParser(
        description="Bench send/receive utility for the Waveshare USB-CAN-A."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover", help="find adapters by USB VID:PID 1a86:7523")

    send = subparsers.add_parser("send", help="send one CAN data frame")
    send.add_argument("--can-bitrate", type=int, default=DEFAULT_CAN_BITRATE)
    send.add_argument("--id", required=True, help="CAN ID (hex, e.g. 123 or 0x123)")
    send.add_argument("--data", default="", help="0-8 payload bytes as hex")
    send.add_argument("--extended", action="store_true", help="use a 29-bit ID")
    send.add_argument("--device", help="explicit matching adapter tty path")
    send.add_argument("--serial-baud", type=int, default=DEFAULT_SERIAL_BAUD)

    receive = subparsers.add_parser("receive", help="receive and display CAN frames")
    receive.add_argument("--can-bitrate", type=int, default=DEFAULT_CAN_BITRATE)
    receive.add_argument(
        "--frame-type", choices=sorted(FRAME_TYPES), default="standard",
        help="adapter receive frame selection (default: standard)",
    )
    receive.add_argument("--device", help="explicit matching adapter tty path")
    receive.add_argument("--serial-baud", type=int, default=DEFAULT_SERIAL_BAUD)
    return parser


def run(argv=None, ports_provider=None, serial_opener=None):
    args = make_parser().parse_args(argv)
    if args.command == "discover":
        return discover()

    validate_bitrate(args.can_bitrate)
    _, list_ports = get_serial_modules()
    ports = ports_provider() if ports_provider else list_ports.comports()
    device = resolve_device(ports, args.device)
    opener = serial_opener or open_adapter

    if args.command == "send":
        extended = args.extended
        can_id = parse_can_id(args.id, extended)
        data = parse_data(args.data)
        packet = build_data_frame(can_id, data, extended)
        frame_type = "extended" if extended else "standard"
        with opener(device, args.serial_baud) as port:
            configure_adapter(port, args.can_bitrate, frame_type)
            port.write(packet)
            port.flush()
        print(
            f"TX {frame_type} ID 0x{can_id:0{8 if extended else 3}X} "
            f"DLC {len(data)} payload "
            f"{' '.join(f'{byte:02X}' for byte in data) or '(empty)'} "
            f"via {device}"
        )
        return 0

    with opener(device, args.serial_baud) as port:
        configure_adapter(port, args.can_bitrate, args.frame_type)
        print(
            f"Receiving {args.frame_type} CAN at {args.can_bitrate} bit/s "
            f"from {device}; Ctrl-C to stop.",
            flush=True,
        )
        receive_frames(port)


def main(argv=None):
    try:
        return run(argv)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"pt-usb-can: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
