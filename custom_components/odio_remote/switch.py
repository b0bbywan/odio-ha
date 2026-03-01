"""Switch platform for Odio Remote — start/stop user-scope systemd services."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .coordinator import OdioServiceCoordinator

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Platform context
# =============================================================================


@dataclass
class _SwitchContext:
    """Shared setup state for switch platform helpers."""

    entry_id: str
    service_coordinator: OdioServiceCoordinator
    api: OdioApiClient
    device_info: DeviceInfo


# =============================================================================
# Platform setup
# =============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote switch entities."""
    rd = entry.runtime_data
    service_coordinator = rd.service_coordinator

    if service_coordinator is None:
        return

    ctx = _SwitchContext(
        entry_id=entry.entry_id,
        service_coordinator=service_coordinator,
        api=rd.api,
        device_info=rd.device_info,
    )

    entities = []
    if service_coordinator.data:
        entities = [
            OdioServiceSwitch(ctx, svc)
            for svc in service_coordinator.data.get("services", [])
            if svc.get("exists") and svc.get("scope") == "user"
        ]
        _LOGGER.debug("Creating %d service switch entities", len(entities))

    async_add_entities(entities)

    # -------------------------------------------------------------------------
    # Dynamic switch creation
    # Fires when service_coordinator first gets data after an API-down startup.
    # -------------------------------------------------------------------------
    known_switch_keys = {
        f"{e._service_info['scope']}/{e._service_info['name']}"
        for e in entities
    }

    @callback
    def _async_check_new_switches() -> None:
        if not service_coordinator.data:
            return
        new_entities = []
        for svc in service_coordinator.data.get("services", []):
            key = f"{svc.get('scope', 'user')}/{svc['name']}"
            if (
                svc.get("exists")
                and svc.get("scope") == "user"
                and key not in known_switch_keys
            ):
                new_entities.append(OdioServiceSwitch(ctx, svc))
                known_switch_keys.add(key)
        if new_entities:
            _LOGGER.info(
                "Dynamically adding %d switch entities after late API connection",
                len(new_entities),
            )
            async_add_entities(new_entities)

    entry.async_on_unload(
        service_coordinator.async_add_listener(_async_check_new_switches)
    )


# =============================================================================
# Entity
# =============================================================================


class OdioServiceSwitch(CoordinatorEntity[OdioServiceCoordinator], SwitchEntity):
    """Switch that starts/stops a user-scope systemd service."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _SwitchContext, service_info: dict[str, Any]) -> None:
        super().__init__(ctx.service_coordinator)
        self._api = ctx.api
        self._service_info = service_info

        service_name: str = service_info["name"]
        scope: str = service_info["scope"]

        self._attr_unique_id = f"{ctx.entry_id}_switch_{scope}_{service_name}"
        self._attr_name = service_name.removesuffix(".service")
        self._attr_device_info = ctx.device_info

    @property
    def is_on(self) -> bool:
        """Return True when the service is running."""
        if not self.coordinator.data:
            return False
        for svc in self.coordinator.data.get("services", []):
            if svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]:
                return svc.get("running", False)
        return False

    @property
    def available(self) -> bool:
        """Return False when the coordinator has no data."""
        return self.coordinator.last_update_success and bool(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the service."""
        await self._api.control_service(
            "start", self._service_info["scope"], self._service_info["name"]
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the service."""
        await self._api.control_service(
            "stop", self._service_info["scope"], self._service_info["name"]
        )
