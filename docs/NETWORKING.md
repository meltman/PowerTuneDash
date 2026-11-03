# PowerTune Networking: Current State and Refactor Design

This document records the PowerTune NetworkManager client implementation and
Device 0 validation. NetworkManager owns Wi-Fi profiles and IP configuration;
the PowerTune Network page presents discovered state and bounded address
summaries.

## Current implementation

### Source inventory

| Source | Current behavior | Classification |
| --- | --- | --- |
| `networkmanagerclient.cpp` / `networkmanagerclient.h` | Implements asynchronous system-D-Bus discovery, on-demand scans, SSID listing, saved/new profile activation, disconnection, radio/state/address reporting, and secret-free error messages. It filters by NetworkManager device type, excludes `p2p-dev-*`, and picks one deterministic device of each supported type. | Active client; Device 0 scan, connection, and addressing validated |
| `wifiscanner.cpp` / `wifiscanner.h` | Retains the old `iw wlan0` scanner, fixed `wlan0`/`eth0` status reads, and plaintext supplicant writer. It is no longer compiled or exposed to QML. | Dormant legacy source, excluded from the application |
| `Settings/network.qml` | Explicit Scan button; SSID selection/hidden SSID entry; masked password field; connect, disconnect, cancel, status, error, and address display. It uses `NetworkManager` and does not scan during app startup. | Active settings UI wired to the new client |
| `Settings/WifiCountryList.qml` | Supplies fixed country-code/name choices for the old supplicant writer. | No longer used by the active Network settings page |
| `SerialSettings.qml` | Declares the Network tab (index 9) with source `Settings/network.qml`. | UI entry point |
| `connect.cpp` / `connect.h` | Owns and exposes `NetworkManagerClient` as `NetworkManager`. `canbitratesetup()` still truncates and rewrites `/etc/network/interfaces`; its Yocto branch writes `wlan0`, `eth0`, and `can0` stanzas together. | New Wi-Fi client wiring; CAN/network configuration coupling remains untouched |
| `dashboard.h` / `dashboard.cpp` | Exposes `WifiStat`, `EthernetStat`, and a Wi-Fi string list to QML. Status setters emit change signals. | Active UI state transport; the status values are in-memory |
| `appsettings.cpp` / `appsettings.h` | Exposes `getDaemonActivationKey()`, which derives a key from the MAC address of `eth0`. No in-repository caller was found. | Dormant legacy identity/activation assumption, not connection management |
| `PowertuneQMLGui.pro` | Enables QtDBus and compiles `networkmanagerclient.cpp`; the old scanner is excluded. Qt Network remains for unrelated HTTP features. | Active build configuration |
| `main.cpp` / `main.qml` | Configures Qt's virtual-keyboard input method and provides an application-wide `InputPanel`. | Existing UI capability; verify deployed keyboard QML package |
| `meta-powertune/recipes-core/packagegroups/packagegroup-powertune-qt5-runtime.bb` | Explicitly depends on `networkmanager-daemon` and `networkmanager-wifi`. | Runtime package dependency added in the companion metadata worktree |
| `test.sh` and generated daemon scripts in `connect.cpp` | Use `ifdown can0` / `ifup can0`; generated scripts also mention CAN setup. | CAN-only; do not change in this networking refactor |
| `gopro.cpp`, `downloadmanager.cpp`, `parsegithubdata.cpp` | Use Qt networking for GoPro requests and downloads. | Unrelated application networking; preserve |
| `README.md` | Contains `wpa_passphrase` setup steps in its historical Raspberry Pi instructions. | Legacy documentation, not the current Device 0 application flow |

The active client does not invoke `nmcli`, `iw`, `ifconfig`, or `ip`, and has
no synchronous process wait. The dormant scanner source still contains legacy
shell and interface-name assumptions but is no longer part of the qmake
target. Qt Network continues to support unrelated HTTP features.

### Wi-Fi scan and AP-model lifecycle

Device 0 runtime validation confirmed that the Network page opens, Scan can
be pressed, PowerTune does not spawn `iw`, `nmcli`, or `wpa_passphrase`, and
NetworkManager immediately reports numerous WPA2/WPA3 access points through
`nmcli` after the PowerTune scan. At that time the PowerTune dropdown remained
empty. The request being accepted is not evidence that scan results are ready.

The source trace found two gaps at the boundary between the accepted request
and model population: a successful `RequestScan` reply caused an immediate
refresh before NetworkManager's result properties necessarily changed, and
the `AccessPoints` `ao` value was read only as a native
`QList<QDBusObjectPath>`, without handling QtDBus's `QDBusArgument`
representation. The latter can leave the enumerated path list empty and thus
publish an empty model even though NetworkManager has access points.

