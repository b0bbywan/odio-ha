"""MPRIS media player platform for Odio Audio integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api_client import OdioApiClient
from .const import DOMAIN
from .mixins import MappedSwitchMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio MPRIS media players from a config entry."""
    coordinator_data = hass.data[DOMAIN][entry.entry_id]
    service_coordinator = coordinator_data["service_coordinator"]
    api: OdioApiClient = coordinator_data["api"]

    # Get players and services from coordinator data
    players = service_coordinator.data.get("players", [])
    services = service_coordinator.data.get("services", [])
    server = service_coordinator.data.get("server", {})

    _LOGGER.debug("Setting up MPRIS players: %d found", len(players))

    # Build mapping from player name to potential switch entity_id
    # Format: player "firefox.instance12345" -> service "firefox-kiosk@www.netflix.com.service"
    player_to_switch = _build_player_switch_mapping(players, services, server.get("hostname", "odio"))

    entities = []
    for player in players:
        player_name = player.get("name", "")
        _LOGGER.debug("Creating MPRIS player for: %s", player_name)

        mapped_switch = player_to_switch.get(player_name)
        entities.append(
            OdioMPRISMediaPlayer(
                service_coordinator,
                api,
                player,
                server,
                entry.entry_id,
                mapped_switch,
            )
        )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d MPRIS media player entities", len(entities))


def _build_player_switch_mapping(
    players: list[dict[str, Any]],
    services: list[dict[str, Any]],
    hostname: str,
) -> dict[str, str]:
    """Build mapping from MPRIS player name to switch entity_id.

    Args:
        players: List of MPRIS players
        services: List of systemd services
        hostname: Server hostname

    Returns:
        Dictionary mapping player name to switch entity_id
    """
    mapping = {}

    for player in players:
        player_name = player.get("name", "")
        if not player_name:
            continue

        # Try to find matching service
        # Example: player "firefox.instance123" matches service "firefox-kiosk@www.netflix.com.service"
        for service in services:
            if service.get("scope") != "user":
                continue

            unit = service.get("unit", "")
            # Simple heuristic: if player name starts with first part of unit name
            # e.g., "firefox" in "firefox.instance123" matches "firefox-kiosk@..."
            unit_prefix = unit.split(".")[0].split("@")[0].split("-")[0]
            player_prefix = player_name.split(".")[0]

            if player_prefix == unit_prefix or unit_prefix in player_prefix:
                # Found a match, generate switch entity_id
                sanitized = unit.replace(".service", "").replace("@", "_").replace(".", "_")
                switch_entity_id = f"switch.{hostname}_{sanitized}"
                mapping[player_name] = switch_entity_id
                _LOGGER.debug(
                    "Mapped player %s to switch %s (service: %s)",
                    player_name,
                    switch_entity_id,
                    unit,
                )
                break

    return mapping


class OdioMPRISMediaPlayer(MappedSwitchMixin, CoordinatorEntity, MediaPlayerEntity):
    """MPRIS media player entity with full native MPRIS support."""

    def __init__(
        self,
        coordinator,
        api: OdioApiClient,
        player: dict[str, Any],
        server: dict[str, Any],
        entry_id: str,
        mapped_switch_id: str | None = None,
    ) -> None:
        """Initialize the MPRIS media player."""
        super().__init__(coordinator)
        self._api = api
        self._player_name = player.get("name", "")
        self._entry_id = entry_id
        self._mapped_switch_id = mapped_switch_id

        # Device info from server
        self._server_name = server.get("name", "Odio Audio")
        self._server_hostname = server.get("hostname", "unknown")
        self._server_version = server.get("version", "unknown")

        # Generate unique_id and entity_id
        # Example: media_player.odio_firefox for firefox.instance123
        sanitized_name = self._player_name.replace(".", "_").replace("@", "_")
        self._attr_unique_id = f"{self._server_hostname}_mpris_{sanitized_name}"

        # Try to get a nice name from player identity if available
        identity = player.get("identity", "")
        if identity:
            self._attr_name = f"{self._server_name} {identity}"
        else:
            self._attr_name = f"{self._server_name} {sanitized_name.replace('_', ' ').title()}"

        _LOGGER.debug(
            "Initialized MPRIS player: unique_id=%s, name=%s, player=%s, switch=%s",
            self._attr_unique_id,
            self._attr_name,
            self._player_name,
            self._mapped_switch_id,
        )

    @property
    def _hass(self):
        """Return HomeAssistant instance for MappedSwitchMixin."""
        return self.hass

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._server_hostname)},
            name=self._server_name,
            manufacturer="Odio",
            model="Audio Server",
            sw_version=self._server_version,
        )

    @property
    def _player_data(self) -> dict[str, Any] | None:
        """Get current player data from coordinator."""
        players = self.coordinator.data.get("players", [])
        for player in players:
            if player.get("name") == self._player_name:
                return player
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Check if mapped switch exists and if so, whether service is running
        if self._mapped_switch_id:
            # Check if switch is on (service running)
            switch_state = self.hass.states.get(self._mapped_switch_id)
            if not switch_state or switch_state.state != "on":
                return False

        # Check if player exists in coordinator data
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

        # MPRIS control capabilities
        if player.get("can_play"):
            features |= MediaPlayerEntityFeature.PLAY
        if player.get("can_pause"):
            features |= MediaPlayerEntityFeature.PAUSE
        # Stop is always available if we can control
        if player.get("can_control"):
            features |= MediaPlayerEntityFeature.STOP
        if player.get("can_go_next"):
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if player.get("can_go_previous"):
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if player.get("can_seek"):
            features |= MediaPlayerEntityFeature.SEEK

        # Volume control
        if player.get("can_control") and player.get("volume") is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP

        # Shuffle and repeat
        if player.get("shuffle") is not None:
            features |= MediaPlayerEntityFeature.SHUFFLE_SET
        if player.get("loop_status") is not None:
            features |= MediaPlayerEntityFeature.REPEAT_SET

        return features

    # =========================================================================
    # Media properties from MPRIS
    # =========================================================================

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
        # MPRIS doesn't provide this, default to music
        return MediaType.MUSIC

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        player = self._player_data
        if player and player.get("metadata"):
            # MPRIS uses microseconds, convert to seconds
            length_us = player["metadata"].get("mpris:length")
            if length_us is not None:
                return int(length_us / 1_000_000)
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        player = self._player_data
        if player:
            # MPRIS uses microseconds, convert to seconds
            position_us = player.get("position")
            if position_us is not None:
                return int(position_us / 1_000_000)
        return None

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        # Return coordinator's last update time
        return self.coordinator.last_update_success_time

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

        attrs = {
            "player_name": self._player_name,
            "identity": player.get("identity"),
            "desktop_entry": player.get("desktop_entry"),
            "playback_status": player.get("playback_status"),
            "can_control": player.get("can_control"),
            "can_play": player.get("can_play"),
            "can_pause": player.get("can_pause"),
            "can_seek": player.get("can_seek"),
            "can_go_next": player.get("can_go_next"),
            "can_go_previous": player.get("can_go_previous"),
        }

        if self._mapped_switch_id:
            attrs["mapped_switch"] = self._mapped_switch_id

        return attrs

    # =========================================================================
    # Media control actions via MPRIS API
    # =========================================================================

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
        # HA uses seconds, MPRIS uses microseconds
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
