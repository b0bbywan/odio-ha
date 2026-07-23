"""Startup data cache for Odio Remote, backed by pyodio models."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pyodio import OdioHub, PowerCapabilities, ServerInfo

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from . import OdioConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class StartupData:
    """Server info + power capabilities, persisted for API-down startups."""

    server_info: ServerInfo
    power: PowerCapabilities

    @classmethod
    def from_hub(cls, hub: OdioHub) -> StartupData:
        """Snapshot a connected hub."""
        return cls(
            server_info=hub.server,
            power=hub.power.capabilities or PowerCapabilities(),
        )

    @classmethod
    def from_cache(cls, entry_data: Mapping[str, Any]) -> StartupData:
        """Build from cached entry data."""
        return cls(
            server_info=ServerInfo.from_dict(entry_data.get("server_info", {})),
            power=PowerCapabilities.from_dict(entry_data.get("power_capabilities", {})),
        )

    def cache(self, hass: HomeAssistant, entry: OdioConfigEntry) -> None:
        """Persist to entry.data if values have changed."""
        si_dict = asdict(self.server_info)
        power_dict = asdict(self.power)
        updates: dict[str, Any] = {}
        if si_dict != entry.data.get("server_info"):
            updates["server_info"] = si_dict
        if power_dict != entry.data.get("power_capabilities"):
            updates["power_capabilities"] = power_dict
        if updates:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **updates}
            )
