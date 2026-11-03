import QtQuick 2.8
import QtQuick.Controls 2.1
import QtQuick.Controls 1.4 as Quick1
import QtQuick.Controls.Styles 1.4
import "qrc:/Translator.js" as Translator

Rectangle {
    id: extrarect
    anchors.fill: parent
    color: "grey"
    Component.onCompleted: NetworkManager.refresh()

    function firstIpv4Address(addresses) {
        return addresses.length ? addresses[0] : ""
    }

    function preferredIpv6Address(addresses) {
        var firstLinkLocal = ""
        for (var i = 0; i < addresses.length; ++i) {
            if (!/^fe[89ab]/i.test(addresses[i]))
                return addresses[i]
            if (!firstLinkLocal)
                firstLinkLocal = addresses[i]
        }
        return firstLinkLocal
    }

    function addressSummary(ipv4, ipv6) {
        var v4 = firstIpv4Address(ipv4)
        var v6 = preferredIpv6Address(ipv6)
        return "IPv4: " + (v4 || "-") + "  IPv6: " + (v6 || "-")
    }

    Row {
        id: sections
        anchors.fill: parent
        anchors.margins: parent.width / 60
        spacing: 12

        GroupBox {
            id: wifiSection
            title: qsTr("Wi-Fi")
            width: (sections.width - sections.spacing * 2) * 0.46
            height: sections.height

            Column {
                anchors.fill: parent
                spacing: 8

                Button {
                    id: btnScanNetwork
                    text: NetworkManager.wifiScanning ? qsTr("Scanning...") : qsTr("Scan Wi-Fi")
                    width: parent.width
                    height: 40
                    enabled: NetworkManager.managerAvailable && NetworkManager.wifiAvailable
                             && NetworkManager.wifiRadioEnabled && !NetworkManager.wifiScanning
                    onClicked: NetworkManager.scanWifi()
                }
                Label { text: qsTr("Wi-Fi network") }
                ComboBox {
                    id: networkSelector
                    width: parent.width
                    height: 40
                    model: NetworkManager.accessPoints
                    textRole: "displayName"
                    editable: true
                    enabled: NetworkManager.wifiAvailable && NetworkManager.wifiRadioEnabled
                    property var selectedAccessPoint: null
                    property string candidateSsid: {
                        if (!selectedAccessPoint)
                            return ""
                        if (selectedAccessPoint.hidden)
                            return editText === selectedAccessPoint.displayName ? "" : editText.trim()
                        return selectedAccessPoint.ssid.trim()
                    }
                    property bool selectedAccessPointSupported: selectedAccessPoint !== null
                                                               && selectedAccessPoint.supported
                    property bool canConnect: NetworkManager.managerAvailable
                                             && NetworkManager.wifiAvailable
                                             && NetworkManager.wifiRadioEnabled
                                             && !NetworkManager.wifiConnecting
                                             && selectedAccessPointSupported
                                             && candidateSsid.length > 0
                    onActivated: selectedAccessPoint = NetworkManager.accessPoints[index]
                    delegate: ItemDelegate {
                        width: networkSelector.width
                        text: modelData.displayName
                        highlighted: networkSelector.highlightedIndex == index
                        hoverEnabled: networkSelector.hoverEnabled
                    }
                }
                Label { text: qsTr("Password") }
                TextField {
                    id: pw1
                    width: parent.width
                    height: 40
                    placeholderText: qsTr("Wi-Fi password (if required)")
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    enabled: NetworkManager.wifiAvailable && NetworkManager.wifiRadioEnabled
                }
                Row {
                    spacing: 8
                    Button {
                        id: applyWifiSettings
                        text: NetworkManager.wifiConnecting ? qsTr("Connecting...") : qsTr("Connect")
                        height: 40
                        enabled: networkSelector.canConnect
                        onClicked: {
                            NetworkManager.connectToWifi(networkSelector.candidateSsid, pw1.text,
                                                         networkSelector.selectedAccessPoint.keyManagement)
                            pw1.clear()
                        }
                    }
                    Button {
                        text: qsTr("Disconnect")
                        height: 40
                        enabled: NetworkManager.wifiState == "connected"
                        onClicked: NetworkManager.disconnectWifi()
                    }
                    Button {
                        text: qsTr("Cancel")
                        height: 40
                        visible: NetworkManager.wifiConnecting
                        onClicked: NetworkManager.cancelConnectionAttempt()
                    }
                }
                Label {
                    width: parent.width
                    height: 28
                    text: !NetworkManager.managerAvailable ? qsTr("NetworkManager unavailable")
                          : !NetworkManager.wifiAvailable ? qsTr("Wi-Fi unavailable")
                          : !NetworkManager.wifiRadioEnabled ? qsTr("Wi-Fi radio disabled")
                          : NetworkManager.wifiCurrentSsid.length
                            ? NetworkManager.wifiState + " - " + NetworkManager.wifiCurrentSsid
                            : NetworkManager.wifiState
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
                Label {
                    width: parent.width
                    height: 28
                    text: extrarect.addressSummary(NetworkManager.wifiIpv4Addresses,
                                                   NetworkManager.wifiIpv6Addresses)
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
                Label {
                    width: parent.width
                    height: 28
                    text: NetworkManager.wifiError
                    color: "darkred"
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    visible: text.length > 0
                }
            }
        }

        GroupBox {
            id: ethernetSection
            title: qsTr("Ethernet")
            width: (sections.width - sections.spacing * 2) * 0.28
            height: sections.height

            Column {
                anchors.fill: parent
                spacing: 8
                Quick1.Button {
                    id: ethernetstatus
                    text: NetworkManager.ethernetAvailable
                          ? NetworkManager.ethernetDeviceName + ": " + NetworkManager.ethernetState
                            : qsTr("Ethernet unavailable")
                    width: parent.width
                    height: 40
                    style: ButtonStyle {
                        label: Label {
                            text: ethernetstatus.text
                            color: "black"
                            width: ethernetstatus.width - 12
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            wrapMode: Text.NoWrap
                        }
                        background: Rectangle {
                            color: NetworkManager.ethernetConnected ? "green"
                                   : NetworkManager.ethernetCarrier ? "orange" : "red"
                            border.width: control.activeFocus ? 2 : 1
                            border.color: "#888"
                        }
                    }
                }
                Label {
                    width: parent.width
                    height: 28
                    text: extrarect.addressSummary(NetworkManager.ethernetIpv4Addresses,
                                                   NetworkManager.ethernetIpv6Addresses)
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
            }
        }

        GroupBox {
            id: utilitySection
            title: qsTr("PowerTune")
            width: sections.width - wifiSection.width - ethernetSection.width - sections.spacing * 2
            height: sections.height

            Column {
                anchors.fill: parent
                spacing: 8

                Button {
                    id: updateBtn
                    text: Translator.translate("Update", Dashboard.language)
                    width: parent.width
                    height: 40
                    onClicked: {
                        Connect.update()
                        updateBtn.enabled = false
                    }
                }
                Button {
                    text: Translator.translate("Restart daemon", Dashboard.language)
                    width: parent.width
                    height: 40
                    onClicked: Connect.restartDaemon()
                }
                Button {
                    id: trackUpdate
                    text: Translator.translate("Update Tracks", Dashboard.language)
                    width: parent.width
                    height: 40
                    onClicked: {
                        downloadManager.append("")
                        downloadManager.append(
                                    "https://gitlab.com/PowerTuneDigital/PowertuneTracks/-/raw/main/repo.txt")
                        downloadManager.append("")
                        trackUpdate.enabled = false
                        downloadprogress.indeterminate = true
                    }
                }
                Quick1.ProgressBar {
                    id: downloadprogress
                    width: parent.width
                    height: 32
                }
                Label {
                    id: downloadspeedtext
                    width: parent.width
                    text: downloadManager.downloadStatus
                    elide: Text.ElideRight
                    onTextChanged: {
                        if (downloadspeedtext.text == "Finished") {
                            downloadprogress.indeterminate = false
                            downloadspeedtext.text = " "
                            Connect.changefolderpermission()
                        }
                    }
                }
                Label {
                    id: downloadfilenametext
                    width: parent.width
                    text: downloadManager.downloadFilename
                    elide: Text.ElideRight
                }
            }
        }
    }
}
