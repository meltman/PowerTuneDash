TEMPLATE = app

QT += qml quick serialport serialbus network dbus charts location positioning sensors multimedia widgets

CONFIG += c++11

# Build provenance: pass `qmake PT_BUILD_VERSION=... PT_BUILD_REVISION=...
# [PT_BUILD_BRANCH=...]` or set the same names in the environment. When absent,
# ptbuildinfo.h falls back to "unknown".
isEmpty(PT_BUILD_VERSION): PT_BUILD_VERSION = $$(PT_BUILD_VERSION)
isEmpty(PT_BUILD_REVISION): PT_BUILD_REVISION = $$(PT_BUILD_REVISION)
isEmpty(PT_BUILD_BRANCH): PT_BUILD_BRANCH = $$(PT_BUILD_BRANCH)
!isEmpty(PT_BUILD_VERSION): DEFINES += PT_BUILD_VERSION=\\\"$$PT_BUILD_VERSION\\\"
!isEmpty(PT_BUILD_REVISION): DEFINES += PT_BUILD_REVISION=\\\"$$PT_BUILD_REVISION\\\"
!isEmpty(PT_BUILD_BRANCH): DEFINES += PT_BUILD_BRANCH=\\\"$$PT_BUILD_BRANCH\\\"

# QMAKE_LFLAGS += -static
static {
    QT += svg
    QTPLUGIN += qtvirtualkeyboardplugin
}


SOURCES += main.cpp \
    Extender.cpp \
    dashboard.cpp \
    downloadmanager.cpp \
    iomapdata.cpp \
    parsegithubdata.cpp \
    serialport.cpp \
    appsettings.cpp \
    gopro.cpp \
    gps.cpp \
    sensors.cpp \
    datalogger.cpp \
    Apexi.cpp \
    AdaptronicSelect.cpp \
    connect.cpp \
    calculations.cpp \
    shcalc.cpp \
    textprogressbar.cpp \
    udpreceiver.cpp \
    ptprofile.cpp \
    arduino.cpp \
    networkmanagerclient.cpp


RESOURCES += qml.qrc

# Additional import path used to resolve QML modules in Qt Creator's code model
QML_IMPORT_PATH =

# Default rules for deployment.
include(deployment.pri)

HEADERS += \
    Extender.h \
    dashboard.h \
    downloadmanager.h \
    iomapdata.h \
    parsegithubdata.h \
    serialport.h \
    appsettings.h \
    gopro.h \
    gps.h \
    sensors.h \
    datalogger.h \
    Apexi.h \
    AdaptronicSelect.h \
    connect.h \
    calculations.h \
    shcalc.h \
    textprogressbar.h \
    udpreceiver.h \
    ptprofile.h \
    arduino.h \
    networkmanagerclient.h


FORMS +=

DISTFILES += \
    KTracks/Australia/KimTestTrack - Copy.txt \
    KTracks/Australia/stupid2.txt \
    KTracks/Australia/stupid3.txt \
    KTracks/Australia/stupid4.txt
