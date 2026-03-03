"""Sensor platform for Odio Remote."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .coordinator import OdioBluetoothCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote sensor entities."""
    rd = entry.runtime_data
    if rd.bluetooth_coordinator is None:
        return

    async_add_entities([
        OdioBluetoothConnectedDeviceSensor(
            rd.bluetooth_coordinator,
            entry.entry_id,
            rd.device_info,
        )
    ])


class OdioBluetoothConnectedDeviceSensor(
    CoordinatorEntity[OdioBluetoothCoordinator], SensorEntity
):
    """Sensor reporting the name of the connected Bluetooth device."""

    _attr_translation_key = "bluetooth_connected_device"
    _attr_icon = "mdi:bluetooth-audio"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OdioBluetoothCoordinator,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_bluetooth_connected_device"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str:
        """Return the name of the first connected Bluetooth device, or 'none'."""
        if not self.coordinator.data:
            return "none"
        for device in self.coordinator.data.get("known_devices", []):
            if device.get("connected"):
                return device.get("name")
        return "none"
