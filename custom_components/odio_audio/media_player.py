"""Media player platform for Odio Audio."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

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
    ENDPOINT_CLIENT_MUTE,
    ENDPOINT_SERVICE_ENABLE,
    ENDPOINT_SERVICE_DISABLE,
    ENDPOINT_SERVICE_RESTART,
    SUPPORTED_SERVICES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Audio media player based on a config entry."""
    coordinator_data = hass.data[DOMAIN][config_entry.entry_id]
    audio_coordinator = coordinator_data["audio_coordinator"]
    service_coordinator = coordinator_data["service_coordinator"]
    api_url = coordinator_data["api_url"]
    session = coordinator_data["session"]
    service_mappings = coordinator_data["service_mappings"]

    # Get server hostname to identify remote clients
    server_hostname = None
    if service_coordinator.data:
        server_info = service_coordinator.data.get("server", {})
        server_hostname = server_info.get("hostname")

    _LOGGER.debug("Server hostname: %s", server_hostname)

    # Create main receiver entity (represents PulseAudio/PipeWire server)
    entities = [
        OdioReceiverMediaPlayer(
            audio_coordinator,
            service_coordinator,
            api_url,
            session,
            config_entry.entry_id,
        )
    ]

    # Track which clients are handled by services
    handled_client_patterns = set()

    # Create service entities (audio clients/players with systemd services)
    # Excludes: pulseaudio.service, pipewire-pulse.service (they ARE the server)
    #          mpd-discplayer.service (just relays to MPD)
    if service_coordinator.data:
        services = service_coordinator.data.get("services", [])
        for service in services:
            if (
                service.get("exists")
                and service.get("enabled")
                and service["name"] in SUPPORTED_SERVICES
            ):
                service_key = f"{service['scope']}/{service['name']}"
                mapped_entity = service_mappings.get(service_key)

                entity = OdioServiceMediaPlayer(
                    audio_coordinator,
                    service_coordinator,
                    api_url,
                    session,
                    config_entry.entry_id,
                    service,
                    mapped_entity,
                )
                entities.append(entity)

                # Track this service's client pattern
                service_name = service["name"].replace(".service", "").lower()
                handled_client_patterns.add(service_name)

    # Create entities for standalone clients (e.g., PipeWire TCP tunnels)
    # These are remote clients (different host) without a local systemd service
    if audio_coordinator.data:
        for client in audio_coordinator.data:
            client_name = client.get("name", "")
            client_host = client.get("host", "")
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()

            # Only create standalone entity for remote clients
            is_remote = server_hostname and client_host and client_host != server_hostname

            if not is_remote:
                continue

            # Skip if this client is already handled by a service entity
            is_handled = any(
                pattern in [client_name.lower(), app, binary]
                for pattern in handled_client_patterns
            )

            if not is_handled and client_name:
                # Create a standalone client entity using the client name as stable identifier
                entity = OdioStandaloneClientMediaPlayer(
                    audio_coordinator,
                    api_url,
                    session,
                    config_entry.entry_id,
                    client,
                    server_hostname,
                )
                entities.append(entity)

    _LOGGER.info("Creating %d media_player entities (1 receiver + %d services + %d standalone clients)",
                 len(entities),
                 len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
                 len([e for e in entities if isinstance(e, OdioStandaloneClientMediaPlayer)]))

    async_add_entities(entities)

    # Track known standalone clients to detect new ones
    known_remote_clients = {
        entity._client_name: entity
        for entity in entities
        if isinstance(entity, OdioStandaloneClientMediaPlayer)
    }

    # Set up listener to detect new remote clients
    @callback
    def _async_check_new_clients():
        """Check for new remote clients and create entities."""
        if not audio_coordinator.data or not server_hostname:
            return

        new_entities = []

        for client in audio_coordinator.data:
            client_name = client.get("name", "")
            client_host = client.get("host", "")
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()

            # Only process remote clients
            is_remote = client_host and client_host != server_hostname
            if not is_remote or not client_name:
                continue

            # Skip if we already have an entity for this client
            if client_name in known_remote_clients:
                continue

            # Skip if handled by a service
            is_handled = any(
                pattern in [client_name.lower(), app, binary]
                for pattern in handled_client_patterns
            )
            if is_handled:
                continue

            # Create new entity for this remote client
            _LOGGER.info("Detected new remote client: '%s' from host '%s'", client_name, client_host)
            entity = OdioStandaloneClientMediaPlayer(
                audio_coordinator,
                api_url,
                session,
                config_entry.entry_id,
                client,
                server_hostname,
            )
            new_entities.append(entity)
            known_remote_clients[client_name] = entity

        if new_entities:
            _LOGGER.info("Adding %d new remote client entities", len(new_entities))
            async_add_entities(new_entities)

    # Listen for coordinator updates
    config_entry.async_on_unload(
        audio_coordinator.async_add_listener(_async_check_new_clients)
    )


class OdioReceiverMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of the main Odio Audio receiver.

    This entity represents the PulseAudio/PipeWire audio server itself.
    It aggregates all audio clients and provides global control.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        audio_coordinator: DataUpdateCoordinator,
        service_coordinator: DataUpdateCoordinator,
        api_url: str,
        session: aiohttp.ClientSession,
        entry_id: str,
    ) -> None:
        """Initialize the receiver."""
        super().__init__(audio_coordinator)
        self._service_coordinator = service_coordinator
        self._api_url = api_url
        self._session = session
        self._attr_unique_id = f"{entry_id}_receiver"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "PulseAudio Receiver",
        }

        if service_coordinator.data:
            server = service_coordinator.data.get("server", {})
            if server:
                self._attr_device_info["sw_version"] = server.get("version")
                self._attr_device_info["configuration_url"] = api_url

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        if not self.coordinator.data:
            return MediaPlayerState.OFF

        # Check if any client is playing
        for client in self.coordinator.data:
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

        # Average volume of all clients
        volumes = [client.get("volume", 0) for client in self.coordinator.data]
        if volumes:
            return sum(volumes) / len(volumes)
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        if not self.coordinator.data:
            return False

        # Check if any client is muted
        return any(client.get("muted", False) for client in self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        if self.coordinator.data:
            attrs["active_clients"] = len(self.coordinator.data)
            attrs["playing_clients"] = sum(
                1 for client in self.coordinator.data if not client.get("corked", True)
            )

        if self._service_coordinator.data:
            server = self._service_coordinator.data.get("server", {})
            if server:
                attrs["server_name"] = server.get("name")
                attrs["server_hostname"] = server.get("hostname")
                attrs["default_sink"] = server.get("default_sink")

        return attrs

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Note: API doesn't support setting volume directly
        # This would need to be implemented in go-odio-api
        _LOGGER.warning("Volume control not yet implemented in API")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        if not self.coordinator.data:
            return

        for client in self.coordinator.data:
            client_name = client.get("name")
            if client_name:
                try:
                    # PulseAudio utilise le name, pas l'id
                    # URL encode le nom pour gérer les espaces et caractères spéciaux
                    encoded_name = quote(client_name, safe='')
                    url = f"{self._api_url}{ENDPOINT_CLIENT_MUTE.format(name=encoded_name)}"
                    _LOGGER.debug("Muting client '%s' at %s", client_name, url)
                    async with self._session.post(url, json={"muted": mute}) as response:
                        response.raise_for_status()
                except aiohttp.ClientError as err:
                    _LOGGER.error("Error muting client '%s': %s", client_name, err)

        await self.coordinator.async_request_refresh()


class OdioServiceMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Odio Audio service (audio client/player).

    Each audio client service (MPD, Snapcast, Spotifyd, etc.) that sends
    audio through PulseAudio/PipeWire gets its own entity.

    Excluded services:
    - pulseaudio.service / pipewire-pulse.service: They ARE the server
    - mpd-discplayer.service: Just relays to MPD
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        audio_coordinator: DataUpdateCoordinator,
        service_coordinator: DataUpdateCoordinator,
        api_url: str,
        session: aiohttp.ClientSession,
        entry_id: str,
        service_info: dict[str, Any],
        mapped_entity: str | None = None,
    ) -> None:
        """Initialize the service."""
        super().__init__(audio_coordinator)
        self._service_coordinator = service_coordinator
        self._api_url = api_url
        self._session = session
        self._service_info = service_info
        self._mapped_entity = mapped_entity
        self._hass = None  # Will be set in async_added_to_hass

        service_name = service_info["name"]
        scope = service_info["scope"]

        self._attr_unique_id = f"{entry_id}_service_{scope}_{service_name}"
        self._attr_name = f"{service_name} ({scope})"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "PulseAudio Receiver",
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._hass = self.hass

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()

        # Also listen to service coordinator
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
        # If mapped to another entity, use its state when service is running
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                # Check if service is running first
                service_running = self._is_service_running()
                if not service_running:
                    return MediaPlayerState.OFF

                # Map the state from the mapped entity
                if mapped_state.state == "playing":
                    return MediaPlayerState.PLAYING
                elif mapped_state.state == "paused":
                    return MediaPlayerState.PAUSED
                elif mapped_state.state in ["idle", "on"]:
                    return MediaPlayerState.IDLE
                elif mapped_state.state == "off":
                    return MediaPlayerState.OFF

        # Fallback to original logic
        service_running = self._is_service_running()
        if not service_running:
            return MediaPlayerState.OFF

        # Check if service has an active audio client
        if self.coordinator.data:
            service_name = self._service_info["name"].replace(".service", "")
            for client in self.coordinator.data:
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
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
                ):
                    return svc.get("running", False)
        return False

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )

        # Add volume control if client is found
        if self._get_client():
            features |= MediaPlayerEntityFeature.VOLUME_SET

        # Add features from mapped entity if available
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state and mapped_state.attributes.get("supported_features"):
                mapped_features = mapped_state.attributes["supported_features"]

                # Add relevant features from the mapped entity
                if mapped_features & MediaPlayerEntityFeature.PLAY:
                    features |= MediaPlayerEntityFeature.PLAY
                if mapped_features & MediaPlayerEntityFeature.PAUSE:
                    features |= MediaPlayerEntityFeature.PAUSE
                if mapped_features & MediaPlayerEntityFeature.STOP:
                    features |= MediaPlayerEntityFeature.STOP
                if mapped_features & MediaPlayerEntityFeature.NEXT_TRACK:
                    features |= MediaPlayerEntityFeature.NEXT_TRACK
                if mapped_features & MediaPlayerEntityFeature.PREVIOUS_TRACK:
                    features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
                if mapped_features & MediaPlayerEntityFeature.SEEK:
                    features |= MediaPlayerEntityFeature.SEEK
                if mapped_features & MediaPlayerEntityFeature.SELECT_SOURCE:
                    features |= MediaPlayerEntityFeature.SELECT_SOURCE
                if mapped_features & MediaPlayerEntityFeature.SHUFFLE_SET:
                    features |= MediaPlayerEntityFeature.SHUFFLE_SET
                if mapped_features & MediaPlayerEntityFeature.REPEAT_SET:
                    features |= MediaPlayerEntityFeature.REPEAT_SET

        return features

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Prefer mapped entity volume if available
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                volume = mapped_state.attributes.get("volume_level")
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
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                muted = mapped_state.attributes.get("is_volume_muted")
                if muted is not None:
                    return muted

        # Fallback to client mute
        client = self._get_client()
        if client:
            return client.get("muted", False)
        return False

    @property
    def media_content_id(self) -> str | None:
        """Content ID of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_content_id")
        return None

    @property
    def media_content_type(self) -> str | None:
        """Content type of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_content_type")
        return None

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_duration")
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_position")
        return None

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_position_updated_at")
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_title")
        return None

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_artist")
        return None

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_album_name")
        return None

    @property
    def media_track(self) -> int | None:
        """Track number of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("media_track")
        return None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("entity_picture")
        return None

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("shuffle")
        return None

    @property
    def repeat(self) -> str | None:
        """Return current repeat mode."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("repeat")
        return None

    @property
    def source(self) -> str | None:
        """Name of the current input source."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("source")
        return None

    @property
    def source_list(self) -> list[str] | None:
        """List of available input sources."""
        if self._mapped_entity and self._hass:
            mapped_state = self._hass.states.get(self._mapped_entity)
            if mapped_state:
                return mapped_state.attributes.get("source_list")
        return None

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
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
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
        for client in self.coordinator.data:
            client_name = client.get("name", "").lower()
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()

            if service_name in [client_name, app, binary]:
                return client

        return None

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        _LOGGER.debug("Turning on service %s/%s", self._service_info["scope"], self._service_info["name"])

        # Enable the service first, then restart it
        await self._control_service("enable")
        await asyncio.sleep(0.5)  # Small delay between enable and restart
        await self._control_service("restart")

        # Wait a bit longer before refreshing to let the service start
        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        await asyncio.sleep(0.5)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        _LOGGER.debug("Turning off service %s/%s", self._service_info["scope"], self._service_info["name"])
        await self._control_service("disable")

        # Wait for service to stop
        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        await asyncio.sleep(0.5)
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        """Send play command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating play to %s", self._mapped_entity)
            await self._hass.services.async_call(
                "media_player",
                "media_play",
                {"entity_id": self._mapped_entity},
                blocking=True,
            )

    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating pause to %s", self._mapped_entity)
            await self._hass.services.async_call(
                "media_player",
                "media_pause",
                {"entity_id": self._mapped_entity},
                blocking=True,
            )

    async def async_media_stop(self) -> None:
        """Send stop command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating stop to %s", self._mapped_entity)
            await self._hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": self._mapped_entity},
                blocking=True,
            )

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating next_track to %s", self._mapped_entity)
            await self._hass.services.async_call(
                "media_player",
                "media_next_track",
                {"entity_id": self._mapped_entity},
                blocking=True,
            )

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating previous_track to %s", self._mapped_entity)
            await self._hass.services.async_call(
                "media_player",
                "media_previous_track",
                {"entity_id": self._mapped_entity},
                blocking=True,
            )

    async def async_media_seek(self, position: float) -> None:
        """Send seek command."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating seek to %s (position=%s)", self._mapped_entity, position)
            await self._hass.services.async_call(
                "media_player",
                "media_seek",
                {"entity_id": self._mapped_entity, "seek_position": position},
                blocking=True,
            )

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle mode."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating shuffle to %s (shuffle=%s)", self._mapped_entity, shuffle)
            await self._hass.services.async_call(
                "media_player",
                "shuffle_set",
                {"entity_id": self._mapped_entity, "shuffle": shuffle},
                blocking=True,
            )

    async def async_set_repeat(self, repeat: str) -> None:
        """Set repeat mode."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating repeat to %s (repeat=%s)", self._mapped_entity, repeat)
            await self._hass.services.async_call(
                "media_player",
                "repeat_set",
                {"entity_id": self._mapped_entity, "repeat": repeat},
                blocking=True,
            )

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating select_source to %s (source=%s)", self._mapped_entity, source)
            await self._hass.services.async_call(
                "media_player",
                "select_source",
                {"entity_id": self._mapped_entity, "source": source},
                blocking=True,
            )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Delegate to mapped entity if available
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating volume_level to %s (volume=%s)", self._mapped_entity, volume)
            await self._hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": self._mapped_entity, "volume_level": volume},
                blocking=True,
            )
        else:
            _LOGGER.warning("Volume control not yet implemented in API")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        # Try mapped entity first
        if self._mapped_entity and self._hass:
            _LOGGER.debug("Delegating mute to %s (mute=%s)", self._mapped_entity, mute)
            try:
                await self._hass.services.async_call(
                    "media_player",
                    "volume_mute",
                    {"entity_id": self._mapped_entity, "is_volume_muted": mute},
                    blocking=True,
                )
                return
            except Exception as err:
                _LOGGER.warning("Failed to delegate mute to %s: %s, falling back to PulseAudio",
                              self._mapped_entity, err)

        # Fallback to PulseAudio client mute
        client = self._get_client()
        if not client:
            _LOGGER.warning("No client found for service %s/%s, cannot mute",
                          self._service_info["scope"], self._service_info["name"])
            return

        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return

        try:
            # PulseAudio utilise le name, pas l'id
            # URL encode le nom pour gérer les espaces et caractères spéciaux
            encoded_name = quote(client_name, safe='')
            url = f"{self._api_url}{ENDPOINT_CLIENT_MUTE.format(name=encoded_name)}"
            _LOGGER.debug("Muting client '%s' at %s with muted=%s", client_name, url, mute)
            async with self._session.post(url, json={"muted": mute}) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except aiohttp.ClientError as err:
            _LOGGER.error("Error muting client '%s': %s", client_name, err)

    async def _control_service(self, action: str) -> None:
        """Control the service (enable/disable/restart)."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]

        endpoint_map = {
            "enable": ENDPOINT_SERVICE_ENABLE,
            "disable": ENDPOINT_SERVICE_DISABLE,
            "restart": ENDPOINT_SERVICE_RESTART,
        }

        endpoint = endpoint_map.get(action)
        if not endpoint:
            _LOGGER.error("Unknown service action: %s", action)
            return

        try:
            url = f"{self._api_url}{endpoint.format(scope=scope, unit=unit)}"
            _LOGGER.debug("Controlling service %s/%s: %s at %s", scope, unit, action, url)
            async with self._session.post(url) as response:
                response.raise_for_status()
                _LOGGER.info("Successfully %sd service %s/%s", action, scope, unit)
        except aiohttp.ClientError as err:
            _LOGGER.error("Error controlling service %s/%s (%s): %s", scope, unit, action, err)


class OdioStandaloneClientMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a standalone audio client (e.g., PipeWire TCP tunnel).

    These are remote audio clients that connect directly to PulseAudio/PipeWire
    from a different host (TCP tunnels, network streams, etc.)

    Uses client NAME as stable identifier, not ID (which changes on reconnection).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        audio_coordinator: DataUpdateCoordinator,
        api_url: str,
        session: aiohttp.ClientSession,
        entry_id: str,
        initial_client: dict[str, Any],
        server_hostname: str | None = None,
    ) -> None:
        """Initialize the standalone client."""
        super().__init__(audio_coordinator)
        self._api_url = api_url
        self._session = session
        self._server_hostname = server_hostname

        # Use client NAME as stable identifier (ID changes on reconnection)
        self._client_name = initial_client.get("name", "")
        self._client_host = initial_client.get("host", "")

        # Generate a stable unique_id from the client name
        # Sanitize the name for use in entity_id
        import re
        safe_name = re.sub(r'[^a-z0-9_]+', '_', self._client_name.lower()).strip('_')

        self._attr_unique_id = f"{entry_id}_remote_{safe_name}"
        self._attr_name = self._client_name

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "PulseAudio Receiver",
        }

        _LOGGER.debug("Created standalone client entity for '%s' from host '%s' with unique_id '%s'",
                     self._client_name, self._client_host, self._attr_unique_id)

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        client = self._get_current_client()

        if not client:
            # Client is not in the current list - it's disconnected
            return MediaPlayerState.OFF

        # Client exists - check if it's playing
        if not client.get("corked", True):
            return MediaPlayerState.PLAYING

        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        # Standalone clients only support mute and volume
        return MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.VOLUME_SET

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        client = self._get_current_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
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
        # Entity is always available, but state will be OFF if disconnected
        return True

    def _get_current_client(self) -> dict[str, Any] | None:
        """Get the current client data from coordinator by NAME."""
        if not self.coordinator.data:
            return None

        # Find client by NAME (stable across reconnections)
        for client in self.coordinator.data:
            if client.get("name") == self._client_name:
                return client

        return None

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        _LOGGER.warning("Volume control not yet implemented in API")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        client = self._get_current_client()
        if not client:
            _LOGGER.warning("Remote client '%s' is not connected, cannot mute", self._client_name)
            return

        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return

        try:
            # PulseAudio utilise le name, pas l'id
            encoded_name = quote(client_name, safe='')
            url = f"{self._api_url}{ENDPOINT_CLIENT_MUTE.format(name=encoded_name)}"
            _LOGGER.debug("Muting remote client '%s' (host: %s) at %s with muted=%s",
                         client_name, self._client_host, url, mute)
            async with self._session.post(url, json={"muted": mute}) as response:
                response.raise_for_status()
            await self.coordinator.async_request_refresh()
        except aiohttp.ClientError as err:
            _LOGGER.error("Error muting remote client '%s': %s", client_name, err)
