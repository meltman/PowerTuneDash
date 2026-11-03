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

    function stateLabel(state) {
        return state.length ? state.charAt(0).toUpperCase() + state.slice(1)
                            : qsTr("Unavailable")
    }

    function wifiStatusColor() {
        if (!NetworkManager.managerAvailable || !NetworkManager.wifiAvailable
                || !NetworkManager.wifiRadioEnabled)
            return "red"
        if (NetworkManager.wifiState === "connected")
            return "green"
        if (NetworkManager.wifiConnecting
                || ["preparing", "configuring", "waiting for credentials", "configuring IP",
                    "checking connection", "finishing connection"].indexOf(NetworkManager.wifiState) >= 0)
            return "orange"
        return "red"
    }

    function wifiErrorMessage(error) {
        if (error === "Wi-Fi authentication failed. Check the password.")
            return qsTr("Wi-Fi authentication failed. Check the password.")
        if (error === "The network did not provide a usable IP configuration.")
            return qsTr("Wi-Fi connected, but IP configuration failed.")
        if (error === "NetworkManager could not connect. Check the network and credentials.")
            return qsTr("NetworkManager could not connect to this Wi-Fi network.")
        var knownSafeErrors = [
            "System D-Bus is unavailable.",
            "Could not discover NetworkManager devices.",
            "NetworkManager is unavailable.",
            "No Wi-Fi device is available.",
            "Wi-Fi is disabled.",
            "Wi-Fi is not connected.",
            "NetworkManager could not scan for Wi-Fi networks.",
            "Wi-Fi scan timed out.",
            "Wi-Fi is not available.",
            "Select a network before connecting.",
            "This Wi-Fi security type is not supported.",
            "NetworkManager needs valid Wi-Fi credentials.",
            "NetworkManager denied the connection request.",
            "NetworkManager rejected the Wi-Fi settings.",
            "The saved Wi-Fi profile is invalid.",
            "The selected Wi-Fi network was not found. Check that it is in range.",
            "Connection cancelled.",
            "NetworkManager could not disconnect Wi-Fi."
        ]
        return knownSafeErrors.indexOf(error) >= 0
                ? error : qsTr("NetworkManager could not connect to this Wi-Fi network.")
    }

    function ethernetStatusText() {
        if (!NetworkManager.ethernetAvailable)
            return qsTr("Ethernet unavailable")
        var state = NetworkManager.ethernetConnected ? qsTr("Connected")
                   : NetworkManager.ethernetCarrier ? qsTr("Link up")
                   : stateLabel(NetworkManager.ethernetState)
        return NetworkManager.ethernetDeviceName + ": " + state
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

    property bool wifiErrorDismissed: false
    property string observedWifiError: NetworkManager.wifiError

    Connections {
        target: NetworkManager
        function onAccessPointsChanged() {
            networkSelector.restoreSelection()
        }
        function onWifiStateChanged() {
            networkSelector.restoreSelection()
            if (NetworkManager.wifiError !== extrarect.observedWifiError) {
                extrarect.observedWifiError = NetworkManager.wifiError
                extrarect.wifiErrorDismissed = false
            }
        }
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
                    editable: false
                    enabled: NetworkManager.wifiAvailable && NetworkManager.wifiRadioEnabled
                    currentIndex: -1
                    property var selectedAccessPoint: null
                    property string selectedSsid: ""
                    property string selectedPath: ""
                    property string candidateSsid: {
                        if (!selectedAccessPoint)
                            return ""
                        if (selectedAccessPoint.hidden)
                            return hiddenSsidField.text.trim()
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
                    function findAccessPoint(ssid, path) {
                        var points = NetworkManager.accessPoints
                        for (var i = 0; i < points.length; ++i) {
                            var point = points[i]
                            if (path.length && point.path === path)
                                return i
                            if (ssid.length && !point.hidden && point.ssid === ssid)
                                return i
                        }
                        return -1
                    }
                    function restoreSelection() {
                        var points = NetworkManager.accessPoints
                        var connectedIndex = NetworkManager.wifiCurrentSsid.length
                                ? findAccessPoint(NetworkManager.wifiCurrentSsid, "") : -1
                        var wantedIndex = connectedIndex >= 0 ? connectedIndex
                                : findAccessPoint(selectedSsid, selectedPath)
                        currentIndex = wantedIndex
                        selectedAccessPoint = wantedIndex >= 0 ? points[wantedIndex] : null
                    }
                    onActivated: {
                        var previousPath = selectedPath
                        var selected = NetworkManager.accessPoints[index]
                        if (!selected.hidden || selected.path !== previousPath)
                            hiddenSsidField.clear()
                        selectedAccessPoint = selected
                        selectedSsid = selectedAccessPoint.hidden ? "" : selectedAccessPoint.ssid
                        selectedPath = selectedAccessPoint.hidden ? selectedAccessPoint.path : ""
                        extrarect.wifiErrorDismissed = true
                    }
                    delegate: ItemDelegate {
                        width: networkSelector.width
                        text: modelData.displayName
                        highlighted: networkSelector.highlightedIndex == index
                        hoverEnabled: networkSelector.hoverEnabled
                    }
                }
                TextField {
                    id: hiddenSsidField
                    width: parent.width
                    height: 40
                    visible: networkSelector.selectedAccessPoint !== null
                             && networkSelector.selectedAccessPoint.hidden
                    placeholderText: qsTr("Enter hidden Wi-Fi network name")
                    onTextChanged: extrarect.wifiErrorDismissed = true
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
                            extrarect.wifiErrorDismissed = true
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
                        onClicked: {
                            NetworkManager.cancelConnectionAttempt()
                            extrarect.wifiErrorDismissed = true
                        }
                    }
                }
                Quick1.Button {
                    id: wifiStatus
                    text: NetworkManager.managerAvailable && NetworkManager.wifiAvailable
                          ? NetworkManager.wifiDeviceName + ": " + extrarect.stateLabel(NetworkManager.wifiState)
                          : qsTr("Wi-Fi unavailable")
                    width: parent.width
                    height: 40
                    style: ButtonStyle {
                        label: Label {
                            text: wifiStatus.text
                            color: "black"
                            width: wifiStatus.width - 12
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            wrapMode: Text.NoWrap
                        }
                        background: Rectangle {
                            color: extrarect.wifiStatusColor()
                            border.width: control.activeFocus ? 2 : 1
                            border.color: "#888"
                        }
                    }
                }
                Label {
                    width: parent.width
                    height: 28
                    text: "IPv4: " + (extrarect.firstIpv4Address(NetworkManager.wifiIpv4Addresses) || "-")
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    clip: true
                }
                Label {
                    width: parent.width
                    height: 28
                    text: "IPv6: " + (extrarect.preferredIpv6Address(NetworkManager.wifiIpv6Addresses) || "-")
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    clip: true
                }
                Label {
                    width: parent.width
                    height: 52
                    text: extrarect.wifiErrorMessage(NetworkManager.wifiError)
                    color: "darkred"
                    elide: Text.ElideRight
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    clip: true
                    visible: text.length > 0 && !extrarect.wifiErrorDismissed
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
                    text: extrarect.ethernetStatusText()
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
                    text: "IPv4: " + (extrarect.firstIpv4Address(NetworkManager.ethernetIpv4Addresses) || "-")
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    clip: true
                }
                Label {
                    width: parent.width
                    height: 28
                    text: "IPv6: " + (extrarect.preferredIpv6Address(NetworkManager.ethernetIpv6Addresses) || "-")
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                    clip: true
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
