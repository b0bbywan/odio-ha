"""Media player platform for Odio Remote."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .const import (
    _MPRIS_BUS_PREFIX,
    ATTR_CLIENT_ID,
    ATTR_APP,
    ATTR_BACKEND,
    ATTR_USER,
    ATTR_HOST,
    ATTR_CORKED,
    ATTR_SERVICE_SCOPE,
    ATTR_SERVICE_ENABLED,
    ATTR_SERVICE_ACTIVE,
)
from .coordinator import OdioAudioCoordinator, OdioMPRISCoordinator, OdioServiceCoordinator
from .event_stream import OdioEventStreamManager
from .helpers import api_command
from .mixins import MappedEntityMixin

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


def _extract_mpris_app_name(bus_name: str) -> str:
    """Extract application name from an MPRIS D-Bus bus name.

    Examples:
        "org.mpris.MediaPlayer2.mpd"                → "mpd"
        "org.mpris.MediaPlayer2.firefox.instance123" → "firefox"
    """
    if bus_name.startswith(_MPRIS_BUS_PREFIX):
        suffix = bus_name[len(_MPRIS_BUS_PREFIX):]
        return suffix.split(".")[0]
    return bus_name
# =============================================================================
# Platform context
# =============================================================================


@dataclass
class _MediaPlayerContext:
    """Shared setup state for media player platform helpers.

    Bundles all objects that entity constructors and setup callbacks need,
    avoiding long parameter lists and keeping the live coordinator accessible
    for closures that must derive values (e.g. hostname) at call time rather
    than at setup time.
    """

    entry_id: str
    event_stream: OdioEventStreamManager
    audio_coordinator: OdioAudioCoordinator | None
    service_coordinator: OdioServiceCoordinator | None
    mpris_coordinator: OdioMPRISCoordinator | None
    api: OdioApiClient
    device_info: DeviceInfo
    service_mappings: dict[str, str]
    backends: dict[str, bool]
    server_hostname: str | None


# =============================================================================
# Platform setup
# =============================================================================


def _build_service_entities(
    ctx: _MediaPlayerContext,
) -> list[MediaPlayerEntity]:
    """Build service media player entities from coordinator data."""
    entities: list[MediaPlayerEntity] = []
    if ctx.service_coordinator is None or not ctx.service_coordinator.data:
        return entities
    for service in ctx.service_coordinator.data.get("services", []):
        mapping_key = f"{service.get('scope', 'user')}/{service['name']}"
        if service.get("exists") and mapping_key in ctx.service_mappings:
            entities.append(OdioServiceMediaPlayer(ctx, service))
    return entities


def _build_remote_client_entities(
    ctx: _MediaPlayerContext,
) -> list[MediaPlayerEntity]:
    """Build standalone remote client entities from audio coordinator data."""
    entities: list[MediaPlayerEntity] = []
    if ctx.audio_coordinator is None or not ctx.audio_coordinator.data:
        return entities
    hostname = ctx.server_hostname
    for client in ctx.audio_coordinator.data.get("audio", []):
        client_name = client.get("name", "")
        client_host = client.get("host", "")
        if hostname and client_host and client_host != hostname and client_name:
            entities.append(OdioPulseClientMediaPlayer(ctx, client))
    return entities


def _build_mpris_entities(
    ctx: _MediaPlayerContext,
) -> list[MediaPlayerEntity]:
    """Build MPRIS media player entities from coordinator data."""
    entities: list[MediaPlayerEntity] = []
    if ctx.mpris_coordinator is None or not ctx.mpris_coordinator.data:
        return entities
    for player in ctx.mpris_coordinator.data.get("mpris", []):
        if player.get("bus_name") and player.get("available", True):
            entities.append(OdioMPRISMediaPlayer(ctx, player))
    return entities


def _register_dynamic_services(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for late-discovered service entities."""
    if ctx.service_coordinator is None:
        return
    service_coordinator = ctx.service_coordinator
    known_service_keys = {
        f"{e._service_info['scope']}/{e._service_info['name']}"
        for e in initial_entities
        if isinstance(e, OdioServiceMediaPlayer)
    }

    @callback
    def _async_check_new_services() -> None:
        if not service_coordinator.data:
            return
        new_entities: list[MediaPlayerEntity] = []
        for service in service_coordinator.data.get("services", []):
            mapping_key = f"{service.get('scope', 'user')}/{service['name']}"
            if (
                service.get("exists")
                and mapping_key in ctx.service_mappings
                and mapping_key not in known_service_keys
            ):
                new_entities.append(OdioServiceMediaPlayer(ctx, service))
                known_service_keys.add(mapping_key)
        if new_entities:
            _LOGGER.info(
                "Dynamically adding %d service entities after late API connection",
                len(new_entities),
            )
            async_add_entities(new_entities)

    config_entry.async_on_unload(
        service_coordinator.async_add_listener(_async_check_new_services)
    )


