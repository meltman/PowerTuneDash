import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diag = load("car_diag", "pt-car-diag.py")
analyzer = load("capture_analyzer", "kpro-capture-analyze.py")
bridge = load("bridge_for_car_test", "kpro-powertune-bridge.py")
FIXED = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


class MockProcess:
    def __init__(self, args, stdout, stderr, status=124):
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.status = status
        self.waits = 0
        stdout.write("(100.000000) canE 661#001E0037000000\n")
        stdout.flush()

    def wait(self, timeout=None):
        self.waits += 1
        if self.waits == 1 and self.status == 124:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.status

    def kill(self):
        raise AssertionError("unexpected kill")


class CarDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "appliance.conf"
        self.config.write_text("PT_CAN_INTERFACE=canE\nPT_CAN_BITRATE=1000000\n"
                               "PT_CAN_RESTART_MS=100\nPT_KPRO_PROFILE=hondata-motec\n"
                               "SECRET_TOKEN=do-not-export\n")
        self.dashboard = self.root / "dashboard.txt"
        self.dashboard.write_text("vehicle dashboard\n")
        self.log = self.root / "dashboard.log"
        self.log.write_text("log\n")
        self.calls = []
        self.fail_optional = False
        self.capture_status = 124

    def fake_run(self, args, **kwargs):
        self.calls.append(args)
        if self.fail_optional and args[0] == "findmnt":
            raise FileNotFoundError("missing findmnt")
        if args[0] == "journalctl" and "powertunedash.service" in args:
            output = 'PowerTune build: version="2026.11.05", revision="1234567"\n'
        elif args[0] == "hostname":
            output = "test-host\n"
        else:
            output = "test output\n"
        return subprocess.CompletedProcess(args, 0, output, "")

    def fake_popen(self, args, **kwargs):
        self.calls.append(args)
        return MockProcess(args, kwargs["stdout"], kwargs["stderr"], self.capture_status)

    def run_capture(self, duration=5, note=""):
        out, err = io.StringIO(), io.StringIO()
        with (mock.patch.object(diag, "CONFIG", self.config),
              mock.patch.object(diag, "DASHBOARD", self.dashboard),
              mock.patch.object(diag, "LOG", self.log),
              mock.patch.object(diag, "utc", return_value=FIXED),
              mock.patch.object(diag.subprocess, "run", side_effect=self.fake_run),
              mock.patch.object(diag.subprocess, "Popen", side_effect=self.fake_popen),
              contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
            result = diag.collect(diag.parser().parse_args(["--duration", str(duration), "--note", note]), self.root)
        return result, out.getvalue(), err.getvalue()

    def archive(self):
        return self.root / "powertune-car-diag-20261109T180000Z.tar.gz"

    def test_duration_validation_and_defaults(self):
        self.assertEqual(diag.parser().parse_args([]).duration, 60)
        self.assertEqual(diag.parser().parse_args(["--duration", "30"]).duration, 30)
        for value in ("", "-1", "4", "601", "abc", "1.5"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    diag.parser().parse_args(["--duration", value])

    def test_default_output_is_persistent_appliance_state(self):
        self.assertEqual(diag.OUTPUT_DIR, Path("/var/lib/powertune/diagnostics"))
        diag.validate_default_output(diag.OUTPUT_DIR)

    def test_known_volatile_default_is_rejected(self):
        for directory in ("/tmp/captures", "/var/tmp/captures",
                          "/run/captures", "/var/volatile/captures",
                          "/dev/shm/captures", "relative/captures"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                diag.validate_default_output(Path(directory))
        link = self.root / "volatile-link"
        link.symlink_to("/var/tmp", target_is_directory=True)
        with self.assertRaises(ValueError):
            diag.validate_default_output(link / "captures")

    def test_collector_rejects_volatile_configured_default_before_capture(self):
        error = io.StringIO()
        with (mock.patch.object(diag, "OUTPUT_DIR", Path("/var/tmp/pt-car-diag-test")),
              mock.patch.object(diag.subprocess, "Popen") as capture,
              contextlib.redirect_stderr(error)):
            result = diag.collect(diag.parser().parse_args(["--duration", "5"]))
        self.assertNotEqual(result, 0)
        self.assertIn("refusing volatile", error.getvalue())
        capture.assert_not_called()

    def test_new_output_directory_is_private(self):
        target = self.root / "new-diagnostics"
        with (mock.patch.object(diag, "CONFIG", self.config),
              mock.patch.object(diag, "DASHBOARD", self.dashboard),
              mock.patch.object(diag, "LOG", self.log),
              mock.patch.object(diag, "utc", return_value=FIXED),
              mock.patch.object(diag.subprocess, "run", side_effect=self.fake_run),
              mock.patch.object(diag.subprocess, "Popen", side_effect=self.fake_popen),
              contextlib.redirect_stdout(io.StringIO())):
            result = diag.collect(diag.parser().parse_args(["--duration", "5"]), target)
        self.assertEqual(result, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertTrue((target / self.archive().name).is_file())

    def test_mocked_five_second_capture_archive_and_safety(self):
        note = 'Pi ECT 55C\nliteral $(not executed)\n'
        code, out, _ = self.run_capture(note=note)
        self.assertEqual(code, 0)
        self.assertIn(str(self.archive()), out)
        self.assertIn("Stationary", out)
        self.assertEqual(self.archive().stat().st_mode & 0o777, 0o600)
        with tarfile.open(self.archive()) as archive:
            names = archive.getnames()
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertEqual(sorted(names), manifest["files"])
            for name in ("can/before.txt", "can/midpoint.txt", "can/after.txt",
                         "can/vehicle.candump", "can/candump.stderr", "can/candump-status.txt",
                         "services/statuses.txt", "services/properties.txt",
                         "services/processes.txt", "logs/can-service-journal.txt",
                         "logs/bridge-journal.txt", "logs/powertunedash-journal.txt",
                         "logs/kernel-can.txt", "network/udp-listeners.txt", "build/Dash1Export.txt"):
                self.assertIn(name, names)
            self.assertEqual(archive.extractfile("operator-note.txt").read().decode(), note)
            config = archive.extractfile("config/powertune-appliance.conf").read().decode()
            self.assertIn("SECRET_TOKEN=[redacted]", config)
            self.assertNotIn("do-not-export", config)
            self.assertEqual(manifest["can_interface"], "canE")
            self.assertEqual(manifest["can_bitrate"], "1000000")
            self.assertEqual(manifest["build_revision"], "1234567")
            self.assertEqual(manifest["build_version"], "2026.11.05")
            self.assertFalse(manifest["dashboard_matches_reference"])
            self.assertEqual(len(manifest["dashboard_sha256"]), 64)
            self.assertTrue(manifest["results"]["can_capture"]["ok"])
        self.assertEqual(len([c for c in self.calls if c[0] == "ip"]), 3)
        self.assertIn(["timeout", "-s", "INT", "5", "candump", "-L", "canE"], self.calls)
        self.assertTrue(any(c[:3] == ["systemctl", "--no-pager", "--full"] for c in self.calls))
        self.assertEqual(len([c for c in self.calls if c[0] == "journalctl"]), 4)
        self.assertFalse(any(c[0] in ("cansend", "reboot", "fw_setenv") for c in self.calls))
        self.assertFalse(any("restart" in c or "set" in c for c in self.calls))
        self.assertEqual(list(self.root.glob("powertune-car-diag-*")), [self.archive()])

    def test_optional_failure_does_not_abort_capture(self):
        self.fail_optional = True
        self.assertEqual(self.run_capture()[0], 0)
        with tarfile.open(self.archive()) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertFalse(manifest["results"]["system/root-device.txt"]["ok"])
            self.assertTrue(manifest["results"]["can_capture"]["ok"])

    def test_missing_candump_or_interface_produces_failure_archive(self):
        for status in (127, 1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                collector = diag.Collector(root)
                self.capture_status = status
                with mock.patch.object(diag.subprocess, "Popen", side_effect=self.fake_popen), \
                        mock.patch.object(diag.subprocess, "run", side_effect=self.fake_run):
                    collector.capture("canE", 5)
                self.assertFalse(collector.results["can_capture"]["ok"])
                self.assertIn(str(status), (root / "can/candump-status.txt").read_text())

    def test_missing_timeout_and_missing_candump_keep_archive(self):
        for missing in ("timeout", "candump"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                collector = diag.Collector(root)
                if missing == "timeout":
                    with mock.patch.object(diag.subprocess, "Popen", side_effect=FileNotFoundError("timeout")):
                        collector.capture("canE", 5)
                else:
                    self.capture_status = 127
                    with mock.patch.object(diag.subprocess, "Popen", side_effect=self.fake_popen), \
                            mock.patch.object(diag.subprocess, "run", side_effect=self.fake_run):
                        collector.capture("canE", 5)
                self.assertFalse(collector.results["can_capture"]["ok"])
                self.assertTrue((root / "can/vehicle.candump").exists())
                self.assertTrue((root / "can/candump-status.txt").exists())

    def test_missing_config_interface_is_not_assumed(self):
        self.config.write_text("PT_CAN_BITRATE=1000000\n")
        self.assertNotEqual(self.run_capture()[0], 0)
        with tarfile.open(self.archive()) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertIsNone(manifest["can_interface"])
            self.assertFalse(manifest["results"]["can_capture"]["ok"])
        self.assertFalse(any(c[0] == "timeout" for c in self.calls))

    def test_unavailable_can_interface_still_produces_full_archive(self):
        self.capture_status = 1
        code, _, error = self.run_capture()
        self.assertNotEqual(code, 0)
        self.assertIn("CAN capture failed", error)
        with tarfile.open(self.archive()) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertFalse(manifest["results"]["can_capture"]["ok"])
            self.assertEqual(manifest["results"]["can_capture"]["exit_status"], 1)
            self.assertIn("can/after.txt", archive.getnames())

    def test_collision_retains_working_directory(self):
        self.archive().write_bytes(b"existing")
        code, _, error = self.run_capture()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.archive().read_bytes(), b"existing")
        self.assertIn("working directory retained", error)
        self.assertEqual(len([p for p in self.root.glob("powertune-car-diag-*") if p.is_dir()]), 1)

    def test_archive_failure_retains_working_directory(self):
        with mock.patch.object(diag.tarfile, "open", side_effect=OSError("disk full")):
            code, _, error = self.run_capture()
        self.assertNotEqual(code, 0)
        self.assertIn("working directory retained", error)
        self.assertEqual(len([p for p in self.root.glob("powertune-car-diag-*") if p.is_dir()]), 1)

    def test_archive_fsync_failure_retains_working_directory(self):
        with mock.patch.object(diag.os, "fsync", side_effect=[None, OSError("fsync failed")]):
            code, _, error = self.run_capture()
        self.assertNotEqual(code, 0)
        self.assertIn("fsync failed", error)
        self.assertIn("working directory retained", error)
        directories = [p for p in self.root.glob("powertune-car-diag-*") if p.is_dir()]
        self.assertEqual(len(directories), 1)
        self.assertTrue((directories[0] / "can/vehicle.candump").exists())

    def test_output_directory_fsync_precedes_cleanup(self):
        with mock.patch.object(diag, "fsync_directory", wraps=diag.fsync_directory) as sync:
            code, _, _ = self.run_capture()
        self.assertEqual(code, 0)
        self.assertEqual([call.args[0] for call in sync.call_args_list],
                         [self.root.parent, self.root])

    def test_directory_fsync_failure_retains_working_directory(self):
        with mock.patch.object(diag, "fsync_directory", side_effect=[None, OSError("directory sync failed")]):
            code, out, error = self.run_capture()
        self.assertNotEqual(code, 0)
        self.assertIn("directory sync failed", error)
        self.assertNotIn("Archive:", out)
        directories = [p for p in self.root.glob("powertune-car-diag-*") if p.is_dir()]
        self.assertEqual(len(directories), 1)
        self.assertTrue((directories[0] / "manifest.json").exists())

    def test_packaging_declares_tools_and_dependencies(self):
        layer = ROOT.parent / "compulab-nxp-bsp/compulab-imx8mp-bsp/sources/meta-powertune"
        recipe = (layer / "recipes-powertune/powertunedash/powertunedash.bb").read_text()
        for item in ("pt-car-diag", "kpro-capture-analyze", "python3-compression",
                     "python3-io", "can-utils", "coreutils"):
            self.assertIn(item, recipe)


class OfflineAnalysisTests(unittest.TestCase):
    def test_ect_raw_evidence_and_unexpected_frames(self):
        report = analyzer.analyze([
            "(1.000000) canE 123#DEADBEEF\n",
            "(2.000000) canE 661#001E0037000000\n",
            "(5.000000) canE 661#001E0038000000\n",
            "(6.000000) canE 661#001E0039\n",
            "malformed\n",
        ])
        self.assertIn("123", report["observed_frames"])
        self.assertEqual(report["observed_frames"]["661"]["dlcs"], {4: 1, 7: 2})
        ect = report["ect"]
        self.assertEqual(ect["assumed_byte_offset_zero_based"], 2)
        self.assertEqual(ect["min_c"], "55")
        self.assertEqual(ect["max_c"], "56")
        self.assertEqual(ect["change_count"], 2)
        self.assertEqual(ect["initial_and_changes"][0]["raw_hex"], "0037")
        self.assertEqual(ect["initial_and_changes"][0]["current_decoded_c"], "55")
        self.assertIsNone(ect["initial_and_changes"][-1]["current_decoded_c"])
        self.assertEqual(len(report["malformed_records_or_frames"]), 2)
        self.assertTrue(report["stale_transitions_observed_at_next_timestamped_frame"])

    def test_no_udp_replay_and_analysis(self):
        fixture = ROOT / "tests/fixtures/hondata/representative.candump"
        with mock.patch.object(bridge.socket, "socket", side_effect=AssertionError("socket opened")), \
                contextlib.redirect_stdout(io.StringIO()):
            args = bridge.make_parser().parse_args(["--replay", str(fixture), "--no-udp",
                                                     "--diagnostic", "--replay-speed", "0"])
            bridge.run_bridge(args, socket_factory=bridge.socket.socket)
            self.assertEqual(analyzer.main([str(fixture)]), 0)

    def test_no_udp_rejects_live_interface(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bridge.main(["--can-interface", "canE", "--no-udp"]), 2)


if __name__ == "__main__":
    unittest.main()
