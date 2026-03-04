"""Tests for media_player entity classes (Receiver, Service, PulseClient)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState

from custom_components.odio_remote.media_player import (
    OdioReceiverMediaPlayer,
    OdioServiceMediaPlayer,
    OdioPulseClientMediaPlayer,
    _MediaPlayerContext,
    _extract_mpris_app_name,
    async_setup_entry,
)

from .conftest import (
    MOCK_DEVICE_INFO,
    MOCK_REMOTE_CLIENTS,
    MOCK_SERVICES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_stream(connected=True):
    es = MagicMock()
    es.sse_connected = connected
    es.async_add_listener = MagicMock(return_value=lambda: None)
    return es


def _make_audio_coordinator(clients=None, success=True):
    coord = MagicMock()
    coord.data = {"audio": clients} if clients is not None else None
    coord.last_update_success = success
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_service_coordinator(services=None, success=True):
    coord = MagicMock()
    coord.data = {"services": services} if services is not None else None
    coord.last_update_success = success
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    coord.async_request_refresh = AsyncMock()
    coord.config_entry = MagicMock()
    coord.config_entry.runtime_data.service_mappings = {}
    return coord


def _make_ctx(
    audio_coordinator=None,
    service_coordinator=None,
    mpris_coordinator=None,
    service_mappings=None,
    backends=None,
    server_hostname="htpc",
):
    return _MediaPlayerContext(
        entry_id="test_entry",
        event_stream=_make_event_stream(),
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        mpris_coordinator=mpris_coordinator,
        api=MagicMock(),
        device_info=MOCK_DEVICE_INFO,
        service_mappings=service_mappings or {},
        backends=backends if backends is not None else {"pulseaudio": True, "systemd": True},
        server_hostname=server_hostname,
    )


# ---------------------------------------------------------------------------
# _extract_mpris_app_name
# ---------------------------------------------------------------------------


class TestExtractMprisAppName:

    def test_standard_bus_name(self):
        assert _extract_mpris_app_name("org.mpris.MediaPlayer2.mpd") == "mpd"

    def test_instance_bus_name(self):
        assert _extract_mpris_app_name("org.mpris.MediaPlayer2.firefox.instance123") == "firefox"

    def test_non_mpris_bus_name(self):
        assert _extract_mpris_app_name("com.example.player") == "com.example.player"


# ---------------------------------------------------------------------------
# OdioReceiverMediaPlayer
# ---------------------------------------------------------------------------


class TestReceiverEntity:

    def _make_receiver(self, audio_coordinator=None, service_coordinator=None,
                       backends=None, connected=True):
        ctx = _make_ctx(
            audio_coordinator=audio_coordinator,
            service_coordinator=service_coordinator,
            backends=backends if backends is not None else {"pulseaudio": True},
        )
        ctx.event_stream = _make_event_stream(connected)
        entity = OdioReceiverMediaPlayer(ctx)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        return entity

    # -- state --

    def test_state_off_when_disconnected(self):
        entity = self._make_receiver(connected=False)
        assert entity.state == MediaPlayerState.OFF

    def test_state_off_when_no_audio_coordinator(self):
        entity = self._make_receiver(audio_coordinator=None)
        assert entity.state == MediaPlayerState.OFF

    def test_state_off_when_update_failed(self):
        coord = _make_audio_coordinator(clients=[], success=False)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.state == MediaPlayerState.OFF

    def test_state_off_when_no_data(self):
        coord = _make_audio_coordinator()
        coord.data = None
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.state == MediaPlayerState.OFF

    def test_state_idle_no_active_clients(self):
        clients = [{"corked": True}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.state == MediaPlayerState.IDLE

    def test_state_playing_with_active_client(self):
        clients = [{"corked": False}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.state == MediaPlayerState.PLAYING

    # -- supported_features --

    def test_features_with_pulseaudio(self):
        entity = self._make_receiver(backends={"pulseaudio": True})
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.VOLUME_MUTE

    def test_features_without_pulseaudio(self):
        entity = self._make_receiver(backends={})
        assert entity.supported_features == MediaPlayerEntityFeature(0)

    # -- volume --

    def test_volume_level_average(self):
        clients = [{"volume": 0.8}, {"volume": 0.4}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.volume_level == pytest.approx(0.6)

    def test_volume_level_none_when_no_coordinator(self):
        entity = self._make_receiver(audio_coordinator=None)
        assert entity.volume_level is None

    def test_volume_level_none_when_no_clients(self):
        coord = _make_audio_coordinator(clients=[])
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.volume_level is None

    def test_is_volume_muted_true(self):
        clients = [{"muted": True}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.is_volume_muted is True

    def test_is_volume_muted_false(self):
        clients = [{"muted": False}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        assert entity.is_volume_muted is False

    def test_is_volume_muted_no_coordinator(self):
        entity = self._make_receiver(audio_coordinator=None)
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs_with_audio(self):
        clients = [{"corked": False}, {"corked": True}]
        coord = _make_audio_coordinator(clients=clients)
        entity = self._make_receiver(audio_coordinator=coord)
        attrs = entity.extra_state_attributes
        assert attrs["active_clients"] == 2
        assert attrs["playing_clients"] == 1
        assert "backends" in attrs

    def test_extra_attrs_without_audio(self):
        entity = self._make_receiver(audio_coordinator=None)
        attrs = entity.extra_state_attributes
        assert "backends" in attrs
        assert "active_clients" not in attrs

    # -- actions --

    @pytest.mark.asyncio
    async def test_set_volume_level(self):
        entity = self._make_receiver()
        entity._api_client.set_server_volume = AsyncMock()
        await entity.async_set_volume_level(0.5)
        entity._api_client.set_server_volume.assert_awaited_once_with(0.5)

    @pytest.mark.asyncio
    async def test_mute_volume(self):
        entity = self._make_receiver()
        entity._api_client.set_server_mute = AsyncMock()
        await entity.async_mute_volume(True)
        entity._api_client.set_server_mute.assert_awaited_once_with(True)

    # -- async_added_to_hass --

    @pytest.mark.asyncio
    async def test_added_to_hass_registers_listeners(self):
        coord = _make_audio_coordinator(clients=[])
        svc = _make_service_coordinator(services=[])
        entity = self._make_receiver(audio_coordinator=coord, service_coordinator=svc)
        await entity.async_added_to_hass()
        # event_stream + audio + service = 3 listeners
        assert entity.async_on_remove.call_count == 3

    @pytest.mark.asyncio
    async def test_added_to_hass_no_coordinators(self):
        entity = self._make_receiver(audio_coordinator=None, service_coordinator=None)
        await entity.async_added_to_hass()
        # only event_stream listener
        assert entity.async_on_remove.call_count == 1


# ---------------------------------------------------------------------------
# OdioServiceMediaPlayer
# ---------------------------------------------------------------------------


class TestServiceEntity:

    def _make_service(self, service_info=None, services_data=None,
                      mappings=None, connected=True):
        svc_info = service_info or MOCK_SERVICES[0]
        coord = _make_service_coordinator(
            services=services_data if services_data is not None else MOCK_SERVICES
        )
        if mappings:
            coord.config_entry.runtime_data.service_mappings = mappings
        ctx = _make_ctx(service_coordinator=coord, service_mappings=mappings or {})
        ctx.event_stream = _make_event_stream(connected)
        entity = OdioServiceMediaPlayer(ctx, svc_info)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    # -- state --

    def test_state_idle_when_running(self):
        entity = self._make_service()
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_not_running(self):
        entity = self._make_service(service_info=MOCK_SERVICES[1])
        assert entity.state == MediaPlayerState.OFF

    def test_state_playing_via_mapped_entity(self):
        entity = self._make_service(
            mappings={"user/mpd.service": "media_player.mpd"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        assert entity.state == MediaPlayerState.PLAYING

    # -- available --

    def test_available_when_connected(self):
        entity = self._make_service(connected=True)
        assert entity.available is True

    def test_unavailable_when_disconnected(self):
        entity = self._make_service(connected=False)
        assert entity.available is False

    # -- mapping_key --

    def test_mapping_key(self):
        entity = self._make_service()
        assert entity._mapping_key == "user/mpd.service"

    # -- supported_features --

    def test_base_features(self):
        entity = self._make_service()
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.TURN_ON
        assert features & MediaPlayerEntityFeature.TURN_OFF

    def test_features_with_mapped_entity(self):
        entity = self._make_service(
            mappings={"user/mpd.service": "media_player.mpd"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {
            "supported_features": MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE,
        }
        entity.hass.states.get.return_value = mock_state
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.PLAY
        assert features & MediaPlayerEntityFeature.PAUSE

    # -- volume --

    def test_volume_level_none_without_mapping(self):
        entity = self._make_service()
        assert entity.volume_level is None

    def test_is_volume_muted_false_without_mapping(self):
        entity = self._make_service()
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs(self):
        entity = self._make_service()
        attrs = entity.extra_state_attributes
        assert attrs["scope"] == "user"
        assert "running" in attrs
        assert "active_state" in attrs

    def test_extra_attrs_with_mapped_entity(self):
        entity = self._make_service(
            mappings={"user/mpd.service": "media_player.mpd"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        attrs = entity.extra_state_attributes
        assert attrs["mapped_entity"] == "media_player.mpd"

    # -- _is_service_running --

    def test_is_running_true(self):
        entity = self._make_service()
        assert entity._is_service_running() is True

    def test_is_running_false_no_data(self):
        entity = self._make_service()
        entity.coordinator.data = None
        assert entity._is_service_running() is False

    # -- actions --

    @pytest.mark.asyncio
    async def test_turn_on(self):
        entity = self._make_service()
        entity._api_client.control_service = AsyncMock()
        with patch("custom_components.odio_remote.media_player.asyncio.sleep", new_callable=AsyncMock):
            await entity.async_turn_on()
        entity._api_client.control_service.assert_awaited_once_with("enable", "user", "mpd.service")

    @pytest.mark.asyncio
    async def test_turn_off(self):
        entity = self._make_service()
        entity._api_client.control_service = AsyncMock()
        with patch("custom_components.odio_remote.media_player.asyncio.sleep", new_callable=AsyncMock):
            await entity.async_turn_off()
        entity._api_client.control_service.assert_awaited_once_with("disable", "user", "mpd.service")

    @pytest.mark.asyncio
    async def test_set_volume_delegates(self):
        entity = self._make_service(
            mappings={"user/mpd.service": "media_player.mpd"}
        )
        entity.hass.services.async_call = AsyncMock()
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        await entity.async_set_volume_level(0.5)
        entity.hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_mute_delegates(self):
        entity = self._make_service(
            mappings={"user/mpd.service": "media_player.mpd"}
        )
        entity.hass.services.async_call = AsyncMock()
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        await entity.async_mute_volume(True)
        entity.hass.services.async_call.assert_called_once()

    # -- async_added_to_hass --

    @pytest.mark.asyncio
    async def test_added_to_hass_registers_sse_listener(self):
        entity = self._make_service()
        await entity.async_added_to_hass()
        assert entity.async_on_remove.call_count >= 1


# ---------------------------------------------------------------------------
# OdioPulseClientMediaPlayer
# ---------------------------------------------------------------------------


class TestPulseClientEntity:

    def _make_client(self, client_data=None, clients=None, mappings=None, connected=True):
        client = client_data or MOCK_REMOTE_CLIENTS[0]
        coord = _make_audio_coordinator(
            clients=clients if clients is not None else [client]
        )
        coord.config_entry = MagicMock()
        coord.config_entry.runtime_data.service_mappings = mappings or {}
        ctx = _make_ctx(audio_coordinator=coord, service_mappings=mappings or {})
        ctx.event_stream = _make_event_stream(connected)
        entity = OdioPulseClientMediaPlayer(ctx, client)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    # -- state --

    def test_state_playing_not_corked(self):
        entity = self._make_client()
        assert entity.state == MediaPlayerState.PLAYING

    def test_state_idle_when_corked(self):
        client = {**MOCK_REMOTE_CLIENTS[0], "corked": True}
        entity = self._make_client(client_data=client, clients=[client])
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_client_gone(self):
        entity = self._make_client(clients=[])
        assert entity.state == MediaPlayerState.OFF

    def test_state_playing_via_mapped_entity(self):
        entity = self._make_client(
            mappings={"client:RemoteClient": "media_player.kodi"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        assert entity.state == MediaPlayerState.PLAYING

    # -- available --

    def test_available_when_connected(self):
        entity = self._make_client(connected=True)
        assert entity.available is True

    def test_unavailable_when_disconnected(self):
        entity = self._make_client(connected=False)
        assert entity.available is False

    # -- mapping_key --

    def test_mapping_key(self):
        entity = self._make_client()
        assert entity._mapping_key == "client:RemoteClient"

    # -- supported_features --

    def test_base_features(self):
        entity = self._make_client()
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.VOLUME_MUTE

    # -- volume --

    def test_volume_from_client(self):
        entity = self._make_client()
        assert entity.volume_level == 0.8

    def test_volume_from_mapped_takes_priority(self):
        entity = self._make_client(
            mappings={"client:RemoteClient": "media_player.kodi"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {"volume_level": 0.3}
        entity.hass.states.get.return_value = mock_state
        assert entity.volume_level == 0.3

    def test_volume_none_when_client_gone(self):
        entity = self._make_client(clients=[])
        assert entity.volume_level is None

    def test_muted_from_client(self):
        entity = self._make_client()
        assert entity.is_volume_muted is False

    def test_muted_from_mapped(self):
        entity = self._make_client(
            mappings={"client:RemoteClient": "media_player.kodi"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {"is_volume_muted": True}
        entity.hass.states.get.return_value = mock_state
        assert entity.is_volume_muted is True

    def test_muted_false_when_client_gone(self):
        entity = self._make_client(clients=[])
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs_connected(self):
        entity = self._make_client()
        attrs = entity.extra_state_attributes
        assert attrs["status"] == "connected"
        assert attrs["client_name"] == "RemoteClient"
        assert attrs["remote_host"] == "remote-host"
        assert "client_id" in attrs

    def test_extra_attrs_disconnected(self):
        entity = self._make_client(clients=[])
        attrs = entity.extra_state_attributes
        assert attrs["status"] == "disconnected"

    def test_extra_attrs_with_props(self):
        client = {**MOCK_REMOTE_CLIENTS[0], "props": {
            "native-protocol.peer": "192.168.1.50",
            "application.process.host": "remote-box",
            "application.version": "1.2.3",
        }}
        entity = self._make_client(client_data=client, clients=[client])
        attrs = entity.extra_state_attributes
        assert attrs["connection"] == "192.168.1.50"
        assert attrs["remote_host"] == "remote-box"
        assert attrs["app_version"] == "1.2.3"

    def test_extra_attrs_with_mapped_entity(self):
        entity = self._make_client(
            mappings={"client:RemoteClient": "media_player.kodi"}
        )
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        attrs = entity.extra_state_attributes
        assert attrs["mapped_entity"] == "media_player.kodi"

    # -- _get_current_client --

    def test_get_current_client_found(self):
        entity = self._make_client()
        client = entity._get_current_client()
        assert client is not None
        assert client["name"] == "RemoteClient"

    def test_get_current_client_not_found(self):
        entity = self._make_client(clients=[])
        assert entity._get_current_client() is None

    def test_get_current_client_no_data(self):
        entity = self._make_client()
        entity.coordinator.data = None
        assert entity._get_current_client() is None

    # -- actions --

    @pytest.mark.asyncio
    async def test_set_volume_with_fallback(self):
        entity = self._make_client()
        entity._api_client.set_client_volume = AsyncMock()
        await entity.async_set_volume_level(0.5)
        entity._api_client.set_client_volume.assert_awaited_once_with("RemoteClient", 0.5)

    @pytest.mark.asyncio
    async def test_mute_with_fallback(self):
        entity = self._make_client()
        entity._api_client.set_client_mute = AsyncMock()
        await entity.async_mute_volume(True)
        entity._api_client.set_client_mute.assert_awaited_once_with("RemoteClient", True)


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


class TestMediaPlayerAsyncSetupEntry:

    @pytest.mark.asyncio
    async def test_creates_receiver_entity(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {"server_info": {"backends": {}, "hostname": "htpc"}}
        entry.runtime_data.audio_coordinator = None
        entry.runtime_data.service_coordinator = None
        entry.runtime_data.mpris_coordinator = None
        entry.runtime_data.event_stream = _make_event_stream()
        entry.runtime_data.api = MagicMock()
        entry.runtime_data.device_info = MOCK_DEVICE_INFO
        entry.runtime_data.service_mappings = {}
        entry.async_on_unload = MagicMock()

        added = []

        def async_add(entities):
            added.extend(entities)

        await async_setup_entry(hass, entry, async_add)

        assert len(added) == 1
        assert isinstance(added[0], OdioReceiverMediaPlayer)
