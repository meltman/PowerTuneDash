from contextlib import redirect_stdout
import re
import importlib.util
from io import StringIO
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SIM_PATH = ROOT / "tools" / "powertune-udp-sim.py"
SPEC = importlib.util.spec_from_file_location("powertune_udp_sim", SIM_PATH)
SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIM)


class UdpSimulatorTests(unittest.TestCase):
    def test_exact_udp_payload_serialization(self):
        self.assertEqual(SIM.serialize_record(179, "800"), b"179,800")

    def test_one_shot_values_support_positive_negative_and_decimal(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendto(self, payload, address):
                self.sent.append((payload, address))

        sock = FakeSocket()
        for value in ("800", "-12", "1.25"):
            SIM.announce_and_send(sock, 179, value, "rpm")
        self.assertEqual(
            [payload for payload, _ in sock.sent],
            [b"179,800", b"179,-12", b"179,1.25"],
        )
        self.assertTrue(
            all(address == (SIM.DEFAULT_HOST, SIM.DEFAULT_PORT) for _, address in sock.sent)
        )

    def test_one_shot_cli_sends_record(self):
        class FakeSocket:
            def __init__(self, *_):
                self.sent = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def sendto(self, payload, address):
                self.sent.append((payload, address))

        fake_socket = FakeSocket()
        with mock.patch.object(SIM.socket, "socket", return_value=fake_socket):
            with redirect_stdout(StringIO()):
                SIM.run(["--id", "179", "--value", "800"])
        self.assertEqual(
            fake_socket.sent, [(b"179,800", ("127.0.0.1", 45454))]
        )

    def test_sweep_includes_both_endpoints(self):
        self.assertEqual(
            SIM.sweep_values("800", "1250", "200"),
            ["800", "1000", "1200", "1250"],
        )

    def test_bounce_reverses_without_duplicate_endpoints(self):
        self.assertEqual(
            SIM.sweep_values("0", "2", "1", bounce=True),
            ["0", "1", "2", "1"],
        )

    def test_named_preset_mappings(self):
        self.assertEqual(
            {name: SIM.PRESETS[name][0] for name in SIM.PRESETS},
            {"rpm": 179, "map": 155, "speed": 199, "coolant": 221, "tps": 210},
        )
        receiver = (ROOT / "udpreceiver.cpp").read_text()
        expected_setters = {
            "rpm": "setrpm",
            "map": "setMAP",
            "speed": "setSpeed",
            "coolant": "setWatertemp",
            "tps": "setTPS",
        }
        for signal, (identifier, _) in SIM.PRESETS.items():
            case = re.search(
                rf"\bcase\s+{identifier}\s*:(.*?)(?=\n\s*case\s+\d+\s*:|\Z)",
                receiver,
                re.DOTALL,
            )
            self.assertIsNotNone(case)
            self.assertIn(f"m_dashboard->{expected_setters[signal]}(", case.group(1))

    def test_scenario_parsing(self):
        scenario = {
            "interval_ms": 100,
            "signals": {
                "rpm": [800, 1500],
                "speed": [0, 10],
                "map": [30, 40],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            interval, records = SIM.load_scenario(path)
        self.assertEqual(interval, 100)
        self.assertEqual(
            [(identifier, label, values) for identifier, label, values in records],
            [
                (179, "rpm", [800, 1500]),
                (199, "speed", [0, 10]),
                (155, "MAP", [30, 40]),
            ],
        )

    def test_timed_event_scenario_sends_at_absolute_offsets_and_runs_duration(self):
        data = {
            "format": "powertune-udp-events-v1",
            "duration_ms": 100,
            "events": [
                {"at_ms": 0, "identifier": 179, "value": "800"},
                {"at_ms": 20, "identifier": 179, "value": "900"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timed.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            duration_ms, events = SIM.load_timed_scenario(path)
        self.assertEqual(duration_ms, 100)

        now = [0.0]
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendto(self, payload, address):
                self.sent.append((payload, address, now[0]))

        sock = FakeSocket()
        with redirect_stdout(StringIO()):
            SIM.send_timed_events(sock, duration_ms, events, lambda: now[0], sleep)
        self.assertEqual(
            [(payload, timestamp) for payload, _address, timestamp in sock.sent],
            [(b"179,800", 0.0), (b"179,900", 0.02)],
        )
        self.assertAlmostEqual(now[0], 0.1)
        self.assertEqual(sleeps, [0.02, 0.08])

    def test_timed_scenario_rejects_out_of_order_events(self):
        data = {
            "format": "powertune-udp-events-v1",
            "duration_ms": 100,
            "events": [
                {"at_ms": 20, "identifier": 179, "value": "800"},
                {"at_ms": 10, "identifier": 179, "value": "900"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timed.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ordered"):
                SIM.load_timed_scenario(path)

    def test_default_destination_is_localhost(self):
        args = SIM.parse_args(["--id", "179", "--value", "800"])
        self.assertEqual(
            (SIM.DEFAULT_HOST, SIM.DEFAULT_PORT), ("127.0.0.1", 45454)
        )
        self.assertEqual(args.identifier, 179)

    def test_protocol_documentation_covers_every_receiver_identifier(self):
        receiver = (ROOT / "udpreceiver.cpp").read_text()
        documented = (ROOT / "docs" / "DAEMON_UDP_PROTOCOL.md").read_text()
        cases = {
            int(value)
            for value in re.findall(r"\bcase\s+(\d+)\s*:", receiver)
        }
        table = documented.split("## Identifier dispatch table\n", 1)[1].split(
            "\n## Malformed and repeated input behavior", 1
        )[0]
        documented_ids = {
            int(match)
            for match in re.findall(r"^\|\s*(\d+)\s*\|", table, re.MULTILINE)
        }
        self.assertEqual(len(cases), 407)
        self.assertEqual(documented_ids, cases)
        active_rows = re.findall(r"^\|\s*\d+\s*\|\s*`set\w+`", table, re.MULTILINE)
        self.assertEqual(len(active_rows), 378)
        self.assertNotIn("format marker in a bundled binary", table)
        self.assertNotIn("Hondata", table)

    def test_device_validated_rpm_example_serializes_unchanged(self):
        self.assertEqual(SIM.serialize_record(179, "2500"), b"179,2500")


if __name__ == "__main__":
    unittest.main()
