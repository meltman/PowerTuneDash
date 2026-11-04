"""Pure data decoder for the published Hondata K-Pro4 CAN tables."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


HONDATA_MOTEC_SOURCE = "https://www.hondata.com/help/kmanager/can_output.htm"
AIM_SOURCE = "https://www.hondata.com/help/kmanager/can_output_2.htm"


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes
    extended: bool = False
    remote: bool = False
    timestamp: Optional[float] = None


@dataclass(frozen=True)
class FieldSpec:
    name: str
    bits: int
    unit: str
    divisor: Decimal = Decimal(1)
    reciprocal: bool = False
    signed: bool = False
    source_name: str = ""

    @property
    def byte_width(self):
        return self.bits // 8


@dataclass(frozen=True)
class FrameSpec:
    can_id: int
    fields: Tuple[FieldSpec, ...]
    profile: str

    @property
    def derived_dlc(self):
        return sum(field.byte_width for field in self.fields)


@dataclass(frozen=True)
class DecodedSignal:
    name: str
    value: Optional[Decimal]
    unit: str
    can_id: int
    valid: bool = True
    invalid_reason: str = ""


@dataclass
class SignalState:
    value: Optional[Decimal]
    unit: str
    can_id: Optional[int]
    source_timestamp: Optional[float]
    last_update: float
    validity: str = "valid"


class FrameDecodeError(ValueError):
    pass


def _field(name, bits, unit, divisor="1", reciprocal=False, signed=False, source=""):
    return FieldSpec(
        name=name,
        bits=bits,
        unit=unit,
        divisor=Decimal(divisor),
        reciprocal=reciprocal,
        signed=signed,
        source_name=source or name,
    )


def _common_temperatures():
    return (
        _field("iat_c", 16, "degC", source="IAT"),
        _field("ect_c", 16, "degC", source="ECT"),
        _field("mil", 8, "status", source="MIL"),
        _field("vts", 8, "status", source="VTS"),
        _field("closed_loop", 8, "status", source="CL"),
    )


def _analog_fields(first):
    return tuple(
        _field(f"analog{index}", 16, "V", divisor="819.2", source=f"Analog{index}")
        for index in range(first, first + 4)
    )


def _frame(can_id, profile, *fields):
    return FrameSpec(can_id, tuple(fields), profile)


HONDATA_MOTEC_FRAMES = (
    _frame(
        0x660, "hondata-motec",
        _field("rpm", 16, "rpm", source="Rpm"),
        _field("speed_kph", 16, "kph", source="Speed"),
        _field("gear", 8, "gear", source="Gear"),
        _field("voltage_v", 8, "V", divisor="10", source="Voltage"),
    ),
    _frame(0x661, "hondata-motec", *_common_temperatures()),
    _frame(
        0x662, "hondata-motec",
        _field("tps_pct", 16, "%", source="TPS"),
        _field("map_kpa", 16, "kPa", divisor="10", source="MAP"),
    ),
    _frame(
        0x663, "hondata-motec",
        _field("injector_ms", 16, "ms", divisor="1000", source="INJ"),
        _field("ignition_deg", 16, "deg", signed=True, source="IGN"),
    ),
    _frame(
        0x664, "hondata-motec",
        _field("lambda", 16, "lambda", reciprocal=True, source="Lambda"),
    ),
    _frame(
        0x665, "hondata-motec",
        _field("knock_count", 16, "count", source="Knock count"),
    ),
    _frame(
        0x666, "hondata-motec",
        _field("target_cam_deg", 16, "deg", source="Target cam angle"),
        _field("actual_cam_deg", 16, "deg", source="Actual cam angle"),
    ),
    _frame(0x667, "hondata-motec", *_analog_fields(0)),
    _frame(0x668, "hondata-motec", *_analog_fields(4)),
    _frame(
        0x669, "hondata-motec",
        _field("frequency_hz", 8, "Hz", source="Frequency"),
        _field("ethanol_pct", 8, "%", source="Ethanol content"),
        _field("fuel_temp_c", 16, "degC", source="Fuel temperature"),
    ),
)

AIM_FRAMES = (
    _frame(
        0x5F0, "aim",
        _field("rpm", 16, "rpm", source="Rpm"),
        _field("tps_pct", 16, "%", source="TPS"),
        _field("gear", 8, "gear", source="Gear"),
        _field("voltage_v", 8, "V", divisor="10", source="Voltage"),
        _field("speed_kph", 8, "kph", source="Speed"),
    ),
    _frame(0x5F2, "aim", *_common_temperatures()),
    _frame(
        0x5F3, "aim",
        _field("map_kpa", 16, "kPa", divisor="10", source="MAP"),
    ),
    _frame(
        0x5F4, "aim",
        _field("injector_ms", 16, "ms", divisor="1000", source="INJ"),
        _field("ignition_deg", 16, "deg", signed=True, source="IGN"),
    ),
    _frame(
        0x5F6, "aim",
        _field("lambda", 16, "lambda", reciprocal=True, source="Lambda"),
    ),
    _frame(
        0x5F7, "aim",
        _field("knock_count", 16, "count", source="Knock count"),
    ),
    _frame(
        0x5FB, "aim",
        _field("target_cam_deg", 16, "deg", source="Target cam angle"),
        _field("actual_cam_deg", 16, "deg", source="Actual cam angle"),
    ),
    _frame(0x5FC, "aim", *_analog_fields(0)),
    _frame(0x667, "aim", *_analog_fields(0)),
    _frame(0x668, "aim", *_analog_fields(4)),
    _frame(
        0x669, "aim",
        _field("frequency_hz", 8, "Hz", source="Frequency"),
        _field("ethanol_pct", 8, "%", source="Ethanol content"),
        _field("fuel_temp_c", 16, "degC", source="Fuel temperature"),
    ),
)

PROFILES = {
    "hondata-motec": {
        "frames": HONDATA_MOTEC_FRAMES,
        "source": HONDATA_MOTEC_SOURCE,
        "bitrate": "250, 500, or 1000 kbit/s (generic); 500 kbit/s (MoTeC)",
    },
    "aim": {
        "frames": AIM_FRAMES,
        "source": AIM_SOURCE,
        "bitrate": "1000 kbit/s",
    },
}


def _raw_value(field, raw):
    if field.reciprocal:
        if raw == 0:
            return None
        return Decimal(32768) / Decimal(raw)
    return Decimal(raw) / field.divisor


def decode_frame(frame, profile="hondata-motec"):
    """Decode a documented packet; field positions/DLC derive from table order."""
    if profile not in PROFILES:
        raise ValueError(f"unknown K-Pro profile: {profile}")
    if frame.extended or frame.remote:
        return []
    spec = next(
        (item for item in PROFILES[profile]["frames"] if item.can_id == frame.can_id),
        None,
    )
    if spec is None:
        return []
    if len(frame.data) != spec.derived_dlc:
        raise FrameDecodeError(
            f"CAN ID 0x{frame.can_id:03X} requires derived DLC "
            f"{spec.derived_dlc}, received {len(frame.data)}"
        )

    signals = []
    offset = 0
    for field in spec.fields:
        end = offset + field.byte_width
        raw = int.from_bytes(frame.data[offset:end], "big", signed=field.signed)
        value = _raw_value(field, raw)
        signals.append(
            DecodedSignal(
                name=field.name,
                value=value,
                unit=field.unit,
                can_id=frame.can_id,
                valid=value is not None,
                invalid_reason="raw lambda is zero" if value is None else "",
            )
        )
        offset = end
    return signals


def encode_signals(values: Mapping[str, object], profile="hondata-motec"):
    """Encode documented field values into one packet per affected CAN ID.

    This is for deterministic simulation and fixtures only; it sends no CAN.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown K-Pro profile: {profile}")
    frames = []
    remaining = dict(values)
    for spec in PROFILES[profile]["frames"]:
        selected = {field.name: remaining[field.name] for field in spec.fields
                    if field.name in remaining}
        if not selected:
            continue
        data = bytearray()
        for field in spec.fields:
            raw = _encode_raw(field, selected[field.name]) if field.name in selected else 0
            minimum = -(1 << (field.bits - 1)) if field.signed else 0
            maximum = (1 << (field.bits - (1 if field.signed else 0))) - 1
            if not minimum <= raw <= maximum:
                raise ValueError(f"{field.name} raw value is outside its {field.bits}-bit range")
            data.extend(raw.to_bytes(field.byte_width, "big", signed=field.signed))
            remaining.pop(field.name, None)
        frames.append(CanFrame(spec.can_id, bytes(data)))
    if remaining:
        names = ", ".join(sorted(remaining))
        raise ValueError(f"signals are not defined by profile {profile}: {names}")
    return frames


