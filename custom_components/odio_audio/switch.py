"""Switch platform for Odio Audio integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _build_services_device_info(
    hostname: str,
    api_version: str,
    api_url: str,
    os_version: str,
) -> DeviceInfo:
    """Build device info for Services device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{hostname}_services")},
        name=f"Odio Services ({hostname})",
        manufacturer="Odio",
        model="Service Controller",
        model_id="systemd",
        sw_version=api_version,
        hw_version=os_version,
        configuration_url=api_url,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio service switches from a config entry."""
    data = entry.runtime_data
    service_coordinator = data.service_coordinator
    api: OdioApiClient = data.api
    server_info = data.server_info

    # Build services device info
    hostname = server_info.get("hostname", "unknown")
    api_version = server_info.get("api_version", "unknown")
    os_version = server_info.get("os_version", "unknown")
    api_url = api._api_url

    services_device_info = _build_services_device_info(
        hostname,
        api_version,
        api_url,
        os_version,
    )

    # Get services from coordinator data
    if not service_coordinator or not service_coordinator.data:
        _LOGGER.debug("No service coordinator data available, skipping switches")
        return

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
                    services_device_info,
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

    _attr_has_entity_name = True

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

        # Extract hostname from device_info identifiers for unique_id
        hostname = "unknown"
        for domain, identifier in device_info.get("identifiers", set()):
            if domain == DOMAIN and identifier.endswith("_services"):
                hostname = identifier.replace("_services", "")
                break

        # Generate unique_id and entity_id
        # Example: switch.odio_netflix for firefox-kiosk@www.netflix.com.service
        sanitized_unit = self._service_unit.replace(".service", "").replace("@", "_").replace(".", "_")
        self._attr_unique_id = f"{hostname}_switch_{self._service_scope}_{sanitized_unit}"
        # Just use the service name, no prefix
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the service on (start)."""
        _LOGGER.info("Starting service: %s/%s", self._service_scope, self._service_unit)
        try:
            await self._api.control_service(
                "start",
                self._service_scope,
                self._service_unit,
            )
            # Wait for state to update
            await asyncio.sleep(1.0)
            await self.coordinator.async_request_refresh()
            # Additional delay to let coordinator update
            await asyncio.sleep(0.5)
        except Exception as err:
            _LOGGER.error(
                "Failed to start service %s/%s: %s",
                self._service_scope,
                self._service_unit,
                err,
            )
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the service off (stop)."""
        _LOGGER.info("Stopping service: %s/%s", self._service_scope, self._service_unit)
        try:
            await self._api.control_service(
                "stop",
                self._service_scope,
                self._service_unit,
            )
            # Wait for state to update
            await asyncio.sleep(1.0)
            await self.coordinator.async_request_refresh()
            # Additional delay to let coordinator update
            await asyncio.sleep(0.5)
        except Exception as err:
            _LOGGER.error(
                "Failed to stop service %s/%s: %s",
                self._service_scope,
                self._service_unit,
                err,
            )
            raise
