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
    """Set up Odio Remote update entity."""
    rd = entry.runtime_data
    if not rd.server_info.backends.upgrade:
        return
    async_add_entities(
        [
            OdioUpdateEntity(
                rd.hub,
                entry.entry_id,
                rd.device_info,
                rd.server_info.api_version,
            )
        ]
    )


class OdioUpdateEntity(OdioEntity, UpdateEntity):
    """Update entity backed by the Odio upgrade detector."""

    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _unique_suffix = "firmware_update"

    def __init__(self, hub: Any, entry_id: str, device_info: Any, fallback_version: str | None) -> None:
        super().__init__(hub, entry_id, device_info)
        self._fallback_version = fallback_version

    def _change_sources(self) -> tuple:
        return (self._hub.upgrade.on_change,)

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Expose PROGRESS always; INSTALL only when the server allows starting.

        ``can_upgrade`` is reported by the detector and gates whether
        ``POST /upgrade/start`` is available (e.g. disabled while a run is
        already in progress or when the deployment forbids it).
        """
        features = UpdateEntityFeature.PROGRESS
        status = self._hub.upgrade.status
        if status is not None and status.can_upgrade:
            features |= UpdateEntityFeature.INSTALL
        return features

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed version."""
        return self._hub.upgrade.current_version or self._fallback_version

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
        if self._hub.upgrade.available:
            return self._hub.upgrade.latest_version or None
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        """Return True while an upgrade run is active."""
        return self._hub.upgrade.in_progress

    @property
    def update_percentage(self) -> int | None:
        """Return the upgrade progress percentage, if known."""
        if not self.in_progress:
            return None
        return self._hub.upgrade.progress_percent

    @api_command
    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Start the upgrade process."""
        await self._hub.upgrade.start()
