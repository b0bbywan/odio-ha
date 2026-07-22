"""The Odio Remote integration."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceEntry
from homeassistant.helpers.device_registry import DeviceInfo
from pyodio import OdioError, OdioHub, PowerCapabilities, ServerInfo

from .migrate import migrate_mpris_service_mappings, migrate_mpris_unique_ids
from .models import StartupData
from .const import (
    CONF_API_URL,
    CONF_KEEPALIVE_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DOMAIN,
)
from .helpers import async_get_mac_from_ip

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


@dataclass
class OdioRemoteRuntimeData:
    """Runtime data for the Odio Remote integration."""

    hub: OdioHub
    device_info: DeviceInfo
    server_info: ServerInfo
    service_mappings: dict[str, str]
    power_capabilities: PowerCapabilities


type OdioConfigEntry = ConfigEntry[OdioRemoteRuntimeData]


async def _resolve_mac(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api_url: str,
) -> str | None:
    """Resolve MAC address via device_tracker; fall back to cached value."""
    host = urlparse(api_url).hostname
    mac = await async_get_mac_from_ip(hass, host) if host else None
    if mac:
        _LOGGER.debug("Resolved MAC for %s: %s", host, mac)
        if mac != entry.data.get("mac"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "mac": mac}
            )
    else:
        mac = entry.data.get("mac")
        if mac:
            _LOGGER.debug("Using cached MAC for %s: %s", host, mac)
        else:
            _LOGGER.warning(
                "MAC address not resolved for %s — 'Connected via' link unavailable",
                host,
            )
    return mac


def _cache_services(hass: HomeAssistant, entry: OdioConfigEntry, hub: OdioHub) -> None:
    """Persist the systemd service list so switches survive API-down startups."""
    services = [asdict(s.state) for s in hub.services.values()]
    if services and services != entry.data.get("cached_services"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "cached_services": services}
        )


def _register_sw_version_sync(
    hass: HomeAssistant, entry: OdioConfigEntry, hub: OdioHub
) -> None:
    """Keep the device registry's software version in sync with the detector."""
    last_synced: str | None = hub.upgrade.current_version or None

    @callback
    def _sync_device_sw_version(change: str, _obj: object) -> None:
        nonlocal last_synced
        current = hub.upgrade.current_version
        if not current or current == last_synced:
            return
        last_synced = current
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
        if device is not None and device.sw_version != current:
            dev_reg.async_update_device(device.id, sw_version=current)

    entry.async_on_unload(hub.upgrade.on_change(_sync_device_sw_version))


async def async_setup_entry(hass: HomeAssistant, entry: OdioConfigEntry) -> bool:
    """Set up Odio Remote from a config entry."""
    _LOGGER.info("Setting up Odio Remote integration")

    api_url = entry.data[CONF_API_URL]
    keepalive_interval = entry.options.get(CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL)
    service_mappings = entry.options.get(CONF_SERVICE_MAPPINGS, {})

    _LOGGER.debug(
        "Configuration: api_url=%s, keepalive_interval=%s",
        api_url,
        keepalive_interval,
    )
    _LOGGER.debug("Service mappings: %s", service_mappings)

    session = async_get_clientsession(hass)
    hub = OdioHub(api_url, session, keepalive=keepalive_interval)

    # Initial sync fetches server_info + power capabilities; if the API is
    # down, fall back to the cached snapshot and let the stream connect later.
    try:
        await hub.connect()
        startup = StartupData.from_hub(hub)
    except OdioError:
        startup = StartupData.from_cache(entry.data)
        _LOGGER.warning(
            "API unreachable at startup — using cached data (backends: %s)",
            startup.server_info.backends,
        )
        await hub.start()
    startup.cache(hass, entry)
    server_info = startup.server_info
    backends = server_info.backends
    _LOGGER.debug("Detected backends: %s", backends)

    if backends.systemd:
        _cache_services(hass, entry, hub)
    if backends.upgrade:
        _register_sw_version_sync(hass, entry, hub)

    mac = await _resolve_mac(hass, entry, api_url)
    device_connections: set[tuple[str, str]] = (
        {(CONNECTION_NETWORK_MAC, mac)} if mac else set()
    )

    # Build DeviceInfo once — shared by all platforms so every entity stays
    # consistent regardless of which platform registers first. The displayed
    # software version comes from the upgrade detector's current version when
    # the upgrade backend is enabled, falling back to the API's own version.
    hostname = server_info.hostname or entry.entry_id
    sw_version = hub.upgrade.current_version if backends.upgrade else None
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=device_connections,
        name=f"Odio Remote ({hostname})",
        manufacturer="Odio",
        sw_version=sw_version or server_info.api_version,
        hw_version=server_info.os_version,
        configuration_url=f"{api_url}/ui",
    )

    # On SSE (re)connect, re-detect backends: an upgrade can add/remove a
    # backend, which needs a full reload to rebuild entities. The hub resyncs
    # before reporting the connection, so hub.server is fresh here.
    @callback
    def _on_connection_change(connected: bool) -> None:
        if not connected:
            return
        if hub.server.backends != server_info.backends:
            _LOGGER.info(
                "Backends changed on SSE reconnect (%s -> %s) — reloading entry",
                server_info.backends,
                hub.server.backends,
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        StartupData.from_hub(hub).cache(hass, entry)
        if backends.systemd:
            _cache_services(hass, entry, hub)

    entry.async_on_unload(hub.on_connection_change(_on_connection_change))

    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub,
        device_info=device_info,
        server_info=server_info,
        service_mappings=service_mappings,
        power_capabilities=startup.power,
    )

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Odio Remote integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.hub.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: OdioConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration."""
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: OdioConfigEntry) -> bool:
    """Migrate an Odio Remote config entry to the current schema."""
    _LOGGER.debug("Migrating Odio config entry from version %s", entry.version)
    if entry.version > 2:
        return False
    if entry.version < 2:
        migrate_mpris_unique_ids(hass, entry)
        migrate_mpris_service_mappings(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
    return True
