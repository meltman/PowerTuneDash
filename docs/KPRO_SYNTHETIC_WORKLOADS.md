# Synthetic K-Pro workload tooling

This tooling creates deterministic test telemetry from the same
manufacturer-derived frame and field definitions used by the K-Pro decoder.
It is a bench/software test system, not a K-Pro implementation, calibration,
or vehicle model.

## Evidence and boundaries

Device 0 has validated the end-to-end open integration path using a synthetic
manufacturer-format frame:

```text
CAN ID 0x660
payload 03 20 00 00 01 78
    -> physical Waveshare USB-CAN-A and terminated CAN bench
    -> Device 0 P8 / canE / FlexCAN2
    -> kpro-powertune-bridge
    -> decoded rpm=800, speed_kph=0, gear=1, voltage_v=12.0
    -> PowerTune UDP records 179,800 and 199,0
    -> existing RPM gauge displayed 800 RPM
```

This validates the independent CAN transport, decoder-to-publisher boundary,
UDP receiver, and gauge for that test vector. It does **not** validate actual
K-Pro output, signal layouts against a K-Pro device, or vehicle behavior.
No proprietary ECU daemon, licensing helper, ARM32 compatibility layer, or
MAC-derived activation is involved.

Manufacturer field names, widths, conversions, IDs, endian declaration, and
documented rates are sourced from the official Hondata pages in
[`HONDATA_KPRO_CAN.md`](HONDATA_KPRO_CAN.md). The pages state **100 Hz,
cycling through packets**; they do not state 20 Hz or a per-ID cadence. The
workload tool's default of 20 total CAN frames per second is a configurable,
conservative **synthetic bench schedule**, not a claim about K-Pro timing.
The schedule cycles round-robin through active IDs. Set `frame_rate_hz` in a
scenario or pass `--frame-rate-hz` to change it. Actual per-ID timing remains
unvalidated.

The checked-in synthetic scenarios use **500,000 bit/s** as their qualified
bench default. A scenario's `can_bitrate` is explicit and can be changed in
its JSON, or overridden for physical transmission with `--can-bitrate`.
Bitrate configures the CAN transport only: it does not change scenario signal
values, frame payloads, workload class, or synthetic scheduling semantics.
Casey's actual Hondata K-Pro is configured for **1,000,000 bit/s**; real-
vehicle validation with this ECU must use `--can-bitrate 1000000` (and a
scenario/adapter configuration compatible with it), unless its CAN
configuration is deliberately changed. Do not treat the bench default as
the vehicle's bitrate.

## Scenario format

Scenario JSON is test tooling only; it is not PowerTune dashboard data. A
scenario has these fields:

```json
{
  "name": "steady-cruise",
  "workload_class": "P2",
  "duration_seconds": 30,
  "tick_ms": 50,
  "can_bitrate": 500000,
  "profile": "hondata-motec",
  "frame_rate_hz": 20,
  "signals": {
    "rpm": {"type": "constant", "value": 3000},
    "speed_kph": {"type": "constant", "value": 100},
    "gear": {"type": "constant", "value": 4},
    "voltage_v": {"type": "constant", "value": 14},
    "iat_c": {"type": "constant", "value": 30},
    "ect_c": {"type": "constant", "value": 90},
    "mil": {"type": "constant", "value": 0},
    "vts": {"type": "constant", "value": 0},
    "closed_loop": {"type": "constant", "value": 1},
    "tps_pct": {"type": "constant", "value": 25},
    "map_kpa": {"type": "constant", "value": 65},
    "lambda": {"type": "constant", "value": 1}
  }
}
```

`duration_seconds` must be positive, no greater than one hour, and an exact
multiple of `tick_ms`. `tick_ms` is the scenario evaluation interval; it is
independent of the frame transmission schedule. The profile must be a decoder
profile and bitrate must be one supported by the Waveshare classic-CAN
adapter. `P0` is the only class with no signals and no CAN frames.

Supported signal behaviors:

* `constant` and `explicit`: `{ "type": "...", "value": number }`.
* `sweep`: `{ "type": "sweep", "start": number, "end": number }`, linearly
  interpolated from zero to scenario duration.
* `triangle`: `minimum`, `maximum`, `period_seconds`, and optional
  `phase_seconds`; sweeps up and down over one period.
* `sequence`: nonempty `values`, optional positive integer `hold_ticks`
  (default 1); holds each value and then holds the final value.
* `keyframes`: ordered `{ "at_seconds": number, "value": number }` entries
  beginning at zero; `interpolation` is `linear` or `step`.
* `sine`: `center`, `amplitude`, `period_seconds`, and optional
  `phase_radians`.

All values must be finite and encodable by the shared decoder field
definitions. Integer raw values are rounded half-up to the nearest
representable unit, so decoded values differ by at most half a raw unit for
linear conversions. Reciprocal lambda follows its documented raw conversion;
zero or unencodable values are rejected. There are no claimed vendor sensor
limits or reserved-value semantics. Every field in a scheduled frame must be
specified; the generator does not silently fill companion fields with zero.

`stop_frames_after_seconds` may map active frame IDs (for example `"0x661"`)
to a time; it models missing traffic for stale-state tests. Optional
`publication_epsilon` maps published signal names to nonnegative material
change thresholds. The publisher compares against the last published value;
below-threshold samples do not send another UDP record.

