"""Mixin for entities that can delegate to mapped media_player entities."""
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class MediaPlayerMappingMixin:
    """Mixin for entities that can delegate to mapped entities.

    Subclasses must implement:
    - _mapping_key property: returns the key for looking up mappings
    - _hass property: HomeAssistant instance
    - _entry_id property: config entry ID
    """

    _hass: HomeAssistant | None
    _entry_id: str

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings. Must be implemented by subclass."""
        raise NotImplementedError("Subclass must implement _mapping_key")

    @property
    def _mapped_entity(self) -> str | None:
        """Get current mapped entity dynamically from hass.data."""
        if not self._hass:
            return None

        coordinator_data = self._hass.data.get(DOMAIN, {}).get(self._entry_id)
        if not coordinator_data:
            return None

        service_mappings = coordinator_data.get("service_mappings", {})
        return service_mappings.get(self._mapping_key)

    def _get_mapped_state(self):
        """Get the state object of the mapped entity."""
        if not self._mapped_entity or not self._hass:
            return None
        return self._hass.states.get(self._mapped_entity)

    def _get_mapped_attribute(self, attribute: str) -> Any | None:
        """Get an attribute from the mapped entity."""
        mapped_state = self._get_mapped_state()
        if mapped_state:
            return mapped_state.attributes.get(attribute)
        return None

    def _get_supported_features(
        self,
        base_features: MediaPlayerEntityFeature,
        mapped_features: MediaPlayerEntityFeature | None,
    ) -> MediaPlayerEntityFeature:
        """Add mapped features to base features.

        Args:
            base_features: Native features of this entity
            mapped_features: Features from the mapped entity (or None)

        Returns:
            Combined features
        """
        if mapped_features is None:
            return base_features

        features = base_features
        delegatable = {
            MediaPlayerEntityFeature.PLAY,
            MediaPlayerEntityFeature.PAUSE,
            MediaPlayerEntityFeature.STOP,
            MediaPlayerEntityFeature.NEXT_TRACK,
            MediaPlayerEntityFeature.PREVIOUS_TRACK,
            MediaPlayerEntityFeature.SEEK,
            MediaPlayerEntityFeature.SELECT_SOURCE,
            MediaPlayerEntityFeature.SHUFFLE_SET,
            MediaPlayerEntityFeature.REPEAT_SET,
        }

        for feature in delegatable:
            if mapped_features & feature:
                features |= feature

        return features

    async def _delegate_to_hass(self, service: str, data: dict | None = None) -> bool:
        """Delegate a media_player service call to the mapped entity.

        Args:
            service: Service name (e.g., "media_play")
            data: Optional service data

        Returns:
            True if delegation succeeded, False otherwise
        """
        if not self._mapped_entity or not self._hass:
            _LOGGER.debug("No mapped entity available for %s", service)
            return False

        if data is None:
            data = {}

        data.setdefault("entity_id", self._mapped_entity)
        _LOGGER.debug("Delegating %s to %s with %s", service, self._mapped_entity, data)

        try:
            await self._hass.services.async_call(
                "media_player",
                service,
                data,
                blocking=True,
            )
            return True
        except Exception as err:
            _LOGGER.warning(
                "Failed to delegate %s to %s: %s", service, self._mapped_entity, err
            )
            return False

    # =========================================================================
    # Media properties delegated to mapped entity
    # =========================================================================

    @property
    def media_content_id(self) -> str | None:
        """Content ID of current playing media."""
        return self._get_mapped_attribute("media_content_id")

    @property
    def media_content_type(self) -> str | None:
        """Content type of current playing media."""
        return self._get_mapped_attribute("media_content_type")

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        return self._get_mapped_attribute("media_duration")

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        return self._get_mapped_attribute("media_position")

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        return self._get_mapped_attribute("media_position_updated_at")

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self._get_mapped_attribute("media_title")

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        return self._get_mapped_attribute("media_artist")

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        return self._get_mapped_attribute("media_album_name")

    @property
    def media_track(self) -> int | None:
        """Track number of current playing media."""
        return self._get_mapped_attribute("media_track")

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        return self._get_mapped_attribute("entity_picture")

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        return self._get_mapped_attribute("shuffle")

    @property
    def repeat(self) -> str | None:
        """Return current repeat mode."""
        return self._get_mapped_attribute("repeat")

    @property
    def source(self) -> str | None:
        """Name of the current input source."""
        return self._get_mapped_attribute("source")

    @property
    def source_list(self) -> list[str] | None:
        """List of available input sources."""
        return self._get_mapped_attribute("source_list")

    # =========================================================================
    # Media control actions delegated to mapped entity
    # =========================================================================

    async def async_media_play(self) -> None:
        """Send play command."""
        await self._delegate_to_hass("media_play")

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self._delegate_to_hass("media_pause")

    async def async_media_stop(self) -> None:
        """Send stop command."""
        await self._delegate_to_hass("media_stop")

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self._delegate_to_hass("media_next_track")

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self._delegate_to_hass("media_previous_track")

    async def async_media_seek(self, position: float) -> None:
        """Send seek command."""
        await self._delegate_to_hass("media_seek", {"seek_position": position})

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Enable/disable shuffle mode."""
        await self._delegate_to_hass("shuffle_set", {"shuffle": shuffle})

    async def async_set_repeat(self, repeat: str) -> None:
        """Set repeat mode."""
        await self._delegate_to_hass("repeat_set", {"repeat": repeat})

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        await self._delegate_to_hass("select_source", {"source": source})

    # =========================================================================
    # State mapping helper
    # =========================================================================

    def _map_state_from_entity(self, is_available_func) -> MediaPlayerState | None:
        """Map state from mapped entity if available.

        Args:
            is_available_func: Callable that returns truthy if device is available

        Returns:
            Mapped MediaPlayerState or None if no mapping available
        """
        from homeassistant.components.media_player import MediaPlayerState

        if not self._mapped_entity or not self._hass:
            return None

        mapped_state = self._hass.states.get(self._mapped_entity)
        if not mapped_state:
            return None

        # Check availability first
        if not is_available_func():
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

        return None

    # =========================================================================
    # Volume control with delegation fallback
    # =========================================================================

    async def _control_with_fallback(
        self,
        service_name: str,
        service_data: dict,
        get_client_name_func,
        api_client_method,
        *api_args,
    ) -> None:
        """Generic control with delegation to mapped entity first.

        Args:
            service_name: Service to call on mapped entity (e.g., "volume_set")
            service_data: Data for the service call
            get_client_name_func: Callable that returns client name for fallback
            api_client_method: API client method to call for fallback
            *api_args: Additional arguments for api_client_method
        """
        # Try to delegate to mapped entity first
        if await self._delegate_to_hass(service_name, service_data):
            return

        # Fallback to PulseAudio client control
        client_name = get_client_name_func()
        if not client_name:
            import logging
            _LOGGER = logging.getLogger(__name__)
            _LOGGER.warning("Cannot %s: no client name available", service_name)
            return

        await api_client_method(client_name, *api_args)

    async def _set_volume_with_fallback(
        self,
        volume: float,
        get_client_name_func,
        api_client,
    ) -> None:
        """Set volume level with delegation to mapped entity first.

        Args:
            volume: Volume level 0..1
            get_client_name_func: Callable that returns client name for fallback
            api_client: API client for PulseAudio control
        """
        await self._control_with_fallback(
            "volume_set",
            {"volume_level": volume},
            get_client_name_func,
            api_client.set_client_volume,
            volume,
        )

    async def _mute_with_fallback(
        self,
        mute: bool,
        get_client_name_func,
        api_client,
    ) -> None:
        """Mute volume with delegation to mapped entity first.

        Args:
            mute: Mute state
            get_client_name_func: Callable that returns client name for fallback
            api_client: API client for PulseAudio control
        """
        await self._control_with_fallback(
            "volume_mute",
            {"is_volume_muted": mute},
            get_client_name_func,
            api_client.set_client_mute,
            mute,
        )


