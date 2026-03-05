"""The Odio Remote integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceEntry
from homeassistant.helpers.entity import DeviceInfo

from .api_client import OdioApiClient
from .event_stream import OdioEventStreamManager
from .exceptions import OdioError
from .models import PowerCapabilities, ServerInfo, StartupData
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
class OdioCoordinators:
    """Groups the four optional SSE-driven coordinators."""

    audio: OdioAudioCoordinator | None = None
    service: OdioServiceCoordinator | None = None
    bluetooth: OdioBluetoothCoordinator | None = None
    mpris: OdioMPRISCoordinator | None = None

    def refresh_all(self, hass: HomeAssistant) -> None:
        """Schedule async_refresh on every active coordinator."""
        for coord in (self.audio, self.service, self.bluetooth, self.mpris):
            if coord is not None:
                hass.async_create_task(coord.async_refresh())


@dataclass
class OdioRemoteRuntimeData:
    """Runtime data for the Odio Remote integration."""

    api: OdioApiClient
    device_info: DeviceInfo
    server_info: ServerInfo
    coordinators: OdioCoordinators
    event_stream: OdioEventStreamManager
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

    # Fetch server_info + power capabilities once at startup — static, never polled again.
    try:
        startup = await StartupData.fetch(api)
    except OdioError:
        startup = StartupData.from_cache(entry.data)
        _LOGGER.warning(
            "API unreachable at startup — using cached data (backends: %s)",
            startup.server_info.backends,
        )
    startup.cache(hass, entry)
    server_info = startup.server_info
    backends = server_info.backends
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

    mac = await _resolve_mac(hass, entry, api_url)
    device_connections: set[tuple[str, str]] = (
        {(CONNECTION_NETWORK_MAC, mac)} if mac else set()
    )

    # Build DeviceInfo once — shared by all platforms so every entity stays
    # consistent regardless of which platform registers first.
    hostname = server_info.hostname or entry.entry_id
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=device_connections,
        name=f"Odio Remote ({hostname})",
        manufacturer="Odio",
        sw_version=server_info.api_version,
        hw_version=server_info.os_version,
        configuration_url=f"{api_url}/ui",
    )

    coordinators = OdioCoordinators(
        audio=await _setup_audio_coordinator(hass, entry, api, event_stream)
        if backends.get("pulseaudio") else None,
        service=await _setup_service_coordinator(hass, entry, api, event_stream)
        if backends.get("systemd") else None,
        mpris=await _setup_mpris_coordinator(hass, entry, api, event_stream)
        if backends.get("mpris") else None,
        bluetooth=await _setup_bluetooth_coordinator(hass, entry, api, event_stream)
        if backends.get("bluetooth") else None,
    )

    # Re-fetch coordinator data on SSE reconnect to avoid stale state.
    def _on_sse_reconnect() -> None:
        if not event_stream.sse_connected:
            return
        coordinators.refresh_all(hass)

    entry.async_on_unload(event_stream.async_add_listener(_on_sse_reconnect))

    entry.runtime_data = OdioRemoteRuntimeData(
        api=api,
        device_info=device_info,
        server_info=server_info,
        coordinators=coordinators,
        event_stream=event_stream,
        service_mappings=service_mappings,
        power_capabilities=startup.power,
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
