import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def section(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


class UdpReceiverLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connect = (ROOT / "connect.cpp").read_text(encoding="utf-8")
        cls.receiver = (ROOT / "udpreceiver.cpp").read_text(encoding="utf-8")
        cls.receiver_header = (ROOT / "udpreceiver.h").read_text(encoding="utf-8")

    def test_application_constructs_and_starts_receiver_once(self):
        constructor = section(
            self.connect, "Connect::Connect(QObject *parent)", "Connect::~Connect()"
        )
        self.assertIn("m_udpreceiver= new udpreceiver(m_dashBoard, this);", constructor)
        self.assertIn("m_udpreceiver->startreceiver();", constructor)
        self.assertNotIn("ecuSelect", constructor)
        self.assertLess(
            constructor.index("m_udpreceiver->startreceiver();"),
            constructor.index("m_extender = new Extender"),
        )
        self.assertEqual(self.connect.count("m_udpreceiver->startreceiver();"), 1)
        main = (ROOT / "main.cpp").read_text(encoding="utf-8")
        self.assertLess(
            main.index('setContextProperty("Connect", new Connect(&engine))'),
            main.index("engine.load("),
        )

    def test_ecu_connect_and_disconnect_do_not_own_receiver_lifecycle(self):
        open_connection = section(
            self.connect,
            "void Connect::openConnection(",
            "void Connect::closeConnection()",
        )
        close_connection = section(
            self.connect, "void Connect::closeConnection()", "void Connect::update()"
        )
        self.assertNotIn("startreceiver", open_connection)
        self.assertNotIn("m_udpreceiver", close_connection)
        self.assertIn("m_apexi->closeConnection();", close_connection)

    def test_startup_daemon_setting_does_not_control_receiver(self):
        daemon_startup = section(
            self.connect, "void Connect::daemonstartup(", "void Connect::canbitratesetup("
        )
        startup_qml = (ROOT / "Settings" / "startup.qml").read_text(encoding="utf-8")
        self.assertNotIn("startreceiver", daemon_startup)
        self.assertIn('model: ["None"', startup_qml)
        self.assertIn("Connect.daemonstartup(", startup_qml)
        self.assertNotIn("startreceiver", startup_qml)

    def test_receiver_start_is_one_shot_and_preserves_wildcard_compatibility(self):
        start = section(
            self.receiver,
            "void udpreceiver::startreceiver()",
            "void udpreceiver::processPendingDatagrams()",
        )
        self.assertIn("if (m_startAttempted)", start)
        self.assertIn("m_startAttempted = true;", start)
        self.assertEqual(start.count("udpSocket->bind("), 1)
        self.assertIn("udpSocket->bind(45454, QUdpSocket::ShareAddress)", start)
        self.assertNotIn("QHostAddress::LocalHost", start)
        self.assertNotIn("while (", start)
        self.assertIn("bool        m_startAttempted = false;", self.receiver_header)

    def test_bind_failure_is_reported_once_and_success_logs_bound_address(self):
        start = section(
            self.receiver,
            "void udpreceiver::startreceiver()",
            "void udpreceiver::processPendingDatagrams()",
        )
        self.assertIn("if (!udpSocket->bind(", start)
        self.assertIn(".left(256)", start)
        self.assertIn(".replace(QLatin1Char('\\n'), QLatin1Char(' '))", start)
        self.assertIn(
            "ERROR PowerTune integration receiver failed to bind UDP port 45454:",
            start,
        )
        self.assertIn(
            'INFO PowerTune integration receiver listening: address=\\"%1\\", port=45454',
            start,
        )
        self.assertIn("udpSocket->localAddress().toString()", start)

    def test_existing_parser_grammar_and_known_mappings_are_retained(self):
        parser = section(
            self.receiver,
            "void udpreceiver::processPendingDatagrams()",
            "\n}",
        )
        for expected in (
            'QString raw = datagram.data();',
            'raw ="0,0";',
            'QStringList list = raw.split( "," );',
            "int ident =list[0].toInt();",
            "float Value =list[1].toFloat();",
            "switch(ident)",
        ):
            self.assertIn(expected, parser)
        for identifier, setter in ((179, "setrpm"), (155, "setMAP"), (199, "setSpeed")):
            case = re.search(
                rf"\bcase\s+{identifier}\s*:(.*?)(?=\n\s*case\s+\d+\s*:|\Z)",
                parser,
                re.DOTALL,
            )
            self.assertIsNotNone(case)
            self.assertIn(f"m_dashboard->{setter}(", case.group(1))

    def test_device_validated_simulator_record_remains_compatible(self):
        protocol = (ROOT / "docs" / "DAEMON_UDP_PROTOCOL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("`179,2500`", protocol)
        self.assertIn("pt-udp-sim --signal rpm --value 2500", protocol)


if __name__ == "__main__":
    unittest.main()
