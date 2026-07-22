"""Media player platform for Odio Remote."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyodio import (
    ADDED,
    AudioClient,
    AudioClientState,
    Backends,
    OdioHub,
    Player,
    Service,
    ServiceState,
)

from . import OdioConfigEntry
from .const import (
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
from .entity import OdioEntity
from .helpers import (
    api_command,
    extract_mpris_app_name,
    register_dynamic_entities,
)
from .mixins import MappedEntityMixin

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Platform context
# =============================================================================


@dataclass
class _MediaPlayerContext:
    """Shared setup state for media player platform helpers."""

    entry_id: str
    hub: OdioHub
    device_info: DeviceInfo
    service_mappings: dict[str, str]
    backends: Backends
    server_hostname: str | None


def _is_remote_client(ctx: _MediaPlayerContext, state: AudioClientState) -> bool:
    """Whether an audio client comes from another host than the odio server."""
    hostname = ctx.server_hostname
    return bool(hostname and state.host and state.host != hostname and state.name)


# =============================================================================
# Platform setup
# =============================================================================


def _build_service_entities(ctx: _MediaPlayerContext) -> list[MediaPlayerEntity]:
    """Build service media player entities for mapped services."""
    return [
        OdioServiceMediaPlayer(ctx, service.state)
        for service in ctx.hub.services.values()
        if service.state.exists and service.state.key in ctx.service_mappings
    ]


def _build_remote_client_entities(ctx: _MediaPlayerContext) -> list[MediaPlayerEntity]:
    """Build standalone remote client entities from the hub's audio clients."""
    return [
        OdioPulseClientMediaPlayer(ctx, client.state)
        for client in ctx.hub.audio.clients.values()
        if _is_remote_client(ctx, client.state)
    ]


def _build_mpris_entities(ctx: _MediaPlayerContext) -> list[MediaPlayerEntity]:
    """Build MPRIS media player entities from the hub's players.

    Deduplicates by app name so multi-instance players (e.g. Chrome) produce
    only one entity.
    """
    entities: list[MediaPlayerEntity] = []
    seen_app_names: set[str] = set()
    for player in ctx.hub.players.values():
        if not player.bus_name or not player.available:
            continue
        app_name = extract_mpris_app_name(player.bus_name)
        if app_name in seen_app_names:
            continue
        seen_app_names.add(app_name)
        entities.append(OdioMPRISMediaPlayer(ctx, player))
    return entities