def _encode_raw(field, value):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field.name} must be a decimal number") from exc
    if not value.is_finite():
        raise ValueError(f"{field.name} must be a finite number")
    if field.reciprocal:
        if value <= 0:
            raise ValueError(f"{field.name} must be greater than zero")
        raw = Decimal(32768) / value
    else:
        raw = value * field.divisor
    if raw != raw.to_integral_value():
        raise ValueError(f"{field.name} value does not map to an integer raw value")
    return int(raw)


class SignalTracker:
    """Tracks decoded value/freshness without knowing PowerTune identifiers."""

    def __init__(self, profile="hondata-motec"):
        if profile not in PROFILES:
            raise ValueError(f"unknown K-Pro profile: {profile}")
        self.profile = profile
        self.states: Dict[str, SignalState] = {}

    def get_state(self, name, now=0.0):
        state = self.states.get(name)
        if state is not None:
            return state
        for frame in PROFILES[self.profile]["frames"]:
            for field in frame.fields:
                if field.name == name:
                    return SignalState(
                        value=None,
                        unit=field.unit,
                        can_id=frame.can_id,
                        source_timestamp=None,
                        last_update=now,
                        validity="unavailable",
                    )
        raise KeyError(f"signal is not defined by profile {self.profile}: {name}")

    def update(self, signal, now, source_timestamp=None):
        previous = self.states.get(signal.name)
        changed = (
            previous is None
            or previous.validity != ("valid" if signal.valid else "invalid")
            or previous.value != signal.value
        )
        self.states[signal.name] = SignalState(
            value=signal.value,
            unit=signal.unit,
            can_id=signal.can_id,
            source_timestamp=source_timestamp,
            last_update=now,
            validity="valid" if signal.valid else "invalid",
        )
        return changed

    def mark_stale(self, now, stale_after):
        transitions = []
        for name, state in self.states.items():
            if state.validity == "valid" and now - state.last_update > stale_after:
                state.validity = "stale"
                transitions.append(name)
        return transitions
