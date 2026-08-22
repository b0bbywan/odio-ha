"""Button platform for Odio Remote (power off / reboot / Bluetooth pairing)."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioConfigEntry
from .entity import OdioEntity
from .helpers import api_command

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote button entities."""
    rd = entry.runtime_data
    caps = rd.power_capabilities

    entities: list[ButtonEntity] = []
    if caps.power_off:
        entities.append(OdioPowerOffButton(rd.hub, entry.entry_id, rd.device_info))
    if caps.reboot:
        entities.append(OdioRebootButton(rd.hub, entry.entry_id, rd.device_info))
    if rd.server_info.backends.bluetooth:
        entities.append(OdioBluetoothPairingButton(rd.hub, entry.entry_id, rd.device_info))

    async_add_entities(entities)


class OdioPowerOffButton(OdioEntity, ButtonEntity):
    """Button that powers off the Odio device."""

    _attr_device_class = None
    _attr_translation_key = "power_off"
    _attr_icon = "mdi:power"
    _unique_suffix = "power_off"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.power.power_off()


class OdioRebootButton(OdioEntity, ButtonEntity):
    """Button that reboots the Odio device."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_translation_key = "reboot"
    _unique_suffix = "reboot"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.power.reboot()


class OdioBluetoothPairingButton(OdioEntity, ButtonEntity):
    """Button that triggers Bluetooth pairing mode (60s server-side timeout)."""

    _attr_device_class = None
    _attr_translation_key = "bluetooth_pairing"
    _attr_icon = "mdi:bluetooth-connect"
    _unique_suffix = "bluetooth_pairing"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.bluetooth.pairing_mode()