def _register_dynamic_services(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for late-discovered service entities."""

    def _select_key(obj: Any) -> str | None:
        if not isinstance(obj, Service):
            return None
        key = obj.state.key
        if obj.state.exists and key in ctx.service_mappings:
            return key
        return None

    register_dynamic_entities(
        config_entry,
        ctx.hub.services.on_change,
        select_key=_select_key,
        factory=lambda service: OdioServiceMediaPlayer(ctx, service.state),
        initial_keys={
            e.service_key
            for e in initial_entities
            if isinstance(e, OdioServiceMediaPlayer)
        },
        label="service media_player(s)",
        async_add_entities=async_add_entities,
    )


def _register_dynamic_clients(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for newly discovered remote audio clients."""

    def _select_key(obj: Any) -> str | None:
        if not isinstance(obj, AudioClient):
            return None
        return obj.name if _is_remote_client(ctx, obj.state) else None

    register_dynamic_entities(
        config_entry,
        ctx.hub.audio.on_change,
        select_key=_select_key,
        factory=lambda client: OdioPulseClientMediaPlayer(ctx, client.state),
        initial_keys={
            entity._client_name
            for entity in initial_entities
            if isinstance(entity, OdioPulseClientMediaPlayer)
        },
        label="remote client media_player(s)",
        async_add_entities=async_add_entities,
    )


def _register_dynamic_mpris(
    config_entry: OdioConfigEntry,
    ctx: _MediaPlayerContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
) -> None:
    """Register listener for newly discovered MPRIS players."""
    known_mpris_players: dict[str, OdioMPRISMediaPlayer] = {
        entity._player_name: entity
        for entity in initial_entities
        if isinstance(entity, OdioMPRISMediaPlayer)
    }
    known_app_names: set[str] = {e._app_name for e in known_mpris_players.values()}

    @callback
    def _handle_player_change(change: str, player: Any) -> None:
        if change != ADDED or not isinstance(player, Player):
            return
        bus_name = player.bus_name
        if not bus_name or bus_name in known_mpris_players:
            return
        app_name = extract_mpris_app_name(bus_name)
        if app_name in known_app_names:
            # The app already has an entity — rebind it if it is currently
            # unavailable (e.g. Chrome restarted with a new bus_name / PID).
            existing = next(
                (
                    e for e in known_mpris_players.values()
                    if e._app_name == app_name and not e.available
                ),
                None,
            )
            if existing is not None:
                known_mpris_players.pop(existing._player_name, None)
                existing._player_name = bus_name
                known_mpris_players[bus_name] = existing
                existing.async_write_ha_state()
            return
        entity = OdioMPRISMediaPlayer(ctx, player)
        known_mpris_players[bus_name] = entity
        known_app_names.add(app_name)
        _LOGGER.info("Adding new MPRIS player entity for %s", bus_name)
        async_add_entities([entity])

    config_entry.async_on_unload(ctx.hub.players.on_change(_handle_player_change))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote media player based on a config entry."""
    rd = config_entry.runtime_data
    server_info = rd.server_info
    ctx = _MediaPlayerContext(
        entry_id=config_entry.entry_id,
        hub=rd.hub,
        device_info=rd.device_info,
        service_mappings=rd.service_mappings,
        backends=server_info.backends,
        server_hostname=server_info.hostname or None,
    )

    entities: list[MediaPlayerEntity] = [OdioReceiverMediaPlayer(ctx)]
    if server_info.backends.systemd:
        entities += _build_service_entities(ctx)
    if server_info.backends.pulseaudio:
        entities += _build_remote_client_entities(ctx)
    if server_info.backends.mpris:
        entities += _build_mpris_entities(ctx)

    _LOGGER.info(
        "Creating %d media_player entities (1 receiver + %d services + %d standalone clients + %d mpris)",
        len(entities),
        len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioPulseClientMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioMPRISMediaPlayer)]),
    )
    async_add_entities(entities)

    if server_info.backends.systemd:
        _register_dynamic_services(config_entry, ctx, async_add_entities, entities)
    if server_info.backends.pulseaudio:
        _register_dynamic_clients(config_entry, ctx, async_add_entities, entities)
    if server_info.backends.mpris:
        _register_dynamic_mpris(config_entry, ctx, async_add_entities, entities)


# =============================================================================
# Entities
# =============================================================================


class OdioReceiverMediaPlayer(OdioEntity, MediaPlayerEntity):
    """Representation of the main Odio Remote receiver (the Odio instance)."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _unique_suffix = "receiver"

    def __init__(self, ctx: _MediaPlayerContext) -> None:
        """Initialize the receiver."""
        super().__init__(ctx.hub, ctx.entry_id, ctx.device_info)
        self._backends = ctx.backends

    def _change_sources(self) -> tuple:
        sources = []
        if self._backends.pulseaudio:
            sources.append(self._hub.audio.on_change)
        if self._backends.mpris:
            sources.append(self._hub.players.on_change)
        return tuple(sources)

    @property
    def available(self) -> bool:
        """The receiver is always shown; connectivity is reflected in its state."""
        return True

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if not self._hub.connected or not self._backends.pulseaudio:
            return MediaPlayerState.OFF

        clients = self._hub.audio.clients.values()
        if any(not client.corked for client in clients):
            return MediaPlayerState.PLAYING

        if self._backends.mpris and self._hub.players.playing:
            return MediaPlayerState.PLAYING

        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = MediaPlayerEntityFeature(0)
        if self._backends.pulseaudio:
            features |= (
                MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_MUTE
                | MediaPlayerEntityFeature.SELECT_SOURCE
            )
        return features

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        volumes = [client.volume for client in self._hub.audio.clients.values()]
        if volumes:
            return sum(volumes) / len(volumes)
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        return any(client.muted for client in self._hub.audio.clients.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "backends": asdict(self._backends),
        }
        if self._backends.pulseaudio:
            clients = list(self._hub.audio.clients.values())
            attrs["active_clients"] = len(clients)
            attrs["playing_clients"] = len([c for c in clients if not c.corked])
        return attrs

    @property
    def source_list(self) -> list[str] | None:
        """Return the list of available audio outputs."""
        outputs = list(self._hub.audio.outputs.values())
        if not outputs:
            return None
        return [o.description or o.name for o in outputs]

    @property
    def source(self) -> str | None:
        """Return the current default audio output."""
        default = self._hub.audio.default_output
        if default is None:
            return None
        return default.description or default.name

    async def async_select_source(self, source: str) -> None:
        """Set the default audio output."""
        for output in self._hub.audio.outputs.values():
            if (output.description or output.name) == source:
                await output.make_default()
                return

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._hub.audio.set_volume(volume)

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._hub.audio.set_muted(mute)


class OdioServiceMediaPlayer(MappedEntityMixin, OdioEntity, MediaPlayerEntity):
    """Representation of an Odio Remote service using MappedEntityMixin.

    A service entity is a simple ON/OFF wrapper around a systemd service.
    It has no native media capabilities — playback state, volume, and media
    metadata are all delegated to the mapped entity via MappedEntityMixin.
    """

    def __init__(self, ctx: _MediaPlayerContext, state: ServiceState) -> None:
        """Initialize the service."""
        self._key = state.key
        self._scope = state.scope
        self._service_name = state.name
        self._initial_enabled = state.enabled
        self._unique_suffix = f"service_{state.scope}_{state.name}"
        super().__init__(ctx.hub, ctx.entry_id, ctx.device_info)
        self._service_mappings = ctx.service_mappings
        self._attr_name = f"{state.name} ({state.scope})"

    @property
    def service_key(self) -> str:
        """Return the ``scope/name`` key of the backing service."""
        return self._key

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return self._key

    def _change_sources(self) -> tuple:
        return (self._hub.services.on_change,)

    def _relevant_change(self, change: str, obj: Any) -> bool:
        return isinstance(obj, Service) and obj.state.key == self._key

    def _service(self) -> Service | None:
        return self._hub.services.get(self._key)

    def _is_service_running(self) -> bool:
        """Check if the service is running."""
        service = self._service()
        return bool(service and service.running)

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._is_service_running)
        if mapped_state is not None:
            return mapped_state

        if not self._is_service_running():
            return MediaPlayerState.OFF

        return MediaPlayerState.IDLE

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
        service = self._service()
        attrs = {
            ATTR_SERVICE_SCOPE: self._scope,
            ATTR_SERVICE_ENABLED: service.enabled if service else self._initial_enabled,
        }
        if service is not None:
            attrs[ATTR_SERVICE_ACTIVE] = service.state.active_state
            attrs["running"] = service.running
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        return attrs

    @api_command
    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        _LOGGER.debug("Turning on service %s", self._key)
        await self._hub.client.service_enable(self._scope, self._service_name)

    @api_command
    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        _LOGGER.debug("Turning off service %s", self._key)
        await self._hub.client.service_disable(self._scope, self._service_name)

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._delegate_to_hass("volume_set", {"volume_level": volume})

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._delegate_to_hass("volume_mute", {"is_volume_muted": mute})


