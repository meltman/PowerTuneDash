# USB-CAN-A Bench Testing

This is a stand-alone bench procedure for the external Waveshare USB-CAN-A.
It does not change PowerTuneDash CAN setup, ECU selection, daemon selection,
or networking behavior. `pt-usb-can.py` speaks the adapter's serial-to-CAN
protocol directly; it does not use SLCAN, SocketCAN, or CAN FD.

## Device 0 hardware

The validated Device 0 configuration has:

* The P8 path used for this bench is empirically confirmed as `canE`, backed
  by FlexCAN2 at `308d0000.can`.
* `canC` (`308c0000.can`) is a different SoC controller and did not correspond
  to the tested P8 path. Interface presence alone does not establish that a
  physical transceiver is connected to that interface.
* An external Waveshare USB-CAN-A with USB VID:PID `1a86:7523`, using the
  CH341 driver. Its current tty was `/dev/ttyUSB0`; this is not stable and
  must not be assumed. The EC25 modem also consumes ttyUSB interfaces.

A Linux CAN interface existing in software does not prove that a physical
CAN transceiver is populated. See [IMX8_PORT.md](IMX8_PORT.md) for the broader
Device 0 platform baseline.

## Waveshare protocol and provenance

`tools/pt-usb-can.py` is an independent bench utility based on Waveshare's
published materials:

