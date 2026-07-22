"""Sensor platform for Odio Remote."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Set up Odio Remote sensor entities."""
    rd = entry.runtime_data
    backends = rd.server_info.backends
    entities: list[SensorEntity] = []

    if backends.pulseaudio:
        entities.append(
            OdioDefaultOutputSensor(rd.hub, entry.entry_id, rd.device_info)
        )
    if backends.bluetooth:
        entities.append(
            OdioBluetoothConnectedDeviceSensor(rd.hub, entry.entry_id, rd.device_info)
        )

    if entities:
        async_add_entities(entities)


class OdioDefaultOutputSensor(OdioEntity, SensorEntity):
    """Sensor reporting the description of the default audio output."""

    _attr_translation_key = "default_output"
    _attr_icon = "mdi:speaker"
    _unique_suffix = "default_output"

    def _change_sources(self) -> tuple:
        return (self._hub.audio.on_change,)

    @property
    def native_value(self) -> str | None:
        """Return the description of the default audio output, or None."""
        output = self._hub.audio.default_output
        if output is None:
            return None
        return output.description or output.name

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes of the default audio output."""
        output = self._hub.audio.default_output
        if output is None:
            return None
        return {
            k: v for k, v in asdict(output.state).items()
            if k not in ("default", "props")
        }


class OdioBluetoothConnectedDeviceSensor(OdioBluetoothEntity, SensorEntity):
    """Sensor reporting the name of the connected Bluetooth device."""

    _attr_translation_key = "bluetooth_connected_device"
    _attr_icon = "mdi:bluetooth-audio"
    _unique_suffix = "bluetooth_connected_device"

    @property
    def native_value(self) -> str:
        """Return the name of the first connected Bluetooth device, or 'none'."""
        connected = self._hub.bluetooth.connected_devices
        if connected:
            return connected[0].name
        return "none"
