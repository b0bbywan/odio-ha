"""The Odio Remote integration."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .api_client import OdioApiClient
from .event_stream import OdioEventStreamManager
from .exceptions import OdioError
from .helpers import extract_mpris_app_name
from .models import PowerCapabilities, ServerInfo, StartupData
from .const import (
    CONF_API_URL,
    CONF_KEEPALIVE_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DOMAIN,
    SSE_EVENT_AUDIO_OUTPUT_REMOVED,
    SSE_EVENT_AUDIO_OUTPUT_UPDATED,
    SSE_EVENT_AUDIO_REMOVED,
    SSE_EVENT_AUDIO_UPDATED,
    SSE_EVENT_BLUETOOTH_UPDATED,
    SSE_EVENT_PLAYER_UPDATED,
    SSE_EVENT_PLAYER_ADDED,
    SSE_EVENT_PLAYER_REMOVED,
    SSE_EVENT_PLAYER_POSITION,
    SSE_EVENT_SERVICE_UPDATED,
)
from .coordinator import OdioAudioCoordinator, OdioBluetoothCoordinator, OdioMPRISCoordinator, OdioServiceCoordinator
from .helpers import async_get_mac_from_ip

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class OdioCoordinators:
    """Groups the four optional SSE-driven coordinators."""

    audio: OdioAudioCoordinator | None = None
    service: OdioServiceCoordinator | None = None
    bluetooth: OdioBluetoothCoordinator | None = None
    mpris: OdioMPRISCoordinator | None = None

    def refresh_all(self, hass: HomeAssistant) -> None:
        """Schedule async_refresh on every active coordinator."""
        for coord in (self.audio, self.service, self.bluetooth, self.mpris):
            if coord is not None:
                hass.async_create_task(coord.async_refresh())


@dataclass
class OdioRemoteRuntimeData:
    """Runtime data for the Odio Remote integration."""

    api: OdioApiClient
    device_info: DeviceInfo
    server_info: ServerInfo
    coordinators: OdioCoordinators
    event_stream: OdioEventStreamManager
    service_mappings: dict[str, str]
    power_capabilities: PowerCapabilities


type OdioConfigEntry = ConfigEntry[OdioRemoteRuntimeData]


async def _resolve_mac(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api_url: str,
) -> str | None:
    """Resolve MAC address via device_tracker; fall back to cached value."""
    host = urlparse(api_url).hostname
    mac = await async_get_mac_from_ip(hass, host) if host else None
    if mac:
        _LOGGER.debug("Resolved MAC for %s: %s", host, mac)
        if mac != entry.data.get("mac"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "mac": mac}
            )
    else:
        mac = entry.data.get("mac")
        if mac:
            _LOGGER.debug("Using cached MAC for %s: %s", host, mac)
        else:
            _LOGGER.warning(
                "MAC address not resolved for %s — 'Connected via' link unavailable",
                host,
            )
    return mac


async def _setup_audio_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioAudioCoordinator:
    """Create audio coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioAudioCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_UPDATED, coordinator.handle_sse_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_REMOVED, coordinator.handle_sse_remove_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_OUTPUT_UPDATED, coordinator.handle_sse_output_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_AUDIO_OUTPUT_REMOVED, coordinator.handle_sse_output_remove_event
        )
    )
    _LOGGER.debug("Audio coordinator created (pulseaudio backend enabled)")
    return coordinator


async def _setup_service_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioServiceCoordinator:
    """Create service coordinator, refresh, cache services, and wire SSE listeners."""
    coordinator = OdioServiceCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    if coordinator.data:
        services = coordinator.data.get("services", [])
        if services != entry.data.get("cached_services"):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "cached_services": services}
            )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_SERVICE_UPDATED, coordinator.handle_sse_event
        )
    )
    _LOGGER.debug("Service coordinator created (systemd backend enabled)")
    return coordinator