Safety limits: frame rate is at most 200 total frames/second, duration at
most one hour, and a scenario may generate at most 200,000 frames. The frame
rate limit applies to physical transmit as well as export and replay.

## Workload classes

| Class | Purpose | Expected display-side effect |
|---|---|---|
| P0 | No telemetry; baseline | No CAN frames and no bridge input |
| P1 | Decoded but unmapped traffic | Decoder work; no PowerTune UDP records |
| P2 | Constant mapped values | Initial mapped records only; identical updates suppressed |
| P3 | Slowly changing mapped values | Low-rate material value updates |
| P4 | Multi-phase synthetic drive | Idle/cruise/acceleration/deceleration signal scaling |
| P5 | Maximum synthetic stress | All ten Hondata/MoTeC IDs, up to 200 total frames/s |
| P6 | Display-static, bus-noisy | Repeated CAN with unchanged or sub-threshold mapped values |

P4 scenarios are scripted deterministic telemetry, not physically accurate
K-Pro calibration. P5 is deliberately bounded. P6 is intended to expose
unnecessary display-side activity when CAN frames arrive but displayed
values do not materially change.

## Fixtures

* `idle-baseline.json` — warm idle and closed throttle/load values.
* `warm-idle-variation.json` — triangle RPM/MAP and small voltage variation.
* `steady-cruise.json` — unchanged mapped values for P2.
* `slow-change.json` — gradual RPM changes for P3.
* `acceleration-workload.json` — coordinated rising RPM/speed/load and
  scripted injector, ignition, and lambda values.
* `deceleration.json` — coordinated falling RPM/speed/throttle/load/injector.
* `unmapped-decode.json` — changing knock-count traffic for P1.
* `constant-mapped.json` — P2 mapped-value suppression baseline.
* `maximum-activity.json` — all ten documented Hondata/MoTeC IDs at the
  maximum bounded synthetic total rate.
* `display-static-noisy.json` — P6 sub-threshold changes followed by material
  RPM/speed changes.
* `stale-data.json` — frame `0x661` stops after one second.
* `no-telemetry.json` — P0 baseline.
* `invalid-input.json` — test-only malformed/edge vectors, not a capture.

The existing `acceleration.json`, `representative.candump`, and
`edge_cases.candump` are retained as bridge fixtures. They are separate from
the scenario workload format.

## Commands

Inspect a scenario, including sampled value ranges, frame IDs, mapped signal
IDs, and assumptions:

```sh
python3 tools/kpro-workload.py inspect \
  --scenario tests/fixtures/hondata/steady-cruise.json
```

Replay generated frames through the actual decoder and publisher in-process.
Use `--no-udp` for software-only checks without contacting PowerTune; omit it
to send normalized records to localhost port 45454:

```sh
python3 tools/kpro-workload.py replay \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --no-udp --diagnostic --summary
```

Export deterministic candump text accepted by
`kpro-powertune-bridge.py --replay`:

```sh
python3 tools/kpro-workload.py export \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --output /tmp/acceleration-workload.candump
python3 tools/kpro-powertune-bridge.py \
  --replay /tmp/acceleration-workload.candump --replay-speed 0 --summary
```

Generate direct-UDP controls from the mapped, decoder-produced values and
timestamps in the source K-Pro scenarios. These generated event fixtures are
derived outputs; do not maintain a second hand-authored signal trajectory:

```sh
python3 tools/kpro-workload.py udp-control \
  --scenario tests/fixtures/hondata/slow-change.json \
  --output tests/fixtures/udp/direct-p3-profile-control.json
python3 tools/kpro-workload.py udp-control \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --output tests/fixtures/udp/direct-p4-acceleration-control.json
python3 tools/powertune-udp-sim.py \
  --scenario tests/fixtures/udp/direct-p3-profile-control.json
```

Timed direct controls retain the source scenario duration and emit each
PowerTune identifier/value event at its absolute scenario offset. Equivalence
tests ensure the generated controls match the decoder/publisher values and
publication timing.

Explicitly transmit over the Waveshare adapter (this sends physical CAN;
requires an authorized, terminated bench and is not part of static tests):

```sh
python3 tools/kpro-workload.py transmit \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --can-bitrate 500000 --device /dev/ttyUSB3 --summary
```

Without `--device`, the utility reuses `pt-usb-can.py` discovery for VID:PID
`1a86:7523` and refuses to guess if multiple adapters match. It never assumes
a tty number, configures a Linux CAN interface, writes
`/etc/network/interfaces`, or changes PowerTune settings. Physical send uses
the Waveshare protocol and requires Python 3, `pyserial`, CH341 support, and
permission to access the selected serial device. Software-only inspect,
replay, and export need Python 3 standard library only.

`--diagnostic` is bounded signal-change output. `--summary` prints a compact
JSON record containing elapsed time, generated/transmitted/received frames,
decoded/ignored/malformed frames, signal updates and changes, unchanged
publication suppression, UDP sends, stale/invalid transitions, and effective
rates. A replay run's generated and received frame counts are known; transmit
mode reports generated/transmitted counts but cannot report downstream
decoder/UDP metrics unless the bridge is separately run and its `--summary`
is captured. The bridge's own `--summary` reports bounded receive-side counts.

The CLI and all unit tests use fake sockets/adapters where appropriate; no
physical CAN transmission is performed by tests.
