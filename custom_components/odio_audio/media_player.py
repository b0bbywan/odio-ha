"""Media player platform for Odio Audio."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .const import (
    DOMAIN,
    ATTR_CLIENT_ID,
    ATTR_APP,
    ATTR_BACKEND,
    ATTR_USER,
    ATTR_HOST,
    ATTR_CORKED,
    ATTR_SERVICE_SCOPE,
    ATTR_SERVICE_ENABLED,
    ATTR_SERVICE_ACTIVE,
    SUPPORTED_SERVICES,
)
from .mixins import MediaPlayerMappingMixin, SwitchMappingMixin

_LOGGER = logging.getLogger(__name__)

_MPRIS_BUS_PREFIX = "org.mpris.MediaPlayer2."


# =============================================================================
# Platform setup context and helpers
# =============================================================================


@dataclass(frozen=True)
class _PlatformContext:
    """Shared context for media player platform setup.

    Groups all the objects that every helper function needs,
    avoiding long parameter lists and keeping setup readable.
    """

    config_entry: OdioConfigEntry
    media_coordinator: DataUpdateCoordinator
    service_coordinator: DataUpdateCoordinator | None
    api: OdioApiClient
    device_info: DeviceInfo
    hostname: str


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


def _build_receiver_device_info(
    hostname: str,
    api_version: str,
    api_url: str,
    model_id: str | None,
    hw_version: str | None,
) -> DeviceInfo:
    """Build device info for Receiver device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{hostname}_receiver")},
        name=f"Odio Receiver ({hostname})",
        manufacturer="Odio",
        model="Media Hub",
        model_id=model_id,
        sw_version=api_version,
        hw_version=hw_version,
        configuration_url=api_url,
    )


def _build_platform_context(
    config_entry: OdioConfigEntry,
    media_coordinator: DataUpdateCoordinator,
) -> _PlatformContext:
    """Build shared platform context from config entry runtime data."""
    data = config_entry.runtime_data
    server_info = data.server_info
    backends = data.backends

    hostname = server_info.get("hostname", "unknown")
    api_version = server_info.get("api_version", "unknown")

    # Model ID reflects which audio backends are active
    backends_list = [b for b in ("pulseaudio", "mpris") if backends.get(b)]
    model_id = "+".join(backends_list) if backends_list else None

    # Hardware version from PulseAudio/PipeWire server info
    hw_version = None
    if media_coordinator.data:
        server_data = media_coordinator.data.get("server", {})
        kind = server_data.get("kind", "")
        version = server_data.get("version", "")
        if kind:
            hw_version = f"{kind} {version}"

    device_info = _build_receiver_device_info(
        hostname, api_version, data.api._api_url, model_id, hw_version,
    )

    return _PlatformContext(
        config_entry=config_entry,
        media_coordinator=media_coordinator,
        service_coordinator=data.service_coordinator,
        api=data.api,
        device_info=device_info,
        hostname=hostname,
    )


# =============================================================================
# Entity creation helpers
# =============================================================================


def _create_receiver_entity(ctx: _PlatformContext) -> OdioReceiverMediaPlayer:
    """Create the main receiver entity (global volume control)."""
    return OdioReceiverMediaPlayer(
        ctx.media_coordinator,
        ctx.api,
        ctx.config_entry.entry_id,
        ctx.device_info,
    )


def _create_service_entities(
    ctx: _PlatformContext,
    handled_patterns: set[str],
) -> list[OdioServiceMediaPlayer]:
    """Create media player entities for supported systemd services.

    Also populates *handled_patterns* with service names so that standalone
    client detection can skip clients already covered by a service entity.
    """
    if not ctx.service_coordinator or not ctx.service_coordinator.data:
        return []

    entities: list[OdioServiceMediaPlayer] = []
    for service in ctx.service_coordinator.data.get("services", []):
        if not (
            service.get("exists")
            and service.get("enabled")
            and service["name"] in SUPPORTED_SERVICES
        ):
            continue

        entities.append(
            OdioServiceMediaPlayer(
                ctx.media_coordinator,
                ctx.service_coordinator,
                ctx.api,
                ctx.config_entry.entry_id,
                service,
                ctx.device_info,
            )
        )
        handled_patterns.add(service["name"].replace(".service", "").lower())

    return entities


