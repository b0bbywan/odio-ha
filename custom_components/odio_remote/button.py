"""Button platform for Odio Remote (power off / reboot)."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .event_stream import OdioEventStreamManager
from .helpers import api_command

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote button entities."""
    caps = entry.runtime_data.power_capabilities
    api = entry.runtime_data.api
    entry_id = entry.entry_id
    device_info = entry.runtime_data.device_info
    event_stream = entry.runtime_data.event_stream

    entities: list[ButtonEntity] = []
    if caps.power_off:
        entities.append(OdioPowerOffButton(event_stream, api, entry_id, device_info))
    if caps.reboot:
        entities.append(OdioRebootButton(event_stream, api, entry_id, device_info))
    if entry.runtime_data.coordinators.bluetooth is not None:
        entities.append(OdioBluetoothPairingButton(event_stream, api, entry_id, device_info))

    async_add_entities(entities)


class _OdioPowerButtonBase(ButtonEntity):
    """Base class for Odio power buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        event_stream: OdioEventStreamManager,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self._event_stream = event_stream
        self._api = api
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return True when the SSE stream is connected."""
        return self._event_stream.sse_connected


class OdioPowerOffButton(_OdioPowerButtonBase):
    """Button that powers off the Odio device."""

    _attr_device_class = None
    _attr_translation_key = "power_off"
    _attr_icon = "mdi:power"

    def __init__(
        self,
        event_stream: OdioEventStreamManager,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(event_stream, api, entry_id, device_info)
        self._attr_unique_id = f"{entry_id}_power_off"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._api.power_off()


class OdioRebootButton(_OdioPowerButtonBase):
    """Button that reboots the Odio device."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_translation_key = "reboot"

    def __init__(
        self,
        event_stream: OdioEventStreamManager,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(event_stream, api, entry_id, device_info)
        self._attr_unique_id = f"{entry_id}_reboot"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._api.reboot()


class OdioBluetoothPairingButton(_OdioPowerButtonBase):
    """Button that triggers Bluetooth pairing mode (60s server-side timeout)."""

    _attr_device_class = None
    _attr_translation_key = "bluetooth_pairing"
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(
        self,
        event_stream: OdioEventStreamManager,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(event_stream, api, entry_id, device_info)
        self._attr_unique_id = f"{entry_id}_bluetooth_pairing"

    @api_command
    async def async_press(self) -> None:
        """Handle the button press."""
        await self._api.bluetooth_pairing_mode()
