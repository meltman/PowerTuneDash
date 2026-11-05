"""Deterministic K-Pro telemetry scenarios and synthetic frame scheduling."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Dict, Iterable, Mapping, Optional

from kpro_can import PROFILES, CanFrame, encode_signals
from powertune_udp import POWER_TUNE_IDS


WORKLOAD_CLASSES = {
    "P0": "no telemetry",
    "P1": "decoded but unmapped traffic",
    "P2": "constant mapped values",
    "P3": "slowly changing mapped values",
    "P4": "realistic multi-signal drive",
    "P5": "maximum synthetic stress",
    "P6": "display-static bus-noisy",
}
SUPPORTED_BITRATES = {
    1_000_000, 800_000, 500_000, 400_000, 250_000, 200_000,
    125_000, 100_000, 50_000, 20_000, 10_000, 5_000,
}
DEFAULT_FRAME_RATE_HZ = 20
MAX_FRAME_RATE_HZ = 200
MAX_DURATION_SECONDS = 3600
MAX_GENERATED_FRAMES = 200_000
PUBLISHABLE_SIGNALS = frozenset(POWER_TUNE_IDS)


class ScenarioError(ValueError):
    pass


def _decimal(value, context):
    if isinstance(value, bool):
        raise ScenarioError(f"{context} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ScenarioError(f"{context} must be a finite number") from None
    if not result.is_finite():
        raise ScenarioError(f"{context} must be a finite number")
    return result


@dataclass(frozen=True)
class Scenario:
    data: Mapping
    active_specs: tuple
    signals_by_frame: Mapping[int, tuple]
    stop_frames_after: Mapping[int, Decimal]

    @property
    def name(self):
        return self.data["name"]

    @property
    def workload_class(self):
        return self.data["workload_class"]

    @property
    def profile(self):
        return self.data["profile"]

    @property
    def duration(self):
        return Decimal(str(self.data["duration_seconds"]))

    @property
    def duration_ms(self):
        return int(self.duration * 1000)

    @property
    def tick_ms(self):
        return self.data["tick_ms"]

    @property
    def frame_rate_hz(self):
        return self.data["frame_rate_hz"]

    @property
    def can_bitrate(self):
        return self.data["can_bitrate"]

    @property
    def publication_epsilon(self):
        return {
            name: Decimal(str(value))
            for name, value in self.data.get("publication_epsilon", {}).items()
        }

    def value_at(self, name, seconds):
        behavior = self.data["signals"][name]
        kind = behavior["type"]
        t = Decimal(str(seconds))
        if kind in ("constant", "explicit"):
            return _decimal(behavior["value"], f"signal {name}")
        if kind == "sweep":
            fraction = min(Decimal(1), t / self.duration)
            return _lerp(behavior["start"], behavior["end"], fraction)
        if kind == "triangle":
            period = _decimal(behavior["period_seconds"], f"{name}.period_seconds")
            phase = (
                t + _decimal(behavior.get("phase_seconds", 0), f"{name}.phase_seconds")
            ) % period
            phase = (phase + period) % period
            half = period / 2
            fraction = phase / half if phase <= half else (period - phase) / half
            return _lerp(behavior["minimum"], behavior["maximum"], fraction)
        if kind == "sequence":
            hold = behavior["hold_ticks"] * self.tick_ms
            index = min(int(t * 1000 // hold), len(behavior["values"]) - 1)
            return _decimal(behavior["values"][index], f"{name}.values[{index}]")
        if kind == "keyframes":
            return _keyframe_value(behavior, t, name)
        if kind == "sine":
            period = float(behavior["period_seconds"])
            phase = float(behavior.get("phase_radians", 0))
            wave = math.sin((2 * math.pi * float(t) / period) + phase)
            value = float(behavior["center"]) + float(behavior["amplitude"]) * wave
            return _decimal(value, f"signal {name}")
        raise ScenarioError(f"unsupported behavior type for {name}: {kind}")

    def values_at(self, seconds):
        return {name: self.value_at(name, seconds) for name in self.data["signals"]}


def _lerp(start, end, fraction):
    return _decimal(start, "interpolation start") + (
        _decimal(end, "interpolation end") - _decimal(start, "interpolation start")
    ) * fraction


def _keyframe_value(behavior, seconds, name):
    frames = behavior["keyframes"]
    if seconds <= Decimal(str(frames[0]["at_seconds"])):
        return _decimal(frames[0]["value"], f"{name} keyframe")
    for left, right in zip(frames, frames[1:]):
        left_t = Decimal(str(left["at_seconds"]))
        right_t = Decimal(str(right["at_seconds"]))
        if seconds <= right_t:
            left_value = _decimal(left["value"], f"{name} keyframe")
            if behavior["interpolation"] == "step":
                return left_value
            fraction = (seconds - left_t) / (right_t - left_t)
            return _lerp(left_value, right["value"], fraction)
    return _decimal(frames[-1]["value"], f"{name} keyframe")


def _validate_behavior(name, behavior, duration, tick_ms):
    if not isinstance(behavior, dict):
        raise ScenarioError(f"signal {name} behavior must be an object")
    kind = behavior.get("type")
    if kind in ("constant", "explicit"):
        _decimal(behavior.get("value"), f"signal {name}.value")
        return
    if kind == "sweep":
        _decimal(behavior.get("start"), f"signal {name}.start")
        _decimal(behavior.get("end"), f"signal {name}.end")
        return
    if kind == "triangle":
        minimum = _decimal(behavior.get("minimum"), f"signal {name}.minimum")
        maximum = _decimal(behavior.get("maximum"), f"signal {name}.maximum")
        if minimum > maximum:
            raise ScenarioError(f"signal {name} minimum must not exceed maximum")
        period = _decimal(behavior.get("period_seconds"), f"signal {name}.period_seconds")
        if period <= 0:
            raise ScenarioError(f"signal {name} period_seconds must be greater than zero")
        _decimal(behavior.get("phase_seconds", 0), f"signal {name}.phase_seconds")
        return
    if kind == "sequence":
        values = behavior.get("values")
        hold_ticks = behavior.get("hold_ticks", 1)
        if not isinstance(values, list) or not values:
            raise ScenarioError(f"signal {name} sequence values must be a nonempty array")
        if isinstance(hold_ticks, bool) or not isinstance(hold_ticks, int) or hold_ticks < 1:
            raise ScenarioError(f"signal {name} hold_ticks must be a positive integer")
        for index, value in enumerate(values):
            _decimal(value, f"signal {name}.values[{index}]")
        return
    if kind == "keyframes":
        frames = behavior.get("keyframes")
        interpolation = behavior.get("interpolation")
        if interpolation not in ("linear", "step"):
            raise ScenarioError(f"signal {name} interpolation must be linear or step")
        if not isinstance(frames, list) or not frames:
            raise ScenarioError(f"signal {name} keyframes must be a nonempty array")
        previous = None
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict) or "at_seconds" not in frame or "value" not in frame:
                raise ScenarioError(f"signal {name} keyframe {index} needs at_seconds and value")
            at = _decimal(frame["at_seconds"], f"signal {name} keyframe time")
            if at < 0 or at > duration or (previous is not None and at <= previous):
                raise ScenarioError(f"signal {name} keyframe times must increase within the scenario")
            _decimal(frame["value"], f"signal {name} keyframe value")
            previous = at
        if Decimal(str(frames[0]["at_seconds"])) != 0:
            raise ScenarioError(f"signal {name} keyframes must begin at 0 seconds")
        return
    if kind == "sine":
        center = _decimal(behavior.get("center"), f"signal {name}.center")
        amplitude = _decimal(behavior.get("amplitude"), f"signal {name}.amplitude")
        period = _decimal(behavior.get("period_seconds"), f"signal {name}.period_seconds")
        if period <= 0:
            raise ScenarioError(f"signal {name} period_seconds must be greater than zero")
        phase = _decimal(behavior.get("phase_radians", 0), f"signal {name}.phase_radians")
        if not all(math.isfinite(float(value)) for value in (center, amplitude, period, phase)):
            raise ScenarioError(f"signal {name} sine parameters must be finite machine numbers")
        return
    raise ScenarioError(
        f"signal {name} has unsupported type {kind!r}; use constant, explicit, "
        "sweep, triangle, sequence, keyframes, or sine"
    )


def _behavior_bounds(name, behavior):
    kind = behavior["type"]
    if kind in ("constant", "explicit"):
        return (behavior["value"],)
    if kind == "sweep":
        return (behavior["start"], behavior["end"])
    if kind == "triangle":
        return (behavior["minimum"], behavior["maximum"])
    if kind == "sequence":
        return tuple(behavior["values"])
    if kind == "keyframes":
        return tuple(frame["value"] for frame in behavior["keyframes"])
    if kind == "sine":
        center = _decimal(behavior["center"], f"{name}.center")
        amplitude = abs(_decimal(behavior["amplitude"], f"{name}.amplitude"))
        return (center - amplitude, center + amplitude)
    raise ScenarioError(f"unsupported behavior type for {name}: {kind}")


def validate_scenario(data):
    if not isinstance(data, dict):
        raise ScenarioError("scenario root must be a JSON object")
    required = ("name", "workload_class", "duration_seconds", "tick_ms", "can_bitrate", "profile", "signals")
    missing = [key for key in required if key not in data]
    if missing:
        raise ScenarioError(f"scenario is missing required fields: {', '.join(missing)}")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise ScenarioError("scenario name must be a nonempty string")
    if not isinstance(data["workload_class"], str) or data["workload_class"] not in WORKLOAD_CLASSES:
        raise ScenarioError("workload_class must be one of P0 through P6")
    duration = _decimal(data["duration_seconds"], "duration_seconds")
    if not 0 < duration <= MAX_DURATION_SECONDS:
        raise ScenarioError(f"duration_seconds must be in (0, {MAX_DURATION_SECONDS}]")
    tick_ms = data["tick_ms"]
    if isinstance(tick_ms, bool) or not isinstance(tick_ms, int) or not 1 <= tick_ms <= 60_000:
        raise ScenarioError("tick_ms must be an integer from 1 through 60000")
    duration_ms = duration * 1000
    if duration_ms % tick_ms != 0:
        raise ScenarioError("duration_seconds must be an exact multiple of tick_ms")
    if not isinstance(data["profile"], str) or data["profile"] not in PROFILES:
        raise ScenarioError(f"unknown frame profile: {data['profile']}")
    bitrate = data["can_bitrate"]
    if isinstance(bitrate, bool) or not isinstance(bitrate, int) or bitrate not in SUPPORTED_BITRATES:
        raise ScenarioError(f"unsupported CAN bitrate: {bitrate}")
    if data["profile"] == "aim" and bitrate != 1_000_000:
        raise ScenarioError("the documented AiM profile requires 1000000 bit/s")
    if data["profile"] == "hondata-motec" and bitrate not in (250_000, 500_000, 1_000_000):
        raise ScenarioError(
            "the documented Hondata/MoTeC profile supports 250000, 500000, "
            "or 1000000 bit/s"
        )
    frame_rate = data.get("frame_rate_hz", DEFAULT_FRAME_RATE_HZ)
    if (
        isinstance(frame_rate, bool)
        or not isinstance(frame_rate, int)
        or not 0 <= frame_rate <= MAX_FRAME_RATE_HZ
    ):
        raise ScenarioError(f"frame_rate_hz must be an integer from 0 through {MAX_FRAME_RATE_HZ}")
    if Decimal(frame_rate) * duration > MAX_GENERATED_FRAMES:
        raise ScenarioError(
            f"scenario exceeds the {MAX_GENERATED_FRAMES}-frame safety limit"
        )
    if frame_rate == 0 and data["workload_class"] != "P0":
        raise ScenarioError("frame_rate_hz=0 is only valid for P0 no-telemetry scenarios")
    signals = data["signals"]
    if not isinstance(signals, dict):
        raise ScenarioError("signals must be a JSON object")
    if not signals and data["workload_class"] != "P0":
        raise ScenarioError("only a P0 scenario may have no signals")
    if signals and data["workload_class"] == "P0":
        raise ScenarioError("P0 no-telemetry scenarios must not define signals")
    all_fields = {
        field.name: spec
        for spec in PROFILES[data["profile"]]["frames"]
        for field in spec.fields
    }
    for name, behavior in signals.items():
        if name not in all_fields:
            raise ScenarioError(f"unsupported signal name: {name}")
        _validate_behavior(name, behavior, duration, tick_ms)
        for value in _behavior_bounds(name, behavior):
            try:
                encode_signals({name: value}, data["profile"])
            except ValueError as exc:
                raise ScenarioError(f"signal {name} has an unencodable value: {exc}") from exc

    active_specs = []
    signals_by_frame = {}
    for spec in PROFILES[data["profile"]]["frames"]:
        names = tuple(field.name for field in spec.fields)
        selected = tuple(name for name in names if name in signals)
        if selected:
            missing_fields = [name for name in names if name not in signals]
            if missing_fields:
                raise ScenarioError(
                    f"frame 0x{spec.can_id:03X} requires explicit values for all fields; "
                    f"missing {', '.join(missing_fields)}"
                )
            active_specs.append(spec)
            signals_by_frame[spec.can_id] = names

    if data["workload_class"] == "P1" and any(name in PUBLISHABLE_SIGNALS for name in signals):
        raise ScenarioError("P1 must contain decoded signals that are not PowerTune-mapped")
    if data["workload_class"] in ("P2", "P6") and not (set(signals) & PUBLISHABLE_SIGNALS):
        raise ScenarioError(f"{data['workload_class']} must include mapped signals")
    if data["workload_class"] == "P2" and not PUBLISHABLE_SIGNALS.issubset(signals):
        raise ScenarioError("P2 must include RPM, speed, MAP, TPS, and ECT")
    if data["workload_class"] == "P2" and any(
        signals[name]["type"] not in ("constant", "explicit")
        for name in set(signals) & PUBLISHABLE_SIGNALS
    ):
        raise ScenarioError("P2 mapped signals must use constant or explicit behavior")
    if data["workload_class"] == "P5" and len(active_specs) != len(PROFILES[data["profile"]]["frames"]):
        raise ScenarioError("P5 must include every documented frame ID for its profile")

    epsilon = data.get("publication_epsilon", {})
    if not isinstance(epsilon, dict):
        raise ScenarioError("publication_epsilon must be an object")
    for name, value in epsilon.items():
        if name not in PUBLISHABLE_SIGNALS or name not in signals:
            raise ScenarioError(f"publication_epsilon signal is not mapped in this scenario: {name}")
        if _decimal(value, f"publication_epsilon.{name}") < 0:
            raise ScenarioError("publication_epsilon values must be nonnegative")

    stop_after = data.get("stop_frames_after_seconds", {})
    if not isinstance(stop_after, dict):
        raise ScenarioError("stop_frames_after_seconds must be an object")
    parsed_stops = {}
    active_ids = {spec.can_id for spec in active_specs}
    for key, value in stop_after.items():
        try:
            frame_id = int(key, 0)
        except (TypeError, ValueError):
            raise ScenarioError(f"invalid stopped frame ID: {key}") from None
        if frame_id not in active_ids:
            raise ScenarioError(f"stopped frame 0x{frame_id:X} is not active in this scenario")
        stop_time = _decimal(value, f"stop_frames_after_seconds.{key}")
        if not 0 <= stop_time <= duration:
            raise ScenarioError(f"stop time for frame 0x{frame_id:X} is outside scenario duration")
        parsed_stops[frame_id] = stop_time
    return Scenario(data, tuple(active_specs), signals_by_frame, parsed_stops)


def _encode_frame(spec, values, profile):
    encoded = encode_signals(values, profile)
    match = next(frame for frame in encoded if frame.can_id == spec.can_id)
    return CanFrame(match.can_id, match.data, match.extended, match.remote)


def iter_scheduled_frames(scenario, frame_rate_hz=None):
    """Yield deterministic virtual-time frames under a synthetic round-robin policy."""
    scenario = scenario if isinstance(scenario, Scenario) else validate_scenario(scenario)
    rate = scenario.frame_rate_hz if frame_rate_hz is None else frame_rate_hz
    if isinstance(rate, bool) or not isinstance(rate, int) or not 0 <= rate <= MAX_FRAME_RATE_HZ:
        raise ScenarioError(f"frame rate must be from 0 through {MAX_FRAME_RATE_HZ} Hz")
    count = int(Decimal(rate) * scenario.duration)
    if count > MAX_GENERATED_FRAMES:
        raise ScenarioError(f"scheduled workload exceeds {MAX_GENERATED_FRAMES} frames")
    if not scenario.active_specs or rate == 0:
        return
    for slot in range(count):
        seconds = Decimal(slot) / Decimal(rate)
        spec = scenario.active_specs[slot % len(scenario.active_specs)]
        stop = scenario.stop_frames_after.get(spec.can_id)
        if stop is not None and seconds >= stop:
            continue
        tick = int(seconds * 1000 // scenario.tick_ms)
        sampled_seconds = Decimal(tick * scenario.tick_ms) / 1000
        values = {
            name: scenario.value_at(name, sampled_seconds)
            for name in scenario.signals_by_frame[spec.can_id]
        }
        frame = _encode_frame(spec, values, scenario.profile)
        frame = CanFrame(
            frame.can_id, frame.data, frame.extended, frame.remote, float(seconds)
        )
        yield frame


def scenario_summary(scenario, frame_rate_hz=None):
    scenario = scenario if isinstance(scenario, Scenario) else validate_scenario(scenario)
    frame_rate = scenario.frame_rate_hz if frame_rate_hz is None else frame_rate_hz
    if isinstance(frame_rate, bool) or not isinstance(frame_rate, int):
        raise ScenarioError("frame rate must be an integer")
    if not 0 <= frame_rate <= MAX_FRAME_RATE_HZ:
        raise ScenarioError(f"frame rate must be from 0 through {MAX_FRAME_RATE_HZ} Hz")
    if Decimal(frame_rate) * scenario.duration > MAX_GENERATED_FRAMES:
        raise ScenarioError(f"scenario exceeds the {MAX_GENERATED_FRAMES}-frame safety limit")
    signals = {}
    for name in scenario.data["signals"]:
        bounds = _behavior_bounds(name, scenario.data["signals"][name])
        signals[name] = {
            "minimum": str(min(_decimal(value, f"{name} bound") for value in bounds)),
            "maximum": str(max(_decimal(value, f"{name} bound") for value in bounds)),
            "mapped_to_powertune": name in POWER_TUNE_IDS,
            "power_tune_identifier": POWER_TUNE_IDS.get(name),
        }
    frame_count = int(Decimal(frame_rate) * scenario.duration)
    return {
        "name": scenario.name,
        "workload_class": scenario.workload_class,
        "description": WORKLOAD_CLASSES[scenario.workload_class],
        "profile": scenario.profile,
        "duration_seconds": str(scenario.duration),
        "tick_ms": scenario.tick_ms,
        "can_bitrate": scenario.can_bitrate,
        "scenario_tick_rate_hz": 1000 / scenario.tick_ms,
        "frame_rate_hz": frame_rate,
        "expected_frame_count": frame_count,
        "frame_ids": [f"0x{spec.can_id:03X}" for spec in scenario.active_specs],
        "signals": signals,
        "unmapped_signals": [
            name for name in scenario.data["signals"] if name not in POWER_TUNE_IDS
        ],
        "unresolved_decoder_assumptions": [
            "packed byte offsets and derived DLCs are not stated in Hondata tables",
            "unsigned temperature/status/analog fields are assumptions",
            "signed ignition uses the decoder's two's-complement assumption",
            "analog raw conversion direction follows the published voltage x 819.2 table",
        ],
        "power_tune_epsilon": {
            name: str(value) for name, value in scenario.publication_epsilon.items()
        },
        "schedule_policy": "synthetic round-robin frame cycle; not hardware-validated K-Pro timing",
    }
