"""Tests for MPRIS coordinator SSE handlers and OdioMPRISMediaPlayer entity."""
import asyncio
import pytest
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState, RepeatMode
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.odio_remote.api_client import SseEvent
from custom_components.odio_remote.coordinator import OdioMPRISCoordinator
from custom_components.odio_remote.media_player import OdioMPRISMediaPlayer, _MediaPlayerContext

from .conftest import MOCK_DEVICE_INFO, MOCK_PLAYERS

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MOCK_SPOTIFY = MOCK_PLAYERS[0]
MOCK_CHROME = MOCK_PLAYERS[1]

EMITTED_AT_MS = 1772649711164  # arbitrary ms timestamp


def _make_hass():
    hass = MagicMock()
    try:
        hass.loop = asyncio.get_running_loop()
    except RuntimeError:
        hass.loop = MagicMock()
    return hass


def _make_mpris_coordinator(api=None):
    coord = OdioMPRISCoordinator(_make_hass(), MagicMock(), api or MagicMock())
    coord.async_set_updated_data = MagicMock()
    return coord


@dataclass
class _MockRuntimeData:
    service_mappings: dict


class _MockConfigEntry:
    def __init__(self, mappings=None):
        self.runtime_data = _MockRuntimeData(service_mappings=mappings or {})


def _make_entity(player_data, extra_players=None, mappings=None, last_update_success=True):
    """Build an OdioMPRISMediaPlayer with a minimal mock coordinator."""
    players = [player_data] + (extra_players or [])
    config_entry = _MockConfigEntry(mappings=mappings or {})

    coordinator = MagicMock()
    coordinator.data = {"mpris": players}
    coordinator.last_update_success = last_update_success
    coordinator.config_entry = config_entry

    ctx = MagicMock(spec=_MediaPlayerContext)
    ctx.mpris_coordinator = coordinator
    ctx.api = MagicMock()
    ctx.event_stream = MagicMock()
    ctx.entry_id = "test_entry"
    ctx.device_info = MOCK_DEVICE_INFO
    ctx.server_hostname = "htpc"

    entity = OdioMPRISMediaPlayer.__new__(OdioMPRISMediaPlayer)
    entity.coordinator = coordinator
    entity.hass = MagicMock()
    entity._api_client = ctx.api
    entity._event_stream = ctx.event_stream
    entity._player_name = player_data["bus_name"]
    entity._attr_unique_id = f"test_entry_mpris_{player_data['bus_name']}"
    entity._attr_name = player_data.get("identity", "Unknown")
    entity._attr_device_info = MOCK_DEVICE_INFO
    return entity


# ===========================================================================
# OdioMPRISCoordinator — _async_update_data
# ===========================================================================