def _create_mpris_entities(ctx: _PlatformContext) -> list[OdioMPRISMediaPlayer]:
    """Create media player entities for MPRIS players reported by the API."""
    if not ctx.media_coordinator.data:
        return []

    players = ctx.media_coordinator.data.get("players", [])
    if not players:
        return []

    _LOGGER.debug("Setting up MPRIS players: %d found", len(players))

    services = (
        ctx.service_coordinator.data.get("services", [])
        if ctx.service_coordinator and ctx.service_coordinator.data
        else []
    )
    player_to_switch = _build_player_switch_mapping(players, services, ctx.hostname)

    entities: list[OdioMPRISMediaPlayer] = []
    for player in players:
        bus_name = player.get("bus_name", "")
        if not bus_name:
            continue

        _LOGGER.debug("Creating MPRIS player for: %s", bus_name)
        entities.append(
            OdioMPRISMediaPlayer(
                ctx.media_coordinator,
                ctx.api,
                player,
                ctx.device_info,
                ctx.hostname,
                ctx.config_entry.entry_id,
                player_to_switch.get(bus_name),
            )
        )

    return entities


def _create_standalone_client_entities(
    ctx: _PlatformContext,
) -> list[OdioStandaloneClientMediaPlayer]:
    """Create media player entities for remote PulseAudio clients."""
    if not ctx.media_coordinator.data:
        return []

    entities: list[OdioStandaloneClientMediaPlayer] = []
    for client in ctx.media_coordinator.data.get("audio", []):
        client_name = client.get("name", "")
        client_host = client.get("host", "")

        is_remote = ctx.hostname and client_host and client_host != ctx.hostname
        if not is_remote or not client_name:
            continue

        entities.append(
            OdioStandaloneClientMediaPlayer(
                ctx.media_coordinator,
                ctx.api,
                ctx.config_entry.entry_id,
                client,
                ctx.device_info,
            )
        )

    return entities


# =============================================================================
# Dynamic entity listener
# =============================================================================


def _setup_dynamic_entity_listener(
    ctx: _PlatformContext,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[MediaPlayerEntity],
    handled_patterns: set[str],
) -> None:
    """Register a coordinator listener that detects new MPRIS players and remote clients.

    When the coordinator polls fresh data, this callback compares the current
    set of players/clients against those already known and creates new entities
    for any newcomers.
    """
    known_mpris: dict[str, OdioMPRISMediaPlayer] = {
        e._player_name: e
        for e in initial_entities
        if isinstance(e, OdioMPRISMediaPlayer)
    }
    known_clients: dict[str, OdioStandaloneClientMediaPlayer] = {
        e._client_name: e
        for e in initial_entities
        if isinstance(e, OdioStandaloneClientMediaPlayer)
    }

    coordinator = ctx.media_coordinator
    service_coordinator = ctx.service_coordinator

    @callback
    def _on_coordinator_update() -> None:
        if not coordinator.data or not ctx.hostname:
            return

        new_entities: list[MediaPlayerEntity] = []

        # --- New MPRIS players ---
        for player in coordinator.data.get("players", []):
            bus_name = player.get("bus_name", "")
            if not bus_name or bus_name in known_mpris:
                continue

            _LOGGER.info("Detected new MPRIS player: '%s'", bus_name)
            services = (
                service_coordinator.data.get("services", [])
                if service_coordinator and service_coordinator.data
                else []
            )
            mapping = _build_player_switch_mapping([player], services, ctx.hostname)
            mpris_entity = OdioMPRISMediaPlayer(
                coordinator, ctx.api, player, ctx.device_info,
                ctx.hostname, ctx.config_entry.entry_id, mapping.get(bus_name),
            )
            new_entities.append(mpris_entity)
            known_mpris[bus_name] = mpris_entity

        # --- New remote clients ---
        for client in coordinator.data.get("audio", []):
            client_name = client.get("name", "")
            client_host = client.get("host", "")

            is_remote = client_host and client_host != ctx.hostname
            if not is_remote or not client_name or client_name in known_clients:
                continue

            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()
            if any(p in [client_name.lower(), app, binary] for p in handled_patterns):
                continue

            _LOGGER.info("Detected new remote client: '%s' from '%s'", client_name, client_host)
            client_entity = OdioStandaloneClientMediaPlayer(
                coordinator, ctx.api, ctx.config_entry.entry_id,
                client, ctx.device_info,
            )
            new_entities.append(client_entity)
            known_clients[client_name] = client_entity

        if new_entities:
            _LOGGER.info("Adding %d new entities", len(new_entities))
            async_add_entities(new_entities)

    ctx.config_entry.async_on_unload(
        coordinator.async_add_listener(_on_coordinator_update)
    )


