import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortableDashboardFieldTests(unittest.TestCase):
    def test_all_userdash_importers_keep_empty_fields(self):
        source = (ROOT / "connect.cpp").read_text()
        for number in (1, 2, 3):
            start = source.index(f"void Connect::readdashsetup{number}()")
            end = source.find("\nvoid Connect::", start + 1)
            method = source[start:end if end != -1 else None]
            self.assertIn(
                r'line.split(QRegExp("\\,"), QString::KeepEmptyParts)',
                method,
            )
            self.assertNotIn('removeAll(QString(""))', method)

    def test_exporter_does_not_replace_empty_values(self):
        source = (ROOT / "connect.cpp").read_text()
        start = source.index("void Connect::saveDashtoFile(")
        end = source.index("\nvoid Connect::setfilename1", start)
        self.assertNotIn('fixformat.replace(",,",", ,")', source[start:end])

    def test_historical_portable_examples_contain_empty_cells(self):
        examples = ROOT / "exampleDash" / "UserDashboards"
        self.assertTrue(
            any(
                "" in line.split(",")[1:-1]
                for path in examples.glob("*.txt")
                for line in path.read_text().splitlines()
            )
        )

    def test_state_gif_schema_and_round_trip_keep_positions(self):
        for number in (1, 2, 3):
            source = (ROOT / f"Gauges/Userdash{number}.qml").read_text()
            self.assertRegex(
                source,
                re.compile(
                    r'information\+"\,"\+userDash\.children\[i\]\.x\+"\,"\+'
                    r'userDash\.children\[i\]\.y\+"\,"\+'
                    r'userDash\.children\[i\]\.pictureheight\+"\,"\+'
                    r'userDash\.children\[i\]\.mainvaluename\+"\,"\+'
                    r'userDash\.children\[i\]\.triggervalue\+"\,"\+'
                    r'userDash\.children\[i\]\.statepicturesourceoff\+"\,"\+'
                    r'userDash\.children\[i\]\.statepicturesourceon\+"\,"\+'
                    r'userDash\.children\[i\]\.triggeroffvalue'
                ),
            )
            self.assertIn(
                "CreateStateGIFScript.createPicture("
                "dashvalue.textAt(1),dashvalue.textAt(2),"
                "dashvalue.textAt(3),dashvalue.textAt(4),"
                "dashvalue.textAt(5),dashvalue.textAt(6),"
                "dashvalue.textAt(7),dashvalue.textAt(8))",
                source,
            )
            self.assertRegex(
                source,
                re.compile(
                    r'information\+"\,"\+userDash\.children\[i\]\.x\+"\,"\+'
                    r'userDash\.children\[i\]\.y\+"\,"\+'
                    r'userDash\.children\[i\]\.pictureheight\+"\,"\+'
                    r'userDash\.children\[i\]\.mainvaluename\+"\,"\+'
                    r'userDash\.children\[i\]\.triggervalue\+"\,"\+'
                    r'userDash\.children\[i\]\.statepicturesourceoff\+"\,"\+'
                    r'userDash\.children\[i\]\.statepicturesourceon'
                ),
            )
            self.assertIn(
                "CreateStatePictureScript.createPicture("
                "dashvalue.textAt(1),dashvalue.textAt(2),"
                "dashvalue.textAt(3),dashvalue.textAt(4),"
                "dashvalue.textAt(5),dashvalue.textAt(6),"
                "dashvalue.textAt(7))",
                source,
            )

        # State GIF portable field order:
        # info, x, y, height, datasource, trigger, pictureoff, pictureon, triggeroff
        cases = [
            ["State GIF", "10", "20", "100", "speed", "-1.5", "", "", "2.25"],
            ["State GIF", "10", "20", "100", "speed", "-1.5", "off.gif", "", "2.25"],
            ["State GIF", "10", "20", "100", "speed", "2.25", "", "on.gif", "0"],
            ["State GIF", "10", "20", "100", "speed", "0", "None", "/Logo", "-2.75"],
            ["State GIF", "10", "20", "100", "engine speed", "2.25", "off.gif", "on.gif", "0"],
            ["State gauge", "10", "20", "100", "speed", "-1.5", "", ""],
            ["State gauge", "10", "20", "100", "speed", "0", "off.png", ""],
        ]
        for fields in cases:
            serialized = ",".join(fields)
            parsed = serialized.split(",")
            self.assertEqual(parsed, fields)


if __name__ == "__main__":
    unittest.main()
