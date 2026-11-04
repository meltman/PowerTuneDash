# USB-CAN-A Bench Testing

This is a stand-alone bench procedure for the external Waveshare USB-CAN-A.
It does not change PowerTuneDash CAN setup, ECU selection, daemon selection,
or networking behavior. The utility speaks the adapter's serial-to-CAN
protocol directly; it does not use SLCAN, SocketCAN, or CAN FD.

## Device 0 hardware

The validated Device 0 configuration has:

* `canC` mapped to the physically populated onboard FlexCAN controller
  (`308c0000.can`).
* `canE` present as a Linux SoC FlexCAN interface, but the optional physical
  slot-C CAN hardware is not populated on this particular unit.
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
support for `canC`. This task does not add packages or the tool to the
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

## First qualification procedure

These are the qualification steps for Device 0; this source-only change has
not wired the hardware or run them.

### Waveshare to `canC`

Configure the Linux CAN interface explicitly:

```sh
ip link set canC down
ip link set canC type can bitrate 500000
ip link set canC up
candump canC
```

In another terminal, confirm adapter discovery and transmit the test frame:

```sh
python3 tools/pt-usb-can.py discover
python3 tools/pt-usb-can.py send --can-bitrate 500000 --id 123 --data DEADBEEF
```

Expected `candump canC` frame:

```text
123#DEADBEEF
```

### `canC` to Waveshare

Start the adapter receiver:

```sh
python3 tools/pt-usb-can.py receive --can-bitrate 500000
```

From another terminal, send on `canC`:

```sh
cansend canC 456#CAFEBABE
```

Expected decoded adapter output includes:

```text
Standard data ID 0x456 DLC 4 payload CA FE BA BE
```

The utility only configures the USB-CAN-A. The operator explicitly configures
`canC`; the tool does not invoke PowerTune's `canbitratesetup()`, write
`/etc/network/interfaces`, assume `can0`, or alter any PowerTune setting.

## Future integration boundary

The bench transport is intended to support a future, independently sourced
integration flow:

```text
synthetic/documented CAN frames
    -> physical CAN bench
    -> canC
    -> future K-Pro decoder
    -> documented PowerTune UDP integration interface
    -> gauge
```

No Hondata decoder is implemented here. Any future K-Pro signal definitions
must come from official Hondata documentation and/or independently collected
bus observations, not proprietary daemon implementations. See
[DAEMON_UDP_PROTOCOL.md](DAEMON_UDP_PROTOCOL.md) for the PowerTune-side UDP
interface.
