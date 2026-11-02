function createPicture(setX,setY,setpictureheight,setValuePropertyMain,settriggervalue,setstatepicturesourceoff,setstatepicturesourceon,settriggeroffvalue) {
    var component = Qt.createComponent("StateGIF.qml");
    if (component.status === Component.Ready) {
        finishCreation(component,setX,setY,setpictureheight,setValuePropertyMain,settriggervalue,setstatepicturesourceoff,setstatepicturesourceon,settriggeroffvalue);
    } else if (component.status === Component.Loading) {
        component.statusChanged.connect(function(status) {
            if (status === Component.Ready) {
                finishCreation(component,setX,setY,setpictureheight,setValuePropertyMain,settriggervalue,setstatepicturesourceoff,setstatepicturesourceon,settriggeroffvalue);
            } else if (status === Component.Error) {
                console.warn("Unable to load State GIF widget:", component.errorString());
            }
        });
    } else if (component.status === Component.Error) {
        console.warn("Unable to load State GIF widget:", component.errorString());
    }
}

function finishCreation(component,setX,setY,setpictureheight,setValuePropertyMain,settriggervalue,setstatepicturesourceoff,setstatepicturesourceon,settriggeroffvalue) {
    if (component.status === Component.Ready) {
        var properties = {
            "x": setX,
            "y": setY,
            "pictureheight": setpictureheight
        };
        if (typeof setValuePropertyMain !== "undefined")
            properties.mainvaluename = setValuePropertyMain;
        if (typeof settriggervalue !== "undefined")
            properties.triggervalue = settriggervalue;
        if (typeof setstatepicturesourceoff !== "undefined")
            properties.statepicturesourceoff = setstatepicturesourceoff;
        if (typeof setstatepicturesourceon !== "undefined")
            properties.statepicturesourceon = setstatepicturesourceon;
        if (typeof settriggeroffvalue !== "undefined")
            properties.triggeroffvalue = settriggeroffvalue;

        var gauge = component.createObject(userDash, properties);
        if (gauge === null)
            console.error("Unable to create State GIF widget");
    }
}
