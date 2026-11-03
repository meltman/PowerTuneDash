#include "networkmanagerclient.h"

#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDBusObjectPath>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusVariant>
#include <QDebug>
#include <QMap>
#include <QTimer>
#include <QUuid>
#include <algorithm>

namespace {
const char NetworkManagerService[] = "org.freedesktop.NetworkManager";
const char NetworkManagerPath[] = "/org/freedesktop/NetworkManager";
const char NetworkManagerInterface[] = "org.freedesktop.NetworkManager";
const char PropertiesInterface[] = "org.freedesktop.DBus.Properties";
const char DeviceInterface[] = "org.freedesktop.NetworkManager.Device";
const char WirelessInterface[] = "org.freedesktop.NetworkManager.Device.Wireless";
const char WiredInterface[] = "org.freedesktop.NetworkManager.Device.Wired";
const char AccessPointInterface[] = "org.freedesktop.NetworkManager.AccessPoint";
const char ActiveConnectionInterface[] = "org.freedesktop.NetworkManager.Connection.Active";
const char Ip4ConfigInterface[] = "org.freedesktop.NetworkManager.IP4Config";
const char Ip6ConfigInterface[] = "org.freedesktop.NetworkManager.IP6Config";
const char SettingsInterface[] = "org.freedesktop.NetworkManager.Settings";
const char SettingsConnectionInterface[] = "org.freedesktop.NetworkManager.Settings.Connection";

QVariant unwrapVariant(QVariant value)
{
    while (value.userType() == qMetaTypeId<QDBusVariant>())
        value = qvariant_cast<QDBusVariant>(value).variant();
    return value;
}

QVariantMap unwrapMap(const QVariant &value)
{
    QVariantMap result;
    const QVariantMap source = unwrapVariant(value).toMap();
    for (QVariantMap::const_iterator it = source.constBegin(); it != source.constEnd(); ++it)
        result.insert(it.key(), unwrapVariant(it.value()));
    return result;
}

QList<QDBusObjectPath> objectPaths(const QVariant &value)
{
    const QVariant unwrapped = unwrapVariant(value);
    if (unwrapped.userType() == qMetaTypeId<QDBusArgument>()) {
        const QDBusArgument argument = qvariant_cast<QDBusArgument>(unwrapped);
        QList<QDBusObjectPath> paths;
        argument.beginArray();
        while (!argument.atEnd()) {
            QDBusObjectPath path;
            argument >> path;
            paths.append(path);
        }
        argument.endArray();
        return paths;
    }
    return unwrapped.value<QList<QDBusObjectPath> >();
}

QString stateText(uint state)
{
    switch (state) {
    case 20: return QStringLiteral("unavailable");
    case 30: return QStringLiteral("disconnected");
    case 40: return QStringLiteral("preparing");
    case 50: return QStringLiteral("configuring");
    case 60: return QStringLiteral("waiting for credentials");
    case 70: return QStringLiteral("configuring IP");
    case 80: return QStringLiteral("checking connection");
    case 90: return QStringLiteral("finishing connection");
    case 100: return QStringLiteral("connected");
    case 110: return QStringLiteral("disconnecting");
    case 120: return QStringLiteral("failed");
    default: return QStringLiteral("unknown");
    }
}

QStringList ipAddresses(const QVariantList &entries)
{
    QStringList addresses;
    for (int i = 0; i < entries.size(); ++i) {
        const QVariantMap entry = unwrapMap(entries.at(i));
        const QString address = entry.value(QStringLiteral("address")).toString();
        if (!address.isEmpty() && !addresses.contains(address))
            addresses.append(address);
    }
    return addresses;
}

QVariantList variantMaps(const QVariant &value)
{
    const QVariant unwrapped = unwrapVariant(value);
    if (unwrapped.userType() != qMetaTypeId<QDBusArgument>())
        return unwrapped.toList();

    const QDBusArgument argument = qvariant_cast<QDBusArgument>(unwrapped);
    QVariantList entries;
    argument.beginArray();
    while (!argument.atEnd()) {
        QVariantMap entry;
        argument >> entry;
        entries.append(entry);
    }
    argument.endArray();
    return entries;
}

QStringList ipAddresses(const QVariant &entries)
{
    const QVariant unwrapped = unwrapVariant(entries);
    if (unwrapped.userType() != qMetaTypeId<QDBusArgument>())
        return ipAddresses(unwrapped.toList());
    return ipAddresses(variantMaps(unwrapped));
}

struct AccessPointSecurity {
    bool protectedNetwork;
    bool supported;
    QString keyManagement;
};

AccessPointSecurity classifyAccessPoint(uint flags, uint wpaFlags, uint rsnFlags)
{
    const uint securityFlags = wpaFlags | rsnFlags;
    const uint keyManagementFlags = securityFlags & ~uint(0xff);
    const bool protectedNetwork = (flags & 0x1) != 0 || keyManagementFlags != 0;
    if (!protectedNetwork)
        return {false, true, QStringLiteral("none")};
    if ((securityFlags & 0x400) != 0)
        return {true, true, QStringLiteral("sae")};
    if ((securityFlags & 0x200) != 0)
        return {true, true, QStringLiteral("wpa-psk")};
    return {true, false, QStringLiteral("unsupported")};
}

bool isP2pDevice(const QString &name)
{
    return name.startsWith(QStringLiteral("p2p-dev-"));
}

}

QDBusArgument &operator<<(QDBusArgument &argument,
                          const NetworkConnectionSettings &settings)
{
    argument.beginMap(qMetaTypeId<QString>(), qMetaTypeId<QVariantMap>());
    for (NetworkConnectionSettings::const_iterator it = settings.constBegin();
         it != settings.constEnd(); ++it) {
        argument.beginMapEntry();
        argument << it.key() << it.value();
        argument.endMapEntry();
    }
    argument.endMap();
    return argument;
}

const QDBusArgument &operator>>(const QDBusArgument &argument,
                                NetworkConnectionSettings &settings)
{
    settings.clear();
    argument.beginMap();
    while (!argument.atEnd()) {
        QString key;
        QVariantMap value;
        argument.beginMapEntry();
        argument >> key >> value;
        argument.endMapEntry();
        settings.insert(key, value);
    }
    argument.endMap();
    return argument;
}

NetworkManagerSignalRelay::NetworkManagerSignalRelay(const QString &path,
                                                     const QString &interface,
                                                     QObject *parent)
    : QObject(parent), m_path(path), m_interface(interface)
{
}

QString NetworkManagerSignalRelay::path() const { return m_path; }

void NetworkManagerSignalRelay::propertiesChanged(const QString &interface,
                                                   const QVariantMap &changed,
                                                   const QStringList &invalidated)
{
    if (interface != m_interface)
        return;
    if (m_interface == QString::fromLatin1(WirelessInterface) &&
        (changed.contains(QStringLiteral("LastScan")) ||
         changed.contains(QStringLiteral("AccessPoints")) ||
         invalidated.contains(QStringLiteral("LastScan")) ||
         invalidated.contains(QStringLiteral("AccessPoints")))) {
        emit wirelessScanResultsChanged();
    }
    emit this->changed();
}

void NetworkManagerSignalRelay::notifyDeviceStateChanged(uint state, uint oldState, uint reason)
{
    emit deviceStateChanged(state, oldState, reason);
}

void NetworkManagerSignalRelay::notifyActiveConnectionStateChanged(uint state, uint reason)
{
    emit activeConnectionStateChanged(state, reason);
}

