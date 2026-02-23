"""Button platform for Odio Remote (power off / reboot)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import OdioAudioConfigEntry
from .api_client import OdioApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioAudioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote button entities."""
    caps = entry.runtime_data.power_capabilities
    server_info = entry.runtime_data.server_info
    api = entry.runtime_data.api
    entry_id = entry.entry_id

    entities: list[ButtonEntity] = []
    if caps.get("power_off"):
        entities.append(OdioPowerOffButton(api, entry_id, server_info))
    if caps.get("reboot"):
        entities.append(OdioRebootButton(api, entry_id, server_info))

    async_add_entities(entities)


class _OdioPowerButtonBase(ButtonEntity):
    """Base class for Odio power buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        api: OdioApiClient,
        entry_id: str,
        server_info: dict[str, Any],
    ) -> None:
        self._api = api
        hostname = server_info.get("hostname", entry_id)
        sw_version = server_info.get("api_version")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"Odio Remote ({hostname})",
            manufacturer="Odio",
            sw_version=sw_version,
        )


class OdioPowerOffButton(_OdioPowerButtonBase):
    """Button that powers off the Odio device."""

    _attr_device_class = None
    _attr_translation_key = "power_off"

    def __init__(
        self,
        api: OdioApiClient,
        entry_id: str,
        server_info: dict[str, Any],
    ) -> None:
        super().__init__(api, entry_id, server_info)
        self._attr_unique_id = f"{entry_id}_power_off"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._api.power_off()


class OdioRebootButton(_OdioPowerButtonBase):
    """Button that reboots the Odio device."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_translation_key = "reboot"

    def __init__(
        self,
        api: OdioApiClient,
        entry_id: str,
        server_info: dict[str, Any],
    ) -> None:
        super().__init__(api, entry_id, server_info)
        self._attr_unique_id = f"{entry_id}_reboot"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._api.reboot()