# =============================================================================
# MPRIS switch mapping helper
# =============================================================================


def _build_player_switch_mapping(
    players: list[dict[str, Any]],
    services: list[dict[str, Any]],
    hostname: str,
) -> dict[str, str]:
    """Build mapping from MPRIS player bus_name to switch entity_id.

    Uses the player identity (e.g. "Spotify", "Music Player Daemon") and the
    app name extracted from the bus_name to find a matching systemd user
    service.  When multiple services match (e.g. several firefox-kiosk@…
    instances), the mapping is skipped to avoid incorrect associations.
    """
    mapping: dict[str, str] = {}

    user_services = [s for s in services if s.get("scope") == "user"]

    for player in players:
        bus_name = player.get("bus_name", "")
        if not bus_name:
            continue

        app_name = _extract_mpris_app_name(bus_name).lower()
        identity = player.get("identity", "").lower()
        # First word of identity is usually the app (e.g. "spotify", "mozilla")
        identity_keyword = identity.split()[0] if identity else ""

        media_url = player.get("metadata", {}).get("xesam:url", "").lower()

        matches: list[str] = []
        for service in user_services:
            unit = service.get("unit", "") or service.get("name", "")
            unit_base = unit.split(".service")[0].lower()

            # Template service (e.g. firefox-kiosk@www.youtube.com):
            # match by URL domain from metadata.xesam:url
            if "@" in unit_base:
                instance = unit_base.split("@", 1)[1]
                if instance and media_url and instance in media_url:
                    matches.append(unit)
                continue

            # Simple service: match by app name or identity keyword
            if app_name and app_name in unit_base:
                matches.append(unit)
            elif identity_keyword and identity_keyword in unit_base:
                matches.append(unit)

        if len(matches) == 1:
            unit = matches[0]
            sanitized = unit.replace(".service", "").replace("@", "_").replace(".", "_")
            switch_entity_id = f"switch.{hostname}_{sanitized}"
            mapping[bus_name] = switch_entity_id
            _LOGGER.debug(
                "Mapped player %s (%s) to switch %s",
                bus_name, identity, switch_entity_id,
            )
        elif len(matches) > 1:
            _LOGGER.debug(
                "Skipping auto-map for %s (%s): %d ambiguous service matches (%s)",
                bus_name, identity, len(matches), matches,
            )

    return mapping


