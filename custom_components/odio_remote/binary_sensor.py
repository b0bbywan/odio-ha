"""Binary sensor platform for Odio Remote."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .coordinator import OdioConnectivityCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote binary sensor entities."""
    runtime_data = entry.runtime_data
    async_add_entities([
        ConnectionStatusSensor(
            runtime_data.connectivity_coordinator,
            entry.entry_id,
            runtime_data.device_info,
        )
    ])


class ConnectionStatusSensor(CoordinatorEntity[OdioConnectivityCoordinator], BinarySensorEntity):
    """Binary sensor reporting API connectivity for the Odio device."""

    _attr_translation_key = "connection_status"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: OdioConnectivityCoordinator,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_connectivity"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        """Return True when the API is reachable."""
        return self.coordinator.last_update_success

    @property
    def available(self) -> bool:
        """The sensor itself is always available — it reports connectivity, not state."""
        return True
