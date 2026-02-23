"""Helpers for Odio Remote integration."""
from __future__ import annotations

import functools
import logging
import socket

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_get_mac_from_ip(hass: HomeAssistant, ip: str) -> str | None:
    """Resolve MAC address from the system ARP cache.

    Uses getmac (an HA core dependency) to look up the MAC for the given
    IP/hostname. Runs in the executor to avoid blocking the event loop.
    Returns None if the MAC cannot be resolved (ARP miss, different subnet,
    getmac unavailable, etc.).
    """
    _LOGGER.debug("Resolving MAC address for host: %s", ip)
    try:
        from getmac import get_mac_address  # noqa: PLC0415

        resolved = await hass.async_add_executor_job(socket.gethostbyname, ip)
        _LOGGER.debug("Resolved %s → %s", ip, resolved)

        mac = await hass.async_add_executor_job(
            functools.partial(get_mac_address, ip=resolved)
        )
        _LOGGER.debug("get_mac_address returned %r for %s (%s)", mac, ip, resolved)
        return mac if mac else None
    except Exception as err:
        _LOGGER.debug("MAC resolution failed for %s: %s", ip, err)
        return None