NetworkManagerClient::Device::Device()
    : type(0), state(0), managed(false), carrier(false), lastScan(-1)
{
}

NetworkManagerClient::NetworkManagerClient(QObject *parent)
    : QObject(parent),
      m_bus(QDBusConnection::systemBus()),
      m_refreshTimer(new QTimer(this)),
      m_scanTimeout(new QTimer(this)),
      m_managerAvailable(false),
      m_wifiRadioEnabled(false),
      m_wifiScanning(false),
      m_wifiConnecting(false),
      m_capabilityDiagnosticsEmitted(false),
      m_refreshGeneration(0),
      m_connectionGeneration(0),
      m_pendingDeviceLoads(0),
      m_pendingProfileChecks(0),
      m_scanTimestampAtStart(-1),
      m_matchingProfileFound(false),
      m_attemptProfileCreated(false),
      m_attemptProfileUpdated(false),
      m_profilePersistencePending(false)
{
    qDBusRegisterMetaType<NetworkConnectionSettings>();
    m_refreshTimer->setSingleShot(true);
    m_refreshTimer->setInterval(100);
    m_scanTimeout->setSingleShot(true);
    m_scanTimeout->setInterval(15000);
    connect(m_refreshTimer, &QTimer::timeout, this, &NetworkManagerClient::refreshDevices);
    connect(m_scanTimeout, &QTimer::timeout, this, [this]() {
        if (m_wifiScanning) {
            m_wifiScanning = false;
            setWifiError(QStringLiteral("Wi-Fi scan timed out."));
            publishWifiStateIfChanged();
        }
    });

    if (!m_bus.isConnected()) {
        setWifiError(QStringLiteral("System D-Bus is unavailable."));
        return;
    }

    m_bus.connect(QString(), QStringLiteral("/org/freedesktop/DBus"),
                  QStringLiteral("org.freedesktop.DBus"), QStringLiteral("NameOwnerChanged"),
                  this, SLOT(onNameOwnerChanged(QString,QString,QString)));
    m_bus.connect(NetworkManagerService, NetworkManagerPath, NetworkManagerInterface,
                  QStringLiteral("DeviceAdded"), this, SLOT(onDeviceAdded(QDBusObjectPath)));
    m_bus.connect(NetworkManagerService, NetworkManagerPath, NetworkManagerInterface,
                  QStringLiteral("DeviceRemoved"), this, SLOT(onDeviceRemoved(QDBusObjectPath)));
    initializeManager();
}

bool NetworkManagerClient::managerAvailable() const { return m_managerAvailable; }
bool NetworkManagerClient::wifiAvailable() const { return !m_wifiDevicePath.isEmpty(); }
bool NetworkManagerClient::wifiRadioEnabled() const { return m_wifiRadioEnabled; }
QString NetworkManagerClient::wifiDeviceName() const { return m_devices.value(m_wifiDevicePath).interfaceName; }
QString NetworkManagerClient::wifiState() const { return m_wifiState; }
QString NetworkManagerClient::wifiStateText() const { return m_wifiState; }
QString NetworkManagerClient::wifiCurrentSsid() const { return m_wifiCurrentSsid; }
QStringList NetworkManagerClient::wifiIpv4Addresses() const { return m_wifiIpv4; }
QStringList NetworkManagerClient::wifiIpv6Addresses() const { return m_wifiIpv6; }
bool NetworkManagerClient::wifiScanning() const { return m_wifiScanning; }
bool NetworkManagerClient::wifiConnecting() const { return m_wifiConnecting; }
QString NetworkManagerClient::wifiError() const { return m_wifiError; }
QVariantList NetworkManagerClient::accessPoints() const { return m_accessPoints; }
bool NetworkManagerClient::ethernetAvailable() const { return !m_ethernetDevicePath.isEmpty(); }
bool NetworkManagerClient::ethernetConnected() const
{
    return ethernetAvailable() && m_devices.value(m_ethernetDevicePath).state == 100;
}
bool NetworkManagerClient::ethernetCarrier() const
{
    return ethernetAvailable() && m_devices.value(m_ethernetDevicePath).state != 20 &&
           m_devices.value(m_ethernetDevicePath).carrier;
}
QString NetworkManagerClient::ethernetDeviceName() const { return m_devices.value(m_ethernetDevicePath).interfaceName; }
QString NetworkManagerClient::ethernetState() const { return m_ethernetState; }
QString NetworkManagerClient::ethernetConnectionName() const { return m_ethernetConnectionName; }
QStringList NetworkManagerClient::ethernetIpv4Addresses() const { return m_ethernetIpv4; }
QStringList NetworkManagerClient::ethernetIpv6Addresses() const { return m_ethernetIpv6; }

void NetworkManagerClient::initializeManager()
{
    if (!m_bus.isConnected()) {
        setManagerAvailable(false);
        setWifiError(QStringLiteral("System D-Bus is unavailable."));
        return;
    }

    addRelay(QString::fromLatin1(NetworkManagerPath),
             QString::fromLatin1(NetworkManagerInterface));
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("GetDevices"));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QList<QDBusObjectPath> > reply = *finished;
        finished->deleteLater();
        if (reply.isError()) {
            setManagerAvailable(false);
            clearDiscoveredState();
            setWifiError(QStringLiteral("NetworkManager is unavailable."));
            return;
        }
        setManagerAvailable(true);
        setWifiError(QString());
        refreshDevices();
    });
}

void NetworkManagerClient::setManagerAvailable(bool available)
{
    if (m_managerAvailable == available)
        return;
    m_managerAvailable = available;
    emit managerAvailableChanged();
}

void NetworkManagerClient::clearDiscoveredState()
{
    const bool attemptWasActive = m_wifiConnecting;
    ++m_connectionGeneration;
    clearTransientCredentials();
    m_wifiScanning = false;
    m_wifiConnecting = false;
    m_activeAttemptPath.clear();
    m_attemptProfilePath.clear();
    m_originalAttemptProfileSettings.clear();
    m_createdAttemptProfileSettings.clear();
    m_attemptProfileCreated = false;
    m_attemptProfileUpdated = false;
    m_profilePersistencePending = false;
    m_scanTimeout->stop();
    m_devices.clear();
    m_wifiDevicePath.clear();
    m_ethernetDevicePath.clear();
    m_wifiRadioEnabled = false;
    m_wifiState = QStringLiteral("unavailable");
    m_ethernetState = QStringLiteral("unavailable");
    m_wifiCurrentSsid.clear();
    m_ethernetConnectionName.clear();
    m_wifiIpv4.clear();
    m_wifiIpv6.clear();
    m_ethernetIpv4.clear();
    m_ethernetIpv6.clear();
    m_accessPoints.clear();
    publishWifiStateIfChanged();
    publishEthernetStateIfChanged();
    publishAccessPointsIfChanged();
    if (attemptWasActive)
        emit connectionAttemptFinished(false);
}

void NetworkManagerClient::refresh()
{
    if (m_managerAvailable)
        scheduleRefresh();
    else
        initializeManager();
}

void NetworkManagerClient::scheduleRefresh()
{
    if (m_managerAvailable)
        m_refreshTimer->start();
}