# =============================================================================
# Platform entry point
# =============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Audio media player entities from a config entry."""
    media_coordinator = config_entry.runtime_data.media_coordinator
    if not media_coordinator:
        _LOGGER.debug("No media coordinator available, skipping media player setup")
        return

    ctx = _build_platform_context(config_entry, media_coordinator)
    _LOGGER.debug("Server hostname: %s", ctx.hostname)

    entities: list[MediaPlayerEntity] = []

    # 1. Main receiver (global volume control)
    entities.append(_create_receiver_entity(ctx))

    # 2. Service-backed players (mpd, spotifyd, shairport-sync …)
    handled_patterns: set[str] = set()
    entities.extend(_create_service_entities(ctx, handled_patterns))

    # 3. MPRIS players (native D-Bus media players)
    entities.extend(_create_mpris_entities(ctx))

    # 4. Standalone remote PulseAudio clients
    entities.extend(_create_standalone_client_entities(ctx))

    _LOGGER.info(
        "Creating %d media_player entities (%d receiver, %d services, %d MPRIS, %d standalone)",
        len(entities),
        len([e for e in entities if isinstance(e, OdioReceiverMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioMPRISMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioStandaloneClientMediaPlayer)]),
    )

    async_add_entities(entities)

    # 5. Dynamic detection of new players/clients on coordinator updates
    _setup_dynamic_entity_listener(ctx, async_add_entities, entities, handled_patterns)


# =============================================================================
# Entity: Receiver (global PulseAudio/PipeWire volume)
# =============================================================================


class OdioReceiverMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of the main Odio Audio receiver."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        media_coordinator: DataUpdateCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the receiver."""
        super().__init__(media_coordinator)
        self._api_client = api_client
        self._attr_unique_id = f"{entry_id}_receiver"
        self._attr_device_info = device_info

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        if not self.coordinator.data:
            return MediaPlayerState.OFF

        clients = self.coordinator.data.get("audio", [])
        # Check if any client is playing
        for client in clients:
            if not client.get("corked", True):
                return MediaPlayerState.PLAYING

        # Check if any clients exist
        if self.coordinator.data:
            return MediaPlayerState.IDLE

        return MediaPlayerState.OFF

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        return MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        if not self.coordinator.data:
            return None

        server = self.coordinator.data.get("server", {})
        return server.get("volume")

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        if not self.coordinator.data:
            return False

        clients = self.coordinator.data.get("audio", [])
        return any(client.get("muted", False) for client in clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        if self.coordinator.data:
            clients = self.coordinator.data.get("audio", [])
            attrs["active_clients"] = len(clients)
            attrs["playing_clients"] = len([
                client for client in clients
                if not client.get("corked", True)
            ])

        if self.coordinator.data:
            server = self.coordinator.data.get("server", {})
            if server:
                attrs["server_name"] = server.get("name")
                attrs["server_hostname"] = server.get("hostname")
                attrs["default_sink"] = server.get("default_sink")

        return attrs

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._api_client.set_server_volume(volume)
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._api_client.set_server_mute(mute)
        await self.coordinator.async_request_refresh()


# =============================================================================
# Entity: Service-backed media player (mpd, spotifyd, …)
# =============================================================================


class OdioServiceMediaPlayer(MediaPlayerMappingMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Odio Audio service using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(
        self,
        media_coordinator: DataUpdateCoordinator,
        service_coordinator: DataUpdateCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
        service_info: dict[str, Any],
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the service."""
        super().__init__(media_coordinator)
        self._service_coordinator = service_coordinator
        self._api_client = api_client
        self._entry_id = entry_id
        self._service_info = service_info
        self._hass: HomeAssistant | None = None

        service_name = service_info["name"]
        scope = service_info["scope"]

        self._attr_unique_id = f"{entry_id}_service_{scope}_{service_name}"
        self._attr_name = f"{service_name} ({scope})"
        self._attr_device_info = device_info

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"{self._service_info['scope']}/{self._service_info['name']}"

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._hass = self.hass

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()
        self.async_on_remove(
            self._service_coordinator.async_add_listener(
                self._handle_service_coordinator_update
            )
        )

    @callback
    def _handle_service_coordinator_update(self) -> None:
        """Handle updated data from the service coordinator."""
        self.async_write_ha_state()

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        # Try to map from mapped entity if available
        mapped_state = self._map_state_from_entity(self._is_service_running)
        if mapped_state is not None:
            return mapped_state

        # Fallback to original logic
        if not self._is_service_running():
            return MediaPlayerState.OFF

        # Check if service has an active audio client
        if self.coordinator.data:
            service_name = self._service_info["name"].replace(".service", "")
            clients = self.coordinator.data.get("audio", [])

            for client in clients:
                client_name = client.get("name", "").lower()
                app = client.get("app", "").lower()
                binary = client.get("binary", "").lower()

                if service_name in [client_name, app, binary]:
                    if not client.get("corked", True):
                        return MediaPlayerState.PLAYING
                    return MediaPlayerState.IDLE

        return MediaPlayerState.IDLE

    def _is_service_running(self) -> bool:
        """Check if the service is running."""
        if self._service_coordinator.data:
            services = self._service_coordinator.data.get("services", [])
            for svc in services:
                if (
                    svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]
                ):
                    return svc.get("running", False)
        return False

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = (
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF | MediaPlayerEntityFeature.VOLUME_MUTE
        )

        # Add volume control if client is found
        if self._get_client():
            base_features |= MediaPlayerEntityFeature.VOLUME_SET

        # Add features from mapped entity if available
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Prefer mapped entity volume if available
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume

        # Fallback to client volume
        client = self._get_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        # Prefer mapped entity mute state if available
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted

        # Fallback to client mute
        client = self._get_client()
        if client:
            return client.get("muted", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            ATTR_SERVICE_SCOPE: self._service_info["scope"],
            ATTR_SERVICE_ENABLED: self._service_info.get("enabled", False),
        }

        if self._service_coordinator.data:
            services = self._service_coordinator.data.get("services", [])
            for svc in services:
                if (
                    svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]
                ):
                    attrs[ATTR_SERVICE_ACTIVE] = svc.get("active_state")
                    attrs["running"] = svc.get("running", False)
                    break

        client = self._get_client()
        if client:
            attrs[ATTR_CLIENT_ID] = client.get("id")
            attrs[ATTR_APP] = client.get("app")
            attrs[ATTR_BACKEND] = client.get("backend")
            attrs[ATTR_USER] = client.get("user")
            attrs[ATTR_HOST] = client.get("host")
            attrs[ATTR_CORKED] = client.get("corked")

        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity

        return attrs

    def _get_client(self) -> dict[str, Any] | None:
        """Get the audio client for this service."""
        if not self.coordinator.data:
            return None

        service_name = self._service_info["name"].replace(".service", "")
        clients = self.coordinator.data.get("audio", [])
        for client in clients:
            client_name = client.get("name", "").lower()
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()

            if service_name in [client_name, app, binary]:
                return client

        return None

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning on service %s/%s", scope, unit)

        await self._api_client.control_service("enable", scope, unit)
        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        await asyncio.sleep(0.5)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning off service %s/%s", scope, unit)
        await self._api_client.control_service("disable", scope, unit)

        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        await asyncio.sleep(0.5)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Try to delegate to mapped entity first
        if await self._delegate_to_hass("volume_set", {"volume_level": volume}):
            return

        # Fallback to PulseAudio client volume
        client = self._get_client()
        if not client:
            _LOGGER.warning(
                "No client found for service %s/%s, cannot set volume",
                self._service_info["scope"],
                self._service_info["name"],
            )
            return

        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return

        await self._api_client.set_client_volume(client_name, volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        # Try mapped entity first
        if await self._delegate_to_hass("volume_mute", {"is_volume_muted": mute}):
            return

        # Fallback to PulseAudio client mute
        client = self._get_client()
        if not client:
            _LOGGER.warning(
                "No client found for service %s/%s, cannot mute",
                self._service_info["scope"],
                self._service_info["name"],
            )
            return

        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return

        await self._api_client.set_client_mute(client_name, mute)


# =============================================================================
# Entity: Standalone remote PulseAudio client
# =============================================================================


class OdioStandaloneClientMediaPlayer(MediaPlayerMappingMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of a standalone audio client using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(
        self,
        media_coordinator: DataUpdateCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
        initial_client: dict[str, Any],
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the standalone client."""
        super().__init__(media_coordinator)
        self._api_client = api_client
        self._entry_id = entry_id
        self._hass: HomeAssistant | None = None
        self._attr_device_info = device_info

        # Use client NAME as stable identifier
        self._client_name = initial_client.get("name", "")
        self._client_host = initial_client.get("host", "")

        # Generate a stable unique_id
        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._client_name.lower()).strip("_")
        self._attr_unique_id = f"{entry_id}_remote_{safe_name}"
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._hass = self.hass

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        # Try to map from mapped entity if available
        mapped_state = self._map_state_from_entity(self._get_current_client)
        if mapped_state is not None:
            return mapped_state

        # Fallback to original logic
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

        # Add features from mapped entity if available
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Prefer mapped entity volume if available
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume

        # Fallback to client volume
        client = self._get_current_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        # Prefer mapped entity mute state if available
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted

        # Fallback to client mute
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

        # Add interesting props if available
        props = client.get("props", {})
        if "native-protocol.peer" in props:
            attrs["connection"] = props["native-protocol.peer"]
        if "application.process.host" in props:
            attrs["remote_host"] = props["application.process.host"]
        if "application.version" in props:
            attrs["app_version"] = props["application.version"]

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    def _get_current_client(self) -> dict[str, Any] | None:
        """Get the current client data from coordinator by NAME."""
        if not self.coordinator.data:
            return None

        clients = self.coordinator.data.get("audio", [])
        for client in clients:
            if client.get("name") == self._client_name:
                return client

        return None

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._set_volume_with_fallback(volume, get_client_name, self._api_client)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._mute_with_fallback(mute, get_client_name, self._api_client)


# =============================================================================
# Entity: MPRIS media player (native D-Bus control)
# =============================================================================


class OdioMPRISMediaPlayer(SwitchMappingMixin, CoordinatorEntity, MediaPlayerEntity):
    """MPRIS media player entity with full native MPRIS support."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        api: OdioApiClient,
        player: dict[str, Any],
        device_info: DeviceInfo,
        server_hostname: str,
        entry_id: str,
        mapped_switch_id: str | None = None,
    ) -> None:
        """Initialize the MPRIS media player."""
        super().__init__(coordinator)
        self._api = api
        self._player_name = player.get("bus_name", "")
        self._server_hostname = server_hostname
        self._entry_id = entry_id
        self._mapped_switch_id = mapped_switch_id
        self._attr_device_info = device_info

        # Generate unique_id from bus_name
        sanitized_name = self._player_name.replace(".", "_").replace("@", "_")
        self._attr_unique_id = f"{self._server_hostname}_mpris_{sanitized_name}"

        # Use player identity for a readable name, fall back to app name from bus_name
        identity = player.get("identity", "")
        if identity:
            self._attr_name = identity
        else:
            self._attr_name = _extract_mpris_app_name(self._player_name).replace("_", " ").title()

        _LOGGER.debug(
            "Initialized MPRIS player: unique_id=%s, name=%s, bus_name=%s, switch=%s",
            self._attr_unique_id,
            self._attr_name,
            self._player_name,
            self._mapped_switch_id,
        )

    @property
    def _hass(self):
        """Return HomeAssistant instance for SwitchMappingMixin."""
        return self.hass

    @property
    def _player_data(self) -> dict[str, Any] | None:
        """Get current player data from coordinator."""
        if not self.coordinator.data:
            return None
        players = self.coordinator.data.get("players", [])
        for player in players:
            if player.get("bus_name") == self._player_name:
                return player
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Availability is based solely on whether the player is reported by the
        coordinator.  The mapped switch only adds turn_on/turn_off features;
        it must not gate availability (auto-mapping can be wrong or the switch
        may lag behind the actual player state).
        """
        return self.coordinator.last_update_success and self._player_data is not None

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        if not self.available:
            return MediaPlayerState.OFF

        player = self._player_data
        if not player:
            return MediaPlayerState.OFF

        # Map MPRIS PlaybackStatus to HA state
        playback_status = player.get("playback_status", "")
        if playback_status == "Playing":
            return MediaPlayerState.PLAYING
        elif playback_status == "Paused":
            return MediaPlayerState.PAUSED
        elif playback_status == "Stopped":
            return MediaPlayerState.IDLE
        else:
            return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features based on MPRIS capabilities."""
        player = self._player_data
        if not player:
            return MediaPlayerEntityFeature(0)

        features = MediaPlayerEntityFeature(0)

        # Add switch control features if mapped
        features = self._get_switch_supported_features(features)

        # MPRIS control capabilities (nested under "capabilities" in API response)
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

        # Volume control
        if caps.get("can_control") and player.get("volume") is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP

        # Shuffle and repeat
        if player.get("shuffle") is not None:
            features |= MediaPlayerEntityFeature.SHUFFLE_SET
        if player.get("loop_status") is not None:
            features |= MediaPlayerEntityFeature.REPEAT_SET

        return features

    # Media properties from MPRIS
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
        from homeassistant.util import dt as dt_util
        return dt_util.utcnow()

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
        """Image url of current playing media."""
        player = self._player_data
        if player and player.get("metadata"):
            return player["metadata"].get("mpris:artUrl")
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

        if self._mapped_switch_id:
            attrs["mapped_switch"] = self._mapped_switch_id

        return attrs

    # Media control actions via MPRIS API
    async def async_media_play(self) -> None:
        """Send play command."""
        _LOGGER.debug("MPRIS play: %s", self._player_name)
        await self._api.player_play(self._player_name)
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        _LOGGER.debug("MPRIS pause: %s", self._player_name)
        await self._api.player_pause(self._player_name)
        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        """Send stop command."""
        _LOGGER.debug("MPRIS stop: %s", self._player_name)
        await self._api.player_stop(self._player_name)
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        _LOGGER.debug("MPRIS next: %s", self._player_name)
        await self._api.player_next(self._player_name)
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        _LOGGER.debug("MPRIS previous: %s", self._player_name)
        await self._api.player_previous(self._player_name)
        await self.coordinator.async_request_refresh()

    async def async_media_seek(self, position: float) -> None:
        """Seek to position (in seconds)."""
        _LOGGER.debug("MPRIS seek to %s: %s", position, self._player_name)
        position_us = int(position * 1_000_000)

        player = self._player_data
        if player and player.get("metadata"):
            track_id = player["metadata"].get("mpris:trackid", "/")
            await self._api.player_set_position(self._player_name, track_id, position_us)
            await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0..1)."""
        _LOGGER.debug("MPRIS set volume %s: %s", volume, self._player_name)
        await self._api.player_set_volume(self._player_name, volume)
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Volume up by 5%."""
        current = self.volume_level
        if current is not None:
            new_volume = min(1.0, current + 0.05)
            await self.async_set_volume_level(new_volume)

    async def async_volume_down(self) -> None:
        """Volume down by 5%."""
        current = self.volume_level
        if current is not None:
            new_volume = max(0.0, current - 0.05)
            await self.async_set_volume_level(new_volume)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle mode."""
        _LOGGER.debug("MPRIS set shuffle %s: %s", shuffle, self._player_name)
        await self._api.player_set_shuffle(self._player_name, shuffle)
        await self.coordinator.async_request_refresh()

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        _LOGGER.debug("MPRIS set repeat %s: %s", repeat, self._player_name)
        # Convert HA RepeatMode to MPRIS LoopStatus
        if repeat == RepeatMode.OFF:
            loop_status = "None"
        elif repeat == RepeatMode.ONE:
            loop_status = "Track"
        elif repeat == RepeatMode.ALL:
            loop_status = "Playlist"
        else:
            loop_status = "None"

        await self._api.player_set_loop(self._player_name, loop_status)
        await self.coordinator.async_request_refresh()
