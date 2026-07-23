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
    make_hub,
    push_event,
)

EMITTED_AT_MS = 1770000000000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(hub, service_mappings=None, server_hostname="htpc"):
    return _MediaPlayerContext(
        entry_id="test_entry_id",
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        service_mappings=service_mappings or {},
        backends=hub.server.backends,
        server_hostname=server_hostname,
    )


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.async_on_unload = MagicMock()
    return entry


def _player_added(player_data):
    return {"data": player_data, "emitted_at": EMITTED_AT_MS}


# ---------------------------------------------------------------------------
# _build_service_entities
# ---------------------------------------------------------------------------

class TestBuildServiceEntities:

    def test_returns_entities_for_mapped_services(self):
        hub = make_hub(services=MOCK_SERVICES)
        mappings = {
            "user/mpd.service": "media_player.mpd",
            "user/shairport-sync.service": "media_player.shairport",
        }
        entities = _build_service_entities(_make_ctx(hub, service_mappings=mappings))
        assert len(entities) == 2
        assert all(isinstance(e, OdioServiceMediaPlayer) for e in entities)

    def test_skips_unmapped_services(self):
        hub = make_hub(services=MOCK_SERVICES)
        entities = _build_service_entities(_make_ctx(hub))
        assert len(entities) == 0

    def test_skips_non_existing_services(self):
        services = [{"name": "gone.service", "scope": "user", "exists": False}]
        hub = make_hub(services=services)
        mappings = {"user/gone.service": "media_player.gone"}
        entities = _build_service_entities(_make_ctx(hub, service_mappings=mappings))
        assert len(entities) == 0

    def test_returns_empty_when_no_services(self):
        hub = make_hub()
        entities = _build_service_entities(_make_ctx(hub))
        assert entities == []


# ---------------------------------------------------------------------------
# _build_remote_client_entities
# ---------------------------------------------------------------------------

class TestBuildRemoteClientEntities:

    def test_creates_entities_for_remote_clients(self):
        hub = make_hub(audio={"kind": "pipewire", "clients": MOCK_REMOTE_CLIENTS, "outputs": []})
        entities = _build_remote_client_entities(_make_ctx(hub))
        assert len(entities) == 1
        assert isinstance(entities[0], OdioPulseClientMediaPlayer)

    def test_skips_local_clients(self):
        hub = make_hub(audio={"kind": "pipewire", "clients": MOCK_CLIENTS, "outputs": []})
        entities = _build_remote_client_entities(_make_ctx(hub, server_hostname="htpc"))
        assert len(entities) == 0

    def test_returns_empty_when_no_clients(self):
        hub = make_hub()
        entities = _build_remote_client_entities(_make_ctx(hub))
        assert entities == []

    def test_skips_clients_without_name(self):
        clients = [{"id": 1, "name": "", "host": "remote-host"}]
        hub = make_hub(audio={"kind": "pipewire", "clients": clients, "outputs": []})
        entities = _build_remote_client_entities(_make_ctx(hub))
        assert entities == []


# ---------------------------------------------------------------------------
# _build_mpris_entities
# ---------------------------------------------------------------------------

class TestBuildMprisEntities:

    def test_creates_entities_for_available_players(self):
        hub = make_hub(players=MOCK_PLAYERS)
        entities = _build_mpris_entities(_make_ctx(hub))
        assert len(entities) == 2
        assert all(isinstance(e, OdioMPRISMediaPlayer) for e in entities)

    def test_skips_removed_players(self):
        hub = make_hub(players=MOCK_PLAYERS)
        push_event(hub, "player.removed", {"bus_name": MOCK_PLAYERS[0]["bus_name"]})
        entities = _build_mpris_entities(_make_ctx(hub))
        assert len(entities) == 1
        assert entities[0]._player_name == MOCK_PLAYERS[1]["bus_name"]

    def test_skips_players_without_bus_name(self):
        players = [{**MOCK_PLAYERS[0], "bus_name": ""}]
        hub = make_hub(players=players)
        entities = _build_mpris_entities(_make_ctx(hub))
        assert entities == []

    def test_returns_empty_when_no_players(self):
        hub = make_hub()
        entities = _build_mpris_entities(_make_ctx(hub))
        assert entities == []

    def test_deduplicates_same_app_name(self):
        players = [
            {**MOCK_PLAYERS[1], "bus_name": "org.mpris.MediaPlayer2.chromium.instance1"},
            {**MOCK_PLAYERS[1], "bus_name": "org.mpris.MediaPlayer2.chromium.instance2"},
            {**MOCK_PLAYERS[1], "bus_name": "org.mpris.MediaPlayer2.chromium.instance3"},
        ]
        hub = make_hub(players=players)
        entities = _build_mpris_entities(_make_ctx(hub))
        assert len(entities) == 1
        assert entities[0]._player_name == "org.mpris.MediaPlayer2.chromium.instance1"


# ---------------------------------------------------------------------------
# _register_dynamic_services
# ---------------------------------------------------------------------------

