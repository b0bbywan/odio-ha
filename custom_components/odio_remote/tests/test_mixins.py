"""Tests for MappedEntityMixin."""
import pytest
from unittest.mock import Mock, AsyncMock
from dataclasses import dataclass

from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)

from custom_components.odio_remote.mixins import MappedEntityMixin


@dataclass
class MockRuntimeData:
    """Mock runtime data."""

    service_mappings: dict


class MockConfigEntry:
    """Mock config entry with runtime_data."""

    def __init__(self, service_mappings=None):
        self.runtime_data = MockRuntimeData(
            service_mappings=service_mappings or {},
        )


class MockCoordinator:
    """Mock coordinator with config_entry."""

    def __init__(self, config_entry=None):
        self.config_entry = config_entry or MockConfigEntry()


class ConcreteMappedEntity(MappedEntityMixin):
    """Concrete implementation of MappedEntityMixin for testing."""

    def __init__(self, hass, coordinator, mapping_key):
        self.hass = hass
        self.coordinator = coordinator
        self._mapping_key_value = mapping_key

    @property
    def _mapping_key(self):
        return self._mapping_key_value


def _make_entity(mapping_key="test", mapped_id=None, hass=None, state_obj=None):
    """Build a ConcreteMappedEntity with sensible defaults."""
    mappings = {mapping_key: mapped_id} if mapped_id else {}
    coordinator = MockCoordinator(MockConfigEntry(service_mappings=mappings))
    if hass is None:
        hass = Mock()
        if state_obj is not None:
            hass.states.get.return_value = state_obj
        else:
            hass.states.get.return_value = None
    return ConcreteMappedEntity(hass, coordinator, mapping_key)


def _make_state(state_str="playing", **attrs):
    """Build a mock state object."""
    s = Mock()
    s.state = state_str
    s.attributes = attrs
    return s


# ---------------------------------------------------------------------------
# _mapped_entity
# ---------------------------------------------------------------------------


class TestMappedEntity:

    def test_returns_mapped_id(self):
        entity = _make_entity("user/mpd.service", "media_player.mpd")
        assert entity._mapped_entity == "media_player.mpd"

    def test_returns_none_when_no_mapping(self):
        entity = _make_entity("user/mpd.service")
        assert entity._mapped_entity is None

    def test_returns_none_when_no_config_entry(self):
        entity = ConcreteMappedEntity(Mock(), Mock(config_entry=None), "test")
        assert entity._mapped_entity is None


# ---------------------------------------------------------------------------
# _get_mapped_state / _get_mapped_attribute
# ---------------------------------------------------------------------------


class TestMappedAttributes:

    def test_returns_attribute(self):
        state = _make_state(media_title="Song", media_artist="Artist")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        assert entity._get_mapped_attribute("media_title") == "Song"
        assert entity._get_mapped_attribute("media_artist") == "Artist"

    def test_returns_none_for_missing_attribute(self):
        state = _make_state()
        entity = _make_entity("k", "media_player.x", state_obj=state)
        assert entity._get_mapped_attribute("nonexistent") is None

    def test_returns_none_when_no_state(self):
        entity = _make_entity("k", "media_player.x")
        assert entity._get_mapped_attribute("media_title") is None

    def test_returns_none_when_no_mapped_entity(self):
        entity = _make_entity("k")
        assert entity._get_mapped_attribute("media_title") is None

    def test_returns_none_when_no_hass(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass = None
        assert entity._get_mapped_state() is None


# ---------------------------------------------------------------------------
# _get_supported_features
# ---------------------------------------------------------------------------


class TestGetSupportedFeatures:

    def test_returns_base_when_no_mapped(self):
        entity = _make_entity()
        base = MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
        assert entity._get_supported_features(base, None) == base

    def test_merges_delegatable_features(self):
        entity = _make_entity()
        base = MediaPlayerEntityFeature.TURN_ON
        mapped = MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.SEEK
        result = entity._get_supported_features(base, mapped)
        assert result & MediaPlayerEntityFeature.TURN_ON
        assert result & MediaPlayerEntityFeature.PLAY
        assert result & MediaPlayerEntityFeature.PAUSE
        assert result & MediaPlayerEntityFeature.SEEK

    def test_does_not_merge_non_delegatable(self):
        entity = _make_entity()
        base = MediaPlayerEntityFeature(0)
        mapped = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.PLAY
        result = entity._get_supported_features(base, mapped)
        assert result & MediaPlayerEntityFeature.PLAY
        assert not (result & MediaPlayerEntityFeature.VOLUME_SET)

    def test_all_delegatable_features(self):
        entity = _make_entity()
        base = MediaPlayerEntityFeature(0)
        mapped = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.SHUFFLE_SET
            | MediaPlayerEntityFeature.REPEAT_SET
        )
        result = entity._get_supported_features(base, mapped)
        for f in [
            MediaPlayerEntityFeature.PLAY,
            MediaPlayerEntityFeature.PAUSE,
            MediaPlayerEntityFeature.STOP,
            MediaPlayerEntityFeature.NEXT_TRACK,
            MediaPlayerEntityFeature.PREVIOUS_TRACK,
            MediaPlayerEntityFeature.SEEK,
            MediaPlayerEntityFeature.SELECT_SOURCE,
            MediaPlayerEntityFeature.SHUFFLE_SET,
            MediaPlayerEntityFeature.REPEAT_SET,
        ]:
            assert result & f


