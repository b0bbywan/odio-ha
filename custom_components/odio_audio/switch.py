"""Switch platform for Odio Audio integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api_client import OdioApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio service switches from a config entry."""
    coordinator_data = hass.data[DOMAIN][entry.entry_id]
    service_coordinator = coordinator_data["service_coordinator"]
    api: OdioApiClient = coordinator_data["api"]
    device_info = coordinator_data["device_info"]

    # Get services from coordinator data
    services = service_coordinator.data.get("services", [])

    _LOGGER.debug("Setting up switches for %d services", len(services))

    # Create switch entities for user services only
    entities = []
    for service in services:
        scope = service.get("scope", "")
        unit = service.get("unit", "")

        # Only create switches for user services
        if scope == "user":
            _LOGGER.debug("Creating switch for service: %s/%s", scope, unit)
            entities.append(
                OdioServiceSwitch(
                    service_coordinator,
                    api,
                    service,
                    device_info,
                    entry.entry_id,
                )
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d service switch entities", len(entities))
    else:
        _LOGGER.debug("No user services found to create switches")


class OdioServiceSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for controlling systemd user services."""

    def __init__(
        self,
        coordinator,
        api: OdioApiClient,
        service: dict[str, Any],
        device_info: DeviceInfo,
        entry_id: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._api = api
        self._service_scope = service.get("scope", "user")
        self._service_unit = service.get("name", "")
        self._entry_id = entry_id
        self._attr_device_info = device_info

        # Generate unique_id and entity_id
        sanitized_unit = self._service_unit.replace(".service", "").replace("@", "_").replace(".", "_")
        self._attr_unique_id = f"{entry_id}_switch_{self._service_scope}_{sanitized_unit}"
        self._attr_name = sanitized_unit.replace("_", " ").title()

        _LOGGER.debug(
            "Initialized switch: unique_id=%s, name=%s, service=%s/%s",
            self._attr_unique_id,
            self._attr_name,
            self._service_scope,
            self._service_unit,
        )

    @property
    def _service_data(self) -> dict[str, Any] | None:
        """Get current service data from coordinator."""
        services = self.coordinator.data.get("services", [])
        for service in services:
            if service.get("scope") == self._service_scope and service.get("name") == self._service_unit:
                return service
        return None

    @property
    def is_on(self) -> bool:
        """Return true if the service is active."""
        service = self._service_data
        if not service:
            return False

        # Service is "on" if it's running (active_state == "active")
        active_state = service.get("active_state", "inactive")
        return active_state == "active"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._service_data is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        service = self._service_data
        if not service:
            return {}

        return {
            "scope": service.get("scope"),
            "unit": service.get("unit"),
            "enabled": service.get("enabled"),
            "active_state": service.get("active_state"),
            "sub_state": service.get("sub_state"),
            "load_state": service.get("load_state"),
        }

    async def _control_service(self, action: str) -> None:
        """Control the service and refresh state."""
        service_id = f"{self._service_scope}/{self._service_unit}"
        _LOGGER.info("%s service: %s", action.capitalize(), service_id)
        try:
            await self._api.control_service(
                action,
                self._service_scope,
                self._service_unit,
            )
        except aiohttp.ClientResponseError as err:
            raise HomeAssistantError(
                f"Failed to {action} {service_id}: HTTP {err.status}"
            ) from err
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                f"Cannot reach API to {action} {service_id}: {err}"
            ) from err
        await asyncio.sleep(1.0)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the service on (start)."""
        await self._control_service("start")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the service off (stop)."""
        await self._control_service("stop")
