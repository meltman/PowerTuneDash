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
