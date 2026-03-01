"""Tests for Odio Remote switch platform."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.odio_remote.switch import OdioServiceSwitch, _SwitchContext, async_setup_entry

from .conftest import MOCK_ALL_SERVICES, MOCK_DEVICE_INFO, MOCK_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(services=None, last_update_success=True):
    coord = MagicMock()
    coord.data = {"services": services} if services is not None else None
    coord.last_update_success = last_update_success
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_ctx(coordinator=None, service_info=None):
    if coordinator is None:
        coordinator = _make_coordinator([service_info] if service_info else [])
    return _SwitchContext(
        entry_id="test_entry_id",
        service_coordinator=coordinator,
        api=MagicMock(),
        device_info=MOCK_DEVICE_INFO,
    )


def _make_switch(service_info, coordinator=None):
    if coordinator is None:
        coordinator = _make_coordinator([service_info])
    return OdioServiceSwitch(_make_ctx(coordinator), service_info)


def _make_entry(service_coordinator):
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.runtime_data.service_coordinator = service_coordinator
    entry.runtime_data.api = MagicMock()
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.async_on_unload = MagicMock()
    return entry


# ---------------------------------------------------------------------------
# Entity construction
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchConstruction:

    def test_unique_id(self):
        entity = _make_switch(MOCK_SERVICES[0])
        assert entity.unique_id == "test_entry_id_switch_user_mpd.service"

    def test_name_strips_service_suffix(self):
        assert _make_switch(MOCK_SERVICES[0]).name == "mpd"

    def test_name_without_service_suffix_unchanged(self):
        svc = {"name": "kodi", "scope": "user", "exists": True, "running": False}
        assert _make_switch(svc).name == "kodi"

    def test_has_entity_name(self):
        assert _make_switch(MOCK_SERVICES[0])._attr_has_entity_name is True

    def test_device_info_uses_hostname(self):
        assert "htpc" in str(_make_switch(MOCK_SERVICES[0]).device_info)


# ---------------------------------------------------------------------------
# is_on
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchIsOn:

    def test_is_on_when_running(self):
        assert _make_switch(MOCK_SERVICES[0]).is_on is True

    def test_is_off_when_stopped(self):
        assert _make_switch(MOCK_SERVICES[1]).is_on is False

    def test_is_off_when_service_not_in_data(self):
        svc = {"name": "unknown.service", "scope": "user", "exists": True, "running": True}
        entity = _make_switch(svc, coordinator=_make_coordinator([MOCK_SERVICES[0]]))
        assert entity.is_on is False

    def test_is_off_when_coordinator_data_is_none(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(services=None))
        assert entity.is_on is False

    def test_is_on_matches_scope(self):
        user_svc = {"name": "mpd.service", "scope": "user", "exists": True, "running": True}
        system_svc = {"name": "mpd.service", "scope": "system", "exists": True, "running": False}
        entity = _make_switch(user_svc, coordinator=_make_coordinator([system_svc]))
        assert entity.is_on is False


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchAvailable:

    def test_available_when_coordinator_ok(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(MOCK_SERVICES, last_update_success=True))
        assert entity.available is True

    def test_unavailable_when_last_update_failed(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(MOCK_SERVICES, last_update_success=False))
        assert entity.available is False

    def test_unavailable_when_data_is_none(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(services=None))
        assert entity.available is False


# ---------------------------------------------------------------------------
# Turn on / turn off
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchActions:

    @pytest.mark.asyncio
    async def test_turn_on_calls_start(self):
        svc = MOCK_SERVICES[1]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        ctx = _SwitchContext("test_entry_id", coord, api, MOCK_DEVICE_INFO)
        entity = OdioServiceSwitch(ctx, svc)

        await entity.async_turn_on()

        api.control_service.assert_awaited_once_with("start", "user", "shairport-sync.service")

    @pytest.mark.asyncio
    async def test_turn_on_does_not_poll(self):
        """State update is driven by SSE — no manual refresh after action."""
        svc = MOCK_SERVICES[1]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_SwitchContext("test_entry_id", coord, api, MOCK_DEVICE_INFO), svc)

        await entity.async_turn_on()

        coord.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_calls_stop(self):
        svc = MOCK_SERVICES[0]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_SwitchContext("test_entry_id", coord, api, MOCK_DEVICE_INFO), svc)

        await entity.async_turn_off()

        api.control_service.assert_awaited_once_with("stop", "user", "mpd.service")

    @pytest.mark.asyncio
    async def test_turn_off_does_not_poll(self):
        """State update is driven by SSE — no manual refresh after action."""
        svc = MOCK_SERVICES[0]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_SwitchContext("test_entry_id", coord, api, MOCK_DEVICE_INFO), svc)

        await entity.async_turn_off()

        coord.async_request_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestOdioSwitchSetupEntry:

    @pytest.mark.asyncio
    async def test_creates_user_scope_entities(self):
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 5
        for entity in added:
            assert entity._service_info["scope"] == "user"

    @pytest.mark.asyncio
    async def test_filters_system_scope(self):
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert "bluetooth.service" not in [e._service_info["name"] for e in added]

    @pytest.mark.asyncio
    async def test_filters_non_existing_services(self):
        services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "running": False},
            {"name": "ghost.service", "scope": "user", "exists": False, "running": False},
        ]
        coord = _make_coordinator(services)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert added[0]._service_info["name"] == "mpd.service"

    @pytest.mark.asyncio
    async def test_no_entities_when_no_coordinator(self):
        entry = _make_entry(service_coordinator=None)
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entities_when_coordinator_data_is_none(self):
        coord = _make_coordinator(services=None)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []

    @pytest.mark.asyncio
    async def test_entity_names_strip_service_suffix(self):
        coord = _make_coordinator(MOCK_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert {e.name for e in added} == {"mpd", "shairport-sync", "snapclient"}
