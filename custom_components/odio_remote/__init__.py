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
    CONF_KEEPALIVE_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DOMAIN,
    SSE_EVENT_AUDIO_OUTPUT_REMOVED,
    SSE_EVENT_AUDIO_OUTPUT_UPDATED,
    SSE_EVENT_AUDIO_REMOVED,
    SSE_EVENT_AUDIO_UPDATED,
    SSE_EVENT_BLUETOOTH_UPDATED,
    SSE_EVENT_PLAYER_UPDATED,
    SSE_EVENT_PLAYER_ADDED,
    SSE_EVENT_PLAYER_REMOVED,
    SSE_EVENT_PLAYER_POSITION,
    SSE_EVENT_SERVICE_UPDATED,
)
from .coordinator import OdioAudioCoordinator, OdioBluetoothCoordinator, OdioMPRISCoordinator, OdioServiceCoordinator
from .helpers import async_get_mac_from_ip

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class OdioRemoteRuntimeData:
    """Runtime data for the Odio Remote integration."""

    api: OdioApiClient
    device_info: DeviceInfo
    audio_coordinator: OdioAudioCoordinator | None
    service_coordinator: OdioServiceCoordinator | None
    bluetooth_coordinator: OdioBluetoothCoordinator | None
    mpris_coordinator: OdioMPRISCoordinator | None
    event_stream: OdioEventStreamManager
    service_mappings: dict[str, str]
    power_capabilities: dict[str, bool]


type OdioConfigEntry = ConfigEntry[OdioRemoteRuntimeData]


async def _setup_audio_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioAudioCoordinator:
    """Create audio coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioAudioCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_UPDATED, coordinator.handle_sse_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_REMOVED, coordinator.handle_sse_remove_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_OUTPUT_UPDATED, coordinator.handle_sse_output_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_OUTPUT_REMOVED, coordinator.handle_sse_output_remove_event
        )
    )
    _LOGGER.debug("Audio coordinator created (pulseaudio backend enabled)")
    return coordinator


async def _setup_service_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioServiceCoordinator:
    """Create service coordinator, refresh, cache services, and wire SSE listeners."""
    coordinator = OdioServiceCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    if coordinator.data:
        services = coordinator.data.get("services", [])
        if services != entry.data.get("cached_services"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "cached_services": services}
            )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_SERVICE_UPDATED, coordinator.handle_sse_event
        )
    )
    _LOGGER.debug("Service coordinator created (systemd backend enabled)")
    return coordinator


async def _setup_mpris_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioMPRISCoordinator:
    """Create MPRIS coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioMPRISCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_UPDATED, coordinator.handle_sse_update_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_ADDED, coordinator.handle_sse_update_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_REMOVED, coordinator.handle_sse_removed_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_POSITION, coordinator.handle_sse_position_event
        )
    )
    _LOGGER.debug("MPRIS coordinator created (mpris backend enabled)")
    return coordinator


async def _setup_bluetooth_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioBluetoothCoordinator:
    """Create bluetooth coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioBluetoothCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_BLUETOOTH_UPDATED, coordinator.handle_sse_event
        )
    )
    _LOGGER.debug("Bluetooth coordinator created (bluetooth backend enabled)")
    return coordinator


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
    if backends.get("power"):
        sse_backends.append("power")
    if backends.get("bluetooth"):
        sse_backends.append("bluetooth")
    if backends.get("mpris"):
        sse_backends.append("mpris")

    event_stream = OdioEventStreamManager(
        hass=hass,
        api=api,
        backends=sse_backends,
        keepalive_interval=keepalive_interval,
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

    audio_coordinator = (
        await _setup_audio_coordinator(hass, entry, api, event_stream)
        if backends.get("pulseaudio") else None
    )
    service_coordinator = (
        await _setup_service_coordinator(hass, entry, api, event_stream)
        if backends.get("systemd") else None
    )
    mpris_coordinator = (
        await _setup_mpris_coordinator(hass, entry, api, event_stream)
        if backends.get("mpris") else None
    )
    bluetooth_coordinator = (
        await _setup_bluetooth_coordinator(hass, entry, api, event_stream)
        if backends.get("bluetooth") else None
    )

    # Re-fetch coordinator data on SSE reconnect to avoid stale state.
    def _on_sse_reconnect() -> None:
        if not event_stream.sse_connected:
            return
        if audio_coordinator is not None:
            hass.async_create_task(audio_coordinator.async_refresh())
        if service_coordinator is not None:
            hass.async_create_task(service_coordinator.async_refresh())
        if bluetooth_coordinator is not None:
            hass.async_create_task(bluetooth_coordinator.async_refresh())
        if mpris_coordinator is not None:
            hass.async_create_task(mpris_coordinator.async_refresh())

    entry.async_on_unload(event_stream.async_add_listener(_on_sse_reconnect))

    entry.runtime_data = OdioRemoteRuntimeData(
        api=api,
        device_info=device_info,
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        bluetooth_coordinator=bluetooth_coordinator,
        mpris_coordinator=mpris_coordinator,
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
