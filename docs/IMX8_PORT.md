# PowerTune i.MX8MP Port

This guide records the current PowerTune appliance architecture and the
validated Device 0 baseline. Hardware observations below describe that target;
they should not be inferred from a developer workstation or a BitBake host.

## Target and runtime layout

The target is the **CompuLab IOT-GATE-IMX8PLUS**, based on the NXP i.MX8MP and
running Yocto Linux. The production dashboard is a Qt 5 application rendered
directly through EGLFS/KMS.

| Role | Linux location |
| --- | --- |
| Application executable | `/usr/bin/powertunedash` |
| Immutable packaged resources | `/usr/share/powertune` |
| System/product configuration | `/etc/powertune` |
| Persistent mutable application and user data | `/var/lib/powertune` |
| Application and NMEA logs | `/var/log/powertune` |
| Packaged helper executables, where needed | `/usr/libexec/powertune` |

`ptpaths.h` defines role-specific path helpers. Windows development keeps the
existing `C:/PowerTune` layout for all these roles.

## Graphics

The validated Device 0 DRM topology is:

```text
/dev/dri/card0       galcore
/dev/dri/card1       imx-drm
card1-HDMI-A-1       HDMI output
```

PowerTune starts as:

```text
/usr/bin/powertunedash -platform eglfs
```

The packaged `/etc/powertune/eglfs.json` explicitly selects `/dev/dri/card1`
and sets `"hwcursor": false`. The hardware cursor path failed on the target;
Qt's software/OpenGL cursor works. Do not change the DRM device selection or
enable the hardware cursor without fresh target validation.

Weston remains in the image, but its service and socket are not started by
default. PowerTune uses direct EGLFS/KMS rather than Weston for its production
display.

## Fonts

Qt/fontconfig integration was needed for usable system-font fallback.
Liberation fonts currently provide functional fallback. PowerTune requests
Eurostile extensively, and UserDash uses Lato; neither font family is
currently supplied by the product image. Typography assets and their
licensing/distribution review remain outstanding. Do not add font files
without resolving that work.

## HDMI audio and warning sounds

Device 0 exposes HDMI playback through ALSA card 0 (`audio-hdmi`), device 0
(`i.MX HDMI i2s-hifi-0`), including `/dev/snd/pcmC0D0p`. Raw playback through
`hw:0,0` failed with the default S16_LE parameters; playback through ALSA's
`plughw:0,0` conversion layer succeeded and was audible through the HDMI
display speakers. PowerTune must leave ALSA device selection and format
negotiation/conversion to Qt and ALSA; it must not hard-code either endpoint
or assume the raw PCM accepts the warning WAV's format.

PowerTune's Qt Multimedia target configuration retains ALSA and disables Qt
Multimedia's PulseAudio feature. The existing RPM, coolant-temperature,
knock, and boost warning sounds use Qt's generic audio output with the ALSA
backend and do not require a PulseAudio server. The application checks once
at startup whether Qt reports a default output and supports its own preferred
format. If not, the warning `SoundEffect` is not instantiated and audio
warnings are a no-op for that session. The check does not prescribe the
warning WAV format or an ALSA hardware device; playback format negotiation
remains with Qt/ALSA. This cached check logs exactly one `qInfo()` diagnostic:
either that warning audio is unavailable for the session, or that it is enabled
with Qt's selected output device name and preferred sample rate, channel count,
sample size/type, and codec. Hardware playback through `plughw:0,0` is validated;
the application warning through the rebuilt Qt ALSA backend still requires
runtime verification. The optional GStreamer media player and camera are
separate features and are not changed by this warning-audio work; their
behavior without an audio server is not established here.

## Dashboard architecture and persistence

The dash selector's values map as follows:

```text
dashselect value 4 -> Userdash1.qml -> datastore1
dashselect value 5 -> Userdash2.qml -> datastore2
dashselect value 6 -> Userdash3.qml -> datastore3
```

The selector distinguishes **visible dashboard slots** from **User Dashboard
definitions**. `numberofdash=2` means three visible slots; the setting is a
zero-based selector index, not a count. The first-run defaults are:

```text
numberofdash=2
dashselect1=4
dashselect2=5
dashselect3=6
dashselect4=0
```

The three UserDash definitions are separate dashboard content. Their working
state is held through QML Settings aliases in `datastore1`, `datastore2`, and
`datastore3`, backed by Qt settings. **Save** persists working state through
QSettings. **Import/Export** reads or writes portable dashboard files instead;
those exports and user dashboard data belong under
`/var/lib/powertune/UserDashboards/`.

