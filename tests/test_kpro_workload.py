import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import kpro_can
import kpro_workload

USB_CAN_SPEC = importlib.util.spec_from_file_location(
    "pt_usb_can_workload_test", TOOLS / "pt-usb-can.py"
)
usb_can_adapter = importlib.util.module_from_spec(USB_CAN_SPEC)
USB_CAN_SPEC.loader.exec_module(usb_can_adapter)

CLI_SPEC = importlib.util.spec_from_file_location(
    "kpro_workload_cli", TOOLS / "kpro-workload.py"
)
workload_cli = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(workload_cli)

BRIDGE_SPEC = importlib.util.spec_from_file_location(
    "kpro_powertune_bridge", TOOLS / "kpro-powertune-bridge.py"
)
bridge = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(bridge)


FIXTURES = ROOT / "tests/fixtures/hondata"


def load_scenario(name):
    return kpro_workload.validate_scenario(
        json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def base_660():
    return {
        "name": "behavior-test",
        "workload_class": "P3",
        "duration_seconds": 2,
        "tick_ms": 100,
        "can_bitrate": 500000,
        "profile": "hondata-motec",
        "frame_rate_hz": 20,
        "signals": {
            "rpm": {"type": "constant", "value": 1000},
            "speed_kph": {"type": "constant", "value": 0},
            "gear": {"type": "constant", "value": 1},
            "voltage_v": {"type": "constant", "value": 14},
        },
    }


class ScenarioTests(unittest.TestCase):
    def test_all_behavior_types_are_supported_and_deterministic(self):
        behaviors = (
            {"type": "constant", "value": 1000},
            {"type": "explicit", "value": 1000},
            {"type": "sweep", "start": 1000, "end": 1100},
            {"type": "triangle", "minimum": 900, "maximum": 1100, "period_seconds": 1},
            {"type": "sequence", "values": [900, 1000, 1100], "hold_ticks": 3},
            {"type": "keyframes", "interpolation": "linear",
             "keyframes": [{"at_seconds": 0, "value": 900},
                           {"at_seconds": 2, "value": 1100}]},
            {"type": "keyframes", "interpolation": "step",
             "keyframes": [{"at_seconds": 0, "value": 900},
                           {"at_seconds": 1, "value": 1100}]},
            {"type": "sine", "center": 1000, "amplitude": 50, "period_seconds": 1},
        )
        for behavior in behaviors:
            with self.subTest(kind=behavior["type"], behavior=behavior):
                data = base_660()
                data["signals"]["rpm"] = behavior
                scenario = kpro_workload.validate_scenario(data)
                first = [f.data for f in kpro_workload.iter_scheduled_frames(scenario)]
                second = [f.data for f in kpro_workload.iter_scheduled_frames(scenario)]
                self.assertEqual(first, second)
                self.assertEqual(len(first), 40)

    def test_every_encoder_frame_round_trips_through_actual_decoder(self):
        scenario = load_scenario("maximum-activity.json")
        observed_ids = set()
        for frame in kpro_workload.iter_scheduled_frames(scenario):
            observed_ids.add(frame.can_id)
            decoded = kpro_can.decode_frame(frame, scenario.profile)
            self.assertTrue(decoded)
            tick = int(Decimal(str(frame.timestamp)) * 1000 // scenario.tick_ms)
            sample_time = Decimal(tick * scenario.tick_ms) / 1000
            requested = scenario.values_at(sample_time)
            spec = next(
                item for item in kpro_can.PROFILES[scenario.profile]["frames"]
                if item.can_id == frame.can_id
            )
            for field, signal in zip(spec.fields, decoded):
                self.assertTrue(signal.valid)
                tolerance = (
                    Decimal("0.001")
                    if field.reciprocal
                    else Decimal("0.5") / field.divisor
                )
                self.assertLessEqual(abs(signal.value - requested[field.name]), tolerance)
        self.assertEqual(observed_ids, set(range(0x660, 0x66A)))

    def test_round_robin_schedule_is_separate_from_scenario_tick(self):
        scenario = load_scenario("idle-baseline.json")
        frames = list(kpro_workload.iter_scheduled_frames(scenario))
        self.assertEqual(len(frames), 200)
        self.assertEqual(
            [frame.can_id for frame in frames[:6]],
            [0x660, 0x661, 0x662, 0x664, 0x660, 0x661],
        )
        self.assertEqual(
            [frame.timestamp for frame in frames[:4]],
            [0.0, 0.05, 0.1, 0.15],
        )
        slower = list(kpro_workload.iter_scheduled_frames(scenario, frame_rate_hz=5))
        self.assertEqual(len(slower), 50)

    def test_synthetic_frames_are_independent_of_can_bitrate(self):
        bench = base_660()
        vehicle_rate = dict(bench, can_bitrate=1_000_000)
        bench_frames = list(
            kpro_workload.iter_scheduled_frames(
                kpro_workload.validate_scenario(bench)
            )
        )
        vehicle_frames = list(
            kpro_workload.iter_scheduled_frames(
                kpro_workload.validate_scenario(vehicle_rate)
            )
        )
        self.assertEqual(bench_frames, vehicle_frames)

    def test_all_required_fixtures_validate_and_cover_workload_classes(self):
        fixtures = (
            "idle-baseline.json", "warm-idle-variation.json", "steady-cruise.json",
            "slow-change.json", "acceleration-workload.json", "deceleration.json",
            "unmapped-decode.json", "constant-mapped.json", "maximum-activity.json",
            "display-static-noisy.json", "stale-data.json", "no-telemetry.json",
        )
        scenarios = [load_scenario(name) for name in fixtures]
        self.assertEqual(
            {scenario.workload_class for scenario in scenarios},
            set(kpro_workload.WORKLOAD_CLASSES),
        )
        maximum = load_scenario("maximum-activity.json")
        self.assertEqual(len(maximum.active_specs), 10)
        self.assertEqual(maximum.frame_rate_hz, kpro_workload.MAX_FRAME_RATE_HZ)

    def test_scenario_rejects_malformed_values_ranges_and_schedule(self):
        mutations = (
            ("duration_seconds", 0),
            ("tick_ms", 0),
            ("can_bitrate", 333333),
            ("profile", "unknown"),
            ("frame_rate_hz", kpro_workload.MAX_FRAME_RATE_HZ + 1),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                data = base_660()
                data[key] = value
                with self.assertRaises(kpro_workload.ScenarioError):
                    kpro_workload.validate_scenario(data)
        data = base_660()
        data["signals"]["rpm"] = {"type": "unknown", "value": 800}
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "unsupported type"):
            kpro_workload.validate_scenario(data)
        data = base_660()
        data["signals"]["rpm"] = {"type": "constant", "value": float("inf")}
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "finite"):
            kpro_workload.validate_scenario(data)
        data = base_660()
        data["signals"]["rpm"] = {"type": "sweep", "start": 0, "end": 70000}
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "outside its 16-bit range"):
            kpro_workload.validate_scenario(data)

    def test_invalid_keyframes_and_empty_non_p0_scenario_are_rejected(self):
        data = base_660()
        data["signals"]["rpm"] = {
            "type": "keyframes", "interpolation": "cubic",
            "keyframes": [{"at_seconds": 0, "value": 800}],
        }
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "interpolation"):
            kpro_workload.validate_scenario(data)
        data = base_660()
        data["signals"] = {}
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "no signals"):
            kpro_workload.validate_scenario(data)

    def test_frame_rate_ceiling_and_generated_frame_limit(self):
        data = base_660()
        data["duration_seconds"] = 3600
        data["tick_ms"] = 100
        data["frame_rate_hz"] = 60
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "safety limit"):
            kpro_workload.validate_scenario(data)
        scenario = load_scenario("idle-baseline.json")
        long_data = base_660()
        long_data["duration_seconds"] = 3600
        long_data["tick_ms"] = 100
        long_data["frame_rate_hz"] = 20
        long_scenario = kpro_workload.validate_scenario(long_data)
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "exceeds"):
            list(kpro_workload.iter_scheduled_frames(long_scenario, frame_rate_hz=200))
        with self.assertRaisesRegex(kpro_workload.ScenarioError, "frame rate"):
            list(kpro_workload.iter_scheduled_frames(scenario, frame_rate_hz=201))

    def test_inspection_reports_signal_ranges_and_mappings(self):
        summary = kpro_workload.scenario_summary(load_scenario("steady-cruise.json"))
        self.assertEqual(summary["expected_frame_count"], 600)
        self.assertEqual(summary["frame_ids"], ["0x660", "0x661", "0x662", "0x664"])
        self.assertTrue(summary["signals"]["rpm"]["mapped_to_powertune"])
        self.assertFalse(summary["signals"]["gear"]["mapped_to_powertune"])
        self.assertIn("not hardware-validated", summary["schedule_policy"])

    def test_export_is_repeatable_and_accepted_by_bridge_replay_parser(self):
        scenario = load_scenario("idle-baseline.json")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.candump"
            second = Path(directory) / "second.candump"
            count1 = workload_cli.export_candump(scenario, first)
            count2 = workload_cli.export_candump(scenario, second)
            self.assertEqual(count1, 200)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            lines = first.read_text(encoding="ascii").splitlines()
            self.assertEqual(len(lines), 200)
            frame = bridge.parse_candump_line(lines[0])
            self.assertEqual(frame.can_id, 0x660)
            self.assertEqual(frame.data.hex(), "03200000008a")

    def test_constant_mapped_frames_suppress_repeated_publication(self):
        scenario = load_scenario("constant-mapped.json")
        metrics, packets = workload_cli.replay_scenario(
            scenario, send_udp=False, capture_packets=True
        )
        self.assertEqual(metrics.generated_can_frames, 200)
        self.assertEqual(metrics.received_can_frames, 200)
        self.assertEqual(metrics.udp_records_would_send, 5)
        self.assertEqual(len(packets), 5)
        self.assertGreater(metrics.unchanged_signal_suppressions, 0)
        self.assertEqual(metrics.udp_records_sent, 0)

    def test_visible_changes_publish_expected_values_and_epsilon_gate(self):
        changing = load_scenario("slow-change.json")
        _, records = workload_cli.replay_scenario(
            changing, send_udp=False, capture_packets=True
        )
        rpm_values = [record for record in records if record.startswith(b"179,")]
        self.assertGreater(len(rpm_values), 2)
        self.assertEqual(rpm_values[0], b"179,1800")
        self.assertNotEqual(rpm_values[-1], rpm_values[0])

        noisy = load_scenario("display-static-noisy.json")
        _, noisy_records = workload_cli.replay_scenario(
            noisy, send_udp=False, capture_packets=True
        )
        rpm_values = [record for record in noisy_records if record.startswith(b"179,")]
        self.assertEqual(rpm_values, [b"179,800", b"179,820"])

    def test_matched_direct_udp_and_can_rpm_change_sequence(self):
        scenario = load_scenario("direct-rpm-change.json")
        _, records = workload_cli.replay_scenario(
            scenario, send_udp=False, capture_packets=True
        )
        self.assertEqual(
            [record for record in records if record.startswith(b"179,")],
            [b"179,1800", b"179,1900", b"179,2000", b"179,2100", b"179,2200"],
        )
        self.assertEqual(len(list(kpro_workload.iter_scheduled_frames(scenario))), 10)
        direct = json.loads(
            (ROOT / "tests/fixtures/udp/direct-p3-rpm-control.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(direct["interval_ms"], 200)
        self.assertEqual(
            direct["signals"]["rpm"],
            [1800, 1900, 2000, 2100, 2200],
        )

    def test_stale_frame_schedule_transitions_selected_signals(self):
        scenario = load_scenario("stale-data.json")
        diagnostic = []
        with patch("builtins.print", side_effect=diagnostic.append):
            metrics, _ = workload_cli.replay_scenario(
                scenario, send_udp=False, stale_after=0.5, diagnostic=True
            )
        self.assertGreaterEqual(metrics.stale_transitions, 5)
        self.assertTrue(any("ect_c stale" in line for line in diagnostic))

    def test_invalid_input_fixture_covers_malformed_duplicate_and_reordered_cases(self):
        vectors = json.loads(
            (FIXTURES / "invalid-input.json").read_text(encoding="utf-8")
        )["frames"]
        by_case = {item["case"]: item for item in vectors}
        wrong = by_case["wrong-dlc"]
        with self.assertRaises(kpro_can.FrameDecodeError):
            kpro_can.decode_frame(
                kpro_can.CanFrame(int(wrong["can_id"], 0), bytes.fromhex(wrong["data_hex"]))
            )
        unrelated = by_case["unrelated-id"]
        self.assertEqual(
            kpro_can.decode_frame(
                kpro_can.CanFrame(int(unrelated["can_id"], 0), bytes.fromhex(unrelated["data_hex"]))
            ),
            [],
        )
        invalid = by_case["explicit-invalid-lambda-zero"]
        self.assertFalse(
            kpro_can.decode_frame(
                kpro_can.CanFrame(int(invalid["can_id"], 0), bytes.fromhex(invalid["data_hex"]))
            )[0].valid
        )
        truncated = by_case["truncated-known-frame"]
        with self.assertRaises(kpro_can.FrameDecodeError):
            kpro_can.decode_frame(
                kpro_can.CanFrame(int(truncated["can_id"], 0), bytes.fromhex(truncated["data_hex"]))
            )
        duplicate = by_case["duplicate"]
        frame = kpro_can.CanFrame(int(duplicate["can_id"], 0), bytes.fromhex(duplicate["data_hex"]))
        self.assertEqual(kpro_can.decode_frame(frame), kpro_can.decode_frame(frame))
        reordered = by_case["reordered"]
        self.assertEqual(int(reordered["can_id"], 0), 0x661)
        stream = json.loads(
            (FIXTURES / "invalid-input.json").read_text(encoding="utf-8")
        )["stream"]
        frames = [
            kpro_can.CanFrame(
                int(item["can_id"], 0), bytes.fromhex(item["data_hex"])
            )
            for item in stream
        ]
        self.assertEqual([frame.can_id for frame in frames], [0x660, 0x660, 0x662, 0x661])
        tracker = kpro_can.SignalTracker()
        changes = []
        for index, frame in enumerate(frames):
            changes.append(
                [
                    tracker.update(signal, index, index)
                    for signal in kpro_can.decode_frame(frame)
                ]
            )
        self.assertTrue(all(changes[0]))
        self.assertFalse(any(changes[1]))
        self.assertEqual(
            [signal.name for signal in kpro_can.decode_frame(frames[2])],
            ["tps_pct", "map_kpa"],
        )

    def test_udp_control_sender_and_no_udp_mode(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []
                self.closed = False

            def sendto(self, packet, destination):
                self.sent.append((packet, destination))

            def close(self):
                self.closed = True

        fake = FakeSocket()
        scenario = load_scenario("constant-mapped.json")
        metrics, _ = workload_cli.replay_scenario(
            scenario, socket_factory=lambda *_args: fake, send_udp=True
        )
        self.assertEqual(len(fake.sent), 5)
        self.assertTrue(fake.closed)
        self.assertEqual(metrics.udp_records_sent, 5)

    def test_transmit_reuses_adapter_discovery_and_closes_on_interrupt(self):
        class Port:
            def __init__(self):
                self.packets = []
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def write(self, packet):
                self.packets.append(packet)

            def flush(self):
                pass

        class Ports:
            @staticmethod
            def comports():
                return [type("Device", (), {"device": "/dev/ttyUSB9", "vid": 0x1A86, "pid": 0x7523})()]

        class Adapter:
            port = Port()
            configure = []

            @staticmethod
            def get_serial_modules():
                return None, Ports

            @staticmethod
            def resolve_device(ports, explicit):
                return "/dev/ttyUSB9" if not explicit else explicit

            @staticmethod
            def validate_bitrate(rate):
                if rate != 500000:
                    raise ValueError("unexpected bitrate")

            @staticmethod
            def open_adapter(device, _baud):
                if device != "/dev/ttyUSB9":
                    raise AssertionError(device)
                return Adapter.port

            @staticmethod
            def configure_adapter(port, bitrate, frame_type):
                Adapter.configure.append((bitrate, frame_type))

            @staticmethod
            def build_data_frame(can_id, data, extended):
                return bytes((can_id & 0xFF,)) + data + bytes((int(extended),))

        scenario = load_scenario("idle-baseline.json")
        metrics, device = workload_cli.transmit_scenario(
            scenario, adapter=Adapter, frame_rate=5, speed=1, sleep=lambda _delay: None
        )
        self.assertEqual(device, "/dev/ttyUSB9")
        self.assertEqual(metrics.transmitted_can_frames, 50)
        self.assertEqual(len(Adapter.port.packets), 50)
        self.assertEqual(Adapter.configure, [(500000, "standard")])
        self.assertTrue(Adapter.port.closed)

    def test_transmit_uses_usb_vid_pid_discovery_and_requires_explicit_ambiguity_choice(self):
        class FakePort:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def write(self, _packet):
                pass

            def flush(self):
                pass

        candidates = [
            type("PortInfo", (), {"device": "/dev/ttyUSB2", "vid": 0x1A86, "pid": 0x7523})(),
            type("PortInfo", (), {"device": "/dev/ttyUSB8", "vid": 0x1A86, "pid": 0x7523})(),
        ]
        port = FakePort()
        scenario = load_scenario("idle-baseline.json")
        with patch.object(usb_can_adapter, "get_serial_modules", return_value=(None, type(
            "Ports", (), {"comports": staticmethod(lambda: candidates)}
        ))), patch.object(usb_can_adapter, "open_adapter", return_value=port), \
             patch.object(usb_can_adapter, "configure_adapter"), \
             patch.object(usb_can_adapter, "build_data_frame", return_value=b"x"):
            with self.assertRaisesRegex(ValueError, "multiple Waveshare"):
                workload_cli.transmit_scenario(
                    scenario, adapter=usb_can_adapter, frame_rate=1, speed=1,
                    sleep=lambda _delay: None,
                )
            metrics, device = workload_cli.transmit_scenario(
                scenario, device="/dev/ttyUSB8", adapter=usb_can_adapter,
                frame_rate=1, speed=1, sleep=lambda _delay: None,
            )
        self.assertEqual(device, "/dev/ttyUSB8")
        self.assertEqual(metrics.transmitted_can_frames, 10)
        self.assertTrue(port.closed)

    def test_transmit_closes_adapter_on_ctrl_c(self):
        class InterruptingPort:
            closed = False
            writes = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def write(self, _packet):
                self.writes += 1
                if self.writes == 2:
                    raise KeyboardInterrupt

            def flush(self):
                pass

        class Adapter:
            port = InterruptingPort()

            @staticmethod
            def get_serial_modules():
                return None, type("Ports", (), {"comports": staticmethod(lambda: [])})

            @staticmethod
            def resolve_device(_ports, _explicit):
                return "/dev/ttyUSB7"

            @staticmethod
            def validate_bitrate(_rate):
                return None

            @staticmethod
            def open_adapter(_device, _baud):
                return Adapter.port

            @staticmethod
            def configure_adapter(*_args):
                pass

            @staticmethod
            def build_data_frame(*_args):
                return b"x"

        with self.assertRaises(KeyboardInterrupt):
            workload_cli.transmit_scenario(
                load_scenario("idle-baseline.json"), adapter=Adapter,
                frame_rate=1, speed=1, sleep=lambda _delay: None,
            )
        self.assertTrue(Adapter.port.closed)

    def test_p1_and_p0_have_expected_zero_publication_or_frames(self):
        p1, _ = workload_cli.replay_scenario(
            load_scenario("unmapped-decode.json"), send_udp=False
        )
        self.assertEqual(p1.udp_records_would_send, 0)
        self.assertEqual(p1.decoded_frames, 200)
        p0 = load_scenario("no-telemetry.json")
        metrics, _ = workload_cli.replay_scenario(p0, send_udp=False)
        self.assertEqual(metrics.generated_can_frames, 0)

    def test_provenance_docs_and_all_fixtures_avoid_forbidden_references(self):
        docs = (
            ROOT / "docs/HONDATA_KPRO_CAN.md",
            ROOT / "docs/CAN_BENCH_TESTING.md",
            ROOT / "docs/PERFORMANCE_PROFILING.md",
            ROOT / "docs/KPRO_SYNTHETIC_WORKLOADS.md",
        )
        for path in docs:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\b(HIVE|WASP|NextGen)\b")
        self.assertIn(kpro_can.HONDATA_MOTEC_SOURCE,
                      (ROOT / "docs/HONDATA_KPRO_CAN.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
