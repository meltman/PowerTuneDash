#include <QApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QtQml>
#include <QFileSystemModel>
#include "connect.h"
#include "Extender.h"
#include "iomapdata.h"
#include "downloadmanager.h"
#include "ptpaths.h"
#include <QDebug>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QLoggingCategory>
#include <QMessageLogContext>
#include <QMutex>
#include <QMutexLocker>
#include <cstdio>

namespace {

QFile applicationLog;
QMutex applicationLogMutex;
QtMessageHandler previousMessageHandler = nullptr;
bool applicationLogWriteErrorReported = false;

const char *severityName(QtMsgType type)
{
    switch (type) {
    case QtDebugMsg:
        return "DEBUG";
    case QtInfoMsg:
        return "INFO";
    case QtWarningMsg:
        return "WARNING";
    case QtCriticalMsg:
        return "CRITICAL";
    case QtFatalMsg:
        return "FATAL";
    default:
        return "UNKNOWN";
    }
}

void applicationMessageHandler(QtMsgType type, const QMessageLogContext &context,
                               const QString &message)
{
    if (previousMessageHandler) {
        previousMessageHandler(type, context, message);
    } else {
        const QByteArray formattedMessage = qFormatLogMessage(type, context, message).toLocal8Bit();
        fwrite(formattedMessage.constData(), 1, formattedMessage.size(), stderr);
        fputc('\n', stderr);
        fflush(stderr);
    }

    QMutexLocker locker(&applicationLogMutex);
    if (!applicationLog.isOpen())
        return;

    const QString entry = QStringLiteral("%1 [%2] %3\n")
                              .arg(QDateTime::currentDateTime().toString(Qt::ISODateWithMs),
                                   QString::fromLatin1(severityName(type)), message);
    const QByteArray encodedEntry = entry.toUtf8();
    if (applicationLog.write(encodedEntry) != encodedEntry.size() || !applicationLog.flush()) {
        if (!applicationLogWriteErrorReported) {
            const QByteArray error = QStringLiteral("PowerTune: writing application log %1 failed: %2\n")
                                         .arg(applicationLog.fileName(), applicationLog.errorString())
                                         .toLocal8Bit();
            fwrite(error.constData(), 1, error.size(), stderr);
            fflush(stderr);
            applicationLogWriteErrorReported = true;
        }
        applicationLog.close();
    }
}

void initializeApplicationLogging()
{
    const QString logPath = QDir(ptLogsPath()).filePath(QStringLiteral("powertunedash.log"));
    applicationLog.setFileName(logPath);
    if (!applicationLog.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text)) {
        const QByteArray error = QStringLiteral("PowerTune: cannot open application log %1: %2\n")
                                     .arg(logPath, applicationLog.errorString())
                                     .toLocal8Bit();
        fwrite(error.constData(), 1, error.size(), stderr);
        fflush(stderr);
    }

    previousMessageHandler = qInstallMessageHandler(applicationMessageHandler);
}

}

    ioMapData mpd;

int main(int argc, char *argv[])
{
    qputenv("QT_IM_MODULE", QByteArray("qtvirtualkeyboard"));
    initializeApplicationLogging();
    QApplication app(argc, argv);
    app.setOrganizationName("Power-Tune");
    app.setOrganizationDomain("power-tune.org");
    app.setApplicationName("PowerTune");
    QQmlApplicationEngine engine;
    qmlRegisterType<ioMapData>("IMD", 1, 0, "IMD");
    qmlRegisterType<DownloadManager>("DLM", 1, 0, "DLM");
    qmlRegisterType<Connect>("com.powertune", 1, 0, "ConnectObject");

    engine.rootContext()->setContextProperty("IMD", new ioMapData(&engine));
    engine.rootContext()->setContextProperty("DLM", new DownloadManager(&engine));
    engine.rootContext()->setContextProperty("Connect", new Connect(&engine));
    engine.rootContext()->setContextProperty("Extender2",new Extender(&engine));

    // Base directory for PowerTune data folders (Logo, UserDashboards, maptiles, ...).
    // Linux -> /home/pi, Windows -> C:/PowerTune. See ptpaths.h.
    // PTBasePath is a plain filesystem path; PTBaseUrl is the file:// URL form.
    engine.rootContext()->setContextProperty("PTBasePath", ptBasePath());
    engine.rootContext()->setContextProperty("PTBaseUrl", ptBaseUrl());

#ifdef HAVE_DDCUTIL
    engine.rootContext()->setContextProperty("HAVE_DDCUTIL", true);
#else
    engine.rootContext()->setContextProperty("HAVE_DDCUTIL", false);
#endif
    engine.load(QUrl(QStringLiteral("qrc:/main.qml")));
    return app.exec();

}