The mutable Logo directory is `/var/lib/powertune/Logo/`. The intro Logo is
user-replaceable: it is displayed when `Logo.png` exists and omitted when
absent. Dashboard image fields translate only the exact legacy prefix
`file:///home/pi/Logo/` in memory to the current Logo directory. Loaded source
files are not rewritten; a later normal save/export can persist normalized
URLs. This is a targeted compatibility rule, not a general `/home/pi`
translation.

The current dashboard record and portable-file formats are documented in
[DASHBOARD_SCHEMA.md](DASHBOARD_SCHEMA.md). Save persists JSON through
QSettings, while Export/Import uses separate positional text files; the
per-element schemas are irregular, and historical records remain loadable.
External PNG resource loading and State GIF URL resolution are validated on
Device 0. Animated GIF decoding is not: QML `AnimatedImage` attempts to load
`cat-on.gif` and `cat-off.gif` but reports image-read failures, and target
inspection found no `libqgif.so`. The Qt5 `qtbase` recipe's `gif`
`PACKAGECONFIG` feature was disabled; the product layer now enables it. The
plugin is provided by `qtbase-plugins`, already included in the runtime
packagegroup, at `/usr/lib/plugins/imageformats/libqgif.so`. Actual GIF
rendering still requires validation on Device 0 after an image built with this
configuration is installed.

## Networking

Device 0 uses NetworkManager for normal networking, and the current image
manifest contains NetworkManager, its Wi-Fi plugin, `libnm0`, `nmcli`, QtDBus,
`iw`, and `wpa-supplicant`. PowerTune now has an asynchronous QtDBus
NetworkManager client in source, wired to the Network settings page. The old
fixed-name scanner and supplicant writer are excluded from the application
target. NetworkManager owns persistent Wi-Fi profiles and credentials.

This source change has not been built or validated on Device 0. D-Bus
marshalling/authorization, scanning, connection and disconnection, radio
status, address updates, and password persistence remain unverified. The
`meta-powertune` runtime package group now explicitly depends on
`networkmanager-daemon` and `networkmanager-wifi`. No CAN code or the coupled
`canbitratesetup()` behavior was changed. See
[NETWORKING.md](NETWORKING.md) for implementation details and the Device 0
test matrix.

## CAN bench hardware

The physical IOT-GATE P8 CAN path used in the validated bench is empirically
confirmed as Linux interface `canE`, backed by FlexCAN2 at `308d0000.can`.
`canC` maps to `308c0000.can` and did not correspond to the tested P8 path.
The observed mapping is specific to Device 0; a Linux CAN interface existing
in software does not by itself prove a physical CAN transceiver is populated
or connected to it.

The external Waveshare USB-CAN-A is a separate bench CAN node, identified by
USB VID:PID `1a86:7523` and the CH341 driver. Its tty number is dynamic; it
must be discovered by USB identity and not assumed to be `/dev/ttyUSB0`.
`tools/pt-usb-can.py` uses Waveshare's published serial-to-CAN protocol
directly and does not change PowerTune CAN runtime behavior or configure
Linux CAN interfaces. Device 0 validated 456#CAFEBABE from `canE` to
Waveshare and 123#DEADBEEF from Waveshare to `canE` with an approximately
60.4-ohm completed bus. A synthetic manufacturer-format K-Pro frame
(`0x660#032000000178`) has also been validated end-to-end through `canE`,
the bridge, PowerTune UDP `179,800`, and the existing 800-RPM gauge. This is
synthetic integration evidence, not actual K-Pro or vehicle validation. See
[CAN_BENCH_TESTING.md](CAN_BENCH_TESTING.md) for protocol provenance,
dependencies, the P8 pinout, termination arrangement, CLI, and recorded
bench procedure. K-Pro source limitations and workload tooling are documented
in [HONDATA_KPRO_CAN.md](HONDATA_KPRO_CAN.md) and
[KPRO_SYNTHETIC_WORKLOADS.md](KPRO_SYNTHETIC_WORKLOADS.md).

## GPS and EC25 modem

Validated target hardware includes a Quectel EC25. On Device 0, `/dev/ttyUSB1`
is the GPS/NMEA data port. The primary AT interface is discovered separately
by platform provisioning; applications and provisioning must not assume a
fixed AT tty number.

PowerTune consumes generic NMEA rather than performing Quectel-specific
provisioning. EC25 provisioning is owned by `meta-powertune` and applies
persistent GNSS startup configuration, including the modem's `autogps`
setting, before ModemManager starts. Raw PowerTune NMEA logs are dated files
under `/var/log/powertune/`.

## Logging

PowerTune uses three complementary output paths:

* Application Qt messages are written to
  `/var/log/powertune/powertunedash.log`.
* systemd startup, restart, crash, and service lifecycle output remains in
  journald (`journalctl -u powertunedash.service`).
* Raw NMEA is written to `/var/log/powertune/YYYYMMDD.nmea`.