void NetworkManagerClient::refreshDevices()
{
    if (!m_managerAvailable)
        return;

    const int generation = ++m_refreshGeneration;
    m_devices.clear();
    m_wifiDevicePath.clear();
    m_ethernetDevicePath.clear();

    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("GetDevices"));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QList<QDBusObjectPath> > reply = *finished;
        finished->deleteLater();
        if (generation != m_refreshGeneration)
            return;
        if (reply.isError()) {
            setManagerAvailable(false);
            clearDiscoveredState();
            setWifiError(QStringLiteral("Could not discover NetworkManager devices."));
            return;
        }

        const QList<QDBusObjectPath> paths = reply.value();
        if (paths.isEmpty()) {
            finishDeviceRefresh(generation);
            return;
        }
        m_pendingDeviceLoads = paths.size();
        for (int i = 0; i < paths.size(); ++i)
            loadDeviceProperties(paths.at(i).path(), generation);
    });

    QDBusMessage properties = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    properties << QString::fromLatin1(NetworkManagerInterface);
    QDBusPendingCallWatcher *propertiesWatcher =
        new QDBusPendingCallWatcher(m_bus.asyncCall(properties), this);
    connect(propertiesWatcher, &QDBusPendingCallWatcher::finished, this,
            [this](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (reply.isError())
            return;
        const QVariantMap managerProperties = reply.value();
        const bool enabled = unwrapVariant(managerProperties.value(QStringLiteral("WirelessEnabled"))).toBool();
        const bool hardware = unwrapVariant(managerProperties.value(QStringLiteral("WirelessHardwareEnabled"))).toBool();
        if (m_wifiRadioEnabled != (enabled && hardware)) {
            m_wifiRadioEnabled = enabled && hardware;
            publishWifiStateIfChanged();
        }
    });
}

void NetworkManagerClient::loadDeviceProperties(const QString &path, int generation)
{
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << QString::fromLatin1(DeviceInterface);
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, path, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (generation != m_refreshGeneration)
            return;
        if (reply.isError()) {
            if (--m_pendingDeviceLoads == 0)
                finishDeviceRefresh(generation);
            return;
        }
        const QVariantMap properties = reply.value();
        Device device;
        device.path = path;
        device.type = unwrapVariant(properties.value(QStringLiteral("DeviceType"))).toUInt();
        device.state = unwrapVariant(properties.value(QStringLiteral("State"))).toUInt();
        device.managed = unwrapVariant(properties.value(QStringLiteral("Managed"))).toBool();
        device.interfaceName = unwrapVariant(properties.value(QStringLiteral("Interface"))).toString();
        device.activeConnectionPath =
            unwrapVariant(properties.value(QStringLiteral("ActiveConnection"))).value<QDBusObjectPath>().path();
        m_devices.insert(path, device);
        addRelay(path, QString::fromLatin1(DeviceInterface), QStringLiteral("StateChanged"));
        loadDeviceTypeProperties(path, device.type, generation);
    });
}

void NetworkManagerClient::loadDeviceTypeProperties(const QString &path, uint type, int generation)
{
    QString interface;
    if (type == 2 && !isP2pDevice(m_devices.value(path).interfaceName))
        interface = QString::fromLatin1(WirelessInterface);
    else if (type == 1)
        interface = QString::fromLatin1(WiredInterface);
    else {
        if (--m_pendingDeviceLoads == 0)
            finishDeviceRefresh(generation);
        return;
    }

    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << interface;
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, path, interface, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (generation != m_refreshGeneration)
            return;
        if (!reply.isError()) {
            Device device = m_devices.value(path);
            const QVariantMap properties = reply.value();
            if (interface == QString::fromLatin1(WirelessInterface)) {
                device.activeAccessPointPath =
                    unwrapVariant(properties.value(QStringLiteral("ActiveAccessPoint"))).value<QDBusObjectPath>().path();
                device.lastScan =
                    unwrapVariant(properties.value(QStringLiteral("LastScan"))).toLongLong();
                const QList<QDBusObjectPath> accessPoints =
                    objectPaths(properties.value(QStringLiteral("AccessPoints")));
                for (int i = 0; i < accessPoints.size(); ++i)
                    device.accessPointPaths.append(accessPoints.at(i).path());
                addRelay(path, interface);
            } else {
                device.carrier = unwrapVariant(properties.value(QStringLiteral("Carrier"))).toBool();
                addRelay(path, interface);
            }
            m_devices.insert(path, device);
        }
        if (--m_pendingDeviceLoads == 0)
            finishDeviceRefresh(generation);
    });
}

void NetworkManagerClient::finishDeviceRefresh(int generation)
{
    if (generation != m_refreshGeneration)
        return;
    selectDevices();
    updateSelectedDeviceDetails(m_devices.contains(m_wifiDevicePath) ? &m_devices[m_wifiDevicePath] : Q_NULLPTR, true);
    updateSelectedDeviceDetails(m_devices.contains(m_ethernetDevicePath) ? &m_devices[m_ethernetDevicePath] : Q_NULLPTR, false);

    if (!m_capabilityDiagnosticsEmitted) {
        if (wifiAvailable())
            qInfo().noquote() << QStringLiteral("Wi-Fi interface found: device=\"%1\", state=\"%2\"")
                                 .arg(wifiDeviceName(), stateText(m_devices.value(m_wifiDevicePath).state));
        else
            qInfo() << "Wi-Fi unavailable; wireless configuration disabled";
        if (ethernetAvailable())
            qInfo().noquote() << QStringLiteral("Ethernet interface found: device=\"%1\", state=\"%2\"")
                                 .arg(ethernetDeviceName(), stateText(m_devices.value(m_ethernetDevicePath).state));
        else
            qInfo() << "Ethernet unavailable";
        m_capabilityDiagnosticsEmitted = true;
    }

    if (!m_wifiDevicePath.isEmpty()) {
        loadAccessPoints(m_devices.value(m_wifiDevicePath), generation);
    } else if (!m_accessPoints.isEmpty()) {
        m_accessPoints.clear();
        publishAccessPointsIfChanged();
    }
    publishWifiStateIfChanged();
    publishEthernetStateIfChanged();
}

void NetworkManagerClient::selectDevices()
{
    QStringList wifiPaths;
    QStringList ethernetPaths;
    for (QHash<QString, Device>::const_iterator it = m_devices.constBegin(); it != m_devices.constEnd(); ++it) {
        const Device &device = it.value();
        if (!device.managed || device.interfaceName.isEmpty())
            continue;
        if (device.type == 2 && !isP2pDevice(device.interfaceName))
            wifiPaths.append(device.path);
        else if (device.type == 1)
            ethernetPaths.append(device.path);
    }

    std::sort(wifiPaths.begin(), wifiPaths.end(), [this](const QString &left, const QString &right) {
        const Device a = m_devices.value(left);
        const Device b = m_devices.value(right);
        const bool aActive = a.state == 100;
        const bool bActive = b.state == 100;
        if (aActive != bActive)
            return aActive;
        return a.interfaceName.compare(b.interfaceName, Qt::CaseInsensitive) < 0;
    });
    std::sort(ethernetPaths.begin(), ethernetPaths.end(), [this](const QString &left, const QString &right) {
        const Device a = m_devices.value(left);
        const Device b = m_devices.value(right);
        const int aRank = (a.state == 100 ? 2 : 0) + (a.carrier ? 1 : 0);
        const int bRank = (b.state == 100 ? 2 : 0) + (b.carrier ? 1 : 0);
        if (aRank != bRank)
            return aRank > bRank;
        return a.interfaceName.compare(b.interfaceName, Qt::CaseInsensitive) < 0;
    });
    m_wifiDevicePath = wifiPaths.isEmpty() ? QString() : wifiPaths.first();
    m_ethernetDevicePath = ethernetPaths.isEmpty() ? QString() : ethernetPaths.first();
}