async def _setup_mpris_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioMPRISCoordinator:
    """Create MPRIS coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioMPRISCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_UPDATED, coordinator.handle_sse_update_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_ADDED, coordinator.handle_sse_update_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_REMOVED, coordinator.handle_sse_removed_event
        )
    )
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_PLAYER_POSITION, coordinator.handle_sse_position_event
        )
    )
    _LOGGER.debug("MPRIS coordinator created (mpris backend enabled)")
    return coordinator


async def _setup_bluetooth_coordinator(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    api: OdioApiClient,
    event_stream: OdioEventStreamManager,
) -> OdioBluetoothCoordinator:
    """Create bluetooth coordinator, refresh, and wire SSE listeners."""
    coordinator = OdioBluetoothCoordinator(hass, entry, api)
    await coordinator.async_refresh()
    entry.async_on_unload(
        event_stream.async_add_event_listener(
            SSE_EVENT_BLUETOOTH_UPDATED, coordinator.handle_sse_event
        )
    )
    _LOGGER.debug("Bluetooth coordinator created (bluetooth backend enabled)")
    return coordinator


async def async_setup_entry(hass: HomeAssistant, entry: OdioConfigEntry) -> bool:
    """Set up Odio Remote from a config entry."""
    _LOGGER.info("Setting up Odio Remote integration")

    api_url = entry.data[CONF_API_URL]
    keepalive_interval = entry.options.get(CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL)
    service_mappings = entry.options.get(CONF_SERVICE_MAPPINGS, {})

    _LOGGER.debug(
        "Configuration: api_url=%s, keepalive_interval=%s",
        api_url,
        keepalive_interval,
    )
    _LOGGER.debug("Service mappings: %s", service_mappings)

    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    # Fetch server_info + power capabilities once at startup — static, never polled again.
    try:
        startup = await StartupData.fetch(api)
    except OdioError:
        startup = StartupData.from_cache(entry.data)
        _LOGGER.warning(
            "API unreachable at startup — using cached data (backends: %s)",
            startup.server_info.backends,
        )
    startup.cache(hass, entry)
    server_info = startup.server_info
    backends = server_info.backends
    _LOGGER.debug("Detected backends: %s", backends)

    # Build SSE backends list from server capabilities.
    sse_backends: list[str] = []
    if backends.get("pulseaudio"):
        sse_backends.append("audio")
    if backends.get("systemd"):
        sse_backends.append("systemd")
    if backends.get("power"):
        sse_backends.append("power")
    if backends.get("bluetooth"):
        sse_backends.append("bluetooth")
    if backends.get("mpris"):
        sse_backends.append("mpris")

    event_stream = OdioEventStreamManager(
        hass=hass,
        api=api,
        backends=sse_backends,
        keepalive_interval=keepalive_interval,
    )

    mac = await _resolve_mac(hass, entry, api_url)
    device_connections: set[tuple[str, str]] = (
        {(CONNECTION_NETWORK_MAC, mac)} if mac else set()
    )

    # Build DeviceInfo once — shared by all platforms so every entity stays
    # consistent regardless of which platform registers first.
    hostname = server_info.hostname or entry.entry_id
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=device_connections,
        name=f"Odio Remote ({hostname})",
        manufacturer="Odio",
        sw_version=server_info.api_version,
        hw_version=server_info.os_version,
        configuration_url=f"{api_url}/ui",
    )

    coordinators = OdioCoordinators(
        audio=await _setup_audio_coordinator(hass, entry, api, event_stream)
        if backends.get("pulseaudio") else None,
        service=await _setup_service_coordinator(hass, entry, api, event_stream)
        if backends.get("systemd") else None,
        mpris=await _setup_mpris_coordinator(hass, entry, api, event_stream)
        if backends.get("mpris") else None,
        bluetooth=await _setup_bluetooth_coordinator(hass, entry, api, event_stream)
        if backends.get("bluetooth") else None,
    )

    # Re-fetch coordinator data on SSE reconnect to avoid stale state.
    def _on_sse_reconnect() -> None:
        if not event_stream.sse_connected:
            return
        coordinators.refresh_all(hass)

    entry.async_on_unload(event_stream.async_add_listener(_on_sse_reconnect))

    entry.runtime_data = OdioRemoteRuntimeData(
        api=api,
        device_info=device_info,
        server_info=server_info,
        coordinators=coordinators,
        event_stream=event_stream,
        service_mappings=service_mappings,
        power_capabilities=startup.power,
    )

    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    event_stream.start()

    _LOGGER.info("Odio Remote integration setup complete")
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.event_stream.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: OdioConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device from the integration."""
    return True


_MPRIS_OLD_BUS_SAFE_PREFIX = "org_mpris_mediaplayer2_"
# Match `_instance` followed by at least one digit/underscore (the real D-Bus
# instance-suffix shapes: `instance123`, `instance_1_52`). Requiring [\d_]+
# avoids over-stripping legitimate app names that happen to contain or end
# with `_instance` (e.g. an app literally named `foo_instance`).
_MPRIS_INSTANCE_RE = re.compile(r"^(.+?)(?:_instance[\d_]+)?$")
_HA_SUFFIX_RE = re.compile(r"_(\d+)$")


