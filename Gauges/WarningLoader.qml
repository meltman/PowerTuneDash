import QtQuick 2.8

Rectangle {
    id: loadersource
    anchors.fill: parent
    color:"transparent"

    property bool rpmwarn
    property bool boostwarn
    property bool coolanttempwarn
    property bool knockwarn
    //property var warnmsg : "hello"

    Loader {
        anchors.fill:parent

        id: warningSign
        source: ""
    }
    Text {
        id: warnmsg
        text:"test"
        visible: false
        onTextChanged: {loadersource.setloadersource()}
    }
    Connections{
        target: Dashboard
        function onRpmChanged() {if (PTProfile.enabled) {PTProfile.count("qml.warningloader.onRpmChanged")} if (Dashboard.rpm > Dashboard.rpmwarn) {rpmwarn = true,warnmsg.text = "Danger to Manifold"} else rpmwarn= false }
        function onPimChanged() {if (Dashboard.pim > Dashboard.boostwarn) {boostwarn = true,warnmsg.text = "Boost " +(Dashboard.pim).toFixed(1)} else boostwarn= false }
        function onWatertempChanged() {if (PTProfile.enabled) {PTProfile.count("qml.warningloader.onWatertempChanged")} if (Dashboard.Watertemp > Dashboard.waterwarn) {coolanttempwarn = true,warnmsg.text = "Coolant Temp. " + (Dashboard.Watertemp).toFixed(1)} else coolanttempwarn= false }
        function onKnockChanged() {if (Dashboard.Knock > Dashboard.knockwarn) {knockwarn = true,warnmsg.text = "Knock " + (Dashboard.Knock).toFixed(0)} else knockwarn= false }
    }

    Connections{
        target: loadersource
        function onRpmwarnChanged() {loadersource.setloadersource()}
        function onBoostwarnChanged() {loadersource.setloadersource()}
        function onCoolanttempwarnChanged() {loadersource.setloadersource()}
        function onKnockwarnChanged() {loadersource.setloadersource()}
    }


    function setloadersource()
    {
        if (rpmwarn == true || boostwarn == true || coolanttempwarn == true ||knockwarn == true ) {warningSign.setSource("qrc:/Gauges/Warning.qml",{ "warningtext": warnmsg.text })};
        if (rpmwarn == false && boostwarn == false && coolanttempwarn == false && knockwarn == false ){warningSign.source = ""} //Removes all warning signs
    }

}
//
