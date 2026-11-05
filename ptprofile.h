#ifndef PTPROFILE_H
#define PTPROFILE_H

#include <QHash>
#include <QMutex>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QElapsedTimer>
#include <atomic>

class QQuickWindow;
class QTimer;
class DashBoard;

// Opt-in diagnostic counters for value-update profiling. Disabled unless the
// process is started with PT_PROFILE=1; while disabled every probe is a single
// relaxed atomic load and the object never creates a timer. The probes only
// count and time; they never change what is displayed or published.
//
//   PT_PROFILE=1                     enable
//   PT_PROFILE_INTERVAL_MS=5000      report interval (1000..60000)
class PtProfile : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool enabled READ isEnabled CONSTANT)

public:
    static PtProfile *instance();
    static bool enabled() { return s_enabled.load(std::memory_order_relaxed); }

    bool isEnabled() const { return enabled(); }

    // Observe window frame signals and report the Dashboard signal fan-out.
    void attach(QQuickWindow *window, DashBoard *dashboard);

    Q_INVOKABLE void count(const QString &name);
    Q_INVOKABLE void addTimeUs(const QString &name, qint64 microseconds);
    Q_INVOKABLE qint64 nowUs() const;

    // Parses a PT_PROFILE value; exposed for static verification.
    static bool parseEnabled(const QByteArray &value);

private:
    explicit PtProfile(QObject *parent = nullptr);
    void report();
    void reportFanOut();
    void bump(const QString &name, quint64 events, quint64 microseconds);

    struct Sample {
        quint64 events = 0;
        quint64 microseconds = 0;
    };

    static std::atomic<bool> s_enabled;
    QMutex m_mutex;
    QHash<QString, Sample> m_samples;
    QHash<QString, Sample> m_lastReported;
    QHash<QString, quint64> m_lastThreadTicks;
    QElapsedTimer m_clock;
    qint64 m_lastReportMs = 0;
    int m_intervalMs = 5000;
    QTimer *m_timer = nullptr;
    DashBoard *m_dashboard = nullptr;
    bool m_fanOutReported = false;
};

#define PT_PROFILE_COUNT(name) \
    do { if (PtProfile::enabled()) PtProfile::instance()->count(QStringLiteral(name)); } while (0)

#endif // PTPROFILE_H
