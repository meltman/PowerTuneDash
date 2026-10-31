# READ THESE BEFORE MODIFYING POWERTUNE

This handoff is for developers and coding agents with no prior conversation
history. Use this order before architectural or platform work:

1. `.github/copilot-instructions.md`
2. `docs/AI_HANDOFF.md`
3. `docs/IMX8_PORT.md`
4. `docs/ARCHITECTURE_DECISIONS.md`
5. Recent Git history
6. `meta-powertune` documentation when working on the image/platform

## Known-Good Baseline

The validated Device 0 baseline is:

* PowerTune starts automatically.
* Qt 5 EGLFS renders fullscreen.
* The display DRM device is `/dev/dri/card1`.
* The software cursor is required and works.
* Qt/fontconfig fallback renders text.
* Dashboard edit, import/export, and save operate.
* EC25 GNSS/NMEA works.
* Application-file logging works.
* Weston, Docker, and containerd automatic startup are disabled.
* U-Boot environment can be read and written from Linux.
* Command-line eMMC/U-Boot recovery tools remain available.

Treat these as target-validated observations, not guarantees about other
boards or future images. If new evidence conflicts, investigate and update the
baseline rather than silently treating either version as universal.

## Source-of-truth rule

For Raspberry Pi compatibility cleanup, use committed PowerTuneDash source at
`2216127` (`refactor: remove active Raspberry Pi runtime assumptions`) as the
implementation authority, together with Device 0 behavior that has actually
been validated. Do not copy earlier investigation proposals into the
documentation as though they shipped. For example, the intro Logo remains a
user-replaceable external file under `/var/lib/powertune/Logo/`; it was not
converted to immutable QRC artwork. The source supports capability-detected
sysfs brightness only; DDC/CI is not implemented.

When earlier notes, documentation, and committed source disagree, document
the source-backed behavior and identify any target result that remains
unverified. Do not guess or present source inspection as runtime validation.

## Landmines

* Never assume `/home/pi`.
* The repository-root `README.md` contains historical Raspberry Pi/Buildroot
  setup instructions; do not treat those commands and paths as the current
  i.MX8MP build or deployment workflow.
* Never globally rewrite legacy stored paths.
* Never infer hardware support from build-host files.
* Never remove legacy behavior without proving whether it is active.
* Do not mix large architectural refactors with hardware bring-up.
* Preserve user-replaceable resources as external mutable data.
* PowerTuneDash changes must be committed before BitBake consumes them.
* Do not blindly stage unrelated `meta-powertune` BSP/Falcon work.

## Source and image provenance

PowerTuneDash is consumed by BitBake from Git. The recipe uses a local Git
fetch, which does not include uncommitted source edits. Commit the intended
PowerTuneDash changes before building an image; a dirty source worktree is not
what BitBake builds.

`meta-powertune` is a local Yocto layer consumed directly by the build. Its
local changes can be built before commit, but inspect its worktree and stage
only files relevant to the task. This layer has included separate
Falcon/U-Boot experiments; do not sweep them into unrelated product changes.

USB live boot is the default image-validation workflow. eMMC flashing is
reserved for intentional milestone deployment. `pt-build` and `pt-deploy`
may be available in the established development environment; confirm their
current behavior rather than assuming an uncommitted PowerTuneDash tree is
included in a build.

## Change discipline

Use role paths instead of adding hard-coded Linux paths, and preserve
`C:/PowerTune` development compatibility as documented. Use hardware
capability detection rather than board-name checks. Investigate legacy
behavior before refactoring it. Keep changes small, testable, and within the
requested scope; do not alter CAN/ECU protocol, networking, or hardware
behavior incidentally.

Clearly distinguish validated facts from proposed behavior. Update the
relevant documentation in the same change set whenever a change modifies
architecture, platform behavior, hardware integration, filesystem roles,
persistence, compatibility, boot behavior, or the known-good baseline.
Small implementation fixes that do not alter a documented contract do not
need documentation churn.
