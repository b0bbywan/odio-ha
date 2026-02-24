"""Helpers for Odio Remote integration."""
from __future__ import annotations

import functools
import logging
import socket

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _mac_from_device_trackers(hass: HomeAssistant, ip: str) -> str | None:
    """Search device_tracker entities for a MAC matching the given IP.

    Router integrations (UniFi, Fritz!Box, etc.) expose MAC addresses via
    device_tracker entities — the same source used by HA's DHCP discovery
    component. Works regardless of Docker networking mode.
    """
    for state in hass.states.async_all("device_tracker"):
        if state.attributes.get("ip") == ip:
            mac = state.attributes.get("mac")
            if mac:
                _LOGGER.debug(
                    "Found MAC %s for %s via device tracker %s",
                    mac, ip, state.entity_id,
                )
                return mac
    return None


async def async_get_mac_from_ip(hass: HomeAssistant, ip: str) -> str | None:
    """Resolve MAC address for a host.

    Tries two strategies in order:
    1. ARP cache via getmac — works when HA has L2 visibility (host networking).
    2. device_tracker entities — works when a router integration is configured
       (UniFi, Fritz!Box, etc.), including Docker bridge mode.

    Returns None if neither strategy resolves the MAC.
    """
    _LOGGER.debug("Resolving MAC address for host: %s", ip)
    try:
        resolved = await hass.async_add_executor_job(socket.gethostbyname, ip)
        _LOGGER.debug("Resolved %s → %s", ip, resolved)
    except Exception as err:
        _LOGGER.debug("DNS resolution failed for %s: %s", ip, err)
        return None

    # Strategy 1: ARP cache
    try:
        from getmac import get_mac_address  # noqa: PLC0415

        mac = await hass.async_add_executor_job(
            functools.partial(get_mac_address, ip=resolved)
        )
        _LOGGER.debug("get_mac_address returned %r for %s (%s)", mac, ip, resolved)
        if mac:
            return mac
    except Exception as err:
        _LOGGER.debug("ARP MAC resolution failed for %s: %s", ip, err)

    # Strategy 2: device_tracker entities (router integrations)
    return _mac_from_device_trackers(hass, resolved)
