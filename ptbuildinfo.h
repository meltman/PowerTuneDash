#ifndef PTBUILDINFO_H
#define PTBUILDINFO_H

#include <QString>
#include <QVariantMap>

// Build provenance is injected by PowertuneQMLGui.pro (from qmake variables or
// the environment supplied by the BitBake recipe). Nothing here reads Git or
// the source tree at runtime. Missing metadata falls back to "unknown".

#ifndef PT_BUILD_VERSION
#define PT_BUILD_VERSION "unknown"
#endif

#ifndef PT_BUILD_REVISION
#define PT_BUILD_REVISION "unknown"
#endif

// Optional; only defined when the build can establish it robustly.
#ifndef PT_BUILD_BRANCH
#define PT_BUILD_BRANCH ""
#endif

// Upstream PowerTune release this fork is based on.
#define PT_UPSTREAM_BASE_VERSION "1.99t"

inline QString ptBuildVersion() { return QStringLiteral(PT_BUILD_VERSION); }
inline QString ptBuildRevision() { return QStringLiteral(PT_BUILD_REVISION); }
inline QString ptBuildBranch() { return QStringLiteral(PT_BUILD_BRANCH); }
inline QString ptUpstreamBase() { return QStringLiteral(PT_UPSTREAM_BASE_VERSION); }

inline QString ptBuildLogLine()
{
    QString line = QStringLiteral("PowerTune build: version=\"%1\", revision=\"%2\"")
                       .arg(ptBuildVersion(), ptBuildRevision());
    if (!ptBuildBranch().isEmpty())
        line += QStringLiteral(", branch=\"%1\"").arg(ptBuildBranch());
    return line;
}

inline QVariantMap ptBuildInfo()
{
    QVariantMap info;
    info.insert(QStringLiteral("product"), QStringLiteral("PowerTune i.MX8 Appliance"));
    info.insert(QStringLiteral("version"), ptBuildVersion());
    info.insert(QStringLiteral("revision"), ptBuildRevision());
    info.insert(QStringLiteral("branch"), ptBuildBranch());
    info.insert(QStringLiteral("upstreamBase"), ptUpstreamBase());
    info.insert(QStringLiteral("display"),
                QStringLiteral("%1 (%2)").arg(ptBuildVersion(), ptBuildRevision()));
    return info;
}

#endif // PTBUILDINFO_H
