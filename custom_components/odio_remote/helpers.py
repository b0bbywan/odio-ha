"""Helpers for Odio Remote integration."""
from __future__ import annotations

import logging
import socket
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyodio import OdioError

from .const import _MPRIS_BUS_PREFIX

_LOGGER = logging.getLogger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def extract_mpris_app_name(bus_name: str) -> str:
    """Extract application name from an MPRIS D-Bus bus name.

    Examples:
        "org.mpris.MediaPlayer2.mpd"                → "mpd"
        "org.mpris.MediaPlayer2.firefox.instance123" → "firefox"
    """
    if bus_name.startswith(_MPRIS_BUS_PREFIX):
        suffix = bus_name[len(_MPRIS_BUS_PREFIX):]
        return suffix.split(".")[0]
    return bus_name


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


def is_persistent_bt_device(state: Any) -> bool:
    """Return True for paired/bonded devices, which get their own switch."""
    return bool(state.paired or state.bonded)


def register_dynamic_entities(
    config_entry: ConfigEntry,
    subscribe: Callable[[Callable[[str, Any], None]], Callable[[], None]],
    *,
    select_key: Callable[[Any], str | None],
    factory: Callable[[Any], Entity],
    initial_keys: set[str],
    label: str,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add an entity when a new item appears in a hub namespace, deduped by key.

    ``subscribe`` is a namespace's ``on_change`` registrar; ``select_key``
    returns an item's dedup key when it warrants an entity, or None to skip.
    Callers needing extra side effects (e.g. MPRIS rebind) roll their own.
    """
    known = set(initial_keys)

    @callback
    def _handle_change(change: str, obj: Any) -> None:
        key = select_key(obj)
        if not key or key in known:
            return
        known.add(key)
        _LOGGER.info("Dynamically adding %s: %s", label, key)
        async_add_entities([factory(obj)])

    config_entry.async_on_unload(subscribe(_handle_change))


def api_command(
    func: Callable[_P, Coroutine[Any, Any, _R]],
) -> Callable[_P, Coroutine[Any, Any, _R]]:
    """Decorate an async entity action that calls the Odio API.

    Acts as the boundary between the Odio domain and Home Assistant:
    OdioError subtypes (raised by pyodio) are translated into
    HomeAssistantError so HA can surface meaningful errors to the user.

    Programming errors (TypeError, AttributeError, etc.) are intentionally
    not caught — they bubble up naturally and appear in HA logs as real bugs.
    """

    @wraps(func)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await func(*args, **kwargs)
        except HomeAssistantError:
            raise
        except OdioError as err:
            raise HomeAssistantError(str(err)) from err

    return wrapper
