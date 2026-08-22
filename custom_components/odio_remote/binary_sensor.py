"""Binary sensor platform for Odio Remote."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioConfigEntry
from .entity import OdioBluetoothEntity, OdioEntity

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote binary sensor entities."""
    rd = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        ConnectionStatusSensor(rd.hub, entry.entry_id, rd.device_info)
    ]
    if rd.server_info.backends.bluetooth:
        entities.append(
            OdioBluetoothPairingActiveSensor(rd.hub, entry.entry_id, rd.device_info)
        )
    async_add_entities(entities)


class ConnectionStatusSensor(OdioEntity, BinarySensorEntity):
    """Binary sensor reporting SSE connectivity for the Odio device."""

    _attr_translation_key = "connection_status"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unique_suffix = "connectivity"

    @property
    def available(self) -> bool:
        """Always available — this sensor reports the connectivity itself."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the SSE stream is connected."""
        return self._hub.connected


class OdioBluetoothPairingActiveSensor(OdioBluetoothEntity, BinarySensorEntity):
    """Binary sensor reporting whether Bluetooth pairing mode is active."""

    _attr_translation_key = "bluetooth_pairing_active"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unique_suffix = "bluetooth_pairing_active"

    @property
    def is_on(self) -> bool:
        """Return True when Bluetooth pairing mode is active."""
        return self._hub.bluetooth.pairing_active
