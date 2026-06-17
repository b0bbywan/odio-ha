"""Select platform for Odio Remote — pair newly discovered Bluetooth devices."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioConfigEntry
from .helpers import api_command, is_persistent_bt_device
from .mixins import OdioBluetoothEntity

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote select entities."""
    rd = entry.runtime_data
    if rd.coordinators.bluetooth is None:
        return
    async_add_entities(
        [
            OdioBluetoothPairSelect(
                rd.coordinators.bluetooth,
                rd.api,
                entry.entry_id,
                rd.device_info,
                rd.event_stream,
            )
        ]
    )


class OdioBluetoothPairSelect(OdioBluetoothEntity, SelectEntity):
    """Select that connects (and thereby pairs) a freshly discovered BT device.

    Options are the devices seen during a scan that are not yet paired/bonded
    (paired/bonded devices already have their own connect/disconnect switch).
    Picking one issues a connect, which triggers BlueZ pairing; the device then
    becomes a persistent switch and drops out of this list. This is an action
    trigger, so it has no persistent selection (``current_option`` is None).
    """

    _attr_translation_key = "bluetooth_pair"
    _attr_icon = "mdi:bluetooth-connect"
    _unique_suffix = "bluetooth_pair"

    def _discovered_devices(self) -> list[dict[str, Any]]:
        """Return discovered devices that are not yet paired/bonded."""
        if not self.coordinator.data:
            return []
        return [
            device
            for device in self.coordinator.data.get("known_devices", [])
            if device.get("address") and not is_persistent_bt_device(device)
        ]

    @staticmethod
    def _label(device: dict[str, Any]) -> str:
        """Build an unambiguous option label for a discovered device."""
        address = device["address"]
        name = device.get("name")
        return f"{name} ({address})" if name else address

    @staticmethod
    def _address_from_option(option: str) -> str:
        """Extract the embedded MAC address (stable across name changes)."""
        if option.endswith(")") and "(" in option:
            return option[option.rfind("(") + 1 : -1]
        return option

    @property
    def options(self) -> list[str]:
        """Return the list of pairable (discovered, unpaired) device labels."""
        return [self._label(device) for device in self._discovered_devices()]

    @property
    def current_option(self) -> str | None:
        """No persistent selection — this is an action trigger."""
        return None

    def _has_data(self) -> bool:
        """Available only when at least one device is pairable."""
        return bool(self.options)

    @api_command
    async def async_select_option(self, option: str) -> None:
        """Connect (and pair) the chosen discovered device."""
        # Match on the embedded address, not the label, so a name resolving
        # between render and selection doesn't drop the pick.
        address = self._address_from_option(option)
        for device in self._discovered_devices():
            if device["address"] == address:
                await self._api.bluetooth_connect(address)
                await self.coordinator.async_refresh()
                return
        _LOGGER.warning("Bluetooth pair option no longer available: %s", option)
