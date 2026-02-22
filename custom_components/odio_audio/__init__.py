"""The Odio Audio integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api_client import OdioApiClient
from .const import (
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    CONF_SERVICE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
)
from .coordinator import OdioAudioCoordinator, OdioServiceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


@dataclass
class OdioAudioRuntimeData:
    """Runtime data for the Odio Audio integration."""

    api: OdioApiClient
    audio_coordinator: OdioAudioCoordinator
    service_coordinator: OdioServiceCoordinator
    service_mappings: dict[str, str]


type OdioAudioConfigEntry = ConfigEntry[OdioAudioRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: OdioAudioConfigEntry) -> bool:
    """Set up Odio Audio from a config entry."""
    _LOGGER.info("Setting up Odio Audio integration")

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

    audio_coordinator = OdioAudioCoordinator(hass, entry, api, scan_interval)
    service_coordinator = OdioServiceCoordinator(
        hass, entry, api, service_scan_interval
    )

    await audio_coordinator.async_config_entry_first_refresh()
    await service_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = OdioAudioRuntimeData(
        api=api,
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        service_mappings=service_mappings,
    )

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Odio Audio integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OdioAudioConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: OdioAudioConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration."""
    return True
