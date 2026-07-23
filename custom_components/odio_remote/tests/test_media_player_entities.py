"""Tests for media_player entity classes (Receiver, Service, PulseClient)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState
from pyodio import AudioClientState, Backends, ServiceState

from custom_components.odio_remote.helpers import extract_mpris_app_name
from custom_components.odio_remote.media_player import (
    OdioPulseClientMediaPlayer,
    OdioReceiverMediaPlayer,
    OdioServiceMediaPlayer,
    _MediaPlayerContext,
    async_setup_entry,
)

from .conftest import (
    MOCK_DEVICE_INFO,
    MOCK_PLAYERS,
    MOCK_REMOTE_CLIENTS,
    MOCK_SERVICES,
    make_hub,
)

ENTRY_ID = "test_entry_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(hub, service_mappings=None, backends=None, server_hostname="htpc"):
    return _MediaPlayerContext(
        entry_id=ENTRY_ID,
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        service_mappings=service_mappings or {},
        backends=backends if backends is not None else hub.server.backends,
        server_hostname=server_hostname,
    )


def _audio(clients):
    return {"kind": "pipewire", "clients": clients, "outputs": []}


# ---------------------------------------------------------------------------
# extract_mpris_app_name
# ---------------------------------------------------------------------------


class TestExtractMprisAppName:

    def test_standard_bus_name(self):
        assert extract_mpris_app_name("org.mpris.MediaPlayer2.mpd") == "mpd"

    def test_instance_bus_name(self):
        assert extract_mpris_app_name("org.mpris.MediaPlayer2.firefox.instance123") == "firefox"

    def test_non_mpris_bus_name(self):
        assert extract_mpris_app_name("com.example.player") == "com.example.player"


# ---------------------------------------------------------------------------
# OdioReceiverMediaPlayer
# ---------------------------------------------------------------------------


class TestReceiverEntity:

    def _make_receiver(self, clients=None, players=None, backends=None, connected=True):
        hub = make_hub(
            audio=_audio(clients) if clients is not None else None,
            players=players,
            connected=connected,
        )
        ctx = _make_ctx(hub, backends=backends)
        entity = OdioReceiverMediaPlayer(ctx)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        return entity, hub

    # -- state --

    def test_state_off_when_disconnected(self):
        entity, _ = self._make_receiver(clients=[], connected=False)
        assert entity.state == MediaPlayerState.OFF

    def test_state_off_when_no_pulseaudio_backend(self):
        entity, _ = self._make_receiver(backends=Backends())
        assert entity.state == MediaPlayerState.OFF

    def test_state_idle_no_active_clients(self):
        entity, _ = self._make_receiver(clients=[{"name": "c1", "corked": True}])
        assert entity.state == MediaPlayerState.IDLE

    def test_state_playing_with_active_client(self):
        entity, _ = self._make_receiver(clients=[{"name": "c1", "corked": False}])
        assert entity.state == MediaPlayerState.PLAYING

    def test_state_playing_with_playing_mpris_player(self):
        entity, _ = self._make_receiver(
            clients=[{"name": "c1", "corked": True}], players=[MOCK_PLAYERS[0]]
        )
        assert entity.state == MediaPlayerState.PLAYING

    # -- supported_features --

    def test_features_with_pulseaudio(self):
        entity, _ = self._make_receiver(clients=[])
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.VOLUME_MUTE

    def test_features_without_pulseaudio(self):
        entity, _ = self._make_receiver(backends=Backends())
        assert entity.supported_features == MediaPlayerEntityFeature(0)

    # -- volume --

    def test_volume_level_average(self):
        clients = [{"name": "a", "volume": 0.8}, {"name": "b", "volume": 0.4}]
        entity, _ = self._make_receiver(clients=clients)
        assert entity.volume_level == pytest.approx(0.6)

    def test_volume_level_none_when_no_clients(self):
        entity, _ = self._make_receiver(clients=[])
        assert entity.volume_level is None

    def test_is_volume_muted_true(self):
        entity, _ = self._make_receiver(clients=[{"name": "a", "muted": True}])
        assert entity.is_volume_muted is True

    def test_is_volume_muted_false(self):
        entity, _ = self._make_receiver(clients=[{"name": "a", "muted": False}])
        assert entity.is_volume_muted is False

    def test_is_volume_muted_no_clients(self):
        entity, _ = self._make_receiver(clients=[])
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs_with_audio(self):
        clients = [{"name": "a", "corked": False}, {"name": "b", "corked": True}]
        entity, _ = self._make_receiver(clients=clients)
        attrs = entity.extra_state_attributes
        assert attrs["active_clients"] == 2
        assert attrs["playing_clients"] == 1
        assert "backends" in attrs

    def test_extra_attrs_without_pulseaudio(self):
        entity, _ = self._make_receiver(backends=Backends())
        attrs = entity.extra_state_attributes
        assert "backends" in attrs
        assert "active_clients" not in attrs

    # -- actions --

    async def test_set_volume_level(self):
        entity, hub = self._make_receiver(clients=[])
        await entity.async_set_volume_level(0.5)
        hub.client.set_master_volume.assert_awaited_once_with(0.5)

    async def test_mute_volume_toggles_when_state_differs(self):
        # Snapshot master state is unmuted, so muting toggles.
        entity, hub = self._make_receiver(clients=[])
        await entity.async_mute_volume(True)
        hub.client.toggle_master_mute.assert_awaited_once()

    # -- async_added_to_hass --

    async def test_added_to_hass_registers_listeners(self):
        entity, _ = self._make_receiver(clients=[], players=[])
        await entity.async_added_to_hass()
        # connection + audio + players = 3 listeners
        assert entity.async_on_remove.call_count == 3

    async def test_added_to_hass_no_backends(self):
        entity, _ = self._make_receiver(backends=Backends())
        await entity.async_added_to_hass()
        # only the connection listener
        assert entity.async_on_remove.call_count == 1


# ---------------------------------------------------------------------------
# OdioServiceMediaPlayer
# ---------------------------------------------------------------------------


class TestServiceEntity:

    def _make_service(self, service_info=None, services_data=None, mappings=None, connected=True):
        svc_info = service_info or MOCK_SERVICES[0]
        hub = make_hub(
            services=services_data if services_data is not None else MOCK_SERVICES,
            connected=connected,
        )
        ctx = _make_ctx(hub, service_mappings=mappings)
        entity = OdioServiceMediaPlayer(ctx, ServiceState.from_dict(svc_info))
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity, hub

    # -- construction --

    def test_unique_id(self):
        entity, _ = self._make_service()
        assert entity.unique_id == f"{ENTRY_ID}_service_user_mpd.service"

    # -- state --

    def test_state_idle_when_running(self):
        entity, _ = self._make_service()
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_not_running(self):
        entity, _ = self._make_service(service_info=MOCK_SERVICES[1])
        assert entity.state == MediaPlayerState.OFF

    def test_state_playing_via_mapped_entity(self):
        entity, _ = self._make_service(mappings={"user/mpd.service": "media_player.mpd"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        assert entity.state == MediaPlayerState.PLAYING

    # -- available --

    def test_available_when_connected(self):
        entity, _ = self._make_service(connected=True)
        assert entity.available is True

    def test_unavailable_when_disconnected(self):
        entity, _ = self._make_service(connected=False)
        assert entity.available is False

    # -- mapping_key --

    def test_mapping_key(self):
        entity, _ = self._make_service()
        assert entity._mapping_key == "user/mpd.service"

    # -- supported_features --

    def test_base_features(self):
        entity, _ = self._make_service()
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.TURN_ON
        assert features & MediaPlayerEntityFeature.TURN_OFF

    def test_features_with_mapped_entity(self):
        entity, _ = self._make_service(mappings={"user/mpd.service": "media_player.mpd"})
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
        entity, _ = self._make_service()
        assert entity.volume_level is None

    def test_is_volume_muted_false_without_mapping(self):
        entity, _ = self._make_service()
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs(self):
        entity, _ = self._make_service()
        attrs = entity.extra_state_attributes
        assert attrs["scope"] == "user"
        assert attrs["enabled"] is True
        assert attrs["running"] is True
        assert attrs["active_state"] == "active"

    def test_extra_attrs_with_mapped_entity(self):
        entity, _ = self._make_service(mappings={"user/mpd.service": "media_player.mpd"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        attrs = entity.extra_state_attributes
        assert attrs["mapped_entity"] == "media_player.mpd"

    # -- _is_service_running --

    def test_is_running_true(self):
        entity, _ = self._make_service()
        assert entity._is_service_running() is True

    def test_is_running_false_when_service_gone(self):
        entity, _ = self._make_service(services_data=[])
        assert entity._is_service_running() is False

    # -- actions --

    async def test_turn_on(self):
        entity, hub = self._make_service()
        await entity.async_turn_on()
        hub.client.service_enable.assert_awaited_once_with("user", "mpd.service")

    async def test_turn_off(self):
        entity, hub = self._make_service()
        await entity.async_turn_off()
        hub.client.service_disable.assert_awaited_once_with("user", "mpd.service")

    async def test_set_volume_delegates(self):
        entity, _ = self._make_service(mappings={"user/mpd.service": "media_player.mpd"})
        entity.hass.services.async_call = AsyncMock()
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        await entity.async_set_volume_level(0.5)
        entity.hass.services.async_call.assert_called_once()

    async def test_mute_delegates(self):
        entity, _ = self._make_service(mappings={"user/mpd.service": "media_player.mpd"})
        entity.hass.services.async_call = AsyncMock()
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        await entity.async_mute_volume(True)
        entity.hass.services.async_call.assert_called_once()

    # -- async_added_to_hass --

    async def test_added_to_hass_registers_listeners(self):
        entity, _ = self._make_service()
        await entity.async_added_to_hass()
        # connection + services listeners
        assert entity.async_on_remove.call_count == 2


# ---------------------------------------------------------------------------
# OdioPulseClientMediaPlayer
# ---------------------------------------------------------------------------


class TestPulseClientEntity:

    def _make_client(self, client_data=None, clients=None, mappings=None, connected=True):
        client = client_data or MOCK_REMOTE_CLIENTS[0]
        hub = make_hub(
            audio=_audio(clients if clients is not None else [client]),
            connected=connected,
        )
        ctx = _make_ctx(hub, service_mappings=mappings)
        entity = OdioPulseClientMediaPlayer(ctx, AudioClientState.from_dict(client))
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity, hub

    # -- construction --

    def test_unique_id(self):
        entity, _ = self._make_client()
        assert entity.unique_id == f"{ENTRY_ID}_remote_remoteclient"

    # -- state --

    def test_state_playing_not_corked(self):
        entity, _ = self._make_client()
        assert entity.state == MediaPlayerState.PLAYING

    def test_state_idle_when_corked(self):
        client = {**MOCK_REMOTE_CLIENTS[0], "corked": True}
        entity, _ = self._make_client(client_data=client, clients=[client])
        assert entity.state == MediaPlayerState.IDLE

    def test_state_off_when_client_gone(self):
        entity, _ = self._make_client(clients=[])
        assert entity.state == MediaPlayerState.OFF

    def test_state_playing_via_mapped_entity(self):
        entity, _ = self._make_client(mappings={"client:RemoteClient": "media_player.kodi"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        assert entity.state == MediaPlayerState.PLAYING

    # -- available --

    def test_available_when_connected(self):
        entity, _ = self._make_client(connected=True)
        assert entity.available is True

    def test_unavailable_when_disconnected(self):
        entity, _ = self._make_client(connected=False)
        assert entity.available is False

    # -- mapping_key --

    def test_mapping_key(self):
        entity, _ = self._make_client()
        assert entity._mapping_key == "client:RemoteClient"

    # -- supported_features --

    def test_base_features(self):
        entity, _ = self._make_client()
        features = entity.supported_features
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.VOLUME_MUTE

    # -- volume --

    def test_volume_from_client(self):
        entity, _ = self._make_client()
        assert entity.volume_level == 0.8

    def test_volume_from_mapped_takes_priority(self):
        entity, _ = self._make_client(mappings={"client:RemoteClient": "media_player.kodi"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {"volume_level": 0.3}
        entity.hass.states.get.return_value = mock_state
        assert entity.volume_level == 0.3

    def test_volume_none_when_client_gone(self):
        entity, _ = self._make_client(clients=[])
        assert entity.volume_level is None

    def test_muted_from_client(self):
        entity, _ = self._make_client()
        assert entity.is_volume_muted is False

    def test_muted_from_mapped(self):
        entity, _ = self._make_client(mappings={"client:RemoteClient": "media_player.kodi"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {"is_volume_muted": True}
        entity.hass.states.get.return_value = mock_state
        assert entity.is_volume_muted is True

    def test_muted_false_when_client_gone(self):
        entity, _ = self._make_client(clients=[])
        assert entity.is_volume_muted is False

    # -- extra_state_attributes --

    def test_extra_attrs_connected(self):
        entity, _ = self._make_client()
        attrs = entity.extra_state_attributes
        assert attrs["status"] == "connected"
        assert attrs["client_name"] == "RemoteClient"
        assert attrs["remote_host"] == "remote-host"
        assert "client_id" in attrs

    def test_extra_attrs_disconnected(self):
        entity, _ = self._make_client(clients=[])
        attrs = entity.extra_state_attributes
        assert attrs["status"] == "disconnected"

    def test_extra_attrs_with_props(self):
        client = {**MOCK_REMOTE_CLIENTS[0], "props": {
            "native-protocol.peer": "192.168.1.50",
            "application.process.host": "remote-box",
            "application.version": "1.2.3",
        }}
        entity, _ = self._make_client(client_data=client, clients=[client])
        attrs = entity.extra_state_attributes
        assert attrs["connection"] == "192.168.1.50"
        assert attrs["remote_host"] == "remote-box"
        assert attrs["app_version"] == "1.2.3"

    def test_extra_attrs_with_mapped_entity(self):
        entity, _ = self._make_client(mappings={"client:RemoteClient": "media_player.kodi"})
        mock_state = MagicMock()
        mock_state.state = "playing"
        mock_state.attributes = {}
        entity.hass.states.get.return_value = mock_state
        attrs = entity.extra_state_attributes
        assert attrs["mapped_entity"] == "media_player.kodi"

    # -- _client --

    def test_client_found(self):
        entity, _ = self._make_client()
        client = entity._client()
        assert client is not None
        assert client.name == "RemoteClient"

    def test_client_not_found(self):
        entity, _ = self._make_client(clients=[])
        assert entity._client() is None

    # -- actions --

    async def test_set_volume_with_fallback(self):
        entity, hub = self._make_client()
        await entity.async_set_volume_level(0.5)
        hub.client.set_client_volume.assert_awaited_once_with("RemoteClient", 0.5)

    async def test_mute_with_fallback_toggles(self):
        entity, hub = self._make_client()
        await entity.async_mute_volume(True)
        hub.client.toggle_client_mute.assert_awaited_once_with("RemoteClient")

    async def test_mute_with_fallback_noop_when_already_unmuted(self):
        entity, hub = self._make_client()
        await entity.async_mute_volume(False)
        hub.client.toggle_client_mute.assert_not_awaited()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


class TestMediaPlayerAsyncSetupEntry:

    def _make_entry(self, hub, mappings=None):
        entry = MagicMock()
        entry.entry_id = ENTRY_ID
        entry.runtime_data.hub = hub
        entry.runtime_data.server_info = hub.server
        entry.runtime_data.device_info = MOCK_DEVICE_INFO
        entry.runtime_data.service_mappings = mappings or {}
        entry.async_on_unload = MagicMock()
        return entry

    async def test_creates_receiver_entity_only_without_backends(self):
        hub = make_hub(server_info={"hostname": "htpc", "backends": {}})
        entry = self._make_entry(hub)

        added = []
        await async_setup_entry(MagicMock(), entry, added.extend)

        assert len(added) == 1
        assert isinstance(added[0], OdioReceiverMediaPlayer)

    async def test_creates_all_entity_types(self):
        hub = make_hub(
            services=MOCK_SERVICES,
            audio=_audio(MOCK_REMOTE_CLIENTS),
            players=MOCK_PLAYERS,
        )
        entry = self._make_entry(hub, mappings={"user/mpd.service": "media_player.mpd"})

        added = []
        await async_setup_entry(MagicMock(), entry, added.extend)

        # 1 receiver + 1 mapped service + 1 remote client + 2 mpris
        assert len(added) == 5
        assert sum(isinstance(e, OdioServiceMediaPlayer) for e in added) == 1
        assert sum(isinstance(e, OdioPulseClientMediaPlayer) for e in added) == 1
        # dynamic listeners registered for services, clients and mpris
        assert entry.async_on_unload.call_count == 3