# ---------------------------------------------------------------------------
# _delegate_to_hass
# ---------------------------------------------------------------------------


class TestDelegateToHass:

    @pytest.mark.asyncio
    async def test_success(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        result = await entity._delegate_to_hass("media_play")
        assert result is True
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "media_play",
            {"entity_id": "media_player.x"}, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_with_extra_data(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        result = await entity._delegate_to_hass("volume_set", {"volume_level": 0.7})
        assert result is True
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "volume_set",
            {"entity_id": "media_player.x", "volume_level": 0.7}, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_failure(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock(side_effect=Exception("boom"))
        result = await entity._delegate_to_hass("media_play")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_mapping(self):
        entity = _make_entity("k")
        result = await entity._delegate_to_hass("media_play")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_hass(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass = None
        result = await entity._delegate_to_hass("media_play")
        assert result is False


# ---------------------------------------------------------------------------
# _map_state_from_entity
# ---------------------------------------------------------------------------


class TestMapStateFromEntity:

    def test_playing(self):
        state = _make_state("playing")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: True)
        assert result == MediaPlayerState.PLAYING

    def test_paused(self):
        state = _make_state("paused")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: True)
        assert result == MediaPlayerState.PAUSED

    def test_idle(self):
        state = _make_state("idle")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: True)
        assert result == MediaPlayerState.IDLE

    def test_on_maps_to_idle(self):
        state = _make_state("on")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: True)
        assert result == MediaPlayerState.IDLE

    def test_off_returns_none(self):
        """Mapped entity 'off' doesn't map — caller decides."""
        state = _make_state("off")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: True)
        assert result is None

    def test_unavailable_returns_off(self):
        state = _make_state("playing")
        entity = _make_entity("k", "media_player.x", state_obj=state)
        result = entity._map_state_from_entity(lambda: False)
        assert result == MediaPlayerState.OFF

    def test_no_mapping_returns_none(self):
        entity = _make_entity("k")
        result = entity._map_state_from_entity(lambda: True)
        assert result is None

    def test_no_state_returns_none(self):
        entity = _make_entity("k", "media_player.x")
        result = entity._map_state_from_entity(lambda: True)
        assert result is None


# ---------------------------------------------------------------------------
# Delegated media properties
# ---------------------------------------------------------------------------


class TestDelegatedMediaProperties:

    def _entity_with_attrs(self, **attrs):
        state = _make_state(**attrs)
        return _make_entity("k", "media_player.x", state_obj=state)

    def test_media_content_id(self):
        e = self._entity_with_attrs(media_content_id="abc")
        assert e.media_content_id == "abc"

    def test_media_content_type(self):
        e = self._entity_with_attrs(media_content_type="music")
        assert e.media_content_type == "music"

    def test_media_duration(self):
        e = self._entity_with_attrs(media_duration=300)
        assert e.media_duration == 300

    def test_media_position(self):
        e = self._entity_with_attrs(media_position=120)
        assert e.media_position == 120

    def test_media_position_updated_at(self):
        e = self._entity_with_attrs(media_position_updated_at="2026-01-01")
        assert e.media_position_updated_at == "2026-01-01"

    def test_media_title(self):
        e = self._entity_with_attrs(media_title="Song")
        assert e.media_title == "Song"

    def test_media_artist(self):
        e = self._entity_with_attrs(media_artist="Artist")
        assert e.media_artist == "Artist"

    def test_media_album_name(self):
        e = self._entity_with_attrs(media_album_name="Album")
        assert e.media_album_name == "Album"

    def test_media_track(self):
        e = self._entity_with_attrs(media_track=5)
        assert e.media_track == 5

    def test_media_image_url(self):
        e = self._entity_with_attrs(entity_picture="http://img.jpg")
        assert e.media_image_url == "http://img.jpg"

    def test_shuffle(self):
        e = self._entity_with_attrs(shuffle=True)
        assert e.shuffle is True

    def test_repeat(self):
        e = self._entity_with_attrs(repeat="all")
        assert e.repeat == "all"

    def test_source(self):
        e = self._entity_with_attrs(source="Spotify")
        assert e.source == "Spotify"

    def test_source_list(self):
        e = self._entity_with_attrs(source_list=["A", "B"])
        assert e.source_list == ["A", "B"]

    def test_all_return_none_without_mapping(self):
        entity = _make_entity("k")
        assert entity.media_content_id is None
        assert entity.media_content_type is None
        assert entity.media_duration is None
        assert entity.media_position is None
        assert entity.media_position_updated_at is None
        assert entity.media_title is None
        assert entity.media_artist is None
        assert entity.media_album_name is None
        assert entity.media_track is None
        assert entity.media_image_url is None
        assert entity.shuffle is None
        assert entity.repeat is None
        assert entity.source is None
        assert entity.source_list is None