void NetworkManagerClient::updateSelectedDeviceDetails(Device *device, bool wifi)
{
    if (wifi) {
        m_wifiState = device ? stateText(device->state) : QStringLiteral("unavailable");
        m_wifiCurrentSsid = device ? device->currentSsid : QString();
        m_wifiIpv4 = device ? device->ipv4 : QStringList();
        m_wifiIpv6 = device ? device->ipv6 : QStringList();
    } else {
        m_ethernetState = device ? (device->carrier ? stateText(device->state) + QStringLiteral(" (link up)")
                                                       : stateText(device->state))
                                 : QStringLiteral("unavailable");
        m_ethernetConnectionName = device ? device->connectionName : QString();
        m_ethernetIpv4 = device ? device->ipv4 : QStringList();
        m_ethernetIpv6 = device ? device->ipv6 : QStringList();
    }

    if (!device)
        return;
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), device->path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << QString::fromLatin1(DeviceInterface);
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    const QString devicePath = device->path;
    const int generation = m_refreshGeneration;
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, devicePath, wifi, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (reply.isError() || generation != m_refreshGeneration || !m_devices.contains(devicePath))
            return;
        Device &current = m_devices[devicePath];
        const QVariantMap properties = reply.value();
        current.ip4ConfigPath =
            unwrapVariant(properties.value(QStringLiteral("Ip4Config"))).value<QDBusObjectPath>().path();
        current.ip6ConfigPath =
            unwrapVariant(properties.value(QStringLiteral("Ip6Config"))).value<QDBusObjectPath>().path();
        current.activeConnectionPath =
            unwrapVariant(properties.value(QStringLiteral("ActiveConnection"))).value<QDBusObjectPath>().path();
        if (wifi) {
            current.activeAccessPointPath =
                unwrapVariant(properties.value(QStringLiteral("ActiveAccessPoint"))).value<QDBusObjectPath>().path();
        }
        addRelay(current.ip4ConfigPath, QString::fromLatin1(Ip4ConfigInterface));
        addRelay(current.ip6ConfigPath, QString::fromLatin1(Ip6ConfigInterface));
        addRelay(current.activeConnectionPath, QString::fromLatin1(ActiveConnectionInterface),
                 QStringLiteral("StateChanged"));
        loadIpConfiguration(current.ip4ConfigPath, false, generation, devicePath);
        loadIpConfiguration(current.ip6ConfigPath, true, generation, devicePath);
        loadActiveConnection(current.activeConnectionPath, generation, devicePath);
        if (wifi && !current.activeAccessPointPath.isEmpty())
            loadAccessPoint(current.activeAccessPointPath, generation, current.activeAccessPointPath);
    });
}

void NetworkManagerClient::loadAccessPoints(const Device &device, int generation)
{
    QVariantList results;
    if (device.accessPointPaths.isEmpty()) {
        m_accessPoints = results;
        publishAccessPointsIfChanged();
        if (m_wifiScanning && device.lastScan > m_scanTimestampAtStart) {
            m_wifiScanning = false;
            m_scanTimeout->stop();
            qDebug() << "Wi-Fi scan completed: 0 unique access points";
            publishWifiStateIfChanged();
        }
        return;
    }

    int *remaining = new int(device.accessPointPaths.size());
    QHash<QString, QVariantMap> *unique = new QHash<QString, QVariantMap>();
    const bool scanCompleted = device.lastScan > m_scanTimestampAtStart;
    for (int i = 0; i < device.accessPointPaths.size(); ++i) {
        const QString path = device.accessPointPaths.at(i);
        QDBusMessage message = QDBusMessage::createMethodCall(
            QString::fromLatin1(NetworkManagerService), path,
            QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
        message << QString::fromLatin1(AccessPointInterface);
        QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
        const QString currentPath = device.activeAccessPointPath;
        connect(watcher, &QDBusPendingCallWatcher::finished, this,
                [this, path, currentPath, generation, remaining, unique,
                 scanCompleted](QDBusPendingCallWatcher *finished) {
            QDBusPendingReply<QVariantMap> reply = *finished;
            finished->deleteLater();
            if (generation == m_refreshGeneration && !reply.isError()) {
                const QVariantMap properties = reply.value();
                const QString ssid = QString::fromUtf8(
                    unwrapVariant(properties.value(QStringLiteral("Ssid"))).toByteArray());
                const bool hidden = ssid.isEmpty();
                const QString key = hidden ? path : ssid;
                if (!unique->contains(key)) {
                const AccessPointSecurity security = classifyAccessPoint(
                    unwrapVariant(properties.value(QStringLiteral("Flags"))).toUInt(),
                    unwrapVariant(properties.value(QStringLiteral("WpaFlags"))).toUInt(),
                    unwrapVariant(properties.value(QStringLiteral("RsnFlags"))).toUInt());
                QVariantMap item;
                item.insert(QStringLiteral("ssid"), ssid);
                QString displayName = hidden
                        ? QStringLiteral("Hidden network (enter SSID)")
                        : ssid;
                if (security.protectedNetwork && !security.supported)
                    displayName += QStringLiteral(" (protected security unsupported)");
                item.insert(QStringLiteral("displayName"), displayName);
                item.insert(QStringLiteral("hidden"), hidden);
                    item.insert(QStringLiteral("signalStrength"),
                                unwrapVariant(properties.value(QStringLiteral("Strength"))).toUInt());
                    item.insert(QStringLiteral("secure"), security.protectedNetwork);
                    item.insert(QStringLiteral("keyManagement"), security.keyManagement);
                    item.insert(QStringLiteral("supported"), security.supported);
                    item.insert(QStringLiteral("path"), path);
                    item.insert(QStringLiteral("current"), path == currentPath);
                    unique->insert(key, item);
                }
            }
            if (--*remaining == 0) {
                QVariantList accessPoints;
                QStringList keys = unique->keys();
                std::sort(keys.begin(), keys.end(), [](const QString &left, const QString &right) {
                    return left.compare(right, Qt::CaseInsensitive) < 0;
                });
                for (int i = 0; i < keys.size(); ++i)
                    accessPoints.append(unique->value(keys.at(i)));
                if (generation == m_refreshGeneration) {
                    m_accessPoints = accessPoints;
                    publishAccessPointsIfChanged();
                    if (m_wifiScanning && scanCompleted) {
                        m_wifiScanning = false;
                        m_scanTimeout->stop();
                        qDebug().noquote() << QStringLiteral("Wi-Fi scan completed: %1 unique access points")
                                              .arg(accessPoints.size());
                        publishWifiStateIfChanged();
                    }
                }
                delete remaining;
                delete unique;
            }
        });
    }
}

void NetworkManagerClient::loadAccessPoint(const QString &path, int generation,
                                           const QString &currentAccessPointPath)
{
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << QString::fromLatin1(AccessPointInterface);
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, path, generation, currentAccessPointPath](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (reply.isError() || generation != m_refreshGeneration || !m_devices.contains(m_wifiDevicePath))
            return;
        const QString ssid = QString::fromUtf8(
            unwrapVariant(reply.value().value(QStringLiteral("Ssid"))).toByteArray());
        Device &wifi = m_devices[m_wifiDevicePath];
        wifi.currentSsid = ssid;
        m_wifiCurrentSsid = ssid;
        for (int i = 0; i < m_accessPoints.size(); ++i) {
            QVariantMap item = m_accessPoints.at(i).toMap();
            item.insert(QStringLiteral("current"), item.value(QStringLiteral("path")).toString() == currentAccessPointPath);
            m_accessPoints[i] = item;
        }
        Q_UNUSED(path)
        publishAccessPointsIfChanged();
        publishWifiStateIfChanged();
    });
}

