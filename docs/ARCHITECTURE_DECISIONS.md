# Architecture Decisions

These records distinguish established behavior from future work. "Validated
evidence" cites current source/layer configuration or the documented Device 0
observations; it is not a claim that every future image has been retested.

## PT-001 — Direct Qt5 EGLFS/KMS production rendering

**Context:** PowerTune is a fullscreen instrument-cluster UI on the i.MX8MP.

**Decision:** Production rendering uses Qt 5 EGLFS/KMS directly, started by
`powertunedash.service`.

**Rationale:** The validated product path does not require a Wayland
compositor.

**Validated evidence:** Device 0 runs `/usr/bin/powertunedash -platform eglfs`;
the service and package configure that command.

**Compatibility impact:** Development on other platforms remains possible;
the production display path is target-specific.

**What not to do:** Do not switch production to Weston/Wayland as an incidental
application change.

## PT-002 — Explicit i.MX8 display DRM selection

**Context:** The target exposes multiple DRM devices.

**Decision:** Select `/dev/dri/card1`, the `imx-drm` device driving HDMI, and
set `"hwcursor": false`.

**Rationale:** `card0` is `galcore`; the hardware cursor path failed while the
software/OpenGL cursor worked.

**Validated evidence:** Device 0 topology is `card0 -> galcore`,
`card1 -> imx-drm`, and `card1-HDMI-A-1 -> HDMI`; packaged `eglfs.json` selects
card1 and disables hardware cursor.

**Compatibility impact:** The setting targets the validated i.MX8 image, not
generic desktop or Raspberry Pi rendering.

**What not to do:** Do not assume card numbering or enable the hardware cursor
without testing on the target.

## PT-003 — Role-based Linux filesystem layout

**Context:** The former single-base-path model mixed application resources,
mutable data, configuration, helper programs, and logs.

**Decision:** Use `/usr/share/powertune` for immutable resources,
`/etc/powertune` for system configuration, `/var/lib/powertune` for mutable
data, `/usr/libexec/powertune` for helper executables, and
`/var/log/powertune` for logs. The executable is `/usr/bin/powertunedash`.

**Rationale:** Filesystem roles clarify ownership, persistence, packaging, and
future runtime identity.

**Validated evidence:** `ptpaths.h` defines role helpers; the Yocto recipe
installs the executable and EGLFS configuration at their product locations.

**Compatibility impact:** Windows role helpers continue to resolve under
`C:/PowerTune`; legacy APIs remain compatibility-only.

**What not to do:** Do not add new arbitrary absolute Linux paths or collapse
all data back into one base directory.

## PT-004 — Application logs plus journald

**Context:** Application diagnostics and service lifecycle diagnostics have
different operational uses.

**Decision:** Qt messages go to `/var/log/powertune/powertunedash.log` and
continue to stderr/journald. NMEA remains in dated `.nmea` files.

**Rationale:** The file log is convenient for application troubleshooting;
journald remains authoritative for service startup, restart, and crash
diagnostics.

**Validated evidence:** `main.cpp` installs a Qt message handler that also
forwards to the prior/default handler; the service keeps journal output; the
layer installs a logrotate rule and uses systemd `LogsDirectory`.

**Compatibility impact:** NMEA file behavior is separate from application
log rotation and remains unchanged.

**What not to do:** Do not replace journald with `tee`, a shell wrapper, or a
custom logging daemon; do not rotate NMEA as part of application-log policy.

## PT-005 — Vendor modem provisioning outside PowerTuneDash

**Context:** EC25-specific modem setup is a product/platform concern, while
PowerTune consumes NMEA.

**Decision:** Keep Quectel provisioning in `meta-powertune`, before
ModemManager; keep modem-specific AT commands out of PowerTuneDash.

**Rationale:** Application protocol logic remains generic and provisioning
can identify modem interfaces independently of tty enumeration.

**Validated evidence:** The layer provides a modem-provision service/profile
and a ModemManager ordering drop-in; Device 0 uses `/dev/ttyUSB1` for NMEA and
discovers the primary AT interface separately.

**Compatibility impact:** Other receivers can supply NMEA without EC25
provisioning.

**What not to do:** Do not hard-code an AT tty index or add Quectel startup
commands to application startup.

## PT-006 — Runtime migration of legacy persisted paths

**Context:** Persisted dashboards may contain old user-resource URLs.

**Decision:** Translate only the exact legacy Logo URL prefix
`file:///home/pi/Logo/` to the current mutable Logo directory in memory.

**Rationale:** Existing dashboards continue to load without mutating imported
files merely because they were opened; a later normal save/export can store
the normalized value.

**Validated evidence:** `ptResolveLogoUrl()` implements exact-prefix
translation; dashboard image fields call the resolver; source dashboard files
are not rewritten during resolution. These statements reflect committed
PowerTuneDash source at `2216127`.

**Compatibility impact:** Only historical Logo-resource URLs are migrated;
other legacy paths and URLs remain unchanged.

**What not to do:** Do not globally rewrite `/home/pi`, rewrite imported files
on load, or create `/home/pi` compatibility symlinks.

## PT-007 — Capability-driven hardware integrations

**Context:** Board-name tests and assumed device paths fail across hardware
variants.

