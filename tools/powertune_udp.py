"""PowerTune compatibility publishing, separate from K-Pro decoding."""

from decimal import Decimal
from typing import Dict, Optional, Tuple


POWER_TUNE_IDS = {
    # Verified against udpreceiver.cpp and the corresponding DashBoard setters.
    "rpm": 179,
    "speed_kph": 199,
    "map_kpa": 155,
    "tps_pct": 210,
    "ect_c": 221,
}


def format_numeric(value):
    value = Decimal(value)
    if not value.is_finite():
        raise ValueError("PowerTune UDP values must be finite numbers")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class PowerTunePublisher:
    """Serializes mapped, valid signals and suppresses unchanged values."""

    def __init__(
        self,
        sendto,
        destination: Tuple[str, int] = ("127.0.0.1", 45454),
        identifier_map=None,
        epsilon=None,
    ):
        self.sendto = sendto
        self.destination = destination
        self.identifier_map = dict(
            POWER_TUNE_IDS if identifier_map is None else identifier_map
        )
        self.epsilon = {
            name: Decimal(str(value)) for name, value in (epsilon or {}).items()
        }
        self.last_published: Dict[str, Decimal] = {}

    def serialize(self, signal):
        if not signal.valid or signal.value is None:
            return None
        identifier = self.identifier_map.get(signal.name)
        if identifier is None:
            return None
        return f"{identifier},{format_numeric(signal.value)}".encode("ascii")

    def publish(self, signal):
        packet = self.serialize(signal)
        if packet is None:
            return None
        value = Decimal(signal.value)
        previous = self.last_published.get(signal.name)
        threshold = self.epsilon.get(signal.name, Decimal(0))
        if previous is not None and abs(value - previous) <= threshold:
            return None
        self.sendto(packet, self.destination)
        self.last_published[signal.name] = value
        return packet