def _register_dynamic_clients(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for newly discovered remote audio clients."""
    if ctx.audio_coordinator is None:
        return
    audio_coordinator = ctx.audio_coordinator
    known_remote_clients = {
        entity._client_name: entity
        for entity in initial_entities
        if isinstance(entity, OdioPulseClientMediaPlayer)
    }

    @callback
    def _async_check_new_clients() -> None:
        hostname = ctx.server_hostname
        if not audio_coordinator.data or not hostname:
            return

        new_entities: list[MediaPlayerEntity] = []
        for client in audio_coordinator.data.get("audio", []):
            client_name = client.get("name", "")
            client_host = client.get("host", "")

            if not (client_host and client_host != hostname and client_name):
                continue
            if client_name in known_remote_clients:
                continue

            entity = OdioPulseClientMediaPlayer(ctx, client)
            new_entities.append(entity)
            known_remote_clients[client_name] = entity

        if new_entities:
            _LOGGER.info(
                "Adding %d new remote client entities", len(new_entities)
            )
            async_add_entities(new_entities)

    config_entry.async_on_unload(
        audio_coordinator.async_add_listener(_async_check_new_clients)
    )


def _register_dynamic_mpris(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for newly discovered MPRIS players."""
    if ctx.mpris_coordinator is None:
        return
    mpris_coordinator = ctx.mpris_coordinator
    known_mpris_players: dict[str, OdioMPRISMediaPlayer] = {
        entity._player_name: entity
        for entity in initial_entities
        if isinstance(entity, OdioMPRISMediaPlayer)
    }

    @callback
    def _async_check_new_mpris_players() -> None:
        if not mpris_coordinator.data:
            return
        new_entities: list[MediaPlayerEntity] = []
        for player in mpris_coordinator.data.get("mpris", []):
            bus_name = player.get("bus_name")
            if not bus_name or bus_name in known_mpris_players:
                continue
            if not player.get("available", True):
                continue
            entity = OdioMPRISMediaPlayer(ctx, player)
            new_entities.append(entity)
            known_mpris_players[bus_name] = entity
        if new_entities:
            _LOGGER.info("Adding %d new MPRIS player entities", len(new_entities))
            async_add_entities(new_entities)

    config_entry.async_on_unload(
        mpris_coordinator.async_add_listener(_async_check_new_mpris_players)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote media player based on a config entry."""
    rd = config_entry.runtime_data
    server_info = config_entry.data.get("server_info", {})
    ctx = _MediaPlayerContext(
        entry_id=config_entry.entry_id,
        event_stream=rd.event_stream,
        audio_coordinator=rd.audio_coordinator,
        service_coordinator=rd.service_coordinator,
        mpris_coordinator=rd.mpris_coordinator,
        api=rd.api,
        device_info=rd.device_info,
        service_mappings=rd.service_mappings,
        backends=server_info.get("backends", {}),
        server_hostname=server_info.get("hostname"),
    )

    entities: list[MediaPlayerEntity] = [OdioReceiverMediaPlayer(ctx)]
    entities += _build_service_entities(ctx)
    entities += _build_remote_client_entities(ctx)
    entities += _build_mpris_entities(ctx)

    _LOGGER.info(
        "Creating %d media_player entities (1 receiver + %d services + %d standalone clients + %d mpris)",
        len(entities),
        len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioPulseClientMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioMPRISMediaPlayer)]),
    )
    async_add_entities(entities)

    _register_dynamic_services(config_entry, ctx, async_add_entities, entities)
    _register_dynamic_clients(config_entry, ctx, async_add_entities, entities)
    _register_dynamic_mpris(config_entry, ctx, async_add_entities, entities)


# =============================================================================
# Entities
# =============================================================================


class OdioReceiverMediaPlayer(MediaPlayerEntity):
    """Representation of the main Odio Remote receiver (the Odio instance)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, ctx: _MediaPlayerContext) -> None:
        """Initialize the receiver."""
        self._event_stream = ctx.event_stream
        self._backends = ctx.backends
        self._audio_coordinator = ctx.audio_coordinator
        self._service_coordinator = ctx.service_coordinator
        self._api_client = ctx.api
        self._attr_unique_id = f"{ctx.entry_id}_receiver"
        self._attr_device_info = ctx.device_info

    async def async_added_to_hass(self) -> None:
        """Register listeners on available coordinators."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self._handle_coordinator_update)
        )
        if self._audio_coordinator is not None:
            self.async_on_remove(
                self._audio_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )
        if self._service_coordinator is not None:
            self.async_on_remove(
                self._service_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinators."""
        self.async_write_ha_state()

    def _get_backends(self) -> dict[str, bool]:
        """Return backends dict (static, from server_info fetched at setup)."""
        return self._backends

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if not self._event_stream.sse_connected:
            return MediaPlayerState.OFF

        if self._audio_coordinator is None:
            return MediaPlayerState.OFF

        if not self._audio_coordinator.last_update_success:
            return MediaPlayerState.OFF

        backends = self._get_backends()
        if "pulseaudio" not in backends or self._audio_coordinator is None:
            return MediaPlayerState.OFF

        audio_data = self._audio_coordinator.data
        if audio_data is None:
            return MediaPlayerState.OFF

        clients = audio_data.get("audio", [])
        has_active_client = any(not c.get("corked", True) for c in clients)
        return MediaPlayerState.PLAYING if has_active_client else MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = MediaPlayerEntityFeature(0)
        if self._get_backends().get("pulseaudio"):
            features |= (
                MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_MUTE
                | MediaPlayerEntityFeature.SELECT_SOURCE
            )
        return features

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        if self._audio_coordinator is None or not self._audio_coordinator.data:
            return None
        clients = self._audio_coordinator.data.get("audio", [])
        volumes = [client.get("volume", 0) for client in clients]
        if volumes:
            return sum(volumes) / len(volumes)
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        if self._audio_coordinator is None or not self._audio_coordinator.data:
            return False
        clients = self._audio_coordinator.data.get("audio", [])
        return any(client.get("muted", False) for client in clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "backends": self._get_backends(),
        }
        if self._audio_coordinator is not None and self._audio_coordinator.data:
            clients = self._audio_coordinator.data.get("audio", [])
            attrs["active_clients"] = len(clients)
            attrs["playing_clients"] = len([
                c for c in clients if not c.get("corked", True)
            ])
        return attrs

    def _get_outputs(self) -> list[dict[str, Any]]:
        """Return the outputs list from the audio coordinator."""
        if self._audio_coordinator is None or not self._audio_coordinator.data:
            return []
        return self._audio_coordinator.data.get("outputs", [])

    @property
    def source_list(self) -> list[str] | None:
        """Return the list of available audio outputs."""
        outputs = self._get_outputs()
        if not outputs:
            return None
        return [o.get("description") or o.get("name", "") for o in outputs]

    @property
    def source(self) -> str | None:
        """Return the current default audio output."""
        for o in self._get_outputs():
            if o.get("default"):
                return o.get("description") or o.get("name")
        return None

    async def async_select_source(self, source: str) -> None:
        """Set the default audio output."""
        for o in self._get_outputs():
            label = o.get("description") or o.get("name", "")
            if label == source:
                await self._api_client.set_output_default(o["name"])
                return

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._api_client.set_server_volume(volume)

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._api_client.set_server_mute(mute)


class OdioServiceMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Odio Remote service using MappedEntityMixin.

    A service entity is a simple ON/OFF wrapper around a systemd service.
    It has no native media capabilities — playback state, volume, and media
    metadata are all delegated to the mapped entity via MappedEntityMixin.
    """

    _attr_has_entity_name = True

    def __init__(self, ctx: _MediaPlayerContext, service_info: dict[str, Any]) -> None:
        """Initialize the service."""
        assert ctx.service_coordinator is not None
        super().__init__(ctx.service_coordinator)
        self._event_stream = ctx.event_stream
        self._api_client = ctx.api
        self._service_info = service_info

        service_name = service_info["name"]
        scope = service_info["scope"]

        self._attr_unique_id = f"{ctx.entry_id}_service_{scope}_{service_name}"
        self._attr_name = f"{service_name} ({scope})"
        self._attr_device_info = ctx.device_info

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"{self._service_info['scope']}/{self._service_info['name']}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return False when the SSE stream is disconnected."""
        return self._event_stream.sse_connected and super().available

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._is_service_running)
        if mapped_state is not None:
            return mapped_state

        if not self._is_service_running():
            return MediaPlayerState.OFF

        return MediaPlayerState.IDLE

    def _is_service_running(self) -> bool:
        """Check if the service is running."""
        if self.coordinator.data:
            for svc in self.coordinator.data.get("services", []):
                if (
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
                ):
                    return svc.get("running", False)
        return False

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
        )
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return self._get_mapped_attribute("volume_level")

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        return self._get_mapped_attribute("is_volume_muted") or False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            ATTR_SERVICE_SCOPE: self._service_info["scope"],
            ATTR_SERVICE_ENABLED: self._service_info.get("enabled", False),
        }
        if self.coordinator.data:
            for svc in self.coordinator.data.get("services", []):
                if (
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
                ):
                    attrs[ATTR_SERVICE_ACTIVE] = svc.get("active_state")
                    attrs["running"] = svc.get("running", False)
                    break
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        return attrs

    @api_command
    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning on service %s/%s", scope, unit)
        await self._api_client.control_service("enable", scope, unit)
        await asyncio.sleep(1)
        await self.coordinator.async_request_refresh()

    @api_command
    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning off service %s/%s", scope, unit)
        await self._api_client.control_service("disable", scope, unit)
        await asyncio.sleep(1)
        await self.coordinator.async_request_refresh()

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._delegate_to_hass("volume_set", {"volume_level": volume})

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._delegate_to_hass("volume_mute", {"is_volume_muted": mute})


class OdioPulseClientMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of a standalone audio client using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _MediaPlayerContext, initial_client: dict[str, Any]) -> None:
        """Initialize the standalone client."""
        assert ctx.audio_coordinator is not None
        super().__init__(ctx.audio_coordinator)
        self._api_client = ctx.api
        self._event_stream = ctx.event_stream
        self._server_hostname_value = ctx.server_hostname

        self._client_name = initial_client.get("name", "")
        self._client_host = initial_client.get("host", "")

        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._client_name.lower()).strip("_")
        self._attr_unique_id = f"{ctx.entry_id}_remote_{safe_name}"
        self._attr_name = self._client_name
        self._attr_device_info = ctx.device_info

        _LOGGER.debug(
            "Created standalone client entity for '%s' from host '%s' with unique_id '%s'",
            self._client_name,
            self._client_host,
            self._attr_unique_id,
        )

    @property
    def _server_hostname(self) -> str | None:
        """Return the server hostname (static, from server_info fetched at setup)."""
        return self._server_hostname_value

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"client:{self._client_name}"

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._get_current_client)
        if mapped_state is not None:
            return mapped_state
        client = self._get_current_client()
        if not client:
            return MediaPlayerState.OFF
        if not client.get("corked", True):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.VOLUME_SET
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume
        client = self._get_current_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted
        client = self._get_current_client()
        if client:
            return client.get("muted", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        client = self._get_current_client()
        attrs = {
            "client_name": self._client_name,
            "remote_host": self._client_host,
            "server_hostname": self._server_hostname,
        }
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        if not client:
            attrs["status"] = "disconnected"
            return attrs
        attrs["status"] = "connected"
        attrs[ATTR_CLIENT_ID] = client.get("id")
        attrs[ATTR_APP] = client.get("app")
        attrs[ATTR_BACKEND] = client.get("backend")
        attrs[ATTR_USER] = client.get("user")
        attrs[ATTR_HOST] = client.get("host")
        attrs[ATTR_CORKED] = client.get("corked")
        props = client.get("props", {})
        if "native-protocol.peer" in props:
            attrs["connection"] = props["native-protocol.peer"]
        if "application.process.host" in props:
            attrs["remote_host"] = props["application.process.host"]
        if "application.version" in props:
            attrs["app_version"] = props["application.version"]
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return False when the SSE stream is disconnected."""
        return self._event_stream.sse_connected

    def _get_current_client(self) -> dict[str, Any] | None:
        """Get the current client data from coordinator by NAME."""
        if not self.coordinator.data:
            return None
        for client in self.coordinator.data.get("audio", []):
            if client.get("name") == self._client_name:
                return client
        return None

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._set_volume_with_fallback(volume, get_client_name, self._api_client)

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._mute_with_fallback(mute, get_client_name, self._api_client)


class OdioMPRISMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """MPRIS media player entity with full native MPRIS support."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _MediaPlayerContext, player: dict[str, Any]) -> None:
        """Initialize the MPRIS media player."""
        assert ctx.mpris_coordinator is not None
        super().__init__(ctx.mpris_coordinator)
        self._api_client = ctx.api
        self._event_stream = ctx.event_stream

        self._player_name = player.get("bus_name", "")

        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._player_name.lower()).strip("_")
        self._attr_unique_id = f"{ctx.entry_id}_mpris_{safe_name}"
        self._attr_device_info = ctx.device_info

        identity = player.get("identity", "")
        if identity:
            self._attr_name = identity
        else:
            self._attr_name = _extract_mpris_app_name(self._player_name).replace("_", " ").title()

        _LOGGER.debug(
            "Initialized MPRIS player: unique_id=%s, name=%s, bus_name=%s",
            self._attr_unique_id,
            self._attr_name,
            self._player_name,
        )

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"mpris:{self._player_name}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return True if the player is reported by the coordinator and not removed."""
        player = self._player_data
        return self._event_stream.sse_connected and self.coordinator.last_update_success and player is not None and player.get("available", True)

    @property
    def _player_data(self) -> dict[str, Any] | None:
        """Get current player data from coordinator."""
        if not self.coordinator.data:
            return None
        for player in self.coordinator.data.get("mpris", []):
            if player.get("bus_name") == self._player_name:
                return player
        return None

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        if not self.available:
            return MediaPlayerState.OFF

        player = self._player_data
        if not player:
            return MediaPlayerState.OFF

        playback_status = player.get("playback_status", "")
        if playback_status == "Playing":
            return MediaPlayerState.PLAYING
        elif playback_status == "Paused":
            return MediaPlayerState.PAUSED
        else:
            return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features based on MPRIS capabilities and mapped entity."""
        player = self._player_data
        mapped_features = self._get_mapped_attribute("supported_features")

        features = MediaPlayerEntityFeature(0)

        if player:
            caps = player.get("capabilities", {})
            if caps.get("can_play"):
                features |= MediaPlayerEntityFeature.PLAY
            if caps.get("can_pause"):
                features |= MediaPlayerEntityFeature.PAUSE
            if caps.get("can_control"):
                features |= MediaPlayerEntityFeature.STOP
            if caps.get("can_go_next"):
                features |= MediaPlayerEntityFeature.NEXT_TRACK
            if caps.get("can_go_previous"):
                features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
            if caps.get("can_seek"):
                features |= MediaPlayerEntityFeature.SEEK
            if caps.get("can_control") and player.get("volume") is not None:
                features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
            if player.get("shuffle") is not None:
                features |= MediaPlayerEntityFeature.SHUFFLE_SET
            if player.get("loop_status") is not None:
                features |= MediaPlayerEntityFeature.REPEAT_SET

        return self._get_supported_features(features, mapped_features)

    # Media properties — native MPRIS data overrides mixin delegation

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        player = self._player_data
        if player:
            return player.get("volume")
        return None

    @property
    def media_content_type(self) -> str:
        """Content type of current playing media."""
        return MediaType.MUSIC

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        player = self._player_data
        if player and player.get("metadata"):
            length_us = player["metadata"].get("mpris:length")
            if length_us is not None:
                return int(length_us) // 1_000_000
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        player = self._player_data
        if player:
            position_us = player.get("position")
            if position_us is not None:
                return int(position_us / 1_000_000)
        return None

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        player = self._player_data
        if player:
            return player.get("position_updated_at")
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        player = self._player_data
        if player and player.get("metadata"):
            return player["metadata"].get("xesam:title")
        return None

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        player = self._player_data
        if player and player.get("metadata"):
            artists = player["metadata"].get("xesam:artist")
            if isinstance(artists, list) and artists:
                return ", ".join(artists)
            elif isinstance(artists, str):
                return artists
        return None

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        player = self._player_data
        if player and player.get("metadata"):
            return player["metadata"].get("xesam:album")
        return None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media (http/https only)."""
        player = self._player_data
        if player and player.get("metadata"):
            url = player["metadata"].get("mpris:artUrl", "")
            if url.startswith(("http://", "https://")):
                return url
        return None

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        player = self._player_data
        if player:
            return player.get("shuffle")
        return None

    @property
    def repeat(self) -> RepeatMode | None:
        """Return current repeat mode."""
        player = self._player_data
        if player:
            loop_status = player.get("loop_status")
            if loop_status == "None":
                return RepeatMode.OFF
            elif loop_status == "Track":
                return RepeatMode.ONE
            elif loop_status == "Playlist":
                return RepeatMode.ALL
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        player = self._player_data
        if not player:
            return {}

        caps = player.get("capabilities", {})
        attrs = {
            "player_name": self._player_name,
            "identity": player.get("identity"),
            "desktop_entry": player.get("desktop_entry"),
            "playback_status": player.get("playback_status"),
            "can_control": caps.get("can_control"),
            "can_play": caps.get("can_play"),
            "can_pause": caps.get("can_pause"),
            "can_seek": caps.get("can_seek"),
            "can_go_next": caps.get("can_go_next"),
            "can_go_previous": caps.get("can_go_previous"),
        }
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        return attrs

    # Media control — MPRIS API first if capability exists, else delegate to mapped entity

    @api_command
    async def async_media_play(self) -> None:
        """Send play command."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_play"):
            _LOGGER.debug("MPRIS play: %s", self._player_name)
            await self._api_client.player_play(self._player_name)
            return
        await self._delegate_to_hass("media_play")

    @api_command
    async def async_media_pause(self) -> None:
        """Send pause command."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_pause"):
            _LOGGER.debug("MPRIS pause: %s", self._player_name)
            await self._api_client.player_pause(self._player_name)
            return
        await self._delegate_to_hass("media_pause")

    @api_command
    async def async_media_stop(self) -> None:
        """Send stop command."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_control"):
            _LOGGER.debug("MPRIS stop: %s", self._player_name)
            await self._api_client.player_stop(self._player_name)
            return
        await self._delegate_to_hass("media_stop")

    @api_command
    async def async_media_next_track(self) -> None:
        """Send next track command."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_go_next"):
            _LOGGER.debug("MPRIS next: %s", self._player_name)
            await self._api_client.player_next(self._player_name)
            return
        await self._delegate_to_hass("media_next_track")

    @api_command
    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_go_previous"):
            _LOGGER.debug("MPRIS previous: %s", self._player_name)
            await self._api_client.player_previous(self._player_name)
            return
        await self._delegate_to_hass("media_previous_track")

    @api_command
    async def async_media_seek(self, position: float) -> None:
        """Seek to position (in seconds)."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_seek"):
            _LOGGER.debug("MPRIS seek to %s: %s", position, self._player_name)
            position_us = int(position * 1_000_000)
            track_id = (player.get("metadata") or {}).get("mpris:trackid", "/")
            await self._api_client.player_set_position(self._player_name, track_id, position_us)
            return
        await self._delegate_to_hass("media_seek", {"seek_position": position})

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0..1)."""
        player = self._player_data
        if player and player.get("capabilities", {}).get("can_control") and player.get("volume") is not None:
            _LOGGER.debug("MPRIS set volume %s: %s", volume, self._player_name)
            await self._api_client.player_set_volume(self._player_name, volume)
            return
        await self._delegate_to_hass("volume_set", {"volume_level": volume})

    @api_command
    async def async_volume_up(self) -> None:
        """Volume up by 5%."""
        current = self.volume_level
        if current is not None:
            await self.async_set_volume_level(min(1.0, current + 0.05))

    @api_command
    async def async_volume_down(self) -> None:
        """Volume down by 5%."""
        current = self.volume_level
        if current is not None:
            await self.async_set_volume_level(max(0.0, current - 0.05))

    @api_command
    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle mode."""
        player = self._player_data
        if player and player.get("shuffle") is not None:
            _LOGGER.debug("MPRIS set shuffle %s: %s", shuffle, self._player_name)
            await self._api_client.player_set_shuffle(self._player_name, shuffle)
            return
        await self._delegate_to_hass("shuffle_set", {"shuffle": shuffle})

    @api_command
    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        player = self._player_data
        if player and player.get("loop_status") is not None:
            _LOGGER.debug("MPRIS set repeat %s: %s", repeat, self._player_name)
            if repeat == RepeatMode.OFF:
                loop_status = "None"
            elif repeat == RepeatMode.ONE:
                loop_status = "Track"
            elif repeat == RepeatMode.ALL:
                loop_status = "Playlist"
            else:
                loop_status = "None"
            await self._api_client.player_set_loop(self._player_name, loop_status)
            return
        await self._delegate_to_hass("repeat_set", {"repeat": repeat})
