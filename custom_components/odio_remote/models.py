"""Domain models for Odio Remote startup data."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .api_client import OdioApiClient
    from . import OdioConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class ServerInfo:
    """Static server information fetched once at startup."""

    hostname: str = ""
    backends: dict[str, bool] = field(default_factory=dict)
    api_version: str | None = None
    os_version: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerInfo:
        return cls(
            hostname=data.get("hostname", ""),
            backends=data.get("backends", {}),
            api_version=data.get("api_version"),
            os_version=data.get("os_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "backends": self.backends,
            "api_version": self.api_version,
            "os_version": self.os_version,
        }


@dataclass
class PowerCapabilities:
    """Power capabilities fetched once at startup (requires power backend)."""

    power_off: bool = False
    reboot: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PowerCapabilities:
        return cls(
            power_off=data.get("power_off", False),
            reboot=data.get("reboot", False),
        )

    def to_dict(self) -> dict[str, bool]:
        return {"power_off": self.power_off, "reboot": self.reboot}


@dataclass
class StartupData:
    """Combined startup data: server info + power capabilities."""

    server_info: ServerInfo
    power: PowerCapabilities

    @classmethod
    async def fetch(cls, api: OdioApiClient) -> StartupData:
        """Fetch from API. Raises if server_info fails; soft-fails for power caps."""
        server_info = ServerInfo.from_dict(await api.get_server_info())
        power = PowerCapabilities()
        if server_info.backends.get("power"):
            try:
                power = PowerCapabilities.from_dict(await api.get_power_capabilities())
            except Exception:
                _LOGGER.warning("Power capabilities unavailable — assuming none")
        return cls(server_info=server_info, power=power)

    @classmethod
    def from_cache(cls, entry_data: Mapping[str, Any]) -> StartupData:
        """Build from cached entry data."""
        return cls(
            server_info=ServerInfo.from_dict(entry_data.get("server_info", {})),
            power=PowerCapabilities.from_dict(entry_data.get("power_capabilities", {})),
        )

    def cache(self, hass: HomeAssistant, entry: OdioConfigEntry) -> None:
        """Persist to entry.data if values have changed."""
        si_dict = self.server_info.to_dict()
        power_dict = self.power.to_dict()
        updates: dict[str, Any] = {}
        if si_dict != entry.data.get("server_info"):
            updates["server_info"] = si_dict
        if power_dict != entry.data.get("power_capabilities"):
            updates["power_capabilities"] = power_dict
        if updates:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **updates}
            )
