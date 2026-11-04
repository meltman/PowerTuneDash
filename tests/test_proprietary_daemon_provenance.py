import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProprietaryDaemonProvenanceTests(unittest.TestCase):
    def test_active_tree_has_no_daemons_directory(self):
        self.assertFalse((ROOT / "daemons").exists())

    def test_application_project_keeps_receiver_without_daemon_packaging(self):
        project = (ROOT / "PowertuneQMLGui.pro").read_text(encoding="utf-8")
        self.assertIn("udpreceiver.cpp", project)
        self.assertIn("udpreceiver.h", project)
        self.assertNotIn("daemons/", project)
        self.assertNotIn("Hondatad", project)
        self.assertNotIn("HondataS300", project)
        self.assertNotIn("LicenceRequest", project)

    def test_legacy_updater_cannot_restore_the_removed_directory(self):
        updater = (ROOT / "updatedaemons.sh").read_text(encoding="utf-8")
        self.assertIn("Skipping legacy proprietary ECU daemon updates", updater)
        self.assertNotIn("/home/pi/src/daemons", updater)
        self.assertNotIn("/home/pi/daemons", updater)

    def test_udp_simulator_and_protocol_documentation_remain_available(self):
        self.assertTrue((ROOT / "tools" / "powertune-udp-sim.py").is_file())
        protocol = (ROOT / "docs" / "DAEMON_UDP_PROTOCOL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "This document describes the UDP input interface implemented by "
            "the GPLv3-licensed PowerTuneDash source.",
            protocol,
        )
        self.assertIn(
            "It does not document or derive from the implementation of "
            "PowerTuneDigital's proprietary ECU daemon binaries.",
            protocol,
        )
        self.assertIn(
            "PowerTuneDash `udpreceiver` source and Device 0 behavioral validation",
            protocol,
        )

    def test_integration_provenance_and_hondata_rule_are_documented(self):
        provenance = (ROOT / "docs" / "LICENSING_AND_PROVENANCE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("official Hondata", provenance)
        self.assertIn("independently collected bus observations", provenance)
        self.assertIn("No proprietary ECU daemon implementation is required", provenance)
        self.assertTrue((ROOT / "LICENSE").is_file())

    def test_agent_instructions_prohibit_reintroducing_proprietary_daemons(self):
        required = (
            "Do not add, redistribute, execute, reverse engineer, modify, or "
            "depend upon PowerTuneDigital proprietary ECU daemon binaries in "
            "this fork."
        )
        for path in (
            ROOT / ".github" / "copilot-instructions.md",
            ROOT / "docs" / "AI_HANDOFF.md",
        ):
            with self.subTest(path=path):
                instructions = " ".join(
                    path.read_text(encoding="utf-8").split()
                )
                self.assertIn(required, instructions)
                self.assertIn(
                    "Independent integration publishers should target the documented PowerTune UDP",
                    instructions,
                )


if __name__ == "__main__":
    unittest.main()
