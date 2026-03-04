"""Tests for media_player.py setup helpers."""
from unittest.mock import MagicMock

from custom_components.odio_remote.media_player import (
    OdioMPRISMediaPlayer,
    OdioPulseClientMediaPlayer,
    OdioServiceMediaPlayer,
    _MediaPlayerContext,
    _build_mpris_entities,
    _build_remote_client_entities,
    _build_service_entities,
    _register_dynamic_clients,
    _register_dynamic_mpris,
    _register_dynamic_services,
)

from .conftest import (
    MOCK_CLIENTS,
    MOCK_DEVICE_INFO,
    MOCK_PLAYERS,
    MOCK_REMOTE_CLIENTS,
    MOCK_SERVICES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_stream(sse_connected=True):
    es = MagicMock()
    es.sse_connected = sse_connected
    es.async_add_listener = MagicMock(return_value=lambda: None)
    return es


def _make_coordinator(data=None, last_update_success=True):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = last_update_success
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_ctx(
    service_coordinator=None,
    audio_coordinator=None,
    mpris_coordinator=None,
    service_mappings=None,
    server_hostname="htpc",
):
    return _MediaPlayerContext(
        entry_id="test_entry_id",
        event_stream=_make_event_stream(),
        audio_coordinator=audio_coordinator,
        service_coordinator=service_coordinator,
        mpris_coordinator=mpris_coordinator,
        api=MagicMock(),
        device_info=MOCK_DEVICE_INFO,
        service_mappings=service_mappings or {},
        backends={"pulseaudio": True, "systemd": True, "mpris": True},
        server_hostname=server_hostname,
    )


def _make_entry(ctx):
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.async_on_unload = MagicMock()
    return entry


# ---------------------------------------------------------------------------
# _build_service_entities
# ---------------------------------------------------------------------------

class TestBuildServiceEntities:

    def test_returns_entities_for_mapped_services(self):
        coord = _make_coordinator({"services": MOCK_SERVICES})
        mappings = {
            "user/mpd.service": "media_player.mpd",
            "user/shairport-sync.service": "media_player.shairport",
        }
        ctx = _make_ctx(service_coordinator=coord, service_mappings=mappings)
        entities = _build_service_entities(ctx)
        assert len(entities) == 2
        assert all(isinstance(e, OdioServiceMediaPlayer) for e in entities)

    def test_skips_unmapped_services(self):
        coord = _make_coordinator({"services": MOCK_SERVICES})
        ctx = _make_ctx(service_coordinator=coord, service_mappings={})
        entities = _build_service_entities(ctx)
        assert len(entities) == 0

    def test_skips_non_existing_services(self):
        services = [{"name": "gone.service", "scope": "user", "exists": False}]
        coord = _make_coordinator({"services": services})
        mappings = {"user/gone.service": "media_player.gone"}
        ctx = _make_ctx(service_coordinator=coord, service_mappings=mappings)
        entities = _build_service_entities(ctx)
        assert len(entities) == 0

    def test_returns_empty_when_no_coordinator(self):
        ctx = _make_ctx(service_coordinator=None)
        entities = _build_service_entities(ctx)
        assert entities == []

    def test_returns_empty_when_coordinator_has_no_data(self):
        coord = _make_coordinator(data=None)
        ctx = _make_ctx(service_coordinator=coord)
        entities = _build_service_entities(ctx)
        assert entities == []


# ---------------------------------------------------------------------------
# _build_remote_client_entities
# ---------------------------------------------------------------------------

class TestBuildRemoteClientEntities:

    def test_creates_entities_for_remote_clients(self):
        coord = _make_coordinator({"audio": MOCK_REMOTE_CLIENTS})
        ctx = _make_ctx(audio_coordinator=coord)
        entities = _build_remote_client_entities(ctx)
        assert len(entities) == 1
        assert isinstance(entities[0], OdioPulseClientMediaPlayer)

    def test_skips_local_clients(self):
        coord = _make_coordinator({"audio": MOCK_CLIENTS})
        ctx = _make_ctx(audio_coordinator=coord, server_hostname="htpc")
        entities = _build_remote_client_entities(ctx)
        assert len(entities) == 0

    def test_returns_empty_when_no_coordinator(self):
        ctx = _make_ctx(audio_coordinator=None)
        entities = _build_remote_client_entities(ctx)
        assert entities == []

    def test_returns_empty_when_coordinator_has_no_data(self):
        coord = _make_coordinator(data=None)
        ctx = _make_ctx(audio_coordinator=coord)
        entities = _build_remote_client_entities(ctx)
        assert entities == []

    def test_skips_clients_without_name(self):
        clients = [{"id": 1, "name": "", "host": "remote-host"}]
        coord = _make_coordinator({"audio": clients})
        ctx = _make_ctx(audio_coordinator=coord)
        entities = _build_remote_client_entities(ctx)
        assert entities == []


# ---------------------------------------------------------------------------
# _build_mpris_entities
# ---------------------------------------------------------------------------

class TestBuildMprisEntities:

    def test_creates_entities_for_available_players(self):
        coord = _make_coordinator({"mpris": MOCK_PLAYERS})
        ctx = _make_ctx(mpris_coordinator=coord)
        entities = _build_mpris_entities(ctx)
        assert len(entities) == 2
        assert all(isinstance(e, OdioMPRISMediaPlayer) for e in entities)

    def test_skips_unavailable_players(self):
        players = [{**MOCK_PLAYERS[0], "available": False}]
        coord = _make_coordinator({"mpris": players})
        ctx = _make_ctx(mpris_coordinator=coord)
        entities = _build_mpris_entities(ctx)
        assert entities == []

    def test_skips_players_without_bus_name(self):
        players = [{**MOCK_PLAYERS[0], "bus_name": ""}]
        coord = _make_coordinator({"mpris": players})
        ctx = _make_ctx(mpris_coordinator=coord)
        entities = _build_mpris_entities(ctx)
        assert entities == []

    def test_returns_empty_when_no_coordinator(self):
        ctx = _make_ctx(mpris_coordinator=None)
        entities = _build_mpris_entities(ctx)
        assert entities == []

    def test_returns_empty_when_coordinator_has_no_data(self):
        coord = _make_coordinator(data=None)
        ctx = _make_ctx(mpris_coordinator=coord)
        entities = _build_mpris_entities(ctx)
        assert entities == []


# ---------------------------------------------------------------------------
# _register_dynamic_services
# ---------------------------------------------------------------------------

class TestRegisterDynamicServices:

    def test_noop_when_no_coordinator(self):
        ctx = _make_ctx(service_coordinator=None)
        entry = _make_entry(ctx)
        _register_dynamic_services(entry, ctx, MagicMock(), [])
        entry.async_on_unload.assert_not_called()

    def test_registers_listener(self):
        coord = _make_coordinator({"services": []})
        ctx = _make_ctx(service_coordinator=coord)
        entry = _make_entry(ctx)
        _register_dynamic_services(entry, ctx, MagicMock(), [])
        coord.async_add_listener.assert_called_once()
        entry.async_on_unload.assert_called_once()

    def test_listener_adds_new_service_entities(self):
        coord = _make_coordinator({"services": []})
        mappings = {"user/mpd.service": "media_player.mpd"}
        ctx = _make_ctx(service_coordinator=coord, service_mappings=mappings)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_services(entry, ctx, async_add, [])

        # Simulate coordinator getting new data
        coord.data = {"services": MOCK_SERVICES}
        listener = coord.async_add_listener.call_args[0][0]
        listener()

        async_add.assert_called_once()
        new_entities = async_add.call_args[0][0]
        assert len(new_entities) == 1
        assert isinstance(new_entities[0], OdioServiceMediaPlayer)

    def test_listener_skips_already_known_services(self):
        coord = _make_coordinator({"services": MOCK_SERVICES})
        mappings = {"user/mpd.service": "media_player.mpd"}
        ctx = _make_ctx(service_coordinator=coord, service_mappings=mappings)
        initial_entities = _build_service_entities(ctx)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_services(entry, ctx, async_add, initial_entities)

        listener = coord.async_add_listener.call_args[0][0]
        listener()
        async_add.assert_not_called()


# ---------------------------------------------------------------------------
# _register_dynamic_clients
# ---------------------------------------------------------------------------

class TestRegisterDynamicClients:

    def test_noop_when_no_coordinator(self):
        ctx = _make_ctx(audio_coordinator=None)
        entry = _make_entry(ctx)
        _register_dynamic_clients(entry, ctx, MagicMock(), [])
        entry.async_on_unload.assert_not_called()

    def test_registers_listener(self):
        coord = _make_coordinator({"audio": []})
        ctx = _make_ctx(audio_coordinator=coord)
        entry = _make_entry(ctx)
        _register_dynamic_clients(entry, ctx, MagicMock(), [])
        coord.async_add_listener.assert_called_once()
        entry.async_on_unload.assert_called_once()

    def test_listener_adds_new_remote_clients(self):
        coord = _make_coordinator({"audio": []})
        ctx = _make_ctx(audio_coordinator=coord)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_clients(entry, ctx, async_add, [])

        coord.data = {"audio": MOCK_REMOTE_CLIENTS}
        listener = coord.async_add_listener.call_args[0][0]
        listener()

        async_add.assert_called_once()
        new_entities = async_add.call_args[0][0]
        assert len(new_entities) == 1
        assert isinstance(new_entities[0], OdioPulseClientMediaPlayer)

    def test_listener_skips_already_known_clients(self):
        coord = _make_coordinator({"audio": MOCK_REMOTE_CLIENTS})
        ctx = _make_ctx(audio_coordinator=coord)
        initial = _build_remote_client_entities(ctx)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_clients(entry, ctx, async_add, initial)

        listener = coord.async_add_listener.call_args[0][0]
        listener()
        async_add.assert_not_called()

    def test_listener_skips_local_clients(self):
        coord = _make_coordinator({"audio": []})
        ctx = _make_ctx(audio_coordinator=coord, server_hostname="htpc")
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_clients(entry, ctx, async_add, [])

        coord.data = {"audio": MOCK_CLIENTS}
        listener = coord.async_add_listener.call_args[0][0]
        listener()
        async_add.assert_not_called()


# ---------------------------------------------------------------------------
# _register_dynamic_mpris
# ---------------------------------------------------------------------------

class TestRegisterDynamicMpris:

    def test_noop_when_no_coordinator(self):
        ctx = _make_ctx(mpris_coordinator=None)
        entry = _make_entry(ctx)
        _register_dynamic_mpris(entry, ctx, MagicMock(), [])
        entry.async_on_unload.assert_not_called()

    def test_registers_listener(self):
        coord = _make_coordinator({"mpris": []})
        ctx = _make_ctx(mpris_coordinator=coord)
        entry = _make_entry(ctx)
        _register_dynamic_mpris(entry, ctx, MagicMock(), [])
        coord.async_add_listener.assert_called_once()
        entry.async_on_unload.assert_called_once()

    def test_listener_adds_new_players(self):
        coord = _make_coordinator({"mpris": []})
        ctx = _make_ctx(mpris_coordinator=coord)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, [])

        coord.data = {"mpris": MOCK_PLAYERS}
        listener = coord.async_add_listener.call_args[0][0]
        listener()

        async_add.assert_called_once()
        new_entities = async_add.call_args[0][0]
        assert len(new_entities) == 2
        assert all(isinstance(e, OdioMPRISMediaPlayer) for e in new_entities)

    def test_listener_skips_already_known_players(self):
        coord = _make_coordinator({"mpris": MOCK_PLAYERS})
        ctx = _make_ctx(mpris_coordinator=coord)
        initial = _build_mpris_entities(ctx)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, initial)

        listener = coord.async_add_listener.call_args[0][0]
        listener()
        async_add.assert_not_called()

    def test_listener_skips_unavailable_players(self):
        coord = _make_coordinator({"mpris": []})
        ctx = _make_ctx(mpris_coordinator=coord)
        entry = _make_entry(ctx)
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, [])

        coord.data = {"mpris": [{**MOCK_PLAYERS[0], "available": False}]}
        listener = coord.async_add_listener.call_args[0][0]
        listener()
        async_add.assert_not_called()