class SwitchMappingMixin:
    """Mixin for entities that can be controlled by a switch entity.

    This mixin allows a media_player (or other entity) to delegate turn_on/turn_off
    to a switch entity. Useful for MPRIS players that need a systemd service switch
    to start/stop the underlying application.

    Subclasses must implement:
    - _hass property: HomeAssistant instance
    """

    _hass: HomeAssistant | None
    _mapped_switch_id: str | None = None

    async def async_turn_on(self) -> None:
        """Turn on the entity by delegating to mapped switch."""
        if self._mapped_switch_id and self._hass:
            _LOGGER.debug(
                "Delegating turn_on to switch %s", self._mapped_switch_id
            )
            try:
                await self._hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": self._mapped_switch_id},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning(
                    "Failed to turn on switch %s: %s", self._mapped_switch_id, err
                )
        else:
            _LOGGER.debug("No mapped switch available for turn_on")

    async def async_turn_off(self) -> None:
        """Turn off the entity by delegating to mapped switch."""
        if self._mapped_switch_id and self._hass:
            _LOGGER.debug(
                "Delegating turn_off to switch %s", self._mapped_switch_id
            )
            try:
                await self._hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": self._mapped_switch_id},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning(
                    "Failed to turn off switch %s: %s", self._mapped_switch_id, err
                )
        else:
            _LOGGER.debug("No mapped switch available for turn_off")

    def _get_switch_supported_features(
        self, base_features: MediaPlayerEntityFeature
    ) -> MediaPlayerEntityFeature:
        """Add TURN_ON/TURN_OFF features if switch is mapped.

        Args:
            base_features: Base features of the media player

        Returns:
            Features with TURN_ON/TURN_OFF added if switch is mapped
        """
        features = base_features
        if self._mapped_switch_id:
            features |= (
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        return features
