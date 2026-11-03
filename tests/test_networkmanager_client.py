import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NetworkManagerClientSourceTests(unittest.TestCase):
    def test_qmake_builds_dbus_client_not_legacy_scanner(self):
        project = (ROOT / "PowertuneQMLGui.pro").read_text()
        self.assertIn("network dbus", project)
        self.assertIn("networkmanagerclient.cpp", project)
        self.assertNotIn("wifiscanner.cpp", project)

    def test_connect_exposes_networkmanager_not_wifiscanner(self):
        header = (ROOT / "connect.h").read_text()
        source = (ROOT / "connect.cpp").read_text()
        self.assertIn("NetworkManagerClient *m_networkManager", header)
        self.assertIn('setContextProperty("NetworkManager", m_networkManager)', source)
        self.assertNotIn("WifiScanner", source)
        self.assertNotIn("Wifiscanner", source)

    def test_client_uses_async_dbus_and_discovered_device_types(self):
        source = (ROOT / "networkmanagerclient.cpp").read_text()
        self.assertIn("m_bus.asyncCall", source)
        self.assertIn("device.type == 2", source)
        self.assertIn("device.type == 1", source)
        self.assertIn('startsWith(QStringLiteral("p2p-dev-"))', source)
        self.assertNotIn("wlan0", source)
        self.assertNotIn("eth0", source)
        self.assertNotIn("QProcess", source)
        self.assertNotIn("waitForFinished", source)

    def test_device_policy_and_hidden_ssid_handling_are_explicit(self):
        source = (ROOT / "networkmanagerclient.cpp").read_text()
        self.assertIn("const bool aActive = a.state == 100", source)
        self.assertIn("const int aRank = (a.state == 100 ? 2 : 0) + (a.carrier ? 1 : 0)", source)
        self.assertIn("const bool hidden = ssid.isEmpty()", source)
        self.assertIn("const QString key = hidden ? path : ssid", source)
        self.assertIn("if (!unique->contains(key))", source)
        self.assertIn("NetworkManager could not connect", source)
        self.assertIn("authentication failed", source)

    def test_access_point_security_cases(self):
        source = (ROOT / "networkmanagerclient.cpp").read_text()
        start = source.index("AccessPointSecurity classifyAccessPoint(")
        end = source.index("\nbool isP2pDevice", start)
        classifier = source[start:end]

        privacy = 0x1
        psk = 0x200
        sae = 0x400
        self.assertIn("securityFlags & ~uint(0xff)", classifier)
        self.assertIn("(flags & 0x1) != 0 || keyManagementFlags != 0", classifier)
        self.assertIn("(securityFlags & 0x400) != 0", classifier)
        self.assertIn("(securityFlags & 0x200) != 0", classifier)
        self.assertIn('QStringLiteral("unsupported")', classifier)
        load_access_points = source[source.index("void NetworkManagerClient::loadAccessPoints("):
                                    source.index("void NetworkManagerClient::loadAccessPoint(")]
        for field in ("Flags", "WpaFlags", "RsnFlags"):
            self.assertIn(f'QStringLiteral("{field}")', load_access_points)

        cases = [
            ("open", 0, 0, 0, "none", False, True),
            ("no key management", 0, 0x8, 0, "none", False, True),
            ("WPA-PSK", 0, psk, 0, "wpa-psk", True, True),
            ("SAE", 0, 0, sae, "sae", True, True),
            ("privacy protected without key management", privacy, 0, 0, "unsupported", True, False),
            ("enterprise", 0, 0x100, 0, "unsupported", True, False),
        ]
        for name, flags, wpa, rsn, key_mgmt, protected, supported in cases:
            security_flags = wpa | rsn
            actual_protected = bool(flags & privacy or security_flags & ~0xff)
            actual_key_mgmt = (
                "none" if not actual_protected else
                "sae" if security_flags & sae else
                "wpa-psk" if security_flags & psk else
                "unsupported"
            )
            actual_supported = actual_key_mgmt != "unsupported"
            self.assertEqual(
                (actual_key_mgmt, actual_protected, actual_supported),
                (key_mgmt, protected, supported),
                name,
            )

    def test_networkmanager_connection_dbus_signatures_and_persistence(self):
        source = (ROOT / "networkmanagerclient.cpp").read_text()
        header = (ROOT / "networkmanagerclient.h").read_text()
        self.assertIn("QMap<QString, QVariantMap> NetworkConnectionSettings", header)
        self.assertIn("argument.beginMap(qMetaTypeId<QString>(), qMetaTypeId<QVariantMap>())", source)
        self.assertIn('QStringLiteral("AddAndActivateConnection2")', source)
        add_call = source[source.index('QStringLiteral("AddAndActivateConnection2")'):]
        add_call = add_call[:add_call.index("QDBusPendingCallWatcher")]
        self.assertIn("QVariant::fromValue(settings)", add_call)
        self.assertIn("QDBusObjectPath(m_wifiDevicePath)", add_call)
        self.assertIn('QDBusObjectPath(QStringLiteral("/"))', add_call)
        self.assertIn("QVariant::fromValue(options)", add_call)
        self.assertIn('QStringLiteral("persist"), QStringLiteral("disk")', source)
        add_method = source[source.index("void NetworkManagerClient::addAndActivateConnection()"):
                            source.index("void NetworkManagerClient::activateConnection(")]
        for setting in ('"connection"', '"802-11-wireless"', '"ipv4"', '"ipv6"',
                        '"802-11-wireless-security"', '"psk"', '"key-mgmt"'):
            self.assertIn(f"QStringLiteral({setting})", add_method)
        self.assertIn("QDBusPendingReply<QDBusObjectPath, QDBusObjectPath, QVariantMap>", add_method)
        self.assertIn('QStringLiteral("Update2")', source)
        self.assertIn("QVariant::fromValue(settings) << uint(0x1) << QVariantMap()", source)
        profile_lookup = source[source.index("void NetworkManagerClient::connectToWifi("):
                                source.index("void NetworkManagerClient::activateSavedConnection(")]
        self.assertEqual(profile_lookup.count(
            "finishConnectionAttempt(false, safeErrorText(reply.error().name()))"), 1)
        self.assertEqual(profile_lookup.count(
            "finishConnectionAttempt(false, safeErrorText(profileReply.error().name()))"), 1)

    def test_connect_button_requires_selected_supported_network_and_ssid(self):
        qml = (ROOT / "Settings/network.qml").read_text()
        self.assertIn("property var selectedAccessPoint: null", qml)
        self.assertIn("property string candidateSsid:", qml)
        self.assertIn("property bool selectedAccessPointSupported:", qml)
        self.assertIn("property bool canConnect:", qml)
        self.assertIn("&& selectedAccessPointSupported", qml)
        self.assertIn("&& candidateSsid.length > 0", qml)
        self.assertIn("enabled: networkSelector.canConnect", qml)
        self.assertIn("networkSelector.candidateSsid, pw1.text", qml)
        self.assertNotIn("currentIndex < 0", qml)
        self.assertNotIn("&& networkSelector.currentIndex", qml)
        self.assertIn("if (!selectedAccessPoint)\n                    return \"\"", qml)
        self.assertIn('return editText === selectedAccessPoint.displayName ? "" : editText.trim()', qml)
        self.assertIn("protected security unsupported", (ROOT / "networkmanagerclient.cpp").read_text())

        def candidate_ssid(access_point, edit_text):
            if access_point is None:
                return ""
            if access_point["hidden"]:
                return "" if edit_text == access_point["displayName"] else edit_text.strip()
            return access_point["ssid"].strip()

        def can_connect(access_point, edit_text, manager=True, wifi=True,
                        radio=True, connecting=False):
            return (manager and wifi and radio and not connecting
                    and access_point is not None
                    and access_point["supported"]
                    and len(candidate_ssid(access_point, edit_text)) > 0)

        visible = {"hidden": False, "ssid": "Workshop", "displayName": "Workshop",
                   "supported": True}
        hidden = {"hidden": True, "ssid": "", "displayName": "Hidden network (enter SSID)",
                  "supported": True}
        unsupported = {"hidden": False, "ssid": "Enterprise", "displayName": "Enterprise",
                       "supported": False}
        cases = [
            ("visible supported AP", visible, "Workshop", "Workshop", True),
            ("hidden AP with empty typed SSID", hidden, hidden["displayName"], "", False),
            ("hidden AP with typed SSID", hidden, "HiddenLab", "HiddenLab", True),
            ("unsupported protected AP", unsupported, "Enterprise", "Enterprise", False),
            ("no selection with empty text", None, "", "", False),
            ("no selection with typed text", None, "UnknownNetwork", "", False),
        ]
        for name, access_point, edit_text, expected_ssid, expected_enabled in cases:
            with self.subTest(name=name):
                self.assertEqual(candidate_ssid(access_point, edit_text), expected_ssid)
                self.assertEqual(can_connect(access_point, edit_text), expected_enabled)

    def test_connection_credentials_are_sent_to_networkmanager_not_logged(self):
        source = (ROOT / "networkmanagerclient.cpp").read_text()
        self.assertIn('QStringLiteral("AddAndActivateConnection2")', source)
        self.assertIn('QStringLiteral("Update2")', source)
        self.assertIn('QStringLiteral("persist"), QStringLiteral("disk")', source)
        self.assertIn("m_pendingPassword.fill(QChar(0))", source)
        attempt = source[source.index("void NetworkManagerClient::connectToWifi("):
                          source.index("void NetworkManagerClient::activateSavedConnection(")]
        self.assertLess(attempt.index("++m_connectionGeneration"),
                        attempt.index("clearTransientCredentials()"))
        self.assertLess(attempt.index("clearTransientCredentials()"),
                        attempt.index("m_pendingPassword ="))
        self.assertNotIn("m_pendingPassword <<", source)
        self.assertNotIn("qDebug() << m_pendingPassword", source)
        self.assertNotIn("qInfo() << m_pendingPassword", source)
        self.assertNotIn("wpa_supplicant", source)

    def test_network_page_masks_password_and_avoids_legacy_reboot_flow(self):
        qml = (ROOT / "Settings/network.qml").read_text()
        self.assertIn("echoMode: TextInput.Password", qml)
        self.assertIn("Qt.ImhSensitiveData", qml)
        self.assertIn("NetworkManager.scanWifi()", qml)
        self.assertIn("NetworkManager.connectToWifi", qml)
        self.assertIn("NetworkManager.disconnectWifi()", qml)
        self.assertNotIn("Wifiscanner", qml)
        self.assertNotIn("Connect.reboot()", qml)

    def test_can_configuration_function_is_not_rewritten_by_this_change(self):
        source = (ROOT / "connect.cpp").read_text()
        self.assertIn("void Connect::canbitratesetup(", source)
        self.assertIn("can0", source[source.index("void Connect::canbitratesetup("):])


if __name__ == "__main__":
    unittest.main()