def _pick_keeper(
    ents: list["er.RegistryEntry"], new_uid: str
) -> "er.RegistryEntry":
    """Pick which entry of a same-app group survives the migration.

    Priority:
      1. An entry already on the target uid — no rename runs, so no collision.
      2. The canonical entity_id of the group: the one that is a strict prefix
         (followed by `_<digits>`) of every other entry. Survives apps whose
         name itself ends in `_<digits>` (e.g. `vlc_3`).
      3. Fall back to the orphan with the lowest HA-added numeric suffix —
         sorted as integers so `_2` beats `_10`.
    """
    already_migrated = next((e for e in ents if e.unique_id == new_uid), None)
    if already_migrated is not None:
        return already_migrated

    def _is_canonical(candidate: "er.RegistryEntry") -> bool:
        base = candidate.entity_id
        for other in ents:
            if other is candidate:
                continue
            if not re.fullmatch(rf"{re.escape(base)}_\d+", other.entity_id):
                return False
        return True

    canonical = next((e for e in ents if _is_canonical(e)), None)
    if canonical is not None:
        return canonical

    def _trailing_int(e: "er.RegistryEntry") -> int:
        m = _HA_SUFFIX_RE.search(e.entity_id)
        return int(m.group(1)) if m else 0

    return min(ents, key=lambda e: (_trailing_int(e), e.entity_id))


def _migrate_mpris_unique_ids(hass: HomeAssistant, entry: OdioConfigEntry) -> None:
    """Collapse per-instance MPRIS entries into one stable entry per app.

    Old unique_id encoded the full D-Bus bus_name (including the volatile
    `.instanceXXX` suffix), so every Firefox/Chrome restart leaked a new
    orphan entity. New format is `<entry_id>_mpris_<safe_app_name>`.

    Pre-existing new-format entries (e.g. from a beta or a partially-applied
    earlier migration pass) are folded into the same group so the rename
    cannot collide on `async_update_entity`.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_mpris_"

    by_app: dict[str, list[er.RegistryEntry]] = {}
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not ent.unique_id.startswith(prefix):
            continue
        suffix = ent.unique_id[len(prefix):]
        if suffix.startswith(_MPRIS_OLD_BUS_SAFE_PREFIX):
            tail = suffix[len(_MPRIS_OLD_BUS_SAFE_PREFIX):]
            match = _MPRIS_INSTANCE_RE.match(tail)
            if not match:
                continue
            app = match.group(1)
        else:
            # Already in the new `<entry>_mpris_<app>` format.
            app = suffix
        by_app.setdefault(app, []).append(ent)

    for app, ents in by_app.items():
        new_uid = f"{prefix}{app}"
        keeper = _pick_keeper(ents, new_uid)
        for orphan in ents:
            if orphan is keeper:
                continue
            _LOGGER.info(
                "Removing orphan MPRIS entity %s (unique_id=%s)",
                orphan.entity_id,
                orphan.unique_id,
            )
            registry.async_remove(orphan.entity_id)
        if keeper.unique_id != new_uid:
            _LOGGER.info(
                "Migrating MPRIS unique_id for %s: %s → %s",
                keeper.entity_id,
                keeper.unique_id,
                new_uid,
            )
            try:
                registry.async_update_entity(
                    keeper.entity_id, new_unique_id=new_uid
                )
            except ValueError:
                # Defensive: a stray entity outside this group also holds the
                # target uid. Drop the keeper rather than fail the whole entry
                # setup; the other entity wins.
                _LOGGER.warning(
                    "Cannot migrate %s to %s (uid already in use); removing",
                    keeper.entity_id,
                    new_uid,
                )
                registry.async_remove(keeper.entity_id)


def _migrate_mpris_service_mappings(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> None:
    """Rewrite MPRIS keys in entry.options[CONF_SERVICE_MAPPINGS].

    Old keys encoded the full D-Bus bus_name (`mpris:org.mpris.MediaPlayer2.
    firefox.instance_1_52`); they broke on every browser restart. New keys
    use the extracted app name (`mpris:firefox`), matching the stable form
    now produced by `OdioMPRISMediaPlayer._mapping_key`.
    """
    options: dict[str, Any] = dict(entry.options or {})
    mappings = options.get(CONF_SERVICE_MAPPINGS) or {}
    if not mappings:
        return

    new_mappings: dict[str, str] = {}
    changed = False
    for key, target in mappings.items():
        if not key.startswith("mpris:"):
            new_mappings[key] = target
            continue
        bus_name = key[len("mpris:"):]
        new_key = f"mpris:{extract_mpris_app_name(bus_name)}"
        if new_key != key:
            changed = True
            _LOGGER.info("Migrating MPRIS mapping key: %s → %s", key, new_key)
        # Collisions (e.g. two firefox bus_names mapping to different targets)
        # resolve to the last write — the user can re-pick in the options flow.
        new_mappings[new_key] = target

    if changed:
        hass.config_entries.async_update_entry(
            entry, options={**options, CONF_SERVICE_MAPPINGS: new_mappings}
        )


async def async_migrate_entry(hass: HomeAssistant, entry: OdioConfigEntry) -> bool:
    """Migrate old config entries."""
    _LOGGER.debug("Migrating Odio config entry from version %s", entry.version)
    if entry.version > 2:
        return False
    if entry.version < 2:
        _migrate_mpris_unique_ids(hass, entry)
        _migrate_mpris_service_mappings(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
    return True