void NetworkManagerClient::loadIpConfiguration(const QString &path, bool ipv6, int generation,
                                                const QString &devicePath)
{
    if (path.isEmpty() || path == QStringLiteral("/"))
        return;
    const QString interface = ipv6 ? QString::fromLatin1(Ip6ConfigInterface)
                                   : QString::fromLatin1(Ip4ConfigInterface);
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << interface;
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, ipv6, generation, devicePath](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (reply.isError() || generation != m_refreshGeneration || !m_devices.contains(devicePath))
            return;
        const QVariantMap properties = reply.value();
        const QStringList addresses = ipAddresses(properties.value(QStringLiteral("AddressData")));
        Device &device = m_devices[devicePath];
        if (ipv6)
            device.ipv6 = addresses;
        else
            device.ipv4 = addresses;
        if (devicePath == m_wifiDevicePath) {
            m_wifiIpv4 = device.ipv4;
            m_wifiIpv6 = device.ipv6;
            publishWifiStateIfChanged();
        }
        if (devicePath == m_ethernetDevicePath) {
            m_ethernetIpv4 = device.ipv4;
            m_ethernetIpv6 = device.ipv6;
            publishEthernetStateIfChanged();
        }
    });
}

void NetworkManagerClient::loadActiveConnection(const QString &path, int generation,
                                                 const QString &devicePath)
{
    if (path.isEmpty() || path == QStringLiteral("/"))
        return;
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(PropertiesInterface), QStringLiteral("GetAll"));
    message << QString::fromLatin1(ActiveConnectionInterface);
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, path, generation, devicePath](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (reply.isError() || generation != m_refreshGeneration || !m_devices.contains(devicePath))
            return;
        const QString name =
            unwrapVariant(reply.value().value(QStringLiteral("Id"))).toString();
        m_devices[devicePath].connectionName = name;
        const uint state =
            unwrapVariant(reply.value().value(QStringLiteral("State"))).toUInt();
        if (path == m_activeAttemptPath && m_wifiConnecting && state == 2)
            handleActivationState(state, 0);
        if (devicePath == m_ethernetDevicePath) {
            m_ethernetConnectionName = name;
            publishEthernetStateIfChanged();
        }
    });
}

void NetworkManagerClient::addRelay(const QString &path, const QString &interface,
                                    const QString &signalName)
{
    if (path.isEmpty() || path == QStringLiteral("/"))
        return;
    const QString key = path + QLatin1Char('|') + interface;
    if (m_relays.contains(key))
        return;
    NetworkManagerSignalRelay *relay = new NetworkManagerSignalRelay(path, interface, this);
    m_relays.insert(key, relay);
    m_bus.connect(NetworkManagerService, path, QString::fromLatin1(PropertiesInterface),
                  QStringLiteral("PropertiesChanged"), relay,
                  SLOT(propertiesChanged(QString,QVariantMap,QStringList)));
    if (!signalName.isEmpty()) {
        const QString actualInterface = interface == QString::fromLatin1(ActiveConnectionInterface)
                                            ? QString::fromLatin1(ActiveConnectionInterface)
                                            : QString::fromLatin1(DeviceInterface);
        m_bus.connect(NetworkManagerService, path, actualInterface, signalName, relay,
                      actualInterface == QString::fromLatin1(ActiveConnectionInterface)
                          ? SLOT(notifyActiveConnectionStateChanged(uint,uint))
                          : SLOT(notifyDeviceStateChanged(uint,uint,uint)));
    }
    connect(relay, &NetworkManagerSignalRelay::changed, this, &NetworkManagerClient::onRelayChanged);
    connect(relay, &NetworkManagerSignalRelay::wirelessScanResultsChanged,
            this, [this, path]() {
        if (m_wifiScanning) {
            qDebug().noquote() << QStringLiteral("Wi-Fi scan result update detected: device-path=\"%1\"")
                                  .arg(path);
        }
    });
    connect(relay, &NetworkManagerSignalRelay::deviceStateChanged,
            this, &NetworkManagerClient::onDeviceStateChanged);
    connect(relay, &NetworkManagerSignalRelay::activeConnectionStateChanged,
            this, &NetworkManagerClient::onActiveConnectionStateChanged);
}

void NetworkManagerClient::onNameOwnerChanged(const QString &name, const QString &oldOwner,
                                               const QString &newOwner)
{
    Q_UNUSED(oldOwner)
    if (name != QString::fromLatin1(NetworkManagerService))
        return;
    if (newOwner.isEmpty()) {
        setManagerAvailable(false);
        clearDiscoveredState();
        setWifiError(QStringLiteral("NetworkManager is unavailable."));
    } else {
        initializeManager();
    }
}

void NetworkManagerClient::onDeviceAdded(const QDBusObjectPath &path)
{
    Q_UNUSED(path)
    scheduleRefresh();
}

void NetworkManagerClient::onDeviceRemoved(const QDBusObjectPath &path)
{
    Q_UNUSED(path)
    scheduleRefresh();
}

void NetworkManagerClient::scanWifi()
{
    if (!m_managerAvailable) {
        setWifiError(QStringLiteral("NetworkManager is unavailable."));
        return;
    }
    if (m_wifiDevicePath.isEmpty()) {
        setWifiError(QStringLiteral("No Wi-Fi device is available."));
        return;
    }
    if (!m_wifiRadioEnabled) {
        setWifiError(QStringLiteral("Wi-Fi is disabled."));
        return;
    }
    if (m_wifiScanning)
        return;

    setWifiError(QString());
    m_scanTimestampAtStart = m_devices.value(m_wifiDevicePath).lastScan;
    m_wifiScanning = true;
    publishWifiStateIfChanged();
    m_scanTimeout->start();
    qDebug().noquote() << QStringLiteral("Wi-Fi scan requested: device=\"%1\"")
                          .arg(wifiDeviceName());
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), m_wifiDevicePath,
        QString::fromLatin1(WirelessInterface), QStringLiteral("RequestScan"));
    message << QVariantMap();
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<> reply = *finished;
        finished->deleteLater();
        if (reply.isError()) {
            m_wifiScanning = false;
            m_scanTimeout->stop();
            setWifiError(QStringLiteral("NetworkManager could not scan for Wi-Fi networks."));
            publishWifiStateIfChanged();
        } else {
            qDebug() << "NetworkManager accepted Wi-Fi scan request; awaiting wireless property updates";
        }
    });
}

