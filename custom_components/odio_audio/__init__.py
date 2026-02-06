"""The Odio Audio integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api_client import OdioApiClient
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Odio Audio from a config entry."""
    _LOGGER.info("Setting up Odio Audio integration")

    # Debug: log raw entry data
    _LOGGER.debug("entry.data = %s", dict(entry.data))
    _LOGGER.debug("entry.options = %s", dict(entry.options))

    api_url = entry.data[CONF_API_URL]
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    service_scan_interval = entry.options.get(
        CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
    )
    # Read mappings from options only (not from data anymore)
    service_mappings = entry.options.get(CONF_SERVICE_MAPPINGS, {})

    _LOGGER.debug(
        "Configuration: api_url=%s, scan_interval=%s, service_scan_interval=%s",
        api_url, scan_interval, service_scan_interval,
    )
    _LOGGER.debug("Service mappings: %s", service_mappings)

    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    # -----------------------------------------------------------------
    # Fetch server capabilities once at startup
    # -----------------------------------------------------------------
    server_info = await api.get_server_capabilities()
    backends = server_info.get("backends", {})
    has_pulseaudio = backends.get("pulseaudio", False)
    has_mpris = backends.get("mpris", False)
    has_systemd = backends.get("systemd", False)

    _LOGGER.info(
        "Server capabilities: hostname=%s, api=%s v%s, backends: pulseaudio=%s, mpris=%s, systemd=%s",
        server_info.get("hostname"),
        server_info.get("api_sw"),
        server_info.get("api_version"),
        has_pulseaudio, has_mpris, has_systemd,
    )

    # Track consecutive failures for exponential backoff
    failure_counts = {"audio": 0, "services": 0}

    # ---------------------------------------------------------------------
    # Audio clients coordinator (fast polling)
    # Only polls endpoints whose backends are available
    # ---------------------------------------------------------------------

    async def async_update_audio() -> dict[str, Any]:
        try:
            clients = await api.get_clients() if has_pulseaudio else []
            players = await api.get_players() if has_mpris else []
            try:
                server = await api.get_server_info() if has_pulseaudio else {}
            except Exception:
                _LOGGER.debug("Could not fetch /audio/server, skipping")
                server = {}
            # Reset failure count on success
            failure_counts["audio"] = 0
            return {"audio": clients, "players": players, "server": server}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            # Connection errors are expected when device is offline
            # Implement exponential backoff with 1h max
            failure_counts["audio"] += 1
            retry_delay = min(scan_interval * (2 ** failure_counts["audio"]), 3600)
            _LOGGER.debug(
                "Connection failed (attempt %d), retrying in %ds",
                failure_counts["audio"], retry_delay
            )
            raise UpdateFailed(
                f"Unable to connect to Odio Audio API: {err}",
                retry_after=retry_delay
            ) from err
        except aiohttp.ClientResponseError as err:
            # HTTP errors (404, 500, etc.) should be handled gracefully
            failure_counts["audio"] += 1
            retry_delay = min(scan_interval * (2 ** failure_counts["audio"]), 3600)
            _LOGGER.warning(
                "HTTP error %d fetching audio data (attempt %d): %s",
                err.status, failure_counts["audio"], err
            )
            raise UpdateFailed(
                f"HTTP error {err.status}: {err.message}",
                retry_after=retry_delay
            ) from err
        except Exception as err:
            # Unexpected errors should still be logged with full traceback
            _LOGGER.exception("Unexpected error fetching audio clients/players")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    media_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_audio",
        update_method=async_update_audio,
        update_interval=timedelta(seconds=scan_interval),
        config_entry=entry,
    ) if has_pulseaudio or has_mpris else None

    # ---------------------------------------------------------------------
    # Services coordinator (slow polling)
    # Only polls endpoints whose backends are available
    # ---------------------------------------------------------------------

    async def async_update_services() -> dict[str, object]:
        try:
            services = await api.get_services()
            # Reset failure count on success
            failure_counts["services"] = 0
            return {"services": services}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            # Connection errors are expected when device is offline
            # Implement exponential backoff with 1h max
            failure_counts["services"] += 1
            retry_delay = min(service_scan_interval * (2 ** failure_counts["services"]), 3600)
            _LOGGER.debug(
                "Connection failed (attempt %d), retrying in %ds",
                failure_counts["services"], retry_delay
            )
            raise UpdateFailed(
                f"Unable to connect to Odio Audio API: {err}",
                retry_after=retry_delay
            ) from err
        except Exception as err:
            # Unexpected errors should still be logged with full traceback
            _LOGGER.exception("Unexpected error fetching services/server")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    service_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_services",
        update_method=async_update_services,
        update_interval=timedelta(seconds=service_scan_interval),
        config_entry=entry,
    ) if has_systemd else None

    # ---------------------------------------------------------------------
    # Initial refresh
    # ---------------------------------------------------------------------

    if media_coordinator:
        await media_coordinator.async_config_entry_first_refresh()
    if service_coordinator:
        await service_coordinator.async_config_entry_first_refresh()

    # Only forward platforms that have available backends
    platforms = []
    if has_pulseaudio or has_mpris or has_systemd:
        platforms.append(Platform.MEDIA_PLAYER)
    if has_systemd:
        platforms.append(Platform.SWITCH)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "media_coordinator": media_coordinator,
        "service_coordinator": service_coordinator,
        "service_mappings": service_mappings,
        "server_info": server_info,
        "backends": backends,
        "platforms": platforms,
    }

    _LOGGER.debug("Forwarding setup to platforms: %s", platforms)
    if platforms:
        await hass.config_entries.async_forward_entry_setups(entry, platforms)

    _LOGGER.info("Odio Audio integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = hass.data[DOMAIN][entry.entry_id].get("platforms", [])
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, platforms):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration.

    Allow the user to remove the Receiver or Services device from the UI.
    """
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("Reloading Odio Audio integration")
    hass.config_entries.async_schedule_reload(entry.entry_id)