class OdioPulseClientMediaPlayer(MappedEntityMixin, OdioEntity, MediaPlayerEntity):
    """Representation of a standalone audio client using MappedEntityMixin."""

    def __init__(self, ctx: _MediaPlayerContext, state: AudioClientState) -> None:
        """Initialize the standalone client."""
        self._client_name = state.name
        self._client_host = state.host

        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._client_name.lower()).strip("_")
        self._unique_suffix = f"remote_{safe_name}"
        super().__init__(ctx.hub, ctx.entry_id, ctx.device_info)
        self._service_mappings = ctx.service_mappings
        self._server_hostname = ctx.server_hostname
        self._attr_name = self._client_name

        _LOGGER.debug(
            "Created standalone client entity for '%s' from host '%s' with unique_id '%s'",
            self._client_name,
            self._client_host,
            self._attr_unique_id,
        )

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"client:{self._client_name}"

    def _change_sources(self) -> tuple:
        return (self._hub.audio.on_change,)

    def _relevant_change(self, change: str, obj: Any) -> bool:
        return isinstance(obj, AudioClient) and obj.name == self._client_name

    def _client(self) -> AudioClient | None:
        """Return the live audio client, or None when disconnected."""
        return self._hub.audio.clients.get(self._client_name)

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._client)
        if mapped_state is not None:
            return mapped_state
        client = self._client()
        if client is None:
            return MediaPlayerState.OFF
        if not client.corked:
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
        client = self._client()
        if client is not None:
            return client.volume
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted
        client = self._client()
        if client is not None:
            return client.muted
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        client = self._client()
        attrs = {
            "client_name": self._client_name,
            "remote_host": self._client_host,
            "server_hostname": self._server_hostname,
        }
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        if client is None:
            attrs["status"] = "disconnected"
            return attrs
        state = client.state
        attrs["status"] = "connected"
        attrs[ATTR_CLIENT_ID] = state.id
        attrs[ATTR_APP] = state.app
        attrs[ATTR_BACKEND] = state.backend
        attrs[ATTR_USER] = state.user
        attrs[ATTR_HOST] = state.host
        attrs[ATTR_CORKED] = state.corked
        props = state.props
        if "native-protocol.peer" in props:
            attrs["connection"] = props["native-protocol.peer"]
        if "application.process.host" in props:
            attrs["remote_host"] = props["application.process.host"]
        if "application.version" in props:
            attrs["app_version"] = props["application.version"]
        return attrs

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._set_volume_with_fallback(volume, self._client)

    @api_command
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._mute_with_fallback(mute, self._client)