* [USB-CAN-A Linux documentation](https://www.waveshare.com/wiki/USB-CAN-A)
* [USB-CAN-A Linux C demo ZIP](https://files.waveshare.com/wiki/USB-CAN-A/Demo/USB-CAN-A.zip)
* [Secondary Development—Serial Conversion Definition of CAN Protocol](https://www.waveshare.com/wiki/Secondary_Development_Serial_Conversion_Definition_of_CAN_Protocol)

The tool uses the variable-length serial protocol. Serial defaults to
2,000,000 baud, 8 data bits, one stop bit, and no parity. The 20-byte setup
command selects variable-length communication (`0x12`), the requested CAN
bitrate, standard or extended frame selection, zero filter/block IDs, normal
mode, enabled automatic retransmission, reserved zero bytes, and the
documented low-byte checksum. Data packets use `0xAA`, a type/DLC byte,
little-endian 2-byte standard or 4-byte extended CAN ID, payload bytes, and
`0x55`. The implementation does not change the adapter's persistent serial
baud setting. The protocol page specifies 8N1, while the published Linux C
demo configures two stop bits; this utility follows the protocol page, and
the serial framing choice still needs physical validation.

Supported classic-CAN bitrates are 1,000,000; 800,000; 500,000; 400,000;
250,000; 200,000; 125,000; 100,000; 50,000; 20,000; 10,000; and 5,000 bit/s.
The default is 500,000 bit/s. CAN FD is not supported.

## Utility commands

Run from the repository root:

```sh
python3 tools/pt-usb-can.py discover
python3 tools/pt-usb-can.py send --can-bitrate 500000 --id 123 --data DEADBEEF
python3 tools/pt-usb-can.py receive --can-bitrate 500000
```

`discover` lists adapters matching USB VID:PID `1a86:7523`. Send/receive
automatically use the sole matching adapter, if exactly one exists. If none
exist, the tool reports that; if multiple exist, it lists the candidates and
requires explicit selection, for example `--device /dev/ttyUSB3`. Tty names
are discovered at runtime, never hard-coded.

`--id` is hexadecimal, with or without a `0x` prefix. Standard IDs are limited
to `0x7ff`; extended IDs are limited to `0x1fffffff` and use `--extended`.
`--data` accepts zero through eight bytes as an even-length hexadecimal
string; omitting it sends a zero-length data frame. For example:

```sh
python3 tools/pt-usb-can.py send --can-bitrate 500000 --id 456 --data CAFEBABE
python3 tools/pt-usb-can.py send --can-bitrate 500000 --extended --id 1234567 --data DEADBEEF
```

Receive defaults to standard-frame setup. Specify `--frame-type extended` to
configure the adapter for extended frames. Received output includes a local
timestamp, frame type, CAN ID, DLC, and payload. Ctrl-C closes the serial port.
Received remote frames are identified and displayed with their DLC and no
payload; sending remote frames is not exposed by this initial utility.
The optional `--serial-baud` changes only the host serial-port setting for
diagnostics; its default is Waveshare's documented 2,000,000 baud.

The utility needs Python 3 and `pyserial` (Yocto package commonly named
`python3-pyserial`). The account running it must have permission to access
the adapter's tty, and the kernel must provide CH341 support for this adapter.
The qualification procedure additionally uses `ip` from `iproute2` and
`candump`/`cansend` from `can-utils`, plus the target's SocketCAN/FlexCAN
support for the selected interface (`canE` on the validated Device 0 P8 path).
This task does not add packages or the tool to the
PowerTuneDash runtime image.

## Bench electrical setup

On Device 0, the onboard CAN connector is:

```text
IOT-GATE P8 pin 4 = CAN_H
IOT-GATE P8 pin 2 = CAN_L
IOT-GATE P8 pin 5 = ISO_GND_1
```

Use a twisted CAN_H/CAN_L pair and 120-ohm termination at each physical end
of the bench bus. The completed, unpowered harness measured approximately
60.4 ohms between CAN_H and CAN_L. Keep the Waveshare onboard 120-ohm
termination **disabled** with this harness; enabling it would make three
terminators on the bus.

## Validated bidirectional bench and qualification procedure

Device 0 has validated the bidirectional bench at 500,000 bit/s using the
Waveshare adapter, `pt-usb-can`, the terminated twisted-pair harness, and
`canE`. The P8-to-interface mapping is empirical for this unit; do not infer
it on other hardware.

### Waveshare to `canE`

Configure the Linux CAN interface explicitly:

```sh
ip link set canE down
ip link set canE type can bitrate 500000
ip link set canE up
candump canE
```

In another terminal, confirm adapter discovery and transmit the test frame:

```sh
python3 tools/pt-usb-can.py discover
python3 tools/pt-usb-can.py send --can-bitrate 500000 --id 123 --data DEADBEEF
```

Expected and observed `candump canE` frame:

```text
123#DEADBEEF
```

### `canE` to Waveshare

Start the adapter receiver:

```sh
python3 tools/pt-usb-can.py receive --can-bitrate 500000
```

From another terminal, send on `canE`:

```sh
cansend canE 456#CAFEBABE
```

Observed decoded adapter output includes:

```text
Standard data ID 0x456 DLC 4 payload CA FE BA BE
```

## K-Pro synthetic workload integration

This end-to-end synthetic frame has been validated on Device 0, not captured
from a K-Pro. ID `0x660` with payload `03 20 00 00 01 78` passed through
Waveshare, the terminated P8/`canE` bus, the bridge, and the UDP receiver;
decoded RPM was 800 and the existing gauge displayed 800 RPM. This validates
the open integration path for this vector only, not K-Pro output or vehicle
behavior.

The Device 0 bench qualification above uses 500,000 bit/s. Casey's actual
Hondata K-Pro is configured for **1,000,000 bit/s**; real-vehicle validation
with that ECU must use 1,000,000 bit/s on the CAN bus unless its ECU
configuration is deliberately changed. The 500,000 bit/s workload fixture
and bench examples are not evidence of the K-Pro's configured vehicle rate.
The synthetic workload's signal and frame-generation semantics do not depend
on bitrate; `can_bitrate` selects the transport rate, and is configurable per
scenario or with the CLI override. Do not transmit synthetic workloads on a
connected ECU or vehicle.

With `canE` configured as above and `candump canE` confirming the bus, start
the bridge in another terminal:

```sh
python3 tools/kpro-powertune-bridge.py --can-interface canE --profile hondata-motec --diagnostic
```

In the Waveshare terminal, transmit the synthetic 0x660 layout for 800 rpm,
0 kph, gear 1, and 12.0 V:

```sh
python3 tools/pt-usb-can.py send --can-bitrate 500000 --id 660 --data 032000000178
```

The bridge should decode those fields and show the mapped records `179,800`
and `199,0` in diagnostic output. PowerTune's receiver may ignore identifier
199 when `ExternalSpeed` is nonzero. This test checks the documented bridge
boundary only; it does not validate any signal against a K-Pro device or a
vehicle. Do not treat generated scenario data as a real K-Pro capture.

The deterministic workload CLI drives the same shared encoder in software,
candump export, and physical adapter transmission:

```sh
python3 tools/kpro-workload.py inspect --scenario tests/fixtures/hondata/steady-cruise.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/acceleration-workload.json --no-udp --summary
python3 tools/kpro-workload.py export --scenario tests/fixtures/hondata/acceleration-workload.json --output /tmp/acceleration.candump
```

Physical transmission is an explicit action and is not part of this change's
validation:

```sh
python3 tools/kpro-workload.py transmit \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --can-bitrate 500000 --device /dev/ttyUSB3
```

It reuses the Waveshare USB VID:PID discovery helper, supports `--device` for
explicit selection, and does not assume a tty index. Scenario and frame rates
are independent. Workload scheduling is synthetic, round-robin, default 20
total frames/s and bounded at 200 frames/s; it is not a claim about exact
per-frame K-Pro timing. Inspect all workload classes and fixtures in
[KPRO_SYNTHETIC_WORKLOADS.md](KPRO_SYNTHETIC_WORKLOADS.md), and profiling
comparisons in [PERFORMANCE_PROFILING.md](PERFORMANCE_PROFILING.md).

`pt-usb-can.py` configures only the USB-CAN-A. The operator explicitly
configures the selected Linux CAN interface; neither bench utility invokes
PowerTune's `canbitratesetup()`, writes `/etc/network/interfaces`, assumes
`can0`, `canC`, or `canE`, or alters any PowerTune setting.

## Future integration boundary

The bench transport and synthetic workload tool support this independently
sourced integration flow:

```text
synthetic/documented CAN frames
    -> physical CAN bench
    -> selected SocketCAN interface (validated Device 0 P8 path: canE)
    -> K-Pro profile decoder (prototype; actual K-Pro output unvalidated)
    -> documented PowerTune UDP integration interface
    -> gauge
```

The bridge accepts an explicit CAN interface, classic candump replay, or the
legacy deterministic bridge JSON scenario. The workload CLI also supports
the behavior-based scenario format, software replay, candump export, and
explicit physical transmission through Waveshare. Its synthetic scenario
frames are not vehicle captures. Run software-only tests with:

```sh
python3 tools/kpro-powertune-bridge.py --replay tests/fixtures/hondata/representative.candump --replay-speed 0 --diagnostic
python3 tools/kpro-powertune-bridge.py --scenario tests/fixtures/hondata/acceleration.json --replay-speed 0 --diagnostic
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/maximum-activity.json --no-udp --summary
```

Hondata's official field tables and the prototype's limitations are listed
in [HONDATA_KPRO_CAN.md](HONDATA_KPRO_CAN.md). Do not derive signal
definitions from proprietary daemon implementations. See
[DAEMON_UDP_PROTOCOL.md](DAEMON_UDP_PROTOCOL.md) for the PowerTune-side UDP
interface.

The bridge uses Python 3 standard-library modules only. Live input requires
Linux SocketCAN/FlexCAN support and permission to open the selected interface.
`pt-usb-can.py` separately requires `pyserial` (Yocto package commonly
`python3-pyserial`) and CH341 kernel support. The documented interface setup
and `candump`/`cansend` checks use `iproute2` and `can-utils`. No runtime image
packages are added by this change.

## Waveshare transmit anomaly investigation (1,000,000 bit/s)

Observed on Device 0 (canE, 1 Mbit/s): `canE -> Waveshare` works for
`456#CAFEBABE` and `660#032000000178`; `Waveshare -> canE` works for
`123#DEADBEEF`, but `660#032000000178` raises the canE RX error counter to about
130 and drives canE ERROR-PASSIVE.

### Framing comparison against Waveshare's published protocol

`pt-usb-can send ... --dump-serial-frame` prints the exact configuration and
data bytes without opening the adapter or transmitting. Bytes for each vector
at 1,000,000 bit/s:

| Frame | Bytes written |
|-------|---------------|
| configuration (both) | `AA 55 12 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 14` |
| `123#DEADBEEF` | `AA C4 23 01 DE AD BE EF 55` |
| `660#032000000178` | `AA C6 60 06 03 20 00 00 01 78 55` |

Checked against the published "Serial (USB) to CAN Protocol Conversion" page:

- header `0xAA`; end code `0x55`; no checksum in variable-length data frames;
- type byte `0xC0 | (extended ? 0x20 : 0) | (remote ? 0x10 : 0) | DLC`, so
  DLC 4 -> `C4`, DLC 6 -> `C6`;
- standard ID is two bytes, low byte first (`0x123` -> `23 01`,
  `0x660` -> `60 06`), matching the published `0x123` and `0x103` examples;
- frame length is `1 + 1 + 2 + DLC + 1` for standard frames (9 bytes for DLC 4,
  11 bytes for DLC 6); each data frame is written in a single `write()`;
- configuration is the 20-byte `0x12` variable-protocol command: bitrate
  `0x01` = 1 Mbit/s, frame type `0x01`, mode normal, auto-retransmit `0x00`
  (enabled), checksum = low 8 bits of the sum of bytes 2..18 (`0x14`);
- the published examples (`AA C8 23 01 11..88 55`, `AA C2 03 01 11 22 55`, and
  both extended examples) are encoded as unit tests, plus a table over DLC 0-8
  and IDs `0x000, 0x103, 0x123, 0x456, 0x660, 0x7FF`.

The tool is also unrelated to payload content: nothing treats bytes after
DLC 4 differently, and a six-byte payload produces no off-by-one (length is
computed from the payload, tests cover every DLC). The Waveshare Linux C demo
was not re-examined for short-frame handling in this pass; its fixed 20-byte
protocol is a different mode that `pt-usb-can` does not use.

### Conclusion

No framing defect was found: both vectors are byte-identical to what the
published protocol specifies, and the two vectors differ only in ID, DLC and
payload, all encoded by the same code path. The root cause is therefore **not
established** and is not attributable to `pt-usb-can` serial framing. Facts
that point elsewhere (hypotheses, unproven): the failing frame is the one with
many consecutive zero bits (`00 00` in the payload plus `0x660`'s ID), so a
bit-timing or sample-point mismatch between the adapter's CAN controller and
canE at 1 Mbit/s that only shows on certain stuffing patterns would fit; and
the adapter's auto-retransmit (enabled by default) repeats a frame that is
destroyed on the bus, which would inflate the error counter on a single send.
Receiving from canE works, which does not exercise the adapter's transmitter.

### Smallest controlled Device 0 test matrix

First confirm the bytes on the host: run with `--dump-serial-frame` and compare
to the table. Then, with canE reset (`ip link set canE down/up`) and
`ip -details -statistics link show canE` before and after each row, one send per
row, using `--no-auto-retransmit` (adapter's documented option 0x01; default is
unchanged) to stop repeats from masking or inflating the counters:

| # | Purpose | ID | Data |
|---|---------|----|------|
| 1 | known good baseline | `123` | `DEADBEEF` |
| 2 | ID effect (DLC/payload same as 1) | `660` | `DEADBEEF` |
| 3 | DLC effect (ID same as 1) | `123` | `DEADBEEF0000` |
| 4 | payload effect (ID/DLC same as failing) | `660` | `DEADBEEFDEAD` |
| 5 | failing vector, retransmit disabled | `660` | `032000000178` |
| 6 | zero-run effect (ID same as 1) | `123` | `032000000178` |
| 7 | repeat of 5 at 500000 on both ends | `660` | `032000000178` |

Interpretation: failures following the payload (rows 5-6 but not 2-4) implicate
bit-stuffing/timing; following the ID implicates row 2; row 7 passing with 5
failing implicates 1 Mbit/s bit timing (sample point) of the adapter, canE or
the cabling/termination at that rate. If row 5 still raises the counter by only
a few counts while default auto-retransmit raises it by about 130, the
retransmit loop is the amplifier, not the cause. Do not change canE settings,
K-Pro decoding or PowerTune as part of this matrix.

## Appliance-managed CAN and K-Pro services

Two systemd units (installed and enabled by the `powertunedash` recipe in
`meta-powertune`) own the K-Pro lifecycle:

- `powertune-can.service` (oneshot, `RemainAfterExit`) runs
  `ip link set canE down`, then `type can bitrate 1000000 restart-ms 100`,
  then `up`. It is idempotent across boot and `systemctl restart`; any failing
  step fails the unit with the `ip` error in the journal.
- `powertune-kpro-bridge.service` `Requires=`/`After=` the CAN unit and runs
  `/usr/bin/kpro-powertune-bridge --can-interface canE --profile
  hondata-motec` (no `--diagnostic`), restarting on failure with
  `StartLimitBurst=5` per 60 s.

`powertunedash.service` is independent; UDP lets either process start first.

Validated facts: `canE` is empirically the populated Device 0 P8 CAN
interface; Casey's K-Pro is configured for 1 Mbps; sustained Device 0 ↔
Device 1 FlexCAN testing at 1 Mbps passed with both nodes `ERROR-ACTIVE` and
zero error counters; `ISO_GND_1` was required between the two isolated bench
nodes (with CAN_H and CAN_L). Real K-Pro signal validation remains pending.

### Cold-boot acceptance procedure

1. With the K-Pro-format source (or bench peer) connected, power-cycle Device 0.
2. `systemctl status powertune-can powertune-kpro-bridge powertunedash`:
   CAN unit `active (exited)`, the other two `active (running)`.
3. `ip -details link show canE`: `UP`, `bitrate 1000000`, `restart-ms 100`,
   `ERROR-ACTIVE`.
4. `journalctl -b -u powertune-can -u powertune-kpro-bridge` shows both
   breadcrumbs (`PowerTune CAN: interface=canE bitrate=1000000 ...`,
   `PowerTune K-Pro bridge: interface=canE profile=hondata-motec
   destination=127.0.0.1:45454`) and no per-frame logging.
5. Gauges respond to the bench source over UDP `127.0.0.1:45454`.
6. `kill` the bridge once: it restarts after ~2 s; `systemctl restart
   powertune-can` is repeatable without error.
7. Failure check: set `PT_CAN_INTERFACE` to a nonexistent name, restart the
   CAN unit, confirm a nonzero result and clear journal error; restore it.

## Stationary vehicle diagnostic capture

Device 0 is installed for initial vehicle testing. CAN_H and CAN_L were
initially reversed; correcting polarity produced continuous vehicle CAN
traffic. The known-working Raspberry Pi dashboard showed ECT around 55 °C,
while the i.MX8Plus dashboard did not show the same result. The cause remains
unresolved; this observation does not establish a decoder or documentation
error. The Pi and i.MX8Plus appliances can coexist on the same CAN bus.
Subsequent real-vehicle captures/replays validated `0x661` IAT at 18 °C and
ECT at 25 °C. The bridge emitted `221,25` and Device 0's metric gauge
displayed 25. RPM, TPS, and MAP were also physically validated. Source tracing
identifies IAT as UDP `135` → `setIntaketemp` → `Dashboard.Intaketemp`,
the `Intaketemp` datasource labeled `IAT`; the newly added IAT publication
still requires an on-device gauge check. The cause of the earlier 55 °C
mismatch remains undetermined.
The first real K-Pro capture was lost: `/var/tmp` mapped to volatile tmpfs
on this image, so its archive did not survive shutdown. No analysis or
claims can be made from that missing capture beyond the operator observations
above.

Run while safely stationary, not while driving:

```sh
sudo pt-car-diag --duration 60 --note "Ignition on, engine started at 10s, warm idle, Pi showed ECT 55C"
```

Default duration is 60 seconds; accepted integer range is 5–600. The note is
stored verbatim. The suggested sequence is approximately 0–10 s ignition on,
engine off; 10–30 s idle; 30–45 s two gentle RPM increases; 45–60 s idle.
The output is a private
`/var/lib/powertune/diagnostics/powertune-car-diag-<UTC>.tar.gz` archive.
On the appliance's persistent root filesystem this directory survives
reboot and poweroff; verify that it is not separately mounted on volatile
storage on a different deployment. The collector creates the directory
privately if absent, preserves existing directory permissions, and uses
private working directories and archives. Both the archive and any retained
working directory live there. The archive is flushed and synced before
success is reported.
The tool reads the configured interface, invokes `timeout -s INT <duration>
candump -L <interface>` alongside the existing bridge, and records CAN link
statistics before, near the midpoint, and after. It never sends CAN or UDP,
reconfigures hardware, changes services, or reboots. Nonzero exit means
capture or archive failure; optional collection errors are listed in the
manifest. A failed archive retains the private working directory, whose path
is printed; a partially created archive must not be treated as complete.

Before powering down, use the exact archive path printed by the collector:

```sh
ls -lh /var/lib/powertune/diagnostics/
sudo tar -tzf <archive> | head
sync
```

Replace `<archive>` with that path (without angle brackets). Check the
collector exit status and that the archive listing contains
`can/vehicle.candump` and `manifest.json`; investigate failures before
powering down.

`manifest.json` identifies the requested and actual times, available
configuration, build revision, actual dashboard hash, reference-hash match,
and individual collection results. The archive also contains the operator
note, dashboard copy, sanitized config (unknown values redacted), service
state and processes, CAN capture/status, journal, application log, and socket
information. The reference dashboard hash is informational; vehicle
dashboards need not match. UDP destination is recorded as the bridge's
default, not proof of effective process arguments. `ss` and boot status may
be unavailable, and system journals/logs can contain sensitive data.
Interface, bitrate, and profile are configured values, not independently
verified running-process settings. Compare service properties and CAN state.

On the analysis machine, replace the address and timestamp with actual values:

```sh
scp root@DEVICE0:/var/lib/powertune/diagnostics/powertune-car-diag-20261109T180000Z.tar.gz .
mkdir vehicle-capture
tar -xzf powertune-car-diag-20261109T180000Z.tar.gz -C vehicle-capture
kpro-capture-analyze vehicle-capture/can/vehicle.candump --profile hondata-motec
kpro-powertune-bridge --replay vehicle-capture/can/vehicle.candump --profile hondata-motec --diagnostic --no-udp --replay-speed 0
```

The analyzer reports all parseable observed IDs and DLCs before profile
interpretation, malformed/unexpected frames, value ranges and freshness
transitions at the next timestamped frame. ECT evidence includes assumed
source ID/offset/DLC, observed bytes and changes, signed and unsigned values,
the current decoded Celsius value and explicitly labeled offset hypotheses.
It does not select a hypothesis or modify the decoder. Inspect the archive and
CAN traffic for sensitive or unrelated information before sharing. After
explicit review, a scrubbed capture can become a private regression fixture;
record the source, collection date, profile, wiring, observed Pi value and
physical test sequence. Do not automatically commit raw vehicle captures.
