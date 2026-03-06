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
from homeassistant.util import dt as dt_util

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
        """Fetch audio data (clients + outputs) from API."""
        try:
            data = await self.api.get_audio_data()
            return {"audio": data["clients"], "outputs": data["outputs"]}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching audio data")
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
        self.async_set_updated_data({**(self.data or {}), "audio": result})

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
        self.async_set_updated_data({**(self.data or {}), "audio": result})

    def handle_sse_output_event(self, event: SseEvent) -> None:
        """Handle an audio.output.updated SSE event (merge into outputs list)."""
        if not isinstance(event.data, list):
            _LOGGER.warning(
                "audio.output.updated: expected list, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE audio.output.updated: %d outputs", len(event.data))
        current = list((self.data or {}).get("outputs", []))
        updated_by_name = {o["name"]: o for o in event.data if "name" in o}
        result = [updated_by_name.pop(o.get("name"), o) for o in current]
        result.extend(updated_by_name.values())
        self.async_set_updated_data({**(self.data or {}), "outputs": result})

    def handle_sse_output_remove_event(self, event: SseEvent) -> None:
        """Handle an audio.output.removed SSE event (remove from outputs list)."""
        if not isinstance(event.data, list):
            _LOGGER.warning(
                "audio.output.removed: expected list, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE audio.output.removed: %d outputs", len(event.data))
        removed_names = {o["name"] for o in event.data if "name" in o}
        current = list((self.data or {}).get("outputs", []))
        result = [o for o in current if o.get("name") not in removed_names]
        self.async_set_updated_data({**(self.data or {}), "outputs": result})


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


class OdioMPRISCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for MPRIS players data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
    ) -> None:
        """Initialize MPRIS coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_mpris",
            update_interval=None,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch MPRIS status from API."""
        try:
            players, cache_ts = await self.api.get_players()
            position_updated_at = dt_util.parse_datetime(cache_ts) if cache_ts else dt_util.utcnow()
            stamped = [{**p, "position_updated_at": position_updated_at} for p in players]
            return {"mpris": stamped}
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching MPRIS players")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _merge_player(self, player_data: dict[str, Any], emitted_at_ms: int | None) -> None:
        """Merge a player into the current list, replacing by bus_name if it exists."""
        bus_name = player_data.get("bus_name")
        if not bus_name:
            return
        if emitted_at_ms is not None:
            ts = dt_util.utc_from_timestamp(emitted_at_ms / 1000)
        else:
            ts = dt_util.utcnow()
        stamped = {**player_data, "position_updated_at": ts}
        current = list((self.data or {}).get("mpris", []))
        for i, p in enumerate(current):
            if p.get("bus_name") == bus_name:
                current[i] = stamped
                self.async_set_updated_data({**(self.data or {}), "mpris": current})
                return
        current.append(stamped)
        self.async_set_updated_data({**(self.data or {}), "mpris": current})

    def handle_sse_update_event(self, event: SseEvent) -> None:
        """Handle a player.updated SSE event: {"data": {...player...}, "emitted_at": ms}."""
        if not isinstance(event.data, dict):
            _LOGGER.warning("player.updated: expected dict, got %s", type(event.data).__name__)
            return
        player_data = event.data.get("data")
        if not isinstance(player_data, dict):
            _LOGGER.warning("player.updated: missing 'data' key in %s", event.data)
            return
        _LOGGER.debug("SSE player.updated: %s", player_data.get("bus_name"))
        self._merge_player(player_data, event.data.get("emitted_at"))

    def handle_sse_removed_event(self, event: SseEvent) -> None:
        """Handle a player.removed SSE event: {"bus_name": "..."}.

        Keeps the player in the list but marks it unavailable so the entity
        transitions to OFF rather than disappearing from HA.
        """
        if not isinstance(event.data, dict):
            _LOGGER.warning("player.removed: expected dict, got %s", type(event.data).__name__)
            return
        bus_name = event.data.get("bus_name")
        if not bus_name:
            _LOGGER.warning("player.removed: missing bus_name in %s", event.data)
            return
        current = [
            {**p, "available": False, "playback_status": "Stopped"} if p.get("bus_name") == bus_name else p
            for p in (self.data or {}).get("mpris", [])
        ]
        _LOGGER.debug("SSE player.removed: %s (marked unavailable)", bus_name)
        self.async_set_updated_data({**(self.data or {}), "mpris": current})

    def handle_sse_position_event(self, event: SseEvent) -> None:
        """Handle a player.position SSE event: list of {"bus_name", "position", ...}."""
        if not isinstance(event.data, list):
            _LOGGER.warning("player.position: expected list, got %s", type(event.data).__name__)
            return
        updates = {
            item["bus_name"]: (
                item["position"],
                dt_util.utc_from_timestamp(item["emitted_at"] / 1000) if item.get("emitted_at") else dt_util.utcnow(),
            )
            for item in event.data
            if "bus_name" in item and "position" in item
        }
        if not updates:
            return
        current = [
            {**p, "position": updates[p["bus_name"]][0], "position_updated_at": updates[p["bus_name"]][1]}
            if p.get("bus_name") in updates else p
            for p in (self.data or {}).get("mpris", [])
        ]
        _LOGGER.debug("SSE player.position: %d players updated", len(updates))
        self.async_set_updated_data({**(self.data or {}), "mpris": current})


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
