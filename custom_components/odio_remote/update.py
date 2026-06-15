"""Update platform for Odio Remote (software upgrades)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .coordinator import OdioUpgradeCoordinator
from .helpers import api_command

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote update entity."""
    rd = entry.runtime_data
    if rd.coordinators.upgrade is None:
        return
    async_add_entities(
        [
            OdioUpdateEntity(
                rd.coordinators.upgrade,
                rd.api,
                entry.entry_id,
                rd.device_info,
                rd.server_info.api_version,
            )
        ]
    )


class OdioUpdateEntity(CoordinatorEntity[OdioUpgradeCoordinator], UpdateEntity):
    """Update entity backed by the Odio upgrade detector."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        coordinator: OdioUpgradeCoordinator,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
        fallback_version: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._fallback_version = fallback_version
        self._attr_unique_id = f"{entry_id}_firmware_update"
        self._attr_device_info = device_info

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Expose PROGRESS always; INSTALL only when the server allows starting.

        ``can_upgrade`` is reported by the detector and gates whether
        ``POST /upgrade/start`` is available (e.g. disabled while a run is
        already in progress or when the deployment forbids it).
        """
        features = UpdateEntityFeature.PROGRESS
        if (self.coordinator.data or {}).get("can_upgrade"):
            features |= UpdateEntityFeature.INSTALL
        return features

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed version."""
        data = self.coordinator.data or {}
        return data.get("current") or self._fallback_version

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version.

        When no upgrade is available, mirror the installed version so HA reports
        the device as up to date. When one *is* available we never mirror
        installed — that would make ``latest == installed`` and HA would report
        "up to date", masking the update. If the detector flagged an upgrade
        without naming a target, return ``None`` (HA shows "unknown") rather than
        a false match.
        """
        data = self.coordinator.data or {}
        if data.get("upgrade_available"):
            return data.get("latest")
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        """Return True while an upgrade run is active."""
        return bool((self.coordinator.data or {}).get("in_progress"))

    @property
    def update_percentage(self) -> int | None:
        """Return the upgrade progress percentage, if known."""
        if not self.in_progress:
            return None
        return (self.coordinator.data or {}).get("percent")

    @api_command
    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Start the upgrade process."""
        await self._api.upgrade_start()
