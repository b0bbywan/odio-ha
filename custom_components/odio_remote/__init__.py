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
from homeassistant.helpers.entity import DeviceInfo

from .api_client import OdioApiClient
from .event_stream import OdioEventStreamManager
from .const import (
    CONF_API_URL,
    DOMAIN,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    CONF_SERVICE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
    SSE_EVENT_AUDIO_UPDATED,
    SSE_EVENT_SERVICE_UPDATED,
)
from .coordinator import OdioAudioCoordinator, OdioServiceCoordinator
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
    device_info: DeviceInfo
    audio_coordinator: OdioAudioCoordinator | None
    service_coordinator: OdioServiceCoordinator | None
    event_stream: OdioEventStreamManager
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

    # Fetch server_info once at startup — it is static and never polled again.
    try:
        server_info: dict[str, Any] = await api.get_server_info()
        if server_info != entry.data.get("server_info"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "server_info": server_info}
            )
    except Exception:
        server_info = entry.data.get("server_info", {})
        _LOGGER.warning(
            "API unreachable at startup — using cached server_info (backends: %s)",
            server_info.get("backends", {}),
        )
    backends = server_info.get("backends", {})
    _LOGGER.debug("Detected backends: %s", backends)

    # Build SSE backends list from server capabilities.
    sse_backends: list[str] = []
    if backends.get("pulseaudio"):
        sse_backends.append("audio")
    if backends.get("systemd"):
        sse_backends.append("systemd")

    # Create event_stream early (not started yet) so coordinators can use
    # is_api_reachable as a gate during their initial refresh.
    event_stream = OdioEventStreamManager(
        hass=hass,
        api=api,
        backends=sse_backends,
    )

    # Resolve MAC via device_tracker entities; fall back to cached value.
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
                "MAC address not resolved for %s — 'Connected via' link unavailable", host
            )
    device_connections: set[tuple[str, str]] = (
        {(CONNECTION_NETWORK_MAC, mac)} if mac else set()
    )

    power_capabilities: dict[str, bool] = {}
    if backends.get("power"):
        try:
            power_capabilities = await api.get_power_capabilities()
            if power_capabilities != entry.data.get("power_capabilities"):
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "power_capabilities": power_capabilities}
                )
        except Exception:
            power_capabilities = entry.data.get("power_capabilities", {})
            _LOGGER.warning(
                "Failed to fetch power capabilities — using cached value: %s",
                power_capabilities,
            )

    # Build DeviceInfo once — shared by all platforms so every entity stays
    # consistent regardless of which platform registers first.
    hostname = server_info.get("hostname", entry.entry_id)
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=device_connections,
        name=f"Odio Remote ({hostname})",
        manufacturer="Odio",
        sw_version=server_info.get("api_version"),
        hw_version=server_info.get("os_version"),
        configuration_url=f"{api_url}/ui",
    )

    audio_coordinator: OdioAudioCoordinator | None = None
    if backends.get("pulseaudio"):
        audio_coordinator = OdioAudioCoordinator(
            hass, entry, api, scan_interval, event_stream
        )
        await audio_coordinator.async_refresh()
        _LOGGER.debug("Audio coordinator created (pulseaudio backend enabled)")

    service_coordinator: OdioServiceCoordinator | None = None
    if backends.get("systemd"):
        service_coordinator = OdioServiceCoordinator(
            hass, entry, api, service_scan_interval, event_stream
        )
        await service_coordinator.async_refresh()
        _LOGGER.debug("Service coordinator created (systemd backend enabled)")

    # Wire SSE event listeners now that coordinators exist.
    if audio_coordinator is not None:
        entry.async_on_unload(
            event_stream.async_add_event_listener(
                SSE_EVENT_AUDIO_UPDATED, audio_coordinator.handle_sse_event
            )
        )
    if service_coordinator is not None:
        entry.async_on_unload(
            event_stream.async_add_event_listener(
                SSE_EVENT_SERVICE_UPDATED, service_coordinator.handle_sse_event
            )
        )

    entry.runtime_data = OdioRemoteRuntimeData(
        api=api,
        device_info=device_info,
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        event_stream=event_stream,
        service_mappings=service_mappings,
        power_capabilities=power_capabilities,
    )

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    event_stream.start()

    _LOGGER.info("Odio Remote integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.event_stream.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: OdioConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration."""
    return True
