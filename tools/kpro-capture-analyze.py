#!/usr/bin/env python3
"""Analyze candump evidence offline; never opens a CAN or UDP socket."""

import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path
import sys

from kpro_can import FrameDecodeError, PROFILES, SignalTracker, decode_frame


bridge_path = Path(__file__).with_name("kpro-powertune-bridge.py")
if not bridge_path.exists():
    bridge_path = Path(__file__).with_name("kpro-powertune-bridge")
spec = importlib.util.spec_from_file_location("kpro_bridge_analysis", bridge_path)
if spec is None:
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("kpro_bridge_analysis", str(bridge_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def analyze(lines, profile="hondata-motec", stale_after=2.0):
    profile_data = PROFILES[profile]
    ect_frame, ect_field, ect_offset = next(
        (frame, field, sum(item.byte_width for item in frame.fields[:index]))
        for frame in profile_data["frames"]
        for index, field in enumerate(frame.fields) if field.name == "ect_c"
    )
    tracker = SignalTracker(profile)
    counts = Counter()
    dlcs = {}
    decoded = {}
    errors = []
    stale = []
    invalid = []
    changes = []
    ect_values = []
    last_raw = None
    first = last = previous = None
    ignored = 0
    for line_number, line in enumerate(lines, 1):
        try:
            frame = bridge.parse_candump_line(line)
        except ValueError as exc:
            errors.append({"line": line_number, "error": str(exc)})
            continue
        if frame is None:
            continue
        label = f"{frame.can_id:08X}" if frame.extended else f"{frame.can_id:03X}"
        if frame.remote:
            label += " remote"
        counts[label] += 1
        dlcs.setdefault(label, Counter())[len(frame.data)] += 1
        timestamp = frame.timestamp
        if timestamp is not None:
            first = timestamp if first is None else min(first, timestamp)
            last = timestamp if last is None else max(last, timestamp)
            if previous is not None and timestamp < previous:
                errors.append({"line": line_number, "error": "timestamp moved backwards; freshness may be unreliable"})
            previous = timestamp
            for name in tracker.mark_stale(timestamp, stale_after):
                stale.append({"timestamp": timestamp, "signal": name})
        ect_raw = None
        if (not frame.extended and not frame.remote and frame.can_id == ect_frame.can_id
                and len(frame.data) >= ect_offset + ect_field.byte_width):
            ect_raw = frame.data[ect_offset:ect_offset + ect_field.byte_width]
            if ect_raw != last_raw:
                unsigned = int.from_bytes(ect_raw, "big")
                signed = int.from_bytes(ect_raw, "big", signed=True)
                changes.append({"timestamp": timestamp, "dlc": len(frame.data),
                                "frame_hex": frame.data.hex().upper(), "raw_hex": ect_raw.hex().upper(),
                                "unsigned": unsigned, "signed_twos_complement": signed,
                                "current_decoded_c": None,
                                "hypotheses_c": {"unsigned_minus_40": unsigned - 40,
                                                 "unsigned_minus_273": unsigned - 273}})
                last_raw = ect_raw
        try:
            signals = decode_frame(frame, profile)
        except FrameDecodeError as exc:
            errors.append({"line": line_number, "error": str(exc)})
            continue
        if not signals:
            ignored += 1
            continue
        for signal in signals:
            if timestamp is not None:
                tracker.update(signal, timestamp, timestamp)
            if not signal.valid:
                invalid.append({"timestamp": timestamp, "signal": signal.name,
                                "reason": signal.invalid_reason})
            if signal.valid:
                state = decoded.setdefault(signal.name, {"unit": signal.unit, "min": signal.value,
                                                          "max": signal.value, "last": signal.value, "count": 0})
                state["min"] = min(state["min"], signal.value)
                state["max"] = max(state["max"], signal.value)
                state["last"] = signal.value
                state["count"] += 1
            if signal.name == "ect_c" and signal.valid:
                ect_values.append(signal.value)
                if ect_raw is not None and changes and changes[-1]["timestamp"] == timestamp:
                    changes[-1]["current_decoded_c"] = str(signal.value)
    elapsed = last - first if first is not None and last is not None else None
    for state in decoded.values():
        for key in ("min", "max", "last"):
            state[key] = str(state[key])
    return {
        "profile": profile, "documented_source": profile_data["source"],
        "timestamps": {"first": first, "last": last, "span_seconds": elapsed},
        "observed_frames": {key: {"count": count, "dlcs": dict(sorted(dlcs[key].items())),
                                   "rate_hz_over_capture_span": count / elapsed if elapsed and elapsed > 0 else None}
                            for key, count in sorted(counts.items())},
        "ignored_or_unexpected_frames": ignored, "malformed_records_or_frames": errors,
        "stale_transitions_observed_at_next_timestamped_frame": stale,
        "invalid_signals": invalid,
        "decoded_signals": decoded,
        "ect": {"assumed_source_id": f"0x{ect_frame.can_id:03X}",
                "assumed_dlc": ect_frame.derived_dlc, "assumed_byte_offset_zero_based": ect_offset,
                "width_bytes": ect_field.byte_width, "byte_order_assumption": "big-endian",
                "documented_conversion": "Hondata table: raw ECT in degrees Celsius; see source",
                "current_decoder_assumption": f"{'signed' if ect_field.signed else 'unsigned'} integer / {ect_field.divisor}",
                "hypotheses_warning": "Offsets are illustrative hypotheses, not established conversions; no decoder changes.",
                "raw_unsigned_min": min((item["unsigned"] for item in changes), default=None),
                "raw_unsigned_max": max((item["unsigned"] for item in changes), default=None),
                "min_c": str(min(ect_values)) if ect_values else None,
                "max_c": str(max(ect_values)) if ect_values else None,
                "change_count": max(0, len(changes) - 1), "initial_and_changes": changes},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="classic candump -L file")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="hondata-motec")
    parser.add_argument("--stale-after", type=float, default=2.0)
    args = parser.parse_args(argv)
    if not math.isfinite(args.stale_after) or args.stale_after <= 0:
        parser.error("--stale-after must be finite and positive")
    try:
        with open(args.capture, encoding="ascii") as source:
            report = analyze(source, args.profile, args.stale_after)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError) as exc:
        print(f"kpro-capture-analyze: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
