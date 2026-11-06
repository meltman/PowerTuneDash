from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "tools" / "pt-usb-can.py"
SPEC = importlib.util.spec_from_file_location("pt_usb_can", MODULE_PATH)
pt_usb_can = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pt_usb_can)


class ProtocolTests(unittest.TestCase):
    def test_configuration_frame_uses_published_variable_protocol_vector(self):
        packet = pt_usb_can.build_configuration(500_000, "standard")
        self.assertEqual(len(packet), 20)
        self.assertEqual(
            packet,
            bytes.fromhex(
                "AA 55 12 03 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 16"
            ),
        )

    def test_standard_transmit_matches_waveshare_example(self):
        self.assertEqual(
            pt_usb_can.build_data_frame(
                0x123, bytes.fromhex("1122334455667788")
            ),
            bytes.fromhex("AA C8 23 01 11 22 33 44 55 66 77 88 55"),
        )

    def test_extended_transmit_matches_waveshare_example(self):
        self.assertEqual(
            pt_usb_can.build_data_frame(
                0x1234567, bytes.fromhex("1122334455667788"), extended=True
            ),
            bytes.fromhex("AA E8 67 45 23 01 11 22 33 44 55 66 77 88 55"),
        )

    def test_zero_and_eight_byte_payloads(self):
        self.assertEqual(pt_usb_can.build_data_frame(0x123, b""), b"\xAA\xC0\x23\x01\x55")
        packet = pt_usb_can.build_data_frame(0x123, bytes(range(8)))
        self.assertEqual(len(pt_usb_can.decode_data_frame(packet).data), 8)

    def test_receive_decode_includes_frame_type_id_dlc_and_data(self):
        standard = pt_usb_can.decode_data_frame(
            bytes.fromhex("AA C4 23 01 DE AD BE EF 55")
        )
        self.assertEqual(
            standard,
            pt_usb_can.CanFrame(0x123, False, bytes.fromhex("DEADBEEF"), 4),
        )
        extended = pt_usb_can.decode_data_frame(
            bytes.fromhex("AA E2 21 30 03 01 CA FE 55")
        )
        self.assertEqual(
            extended,
            pt_usb_can.CanFrame(0x1033021, True, bytes.fromhex("CAFE"), 2),
        )

    def test_remote_receive_frame_preserves_dlc_without_payload(self):
        remote = pt_usb_can.decode_data_frame(bytes.fromhex("AA D8 23 01 55"))
        self.assertEqual(remote, pt_usb_can.CanFrame(0x123, False, b"", 8, True))

    def test_stream_parser_handles_fragmented_and_concatenated_frames(self):
        first = bytes.fromhex("AA C2 23 01 DE AD 55")
        second = bytes.fromhex("AA E0 67 45 23 01 55")
        frames, remainder = pt_usb_can.extract_packets(first[:3])
        self.assertEqual(frames, [])
        self.assertEqual(remainder, first[:3])
        frames, remainder = pt_usb_can.extract_packets(remainder + first[3:] + second)
        self.assertEqual(
            frames,
            [
                pt_usb_can.CanFrame(0x123, False, bytes.fromhex("DEAD"), 2),
                pt_usb_can.CanFrame(0x1234567, True, b"", 0),
            ],
        )
        self.assertEqual(remainder, b"")

    def test_invalid_can_ids_and_data_lengths_are_rejected(self):
        for can_id in (-1, 0x800):
            with self.subTest(can_id=can_id), self.assertRaises(ValueError):
                pt_usb_can.build_data_frame(can_id, b"")
        with self.assertRaises(ValueError):
            pt_usb_can.build_data_frame(0x20000000, b"", extended=True)
        with self.assertRaises(ValueError):
            pt_usb_can.build_data_frame(0x123, bytes(9))
        with self.assertRaises(ValueError):
            pt_usb_can.parse_data("ABC")
        with self.assertRaises(ValueError):
            pt_usb_can.parse_data("DEADBEEF0011223344")
        with self.assertRaises(ValueError):
            pt_usb_can.decode_data_frame(bytes.fromhex("AA CF 23 01 55"))
        with self.assertRaises(ValueError):
            pt_usb_can.decode_data_frame(bytes.fromhex("AA C9 23 01 55"))

    def test_unprefixed_cli_id_is_hexadecimal(self):
        self.assertEqual(pt_usb_can.parse_can_id("123"), 0x123)
        self.assertEqual(pt_usb_can.parse_can_id("0x123", extended=True), 0x123)

    def test_bitrate_validation(self):
        for rate in (
            1_000_000, 800_000, 500_000, 400_000, 250_000, 200_000,
            125_000, 100_000, 50_000, 20_000, 10_000, 5_000,
        ):
            self.assertEqual(pt_usb_can.validate_bitrate(rate), rate)
        with self.assertRaisesRegex(ValueError, "unsupported CAN bitrate"):
            pt_usb_can.validate_bitrate(333_333)

    def test_usb_discovery_matches_vid_pid_not_tty_name(self):
        ports = [
            SimpleNamespace(device="/dev/ttyUSB7", vid=0x1A86, pid=0x7523),
            SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523),
            SimpleNamespace(device="/dev/ttyUSB1", vid=0x1234, pid=0x5678),
        ]
        self.assertEqual(
            [port.device for port in pt_usb_can.find_matching_devices(ports)],
            ["/dev/ttyUSB7", "/dev/ttyUSB0"],
        )

    def test_zero_and_ambiguous_adapter_discovery(self):
        with self.assertRaisesRegex(ValueError, "no Waveshare USB-CAN-A"):
            pt_usb_can.resolve_device([])
        ports = [
            SimpleNamespace(device="/dev/ttyUSB3", vid=0x1A86, pid=0x7523),
            SimpleNamespace(device="/dev/ttyUSB9", vid=0x1A86, pid=0x7523),
        ]
        with self.assertRaisesRegex(ValueError, "multiple Waveshare"):
            pt_usb_can.resolve_device(ports)
        self.assertEqual(
            pt_usb_can.resolve_device(ports, "/dev/ttyUSB9"),
            "/dev/ttyUSB9",
        )

    def test_send_cli_writes_configuration_then_one_frame(self):
        matching_port = SimpleNamespace(
            device="/dev/ttyUSB7", vid=0x1A86, pid=0x7523
        )

        class FakeSerial:
            def __init__(self):
                self.writes = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def write(self, data):
                self.writes.append(data)
                return len(data)

            def flush(self):
                pass

        fake_serial = FakeSerial()
        with patch.object(
            pt_usb_can, "get_serial_modules", return_value=(None, None)
        ), redirect_stdout(StringIO()):
            result = pt_usb_can.run(
                ["send", "--id", "123", "--data", "DEADBEEF"],
                ports_provider=lambda: [matching_port],
                serial_opener=lambda _device, _baud: fake_serial,
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            fake_serial.writes,
            [
                pt_usb_can.build_configuration(500_000, "standard"),
                pt_usb_can.build_data_frame(0x123, bytes.fromhex("DEADBEEF")),
            ],
        )