The service retains `StandardOutput=journal` and `StandardError=journal`;
application-file logging supplements rather than replaces journald. systemd
creates the log directory at runtime with `LogsDirectory=powertune`.

The `logrotate` rule applies only to `powertunedash.log`: size threshold 1 MiB,
three rotated files, compression, `missingok`, and `copytruncate`. NMEA files
are intentionally not covered by this rule; their retention policy is a
separate decision.

## Runtime identity

systemd creates a private `/run/powertune` runtime directory with mode `0700`
and sets `XDG_RUNTIME_DIR=/run/powertune`, avoiding Qt's `/tmp/runtime-root`
fallback. The directory ownership follows the service's configured user, so a
future switch to `User=gauges` can use the same systemd-managed setup.

The image creates the `gauges` system account with configured home
`/var/lib/powertune` and supplementary `dialout` and `video` groups. The
service currently runs as `root` with group `gauges`; its log directory is
created with mode `2775`. Migration to `User=gauges` is future work and must
be validated against device access, persistent data ownership, and log
ownership before changing the service identity.

## Raspberry Pi compatibility cleanup

For application behavior in this cleanup, the source of truth is committed
PowerTuneDash source at `2216127` (`refactor: remove active Raspberry Pi
runtime assumptions`), together with target behavior that has actually been
validated. Earlier investigation notes and proposals are not implementation
evidence. If they conflict with that source or verified target behavior, do
not silently reconcile them: record the discrepancy and leave unverified
behavior pending.

New code must not assume `/home/pi` or a board model. Use these rules:

* Mutable or user-replaceable resources belong under `/var/lib/powertune`.
* Immutable application resources belong in QRC or `/usr/share/powertune`.
* Product/system configuration belongs under `/etc/powertune`.
* Helpers belong under `/usr/libexec/powertune`; logs belong under
  `/var/log/powertune`.
* Detect hardware capability through an appropriate backend, not a board-name
  test or an assumed device path.
* Migrate persisted legacy paths with a narrowly scoped compatibility
  resolver. Never blindly replace every occurrence of `/home/pi`.

The current Logo migration uses the mutable-data role and exact-prefix URL
translation described above. Brightness uses generic Linux sysfs backlight
capability discovery; no `rpi_backlight` path or DDC/CI implementation is
part of the current application baseline. Brightness UI is unavailable when
no supported sysfs backend is found. This is the committed application's
capability behavior; availability on a particular image depends on its
runtime sysfs devices. A different backend remains future work.

The source establishes the optional Logo lookup and translation behavior; it
does not by itself establish an end-to-end Device 0 test for present or absent
user artwork. Record that target result only after testing the target image.

## Legacy ECU daemon controls

The upstream repository carried 65 executable-mode ECU daemon artifacts and
two adjacent documents under `daemons/`, a directory identified upstream as
separately proprietary/confidential. This `imx8-appliance` source tree removes
all 67 tracked entries. The application does not package or need that tree
for startup, UDP reception, the dashboard, Generic CAN selection, GPS,
networking, or audio.

The old Startup Daemon UI and related slots remain for compatibility; they
have not been redesigned. `Connect::daemonstartup()` still generates a
legacy `/home/pi/startdaemon.sh` that names files under `/home/pi/daemons`,
and `Connect::restartDaemon()` still attempts to launch that script. Because
the active fork does not provide the daemon files, those controls cannot
launch the corresponding bundled integrations from this source tree. They
may act on separately installed files at those legacy paths. The generated
script also brings `can0` down and up before attempting the daemon, so these
legacy controls are not safe substitutes for the UDP interface and should
not be used on the appliance. Their behavior is not part of the i.MX8
appliance contract.

Other legacy calls still refer to data/configuration paths under the absent
directory, including OBD PID/register lists and OBD/Consult configuration.
The dormant `candump()` path also names the old OBD executable. These are
legacy integration/configuration paths, not dependencies of the application
startup, UDP receiver, or `pt-udp-sim`.

The root `updatedaemons.sh` is a historical Raspberry Pi updater, not part of
the application build. Its daemon-fetch/removal/copy section is disabled in
this fork so it cannot repopulate the proprietary tree. Do not use the
remaining legacy platform-update operations on the i.MX8 appliance.

Any future Hondata K-Pro decoder must use official Hondata documentation
and/or independently collected bus observations for signal definitions. Do
not derive CAN signal semantics from proprietary PowerTuneDigital daemon
implementations.

## PowerTune UDP integration boundary

The QML/dashboard runtime consumes normalized values from the documented
PowerTune UDP interface; it is independent of which publisher produces them.
The boundary is:

