#ifndef NETWORKMANAGERCLIENT_H
#define NETWORKMANAGERCLIENT_H

#include <QDBusConnection>
#include <QDBusArgument>
#include <QDBusObjectPath>
#include <QHash>
#include <QMap>
#include <QMetaType>
#include <QObject>
#include <QVariantMap>
#include <QStringList>
#include <QVariantList>

class QDBusMessage;
class QTimer;

typedef QMap<QString, QVariantMap> NetworkConnectionSettings;
Q_DECLARE_METATYPE(NetworkConnectionSettings)

QDBusArgument &operator<<(QDBusArgument &argument,
                          const NetworkConnectionSettings &settings);
const QDBusArgument &operator>>(const QDBusArgument &argument,
                                NetworkConnectionSettings &settings);

class NetworkManagerSignalRelay : public QObject
{
    Q_OBJECT

public:
    NetworkManagerSignalRelay(const QString &path, const QString &interface,
                              QObject *parent = Q_NULLPTR);
    QString path() const;

signals:
    void changed();
    void wirelessScanResultsChanged();
    void deviceStateChanged(uint state, uint oldState, uint reason);
    void activeConnectionStateChanged(uint state, uint reason);

public slots:
    void propertiesChanged(const QString &interface, const QVariantMap &changed,
                           const QStringList &invalidated);
    void notifyDeviceStateChanged(uint state, uint oldState, uint reason);
    void notifyActiveConnectionStateChanged(uint state, uint reason);

private:
    QString m_path;
    QString m_interface;
};

class NetworkManagerClient : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool managerAvailable READ managerAvailable NOTIFY managerAvailableChanged)
    Q_PROPERTY(bool wifiAvailable READ wifiAvailable NOTIFY wifiStateChanged)
    Q_PROPERTY(bool wifiRadioEnabled READ wifiRadioEnabled NOTIFY wifiStateChanged)
    Q_PROPERTY(QString wifiDeviceName READ wifiDeviceName NOTIFY wifiStateChanged)
    Q_PROPERTY(QString wifiState READ wifiState NOTIFY wifiStateChanged)
    Q_PROPERTY(QString wifiStateText READ wifiStateText NOTIFY wifiStateChanged)
    Q_PROPERTY(QString wifiCurrentSsid READ wifiCurrentSsid NOTIFY wifiStateChanged)
    Q_PROPERTY(QStringList wifiIpv4Addresses READ wifiIpv4Addresses NOTIFY wifiStateChanged)
    Q_PROPERTY(QStringList wifiIpv6Addresses READ wifiIpv6Addresses NOTIFY wifiStateChanged)
    Q_PROPERTY(bool wifiScanning READ wifiScanning NOTIFY wifiStateChanged)
    Q_PROPERTY(bool wifiConnecting READ wifiConnecting NOTIFY wifiStateChanged)
    Q_PROPERTY(QString wifiError READ wifiError NOTIFY wifiStateChanged)
    Q_PROPERTY(QVariantList accessPoints READ accessPoints NOTIFY accessPointsChanged)
    Q_PROPERTY(bool ethernetAvailable READ ethernetAvailable NOTIFY ethernetStateChanged)
    Q_PROPERTY(bool ethernetConnected READ ethernetConnected NOTIFY ethernetStateChanged)
    Q_PROPERTY(bool ethernetCarrier READ ethernetCarrier NOTIFY ethernetStateChanged)
    Q_PROPERTY(QString ethernetDeviceName READ ethernetDeviceName NOTIFY ethernetStateChanged)
    Q_PROPERTY(QString ethernetState READ ethernetState NOTIFY ethernetStateChanged)
    Q_PROPERTY(QString ethernetConnectionName READ ethernetConnectionName NOTIFY ethernetStateChanged)
    Q_PROPERTY(QStringList ethernetIpv4Addresses READ ethernetIpv4Addresses NOTIFY ethernetStateChanged)
    Q_PROPERTY(QStringList ethernetIpv6Addresses READ ethernetIpv6Addresses NOTIFY ethernetStateChanged)

public:
    explicit NetworkManagerClient(QObject *parent = Q_NULLPTR);

    bool managerAvailable() const;
    bool wifiAvailable() const;
    bool wifiRadioEnabled() const;
    QString wifiDeviceName() const;
    QString wifiState() const;
    QString wifiStateText() const;
    QString wifiCurrentSsid() const;
    QStringList wifiIpv4Addresses() const;
    QStringList wifiIpv6Addresses() const;
    bool wifiScanning() const;
    bool wifiConnecting() const;
    QString wifiError() const;
    QVariantList accessPoints() const;
    bool ethernetAvailable() const;
    bool ethernetConnected() const;
    bool ethernetCarrier() const;
    QString ethernetDeviceName() const;
    QString ethernetState() const;
    QString ethernetConnectionName() const;
    QStringList ethernetIpv4Addresses() const;
    QStringList ethernetIpv6Addresses() const;

    Q_INVOKABLE void refresh();
    Q_INVOKABLE void scanWifi();
    Q_INVOKABLE void connectToWifi(const QString &ssid, const QString &password,
                                   const QString &keyManagement);
    Q_INVOKABLE void disconnectWifi();
    Q_INVOKABLE void cancelConnectionAttempt();

