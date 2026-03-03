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
from .coordinator import OdioBluetoothCoordinator, OdioServiceCoordinator
from .event_stream import OdioEventStreamManager

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
    event_stream: OdioEventStreamManager


# =============================================================================
# Platform setup
# =============================================================================


def _build_service_switches(
    entry: OdioConfigEntry,
    service_coordinator: OdioServiceCoordinator,
) -> tuple[_SwitchContext, list["OdioServiceSwitch"]]:
    """Build initial service switch entities from live or cached data."""
    rd = entry.runtime_data
    ctx = _SwitchContext(
        entry_id=entry.entry_id,
        service_coordinator=service_coordinator,
        api=rd.api,
        device_info=rd.device_info,
        event_stream=rd.event_stream,
    )

    live_services = service_coordinator.data.get("services", []) if service_coordinator.data else []
    cached_services = entry.data.get("cached_services", []) if not live_services else []
    services_source = live_services or cached_services

    entities = [
        OdioServiceSwitch(ctx, svc)
        for svc in services_source
        if svc.get("exists") and svc.get("scope") == "user"
    ]
    if live_services or cached_services:
        _LOGGER.debug(
            "Creating %d service switch entities (%s)",
            len(entities),
            "live" if live_services else "cached",
        )
    return ctx, entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote switch entities."""
    rd = entry.runtime_data
    entities: list[SwitchEntity] = []

    if rd.bluetooth_coordinator is not None:
        entities.append(
            OdioBluetoothSwitch(
                rd.bluetooth_coordinator,
                rd.api,
                entry.entry_id,
                rd.device_info,
                rd.event_stream,
            )
        )

    service_coordinator = rd.service_coordinator
    if service_coordinator is not None:
        ctx, service_switches = _build_service_switches(entry, service_coordinator)
        entities += service_switches

    async_add_entities(entities)

    if service_coordinator is None:
        return

    # -------------------------------------------------------------------------
    # Dynamic switch creation
    # Fires when service_coordinator first gets data after an API-down startup.
    # -------------------------------------------------------------------------
    known_switch_keys = {
        f"{e._service_info['scope']}/{e._service_info['name']}"
        for e in entities
        if isinstance(e, OdioServiceSwitch)
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
        self._event_stream = ctx.event_stream
        self._service_info = service_info

        service_name: str = service_info["name"]
        scope: str = service_info["scope"]

        self._attr_unique_id = f"{ctx.entry_id}_switch_{scope}_{service_name}"
        self._attr_name = service_name.removesuffix(".service")
        self._attr_device_info = ctx.device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

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
        """Return False when SSE is disconnected or coordinator has no data."""
        return (
            self._event_stream.sse_connected
            and self.coordinator.last_update_success
            and bool(self.coordinator.data)
        )

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


class OdioBluetoothSwitch(CoordinatorEntity[OdioBluetoothCoordinator], SwitchEntity):
    """Switch that powers the Bluetooth adapter on or off."""

    _attr_has_entity_name = True
    _attr_translation_key = "bluetooth_power"

    def __init__(
        self,
        coordinator: OdioBluetoothCoordinator,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
        event_stream: OdioEventStreamManager,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._event_stream = event_stream
        self._attr_unique_id = f"{entry_id}_bluetooth_power"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def icon(self) -> str:
        """Return icon based on power state."""
        return "mdi:bluetooth" if self.is_on else "mdi:bluetooth-off"

    @property
    def is_on(self) -> bool:
        """Return True when Bluetooth is powered on."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("powered", False)

    @property
    def available(self) -> bool:
        """Return False when SSE is disconnected or coordinator has no data."""
        return (
            self._event_stream.sse_connected
            and self.coordinator.last_update_success
            and bool(self.coordinator.data)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on Bluetooth adapter."""
        await self._api.bluetooth_power_up()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off Bluetooth adapter."""
        await self._api.bluetooth_power_down()
        await self.coordinator.async_refresh()
