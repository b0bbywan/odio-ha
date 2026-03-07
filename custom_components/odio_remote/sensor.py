"""Sensor platform for Odio Remote."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .coordinator import OdioAudioCoordinator, OdioBluetoothCoordinator

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote sensor entities."""
    rd = entry.runtime_data
    entities: list[SensorEntity] = []

    if rd.coordinators.audio is not None:
        entities.append(
            OdioDefaultOutputSensor(
                rd.coordinators.audio,
                entry.entry_id,
                rd.device_info,
            )
        )

    if rd.coordinators.bluetooth is not None:
        entities.append(
            OdioBluetoothConnectedDeviceSensor(
                rd.coordinators.bluetooth,
                entry.entry_id,
                rd.device_info,
            )
        )

    if entities:
        async_add_entities(entities)


class OdioDefaultOutputSensor(
    CoordinatorEntity[OdioAudioCoordinator], SensorEntity
):
    """Sensor reporting the description of the default audio output."""

    _attr_translation_key = "default_output"
    _attr_icon = "mdi:speaker"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OdioAudioCoordinator,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_default_output"
        self._attr_device_info = device_info

    def _get_default_output(self) -> dict[str, Any] | None:
        """Return the default output dict, or None."""
        if not self.coordinator.data:
            return None
        for output in self.coordinator.data.get("outputs", []):
            if output.get("default"):
                return output
        return None

    @property
    def native_value(self) -> str | None:
        """Return the description of the default audio output, or None."""
        output = self._get_default_output()
        if output is None:
            return None
        return output.get("description") or output.get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes of the default audio output."""
        output = self._get_default_output()
        if output is None:
            return None
        return {
            k: v for k, v in output.items()
            if k not in ("default", "props")
        }


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