class OdioMPRISMediaPlayer(MappedEntityMixin, OdioEntity, MediaPlayerEntity):
    """MPRIS media player entity with full native MPRIS support."""

    def __init__(self, ctx: _MediaPlayerContext, player: Player) -> None:
        """Initialize the MPRIS media player."""
        self._player_name = player.bus_name
        self._app_name = extract_mpris_app_name(self._player_name)

        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._app_name.lower()).strip("_")
        self._unique_suffix = f"mpris_{safe_name}"
        super().__init__(ctx.hub, ctx.entry_id, ctx.device_info)
        self._service_mappings = ctx.service_mappings

        if player.identity:
            self._attr_name = player.identity
        else:
            self._attr_name = self._app_name.replace("_", " ").title()

        _LOGGER.debug(
            "Initialized MPRIS player: unique_id=%s, name=%s, bus_name=%s",
            self._attr_unique_id,
            self._attr_name,
            self._player_name,
        )

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings.

        Keyed by app name (stable across browser/HA restarts), not the
        volatile bus_name — see also unique_id derivation in __init__.
        """
        return f"mpris:{self._app_name}"

    def _change_sources(self) -> tuple:
        return (self._hub.players.on_change,)

    def _relevant_change(self, change: str, obj: Any) -> bool:
        return isinstance(obj, Player) and obj.bus_name == self._player_name

    def _player(self) -> Player | None:
        """Return the live player, or None when gone."""
        return self._hub.players.get(self._player_name)

    @property
    def available(self) -> bool:
        """Return True if the player is reported by the hub and not removed."""
        player = self._player()
        return self._hub.connected and player is not None and player.available

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        if not self.available:
            return MediaPlayerState.OFF

        player = self._player()
        if player is None:
            return MediaPlayerState.OFF

        if player.playback_status == "Playing":
            return MediaPlayerState.PLAYING
        if player.playback_status == "Paused":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features based on MPRIS capabilities and mapped entity."""
        player = self._player()
        mapped_features = self._get_mapped_attribute("supported_features")

        features = MediaPlayerEntityFeature(0)

        if player is not None:
            caps = player.capabilities
            if caps.can_play:
                features |= MediaPlayerEntityFeature.PLAY
            if caps.can_pause:
                features |= MediaPlayerEntityFeature.PAUSE
            if caps.can_control:
                features |= MediaPlayerEntityFeature.STOP
            if caps.can_go_next:
                features |= MediaPlayerEntityFeature.NEXT_TRACK
            if caps.can_go_previous:
                features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
            if caps.can_seek:
                features |= MediaPlayerEntityFeature.SEEK
            if caps.can_control and player.volume is not None:
                features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
            if player.shuffle is not None:
                features |= MediaPlayerEntityFeature.SHUFFLE_SET
            if player.loop_status is not None:
                features |= MediaPlayerEntityFeature.REPEAT_SET

        return self._get_supported_features(features, mapped_features)

    # Media properties — native MPRIS data overrides mixin delegation

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        player = self._player()
        if player is not None:
            return player.volume
        return None

    @property
    def media_content_type(self) -> str:
        """Content type of current playing media."""
        return MediaType.MUSIC

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        player = self._player()
        if player is not None and player.duration is not None:
            return player.duration // 1_000_000
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds.

        The raw beacon position is returned together with
        ``media_position_updated_at`` — HA extrapolates while playing.
        """
        player = self._player()
        if player is not None and player.state.position is not None:
            return player.state.position // 1_000_000
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When was the position of the current playing media valid."""
        player = self._player()
        if player is None:
            return None
        updated_at = player.state.position_updated_at
        if updated_at is not None and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return updated_at

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        player = self._player()
        return player.title if player is not None else None

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        player = self._player()
        return player.artist if player is not None else None

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        player = self._player()
        return player.album if player is not None else None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media.

        Routes through the go-odio-api /cover proxy so file:// artwork
        (served from the Odio host's filesystem) is reachable by HA, while
        http(s) URLs are redirected by the proxy. Cache-busts on trackid and
        artUrl, matching the go-odio-api UI.
        """
        player = self._player()
        if player is not None and player.art_url:
            return player.cover_url
        return None

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        player = self._player()
        return player.shuffle if player is not None else None

    @property
    def repeat(self) -> RepeatMode | None:
        """Return current repeat mode."""
        player = self._player()
        if player is not None:
            if player.loop_status == "None":
                return RepeatMode.OFF
            if player.loop_status == "Track":
                return RepeatMode.ONE
            if player.loop_status == "Playlist":
                return RepeatMode.ALL
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        player = self._player()
        if player is None:
            return {}

        caps = player.capabilities
        attrs = {
            "player_name": self._player_name,
            "identity": player.identity,
            "playback_status": player.playback_status,
            "can_control": caps.can_control,
            "can_play": caps.can_play,
            "can_pause": caps.can_pause,
            "can_seek": caps.can_seek,
            "can_go_next": caps.can_go_next,
            "can_go_previous": caps.can_go_previous,
        }
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        return attrs

    # Media control — MPRIS API first if capability exists, else delegate to mapped entity

    @api_command
    async def async_media_play(self) -> None:
        """Send play command."""
        player = self._player()
        if player is not None and player.capabilities.can_play:
            _LOGGER.debug("MPRIS play: %s", self._player_name)
            await player.play()
            return
        await self._delegate_to_hass("media_play")

    @api_command
    async def async_media_pause(self) -> None:
        """Send pause command."""
        player = self._player()
        if player is not None and player.capabilities.can_pause:
            _LOGGER.debug("MPRIS pause: %s", self._player_name)
            await player.pause()
            return
        await self._delegate_to_hass("media_pause")

    @api_command
    async def async_media_stop(self) -> None:
        """Send stop command."""
        player = self._player()
        if player is not None and player.capabilities.can_control:
            _LOGGER.debug("MPRIS stop: %s", self._player_name)
            await player.stop()
            return
        await self._delegate_to_hass("media_stop")

    @api_command
    async def async_media_next_track(self) -> None:
        """Send next track command."""
        player = self._player()
        if player is not None and player.capabilities.can_go_next:
            _LOGGER.debug("MPRIS next: %s", self._player_name)
            await player.next()
            return
        await self._delegate_to_hass("media_next_track")

    @api_command
    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        player = self._player()
        if player is not None and player.capabilities.can_go_previous:
            _LOGGER.debug("MPRIS previous: %s", self._player_name)
            await player.previous()
            return
        await self._delegate_to_hass("media_previous_track")

    @api_command
    async def async_media_seek(self, position: float) -> None:
        """Seek to position (in seconds)."""
        player = self._player()
        if player is not None and player.capabilities.can_seek:
            _LOGGER.debug("MPRIS seek to %s: %s", position, self._player_name)
            await player.set_position(int(position * 1_000_000))
            return
        await self._delegate_to_hass("media_seek", {"seek_position": position})

    @api_command
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0..1)."""
        player = self._player()
        if player is not None and player.capabilities.can_control and player.volume is not None:
            _LOGGER.debug("MPRIS set volume %s: %s", volume, self._player_name)
            await player.set_volume(volume)
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
        player = self._player()
        if player is not None and player.shuffle is not None:
            _LOGGER.debug("MPRIS set shuffle %s: %s", shuffle, self._player_name)
            await player.set_shuffle(shuffle)
            return
        await self._delegate_to_hass("shuffle_set", {"shuffle": shuffle})

    @api_command
    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        player = self._player()
        if player is not None and player.loop_status is not None:
            _LOGGER.debug("MPRIS set repeat %s: %s", repeat, self._player_name)
            if repeat == RepeatMode.ONE:
                loop_status = "Track"
            elif repeat == RepeatMode.ALL:
                loop_status = "Playlist"
            else:
                loop_status = "None"
            await player.set_loop(loop_status)
            return
        await self._delegate_to_hass("repeat_set", {"repeat": repeat})