class TestRegisterDynamicServices:

    def test_registers_unload_listener(self):
        hub = make_hub()
        entry = _make_entry()
        _register_dynamic_services(entry, _make_ctx(hub), MagicMock(), [])
        entry.async_on_unload.assert_called_once()

    def test_event_adds_new_service_entity(self):
        hub = make_hub()
        mappings = {"user/mpd.service": "media_player.mpd"}
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_services(entry, _make_ctx(hub, service_mappings=mappings), async_add, [])

        push_event(hub, "service.updated", MOCK_SERVICES[0])

        async_add.assert_called_once()
        new_entities = async_add.call_args[0][0]
        assert len(new_entities) == 1
        assert isinstance(new_entities[0], OdioServiceMediaPlayer)

    def test_event_skips_unmapped_service(self):
        hub = make_hub()
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_services(entry, _make_ctx(hub), async_add, [])

        push_event(hub, "service.updated", MOCK_SERVICES[0])
        async_add.assert_not_called()

    def test_event_skips_already_known_service(self):
        hub = make_hub(services=MOCK_SERVICES)
        mappings = {"user/mpd.service": "media_player.mpd"}
        ctx = _make_ctx(hub, service_mappings=mappings)
        initial = _build_service_entities(ctx)
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_services(entry, ctx, async_add, initial)

        push_event(hub, "service.updated", MOCK_SERVICES[0])
        async_add.assert_not_called()


# ---------------------------------------------------------------------------
# _register_dynamic_clients
# ---------------------------------------------------------------------------

class TestRegisterDynamicClients:

    def test_registers_unload_listener(self):
        hub = make_hub()
        entry = _make_entry()
        _register_dynamic_clients(entry, _make_ctx(hub), MagicMock(), [])
        entry.async_on_unload.assert_called_once()

    def test_event_adds_new_remote_client(self):
        hub = make_hub(audio={"kind": "pipewire", "clients": [], "outputs": []})
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_clients(entry, _make_ctx(hub), async_add, [])

        push_event(hub, "audio.updated", MOCK_REMOTE_CLIENTS[0])

        async_add.assert_called_once()
        new_entities = async_add.call_args[0][0]
        assert len(new_entities) == 1
        assert isinstance(new_entities[0], OdioPulseClientMediaPlayer)

    def test_event_skips_already_known_client(self):
        hub = make_hub(audio={"kind": "pipewire", "clients": MOCK_REMOTE_CLIENTS, "outputs": []})
        ctx = _make_ctx(hub)
        initial = _build_remote_client_entities(ctx)
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_clients(entry, ctx, async_add, initial)

        push_event(hub, "audio.updated", MOCK_REMOTE_CLIENTS[0])
        async_add.assert_not_called()

    def test_event_skips_local_client(self):
        hub = make_hub(audio={"kind": "pipewire", "clients": [], "outputs": []})
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_clients(entry, _make_ctx(hub, server_hostname="htpc"), async_add, [])

        push_event(hub, "audio.updated", MOCK_CLIENTS[0])
        async_add.assert_not_called()


# ---------------------------------------------------------------------------
# _register_dynamic_mpris
# ---------------------------------------------------------------------------

class TestRegisterDynamicMpris:

    def test_registers_unload_listener(self):
        hub = make_hub()
        entry = _make_entry()
        _register_dynamic_mpris(entry, _make_ctx(hub), MagicMock(), [])
        entry.async_on_unload.assert_called_once()

    def test_event_adds_new_players(self):
        hub = make_hub()
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_mpris(entry, _make_ctx(hub), async_add, [])

        push_event(hub, "player.added", _player_added(MOCK_PLAYERS[0]))
        push_event(hub, "player.added", _player_added(MOCK_PLAYERS[1]))

        assert async_add.call_count == 2
        added = [call[0][0][0] for call in async_add.call_args_list]
        assert all(isinstance(e, OdioMPRISMediaPlayer) for e in added)

    def test_event_skips_already_known_player(self):
        hub = make_hub(players=MOCK_PLAYERS)
        ctx = _make_ctx(hub)
        initial = _build_mpris_entities(ctx)
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, initial)

        push_event(hub, "player.added", _player_added(MOCK_PLAYERS[0]))
        async_add.assert_not_called()

    def test_event_skips_same_app_name_when_entity_available(self):
        hub = make_hub(players=[MOCK_PLAYERS[1]])
        ctx = _make_ctx(hub)
        initial = _build_mpris_entities(ctx)
        entity = initial[0]
        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, initial)

        # New chromium instance while instance1 is still alive — ignored.
        push_event(hub, "player.added", _player_added(
            {**MOCK_PLAYERS[1], "bus_name": "org.mpris.MediaPlayer2.chromium.instance2"}
        ))
        async_add.assert_not_called()
        assert entity._player_name == "org.mpris.MediaPlayer2.chromium.instance1"

    def test_event_rebinds_unavailable_entity_to_new_bus_name(self):
        hub = make_hub(players=[MOCK_PLAYERS[1]])
        ctx = _make_ctx(hub)
        initial = _build_mpris_entities(ctx)
        assert len(initial) == 1
        entity = initial[0]
        assert entity._player_name == "org.mpris.MediaPlayer2.chromium.instance1"
        entity.async_write_ha_state = MagicMock()

        entry = _make_entry()
        async_add = MagicMock()
        _register_dynamic_mpris(entry, ctx, async_add, initial)

        # Chrome restart: instance1 goes away, instance2 appears.
        push_event(hub, "player.removed", {"bus_name": "org.mpris.MediaPlayer2.chromium.instance1"})
        assert entity.available is False

        instance2_bus = "org.mpris.MediaPlayer2.chromium.instance2"
        push_event(hub, "player.added", _player_added(
            {**MOCK_PLAYERS[1], "bus_name": instance2_bus, "playback_status": "Playing"}
        ))

        # No new entity created — existing one was rebound.
        async_add.assert_not_called()
        assert entity._player_name == instance2_bus
        entity.async_write_ha_state.assert_called_once()
