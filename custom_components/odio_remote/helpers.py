"""Helpers for Odio Remote integration."""
from __future__ import annotations

import logging
import socket

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_get_mac_from_ip(hass: HomeAssistant, ip: str) -> str | None:
    """Resolve MAC address for a host via device_tracker entities.

    Router integrations (UniFi, Fritz!Box, etc.) expose the real NIC MAC via
    device_tracker entities regardless of Docker networking mode. ARP is not
    used because it returns the Docker bridge MAC instead of the real NIC MAC
    when HA runs in Docker bridge mode.

    Returns None if no matching device_tracker entity is found.
    """
    _LOGGER.debug("Resolving MAC address for host: %s", ip)
    try:
        resolved = await hass.async_add_executor_job(socket.gethostbyname, ip)
        _LOGGER.debug("Resolved %s → %s", ip, resolved)
    except Exception as err:
        _LOGGER.debug("DNS resolution failed for %s: %s", ip, err)
        return None

    for state in hass.states.async_all("device_tracker"):
        if state.attributes.get("ip") == resolved:
            mac = state.attributes.get("mac")
            if mac:
                _LOGGER.debug(
                    "Found MAC %s for %s via device tracker %s",
                    mac, resolved, state.entity_id,
                )
                return mac

    _LOGGER.debug("No device_tracker entity found for %s (%s)", ip, resolved)
    return None
