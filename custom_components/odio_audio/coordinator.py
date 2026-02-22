"""Coordinators for the Odio Audio integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api_client import OdioApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OdioAudioCoordinator(DataUpdateCoordinator[dict[str, list]]):
    """Coordinator for audio client data (fast polling)."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
        scan_interval: int,
    ) -> None:
        """Initialize audio coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_audio",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=config_entry,
        )
        self.api = api
        self._failure_count = 0
        self._scan_interval = scan_interval

    async def _async_update_data(self) -> dict[str, list]:
        """Fetch audio clients from API."""
        try:
            clients = await self.api.get_clients()
            self._failure_count = 0
            return {"audio": clients}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            self._failure_count += 1
            retry_delay = min(
                self._scan_interval * (2 ** self._failure_count), 3600
            )
            _LOGGER.debug(
                "Connection failed (attempt %d), retrying in %ds",
                self._failure_count,
                retry_delay,
            )
            raise UpdateFailed(
                f"Unable to connect to Odio Audio API: {err}",
                retry_after=retry_delay,
            ) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching audio clients")
            raise UpdateFailed(f"Unexpected error: {err}") from err


class OdioServiceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for service and server data (slow polling)."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
        scan_interval: int,
    ) -> None:
        """Initialize service coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_services",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=config_entry,
        )
        self.api = api
        self._failure_count = 0
        self._scan_interval = scan_interval

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch services and server info from API."""
        try:
            services = await self.api.get_services()
            server = await self.api.get_server_info()
            self._failure_count = 0
            return {
                "services": services,
                "server": server,
            }
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            self._failure_count += 1
            retry_delay = min(
                self._scan_interval * (2 ** self._failure_count), 3600
            )
            _LOGGER.debug(
                "Connection failed (attempt %d), retrying in %ds",
                self._failure_count,
                retry_delay,
            )
            raise UpdateFailed(
                f"Unable to connect to Odio Audio API: {err}",
                retry_after=retry_delay,
            ) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching services/server")
            raise UpdateFailed(f"Unexpected error: {err}") from err
