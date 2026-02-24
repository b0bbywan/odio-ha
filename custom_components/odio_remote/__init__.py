"""The Odio Remote integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceEntry

from .api_client import OdioApiClient
from .const import (
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    CONF_SERVICE_SCAN_INTERVAL,
    DEFAULT_CONNECTIVITY_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
)
from .coordinator import OdioAudioCoordinator, OdioConnectivityCoordinator, OdioServiceCoordinator
from .helpers import async_get_mac_from_ip

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
]


@dataclass
class OdioRemoteRuntimeData:
    """Runtime data for the Odio Remote integration."""

    api: OdioApiClient
    server_info: dict[str, Any]
    device_connections: set[tuple[str, str]]
    connectivity_coordinator: OdioConnectivityCoordinator
    audio_coordinator: OdioAudioCoordinator | None
    service_coordinator: OdioServiceCoordinator | None
    service_mappings: dict[str, str]
    power_capabilities: dict[str, bool]


type OdioConfigEntry = ConfigEntry[OdioRemoteRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: OdioConfigEntry) -> bool:
    """Set up Odio Remote from a config entry."""
    _LOGGER.info("Setting up Odio Remote integration")

    api_url = entry.data[CONF_API_URL]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    service_scan_interval = entry.options.get(
        CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
    )
    service_mappings = entry.options.get(CONF_SERVICE_MAPPINGS, {})

    _LOGGER.debug(
        "Configuration: api_url=%s, scan_interval=%s, service_scan_interval=%s",
        api_url,
        scan_interval,
        service_scan_interval,
    )
    _LOGGER.debug("Service mappings: %s", service_mappings)

    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    connectivity_coordinator = OdioConnectivityCoordinator(
        hass, entry, api, DEFAULT_CONNECTIVITY_SCAN_INTERVAL
    )
    # Use async_refresh (not async_config_entry_first_refresh) so setup always
    # completes even when the API is down.  The connectivity binary sensor can
    # then report "disconnected" instead of the whole device disappearing.
    await connectivity_coordinator.async_refresh()

    if connectivity_coordinator.last_update_success:
        server_info: dict[str, Any] = connectivity_coordinator.data or {}
        # Persist server_info so we can use it on the next startup if the API
        # is unreachable at that point.
        if server_info != entry.data.get("server_info"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "server_info": server_info}
            )
    else:
        # API is down — restore last known server_info from config entry data.
        server_info = entry.data.get("server_info", {})
        _LOGGER.warning(
            "API unreachable at startup — using cached server_info (backends: %s)",
            server_info.get("backends", {}),
        )
    backends = server_info.get("backends", {})
    _LOGGER.debug("Detected backends: %s", backends)

    # Resolve MAC from ARP cache (only populated when connectivity refresh succeeded)
    host = urlparse(api_url).hostname
    mac = await async_get_mac_from_ip(hass, host) if host else None
    if mac:
        _LOGGER.debug("Resolved MAC for %s: %s", host, mac)
        device_connections: set[tuple[str, str]] = {(CONNECTION_NETWORK_MAC, mac)}
    else:
        _LOGGER.warning(
            "MAC address not resolved for %s — 'Connected via' link unavailable", host
        )
        device_connections = set()
    _LOGGER.debug("Connectivity coordinator created")

    power_capabilities: dict[str, bool] = {}
    if backends.get("power"):
        try:
            power_capabilities = await api.get_power_capabilities()
        except Exception:
            _LOGGER.warning("Failed to fetch power capabilities, power buttons disabled")

    audio_coordinator: OdioAudioCoordinator | None = None
    if backends.get("pulseaudio"):
        audio_coordinator = OdioAudioCoordinator(
            hass, entry, api, scan_interval, connectivity_coordinator
        )
        await audio_coordinator.async_refresh()
        _LOGGER.debug("Audio coordinator created (pulseaudio backend enabled)")

    service_coordinator: OdioServiceCoordinator | None = None
    if backends.get("systemd"):
        service_coordinator = OdioServiceCoordinator(
            hass, entry, api, service_scan_interval, connectivity_coordinator
        )
        await service_coordinator.async_refresh()
        _LOGGER.debug("Service coordinator created (systemd backend enabled)")

    entry.runtime_data = OdioRemoteRuntimeData(
        api=api,
        server_info=server_info,
        device_connections=device_connections,
        connectivity_coordinator=connectivity_coordinator,
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        service_mappings=service_mappings,
        power_capabilities=power_capabilities,
    )

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Odio Remote integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: OdioConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration."""
    return True