The corrected flow is event-driven: the wireless device subscribes to
`org.freedesktop.DBus.Properties.PropertiesChanged` for
`org.freedesktop.NetworkManager.Device.Wireless`. An accepted `RequestScan`
leaves scanning active while awaiting `LastScan` or `AccessPoints` changes;
those signals schedule the existing debounced device refresh. `AccessPoints`
is decoded from either the native path list or a `QDBusArgument` array.
`LastScan` advancement completes the scan after AP enumeration, and the
resulting `QVariantList` of `QVariantMap` entries emits `accessPointsChanged`
for the QML `ComboBox` (`textRole: "displayName"`) only when its content
differs from the last published model. Visible SSIDs are
deduplicated by SSID; hidden APs remain separate by object path. Debug
diagnostics identify scan request, relevant wireless result updates, and
unique result count, without logging credentials or every AP.

Device 0 validation now confirms that scanning populates the PowerTune
dropdown. The bounded scan timeout remains a failure safeguard, not the
normal completion mechanism.

### Change-driven QML state publication

NetworkManager D-Bus events continue to refresh internal device, connection,
address, and access-point state. Before notifying QML, the client compares the
decoded Wi-Fi and Ethernet property groups and the complete AP model with
their last published snapshots. Identical state produces no notification;
actual changes publish immediately. The Wi-Fi snapshot includes the complete
address lists, from which the bounded QML address summaries are derived.
Refreshes do not discard or truncate backend state, and subscriptions and
event handling remain active.

### Device 0 connection and address status

Device 0 validation confirms that Wi-Fi scanning populates the AP selector,
and PowerTune can create and activate a NetworkManager Wi-Fi profile
(`PowerTune MCPortAuthority`). NetworkManager owns profile persistence; the
Wi-Fi connection survives restarting `powertunedash.service`. Incorrect
credentials produce a connection error, and no credential leakage was
observed in PowerTune logs during validation. Both physical Device 0 Ethernet
ports have been exercised.

PowerTune follows the active Ethernet interface, and NetworkManager provides
addresses for Wi-Fi and Ethernet. The final Network page presents each discovered interface
with a human-readable state and consistent status colors: green for connected
or activated, orange for connecting/configuring or carrier-only, and red for
disconnected, unavailable, or failed. IPv4 and IPv6 summaries use separate
bounded, elided rows. Wi-Fi authentication errors have a bounded, wrapped
message with the actionable text “Wi-Fi authentication failed. Check the
password.”

### Wi-Fi authentication failure lifecycle

The client treats NetworkManager's terminal activation/device failure as the
end of the PowerTune attempt. An ActiveConnection `StateChanged` to state 4
(`DEACTIVATED`) maps reason 9 (`NO_SECRETS`) and reason 10 (`LOGIN_FAILED`) to
the actionable authentication error; reason 5 (`IP_CONFIG_INVALID`) maps to
the IP-configuration error. A Wi-Fi Device `StateChanged` to state 120
(`FAILED`) also ends the attempt. Device reasons 7 (`NO_SECRETS`), 9
(`SUPPLICANT_CONFIG_FAILED`), and 10 (`SUPPLICANT_FAILED`) are handled as
terminal failures; reasons 7 and 10 map to the authentication error, reason 9
uses the generic connection error, and reasons 5 and 6 map to the
IP-configuration error.
Activation state 2 (`ACTIVATED`) is success. A state read from
`ActiveConnection.GetAll` has no failure reason, so state 4 from that property
read is not allowed to mask the reason-bearing signal with a generic error.

On terminal failure, PowerTune clears its transient password, marks
`wifiConnecting` false, deactivates the failed active connection when
applicable, and emits one warning for an authentication failure. It does not
retry or resubmit credentials. Kernel/wpa_supplicant authentication exchanges
may repeat before NetworkManager emits a terminal state/reason; PowerTune does
not add a timeout or cancellation heuristic for those lower-level exchanges.
Device 0 should be checked to confirm which terminal signal/reason NetworkManager
1.46 reports for a rejected password.

New profiles are created with autoconnect disabled while authentication is in
progress. On success, PowerTune enables autoconnect and retains the persistent
profile. On failure or cancellation, it deactivates the attempt and deletes
only that newly created profile. For an existing saved profile, PowerTune
retains the original settings, temporarily disables autoconnect while the
submitted password is tried, and restores the original profile if the attempt
fails or is cancelled. If restoration fails, the temporary profile remains
non-autoconnecting, preventing repeated bad-password attempts. On success, it
persists the new settings while keeping the profile's original autoconnect
preference; it never deletes a previously valid saved profile. The user can
enter a corrected password and start another explicit attempt.

Connection diagnostics contain only the requested SSID and discovered
interface name, never passwords, PSKs, or connection-setting dictionaries.
The Network page preserves the current connection/error presentation while
also preserving selection by identity: the connected SSID takes priority;
otherwise the user's selected visible SSID or hidden AP object path is
resolved against each rebuilt model. No ComboBox index is stored. Hidden SSID
text is held in its own input field and is not reset when AP results reorder.

