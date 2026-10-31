#ifndef PTPATHS_H
#define PTPATHS_H

#include <QString>
#include <QDir>
#include <QUrl>
#include <QtGlobal>

// Role-specific directories for the Linux runtime layout. Callers will migrate
// to these helpers in later phases; Windows keeps the existing development
// layout until then.
//
// The URL helpers are for local files exposed to QML. Use QUrl to encode
// platform-specific local-file URL syntax.
inline QString ptResourcesPath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/usr/share/powertune");
#endif
}

inline QString ptDataPath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/var/lib/powertune");
#endif
}

inline QString ptDashboardsPath()
{
    return QDir(ptDataPath()).filePath(QStringLiteral("UserDashboards"));
}

inline QString ptLogoPath()
{
    return QDir(ptDataPath()).filePath(QStringLiteral("Logo"));
}

inline QString ptLogoFileUrl(const QString &fileName)
{
    return QUrl::fromLocalFile(QDir(ptLogoPath()).filePath(fileName)).toString();
}

inline QString ptResolveLogoUrl(const QString &resource)
{
    const QString legacyLogoPrefix = QStringLiteral("file:///home/pi/Logo/");
    if (resource == QStringLiteral("None") ||
        resource == QStringLiteral("/Logo") ||
        !resource.startsWith(legacyLogoPrefix)) {
        return resource;
    }

    const QString fileName = QUrl::fromPercentEncoding(
        resource.mid(legacyLogoPrefix.size()).toUtf8());
    return ptLogoFileUrl(fileName);
}

inline QString ptConfigPath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/etc/powertune");
#endif
}

inline QString ptHelpersPath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/usr/libexec/powertune");
#endif
}

inline QString ptLogsPath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/var/log/powertune");
#endif
}

inline QString ptResourcesUrl()
{
    return QUrl::fromLocalFile(ptResourcesPath()).toString();
}

inline QString ptDataUrl()
{
    return QUrl::fromLocalFile(ptDataPath()).toString();
}

// Legacy compatibility API. Runtime callers remain on this path until later
// migration phases; do not use for new path lookups.
inline QString ptBasePath()
{
#ifdef Q_OS_WIN
    return QStringLiteral("C:/PowerTune");
#else
    return QStringLiteral("/home/pi");
#endif
}

// Legacy compatibility API for QML/local-file URLs. Kept in sync with
// ptBasePath() until existing callers are migrated.
inline QString ptBaseUrl()
{
    return QUrl::fromLocalFile(ptBasePath()).toString();
}

#endif // PTPATHS_H
