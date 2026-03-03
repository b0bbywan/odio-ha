"""Binary sensor platform for Odio Remote."""
from __future__ import annotations

import logging
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioConfigEntry
from .event_stream import OdioEventStreamManager

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
            runtime_data.event_stream,
            entry.entry_id,
            runtime_data.device_info,
        )
    ])


class ConnectionStatusSensor(BinarySensorEntity):
    """Binary sensor reporting SSE connectivity for the Odio device."""

    _attr_translation_key = "connection_status"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_available = True

    def __init__(
        self,
        event_stream: OdioEventStreamManager,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self._event_stream = event_stream
        self._attr_unique_id = f"{entry_id}_connectivity"
        self._attr_device_info = device_info
        self._unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._unsub = self._event_stream.async_add_listener(
            self._handle_connectivity_change
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def _handle_connectivity_change(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True when the SSE stream is connected."""
        return self._event_stream.sse_connected