```text
integration publisher
    -> UDP identifier,value
    -> PowerTune receiver on :45454
    -> DashBoard properties
    -> QML gauges
```

Device 0 validated the receiver-to-gauge path using `pt-udp-sim`: sending
`179,2500` updated the existing RPM gauge immediately, and an 800–8000
bounce sweep drove the gauge in both directions. This test did not require a
legacy ECU daemon. It validated the existing receiver/data path while the
normal Generic CAN Connect flow was active; it did not validate the new
application-start lifecycle on the target.

The prior source lifecycle started the receiver from `Connect::openConnection()`
after an ECU Connect action, coupling data reception to that path's CAN
attempt. The i.MX8 appliance implementation starts the receiver once when
`Connect` is constructed, before QML is loaded. It remains available for the
application lifetime with Startup Daemon set to `None`, independently of ECU
selection, Generic CAN, `can0`, or any bundled daemon. Normal ECU
Connect/Disconnect actions do not recreate or close it. Existing
publisher-compatible records and parser mappings are unchanged.

For compatibility, the receiver still binds port 45454 on a wildcard address,
not only loopback, and does not authenticate or filter senders. A successful
bind produces one INFO diagnostic with address and port; a bind failure
produces one bounded ERROR diagnostic and is not retried automatically.
Wildcard binding exposes the record interface on all local network
interfaces; account for this when placing the appliance on a network.

The independent-publisher contract, all 407 receiver identifiers, record
grammar, parser edge cases, and `pt-udp-sim` commands are documented in
[DAEMON_UDP_PROTOCOL.md](DAEMON_UDP_PROTOCOL.md). The new startup lifecycle
and failure diagnostics require a focused Device 0 retest after installation.

## Build identity and provenance

Settings shows the fork identity, not the upstream string:

```
PowerTune i.MX8 Appliance
<version> (<short SHA>)
Upstream base: 1.99t
```

- `<version>` is the commit date of the packaged source (`YYYY.MM.DD`), and
  `<short SHA>` is its 7-character commit hash. Two builds of the same revision
  report identical values; two commits on one day differ by SHA.
- `powertunedash.bb` derives both in `do_configure` from the source BitBake
  fetched and exports `PT_BUILD_VERSION` / `PT_BUILD_REVISION`;
  `PowertuneQMLGui.pro` turns them into compiler definitions (qmake variables of
  the same names also work). `ptbuildinfo.h` holds the definitions, the
  `PTBuild` QML context property, and the startup log line.
- Startup logs one line, for example
  `PowerTune build: version="2026.11.05", revision="10e010b"`.
  A `branch="..."` field appears only if `PT_BUILD_BRANCH` is supplied; the
  recipe does not supply it because a fetched checkout cannot establish it
  reliably.
- Missing metadata falls back to `unknown`. The application never runs Git and
  does not need `.git`.
- `1.99t` is retained only as the explicit "Upstream base" line.

## Recovery and U-Boot

The validated Linux U-Boot environment geometry is:

```text
/dev/mmcblk2boot0 0x3F0000 0x4000
```

`fw_printenv` and `fw_setenv` use the matching `/etc/fw_env.config`. The image
retains CompuLab's `cl-deploy` and `cl-uboot` command-line recovery/deployment
tools. The current boot policy is recovery-oriented; preserve the ability to
inspect and repair U-Boot from Linux. Do not infer additional boot-selection
semantics from the environment geometry alone.

## Development and validation workflow

PowerTuneDash is consumed by BitBake from Git. **Commit PowerTuneDash source
changes before BitBake can build them**: uncommitted edits in a checkout do
not become part of the local Git fetch.

`meta-powertune` is consumed directly as a local Yocto layer, so local layer
changes can be built before they are committed. This does not make unrelated
or unreviewed layer changes safe to include.

USB live boot is the default image-validation workflow. eMMC flashing is an
intentional milestone deployment, not the routine test loop. Validate display,
input, storage, GPS, and recovery-sensitive changes on Device 0 before
considering the corresponding behavior established.

## K-Pro CAN services

`powertune-can.service` configures `canE` (empirically the populated Device 0
P8 CAN interface) at 1 Mbps with restart-ms 100, without
`/etc/network/interfaces` or the legacy PowerTune CAN setup.
`powertune-kpro-bridge.service` runs after and requires it, sending to UDP
`127.0.0.1:45454`. `powertunedash.service` is not ordered against either. Both
are enabled on `powertune-image` by the `powertunedash` recipe and configured
by `/etc/powertune/powertune-appliance.conf`. The bridge is not started from
the legacy daemon UI. `ISO_GND_1` was required between isolated bench nodes.
Real vehicle validation is pending; see
[`CAN_BENCH_TESTING.md`](CAN_BENCH_TESTING.md) for the boot acceptance procedure.
