#!/usr/bin/env python3
"""Collect a bounded, receive-only vehicle diagnostic archive."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time


VERSION = "1"
REFERENCE_HASH = "6f227adba4e1ee11c1c55d48e0ef17fd5b585fe79d508e3057561239ad25ae7a"
CONFIG = Path("/etc/powertune/powertune-appliance.conf")
DASHBOARD = Path("/var/lib/powertune/UserDashboards/Dash1Export.txt")
LOG = Path("/var/log/powertune/powertunedash.log")
OUTPUT_DIR = Path("/var/tmp")
KEYS = ("PT_CAN_INTERFACE", "PT_CAN_BITRATE", "PT_CAN_RESTART_MS", "PT_KPRO_PROFILE")
SERVICES = ("powertune-can.service", "powertune-kpro-bridge.service", "powertunedash.service")


def utc():
    return datetime.now(timezone.utc)


def duration_arg(value):
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must be an integer from 5 to 600") from exc
    if not 5 <= seconds <= 600:
        raise argparse.ArgumentTypeError("duration must be an integer from 5 to 600")
    return seconds


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--duration", type=duration_arg, default=60, help="capture seconds (5-600; default 60)")
    result.add_argument("--note", default="", help="stationary test observations, saved verbatim")
    return result


class Collector:
    def __init__(self, directory):
        self.root = directory
        self.results = {}

    def put(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def run(self, name, args):
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, errors="replace", timeout=15, check=False)
            self.results[name] = {"ok": result.returncode == 0, "exit_status": result.returncode}
            text = result.stdout
            if result.stderr:
                text += "\n[stderr]\n" + result.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.results[name] = {"ok": False, "error": str(exc)}
            text = f"Unavailable: {exc}\n"
        self.put(name, text)
        return text

    def copy(self, source, target):
        try:
            data = source.read_bytes()
            path = self.root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.results[target] = {"ok": True}
            return data
        except OSError as exc:
            self.results[target] = {"ok": False, "error": str(exc)}
            self.put(target, f"Unavailable: {exc}\n")
            return None

    def config(self):
        try:
            text = CONFIG.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.results["config"] = {"ok": False, "error": str(exc)}
            self.put("config/powertune-appliance.conf", f"Unavailable: {exc}\n")
            return {}
        values = {}
        invalid_names = set()
        sanitized = []
        valid = True
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            name, sep, value = stripped.partition("=")
            if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                sanitized.append("[unrecognized configuration line redacted]")
                valid = False
            elif name in KEYS:
                # Do not interpret shell syntax as systemd EnvironmentFile syntax.
                value = value.strip()
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or name in values or name in invalid_names:
                    sanitized.append(name + "=[invalid value redacted]")
                    values.pop(name, None)
                    invalid_names.add(name)
                    valid = False
                else:
                    values[name] = value
                    sanitized.append(name + "=" + value)
            else:
                sanitized.append(name + "=[redacted]")
        self.put("config/powertune-appliance.conf", "\n".join(sanitized) + "\n")
        self.results["config"] = {"ok": valid, "note": "Unknown values and comments redacted"}
        return values

    def capture(self, interface, duration):
        self.put("can/vehicle.candump", "")
        self.put("can/candump.stderr", "")
        if not interface or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}", interface):
            message = "CAN capture unavailable: invalid or missing configured interface"
            self.put("can/candump-status.txt", message + "\n")
            self.results["can_capture"] = {"ok": False, "error": message}
            self.put("can/midpoint.txt", "Unavailable: capture was not started\n")
            return
        try:
            with (self.root / "can/vehicle.candump").open("w") as out, \
                    (self.root / "can/candump.stderr").open("w") as err:
                process = subprocess.Popen(
                    ["timeout", "-s", "INT", str(duration), "candump", "-L", interface],
                    stdout=out, stderr=err,
                )
                try:
                    process.wait(timeout=duration / 2)
                except subprocess.TimeoutExpired:
                    pass
                self.run("can/midpoint.txt", ["ip", "-details", "-statistics", "link", "show", interface])
                try:
                    status = process.wait(timeout=duration / 2 + 5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError("capture timeout supervisor did not exit")
            # GNU timeout returns 124 for its own expected timeout.
            ok = status == 124
            self.results["can_capture"] = {"ok": ok, "exit_status": status,
                                           "expected_timeout": status == 124}
            self.put("can/candump-status.txt", f"exit_status={status}\nexpected_timeout={ok}\n")
        except (OSError, RuntimeError) as exc:
            self.results["can_capture"] = {"ok": False, "error": str(exc)}
            self.put("can/candump-status.txt", f"Capture failed: {exc}\n")
            if not (self.root / "can/midpoint.txt").exists():
                self.put("can/midpoint.txt", "Unavailable: capture could not start\n")


def collect(args, output_dir=OUTPUT_DIR):
    start = utc()
    root = Path(tempfile.mkdtemp(prefix="powertune-car-diag-", dir=output_dir))
    collector = Collector(root)
    archive = output_dir / ("powertune-car-diag-" + start.strftime("%Y%m%dT%H%M%SZ") + ".tar.gz")
    try:
        collector.put("operator-note.txt", args.note)
        collector.put("system/timing.txt", f"start_utc={start.isoformat()}\nrequested_duration_seconds={args.duration}\ntool_version={VERSION}\n")
        collector.run("system/hostname.txt", ["hostname"])
        collector.run("system/uname.txt", ["uname", "-a"])
        collector.copy(Path("/etc/os-release"), "system/os-release.txt")
        collector.run("system/root-device.txt", ["findmnt", "-n", "-o", "SOURCE", "/"])
        collector.run("system/uptime.txt", ["uptime"])
        collector.run("system/boot-mode.txt", ["pt-boot-mode", "status"])
        config = collector.config()
        interface = config.get("PT_CAN_INTERFACE")
        dashboard = collector.copy(DASHBOARD, "build/Dash1Export.txt")
        digest = hashlib.sha256(dashboard).hexdigest() if dashboard is not None else None
        collector.put("build/dashboard.sha256", f"actual={digest or 'unavailable'}\nreference={REFERENCE_HASH}\nmatch={str(digest == REFERENCE_HASH).lower() if digest else 'unavailable'}\n")
        collector.run("services/statuses.txt", ["systemctl", "--no-pager", "--full", "status", *SERVICES])
        collector.run("services/properties.txt", ["systemctl", "--no-pager", "show",
                      "--property=Id,ActiveState,SubState,MainPID,ExecMainStatus,NRestarts,FragmentPath,EnvironmentFiles,User", *SERVICES])
        collector.run("services/processes.txt", ["ps", "-ef"])
        for service, name in zip(SERVICES, ("can-service", "bridge", "powertunedash")):
            collector.run(f"logs/{name}-journal.txt", ["journalctl", "--no-pager", "-b", "-u", service])
        build_lines = (root / "logs/powertunedash-journal.txt").read_text().splitlines()
        build_line = next((line for line in reversed(build_lines) if "PowerTune build:" in line), None)
        collector.put("build/powertune-build.txt", (build_line or "Unavailable") + "\n")
        version_match = re.search(r'version="([^"]*)".*revision="([^"]*)"', build_line or "")
        collector.run("logs/kernel-can.txt", ["journalctl", "--no-pager", "-b", "-k"])
        collector.copy(LOG, "logs/powertunedash.log")
        collector.run("network/udp-listeners.txt", ["ss", "-lunp"])
        collector.copy(Path("/proc/net/udp"), "network/proc-net-udp.txt")
        collector.copy(Path("/proc/net/udp6"), "network/proc-net-udp6.txt")
        if interface and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}", interface):
            collector.run("can/before.txt", ["ip", "-details", "-statistics", "link", "show", interface])
        else:
            collector.put("can/before.txt", "Unavailable: invalid or missing configured interface\n")
            collector.results["can/before.txt"] = {"ok": False}
        print("Stationary sequence (approximate): 0-10 s ignition on, engine off; 10-30 s idle; 30-45 s two gentle RPM increases; 45-60 s idle.", flush=True)
        capture_start = utc()
        capture_clock = time.monotonic()
        collector.capture(interface, args.duration)
        capture_end = utc()
        capture_elapsed = time.monotonic() - capture_clock
        collector.put("can/capture-times.txt",
                      f"start_utc={capture_start.isoformat()}\nend_utc={capture_end.isoformat()}\n"
                      f"elapsed_seconds={capture_elapsed:.3f}\n")
        if interface and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}", interface):
            collector.run("can/after.txt", ["ip", "-details", "-statistics", "link", "show", interface])
        else:
            collector.put("can/after.txt", "Unavailable: invalid or missing configured interface\n")
            collector.results["can/after.txt"] = {"ok": False}
        end = utc()
        manifest = {
            "format": "powertune-car-diag", "version": VERSION,
            "start_utc": start.isoformat(), "end_utc": end.isoformat(),
            "duration_requested_seconds": args.duration,
            "duration_total_seconds": (end - start).total_seconds(),
            "capture_start_utc": capture_start.isoformat(), "capture_end_utc": capture_end.isoformat(),
            "capture_elapsed_seconds": capture_elapsed,
            "hostname": (root / "system/hostname.txt").read_text().strip() if collector.results["system/hostname.txt"]["ok"] else None,
            "can_interface": interface, "can_bitrate": config.get("PT_CAN_BITRATE"),
            "can_restart_ms": config.get("PT_CAN_RESTART_MS"), "profile": config.get("PT_KPRO_PROFILE"),
            "udp_destination_default": "127.0.0.1:45454",
            "build_version": version_match.group(1) if version_match else None,
            "build_revision": version_match.group(2) if version_match else None,
            "dashboard_sha256": digest, "dashboard_matches_reference": digest == REFERENCE_HASH if digest else None,
            "results": collector.results,
            "files": sorted([str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()] + ["manifest.json"]),
        }
        collector.put("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        with archive.open("xb") as file:
            os.fchmod(file.fileno(), 0o600)
            with tarfile.open(fileobj=file, mode="w:gz") as tar:
                for name in manifest["files"]:
                    tar.add(root / name, arcname=name, recursive=False)
        shutil.rmtree(root)
        print(f"Archive: {archive} ({archive.stat().st_size} bytes)")
        if not collector.results["can_capture"]["ok"]:
            print("CAN capture failed; see can/candump-status.txt", file=sys.stderr)
            return 1
        return 0
    except (OSError, tarfile.TarError, ValueError) as exc:
        print(f"Collection/archive failed: {exc}; working directory retained: {root}", file=sys.stderr)
        return 1


def main(argv=None):
    return collect(parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
