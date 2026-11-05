#include "ptprofile.h"
#include "dashboard.h"

#include <QDebug>
#include <QFile>
#include <QQuickWindow>
#include <QTimer>
#include <QtGlobal>
#include <QDir>
#include <QFileInfo>
#include <QVariantMap>
#include <algorithm>

#ifdef Q_OS_LINUX
#include <unistd.h>
#endif

std::atomic<bool> PtProfile::s_enabled(false);

bool PtProfile::parseEnabled(const QByteArray &value)
{
    const QByteArray v = value.trimmed().toLower();
    return v == "1" || v == "true" || v == "yes" || v == "on";
}

PtProfile *PtProfile::instance()
{
    static PtProfile *profile = new PtProfile();
    return profile;
}

PtProfile::PtProfile(QObject *parent)
    : QObject(parent)
{
    s_enabled.store(parseEnabled(qgetenv("PT_PROFILE")), std::memory_order_relaxed);
    const bool both = parseEnabled(qgetenv("PT_PROFILE_DISABLE_BOTH"));
    m_disableNeedletrail = both || parseEnabled(qgetenv("PT_PROFILE_DISABLE_NEEDLETRAIL"));
    m_disableDynamicTickColors = both || parseEnabled(qgetenv("PT_PROFILE_DISABLE_DYNAMIC_TICK_COLORS"));
    if (m_disableNeedletrail || m_disableDynamicTickColors)
        qWarning().noquote()
            << QStringLiteral("WARN PowerTune diagnostic switches active: disable_needletrail=%1 disable_dynamic_tick_colors=%2 (not for production)")
                   .arg(m_disableNeedletrail).arg(m_disableDynamicTickColors);
    bool ok = false;
    const int interval = qEnvironmentVariableIntValue("PT_PROFILE_INTERVAL_MS", &ok);
    if (ok && interval >= 1000 && interval <= 60000)
        m_intervalMs = interval;
}

void PtProfile::bump(const QString &name, quint64 events, quint64 microseconds)
{
    QMutexLocker locker(&m_mutex);
    Sample &sample = m_samples[name];
    sample.events += events;
    sample.microseconds += microseconds;
}

void PtProfile::count(const QString &name)
{
    if (!enabled())
        return;
    bump(name, 1, 0);
}

void PtProfile::addTimeUs(const QString &name, qint64 microseconds)
{
    if (!enabled())
        return;
    bump(name, 1, microseconds > 0 ? quint64(microseconds) : 0);
}

bool PtProfile::countTrue(const QString &name)
{
    if (enabled())
        bump(name, 1, 0);
    return true;
}

qint64 PtProfile::nowUs() const
{
    return enabled() ? m_clock.nsecsElapsed() / 1000 : 0;
}

void PtProfile::attach(QQuickWindow *window, DashBoard *dashboard)
{
    if (!enabled())
        return;

    m_dashboard = dashboard;
    m_clock.start();
    m_lastReportMs = 0;

    if (window) {
        // Render-thread signals are connected directly; count() is mutex protected.
        connect(window, &QQuickWindow::beforeSynchronizing, this,
                [this]() { count(QStringLiteral("frame.sync")); }, Qt::DirectConnection);
        connect(window, &QQuickWindow::beforeRendering, this,
                [this]() { count(QStringLiteral("frame.render")); }, Qt::DirectConnection);
        connect(window, &QQuickWindow::frameSwapped, this,
                [this]() { count(QStringLiteral("frame.swapped")); }, Qt::DirectConnection);
    }

    m_timer = new QTimer(this);
    m_timer->setInterval(m_intervalMs);
    connect(m_timer, &QTimer::timeout, this, &PtProfile::report);
    m_timer->start();

    qInfo().noquote()
        << QStringLiteral("INFO PowerTune profile: enabled interval_ms=%1 window=%2")
               .arg(m_intervalMs).arg(window ? QStringLiteral("yes") : QStringLiteral("no"));
}

