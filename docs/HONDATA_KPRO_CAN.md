# Hondata K-Pro4 CAN output

This document records the manufacturer-published K-Pro4 CAN output tables
used by the independent bridge. Signal definitions below come from Hondata's
official KManager help, not from PowerTuneDigital software or daemon
artifacts.

## Authoritative sources

* [Hondata CAN Output (Hondata and MoTeC)](https://www.hondata.com/help/kmanager/can_output.htm)
* [Hondata CAN Output (AiM)](https://www.hondata.com/help/kmanager/can_output_2.htm)
* [KManager Multiplexer Parameters](https://www.hondata.com/help/kmanager/multiplexer_parameters.htm), which links to both CAN output pages and identifies these as KPro4 options.

The Hondata/MoTeC table specifies 11-bit identifiers, big-endian fields,
selectable 250/500/1000 kbit/s generic output and a stated 100 Hz rate
“cycling through the packets.” MoTeC SDL/ADL is specified at 500 kbit/s.
The AiM table specifies 11-bit identifiers, big-endian fields, 1 Mbit/s, and
the same 100 Hz cycling description. Hondata states that KPro4 has no CAN
termination resistor.

Casey's actual Hondata K-Pro is configured for **1,000,000 bit/s**. Real-
vehicle validation with this ECU must therefore use 1,000,000 bit/s unless
the ECU's CAN configuration is deliberately changed. This actual ECU setting
is separate from the already-qualified 500,000 bit/s Device 0 bench path and
from the synthetic workload fixtures' default bitrate.

The pages list fields in order and give each field's width and conversion,
but do **not** explicitly give byte offsets, per-frame DLC, signedness for
most fields, invalid/reserved encodings, signal value ranges, or a per-ID
update interval. The byte offsets below are derived by packing the listed
fields consecutively in the documented order; displayed DLC is derived from
the sum of those widths. The decoder uses this strict derived DLC and the
documented big-endian order. Hardware verification of those inferred layout
details is outstanding. Only ignition advance is explicitly described as a
signed value; the decoder treats other fields as unsigned pending vendor
clarification. No source-defined signal range or sentinel is claimed.

“100 Hz cycling through the packets” is recorded as Hondata phrases it; it
does not define a separate 100 Hz interval for each CAN identifier.

### Packet layouts and derived DLC

These are not DLC values printed by Hondata. They are the packed payload
lengths derived from the ordered field widths in each page. The following
signal tables use these frame-ID-to-DLC values.

| Profile | CAN ID | Derived DLC | Fields in published order |
|---|---:|---:|---|
| Hondata/MoTeC | `0x660` | 6 | RPM(16), Speed(16), Gear(8), Voltage(8) |
| Hondata/MoTeC | `0x661` | 7 | IAT(16), ECT(16), MIL(8), VTS(8), CL(8) |
| Hondata/MoTeC | `0x662` | 4 | TPS(16), MAP(16) |
| Hondata/MoTeC | `0x663` | 4 | INJ(16), IGN(16) |
| Hondata/MoTeC | `0x664` | 2 | Lambda(16) |
| Hondata/MoTeC | `0x665` | 2 | Knock count(16) |
| Hondata/MoTeC | `0x666` | 4 | Target cam angle(16), Actual cam angle(16) |
| Hondata/MoTeC | `0x667` | 8 | Analog0(16), Analog1(16), Analog2(16), Analog3(16) |
| Hondata/MoTeC | `0x668` | 8 | Analog4(16), Analog5(16), Analog6(16), Analog7(16) |
| Hondata/MoTeC | `0x669` | 4 | Frequency(8), Ethanol content(8), Fuel temperature(16) |
| AiM | `0x5F0` | 7 | RPM(16), TPS(16), Gear(8), Voltage(8), Speed(8) |
| AiM | `0x5F2` | 7 | IAT(16), ECT(16), MIL(8), VTS(8), CL(8) |
| AiM | `0x5F3` | 2 | MAP(16) |
| AiM | `0x5F4` | 4 | INJ(16), IGN(16) |
| AiM | `0x5F6` | 2 | Lambda(16) |
| AiM | `0x5F7` | 2 | Knock count(16) |
| AiM | `0x5FB` | 4 | Target cam angle(16), Actual cam angle(16) |
| AiM | `0x5FC` | 8 | Analog0(16), Analog1(16), Analog2(16), Analog3(16) |
| AiM | `0x667` | 8 | Analog0(16), Analog1(16), Analog2(16), Analog3(16) |
| AiM | `0x668` | 8 | Analog4(16), Analog5(16), Analog6(16), Analog7(16) |
| AiM | `0x669` | 4 | Frequency(8), Ethanol content(8), Fuel temperature(16) |

## Published Hondata/MoTeC catalog

Generic Hondata output is selectable at 250, 500, or 1000 kbit/s. MoTeC
SDL/ADL output is 500 kbit/s. All identifiers below are standard 11-bit.

| CAN ID | Signal (Hondata display name) | Derived byte range | Bits | Conversion / unit | PowerTune mapping |
|---:|---|---:|---:|---|---|
| `0x660` | RPM (`Rpm`) | 0–1 | 16 | raw, rpm | ID 179 → `Dashboard.rpm` (`setrpm`); verified |
| `0x660` | Speed (`Speed`) | 2–3 | 16 | raw, kph | ID 199 → `Dashboard.speed` (`setSpeed`); verified, but receiver ignores it if `ExternalSpeed` is nonzero |
| `0x660` | Gear (`Gear`) | 4 | 8 | raw, gear | None verified |
| `0x660` | Voltage (`Voltage`) | 5 | 8 | raw / 10, V | None verified |
| `0x661` | IAT (`IAT`) | 0–1 | 16 | raw, °C | None verified |
| `0x661` | ECT (`ECT`) | 2–3 | 16 | raw, °C | ID 221 → `Dashboard.Watertemp` (`setWatertemp`); verified |
| `0x661` | MIL (`MIL`) | 4 | 8 | raw status | None verified |
| `0x661` | VTS (`VTS`) | 5 | 8 | raw status | None verified |
| `0x661` | Closed loop (`CL`) | 6 | 8 | raw status | None verified |
| `0x662` | Throttle position (`TPS`) | 0–1 | 16 | raw, % | ID 210 → `Dashboard.TPS` (`setTPS`); verified |
| `0x662` | Manifold pressure (`MAP`) | 2–3 | 16 | raw / 10, kPa | ID 155 → `Dashboard.MAP` (`setMAP`); verified |
| `0x663` | Injector duration (`INJ`) | 0–1 | 16 | raw / 1000, ms | None verified |
| `0x663` | Ignition advance (`IGN`) | 2–3 | 16 | signed raw, degrees | None verified |
| `0x664` | Lambda (`Lambda`) | 0–1 | 16 | 32768 / raw, lambda | None verified |
| `0x665` | Knock count (`Knock count`) | 0–1 | 16 | raw, count | None verified |
| `0x666` | Target cam angle | 0–1 | 16 | raw, degrees | None verified |
| `0x666` | Actual cam angle | 2–3 | 16 | raw, degrees | None verified |
| `0x667` | Analog0 | 0–1 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog1 | 2–3 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog2 | 4–5 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog3 | 6–7 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog4 | 0–1 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog5 | 2–3 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog6 | 4–5 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog7 | 6–7 | 16 | raw / 819.2, V | None verified |
| `0x669` | Frequency (`Frequency`) | 0 | 8 | raw, Hz | None verified |
| `0x669` | Ethanol content | 1 | 8 | raw, % | None verified |
| `0x669` | Fuel temperature | 2–3 | 16 | raw, °C | None verified |

## Published AiM catalog

AiM output is specified at 1 Mbit/s. It uses standard 11-bit identifiers.
The repeated `0x667`–`0x669` entries are part of Hondata's published AiM
table as well.

| CAN ID | Signal (Hondata display name) | Derived byte range | Bits | Conversion / unit | PowerTune mapping |
|---:|---|---:|---:|---|---|
| `0x5F0` | RPM (`Rpm`) | 0–1 | 16 | raw, rpm | ID 179 → `Dashboard.rpm` (`setrpm`); verified |
| `0x5F0` | TPS | 2–3 | 16 | raw, % | ID 210 → `Dashboard.TPS` (`setTPS`); verified |
| `0x5F0` | Gear | 4 | 8 | raw, gear | None verified |
| `0x5F0` | Voltage | 5 | 8 | raw / 10, V | None verified |
| `0x5F0` | Speed | 6 | 8 | raw, kph | ID 199 → `Dashboard.speed` (`setSpeed`); verified, but receiver ignores it if `ExternalSpeed` is nonzero |
| `0x5F2` | IAT | 0–1 | 16 | raw, °C | None verified |
| `0x5F2` | ECT | 2–3 | 16 | raw, °C | ID 221 → `Dashboard.Watertemp` (`setWatertemp`); verified |
| `0x5F2` | MIL | 4 | 8 | raw status | None verified |
| `0x5F2` | VTS | 5 | 8 | raw status | None verified |
| `0x5F2` | Closed loop (`CL`) | 6 | 8 | raw status | None verified |
| `0x5F3` | MAP | 0–1 | 16 | raw / 10, kPa | ID 155 → `Dashboard.MAP` (`setMAP`); verified |
| `0x5F4` | INJ | 0–1 | 16 | raw / 1000, ms | None verified |
| `0x5F4` | IGN | 2–3 | 16 | signed raw, degrees | None verified |
| `0x5F6` | Lambda | 0–1 | 16 | 32768 / raw, lambda | None verified |
| `0x5F7` | Knock count | 0–1 | 16 | raw, count | None verified |
| `0x5FB` | Target cam angle | 0–1 | 16 | raw, degrees | None verified |
| `0x5FB` | Actual cam angle | 2–3 | 16 | raw, degrees | None verified |
| `0x5FC` | Analog0 | 0–1 | 16 | raw / 819.2, V | None verified |
| `0x5FC` | Analog1 | 2–3 | 16 | raw / 819.2, V | None verified |
| `0x5FC` | Analog2 | 4–5 | 16 | raw / 819.2, V | None verified |
| `0x5FC` | Analog3 | 6–7 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog0 | 0–1 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog1 | 2–3 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog2 | 4–5 | 16 | raw / 819.2, V | None verified |
| `0x667` | Analog3 | 6–7 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog4 | 0–1 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog5 | 2–3 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog6 | 4–5 | 16 | raw / 819.2, V | None verified |
| `0x668` | Analog7 | 6–7 | 16 | raw / 819.2, V | None verified |
| `0x669` | Frequency | 0 | 8 | raw, Hz | None verified |
| `0x669` | Ethanol content | 1 | 8 | raw, % | None verified |
| `0x669` | Fuel temperature | 2–3 | 16 | raw, °C | None verified |

The offset/DLC derivations and unsigned interpretations are explicitly
implementation assumptions pending validation; Hondata does not publish
signal value ranges or sentinel encodings on these pages. Raw field capacity
tests are not claims about valid real-world sensor values. Raw lambda zero
cannot be converted by the published reciprocal formula, so the bridge marks
that signal invalid instead of emitting a value.
The signed IGN field is interpreted as a big-endian two's-complement
integer; Hondata identifies it as signed but does not state the signed
integer encoding, so that interpretation also requires validation.

## Decoder and publisher boundary

The architecture is:

```text
SocketCAN / candump replay / deterministic scenario
    -> K-Pro profile decoder (CAN IDs, field layout, units)
    -> typed decoded signal state (value, unit, source ID, time, validity)
    -> separate PowerTune compatibility publisher
    -> UDP identifier,value to 127.0.0.1:45454
    -> existing DashBoard properties and gauges
```

`tools/kpro_can.py` has no SocketCAN, UDP, PowerTune identifier, or QML
dependency. `tools/powertune_udp.py` owns the verified PowerTune mapping and
serialization. No valid/stale/invalid marker exists in the PowerTune UDP
grammar; stale or invalid values are not published, but a dashboard will
continue displaying its last received value because the existing interface
cannot clear or annotate it.

Verified mappings are RPM → 179, speed in kph → 199, MAP in kPa → 155, TPS
percent → 210, and ECT in Celsius → 221. These are source/property-equivalent
mappings, not evidence that a specific car or K-Pro configuration emits those
signals. The existing PowerTune speed setter honors `ExternalSpeed`; when it
is nonzero, identifier 199 does not update the displayed speed. Every other
decoded K-Pro signal remains available to diagnostics/state tracking but is
not sent to PowerTune until a specific compatible identifier and units are
verified.

Publishing is change-driven and uses exact `Decimal` arithmetic so repeated
identical raw samples do not send duplicate records or float-noise updates.
There is no periodic refresh because no PowerTune-side refresh requirement
has been established. A configurable stale timeout marks state stale and
stops later publishing; it does not fabricate zero.

## Synthetic workload encoder and validation status

`tools/kpro_workload.py` uses the decoder's `PROFILES`, `FrameSpec`, and
`FieldSpec` definitions to generate scenario CAN frames; it does not maintain
a second CAN-ID/offset/width/endian/scaling table. The encoder rounds
representable raw values half-up to the nearest wire unit. Every scenario
frame specifies all fields in that packet, so unrequested companion fields
are not silently fabricated as zero. Wire-capacity validation is not a
manufacturer sensor-range claim.

The workload model implements deterministic behavior curves, and the CLI
`tools/kpro-workload.py` uses those generated frames for in-process
decode/publish replay, candump export, or explicit Waveshare bench
transmission. Scenario evaluation ticks and total frame
transmission rate are independent. The synthetic scheduler cycles active
frame IDs round-robin; its default 20 total frames/s, configurable rate, and
200 frames/s ceiling are test-workload policy, not K-Pro timing. The official
Hondata pages state 100 Hz while cycling through packets but do not describe
the per-frame schedule.

Profiles and assumptions remain important: the encoder and decoder share
the current packed-offset/derived-DLC and signedness assumptions documented
above. Encoding test vectors only proves consistency with that decoder; it
does not validate the assumptions against a K-Pro device. See
[`KPRO_SYNTHETIC_WORKLOADS.md`](KPRO_SYNTHETIC_WORKLOADS.md) for scenario
format, fixture list, workload classes, and CLI.

## Input modes and validation status

```sh
python3 tools/kpro-powertune-bridge.py --can-interface canE --diagnostic
python3 tools/kpro-powertune-bridge.py --replay tests/fixtures/hondata/representative.candump --replay-speed 0 --diagnostic
python3 tools/kpro-powertune-bridge.py --scenario tests/fixtures/hondata/acceleration.json --replay-speed 0 --diagnostic
```

SocketCAN mode requires an explicit interface; no interface is assumed by
the reusable decoder or selected automatically. `canE` is the empirically
confirmed P8 interface on this Device 0 only. Classic candump replay and
scenario mode are deterministic and do not require hardware. The scenario
encoder shares the decoder's field definitions. Scenario replay stays
in-process, and the bridge never transmits CAN; live SocketCAN mode is
receive-only.

Unit tests exercise all published profile fields, field-width boundaries,
conversions, endian order, ignition signedness, malformed DLC, lambda-zero
invalidity, unrelated IDs, freshness, stale transitions, duplicate
suppression, UDP mappings/serialization, replay ordering/timing, and explicit
interface selection. Synthetic workload tests additionally cover shared
encode/decode definitions, behavior types, round-trip precision, deterministic
scheduling, fixture export, publication suppression/epsilon, stale frame
stops, invalid-input vectors, and mocked adapter discovery/transmission.

The checked-in replay and scenario fixtures are synthetic test inputs, not
K-Pro captures. They cover representative idle, warm idle, cruise,
acceleration, deceleration, and high-RPM values. Separate edge-case records
exercise lambda-zero invalidity, malformed known-ID DLC, unrelated traffic,
and stale state. Hondata has not published sensor limits or invalid sentinel
values in the cited pages, so the fixtures do not claim manufacturer-valid
sensor minima/maxima or reserved encodings.

**Validation boundary:** source tests and synthetic fixtures do not validate
the inferred offsets/DLCs, unsigned interpretation, timing, K-Pro setup, or
vehicle behavior. Device 0's bidirectional CAN transport (`canE` and
Waveshare USB-CAN-A) and PowerTune's independent UDP presentation path have
now also been exercised end-to-end with a synthetic frame: ID `0x660`,
payload `03 20 00 00 01 78` decoded to RPM 800 and drove the existing gauge
through UDP record `179,800`. No physical CAN transmission was performed for
the workload-tool change. Actual K-Pro output, signal values, and an equipped
vehicle remain unvalidated. Do not connect this telemetry-only prototype to
a vehicle until the inferred layout is checked against manufacturer
clarification or independently captured, safely obtained K-Pro output.
