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

## Legacy ECU daemon compatibility (static findings)

The startup-daemon setting in `Settings/startup.qml` stores a ComboBox index.
The “Hondata 20Hz” choice maps to `daemons/Hondatad`; “Hondata 100Hz” maps to
`daemons/HondataS300`. These are UI labels, not measured update rates.
`Connect::daemonstartup()` generates `/home/pi/startdaemon.sh`, changes to
`/home/pi/daemons`, brings up `can0`, and runs one selected daemon without
arguments. `Connect::restartDaemon()` launches that script. The application
settings flow also calls `Connect::canbitratesetup()`, which writes legacy
`/etc/network/interfaces` CAN configuration and requests a reboot. The script
selects one daemon, but the GUI does not enforce that only one daemon process
exists. It does not supervise daemon failure or stop the daemon when its UDP
receiver is closed. The GUI's restart path can display captured process
output in its status property, but no daemon log-file path is configured
here. No in-repository boot/init hook invoking the generated script was
identified; the installed image's startup mechanism remains to be checked.

Static inspection identifies both Hondata files as ELF32, little-endian ARM
EABI5 hard-float executables, dynamically linked through
`/lib/ld-linux-armhf.so.3` and requiring `libc.so.6` (GLIBC_2.4). They are not
AArch64 binaries:

| File | SHA-256 |
|---|---|
| `daemons/Hondatad` | `6e2f1eafc3d8038b58453f882a15195a6c040579b51b25d61ce4b4a5b855afed` |
| `daemons/HondataS300` | `541fd93f1fbd265d3f5800af74379a1a2f8ec3a10f71252a51ab1d0f1d6abed1` |

Both import networking and CAN-related functions, and their visible strings
include K-Pro/S300 CAN protocol labels and text records shaped like
`identifier,value`. The GUI's `udpreceiver` binds UDP port `45454`, parses
each received datagram as that text pair, and maps identifiers to individual
`DashBoard` properties (for example `179` to RPM, `155` to MAP, and `199` to
speed). The source contains 407 identifier cases, including unused cases.
This is not a fixed global structure. Static inspection did not establish the
Hondata sender's destination port, update rate, or full packet semantics;
those require an authorized runtime capture.

The daemon-adjacent readme says a valid license is required. Both Hondata
binaries contain strings for `Licence.lic`, `eth0`, and license-valid/invalid
messages, but strings do not prove the exact file path, enforcement point, or
failure behavior. Across the 65 ELF files in `daemons/`, 52 contain a
`Licence.lic` string and 50 contain the visible valid/invalid status strings;
this is not evidence that every daemon shares one licensing mechanism.
The GUI's `RequestLicence()` refers to `/home/pi/licencerequest` and
`/home/pi/Licrequest.lic`, while the repository artifact is named
`daemons/LicenceRequest` (different case and location). No in-repository
caller or copy step connecting that GUI helper/key setting to
`daemons/Licence.lic` was found. `AppSettings::getDaemonActivationKey()`
derives a zero-padded decimal string from the last three octets of the
`eth0` MAC (or returns `000-000-000` if unavailable), but no in-repository
caller was found; `writeDaemonLicenseKey()` only stores a Qt setting and
updates a dashboard property. Do not infer license generation, enforcement,
or bypass from these static clues.

On a standard 64-bit i.MX8Plus userspace these ARM32 binaries are not native.
Running them would require a compatible ARM32 hard-float kernel/userspace,
including the loader and libraries; target kernel compatibility and runtime
availability have not been verified. The `/home/pi` and `can0` assumptions
are additional integration dependencies. No daemon was executed for this
assessment.

Hondata's [K-Pro product information](https://www.hondata.com/kpro) confirms
that dash output is available over serial and CAN, but that page does not
publish signal definitions. A compatible replacement could retain the GUI
interface by emitting the existing identifier/value UDP records to port
`45454`; implementing K-Pro CAN decoding requires authoritative manufacturer
signal documentation. Do not infer signal definitions from daemon strings or
recreate licensing behavior.

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
