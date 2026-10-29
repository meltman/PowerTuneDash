Target: CompuLab IOT-GATE-IMX8PLUS / i.MX8MP

Production UI:
Qt5 + EGLFS/KMS
/dev/dri/card1
No Weston requirement

Platform:
Yocto Scarthgap
meta-powertune owns product integration

Rules:
- Do not introduce new Raspberry Pi assumptions.
- Do not hardcode /home/pi.
- Preserve Windows development support.
- Separate immutable resources, mutable data,
  configuration, logs and helper executables.
- Preserve backward compatibility with legacy
  dashboard files where practical.
- Do not casually alter ECU/CAN protocol behavior.
- Prefer standard Linux interfaces over Pi-specific
  commands and sysfs paths.
- HDMI brightness on i.MX8MP will use DDC/CI,
  not rpi_backlight.
- Make small, reviewable changes.
- Do not commit or push without explicit instruction.

Build and deployment workflow:
- The authoritative i.MX8MP build is the Yocto/BitBake recipe powertunedash.
- PowerTuneDash is cross-compiled through Yocto. Do not treat native host qmake or make builds as authoritative.
- The development source checkout on ubuntu-dev is shared into the Yocto container as /work/PowerTuneDash.
- The Yocto container shell automatically initializes the existing build-imx8mp environment.
- For normal application validation, use pt-build.
- For deployment to the development IOT-GATE target, use pt-deploy.
- pt-build runs the required BitBake build/install tasks and records the resulting AArch64 artifact.
- pt-deploy installs that artifact on the development target and restarts powertunedash.service.
- Do not manually search tmp/work for artifacts during the normal development workflow.
- Do not run cleansstate, delete build output, or otherwise invalidate Yocto caches unless explicitly instructed.
- Do not create an alternate native qmake/make build workflow unless explicitly requested.
