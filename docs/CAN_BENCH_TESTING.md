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

## K-Pro bridge bench integration

The following is a future bench-only qualification sequence, not a K-Pro
capture and not run as part of this source change. It sends a synthetic
manufacturer-table-shaped telemetry frame through the existing Waveshare
bench node; it does not transmit a frame to an ECU or implement ECU control.

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

`pt-usb-can.py` configures only the USB-CAN-A. The operator explicitly
configures the selected Linux CAN interface; neither bench utility invokes
PowerTune's `canbitratesetup()`, writes `/etc/network/interfaces`, assumes
`can0`, `canC`, or `canE`, or alters any PowerTune setting.

## Future integration boundary

The bench transport is intended to support a future, independently sourced
integration flow:

```text
synthetic/documented CAN frames
    -> physical CAN bench
    -> selected SocketCAN interface (validated Device 0 P8 path: canE)
    -> K-Pro profile decoder (prototype; actual K-Pro output unvalidated)
    -> documented PowerTune UDP integration interface
    -> gauge
```

The prototype accepts an explicit CAN interface, classic candump replay, or
a deterministic JSON scenario. It does not transmit CAN. Its scenario frames
are synthesized from the decoder's shared signal definitions and are not
vehicle captures. Run it against the fixtures with:

```sh
python3 tools/kpro-powertune-bridge.py --replay tests/fixtures/hondata/representative.candump --replay-speed 0 --diagnostic
python3 tools/kpro-powertune-bridge.py --scenario tests/fixtures/hondata/acceleration.json --replay-speed 0 --diagnostic
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
