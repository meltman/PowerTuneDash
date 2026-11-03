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

    Flickable {
        id: flickable
        width: 450
        height: 400

        TextArea.flickable: TextArea {
            id: consoleText
            wrapMode: TextArea.Wrap
            readOnly: true
            color: "green"
            font.pixelSize: 15
            background: Rectangle {
                height: flickable.height
                width: flickable.width
                color: "black"
            }
        }

        ScrollBar.vertical: ScrollBar {
            id: scrollBar
            policy: ScrollBar.AlwaysOn
        }
    }

    Grid {
        id: extragrid
        anchors.top: parent.top
        anchors.topMargin: parent.height / 20
        anchors.right: parent.right
        rows: 12
        columns: 2
        spacing: parent.width / 150

        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Button {
            id: btnScanNetwork
            text: NetworkManager.wifiScanning ? qsTr("Scanning...") : qsTr("Scan Wi-Fi")
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55
            enabled: NetworkManager.managerAvailable && NetworkManager.wifiAvailable
                     && NetworkManager.wifiRadioEnabled && !NetworkManager.wifiScanning
            onClicked: {
                consoleText.clear()
                NetworkManager.scanWifi()
            }
        }
        Text {
            text: qsTr("Wi-Fi network")
            font.pixelSize: extrarect.width / 55
        }
        ComboBox {
            id: networkSelector
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55
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
                font.pixelSize: networkSelector.font.pixelSize
                highlighted: networkSelector.highlightedIndex == index
                hoverEnabled: networkSelector.hoverEnabled
            }
        }
        Text {
            text: qsTr("Password")
            font.pixelSize: extrarect.width / 55
        }
        TextField {
            id: pw1
            placeholderText: qsTr("Wi-Fi password (if required)")
            width: extrarect.width / 5
            font.pixelSize: extrarect.width / 55
            echoMode: TextInput.Password
            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
            enabled: NetworkManager.wifiAvailable && NetworkManager.wifiRadioEnabled
        }

        Text {
            text: qsTr("Connection")
            font.pixelSize: extrarect.width / 55
        }

        Button {
            id: applyWifiSettings
            text: NetworkManager.wifiConnecting ? qsTr("Connecting...") : qsTr("Connect")
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55
            enabled: networkSelector.canConnect
            onClicked: {
                NetworkManager.connectToWifi(networkSelector.candidateSsid, pw1.text,
                                             networkSelector.selectedAccessPoint.keyManagement)
                pw1.clear()
            }
        }
        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Row {
            width: extrarect.width / 5
            spacing: extrarect.width / 100
            Button {
                text: qsTr("Disconnect")
                height: extrarect.height / 15
                font.pixelSize: extrarect.width / 55
                enabled: NetworkManager.wifiState == "connected"
                onClicked: NetworkManager.disconnectWifi()
            }
            Button {
                text: qsTr("Cancel")
                height: extrarect.height / 15
                font.pixelSize: extrarect.width / 55
                visible: NetworkManager.wifiConnecting
                onClicked: NetworkManager.cancelConnectionAttempt()
            }
        }
        Text {
            text: qsTr("Wi-Fi status")
            font.pixelSize: extrarect.width / 55
        }
        Text {
            text: !NetworkManager.managerAvailable ? qsTr("NetworkManager unavailable")
                  : !NetworkManager.wifiAvailable ? qsTr("Wi-Fi unavailable")
                  : !NetworkManager.wifiRadioEnabled ? qsTr("Wi-Fi radio disabled")
                  : NetworkManager.wifiCurrentSsid.length
                    ? NetworkManager.wifiState + " - " + NetworkManager.wifiCurrentSsid
                    : NetworkManager.wifiState
            font.pixelSize: extrarect.width / 60
            elide: Text.ElideRight
        }
        Text {
            text: qsTr("Wi-Fi addresses")
            font.pixelSize: extrarect.width / 55
        }
        Text {
            text: NetworkManager.wifiIpv4Addresses.concat(NetworkManager.wifiIpv6Addresses).join(", ")
            font.pixelSize: extrarect.width / 60
            elide: Text.ElideRight
        }
        Text {
            text: NetworkManager.wifiError
            color: "darkred"
            font.pixelSize: extrarect.width / 60
            elide: Text.ElideRight
            visible: text.length > 0
        }
        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
            visible: !NetworkManager.wifiError.length
        }

        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Button {
            id: updateBtn
            text: Translator.translate("Update", Dashboard.language)
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55
            onClicked: {
                Connect.update()
                updateBtn.enabled = false
            }
        }

        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }

        Button {
            id: develtest
            text: Translator.translate("Restart daemon", Dashboard.language)
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55

            onClicked: {

                //Arduino.openConnection("COM11");
                Connect.restartDaemon()
                //develtest.enabled = false;
            }
        }
        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Button {
            id: trackUpdate
            text: Translator.translate("Update Tracks", Dashboard.language)
            width: extrarect.width / 5
            height: extrarect.height / 15
            font.pixelSize: extrarect.width / 55
            onClicked: {
                downloadManager.append("") // needed as a workarround
                downloadManager.append(
                            "https://gitlab.com/PowerTuneDigital/PowertuneTracks/-/raw/main/repo.txt")
                downloadManager.append("") // needed as a workarround
                consoleText.append("Downloading Tracks for Laptimer :")
                trackUpdate.enabled = false
                downloadprogress.indeterminate = true
            }
        }
        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Quick1.ProgressBar {
            id: downloadprogress
            width: extrarect.width / 5
            height: extrarect.height / 15
        }
        Text {
            id: ethernetip
            text: Translator.translate("Ethernet IP adress", Dashboard.language)
            font.pixelSize: extrarect.width / 55
            visible: true
        }

        Quick1.Button {
            id: ethernetstatus
            text: NetworkManager.ethernetAvailable
                  ? NetworkManager.ethernetDeviceName + ": " + NetworkManager.ethernetState
                    + " " + NetworkManager.ethernetIpv4Addresses.concat(NetworkManager.ethernetIpv6Addresses).join(", ")
                  : qsTr("Ethernet unavailable")
            width: extrarect.width / 5
            height: extrarect.height / 15
            style: ButtonStyle {
                label: Label {
                    text: ethernetstatus.text
                    color: "black"
                    font.pixelSize: extrarect.width / 55
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: {
                        NetworkManager.ethernetState == "connected" ? "green"
                          : NetworkManager.ethernetState.indexOf("link up") >= 0 ? "orange" : "red"
                    }
                    border.width: control.activeFocus ? 2 : 1
                    border.color: "#888"
                }
            }
        }

        Text {
            id: wlanip
            text: Translator.translate("WLAN IP adress", Dashboard.language)
            font.pixelSize: extrarect.width / 55
            visible: true
        }
        Quick1.Button {
            id: wifistatus
            text: NetworkManager.wifiCurrentSsid.length
                  ? NetworkManager.wifiDeviceName + ": " + NetworkManager.wifiCurrentSsid
                  : NetworkManager.wifiDeviceName + ": " + NetworkManager.wifiState
            width: extrarect.width / 5
            height: extrarect.height / 15
            style: ButtonStyle {
                label: Label {
                    text: wifistatus.text
                    color: "black"
                    font.pixelSize: extrarect.width / 55
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: {
                        NetworkManager.wifiState == "connected" ? "green" : "red"
                    }
                    border.width: control.activeFocus ? 2 : 1
                    border.color: "#888"
                }
            }
        }
        Text {
            text: " "
            font.pixelSize: extrarect.width / 55
        }
        Text {
            id: downloadspeedtext
            text: downloadManager.downloadStatus
            font.pixelSize: extrarect.width / 55
            onTextChanged: {
                if (downloadspeedtext.text == "Finished") {
                    //trackUpdate.enabled = true;
                    downloadprogress.indeterminate = false
                    downloadspeedtext.text = " "
                    Connect.changefolderpermission()
                }
            }
        }
        Text {
            id: downloadfilenametext
            text: downloadManager.downloadFilename
            font.pixelSize: extrarect.width / 55
            visible: false
            onTextChanged: consoleText.append(downloadManager.downloadFilename)
        }


        /*

        Button {
            id: develtest1
            text: "Development dont click"
            width: extrarect.width / 5
            height: extrarect.height /15
            font.pixelSize: extrarect.width / 55
            onClicked: Connect.canbitratesetup(0)

        }*/
    }
}
