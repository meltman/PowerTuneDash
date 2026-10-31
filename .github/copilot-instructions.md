# PowerTune Coding-Agent Contract

Before architectural or platform changes, read these in order:

1. `.github/copilot-instructions.md`
2. `docs/AI_HANDOFF.md`
3. `docs/IMX8_PORT.md`
4. `docs/ARCHITECTURE_DECISIONS.md`
5. Recent Git history
6. `meta-powertune` documentation for image/platform work

## Project baseline

* Target: CompuLab IOT-GATE-IMX8PLUS / NXP i.MX8MP, Yocto Linux, Qt 5.
* Production UI: direct EGLFS/KMS on `/dev/dri/card1`; `"hwcursor": false`.
* Product integration belongs in `meta-powertune`.
* USB live boot is the standard image-validation workflow; eMMC flashing is
  intentional milestone deployment.

## Required practices

* Use role-specific filesystem paths; do not add hard-coded Linux paths.
* Preserve Windows development compatibility under `C:/PowerTune`.
* Preserve user-customizable resources as mutable data; do not replace them
  with embedded defaults unless the resource is intentionally immutable.
* Detect hardware capability through a backend, not board-name checks or
  build-host filesystem contents.
* Investigate legacy code and persisted formats before broad refactors.
* Keep changes small, scoped, and testable; do not casually change ECU/CAN,
  networking, or hardware behavior.
* Separate validated facts from proposals, and do not invent validation
  evidence.
* Update the relevant documentation in the same change set if architecture,
  platform behavior, hardware integration, filesystem roles, persistence,
  compatibility, boot behavior, or the known-good baseline changes. Small
  fixes that do not change a documented contract need no documentation churn.
* PowerTuneDash is fetched by BitBake from Git: commit intended application
  changes before building. Never assume a dirty PowerTuneDash worktree is what
  BitBake will build.
* `meta-powertune` is consumed directly as a local layer and can be built
  before commit. Inspect its worktree and do not stage unrelated BSP or
  Falcon/U-Boot work.
* Do not commit or push unless explicitly requested.

## Build workflow notes

The authoritative target build is Yocto/BitBake (`powertunedash` and the
product image), not a native host qmake/make build. In the established
development environment, `pt-build` and `pt-deploy` may be available; verify
their current behavior and source provenance before use. Do not run
`cleansstate`, delete build output, or invalidate Yocto caches unless
explicitly requested.
