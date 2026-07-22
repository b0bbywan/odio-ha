"""Base entities backed by the pyodio hub."""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from pyodio import OdioHub


class OdioEntity(Entity):
    """Base for hub-backed entities: connectivity-aware availability + change subscriptions.

    Subclasses set ``_unique_suffix`` (class attr, or instance attr before
    calling ``super().__init__``), override ``_change_sources`` to subscribe
    to hub namespaces, ``_relevant_change`` to filter notifications, and
    ``_has_data`` for their own availability gate.
    """

    _attr_has_entity_name = True
    _unique_suffix: str = ""

    def __init__(self, hub: OdioHub, entry_id: str, device_info: DeviceInfo) -> None:
        self._hub = hub
        self._attr_unique_id = f"{entry_id}_{self._unique_suffix}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._hub.on_connection_change(self._handle_connection_change))
        for subscribe in self._change_sources():
            self.async_on_remove(subscribe(self._handle_hub_change))

    def _change_sources(self) -> tuple[Callable[[Callable[[str, Any], None]], Callable[[], None]], ...]:
        """Hub ``on_change`` registrars this entity listens to."""
        return ()

    @callback
    def _handle_connection_change(self, connected: bool) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_hub_change(self, change: str, obj: Any) -> None:
        if self._relevant_change(change, obj):
            self.async_write_ha_state()

    def _relevant_change(self, change: str, obj: Any) -> bool:
        """Filter hub notifications; default reacts to everything."""
        return True

    @property
    def available(self) -> bool:
        return self._hub.connected and self._has_data()

    def _has_data(self) -> bool:
        """Entity-specific availability gate."""
        return True


class OdioBluetoothEntity(OdioEntity):
    """Base for Bluetooth entities bound to ``hub.bluetooth``."""

    def _change_sources(self) -> tuple:
        return (self._hub.bluetooth.on_change,)

    def _has_data(self) -> bool:
        return self._hub.bluetooth.state is not None