class TestMPRISCoordinatorFetch:

    @pytest.mark.asyncio
    async def test_stamps_position_updated_at_from_header(self):
        """x-cache-updated-at header is parsed and stamped on each player."""
        api = MagicMock()
        api.get_players = AsyncMock(return_value=([MOCK_SPOTIFY], "2026-03-04T19:06:44Z"))
        coord = OdioMPRISCoordinator(_make_hass(), MagicMock(), api)

        result = await coord._async_update_data()

        players = result["mpris"]
        assert len(players) == 1
        ts = players[0]["position_updated_at"]
        assert ts is not None
        assert ts.tzinfo is not None
        assert ts.year == 2026

    @pytest.mark.asyncio
    async def test_falls_back_to_utcnow_when_no_header(self):
        """position_updated_at falls back to utcnow when header is absent."""
        api = MagicMock()
        api.get_players = AsyncMock(return_value=([MOCK_SPOTIFY], None))
        coord = OdioMPRISCoordinator(_make_hass(), MagicMock(), api)

        result = await coord._async_update_data()

        assert result["mpris"][0]["position_updated_at"] is not None

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        api = MagicMock()
        api.get_players = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
        )
        coord = OdioMPRISCoordinator(_make_hass(), MagicMock(), api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        api = MagicMock()
        api.get_players = AsyncMock(side_effect=asyncio.TimeoutError())
        coord = OdioMPRISCoordinator(_make_hass(), MagicMock(), api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ===========================================================================
# OdioMPRISCoordinator — handle_sse_update_event / handle_sse_added_event
# ===========================================================================


class TestMPRISCoordinatorSseUpdate:

    def _coord_with_players(self, players):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": players}
        return coord

    def _sse_event(self, player_data, emitted_at=EMITTED_AT_MS):
        return SseEvent(
            type="player.updated",
            data={"data": player_data, "emitted_at": emitted_at},
        )

    def test_replaces_existing_player_by_bus_name(self):
        coord = self._coord_with_players([MOCK_SPOTIFY])
        updated = {**MOCK_SPOTIFY, "playback_status": "Paused"}
        coord.handle_sse_update_event(self._sse_event(updated))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        assert len(result) == 1
        assert result[0]["playback_status"] == "Paused"

    def test_appends_unknown_player(self):
        coord = self._coord_with_players([MOCK_SPOTIFY])
        coord.handle_sse_update_event(self._sse_event(MOCK_CHROME))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        assert len(result) == 2

    def test_stamps_position_updated_at_from_emitted_at(self):
        coord = self._coord_with_players([])
        coord.handle_sse_update_event(self._sse_event(MOCK_SPOTIFY, emitted_at=EMITTED_AT_MS))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        expected_ts = datetime.fromtimestamp(EMITTED_AT_MS / 1000, tz=timezone.utc)
        assert result[0]["position_updated_at"] == expected_ts

    def test_non_dict_data_ignored(self):
        coord = self._coord_with_players([])
        coord.handle_sse_update_event(SseEvent(type="player.updated", data=["not", "a", "dict"]))
        coord.async_set_updated_data.assert_not_called()

    def test_missing_data_key_ignored(self):
        coord = self._coord_with_players([])
        coord.handle_sse_update_event(
            SseEvent(type="player.updated", data={"emitted_at": EMITTED_AT_MS})
        )
        coord.async_set_updated_data.assert_not_called()

    def test_added_event_appends_new_player(self):
        coord = self._coord_with_players([MOCK_SPOTIFY])
        coord.handle_sse_update_event(
            SseEvent(type="player.added", data={"data": MOCK_CHROME, "emitted_at": EMITTED_AT_MS})
        )
        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        assert len(result) == 2

    def test_works_with_no_existing_data(self):
        coord = _make_mpris_coordinator()
        coord.data = None
        coord.handle_sse_update_event(self._sse_event(MOCK_SPOTIFY))
        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        assert len(result) == 1


# ===========================================================================
# OdioMPRISCoordinator — handle_sse_removed_event
# ===========================================================================


class TestMPRISCoordinatorSseRemoved:

    def test_marks_player_unavailable_and_stopped(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY, MOCK_CHROME]}

        coord.handle_sse_removed_event(
            SseEvent(type="player.removed", data={"bus_name": MOCK_SPOTIFY["bus_name"]})
        )

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        spotify = next(p for p in result if p["bus_name"] == MOCK_SPOTIFY["bus_name"])
        assert spotify["available"] is False
        assert spotify["playback_status"] == "Stopped"

    def test_other_players_unchanged(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY, MOCK_CHROME]}

        coord.handle_sse_removed_event(
            SseEvent(type="player.removed", data={"bus_name": MOCK_SPOTIFY["bus_name"]})
        )

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        chrome = next(p for p in result if p["bus_name"] == MOCK_CHROME["bus_name"])
        assert chrome.get("available", True) is True

    def test_unknown_bus_name_leaves_list_intact(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY]}

        coord.handle_sse_removed_event(
            SseEvent(type="player.removed", data={"bus_name": "org.mpris.MediaPlayer2.ghost"})
        )

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        assert result[0] == MOCK_SPOTIFY

    def test_non_dict_data_ignored(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": []}
        coord.handle_sse_removed_event(SseEvent(type="player.removed", data=["not", "dict"]))
        coord.async_set_updated_data.assert_not_called()

    def test_missing_bus_name_ignored(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": []}
        coord.handle_sse_removed_event(SseEvent(type="player.removed", data={}))
        coord.async_set_updated_data.assert_not_called()


# ===========================================================================
# OdioMPRISCoordinator — handle_sse_position_event
# ===========================================================================


class TestMPRISCoordinatorSsePosition:

    def test_updates_position_and_timestamp_per_player(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY, MOCK_CHROME]}

        coord.handle_sse_position_event(SseEvent(
            type="player.position",
            data=[{
                "bus_name": MOCK_SPOTIFY["bus_name"],
                "position": 99000000,
                "emitted_at": EMITTED_AT_MS,
            }],
        ))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        spotify = next(p for p in result if p["bus_name"] == MOCK_SPOTIFY["bus_name"])
        assert spotify["position"] == 99000000
        expected_ts = datetime.fromtimestamp(EMITTED_AT_MS / 1000, tz=timezone.utc)
        assert spotify["position_updated_at"] == expected_ts

    def test_other_players_not_updated(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY, MOCK_CHROME]}

        original_chrome_pos = MOCK_CHROME["position"]
        coord.handle_sse_position_event(SseEvent(
            type="player.position",
            data=[{"bus_name": MOCK_SPOTIFY["bus_name"], "position": 50000000, "emitted_at": EMITTED_AT_MS}],
        ))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        chrome = next(p for p in result if p["bus_name"] == MOCK_CHROME["bus_name"])
        assert chrome["position"] == original_chrome_pos

    def test_multiple_players_updated_at_once(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY, MOCK_CHROME]}

        coord.handle_sse_position_event(SseEvent(
            type="player.position",
            data=[
                {"bus_name": MOCK_SPOTIFY["bus_name"], "position": 10000000, "emitted_at": EMITTED_AT_MS},
                {"bus_name": MOCK_CHROME["bus_name"], "position": 20000000, "emitted_at": EMITTED_AT_MS + 5000},
            ],
        ))

        result = coord.async_set_updated_data.call_args[0][0]["mpris"]
        by_bus = {p["bus_name"]: p for p in result}
        assert by_bus[MOCK_SPOTIFY["bus_name"]]["position"] == 10000000
        assert by_bus[MOCK_CHROME["bus_name"]]["position"] == 20000000

    def test_non_list_data_ignored(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": []}
        coord.handle_sse_position_event(SseEvent(type="player.position", data={"not": "list"}))
        coord.async_set_updated_data.assert_not_called()

    def test_empty_list_no_update(self):
        coord = _make_mpris_coordinator()
        coord.data = {"mpris": [MOCK_SPOTIFY]}
        coord.handle_sse_position_event(SseEvent(type="player.position", data=[]))
        coord.async_set_updated_data.assert_not_called()


# ===========================================================================
# OdioMPRISMediaPlayer — properties
# ===========================================================================


class TestMPRISEntityProperties:

    def test_state_playing(self):
        entity = _make_entity({**MOCK_SPOTIFY, "playback_status": "Playing"})
        assert entity.state == MediaPlayerState.PLAYING

    def test_state_paused(self):
        entity = _make_entity({**MOCK_SPOTIFY, "playback_status": "Paused"})
        assert entity.state == MediaPlayerState.PAUSED

    def test_state_stopped_is_idle(self):
        entity = _make_entity({**MOCK_SPOTIFY, "playback_status": "Stopped"})
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_coordinator_failed(self):
        entity = _make_entity(MOCK_SPOTIFY, last_update_success=False)
        assert entity.state == MediaPlayerState.OFF

    def test_available_true_for_normal_player(self):
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.available is True

    def test_available_false_when_marked_unavailable(self):
        entity = _make_entity({**MOCK_SPOTIFY, "available": False})
        assert entity.available is False

    def test_available_false_when_coordinator_failed(self):
        entity = _make_entity(MOCK_SPOTIFY, last_update_success=False)
        assert entity.available is False

    def test_available_false_when_sse_disconnected(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._event_stream.sse_connected = False
        assert entity.available is False

    def test_media_position_converts_us_to_seconds(self):
        """28962000 µs → 28 seconds."""
        entity = _make_entity({**MOCK_SPOTIFY, "position": 28962000})
        assert entity.media_position == 28

    def test_media_duration_converts_us_to_seconds(self):
        """223840000 µs → 223 seconds."""
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.media_duration == 223

    def test_media_position_updated_at_from_player_data(self):
        ts = datetime(2026, 3, 4, 19, 17, 49, tzinfo=timezone.utc)
        entity = _make_entity({**MOCK_SPOTIFY, "position_updated_at": ts})
        assert entity.media_position_updated_at == ts

    def test_media_image_url_https_allowed(self):
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.media_image_url == "https://i.scdn.co/image/abc123"

    def test_media_image_url_file_filtered(self):
        """file:// URLs must be rejected to avoid HA URL parsing errors."""
        entity = _make_entity(MOCK_CHROME)
        assert entity.media_image_url is None

    def test_media_title(self):
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.media_title == "Narcozik"

    def test_media_artist_list(self):
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.media_artist == "Dooz Kawa"

    def test_media_artist_string(self):
        player = {**MOCK_SPOTIFY, "metadata": {**MOCK_SPOTIFY["metadata"], "xesam:artist": "Solo Artist"}}
        entity = _make_entity(player)
        assert entity.media_artist == "Solo Artist"

    def test_media_album_name(self):
        entity = _make_entity(MOCK_SPOTIFY)
        assert entity.media_album_name == "Etoiles du sol"

    def test_shuffle(self):
        entity = _make_entity({**MOCK_SPOTIFY, "shuffle": True})
        assert entity.shuffle is True

    def test_repeat_off(self):
        entity = _make_entity({**MOCK_SPOTIFY, "loop_status": "None"})
        assert entity.repeat == RepeatMode.OFF

    def test_repeat_one(self):
        entity = _make_entity({**MOCK_SPOTIFY, "loop_status": "Track"})
        assert entity.repeat == RepeatMode.ONE

    def test_repeat_all(self):
        entity = _make_entity({**MOCK_SPOTIFY, "loop_status": "Playlist"})
        assert entity.repeat == RepeatMode.ALL

    def test_volume_level(self):
        entity = _make_entity({**MOCK_SPOTIFY, "volume": 0.75})
        assert entity.volume_level == 0.75

    def test_supported_features_full_capabilities(self):
        entity = _make_entity(MOCK_SPOTIFY)
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.PLAY
        assert features & MediaPlayerEntityFeature.PAUSE
        assert features & MediaPlayerEntityFeature.STOP
        assert features & MediaPlayerEntityFeature.NEXT_TRACK
        assert features & MediaPlayerEntityFeature.PREVIOUS_TRACK
        assert features & MediaPlayerEntityFeature.SEEK
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.SHUFFLE_SET
        assert features & MediaPlayerEntityFeature.REPEAT_SET

    def test_supported_features_limited_capabilities(self):
        """Chrome: can_control only, no play/pause/seek."""
        entity = _make_entity(MOCK_CHROME)
        features = entity.supported_features
        assert not (features & MediaPlayerEntityFeature.PLAY)
        assert not (features & MediaPlayerEntityFeature.PAUSE)
        assert not (features & MediaPlayerEntityFeature.SEEK)
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.STOP

    def test_extra_state_attributes(self):
        entity = _make_entity(MOCK_SPOTIFY)
        attrs = entity.extra_state_attributes
        assert attrs["player_name"] == MOCK_SPOTIFY["bus_name"]
        assert attrs["identity"] == "Spotify"
        assert attrs["playback_status"] == "Playing"
        assert attrs["can_control"] is True


# ===========================================================================
# OdioMPRISMediaPlayer — media control actions
# ===========================================================================


class TestMPRISEntityActions:

    @pytest.mark.asyncio
    async def test_play_uses_api_when_capable(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_play = AsyncMock()
        await entity.async_media_play()
        entity._api_client.player_play.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"])

    @pytest.mark.asyncio
    async def test_play_delegates_when_not_capable(self):
        entity = _make_entity(MOCK_CHROME)  # can_play: False
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_media_play()
        entity._delegate_to_hass.assert_awaited_once_with("media_play")

    @pytest.mark.asyncio
    async def test_pause_uses_api_when_capable(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_pause = AsyncMock()
        await entity.async_media_pause()
        entity._api_client.player_pause.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"])

    @pytest.mark.asyncio
    async def test_stop_uses_api_when_can_control(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_stop = AsyncMock()
        await entity.async_media_stop()
        entity._api_client.player_stop.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"])

    @pytest.mark.asyncio
    async def test_next_track_uses_api(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_next = AsyncMock()
        await entity.async_media_next_track()
        entity._api_client.player_next.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"])

    @pytest.mark.asyncio
    async def test_previous_track_uses_api(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_previous = AsyncMock()
        await entity.async_media_previous_track()
        entity._api_client.player_previous.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"])

    @pytest.mark.asyncio
    async def test_seek_uses_api_with_us_conversion(self):
        """HA sends seconds, API receives µs."""
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_position = AsyncMock()
        await entity.async_media_seek(10.0)  # 10 seconds
        entity._api_client.player_set_position.assert_awaited_once_with(
            MOCK_SPOTIFY["bus_name"],
            MOCK_SPOTIFY["metadata"]["mpris:trackid"],
            10_000_000,  # µs
        )

    @pytest.mark.asyncio
    async def test_seek_delegates_when_not_capable(self):
        entity = _make_entity(MOCK_CHROME)  # can_seek: False
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_media_seek(30.0)
        entity._delegate_to_hass.assert_awaited_once_with("media_seek", {"seek_position": 30.0})

    @pytest.mark.asyncio
    async def test_set_volume_uses_api(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_volume = AsyncMock()
        await entity.async_set_volume_level(0.5)
        entity._api_client.player_set_volume.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], 0.5)

    @pytest.mark.asyncio
    async def test_volume_up_increments_by_5_percent(self):
        entity = _make_entity({**MOCK_SPOTIFY, "volume": 0.5})
        entity._api_client.player_set_volume = AsyncMock()
        await entity.async_volume_up()
        entity._api_client.player_set_volume.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], 0.55)

    @pytest.mark.asyncio
    async def test_volume_down_decrements_by_5_percent(self):
        entity = _make_entity({**MOCK_SPOTIFY, "volume": 0.5})
        entity._api_client.player_set_volume = AsyncMock()
        await entity.async_volume_down()
        entity._api_client.player_set_volume.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], 0.45)

    @pytest.mark.asyncio
    async def test_volume_up_capped_at_1(self):
        entity = _make_entity({**MOCK_SPOTIFY, "volume": 0.98})
        entity._api_client.player_set_volume = AsyncMock()
        await entity.async_volume_up()
        entity._api_client.player_set_volume.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], 1.0)

    @pytest.mark.asyncio
    async def test_volume_down_capped_at_0(self):
        entity = _make_entity({**MOCK_SPOTIFY, "volume": 0.02})
        entity._api_client.player_set_volume = AsyncMock()
        await entity.async_volume_down()
        entity._api_client.player_set_volume.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], 0.0)

    @pytest.mark.asyncio
    async def test_set_shuffle_uses_api(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_shuffle = AsyncMock()
        await entity.async_set_shuffle(False)
        entity._api_client.player_set_shuffle.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], False)

    @pytest.mark.asyncio
    async def test_set_repeat_off_maps_to_none(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_loop = AsyncMock()
        await entity.async_set_repeat(RepeatMode.OFF)
        entity._api_client.player_set_loop.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], "None")

    @pytest.mark.asyncio
    async def test_set_repeat_one_maps_to_track(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_loop = AsyncMock()
        await entity.async_set_repeat(RepeatMode.ONE)
        entity._api_client.player_set_loop.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], "Track")

    @pytest.mark.asyncio
    async def test_set_repeat_all_maps_to_playlist(self):
        entity = _make_entity(MOCK_SPOTIFY)
        entity._api_client.player_set_loop = AsyncMock()
        await entity.async_set_repeat(RepeatMode.ALL)
        entity._api_client.player_set_loop.assert_awaited_once_with(MOCK_SPOTIFY["bus_name"], "Playlist")

    @pytest.mark.asyncio
    async def test_set_repeat_delegates_when_no_loop_status(self):
        """Player without loop_status falls back to mapped entity."""
        player = {k: v for k, v in MOCK_CHROME.items() if k != "loop_status"}
        entity = _make_entity(player)
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_set_repeat(RepeatMode.ALL)
        entity._delegate_to_hass.assert_awaited_once_with("repeat_set", {"repeat": RepeatMode.ALL})
