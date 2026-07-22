"""Tests for OdioMPRISMediaPlayer entity properties, actions and SSE-driven state."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState, RepeatMode

from custom_components.odio_remote.media_player import OdioMPRISMediaPlayer, _MediaPlayerContext

from .conftest import MOCK_DEVICE_INFO, MOCK_PLAYERS, make_hub, push_event, set_connected

MOCK_SPOTIFY = MOCK_PLAYERS[0]
MOCK_CHROME = MOCK_PLAYERS[1]
SPOTIFY_BUS = MOCK_SPOTIFY["bus_name"]

EMITTED_AT_MS = 1772649711164  # arbitrary ms timestamp


def _make_entity(player_data, extra_players=None, mappings=None, connected=True):
    """Build an OdioMPRISMediaPlayer over a real hub seeded with the player."""
    hub = make_hub(players=[player_data] + (extra_players or []), connected=connected)
    ctx = _MediaPlayerContext(
        entry_id="test_entry",
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        service_mappings=mappings or {},
        backends=hub.server.backends,
        server_hostname="htpc",
    )
    entity = OdioMPRISMediaPlayer(ctx, hub.players[player_data["bus_name"]])
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity, hub


# ===========================================================================
# OdioMPRISMediaPlayer — unique_id stability
# ===========================================================================


class TestMPRISUniqueId:
    """unique_id must derive from the app name, not the full bus_name.

    Bus names like `org.mpris.MediaPlayer2.firefox.instance_1_52` carry a
    volatile `.instanceXXX` suffix that changes on every browser restart;
    encoding it into unique_id leaks orphan entities into the registry.
    """

    def _build(self, bus_name: str, identity: str = "") -> OdioMPRISMediaPlayer:
        entity, _ = _make_entity({"bus_name": bus_name, "identity": identity})
        return entity

    def test_unique_id_stable_across_firefox_instance_suffix(self):
        a = self._build("org.mpris.MediaPlayer2.firefox.instance_1_52")
        b = self._build("org.mpris.MediaPlayer2.firefox.instance_1_99")
        assert a.unique_id == b.unique_id == "test_entry_mpris_firefox"

    def test_unique_id_stable_across_chrome_instance_suffix(self):
        a = self._build("org.mpris.MediaPlayer2.chromium.instance1")
        b = self._build("org.mpris.MediaPlayer2.chromium.instance999")
        assert a.unique_id == b.unique_id == "test_entry_mpris_chromium"

    def test_unique_id_for_app_without_instance_suffix(self):
        entity = self._build("org.mpris.MediaPlayer2.mpd")
        assert entity.unique_id == "test_entry_mpris_mpd"

    def test_mapping_key_stable_across_instance_suffix(self):
        """_mapping_key must also be app-name based so service_mappings survives restarts."""
        a = self._build("org.mpris.MediaPlayer2.firefox.instance_1_52")
        b = self._build("org.mpris.MediaPlayer2.firefox.instance_1_99")
        assert a._mapping_key == b._mapping_key == "mpris:firefox"


# ===========================================================================
# OdioMPRISMediaPlayer — properties
# ===========================================================================


class TestMPRISEntityProperties:

    def test_state_playing(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "playback_status": "Playing"})
        assert entity.state == MediaPlayerState.PLAYING

    def test_state_paused(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "playback_status": "Paused"})
        assert entity.state == MediaPlayerState.PAUSED

    def test_state_stopped_is_idle(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "playback_status": "Stopped"})
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_disconnected(self):
        entity, _ = _make_entity(MOCK_SPOTIFY, connected=False)
        assert entity.state == MediaPlayerState.OFF

    def test_available_true_for_normal_player(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
        assert entity.available is True

    def test_available_false_when_player_removed(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        push_event(hub, "player.removed", {"bus_name": SPOTIFY_BUS})
        assert entity.available is False

    def test_available_false_when_sse_disconnected(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        set_connected(hub, False)
        assert entity.available is False

    def test_media_position_converts_us_to_seconds(self):
        """28962000 µs → 28 seconds, raw beacon value — no extrapolation."""
        entity, _ = _make_entity({**MOCK_SPOTIFY, "position": 28962000})
        assert entity.media_position == 28

    def test_media_duration_converts_us_to_seconds(self):
        """223840000 µs → 223 seconds."""
        entity, _ = _make_entity(MOCK_SPOTIFY)
        assert entity.media_duration == 223

    def test_media_position_updated_at_is_aware(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
        ts = entity.media_position_updated_at
        assert ts == datetime(2026, 3, 4, 19, 6, 0, tzinfo=timezone.utc)
        assert ts.tzinfo is not None

    def test_media_image_url_uses_cover_proxy(self):
        """Cover art routes through the go-odio-api proxy with cache-busting query."""
        entity, _ = _make_entity(MOCK_SPOTIFY)
        assert entity.media_image_url == (
            "http://localhost:8018/players/org.mpris.MediaPlayer2.spotify/cover"
            "?t=%2Fcom%2Fspotify%2Ftrack%2Fabc&a=https%3A%2F%2Fi.scdn.co%2Fimage%2Fabc123"
        )

    def test_media_image_url_none_when_no_art(self):
        metadata = {k: v for k, v in MOCK_SPOTIFY["metadata"].items() if k != "mpris:artUrl"}
        entity, _ = _make_entity({**MOCK_SPOTIFY, "metadata": metadata})
        assert entity.media_image_url is None

    def test_media_title(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
        assert entity.media_title == "Narcozik"

    def test_media_artist(self):
        entity, _ = _make_entity(MOCK_CHROME)
        assert entity.media_artist == "Some Artist"

    def test_media_album_name(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
        assert entity.media_album_name == "Etoiles du sol"

    def test_shuffle(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "shuffle": True})
        assert entity.shuffle is True

    def test_repeat_off(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "loop_status": "None"})
        assert entity.repeat == RepeatMode.OFF

    def test_repeat_one(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "loop_status": "Track"})
        assert entity.repeat == RepeatMode.ONE

    def test_repeat_all(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "loop_status": "Playlist"})
        assert entity.repeat == RepeatMode.ALL

    def test_volume_level(self):
        entity, _ = _make_entity({**MOCK_SPOTIFY, "volume": 0.75})
        assert entity.volume_level == 0.75

    def test_supported_features_full_capabilities(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
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
        entity, _ = _make_entity(MOCK_CHROME)
        features = entity.supported_features
        assert not (features & MediaPlayerEntityFeature.PLAY)
        assert not (features & MediaPlayerEntityFeature.PAUSE)
        assert not (features & MediaPlayerEntityFeature.SEEK)
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.STOP

    def test_extra_state_attributes(self):
        entity, _ = _make_entity(MOCK_SPOTIFY)
        attrs = entity.extra_state_attributes
        assert attrs["player_name"] == SPOTIFY_BUS
        assert attrs["identity"] == "Spotify"
        assert attrs["playback_status"] == "Playing"
        assert attrs["can_control"] is True


# ===========================================================================
# OdioMPRISMediaPlayer — SSE-driven state (via the hub's real dispatch path)
# ===========================================================================


class TestMPRISSseFlow:

    def test_update_event_changes_state(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        push_event(hub, "player.updated", {
            "data": {**MOCK_SPOTIFY, "playback_status": "Paused"},
            "emitted_at": EMITTED_AT_MS,
        })
        assert entity.state == MediaPlayerState.PAUSED

    def test_position_event_updates_position_and_timestamp(self):
        entity, hub = _make_entity(MOCK_SPOTIFY, extra_players=[MOCK_CHROME])
        push_event(hub, "player.position", [{
            "bus_name": SPOTIFY_BUS,
            "position": 99000000,
            "emitted_at": EMITTED_AT_MS,
        }])
        assert entity.media_position == 99
        expected_ts = datetime.fromtimestamp(EMITTED_AT_MS / 1000, tz=timezone.utc)
        assert entity.media_position_updated_at == expected_ts

    def test_position_event_leaves_other_players_untouched(self):
        entity, hub = _make_entity(MOCK_CHROME, extra_players=[MOCK_SPOTIFY])
        push_event(hub, "player.position", [{
            "bus_name": SPOTIFY_BUS,
            "position": 50000000,
            "emitted_at": EMITTED_AT_MS,
        }])
        assert entity.media_position == MOCK_CHROME["position"] // 1_000_000

    def test_removed_event_turns_entity_off(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        push_event(hub, "player.removed", {"bus_name": SPOTIFY_BUS})
        assert entity.available is False
        assert entity.state == MediaPlayerState.OFF


# ===========================================================================
# OdioMPRISMediaPlayer — media control actions
# ===========================================================================


class TestMPRISEntityActions:

    async def test_play_uses_api_when_capable(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_play()
        hub.client.player_play.assert_awaited_once_with(SPOTIFY_BUS)

    async def test_play_delegates_when_not_capable(self):
        entity, _ = _make_entity(MOCK_CHROME)  # can_play: False
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_media_play()
        entity._delegate_to_hass.assert_awaited_once_with("media_play")

    async def test_pause_uses_api_when_capable(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_pause()
        hub.client.player_pause.assert_awaited_once_with(SPOTIFY_BUS)

    async def test_stop_uses_api_when_can_control(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_stop()
        hub.client.player_stop.assert_awaited_once_with(SPOTIFY_BUS)

    async def test_next_track_uses_api(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_next_track()
        hub.client.player_next.assert_awaited_once_with(SPOTIFY_BUS)

    async def test_previous_track_uses_api(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_previous_track()
        hub.client.player_previous.assert_awaited_once_with(SPOTIFY_BUS)

    async def test_seek_uses_api_with_us_conversion_and_track_guard(self):
        """HA sends seconds; the API receives µs plus the current track id."""
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_media_seek(10.0)
        hub.client.player_set_position.assert_awaited_once_with(
            SPOTIFY_BUS, 10_000_000, MOCK_SPOTIFY["metadata"]["mpris:trackid"]
        )

    async def test_seek_delegates_when_not_capable(self):
        entity, _ = _make_entity(MOCK_CHROME)  # can_seek: False
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_media_seek(30.0)
        entity._delegate_to_hass.assert_awaited_once_with("media_seek", {"seek_position": 30.0})

    async def test_set_volume_uses_api(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_set_volume_level(0.5)
        hub.client.player_set_volume.assert_awaited_once_with(SPOTIFY_BUS, 0.5)

    async def test_volume_up_increments_by_5_percent(self):
        entity, hub = _make_entity({**MOCK_SPOTIFY, "volume": 0.5})
        await entity.async_volume_up()
        hub.client.player_set_volume.assert_awaited_once_with(SPOTIFY_BUS, 0.55)

    async def test_volume_down_decrements_by_5_percent(self):
        entity, hub = _make_entity({**MOCK_SPOTIFY, "volume": 0.5})
        await entity.async_volume_down()
        hub.client.player_set_volume.assert_awaited_once_with(SPOTIFY_BUS, 0.45)

    async def test_volume_up_capped_at_1(self):
        entity, hub = _make_entity({**MOCK_SPOTIFY, "volume": 0.98})
        await entity.async_volume_up()
        hub.client.player_set_volume.assert_awaited_once_with(SPOTIFY_BUS, 1.0)

    async def test_volume_down_capped_at_0(self):
        entity, hub = _make_entity({**MOCK_SPOTIFY, "volume": 0.02})
        await entity.async_volume_down()
        hub.client.player_set_volume.assert_awaited_once_with(SPOTIFY_BUS, 0.0)

    async def test_set_shuffle_uses_api(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_set_shuffle(False)
        hub.client.player_set_shuffle.assert_awaited_once_with(SPOTIFY_BUS, False)

    async def test_set_repeat_off_maps_to_none(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_set_repeat(RepeatMode.OFF)
        hub.client.player_set_loop.assert_awaited_once_with(SPOTIFY_BUS, "None")

    async def test_set_repeat_one_maps_to_track(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_set_repeat(RepeatMode.ONE)
        hub.client.player_set_loop.assert_awaited_once_with(SPOTIFY_BUS, "Track")

    async def test_set_repeat_all_maps_to_playlist(self):
        entity, hub = _make_entity(MOCK_SPOTIFY)
        await entity.async_set_repeat(RepeatMode.ALL)
        hub.client.player_set_loop.assert_awaited_once_with(SPOTIFY_BUS, "Playlist")

    async def test_set_repeat_delegates_when_no_loop_status(self):
        """Player without loop_status falls back to mapped entity."""
        player = {k: v for k, v in MOCK_CHROME.items() if k != "loop_status"}
        entity, _ = _make_entity(player)
        entity._delegate_to_hass = AsyncMock(return_value=True)
        await entity.async_set_repeat(RepeatMode.ALL)
        entity._delegate_to_hass.assert_awaited_once_with("repeat_set", {"repeat": RepeatMode.ALL})