void PtProfile::reportFanOut()
{
    m_fanOutReported = true;
    if (!m_dashboard)
        return;

    const QVariantMap fanOut = m_dashboard->profileFanOut(
        QStringList() << QStringLiteral("rpm") << QStringLiteral("speed")
                      << QStringLiteral("Watertemp") << QStringLiteral("TPS")
                      << QStringLiteral("MAP"));
    QStringList parts;
    for (auto it = fanOut.constBegin(); it != fanOut.constEnd(); ++it)
        parts << QStringLiteral("%1=%2").arg(it.key(), it.value().toString());
    qInfo().noquote()
        << QStringLiteral("INFO PowerTune profile fanout (signal receivers incl. QML): %1")
               .arg(parts.join(QLatin1Char(' ')));
}

void PtProfile::report()
{
    const qint64 nowMs = m_clock.elapsed();
    const qint64 intervalMs = qMax<qint64>(1, nowMs - m_lastReportMs);
    m_lastReportMs = nowMs;

    if (!m_fanOutReported)
        reportFanOut();

    QHash<QString, Sample> snapshot;
    {
        QMutexLocker locker(&m_mutex);
        snapshot = m_samples;
    }

    QStringList names = snapshot.keys();
    std::sort(names.begin(), names.end());
    QStringList parts;
    for (const QString &name : names) {
        const Sample current = snapshot.value(name);
        const Sample last = m_lastReported.value(name);
        const quint64 events = current.events - last.events;
        if (events == 0)
            continue;
        const quint64 micros = current.microseconds - last.microseconds;
        if (micros > 0)
            parts << QStringLiteral("%1=%2(avg_us=%3)").arg(name).arg(events).arg(micros / events);
        else
            parts << QStringLiteral("%1=%2").arg(name).arg(events);
    }
    m_lastReported = snapshot;

    QString threads;
#ifdef Q_OS_LINUX
    const double ticksPerSecond = double(sysconf(_SC_CLK_TCK));
    QHash<QString, double> byName;
    double total = 0;
    const QFileInfoList tasks = QDir(QStringLiteral("/proc/self/task"))
                                    .entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QFileInfo &task : tasks) {
        QFile stat(task.absoluteFilePath() + QStringLiteral("/stat"));
        if (!stat.open(QIODevice::ReadOnly))
            continue;
        const QByteArray line = stat.readAll();
        const int open = line.indexOf('(');
        const int close = line.lastIndexOf(')');
        if (open < 0 || close < open)
            continue;
        const QString comm = QString::fromLatin1(line.mid(open + 1, close - open - 1));
        const QList<QByteArray> fields = line.mid(close + 2).split(' ');
        if (fields.size() < 13)
            continue;
        const quint64 ticks = fields.at(11).toULongLong() + fields.at(12).toULongLong();
        const QString key = task.fileName();
        const quint64 last = m_lastThreadTicks.value(key, ticks);
        m_lastThreadTicks.insert(key, ticks);
        const double pct = ticksPerSecond > 0
            ? double(ticks - last) / ticksPerSecond / (double(intervalMs) / 1000.0) * 100.0
            : 0.0;
        byName[comm] += pct;
        total += pct;
    }
    QStringList names2 = byName.keys();
    std::sort(names2.begin(), names2.end(), [&byName](const QString &a, const QString &b) {
        return byName.value(a) > byName.value(b);
    });
    QStringList threadParts;
    for (const QString &name : names2) {
        if (byName.value(name) >= 0.05)
            threadParts << QStringLiteral("%1=%2").arg(name).arg(byName.value(name), 0, 'f', 1);
    }
    threads = QStringLiteral(" process_cpu_pct=%1 threads_cpu_pct=\"%2\"")
                  .arg(total, 0, 'f', 1).arg(threadParts.join(QLatin1Char(',')));
#endif

    qInfo().noquote()
        << QStringLiteral("INFO PowerTune profile: interval_ms=%1%2").arg(intervalMs).arg(threads);
    qInfo().noquote()
        << QStringLiteral("INFO PowerTune profile counters: %1").arg(parts.join(QLatin1Char(' ')));
}
