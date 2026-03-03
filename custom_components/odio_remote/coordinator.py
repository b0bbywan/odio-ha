"""Coordinators for the Odio Remote integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api_client import OdioApiClient, SseEvent
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OdioAudioCoordinator(DataUpdateCoordinator[dict[str, list]]):
    """Coordinator for audio client data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
    ) -> None:
        """Initialize audio coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_audio",
            update_interval=None,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, list]:
        """Fetch audio clients from API."""
        try:
            clients = await self.api.get_clients()
            return {"audio": clients}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching audio clients")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def handle_sse_event(self, event: SseEvent) -> None:
        """Handle an audio.updated SSE event (changed/added clients only — merge into list)."""
        if not isinstance(event.data, list):
            _LOGGER.warning(
                "audio.updated: expected list, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE audio.updated: %d changed/added", len(event.data))
        current = list((self.data or {}).get("audio", []))
        updated_by_name = {c["name"]: c for c in event.data if "name" in c}
        result = [updated_by_name.pop(c.get("name"), c) for c in current]
        result.extend(updated_by_name.values())
        self.async_set_updated_data({"audio": result})

    def handle_sse_remove_event(self, event: SseEvent) -> None:
        """Handle an audio.removed SSE event.

        Keeps removed clients in the list but marks them corked=True so entities
        transition to Idle instead of disappearing from HA.
        """
        if not isinstance(event.data, list):
            _LOGGER.warning(
                "audio.removed: expected list, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE audio.removed: %d clients", len(event.data))
        removed_by_name = {
            c["name"]: {**c, "corked": True}
            for c in event.data
            if "name" in c
        }
        current = list((self.data or {}).get("audio", []))
        result = [removed_by_name.get(c.get("name"), c) for c in current]
        self.async_set_updated_data({"audio": result})


class OdioBluetoothCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Bluetooth adapter and device state."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
    ) -> None:
        """Initialize bluetooth coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_bluetooth",
            update_interval=None,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch Bluetooth status from API."""
        try:
            return await self.api.get_bluetooth_status()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching bluetooth status")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def handle_sse_event(self, event: SseEvent) -> None:
        """Handle a bluetooth.updated SSE event."""
        if not isinstance(event.data, dict):
            _LOGGER.warning(
                "bluetooth.updated: expected dict, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE bluetooth.updated: powered=%s", event.data.get("powered"))
        self.async_set_updated_data(event.data)


class OdioServiceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for systemd service data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
    ) -> None:
        """Initialize service coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_services",
            update_interval=None,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch systemd services from API."""
        try:
            services = await self.api.get_services()
            return {"services": services}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching services")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def handle_sse_event(self, event: SseEvent) -> None:
        """Handle a service.updated SSE event: merge into existing list."""
        if not isinstance(event.data, dict):
            _LOGGER.warning(
                "service.updated: expected dict, got %s", type(event.data).__name__
            )
            return

        svc_name = event.data.get("name")
        svc_scope = event.data.get("scope")
        if not svc_name or not svc_scope:
            _LOGGER.warning(
                "service.updated: missing name or scope in %s", event.data
            )
            return

        current = self.data or {"services": []}
        services = list(current.get("services", []))

        replaced = False
        for i, svc in enumerate(services):
            if svc.get("name") == svc_name and svc.get("scope") == svc_scope:
                services[i] = event.data
                replaced = True
                break
        if not replaced:
            services.append(event.data)

        _LOGGER.debug(
            "SSE service.updated: %s/%s (replaced=%s)", svc_scope, svc_name, replaced
        )
        self.async_set_updated_data({"services": services})
