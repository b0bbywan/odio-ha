"""Coordinators for the Odio Remote integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api_client import OdioApiClient, SseEvent
from .const import DOMAIN
from .exceptions import OdioApiError, OdioConnectionError, OdioTimeoutError

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
        except (OdioConnectionError, OdioTimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except OdioApiError as err:
            _LOGGER.error("API error fetching audio data: %s", err)
            raise UpdateFailed(f"API error: {err}") from err

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
        except (OdioConnectionError, OdioTimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except OdioApiError as err:
            _LOGGER.error("API error fetching bluetooth status: %s", err)
            raise UpdateFailed(f"API error: {err}") from err

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
            fallback_ts = dt_util.parse_datetime(cache_ts) if cache_ts else None
            if fallback_ts is None:
                fallback_ts = dt_util.utcnow()
            stamped = []
            for p in players:
                raw = p.get("position_updated_at")
                ts = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
                stamped.append({**p, "position_updated_at": ts or fallback_ts})
            return {"mpris": stamped}
        except (OdioConnectionError, OdioTimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except OdioApiError as err:
            _LOGGER.error("API error fetching MPRIS players: %s", err)
            raise UpdateFailed(f"API error: {err}") from err

    def _merge_player(self, player_data: dict[str, Any], emitted_at_ms: int | None) -> None:
        """Merge a player into the current list, replacing by bus_name if it exists."""
        bus_name = player_data.get("bus_name")
        if not bus_name:
            return
        # Prefer the per-player position_updated_at from the backend; fall back
        # to the SSE wrapper's emitted_at, which can be newer than the actual
        # position write (e.g. a player.updated triggered by a Volume change).
        raw_pos_ts = player_data.get("position_updated_at")
        ts = dt_util.parse_datetime(raw_pos_ts) if isinstance(raw_pos_ts, str) else None
        if ts is None:
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


class OdioUpgradeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for software upgrade state (detector status + run progress).

    Seeded once from GET /upgrade, then driven by two SSE events. The stored
    dict merges three distinct payload shapes, dispatched by ``handle_sse_event``:

    - Detector status (``upgrade.info``) ``{current, latest, upgrade_available,
      can_upgrade, run?}`` — the installed/available versions, whether an upgrade
      may be started, and (during a run only) a nested ``run`` object. Mirrors
      the GET /upgrade body. ``can_check`` is ignored (re-detection is not
      exposed).
    - Run lifecycle (``upgrade.info``) ``{state: "running"|"finished", success?}``
      — toggles ``in_progress``. This is the systemd job result and is
      **authoritative** for completion: ``finished`` clears the run state.
    - Run progress (``upgrade.progress``) ``{event: "begin"|"progress"|"end",
      percent?, step?, total?, current?, success?}`` — drives
      ``percent``/``step`` only. It never clears ``in_progress`` (the script's
      ``end`` can precede the systemd job result), leaving completion to the
      lifecycle event above.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: OdioApiClient,
    ) -> None:
        """Initialize upgrade coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_upgrade",
            update_interval=None,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the last upgrade detector status from API."""
        try:
            status = await self.api.get_upgrade_status()
        except (OdioConnectionError, OdioTimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except OdioApiError as err:
            _LOGGER.error("API error fetching upgrade status: %s", err)
            raise UpdateFailed(f"API error: {err}") from err

        # GET /upgrade is authoritative: it reports the active run (if any) under
        # "run", so there is no need to preserve in-flight state across a refresh.
        previous = self.data or {}
        merged: dict[str, Any] = {
            "in_progress": False,
            "percent": None,
            "step": None,
            "can_upgrade": False,
        }
        if status:
            merged.update(
                current=status.get("current"),
                latest=status.get("latest"),
                upgrade_available=bool(status.get("upgrade_available")),
                can_upgrade=bool(status.get("can_upgrade")),
            )
            self._apply_run(merged, status.get("run"))
        else:
            # Detector has produced no result yet; keep whatever we already had.
            merged.update(
                current=previous.get("current"),
                latest=previous.get("latest"),
                upgrade_available=previous.get("upgrade_available", False),
                can_upgrade=previous.get("can_upgrade", False),
                in_progress=previous.get("in_progress", False),
                percent=previous.get("percent"),
                step=previous.get("step"),
            )
        return merged

    @staticmethod
    def _apply_run(target: dict[str, Any], run: Any) -> None:
        """Merge a nested ``run`` object ``{state, percent, step}`` into target.

        Present in GET /upgrade (and the detector ``upgrade.info`` event) only
        while a run is active; a missing/non-dict ``run`` means no active run.
        """
        if not isinstance(run, dict):
            return
        target["in_progress"] = run.get("state") == "running"
        if isinstance(run.get("percent"), (int, float)):
            target["percent"] = int(run["percent"])
        if run.get("step") is not None:
            target["step"] = run.get("step")

    def handle_sse_event(self, event: SseEvent) -> None:
        """Handle an ``upgrade.info``/``upgrade.progress`` event by payload shape."""
        if not isinstance(event.data, dict):
            _LOGGER.warning(
                "upgrade event: expected dict, got %s", type(event.data).__name__
            )
            return

        data = event.data
        current = {**(self.data or {})}

        if "upgrade_available" in data:
            # upgrade.info — detector status (installed/available versions + flags).
            current.update(
                current=data.get("current"),
                latest=data.get("latest"),
                upgrade_available=bool(data.get("upgrade_available")),
            )
            if "can_upgrade" in data:
                current["can_upgrade"] = bool(data.get("can_upgrade"))
            self._apply_run(current, data.get("run"))
            _LOGGER.debug(
                "SSE upgrade.info detector: current=%s latest=%s available=%s can_upgrade=%s",
                data.get("current"), data.get("latest"),
                data.get("upgrade_available"), data.get("can_upgrade"),
            )
        elif "state" in data:
            # upgrade.info — run lifecycle; the systemd job result is authoritative.
            running = data.get("state") == "running"
            current["in_progress"] = running
            if not running:
                current["percent"] = None
                current["step"] = None
                if data.get("success") is False:
                    _LOGGER.warning(
                        "Upgrade run finished unsuccessfully (state=%s)",
                        data.get("state"),
                    )
            _LOGGER.debug(
                "SSE upgrade.info lifecycle: state=%s success=%s",
                data.get("state"), data.get("success"),
            )
        elif "event" in data:
            # upgrade.progress — fine-grained progress from the upgrade script.
            # Drives percent/step only; completion is owned by the lifecycle
            # event above, so this never clears in_progress.
            ev = data.get("event")
            if ev == "begin":
                current["in_progress"] = True
                current["percent"] = 0
                if data.get("step") is not None:
                    current["step"] = data.get("step")
            elif ev == "progress":
                if isinstance(data.get("percent"), (int, float)):
                    current["percent"] = int(data["percent"])
                if data.get("step") is not None:
                    current["step"] = data.get("step")
            elif ev == "end":
                if data.get("success"):
                    current["percent"] = 100
            else:
                _LOGGER.warning("upgrade.progress: unknown event %s", ev)
                return
            _LOGGER.debug(
                "SSE upgrade.progress: event=%s percent=%s step=%s",
                ev, data.get("percent"), data.get("step"),
            )
        else:
            _LOGGER.warning("upgrade event: unrecognized payload %s", data)
            return

        self.async_set_updated_data(current)


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
        except (OdioConnectionError, OdioTimeoutError) as err:
            raise UpdateFailed(f"Unable to connect to Odio Remote API: {err}") from err
        except OdioApiError as err:
            _LOGGER.error("API error fetching services: %s", err)
            raise UpdateFailed(f"API error: {err}") from err

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
