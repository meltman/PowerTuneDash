import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = (ROOT.parent / "compulab-nxp-bsp" / "compulab-imx8mp-bsp" / "sources"
          / "meta-powertune" / "recipes-powertune" / "powertunedash" / "powertunedash.bb")


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


class BuildProvenanceTests(unittest.TestCase):
    def test_hardcoded_legacy_version_is_not_primary_identity(self):
        qml = read("Settings", "main.qml")
        self.assertNotIn("V 1.99t", qml)
        self.assertIn("PTBuild.product", qml)

    def test_upstream_version_is_explicit_provenance_only(self):
        qml = read("Settings", "main.qml")
        self.assertNotIn("1.99t", qml)
        self.assertIn("Upstream base: ", qml)
        self.assertIn('#define PT_UPSTREAM_BASE_VERSION "1.99t"', read("ptbuildinfo.h"))

    def test_ui_consumes_generated_metadata(self):
        qml = read("Settings", "main.qml")
        self.assertIn("PTBuild.display", qml)
        main = read("main.cpp")
        self.assertIn('setContextProperty("PTBuild", ptBuildInfo())', main)
        pro = read("PowertuneQMLGui.pro")
        for name in ("PT_BUILD_VERSION", "PT_BUILD_REVISION"):
            self.assertIn("DEFINES += %s=" % name, pro)

    def test_startup_log_uses_same_revision_data(self):
        main = read("main.cpp")
        self.assertIn("ptBuildLogLine()", main)
        header = read("ptbuildinfo.h")
        self.assertIn("ptBuildRevision()", header.split("ptBuildLogLine")[1])
        self.assertIn("insert(QStringLiteral(\"revision\"), ptBuildRevision())", header)
        self.assertIn('version=\\"%1\\", revision=\\"%2\\"', header)

    def test_missing_metadata_falls_back(self):
        header = read("ptbuildinfo.h")
        self.assertRegex(header, r'#ifndef PT_BUILD_VERSION\s+#define PT_BUILD_VERSION "unknown"')
        self.assertRegex(header, r'#ifndef PT_BUILD_REVISION\s+#define PT_BUILD_REVISION "unknown"')
        self.assertRegex(header, r'#ifndef PT_BUILD_BRANCH\s+#define PT_BUILD_BRANCH ""')
        self.assertIn("if (!ptBuildBranch().isEmpty())", header)
        pro = read("PowertuneQMLGui.pro")
        self.assertIn("!isEmpty(PT_BUILD_VERSION): DEFINES", pro)

    def test_no_runtime_git_usage(self):
        for name in ("main.cpp", "ptbuildinfo.h"):
            text = read(name)
            self.assertNotRegex(text, r"QProcess|\bgit\b.*rev-parse|\.git\b")

    def test_recipe_supplies_provenance_without_branch(self):
        if not RECIPE.exists():
            self.skipTest("BitBake recipe not present next to this checkout")
        recipe = RECIPE.read_text(encoding="utf-8")
        self.assertIn("export PT_BUILD_REVISION", recipe)
        self.assertIn("export PT_BUILD_VERSION", recipe)
        self.assertIn("rev-parse --short=7 HEAD", recipe)
        self.assertNotIn("PT_BUILD_BRANCH", recipe)

    def test_docs_describe_scheme(self):
        doc = read("docs", "IMX8_PORT.md")
        self.assertIn("## Build identity and provenance", doc)
        self.assertIn("Upstream base: 1.99t", doc)
        self.assertNotRegex(doc, r"HIVE|WASP|NextGen")


if __name__ == "__main__":
    unittest.main()
