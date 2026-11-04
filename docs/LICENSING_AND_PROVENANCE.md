# Licensing and integration provenance

## PowerTuneDash source

The PowerTuneDash source fork is based on GPLv3-covered source and remains
subject to the applicable terms in the repository's existing [LICENSE](../LICENSE).
This document does not modify or replace that license.

## Proprietary ECU daemon artifacts

The upstream repository identified the `daemons/` directory and its contents
as separately proprietary/confidential PowerTuneDigital material. The
`imx8-appliance` active tree intentionally removes all 67 tracked entries
from that directory and neither distributes nor depends on those artifacts.
The inventory contained 65 executable-mode artifacts and two adjacent
documents (`Licence.md` and `Readme.txt`); no source files or generated data
were identified in that directory. The adjacent documents were removed with
the tree, and no implementation, algorithm, or binary content from those
artifacts is included in this fork's integration documentation.

The legacy Startup Daemon controls and source paths remain in parts of the
application for compatibility. They refer to files at old `/home/pi/daemons`
paths and cannot launch the removed files from this source tree. They are not
the PowerTune UDP integration boundary and should not be used as an
appliance integration strategy.

## Independent integration interface

PowerTuneDash exposes a source-visible UDP input interface on port `45454`.
The interface documentation is derived from the GPLv3-covered receiver
source and Device 0 behavior; it describes PowerTune's own record parsing
and identifier-to-Dashboard dispatch.

[`pt-udp-sim`](../tools/powertune-udp-sim.py) is an independently written
development publisher for that interface. Device 0 validation showed that
`179,2500` updates the existing RPM gauge and that an RPM sweep drives it.
No proprietary ECU daemon implementation is required to send compatible
records. The protocol is documented in
[`DAEMON_UDP_PROTOCOL.md`](DAEMON_UDP_PROTOCOL.md).

## ECU integration provenance

Future ECU integrations must derive signal definitions and decoding behavior
from manufacturer-published specifications, legitimately available
open-source work, or independently obtained bus observations. Do not derive,
reverse engineer, or copy ECU signal semantics or decoding from
PowerTuneDigital proprietary daemon implementations.

In particular, a future Hondata K-Pro decoder must use official Hondata
documentation and/or independently collected bus observations. This fork
does not implement Hondata decoding.

## Unresolved licensing helper

The repository contains a separate top-level `LicenceRequest` executable.
Metadata identifies it as an ARM32 executable, but its source, licensing
status, and provenance have not been established. It is not listed in the
PowerTuneDash application project. The legacy `RequestLicence()` source path
uses a differently cased `/home/pi/licencerequest` name, which does not
establish that this top-level artifact is its implementation.

This helper is retained unchanged pending a human provenance/licensing
decision. It has not been executed and its contents have not been read or
analyzed. It is not included in this fork's integration workflow. Do not
redistribute, modify, or rely on it until its status is established.
