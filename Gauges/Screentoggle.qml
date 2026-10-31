import QtQuick 2.8
import QtQuick.Controls 2.1

Item {
    id: toggleswitch
    anchors.fill: parent
    visible: Connect.brightnessSupported()

    property bool on: false

    function toggle() {
        if (toggleswitch.state == "on")
        {
            if (Connect.setBrightness(50))
                toggleswitch.state = "off"
        }
        else
        {
            if (Connect.setBrightness(0))
                toggleswitch.state = "on";
        }
    }


    MouseArea {
        anchors.fill: parent
        onClicked: toggle()
    }

    states: [
        State {
            name: "on"
            PropertyChanges { target: toggleswitch; on: true }
        },
        State {
            name: "off"
            PropertyChanges { target: toggleswitch; on: false }
        }
    ]

    Text {
        text: qsTr("Press to switch off screen")
        font.pixelSize: parent.width * (20 / parent.width)//20
        anchors.centerIn: parent
        font.bold: true
        font.family: "Eurostile"
        color: "white"
    }
}