# ---------------------------------------------------------------------------
# Delegated media control actions
# ---------------------------------------------------------------------------


class TestDelegatedMediaActions:

    @pytest.mark.asyncio
    async def test_async_media_play(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_play()
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_media_pause(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_pause()
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_media_stop(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_stop()
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_media_next_track(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_next_track()
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_media_previous_track(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_previous_track()
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_media_seek(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_media_seek(30.0)
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "media_seek",
            {"entity_id": "media_player.x", "seek_position": 30.0}, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_async_set_shuffle(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_set_shuffle(True)
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "shuffle_set",
            {"entity_id": "media_player.x", "shuffle": True}, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_async_set_repeat(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_set_repeat(RepeatMode.ALL)
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "repeat_set",
            {"entity_id": "media_player.x", "repeat": RepeatMode.ALL}, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_async_select_source(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        await entity.async_select_source("Radio")
        entity.hass.services.async_call.assert_called_once_with(
            "media_player", "select_source",
            {"entity_id": "media_player.x", "source": "Radio"}, blocking=True,
        )


# ---------------------------------------------------------------------------
# _control_with_fallback / _set_volume_with_fallback / _mute_with_fallback
# ---------------------------------------------------------------------------


class TestControlWithFallback:

    @pytest.mark.asyncio
    async def test_delegates_first_when_mapped(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        api = Mock()
        api.set_client_volume = AsyncMock()
        await entity._set_volume_with_fallback(0.5, lambda: "client1", api)
        entity.hass.services.async_call.assert_called_once()
        api.set_client_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_api_when_delegation_fails(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock(side_effect=Exception("fail"))
        api = Mock()
        api.set_client_volume = AsyncMock()
        await entity._set_volume_with_fallback(0.5, lambda: "client1", api)
        api.set_client_volume.assert_awaited_once_with("client1", 0.5)

    @pytest.mark.asyncio
    async def test_falls_back_to_api_when_no_mapping(self):
        entity = _make_entity("k")
        api = Mock()
        api.set_client_volume = AsyncMock()
        await entity._set_volume_with_fallback(0.5, lambda: "client1", api)
        api.set_client_volume.assert_awaited_once_with("client1", 0.5)

    @pytest.mark.asyncio
    async def test_fallback_no_client_name(self):
        entity = _make_entity("k")
        api = Mock()
        api.set_client_volume = AsyncMock()
        await entity._set_volume_with_fallback(0.5, lambda: None, api)
        api.set_client_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_mute_delegates_first(self):
        entity = _make_entity("k", "media_player.x")
        entity.hass.services.async_call = AsyncMock()
        api = Mock()
        api.set_client_mute = AsyncMock()
        await entity._mute_with_fallback(True, lambda: "client1", api)
        entity.hass.services.async_call.assert_called_once()
        api.set_client_mute.assert_not_called()

    @pytest.mark.asyncio
    async def test_mute_falls_back(self):
        entity = _make_entity("k")
        api = Mock()
        api.set_client_mute = AsyncMock()
        await entity._mute_with_fallback(True, lambda: "client1", api)
        api.set_client_mute.assert_awaited_once_with("client1", True)


class TestMappingKeyFunctions:
    """Tests for config_flow_helpers key functions."""

    def test_get_service_keys(self):
        from custom_components.odio_remote.config_flow_helpers import get_service_keys
        service = {"scope": "user", "name": "mpd.service"}
        form_key, mapping_key = get_service_keys(service)
        assert form_key == "user_mpd.service"
        assert mapping_key == "user/mpd.service"

    def test_get_client_keys(self):
        from custom_components.odio_remote.config_flow_helpers import get_client_keys
        client = {"name": "Tunnel for bobby@bobby-desktop"}
        form_key, mapping_key = get_client_keys(client)
        assert form_key == "client_tunnel_for_bobby_bobby_desktop"
        assert mapping_key == "client:Tunnel for bobby@bobby-desktop"

    def test_get_client_keys_special_chars(self):
        from custom_components.odio_remote.config_flow_helpers import get_client_keys
        client = {"name": "Test!@#$%Client-123"}
        form_key, mapping_key = get_client_keys(client)
        assert form_key == "client_test_client_123"
        assert mapping_key == "client:Test!@#$%Client-123"

    def test_get_client_keys_empty_name(self):
        from custom_components.odio_remote.config_flow_helpers import get_client_keys
        client = {"name": ""}
        form_key, mapping_key = get_client_keys(client)
        assert form_key == ""
        assert mapping_key == ""
