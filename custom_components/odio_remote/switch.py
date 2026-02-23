"""Switch platform for Odio Remote — start/stop user-scope systemd services."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .const import DOMAIN
from .coordinator import OdioServiceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote switch entities."""
    runtime_data = entry.runtime_data
    service_coordinator = runtime_data.service_coordinator

    if service_coordinator is None or not service_coordinator.data:
        return

    server_hostname = runtime_data.server_info.get("hostname", entry.entry_id)
    services = service_coordinator.data.get("services", [])

    entities = [
        OdioServiceSwitch(
            service_coordinator,
            runtime_data.api,
            entry.entry_id,
            svc,
            server_hostname,
        )
        for svc in services
        if svc.get("exists") and svc.get("scope") == "user"
    ]

    _LOGGER.debug("Creating %d service switch entities", len(entities))
    async_add_entities(entities)


class OdioServiceSwitch(CoordinatorEntity[OdioServiceCoordinator], SwitchEntity):
    """Switch that starts/stops a user-scope systemd service."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OdioServiceCoordinator,
        api: OdioApiClient,
        entry_id: str,
        service_info: dict[str, Any],
        server_hostname: str,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._service_info = service_info

        service_name: str = service_info["name"]
        scope: str = service_info["scope"]

        self._attr_unique_id = f"{entry_id}_switch_{scope}_{service_name}"
        self._attr_name = service_name.removesuffix(".service")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"Odio Remote ({server_hostname})",
            manufacturer="Odio",
        )

    @property
    def is_on(self) -> bool:
        """Return True when the service is running."""
        if not self.coordinator.data:
            return False
        for svc in self.coordinator.data.get("services", []):
            if svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]:
                return svc.get("running", False)
        return False

    @property
    def available(self) -> bool:
        """Return False when the coordinator has no data."""
        return self.coordinator.last_update_success and bool(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the service."""
        await self._api.control_service(
            "start", self._service_info["scope"], self._service_info["name"]
        )
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the service."""
        await self._api.control_service(
            "stop", self._service_info["scope"], self._service_info["name"]
        )
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()