signals:
    void managerAvailableChanged();
    void wifiStateChanged();
    void accessPointsChanged();
    void ethernetStateChanged();
    void connectionAttemptFinished(bool success);

private slots:
    void onNameOwnerChanged(const QString &name, const QString &oldOwner,
                            const QString &newOwner);
    void onDeviceAdded(const QDBusObjectPath &path);
    void onDeviceRemoved(const QDBusObjectPath &path);
    void onRelayChanged();
    void onDeviceStateChanged(uint state, uint oldState, uint reason);
    void onActiveConnectionStateChanged(uint state, uint reason);

private:
    struct Device {
        QString path;
        QString interfaceName;
        uint type;
        uint state;
        bool managed;
        bool carrier;
        qint64 lastScan;
        QString activeConnectionPath;
        QString activeAccessPointPath;
        QString ip4ConfigPath;
        QString ip6ConfigPath;
        QStringList accessPointPaths;
        QString connectionName;
        QString currentSsid;
        QStringList ipv4;
        QStringList ipv6;

        Device();
    };

    void initializeManager();
    void setManagerAvailable(bool available);
    void clearDiscoveredState();
    void scheduleRefresh();
    void refreshDevices();
    void loadDeviceProperties(const QString &path, int generation);
    void loadDeviceTypeProperties(const QString &path, uint type, int generation);
    void finishDeviceRefresh(int generation);
    void selectDevices();
    void updateSelectedDeviceDetails(Device *device, bool wifi);
    void loadAccessPoints(const Device &device, int generation);
    void loadAccessPoint(const QString &path, int generation,
                         const QString &currentAccessPointPath);
    void loadIpConfiguration(const QString &path, bool ipv6, int generation,
                             const QString &devicePath);
    void loadActiveConnection(const QString &path, int generation,
                              const QString &devicePath);
    void addRelay(const QString &path, const QString &interface,
                  const QString &signalName = QString());
    void publishWifiStateIfChanged();
    void publishEthernetStateIfChanged();
    void publishAccessPointsIfChanged();
    void setWifiError(const QString &error);
    void finishConnectionAttempt(bool success, const QString &error = QString());
    void activateSavedConnection(const QString &connectionPath,
                                 const NetworkConnectionSettings &profileSettings);
    void addAndActivateConnection();
    void activateConnection(const QString &connectionPath);
    void deactivateConnection(const QString &activePath);
    void handleActivationState(uint state, uint reason);
    void finalizeAttemptProfile(bool success);
    void deleteConnectionProfile(const QString &path);
    void restoreConnectionProfile(const QString &path,
                                  const NetworkConnectionSettings &settings);
    QString safeErrorText(const QString &errorName) const;
    void clearTransientCredentials();

    QDBusConnection m_bus;
    QTimer *m_refreshTimer;
    QTimer *m_scanTimeout;
    QHash<QString, Device> m_devices;
    QHash<QString, NetworkManagerSignalRelay *> m_relays;
    QVariantList m_accessPoints;
    QVariantList m_publishedAccessPoints;
    QVariantMap m_publishedWifiState;
    QVariantMap m_publishedEthernetState;
    QString m_wifiDevicePath;
    QString m_ethernetDevicePath;
    QString m_wifiState;
    QString m_ethernetState;
    QString m_wifiError;
    QString m_ethernetConnectionName;
    QString m_wifiCurrentSsid;
    QStringList m_wifiIpv4;
    QStringList m_wifiIpv6;
    QStringList m_ethernetIpv4;
    QStringList m_ethernetIpv6;
    QString m_pendingSsid;
    QString m_pendingPassword;
    QString m_pendingKeyManagement;
    QString m_activeAttemptPath;
    QString m_attemptProfilePath;
    NetworkConnectionSettings m_originalAttemptProfileSettings;
    NetworkConnectionSettings m_createdAttemptProfileSettings;
    bool m_managerAvailable;
    bool m_wifiRadioEnabled;
    bool m_wifiScanning;
    bool m_wifiConnecting;
    bool m_capabilityDiagnosticsEmitted;
    int m_refreshGeneration;
    int m_connectionGeneration;
    int m_pendingDeviceLoads;
    int m_pendingProfileChecks;
    qint64 m_scanTimestampAtStart;
    bool m_matchingProfileFound;
    bool m_attemptProfileCreated;
    bool m_attemptProfileUpdated;
    bool m_profilePersistencePending;
};

#endif // NETWORKMANAGERCLIENT_H