void NetworkManagerClient::connectToWifi(const QString &ssid, const QString &password,
                                         const QString &keyManagement)
{
    if (m_wifiConnecting)
        return;
    if (!m_managerAvailable || m_wifiDevicePath.isEmpty() || !m_wifiRadioEnabled) {
        setWifiError(!m_managerAvailable ? QStringLiteral("NetworkManager is unavailable.")
                                         : QStringLiteral("Wi-Fi is not available."));
        emit connectionAttemptFinished(false);
        return;
    }
    if (ssid.isEmpty()) {
        setWifiError(QStringLiteral("Select a network before connecting."));
        emit connectionAttemptFinished(false);
        return;
    }
    if (keyManagement != QStringLiteral("none") &&
        keyManagement != QStringLiteral("wpa-psk") &&
        keyManagement != QStringLiteral("sae")) {
        setWifiError(QStringLiteral("This Wi-Fi security type is not supported."));
        emit connectionAttemptFinished(false);
        return;
    }

    ++m_connectionGeneration;
    clearTransientCredentials();
    m_pendingSsid = ssid;
    m_pendingPassword = keyManagement == QStringLiteral("none") ? QString() : password;
    m_pendingKeyManagement = keyManagement;
    m_attemptProfilePath.clear();
    m_originalAttemptProfileSettings.clear();
    m_createdAttemptProfileSettings.clear();
    m_attemptProfileCreated = false;
    m_attemptProfileUpdated = false;
    m_profilePersistencePending = false;
    m_wifiConnecting = true;
    m_matchingProfileFound = false;
    m_pendingProfileChecks = 0;
    setWifiError(QString());
    publishWifiStateIfChanged();
    QString logSsid = ssid;
    logSsid.replace(QLatin1Char('"'), QStringLiteral("\\\""));
    logSsid.replace(QLatin1Char('\n'), QLatin1Char(' '));
    logSsid.replace(QLatin1Char('\r'), QLatin1Char(' '));
    qInfo().noquote() << QStringLiteral("Wi-Fi connection requested: ssid=\"%1\"").arg(logSsid);

    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService),
        QStringLiteral("/org/freedesktop/NetworkManager/Settings"),
        QString::fromLatin1(SettingsInterface), QStringLiteral("ListConnections"));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    const int generation = m_connectionGeneration;
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QList<QDBusObjectPath> > reply = *finished;
        finished->deleteLater();
        if (generation != m_connectionGeneration || !m_wifiConnecting)
            return;
        if (reply.isError()) {
            finishConnectionAttempt(false, safeErrorText(reply.error().name()));
            return;
        }
        const QList<QDBusObjectPath> paths = reply.value();
        if (paths.isEmpty()) {
            addAndActivateConnection();
            return;
        }
        m_pendingProfileChecks = paths.size();
        for (int i = 0; i < paths.size(); ++i) {
            QDBusMessage getSettings = QDBusMessage::createMethodCall(
                QString::fromLatin1(NetworkManagerService), paths.at(i).path(),
                QString::fromLatin1(SettingsConnectionInterface), QStringLiteral("GetSettings"));
            QDBusPendingCallWatcher *profileWatcher =
                new QDBusPendingCallWatcher(m_bus.asyncCall(getSettings), this);
            const QString profilePath = paths.at(i).path();
            connect(profileWatcher, &QDBusPendingCallWatcher::finished, this,
                    [this, profilePath, generation](QDBusPendingCallWatcher *profileFinished) {
                        QDBusPendingReply<NetworkConnectionSettings> profileReply = *profileFinished;
                profileFinished->deleteLater();
                if (generation != m_connectionGeneration || !m_wifiConnecting)
                    return;
                if (profileReply.isError()) {
                    finishConnectionAttempt(false, safeErrorText(profileReply.error().name()));
                    return;
                }
                const QVariantMap wireless =
                    profileReply.value().value(QStringLiteral("802-11-wireless"));
                const QString profileSsid = QString::fromUtf8(
                    unwrapVariant(wireless.value(QStringLiteral("ssid"))).toByteArray());
                if (profileSsid == m_pendingSsid && !m_matchingProfileFound) {
                    m_matchingProfileFound = true;
                    activateSavedConnection(profilePath, profileReply.value());
                }
                if (--m_pendingProfileChecks == 0 && !m_matchingProfileFound)
                    addAndActivateConnection();
            });
        }
    });
}

void NetworkManagerClient::activateSavedConnection(const QString &connectionPath,
                                                    const NetworkConnectionSettings &profileSettings)
{
    if (!m_wifiConnecting)
        return;
    m_activeAttemptPath.clear();
    if (m_pendingPassword.isEmpty() || m_pendingKeyManagement.isEmpty() ||
        m_pendingKeyManagement == QStringLiteral("none")) {
        activateConnection(connectionPath);
        return;
    }

    m_attemptProfilePath = connectionPath;
    m_originalAttemptProfileSettings = profileSettings;
    NetworkConnectionSettings settings = profileSettings;
    QVariantMap security = settings.value(QStringLiteral("802-11-wireless-security"));
    security.insert(QStringLiteral("key-mgmt"), m_pendingKeyManagement);
    security.insert(QStringLiteral("psk"), m_pendingPassword);
    settings.insert(QStringLiteral("802-11-wireless-security"), security);
    m_createdAttemptProfileSettings = settings;
    QVariantMap temporaryConnection = settings.value(QStringLiteral("connection"));
    temporaryConnection.insert(QStringLiteral("autoconnect"), false);
    settings.insert(QStringLiteral("connection"), temporaryConnection);

    QDBusMessage update = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), connectionPath,
        QString::fromLatin1(SettingsConnectionInterface), QStringLiteral("Update2"));
    update << QVariant::fromValue(settings) << uint(0x1) << QVariantMap();
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(update), this);
    const int generation = m_connectionGeneration;
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, connectionPath, generation, profileSettings](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        finished->deleteLater();
        if (generation != m_connectionGeneration || !m_wifiConnecting) {
            if (!reply.isError())
                restoreConnectionProfile(connectionPath, profileSettings);
            return;
        }
        if (reply.isError()) {
            finishConnectionAttempt(false, safeErrorText(reply.error().name()));
            return;
        }
        m_attemptProfileUpdated = true;
        activateConnection(connectionPath);
    });
}

void NetworkManagerClient::addAndActivateConnection()
{
    if (!m_wifiConnecting)
        return;
    if (!m_pendingPassword.isEmpty() && m_pendingKeyManagement.isEmpty()) {
        finishConnectionAttempt(false, QStringLiteral("Select a supported Wi-Fi security type."));
        return;
    }
    if (m_pendingPassword.isEmpty() && !m_pendingKeyManagement.isEmpty() &&
        m_pendingKeyManagement != QStringLiteral("none")) {
        finishConnectionAttempt(false, QStringLiteral("Enter the Wi-Fi password."));
        return;
    }
    QVariantMap connection;
    connection.insert(QStringLiteral("id"), QStringLiteral("PowerTune %1").arg(m_pendingSsid));
    connection.insert(QStringLiteral("uuid"), QUuid::createUuid().toString(QUuid::WithoutBraces));
    connection.insert(QStringLiteral("type"), QStringLiteral("802-11-wireless"));
    connection.insert(QStringLiteral("autoconnect"), false);

    QVariantMap wireless;
    wireless.insert(QStringLiteral("ssid"), m_pendingSsid.toUtf8());
    wireless.insert(QStringLiteral("mode"), QStringLiteral("infrastructure"));

    QVariantMap ipv4;
    ipv4.insert(QStringLiteral("method"), QStringLiteral("auto"));
    QVariantMap ipv6;
    ipv6.insert(QStringLiteral("method"), QStringLiteral("auto"));

    NetworkConnectionSettings settings;
    settings.insert(QStringLiteral("connection"), connection);
    settings.insert(QStringLiteral("802-11-wireless"), wireless);
    settings.insert(QStringLiteral("ipv4"), ipv4);
    settings.insert(QStringLiteral("ipv6"), ipv6);

    if (!m_pendingKeyManagement.isEmpty() && m_pendingKeyManagement != QStringLiteral("none")) {
        QVariantMap security;
        security.insert(QStringLiteral("key-mgmt"), m_pendingKeyManagement);
        security.insert(QStringLiteral("psk"), m_pendingPassword);
        settings.insert(QStringLiteral("802-11-wireless-security"), security);
    }

    m_createdAttemptProfileSettings = settings;
    QVariantMap options;
    options.insert(QStringLiteral("persist"), QStringLiteral("disk"));
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("AddAndActivateConnection2"));
    message << QVariant::fromValue(settings)
            << QVariant::fromValue(QDBusObjectPath(m_wifiDevicePath))
            << QVariant::fromValue(QDBusObjectPath(QStringLiteral("/")))
            << QVariant::fromValue(options);

    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    const int generation = m_connectionGeneration;
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QDBusObjectPath, QDBusObjectPath, QVariantMap> reply = *finished;
        finished->deleteLater();
        if (generation != m_connectionGeneration || !m_wifiConnecting)
        {
            if (!reply.isError()) {
                deactivateConnection(reply.argumentAt<1>().path());
                deleteConnectionProfile(reply.argumentAt<0>().path());
            }
            return;
        }
        if (reply.isError()) {
            finishConnectionAttempt(false, safeErrorText(reply.error().name()));
            return;
        }
        m_attemptProfilePath = reply.argumentAt<0>().path();
        m_attemptProfileCreated = true;
        const QString activePath = reply.argumentAt<1>().path();
        m_activeAttemptPath = activePath;
        addRelay(activePath, QString::fromLatin1(ActiveConnectionInterface), QStringLiteral("StateChanged"));
        scheduleRefresh();
    });
}