class TransmitFramingTests(unittest.TestCase):
    """Variable-length frames per Waveshare's published examples."""

    PUBLISHED = (
        # (can_id, extended, data, serial bytes) from the protocol page.
        (0x123, False, bytes.fromhex("1122334455667788"), "AA C8 23 01 11 22 33 44 55 66 77 88 55"),
        (0x103, False, bytes.fromhex("1122"), "AA C2 03 01 11 22 55"),
        (0x1234567, True, bytes.fromhex("1122334455667788"), "AA E8 67 45 23 01 11 22 33 44 55 66 77 88 55"),
        (0x1033021, True, bytes.fromhex("1122"), "AA E2 21 30 03 01 11 22 55"),
    )

    def test_published_examples(self):
        for can_id, extended, data, expected in self.PUBLISHED:
            with self.subTest(can_id=hex(can_id)):
                packet = pt_usb_can.build_data_frame(can_id, data, extended)
                self.assertEqual(packet, bytes.fromhex(expected))

    def test_reported_vectors(self):
        self.assertEqual(
            pt_usb_can.build_data_frame(0x123, bytes.fromhex("DEADBEEF")),
            bytes.fromhex("AAC42301DEADBEEF55"),
        )
        self.assertEqual(
            pt_usb_can.build_data_frame(0x660, bytes.fromhex("032000000178")),
            bytes.fromhex("AAC66006032000000178" "55"),
        )

    def test_table_all_dlcs_and_ids(self):
        for can_id in (0x000, 0x103, 0x123, 0x456, 0x660, 0x7FF):
            for dlc in range(9):
                data = bytes((0x11 * (i + 1)) & 0xFF for i in range(dlc))
                with self.subTest(can_id=hex(can_id), dlc=dlc):
                    packet = pt_usb_can.build_data_frame(can_id, data)
                    expected = (
                        bytes((0xAA, 0xC0 | dlc, can_id & 0xFF, can_id >> 8))
                        + data
                        + b"\x55"
                    )
                    self.assertEqual(packet, expected)
                    self.assertEqual(len(packet), 5 + dlc)

    def test_configuration_precedes_nothing_extra(self):
        config = pt_usb_can.build_configuration(1_000_000)
        self.assertEqual(len(config), 20)
        self.assertEqual(config[:4], bytes((0xAA, 0x55, 0x12, 0x01)))
        self.assertEqual(config[14], 0x00)
        self.assertEqual(config[19], sum(config[2:19]) & 0xFF)
        disabled = pt_usb_can.build_configuration(1_000_000, auto_retransmit=False)
        self.assertEqual(disabled[14], 0x01)
        self.assertEqual(disabled[19], sum(disabled[2:19]) & 0xFF)

    def test_dump_serial_frame_does_not_open_adapter(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("adapter must not be opened")

        output = StringIO()
        with redirect_stdout(output):
            status = pt_usb_can.run(
                ["send", "--can-bitrate", "1000000", "--id", "660",
                 "--data", "032000000178", "--dump-serial-frame"],
                ports_provider=forbidden,
                serial_opener=forbidden,
            )
        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("AA 55 12 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 14", text)
        self.assertIn("AA C6 60 06 03 20 00 00 01 78 55", text)
        self.assertIn("not transmitted", text)

    def test_send_writes_configuration_then_frame(self):
        written = []

        class Port:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def write(self, data):
                written.append(bytes(data))

            def flush(self):
                pass

        ports = [SimpleNamespace(device="/dev/ttyUSB7", vid=0x1A86, pid=0x7523)]
        with redirect_stdout(StringIO()):
            pt_usb_can.run(
                ["send", "--can-bitrate", "1000000", "--id", "660",
                 "--data", "032000000178"],
                ports_provider=lambda: ports,
                serial_opener=lambda device, baud: Port(),
            )
        self.assertEqual(len(written), 2)
        self.assertEqual(len(written[0]), 20)
        self.assertEqual(written[1], bytes.fromhex("AAC6600603200000017855"))


if __name__ == "__main__":
    unittest.main()
