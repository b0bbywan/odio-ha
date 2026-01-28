"""The Odio Audio integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
    ENDPOINT_SERVER,
    ENDPOINT_CLIENTS,
    ENDPOINT_SERVICES,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Odio Audio from a config entry."""
    _LOGGER.info("Setting up Odio Audio integration")

    api_url = entry.data[CONF_API_URL]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    service_scan_interval = entry.options.get(
        CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
    )
    service_mappings = entry.options.get(
        CONF_SERVICE_MAPPINGS,
        entry.data.get(CONF_SERVICE_MAPPINGS, {}),
    )

    _LOGGER.debug(
        "Configuration: api_url=%s, scan_interval=%s, service_scan_interval=%s",
        api_url, scan_interval, service_scan_interval,
    )
    _LOGGER.debug("Service mappings: %s", service_mappings)

    session = async_get_clientsession(hass)

    # Coordinator for audio clients (fast polling)
    async def async_update_audio():
        """Fetch audio data from API."""
        url = f"{api_url}{ENDPOINT_CLIENTS}"
        _LOGGER.debug("Fetching audio clients from: %s", url)

        try:
            async with asyncio.timeout(10):
                async with session.get(url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("Audio clients endpoint returned %s: %s", response.status, error_text)
                        raise UpdateFailed(f"Error fetching audio clients: HTTP {response.status}")

                    data = await response.json()
                    _LOGGER.debug("Audio clients fetched: %d clients", len(data) if isinstance(data, list) else 0)
                    return {"audio": data}

        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout fetching audio clients from %s", url)
            raise UpdateFailed("Timeout communicating with API") from err

        except aiohttp.ClientError as err:
            _LOGGER.error("Client error fetching audio clients: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching audio clients")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    audio_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_audio",
        update_method=async_update_audio,
        update_interval=timedelta(seconds=scan_interval),
        config_entry=entry,
    )

    # Coordinator for services (slow polling)
    async def async_update_services():
        """Fetch services data from API."""
        services_url = f"{api_url}{ENDPOINT_SERVICES}"
        server_url = f"{api_url}{ENDPOINT_SERVER}"

        _LOGGER.debug("Fetching services from: %s", services_url)
        _LOGGER.debug("Fetching server info from: %s", server_url)

        try:
            async with asyncio.timeout(15):
                async with session.get(services_url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("Services endpoint returned %s: %s", response.status, error_text)
                        raise UpdateFailed(f"Error fetching services: HTTP {response.status}")

                    services = await response.json()
                    _LOGGER.debug("Services fetched: %d services", len(services) if isinstance(services, list) else 0)

                async with session.get(server_url) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("Server endpoint returned %s: %s", response.status, error_text)
                        raise UpdateFailed(f"Error fetching server info: HTTP {response.status}")

                    server = await response.json()
                    _LOGGER.debug("Server info fetched: %s", server.get("name"))

                return {"services": services, "server": server}

        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout fetching services/server data")
            raise UpdateFailed("Timeout communicating with API") from err

        except aiohttp.ClientError as err:
            _LOGGER.error("Client error fetching services/server: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching services/server")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    service_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_services",
        update_method=async_update_services,
        update_interval=timedelta(seconds=service_scan_interval),
        config_entry=entry,
    )

    # Fetch initial data
    _LOGGER.debug("Fetching initial data...")

    try:
        await audio_coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial audio data fetched successfully")
    except Exception as err:
        _LOGGER.error("Failed to fetch initial audio data: %s", err)
        raise

    try:
        await service_coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial service data fetched successfully")
    except Exception as err:
        _LOGGER.error("Failed to fetch initial service data: %s", err)
        raise

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "audio_coordinator": audio_coordinator,
        "service_coordinator": service_coordinator,
        "api_url": api_url,
        "session": session,
        "service_mappings": service_mappings,
    }

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Don't auto-reload on options change, only on explicit reload
    # This prevents state conflicts when updating mappings
    # entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Odio Audio integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Odio Audio integration")

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Odio Audio integration unloaded successfully")
    else:
        _LOGGER.error("Failed to unload Odio Audio integration")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("Reloading Odio Audio integration")
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
