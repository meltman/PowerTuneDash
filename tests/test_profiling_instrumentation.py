import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class ProfilingInstrumentationTests(unittest.TestCase):
    def test_profiling_is_env_gated_and_default_off(self):
        source = read("ptprofile.cpp")
        self.assertIn('s_enabled(false)', source)
        self.assertIn('qgetenv("PT_PROFILE")', source)
        self.assertIn("if (!enabled())\n        return;", source)
        header = read("ptprofile.h")
        self.assertIn("PT_PROFILE_COUNT", header)
        self.assertIn("if (PtProfile::enabled())", header)

    def test_build_files_include_profiler(self):
        project = read("PowertuneQMLGui.pro")
        self.assertIn("ptprofile.cpp", project)
        self.assertIn("ptprofile.h", project)
        self.assertIn('setContextProperty("PTProfile"', read("main.cpp"))

    def test_canonical_gauge_identifiers_counted(self):
        source = read("udpreceiver.cpp")
        for ident in (155, 179, 199, 210, 221):
            self.assertIn(f"ident == {ident}", source)
        self.assertIn("udp.datagrams", source)
        dash = read("dashboard.cpp")
        for prop in ("rpm", "speed", "Watertemp", "TPS", "MAP"):
            self.assertIn(f'dash.{prop}.setter', dash)
            self.assertIn(f'dash.{prop}.emit', dash)

    def test_qml_probes_are_guarded(self):
        for name in ("Gauges/RoundGauge.qml", "Settings/main.qml",
                     "Gauges/WarningLoader.qml"):
            text = read(name)
            calls = len(re.findall(r"PTProfile\.(count|addTimeUs)\(", text))
            guards = len(re.findall(r"if \(PTProfile\.enabled\)", text))
            self.assertGreater(calls, 0, name)
            self.assertGreaterEqual(guards, calls, name)
        gauge = read("Gauges/RoundGauge.qml")
        self.assertIn("gauge.needletrail.onPaint", gauge)
        self.assertIn("gauge.needletrail.requestPaint", gauge)

    def test_idle_timers_have_counters(self):
        self.assertIn("timer.calculations.25ms", read("calculations.cpp"))
        self.assertIn("timer.networkmanager.refresh", read("networkmanagerclient.cpp"))

    def test_no_behavior_change_in_setters(self):
        dash = read("dashboard.cpp").replace("\r\n", "\n")
        # setMAP still emits unconditionally; this pass is diagnostic only.
        body = dash.split("void DashBoard::setMAP(const qreal &MAP)")[1].split("}\n\nvoid")[0]
        self.assertNotIn("m_MAP == MAP", body)
        self.assertIn("onValueChanged: {\n                        if (PTProfile.enabled)",
                      read("Gauges/RoundGauge.qml").replace("\r\n", "\n"))

    def test_documentation_records_measurements(self):
        doc = read("docs/PERFORMANCE_PROFILING.md")
        self.assertIn("6f227adba4e1ee11c1c55d48e0ef17fd5b585fe79d508e3057561239ad25ae7a", doc)
        for value in ("8.53%", "8.57%", "13.70%", "14.20%", "20.80%", "21.00%"):
            self.assertIn(value, doc)
        self.assertIn("PT_PROFILE=1", doc)
        for heading in ("Measured evidence", "Inference (not measured)",
                        "Recurring idle work", "Ranked optimization"):
            self.assertIn(heading, doc)
        for term in ("HIVE", "WASP", "NextGen"):
            self.assertNotIn(term, doc)


if __name__ == "__main__":
    unittest.main()
