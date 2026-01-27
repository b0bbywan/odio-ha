import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
)
from .const import (
    CONF_SERVICE_MAPPINGS,
)

_LOGGER = logging.getLogger(__name__)


class MappedEntityMixin:
    """Mixin for entities that can delegate to mapped entities."""

    _hass: HomeAssistant | None
    _entry_id: str

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings. Override in subclass."""
        raise NotImplementedError

    @property
    def mapped_entity(self) -> str | None:
        """Get current mapped entity from config (dynamic lookup)."""
        if not self._hass:
            return None
        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if not entry:
            return None
        mappings = entry.options.get(CONF_SERVICE_MAPPINGS, {})
        return mappings.get(self._mapping_key)

    def _get_supported_features(
        self,
        base_features: MediaPlayerEntityFeature,
        mapped_features: MediaPlayerEntityFeature | None,
    ) -> MediaPlayerEntityFeature:
        """Add mapped features to base features."""
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

    def _get_mapped_state(self):
        """Get the state object of the mapped entity."""
        if not self.mapped_entity or not self._hass:
            return None
        return self._hass.states.get(self.mapped_entity)

    def _get_mapped_attribute(self, attribute: str) -> Any | None:
        """Get an attribute from the mapped entity."""
        mapped_state = self._get_mapped_state()
        if mapped_state:
            return mapped_state.attributes.get(attribute)
        return None

    async def _delegate_to_hass(self, service: str, data: dict | None = None) -> bool:
        """Delegate a media_player service call to the mapped entity."""
        if not self.mapped_entity or not self._hass:
            _LOGGER.debug("No mapped entity available for %s", service)
            return False

        if data is None:
            data = {}

        data.setdefault("entity_id", self.mapped_entity)
        _LOGGER.debug("Delegating %s to %s with %s", service, self.mapped_entity, data)

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
                "Failed to delegate %s to %s: %s", service, self.mapped_entity, err
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