void NetworkManagerClient::activateConnection(const QString &connectionPath)
{
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("ActivateConnection"));
    message << QVariant::fromValue(QDBusObjectPath(connectionPath))
            << QVariant::fromValue(QDBusObjectPath(m_wifiDevicePath))
            << QVariant::fromValue(QDBusObjectPath(QStringLiteral("/")));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    const int generation = m_connectionGeneration;
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this, generation](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QDBusObjectPath> reply = *finished;
        finished->deleteLater();
        if (generation != m_connectionGeneration || !m_wifiConnecting)
        {
            if (!reply.isError())
                deactivateConnection(reply.value().path());
            return;
        }
        if (reply.isError()) {
            finishConnectionAttempt(false, safeErrorText(reply.error().name()));
            return;
        }
        m_activeAttemptPath = reply.value().path();
        addRelay(m_activeAttemptPath, QString::fromLatin1(ActiveConnectionInterface),
                 QStringLiteral("StateChanged"));
        scheduleRefresh();
    });
}

void NetworkManagerClient::handleActivationState(uint state, uint reason)
{
    if (!m_wifiConnecting)
        return;
    if (state == 2) {
        finishConnectionAttempt(true);
    } else if (state == 4) {
        QString error = QStringLiteral("NetworkManager could not connect to this Wi-Fi network.");
        if (reason == 9 || reason == 10)
            error = QStringLiteral("Wi-Fi authentication failed. Check the password.");
        else if (reason == 5)
            error = QStringLiteral("The network did not provide a usable IP configuration.");
        finishConnectionAttempt(false, error);
    }
}

void NetworkManagerClient::disconnectWifi()
{
    if (m_wifiDevicePath.isEmpty()) {
        setWifiError(QStringLiteral("No Wi-Fi device is available."));
        return;
    }
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("DeactivateConnection"));
    const QString activePath = m_devices.value(m_wifiDevicePath).activeConnectionPath;
    if (activePath.isEmpty() || activePath == QStringLiteral("/")) {
        setWifiError(QStringLiteral("Wi-Fi is not connected."));
        return;
    }
    message << QVariant::fromValue(QDBusObjectPath(activePath));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [this](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<> reply = *finished;
        finished->deleteLater();
        if (reply.isError())
            setWifiError(QStringLiteral("NetworkManager could not disconnect Wi-Fi."));
        else
            setWifiError(QString());
        scheduleRefresh();
    });
}

void NetworkManagerClient::deactivateConnection(const QString &activePath)
{
    if (activePath.isEmpty() || activePath == QStringLiteral("/"))
        return;
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), QString::fromLatin1(NetworkManagerPath),
        QString::fromLatin1(NetworkManagerInterface), QStringLiteral("DeactivateConnection"));
    message << QVariant::fromValue(QDBusObjectPath(activePath));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, watcher, &QObject::deleteLater);
}

void NetworkManagerClient::cancelConnectionAttempt()
{
    if (!m_wifiConnecting)
        return;
    const QString activePath = m_activeAttemptPath;
    ++m_connectionGeneration;
    clearTransientCredentials();
    m_wifiConnecting = false;
    m_activeAttemptPath.clear();
    deactivateConnection(activePath);
    finalizeAttemptProfile(false);
    m_attemptProfilePath.clear();
    m_originalAttemptProfileSettings.clear();
    m_createdAttemptProfileSettings.clear();
    m_attemptProfileCreated = false;
    m_attemptProfileUpdated = false;
    m_profilePersistencePending = false;
    qInfo().noquote() << QStringLiteral("Wi-Fi connection attempt cancelled");
    setWifiError(QStringLiteral("Connection cancelled."));
    publishWifiStateIfChanged();
    emit connectionAttemptFinished(false);
}

void NetworkManagerClient::finishConnectionAttempt(bool success, const QString &error)
{
    if (!m_wifiConnecting)
        return;
    if (success && m_profilePersistencePending)
        return;
    if (success && (m_attemptProfileCreated || m_attemptProfileUpdated) &&
        !m_profilePersistencePending) {
        m_profilePersistencePending = true;
        NetworkConnectionSettings settings = m_createdAttemptProfileSettings;
        if (m_attemptProfileCreated) {
            QVariantMap connection = settings.value(QStringLiteral("connection"));
            connection.insert(QStringLiteral("autoconnect"), true);
            settings.insert(QStringLiteral("connection"), connection);
        }
        QDBusMessage update = QDBusMessage::createMethodCall(
            QString::fromLatin1(NetworkManagerService), m_attemptProfilePath,
            QString::fromLatin1(SettingsConnectionInterface), QStringLiteral("Update2"));
        update << QVariant::fromValue(settings) << uint(0x1) << QVariantMap();
        QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(update), this);
        const int generation = m_connectionGeneration;
        connect(watcher, &QDBusPendingCallWatcher::finished, this,
                [this, generation, settings](QDBusPendingCallWatcher *finished) {
            QDBusPendingReply<QVariantMap> reply = *finished;
            finished->deleteLater();
            if (generation != m_connectionGeneration || !m_wifiConnecting)
                return;
            if (reply.isError())
                qWarning() << "Connected Wi-Fi profile settings could not be finalized";
            else
                m_createdAttemptProfileSettings = settings;
            m_attemptProfileCreated = false;
            m_attemptProfileUpdated = false;
            m_profilePersistencePending = false;
            finishConnectionAttempt(true);
        });
        return;
    }

    const QString completedSsid = m_pendingSsid;
    const QString completedDevice = wifiDeviceName();
    if (!success)
        deactivateConnection(m_activeAttemptPath);
    finalizeAttemptProfile(success);
    clearTransientCredentials();
    m_wifiConnecting = false;
    m_activeAttemptPath.clear();
    m_attemptProfilePath.clear();
    m_originalAttemptProfileSettings.clear();
    m_createdAttemptProfileSettings.clear();
    m_attemptProfileCreated = false;
    m_attemptProfileUpdated = false;
    m_profilePersistencePending = false;
    setWifiError(success ? QString() : error);
    if (success) {
        QString logSsid = completedSsid;
        logSsid.replace(QLatin1Char('"'), QStringLiteral("\\\""));
        logSsid.replace(QLatin1Char('\n'), QLatin1Char(' '));
        logSsid.replace(QLatin1Char('\r'), QLatin1Char(' '));
        qInfo().noquote() << QStringLiteral("Wi-Fi connected: device=\"%1\", ssid=\"%2\"")
                                .arg(completedDevice, logSsid);
    } else if (error == QStringLiteral("Wi-Fi authentication failed. Check the password.")) {
        QString logSsid = completedSsid;
        logSsid.replace(QLatin1Char('"'), QStringLiteral("\\\""));
        logSsid.replace(QLatin1Char('\n'), QLatin1Char(' '));
        logSsid.replace(QLatin1Char('\r'), QLatin1Char(' '));
        qWarning().noquote() << QStringLiteral("Wi-Fi authentication failed: ssid=\"%1\"")
                                .arg(logSsid);
    }
    publishWifiStateIfChanged();
    emit connectionAttemptFinished(success);
    scheduleRefresh();
}