**Decision:** Hardware operations must be guarded by backend capability
detection. Brightness currently supports discovered readable/writable Linux
sysfs backlights or an unsupported state.

**Rationale:** Unsupported hardware should neither be accessed nor reported
as successfully controlled; preferences and hardware application are
separate concerns.

**Validated evidence:** `connect.cpp` discovers sysfs backlights before
brightness reads/writes; QML hides/disables controls when unsupported. This
is the behavior in committed PowerTuneDash source at `2216127`; actual
capability depends on target sysfs devices. No DDC/CI backend is established.

**Compatibility impact:** Raspberry Pi systems remain supported when they
expose a valid sysfs backlight; unsupported targets retain configuration
without claiming hardware application.

**What not to do:** Do not restore `rpi_backlight`, infer support from the
build host or board name, or add DDC commands without a separate validated
backend design.

## PT-008 — USB live boot as standard image validation

**Context:** Routine eMMC deployment complicates recovery during image work.

**Decision:** Use USB live boot for normal image validation; flash eMMC only
for intentional milestones.

**Rationale:** It separates iterative testing from persistent deployment.

**Validated evidence:** This is the established Device 0 workflow.

**Compatibility impact:** eMMC deployment remains supported for deliberate
milestone releases.

**What not to do:** Do not treat every local image build as authorization to
flash eMMC.

## PT-009 — User-replaceable resources remain external mutable data

**Context:** Users replace Logo files on disk; embedding them would remove
that customization workflow.

**Decision:** Store replaceable Logo assets under
`/var/lib/powertune/Logo/`; reserve QRC and `/usr/share/powertune` for
immutable factory resources.

**Rationale:** User content must survive application updates and must not be
silently replaced by embedded artwork.

**Validated evidence:** Logo enumeration and the intro resolver use
`ptLogoPath()`; a missing intro Logo returns an empty source rather than a
QRC fallback. These statements reflect committed PowerTuneDash source at
`2216127`.

**Compatibility impact:** Windows continues to use the existing
`C:/PowerTune` development layout.

**What not to do:** Do not package a mandatory customizable Logo, substitute
factory artwork when it is absent, or create `/home/pi` symlinks.

## PT-010 — Visible dashboard slots are distinct from UserDash definitions

**Context:** The selector's numeric value is an index, while dashboard
definitions are separate stored/exportable objects.

**Decision:** Keep visible slot count and `Userdash1/2/3.qml` definitions
distinct. `numberofdash=2` selects three visible slots; selector values 4, 5,
and 6 map to Userdash1, Userdash2, and Userdash3.

**Rationale:** Slot visibility/order and saved dashboard content are
independent user settings.

**Validated evidence:** `Settings/DashSelector.qml` maps selector values and
adds/removes visible pages; `appsettings.cpp` provides the first-run values;
the UserDash QML files expose distinct datastore aliases.

**Compatibility impact:** Existing QSettings values and dashboard exports
must remain interpretable.

**What not to do:** Do not reinterpret `numberofdash` as a literal count or
equate a visible slot with a UserDash definition.

## PT-011 — Use Qt ALSA output for target warning sounds

**Context:** Device 0 has HDMI ALSA playback but no running PulseAudio,
PipeWire, or WirePlumber service. Qt Multimedia's Pulse-enabled
`QSoundEffect` attempted a Pulse connection at startup and retried after
failure.

**Decision:** In the `meta-powertune` target build, disable Qt Multimedia's
PulseAudio feature and retain ALSA. Preserve PowerTune's existing warning
sounds and instantiate them only when Qt reports a default output device.
Leave device selection and playback format negotiation/conversion to Qt and
ALSA; capability detection checks Qt's own preferred format rather than
assuming a particular hardware PCM format. Log the cached outcome once with
`qInfo()`, including Qt-reported output and format details when available.

**Rationale:** Direct ALSA is available on Device 0 and avoids making an
audio server a prerequisite for warning sounds. Device 0's raw `hw:0,0` PCM
does not accept the default S16_LE test parameters, while ALSA's `plughw:0,0`
conversion path plays successfully. A single cached Qt default-device and
preferred-format check avoids format-specific hardware assumptions and keeps
a missing/unusable default output from initializing the warning effect. The
one-time diagnostic makes the selected backend-facing output visible through
both the application log and journald.

**Validated evidence:** Device 0 exposes ALSA card 0, device 0, and
`/dev/snd/pcmC0D0p`; `speaker-test -D hw:0,0` failed with default parameters,
while `speaker-test -D plughw:0,0` produced audible HDMI sound. The Qt
Multimedia recipe has independent `alsa` and
`pulseaudio` `PACKAGECONFIG` features; with Pulse disabled, Qt 5.15.13's
`QSoundEffect` uses its generic `QAudioOutput` implementation. The
`meta-powertune` append applies `-no-pulseaudio` and retains `alsa`.
Qt output-device/preferred-format detection is source-validated. Application
warning playback on Device 0 remains pending target runtime validation.

**Compatibility impact:** This policy applies to the Yocto product target
using `meta-powertune`; Windows/developer builds keep their platform's normal
Qt audio configuration. Optional GStreamer media/camera behavior is not
redefined.

**What not to do:** Do not add or start PulseAudio/PipeWire for warning
sounds, remove warning thresholds or triggers, or infer target audio support
from the build host.