The complete IPv4 and IPv6 address arrays remain exposed by the client for
both Wi-Fi and Ethernet. The current Network settings screen displays the
first address in NetworkManager's returned order for IPv4, and the first
non-link-local IPv6 address (falling back to the first link-local address if
no global address is present). This display-only choice does not filter or
reorder the complete backend arrays. Each address is on its own single-line,
bounded, elided row.

The previous `AddressData` decoder attempted `beginArray()` on a non-const
`QDBusArgument` copy, selecting QtDBus's write-side overload on a read-only
received argument. The decoder now uses a const read-side argument for array
and map extraction, while accepting native QVariant lists/maps. It keeps all
non-empty addresses and removes duplicates. The correction and bounded UI summary have source-level test coverage. Device 0
has validated Wi-Fi and Ethernet address publication; the read-side decoder
warning correction is present in source and still requires final-image
validation.

### Network Settings page

`Connect` creates the D-Bus client during application initialization. It
performs asynchronous capability/device discovery only; it does not wait for
Internet access or scan Wi-Fi. The Network tab remains index 9 and its Scan
button requests scans only after the user opens the tab. Current SSIDs,
hidden-network entries, security capability, device state, and IPv4/IPv6
addresses come from NetworkManager properties.

The client selects one managed Wi-Fi device (activated first, then stable
case-insensitive interface-name order) and one managed Ethernet device
(activated, then carrier, then stable name order); Wi-Fi P2P names are
excluded. Enterprise/WEP security types are not supported by this UI. Hidden
access points remain represented with an empty SSID and a UI prompt for the
user to enter the real SSID.

New connections use NetworkManager's persistent `AddAndActivateConnection2`
API. A matching saved profile is reused; a supplied password updates the
NetworkManager-owned profile through `Update2`. Passwords are masked in QML,
are not written to PowerTune settings/dashboard/export/log files, and are
cleared from the QML field and client transient state after submission or
cancellation. Device D-Bus errors are reduced to fixed, secret-free user
messages. The field uses the existing Qt virtual-keyboard input method.

Access-point support is classified from NetworkManager's `Flags`, `WpaFlags`,
and `RsnFlags`: no privacy or key-management flags is open; PSK and SAE are
supported; privacy-protected networks without either supported key management,
including enterprise networks, are marked protected-but-unsupported. Cipher
bits alone do not imply key management. Unsupported networks are labeled in
the selector and cannot be submitted. Connect additionally requires an
explicitly selected access point and a non-empty SSID. A visible selection
uses its advertised SSID; a selected hidden entry requires the user to type
the SSID. Typing into the editable selector without selecting an access point
does not enable Connect.

The D-Bus connection settings argument is `a{sa{sv}}`; the remaining
`AddAndActivateConnection2` inputs are device object path, specific-object
path, and options `a{sv}`. This client requests `persist="disk"` and handles
the returned active-connection path. Existing profiles are found by SSID;
profile enumeration/read errors are reported rather than silently treated as
an empty profile list. When a password is supplied, `Update2(a{sa{sv}}, u,
a{sv})` uses flag `0x1` (`to-disk`) before activating that profile. A saved
profile may be activated without a newly entered password. Activation
completion uses active connection states 2 (activated) and 4 (deactivated),
with reason codes interpreted using `NMActiveConnectionStateReason`.

The Device 0 evidence above validates scanning, connection persistence,
Wi-Fi/Ethernet addressing, and active Ethernet interface selection. Verify
the QDBus read-only argument warning is absent on the final image.
`wifiscanner.cpp` remains in the tree but is neither compiled nor exposed to
QML.

## Device 0 and image integration evidence

Device 0 validation reports NetworkManager 1.46.0 active, system D-Bus
available, QtDBus 5.15.13 installed, Wi-Fi enabled, and successful
NetworkManager D-Bus introspection. Observed devices include Wi-Fi `wlan0`,
Wi-Fi P2P `p2p-dev-wlan0`, Ethernet `eth0`/`eth1`, GSM `cdc-wdm0`, and
unmanaged CAN devices `canC`/`canE`. Both Ethernet ports have been exercised;
the names are observations, not interface names PowerTune assumes. Fresh
images intentionally contain no preconfigured Wi-Fi credentials. The latest
available `powertune-image` package manifest also includes:

* NetworkManager 1.46, its daemon and Wi-Fi plugin;
* `libnm0` and `networkmanager-nmcli`;
* `iw` and `wpa-supplicant`;
* Qt 5.15.13 `qtbase`, whose package file list contains
  `/usr/lib/libQt5DBus.so.5`.

