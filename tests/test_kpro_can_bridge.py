import importlib.util
import json
from pathlib import Path
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import kpro_can
import powertune_udp

BRIDGE_SPEC = importlib.util.spec_from_file_location(
    "kpro_powertune_bridge", TOOLS / "kpro-powertune-bridge.py"
)
bridge = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(bridge)


class KProDecoderTests(unittest.TestCase):
    def test_published_catalog_frame_ids_and_derived_lengths(self):
        self.assertEqual(
            [spec.can_id for spec in kpro_can.HONDATA_MOTEC_FRAMES],
            list(range(0x660, 0x66A)),
        )
        self.assertEqual(
            [spec.can_id for spec in kpro_can.AIM_FRAMES],
            [0x5F0, 0x5F2, 0x5F3, 0x5F4, 0x5F6, 0x5F7, 0x5FB,
             0x5FC, 0x667, 0x668, 0x669],
        )
        for profile in kpro_can.PROFILES.values():
            for spec in profile["frames"]:
                self.assertGreater(spec.derived_dlc, 0)
                self.assertLessEqual(spec.derived_dlc, 8)

    def test_every_documented_field_decodes_at_raw_boundaries(self):
        for profile_name, profile in kpro_can.PROFILES.items():
            for spec in profile["frames"]:
                for field in spec.fields:
                    minimum = -(1 << (field.bits - 1)) if field.signed else 0
                    maximum = (1 << (field.bits - (1 if field.signed else 0))) - 1
                    candidates = (minimum, (minimum + maximum) // 2, maximum)
                    for raw in candidates:
                        with self.subTest(
                            profile=profile_name, can_id=spec.can_id,
                            signal=field.name, raw=raw,
                        ):
                            data = bytearray(spec.derived_dlc)
                            offset = 0
                            for item in spec.fields:
                                if item is field:
                                    break
                                offset += item.byte_width
                            data[offset:offset + field.byte_width] = raw.to_bytes(
                                field.byte_width, "big", signed=field.signed
                            )
                            decoded = kpro_can.decode_frame(
                                kpro_can.CanFrame(spec.can_id, bytes(data)), profile_name
                            )
                            signal = next(item for item in decoded if item.name == field.name)
                            if field.reciprocal and raw == 0:
                                self.assertFalse(signal.valid)
                                self.assertIsNone(signal.value)
                            else:
                                self.assertTrue(signal.valid)
                                self.assertIsInstance(signal.value, Decimal)

    def test_known_conversion_vectors_and_signed_ignition(self):
        vectors = (
            ("hondata-motec", 0x660, bytes.fromhex("09C403E8038A"),
             {"rpm": Decimal(2500), "speed_kph": Decimal(1000),
              "gear": Decimal(3), "voltage_v": Decimal("13.8")}),
            ("hondata-motec", 0x662, bytes.fromhex("002303E8"),
             {"tps_pct": Decimal(35), "map_kpa": Decimal(100)}),
            ("hondata-motec", 0x663, bytes.fromhex("09C4FFFB"),
             {"injector_ms": Decimal("2.5"), "ignition_deg": Decimal(-5)}),
            ("hondata-motec", 0x664, bytes.fromhex("8000"),
             {"lambda": Decimal(1)}),
            ("hondata-motec", 0x667, bytes.fromhex("1000200030004000"),
             {"analog0": Decimal(4096) / Decimal("819.2"),
              "analog1": Decimal(8192) / Decimal("819.2")}),
            ("aim", 0x5F0, bytes.fromhex("09C40023038A64"),
             {"rpm": Decimal(2500), "tps_pct": Decimal(35),
              "gear": Decimal(3), "voltage_v": Decimal("13.8"),
              "speed_kph": Decimal(100)}),
        )
        for profile, can_id, data, expected in vectors:
            with self.subTest(profile=profile, can_id=can_id):
                result = {
                    signal.name: signal.value
                    for signal in kpro_can.decode_frame(
                        kpro_can.CanFrame(can_id, data), profile
                    )
                }
                for name, value in expected.items():
                    self.assertEqual(result[name], value)

    def test_known_profile_with_wrong_dlc_is_rejected(self):
        with self.assertRaises(kpro_can.FrameDecodeError):
            kpro_can.decode_frame(kpro_can.CanFrame(0x660, b"\x00" * 7))
        with self.assertRaises(kpro_can.FrameDecodeError):
            kpro_can.decode_frame(kpro_can.CanFrame(0x660, b"\x00" * 9))

    def test_unrelated_extended_and_remote_frames_are_ignored(self):
        self.assertEqual(kpro_can.decode_frame(kpro_can.CanFrame(0x123, b"\0")), [])
        self.assertEqual(
            kpro_can.decode_frame(kpro_can.CanFrame(0x660, b"\0" * 8, extended=True)),
            [],
        )
        self.assertEqual(
            kpro_can.decode_frame(kpro_can.CanFrame(0x660, b"", remote=True)),
            [],
        )

    def test_lambda_zero_is_invalid_not_a_fabricated_numeric_value(self):
        signal = kpro_can.decode_frame(
            kpro_can.CanFrame(0x664, b"\0\0")
        )[0]
        self.assertFalse(signal.valid)
        self.assertIsNone(signal.value)
        self.assertEqual(signal.invalid_reason, "raw lambda is zero")

    def test_reusable_decoder_has_no_hardware_or_power_tune_assumptions(self):
        source = (TOOLS / "kpro_can.py").read_text(encoding="utf-8").lower()
        for forbidden in ("can0", "canc", "cane", "udp", "socket", "identifier,value"):
            self.assertNotIn(forbidden, source)

    def test_signal_freshness_valid_invalid_and_stale_transitions(self):
        tracker = kpro_can.SignalTracker()
        self.assertEqual(tracker.get_state("rpm").validity, "unavailable")
        signal = kpro_can.DecodedSignal("rpm", Decimal(800), "rpm", 0x660)
        self.assertTrue(tracker.update(signal, 10.0, 1.0))
        self.assertFalse(tracker.update(signal, 10.1, 1.1))
        self.assertEqual(tracker.mark_stale(11.0, 0.5), ["rpm"])
        self.assertEqual(tracker.states["rpm"].validity, "stale")
        invalid = kpro_can.DecodedSignal(
            "lambda", None, "lambda", 0x664, False, "raw lambda is zero"
        )
        self.assertTrue(tracker.update(invalid, 11.1, 2.0))
        self.assertEqual(tracker.states["lambda"].validity, "invalid")
        self.assertEqual(tracker.mark_stale(20.0, 0.5), [])

    def test_scenario_encoder_uses_decoder_definitions_and_preserves_order(self):
        fixture = ROOT / "tests/fixtures/hondata/acceleration.json"
        scenario = json.loads(fixture.read_text(encoding="utf-8"))
        delays = []
        frames = list(bridge.iter_scenario(scenario, speed=2.0, sleep=delays.append))
        self.assertEqual(
            [frame.can_id for frame in frames[:3]], [0x660, 0x661, 0x662]
        )
        self.assertEqual(delays, [0.05] * (len(scenario["events"]) - 1))
        for event, start in zip(scenario["events"], range(0, len(frames), 3)):
            decoded = {}
            for frame in frames[start:start + 3]:
                decoded.update({
                    signal.name: signal.value
                    for signal in kpro_can.decode_frame(frame)
                })
            expected = {
                name: Decimal(value)
                for name, value in event["expected"].items()
            }
            for name, value in expected.items():
                self.assertEqual(decoded[name], value, event["name"])

    def test_scenario_profile_fallback_and_invalid_timing(self):
        scenario = {
            "events": [{"at_ms": 0, "signals": {"rpm": 2500}}],
        }
        frames = list(bridge.iter_scenario(scenario, default_profile="aim"))
        self.assertEqual([frame.can_id for frame in frames], [0x5F0])
        self.assertEqual(
            kpro_can.decode_frame(frames[0], "aim")[0].value, Decimal(2500)
        )
        for invalid_at_ms in (0.5, True, "10"):
            with self.subTest(at_ms=invalid_at_ms):
                scenario["events"][0]["at_ms"] = invalid_at_ms
                with self.assertRaisesRegex(ValueError, "must be integers"):
                    list(bridge.iter_scenario(scenario))
        with self.assertRaisesRegex(ValueError, "finite nonnegative"):
            list(bridge.iter_scenario(scenario, speed=float("nan")))

    def test_scenario_encoder_rejects_non_numeric_and_nonfinite_values(self):
        for value in ("not-a-number", float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite number|decimal number"):
                    kpro_can.encode_signals({"rpm": value})

    def test_candump_replay_order_and_speed_control(self):
        fixture = ROOT / "tests/fixtures/hondata/representative.candump"
        delays = []
        frames = list(
            bridge.iter_replay(
                fixture.read_text(encoding="ascii").splitlines(),
                speed=2.0,
                sleep=delays.append,
            )
        )
        self.assertEqual([frame.can_id for frame in frames], list(range(0x660, 0x66A)))
        self.assertEqual(len(delays), 9)
        self.assertTrue(all(abs(delay - 0.005) < 1e-7 for delay in delays))
        self.assertEqual(frames[0].timestamp, 1700000000.0)
        with self.assertRaisesRegex(ValueError, "CAN FD"):
            bridge.parse_candump_line("canE 123##11223344")
        with self.assertRaisesRegex(ValueError, "8 bytes"):
            bridge.parse_candump_line("canE 123#001122334455667788")

    def test_edge_fixture_covers_invalid_malformed_and_unrelated_frames(self):
        fixture = ROOT / "tests/fixtures/hondata/edge_cases.candump"
        frames = [
            bridge.parse_candump_line(line)
            for line in fixture.read_text(encoding="ascii").splitlines()
        ]
        lambda_signal = kpro_can.decode_frame(frames[0])[0]
        self.assertFalse(lambda_signal.valid)
        with self.assertRaises(kpro_can.FrameDecodeError):
            kpro_can.decode_frame(frames[1])
        self.assertEqual(kpro_can.decode_frame(frames[2]), [])

    def test_socketcan_input_requires_interface_and_closes_socket(self):
        class FakeSocket:
            def __init__(self):
                self.bound = None
                self.closed = False

            def bind(self, address):
                self.bound = address

            def settimeout(self, _timeout):
                pass

            def close(self):
                self.closed = True

        fake_socket = FakeSocket()
        with self.assertRaises(ValueError):
            bridge.SocketCanSource("")
        with bridge.SocketCanSource(
            "testbus", socket_factory=lambda *_args: fake_socket
        ) as source:
            self.assertEqual(source.interface, "testbus")
            self.assertEqual(fake_socket.bound, ("testbus",))
        self.assertTrue(fake_socket.closed)

    def test_udp_socket_context_closes_cleanly(self):
        class FakeSocket:
            closed = False

            def close(self):
                self.closed = True

        fake_socket = FakeSocket()
        with bridge.open_udp_socket(lambda *_args: fake_socket):
            self.assertFalse(fake_socket.closed)
        self.assertTrue(fake_socket.closed)

    def test_cli_requires_explicit_socketcan_interface_or_other_input(self):
        parser = bridge.make_parser()
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parser.parse_args([])
        args = parser.parse_args(["--can-interface", "testbus"])
        self.assertEqual(args.can_interface, "testbus")


class PowerTunePublisherTests(unittest.TestCase):
    def test_only_verified_mappings_are_published_with_exact_grammar(self):
        sent = []
        publisher = powertune_udp.PowerTunePublisher(
            lambda packet, target: sent.append((packet, target))
        )
        signals = (
            kpro_can.DecodedSignal("rpm", Decimal(2500), "rpm", 0x660),
            kpro_can.DecodedSignal("map_kpa", Decimal(101), "kPa", 0x662),
            kpro_can.DecodedSignal("ect_c", Decimal(90), "degC", 0x661),
            kpro_can.DecodedSignal("speed_kph", Decimal(100), "kph", 0x660),
            kpro_can.DecodedSignal("tps_pct", Decimal(35), "%", 0x662),
            kpro_can.DecodedSignal("injector_ms", Decimal("2.5"), "ms", 0x663),
        )
        records = [publisher.publish(signal) for signal in signals]
        self.assertEqual(
            records,
            [
                b"179,2500", b"155,101", b"221,90",
                b"199,100", b"210,35", None,
            ],
        )
        self.assertEqual(
            sent,
            [
                (b"179,2500", ("127.0.0.1", 45454)),
                (b"155,101", ("127.0.0.1", 45454)),
                (b"221,90", ("127.0.0.1", 45454)),
                (b"199,100", ("127.0.0.1", 45454)),
                (b"210,35", ("127.0.0.1", 45454)),
            ],
        )

    def test_invalid_nonfinite_and_unchanged_values_are_not_sent(self):
        sent = []
        publisher = powertune_udp.PowerTunePublisher(
            lambda packet, target: sent.append(packet),
            epsilon={"rpm": Decimal("0.1")},
        )
        rpm = lambda value: kpro_can.DecodedSignal(
            "rpm", Decimal(value), "rpm", 0x660
        )
        self.assertEqual(publisher.publish(rpm("2500")), b"179,2500")
        self.assertIsNone(publisher.publish(rpm("2500.05")))
        self.assertEqual(publisher.publish(rpm("2500.2")), b"179,2500.2")
        self.assertIsNone(
            publisher.publish(
                kpro_can.DecodedSignal("rpm", None, "rpm", 0x660, False)
            )
        )
        self.assertEqual(sent, [b"179,2500", b"179,2500.2"])
        with self.assertRaises(ValueError):
            powertune_udp.format_numeric(Decimal("NaN"))

    def test_diagnostic_output_is_rate_limited(self):
        output = []
        clock = [0.0]
        limiter = bridge.DiagnosticLimiter(
            output.append, now=lambda: clock[0], max_per_second=2
        )
        limiter.write("one")
        limiter.write("two")
        limiter.write("three")
        self.assertEqual(output, ["one", "two"])
        clock[0] = 1.0
        limiter.write("four")
        self.assertEqual(output, ["one", "two", "diagnostic output suppressed: 1 messages", "four"])

    def test_documentation_records_authoritative_catalog_and_provenance(self):
        document = (ROOT / "docs/HONDATA_KPRO_CAN.md").read_text(encoding="utf-8")
        self.assertIn(kpro_can.HONDATA_MOTEC_SOURCE, document)
        self.assertIn(kpro_can.AIM_SOURCE, document)
        for can_id in ("0x660", "0x669", "0x5F0", "0x5FC", "0x5FB"):
            self.assertIn(can_id, document)
        self.assertIn("DLC", document)
        self.assertIn("derived", document)
        self.assertIn("invalid", document.lower())
        self.assertNotRegex(document, r"\b(HIVE|WASP|NextGen)\b")

    def test_output_numeric_format_is_plain_decimal(self):
        self.assertEqual(powertune_udp.format_numeric(Decimal("1.2500")), "1.25")
        self.assertEqual(powertune_udp.format_numeric(Decimal("0")), "0")


if __name__ == "__main__":
    unittest.main()
