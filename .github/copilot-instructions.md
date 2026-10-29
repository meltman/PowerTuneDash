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