This establishes image/package availability, not a live check of the target
system bus, NetworkManager permissions, radio, or device state. The
PowerTuneDash qmake project now lists the `dbus` module. QtDBus is included
with QtBase; the companion metadata runtime package group now explicitly
depends on `networkmanager-daemon` and `networkmanager-wifi`.

Device 0 validation supplied for this task reports that the Network settings
password field opens the Qt virtual keyboard. The new app field is masked and
uses sensitive/no-prediction input hints. The manifest snapshot is
`powertune-image-iot-gate-imx8plus.rootfs-20261102195130.manifest`.

NetworkManager exports a system D-Bus API for device discovery, wireless
scanning and access points, activation/deactivation, radio state, connection
state, and IP configuration. QtDBus is available in this image and provides
typed asynchronous calls/signals without parsing human-oriented command
output. The image also provides `libnm0`, but the application does not
currently depend on libnm headers or its GLib/GObject client API. `nmcli` is
available as an alternative executable, but parsing its display output is
less robust; putting a passphrase in command arguments can also expose it to
process inspection or diagnostics. Do not invoke it through a shell.

**Implemented source design:** QtDBus calls NetworkManager's system-bus
interfaces asynchronously. The current systemd service runs as root, but
this does not establish effective target D-Bus authorization; verify target
bus policy and each operation. No unrestricted sudo or privilege changes
were introduced. The client performs device discovery on application startup
without requiring Internet access and only scans when the user selects Scan.

## CAN boundary

`Connect::canbitratesetup()` remains the concrete coupling: it writes
`/etc/network/interfaces` and, in its Yocto branch, emits
legacy `wlan0` and `eth0` configuration adjacent to its CAN stanza and CAN
bitrate commands. The other `ifup`/`ifdown` and `ifconfig` hits found by the
source search are CAN-only scripts or generated CAN setup. They are not part
of the NetworkManager UI refactor.

No CAN code, SocketCAN, ECU behavior, or `canbitratesetup()` was changed.
The legacy WLAN/Ethernet stanzas remain coupled with CAN configuration and
require a separately scoped, simulator-validated change.

## Performance and diagnostics findings

The active client uses asynchronous D-Bus calls/signals and contains no
subprocess polling or `waitForFinished()`. The excluded legacy scanner still
contains the old synchronous `iw` scan and repeating timer; it must remain
excluded unless it is removed in a future cleanup. No timing benchmark was
run.

## Expected implementation scope

Source implementation files are `networkmanagerclient.cpp/.h`,
`connect.cpp/.h`, `Settings/network.qml`, and `PowertuneQMLGui.pro`. No
dashboard status-model change was needed. The companion
`meta-powertune` runtime package group now explicitly depends on
`networkmanager-daemon` and `networkmanager-wifi`. The available image
manifest includes these packages. QtDBus uses QtBase; `libnm0` and `nmcli`
are not required by this client.

`appsettings.cpp` has a separate, currently unreferenced `eth0`-MAC-derived
activation-key helper. Decide whether that legacy identity behavior is in
scope before changing it; it is not Wi-Fi/Ethernet connectivity state.
`SerialSettings.qml` changes only if the tab entry/availability behavior
needs adjustment. Do not change unrelated Qt HTTP clients.

## Future Device 0 validation matrix

1. Boot a fresh image with no saved Wi-Fi profile and no network connectivity;
   verify PowerTune starts normally and emits no scan or connection errors.
2. Verify one discovery diagnostic for each present device and one useful
   message when Wi-Fi hardware is absent; verify no periodic duplicate logs.
3. Open Network settings and confirm scanning starts only on page open or
   explicit Scan, with SSIDs listed; close/reopen and verify no accumulating
   polling or duplicate scan workers.
4. With Wi-Fi present, connect to a test AP using the virtual keyboard; test
   wrong password, cancellation, disconnect, reconnect, saved-profile
   persistence after application restart, and current SSID/state.
5. Confirm the password is absent from `powertunedash.log`, journald,
   QSettings, dashboard exports, command-line arguments, and debug output;
   inspect NetworkManager's persisted profile ownership, secret flags, and
   permissions.
6. Disable the Wi-Fi radio and verify controls/status update without an error
   loop; test no-Wi-Fi hardware separately if available.
7. Test no Ethernet device and a connected Ethernet device with an actual
   non-`eth0` name; verify link/activation state and IPv4/IPv6 display.
8. Test NetworkManager unavailable/restarting and D-Bus permission failures;
   verify the UI reports actionable errors and does not block or crash.
9. Verify multiple Wi-Fi/Ethernet devices follow the chosen explicit policy.
10. With a bench CAN/ECU simulator, separately verify CAN bitrate and setup
    behavior remains unchanged by the networking refactor.

No compile, QML lint, target deployment, or Device 0 NetworkManager D-Bus
runtime test has been performed for this source implementation. Validate all
the above interactions on Device 0 before treating networking as complete.
