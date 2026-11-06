import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = (ROOT.parent / "compulab-nxp-bsp" / "compulab-imx8mp-bsp" / "sources"
              / "meta-powertune" / "recipes-powertune" / "powertunedash")
FILES = RECIPE_DIR / "files"
CAN = FILES / "powertune-can.service"
BRIDGE = FILES / "powertune-kpro-bridge.service"
CONF = FILES / "powertune-appliance.conf"
RECIPE = RECIPE_DIR / "powertunedash.bb"


def text(path):
    return path.read_text(encoding="utf-8")


def conf_values():
    values = {}
    for line in text(CONF).splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


class KproServiceTests(unittest.TestCase):
    def test_configuration_defaults(self):
        self.assertEqual(conf_values(), {
            "PT_CAN_INTERFACE": "canE",
            "PT_CAN_BITRATE": "1000000",
            "PT_CAN_RESTART_MS": "100",
            "PT_KPRO_PROFILE": "hondata-motec",
        })

    def test_can_service_configures_interface_from_config(self):
        unit = text(CAN)
        self.assertIn("EnvironmentFile=/etc/powertune/powertune-appliance.conf", unit)
        self.assertIn(
            "ip link set ${PT_CAN_INTERFACE} type can bitrate ${PT_CAN_BITRATE} "
            "restart-ms ${PT_CAN_RESTART_MS}", unit)
        self.assertIn("ip link set ${PT_CAN_INTERFACE} up", unit)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("RemainAfterExit=yes", unit)
        self.assertIn("PowerTune CAN: interface=${PT_CAN_INTERFACE} bitrate=${PT_CAN_BITRATE}", unit)
        # Idempotent: link goes down before reconfiguration; no ignored failures
        # in the configuration path.
        self.assertLess(unit.index("down\n"), unit.index("type can bitrate"))
        for line in unit.splitlines():
            if line.startswith("ExecStart="):
                self.assertFalse(line.startswith("ExecStart=-"))

    def test_bridge_service_command(self):
        unit = text(BRIDGE)
        self.assertIn(
            "ExecStart=/usr/bin/kpro-powertune-bridge --can-interface "
            "${PT_CAN_INTERFACE} --profile ${PT_KPRO_PROFILE}", unit)
        self.assertIn("PowerTune K-Pro bridge: interface=${PT_CAN_INTERFACE} "
                      "profile=${PT_KPRO_PROFILE} destination=127.0.0.1:45454", unit)
        self.assertIn("EnvironmentFile=/etc/powertune/powertune-appliance.conf", unit)

    def test_bridge_ordering_and_restart(self):
        unit = text(BRIDGE)
        self.assertIn("Requires=powertune-can.service", unit)
        self.assertIn("After=powertune-can.service", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertRegex(unit, r"StartLimitBurst=\d+")
        self.assertRegex(unit, r"StartLimitIntervalSec=\d+")
        self.assertNotIn("powertunedash", unit)

    def test_dashboard_not_ordered_with_bridge(self):
        dash = text(FILES / "powertunedash.service")
        self.assertNotIn("kpro", dash)
        self.assertNotIn("powertune-can", dash)

    def test_no_diagnostic_logging(self):
        for path in (CAN, BRIDGE):
            self.assertNotIn("--diagnostic", text(path))
            self.assertNotIn("--summary", text(path))

    def test_forbidden_references(self):
        for path in (CAN, BRIDGE, CONF):
            content = text(path)
            for forbidden in ("can0", "/home/pi", "daemons",
                              "Licence", "startdaemon", "/etc/network/interfaces"):
                self.assertNotIn(forbidden, content, f"{path.name}: {forbidden}")

    def test_recipe_installs_and_enables_services(self):
        recipe = text(RECIPE)
        for name in ("powertune-can.service", "powertune-kpro-bridge.service",
                     "powertune-appliance.conf"):
            self.assertIn(f"file://{name}", recipe)
        self.assertRegex(
            recipe,
            r'SYSTEMD_SERVICE:\$\{PN\} = "[^"]*powertune-can\.service[^"]*'
            r'powertune-kpro-bridge\.service')
        self.assertIn('SYSTEMD_AUTO_ENABLE:${PN} = "enable"', recipe)
        self.assertIn("${systemd_system_unitdir}/powertune-can.service", recipe)
        self.assertIn("${sysconfdir}/powertune/powertune-appliance.conf", recipe)
        # Existing manually packaged utilities are preserved.
        for kept in ("pt-udp-sim", "pt-usb-can", "kpro-workload", "kpro-powertune-bridge"):
            self.assertIn(kept, recipe)

    def test_services_pulled_into_image(self):
        image = text(RECIPE_DIR.parents[1] / "recipes-core" / "packagegroups"
                     / "packagegroup-powertune-qt5-runtime.bb")
        self.assertIn("powertunedash", image)

    def test_bridge_runs_unprivileged_user_exists(self):
        self.assertIn("User=gauges", text(BRIDGE))
        self.assertIn("gauges", text(RECIPE))


if __name__ == "__main__":
    unittest.main()