void NetworkManagerClient::finalizeAttemptProfile(bool success)
{
    if (success)
        return;
    if (m_attemptProfileCreated && !m_attemptProfilePath.isEmpty()) {
        deleteConnectionProfile(m_attemptProfilePath);
    } else if (m_attemptProfileUpdated && !m_attemptProfilePath.isEmpty()) {
        restoreConnectionProfile(m_attemptProfilePath, m_originalAttemptProfileSettings);
    }
}

void NetworkManagerClient::deleteConnectionProfile(const QString &path)
{
    if (path.isEmpty() || path == QStringLiteral("/"))
        return;
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(SettingsConnectionInterface), QStringLiteral("Delete"));
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<> reply = *finished;
        if (reply.isError())
            qWarning() << "Could not remove failed transient Wi-Fi profile";
        finished->deleteLater();
    });
}

void NetworkManagerClient::restoreConnectionProfile(
    const QString &path, const NetworkConnectionSettings &settings)
{
    if (path.isEmpty() || path == QStringLiteral("/") || settings.isEmpty())
        return;
    QDBusMessage message = QDBusMessage::createMethodCall(
        QString::fromLatin1(NetworkManagerService), path,
        QString::fromLatin1(SettingsConnectionInterface), QStringLiteral("Update2"));
    message << QVariant::fromValue(settings) << uint(0x1) << QVariantMap();
    QDBusPendingCallWatcher *watcher = new QDBusPendingCallWatcher(m_bus.asyncCall(message), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this,
            [](QDBusPendingCallWatcher *finished) {
        QDBusPendingReply<QVariantMap> reply = *finished;
        if (reply.isError())
            qWarning() << "Could not restore saved Wi-Fi profile after failed authentication";
        finished->deleteLater();
    });
}

void NetworkManagerClient::publishWifiStateIfChanged()
{
    QVariantMap published;
    published.insert(QStringLiteral("devicePath"), m_wifiDevicePath);
    published.insert(QStringLiteral("deviceName"), wifiDeviceName());
    published.insert(QStringLiteral("available"), wifiAvailable());
    published.insert(QStringLiteral("radioEnabled"), m_wifiRadioEnabled);
    published.insert(QStringLiteral("state"), m_wifiState);
    published.insert(QStringLiteral("currentSsid"), m_wifiCurrentSsid);
    published.insert(QStringLiteral("ipv4"), m_wifiIpv4);
    published.insert(QStringLiteral("ipv6"), m_wifiIpv6);
    published.insert(QStringLiteral("scanning"), m_wifiScanning);
    published.insert(QStringLiteral("connecting"), m_wifiConnecting);
    published.insert(QStringLiteral("error"), m_wifiError);
    if (published == m_publishedWifiState)
        return;
    m_publishedWifiState = published;
    emit wifiStateChanged();
}

void NetworkManagerClient::publishEthernetStateIfChanged()
{
    QVariantMap published;
    published.insert(QStringLiteral("devicePath"), m_ethernetDevicePath);
    published.insert(QStringLiteral("deviceName"), ethernetDeviceName());
    published.insert(QStringLiteral("available"), ethernetAvailable());
    published.insert(QStringLiteral("connected"), ethernetConnected());
    published.insert(QStringLiteral("carrier"), ethernetCarrier());
    published.insert(QStringLiteral("state"), m_ethernetState);
    published.insert(QStringLiteral("connectionName"), m_ethernetConnectionName);
    published.insert(QStringLiteral("ipv4"), m_ethernetIpv4);
    published.insert(QStringLiteral("ipv6"), m_ethernetIpv6);
    if (published == m_publishedEthernetState)
        return;
    m_publishedEthernetState = published;
    emit ethernetStateChanged();
}

void NetworkManagerClient::publishAccessPointsIfChanged()
{
    if (m_accessPoints == m_publishedAccessPoints)
        return;
    m_publishedAccessPoints = m_accessPoints;
    emit accessPointsChanged();
}

void NetworkManagerClient::setWifiError(const QString &error)
{
    if (m_wifiError == error)
        return;
    m_wifiError = error;
    publishWifiStateIfChanged();
}

QString NetworkManagerClient::safeErrorText(const QString &errorName) const
{
    if (errorName.endsWith(QStringLiteral(".NoSecrets")) ||
        errorName.endsWith(QStringLiteral(".SecretsRequired")))
        return QStringLiteral("NetworkManager needs valid Wi-Fi credentials.");
    if (errorName.endsWith(QStringLiteral(".AccessDenied")))
        return QStringLiteral("NetworkManager denied the connection request.");
    if (errorName.endsWith(QStringLiteral(".InvalidArguments")))
        return QStringLiteral("NetworkManager rejected the Wi-Fi settings.");
    if (errorName.endsWith(QStringLiteral(".InvalidConnection")))
        return QStringLiteral("The saved Wi-Fi profile is invalid.");
    return QStringLiteral("NetworkManager could not connect. Check the network and credentials.");
}

void NetworkManagerClient::clearTransientCredentials()
{
    m_pendingPassword.fill(QChar(0));
    m_pendingPassword.clear();
    m_pendingSsid.clear();
    m_pendingKeyManagement.clear();
}

void NetworkManagerClient::onRelayChanged()
{
    scheduleRefresh();
}

void NetworkManagerClient::onDeviceStateChanged(uint state, uint oldState, uint reason)
{
    Q_UNUSED(oldState)
    NetworkManagerSignalRelay *relay =
        qobject_cast<NetworkManagerSignalRelay *>(sender());
    if (m_wifiConnecting && relay && relay->path() == m_wifiDevicePath && state == 120) {
        QString error = QStringLiteral("NetworkManager could not connect to this Wi-Fi network.");
        if (reason == 7 || reason == 10)
            error = QStringLiteral("Wi-Fi authentication failed. Check the password.");
        else if (reason == 5 || reason == 6)
            error = QStringLiteral("The network did not provide a usable IP configuration.");
        finishConnectionAttempt(false, error);
    }
    scheduleRefresh();
}

void NetworkManagerClient::onActiveConnectionStateChanged(uint state, uint reason)
{
    NetworkManagerSignalRelay *relay =
        qobject_cast<NetworkManagerSignalRelay *>(sender());
    if (m_wifiConnecting && relay && relay->path() == m_activeAttemptPath)
        handleActivationState(state, reason);
    scheduleRefresh();
}
