"""Tests for Odio Remote switch platform."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.odio_remote.switch import OdioServiceSwitch, async_setup_entry

from .conftest import MOCK_ALL_SERVICES, MOCK_SERVER_INFO, MOCK_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(services=None, last_update_success=True):
    """Return a minimal mock OdioServiceCoordinator."""
    coord = MagicMock()
    coord.data = {"services": services} if services is not None else None
    coord.last_update_success = last_update_success
    coord.async_request_refresh = AsyncMock()
    return coord


def _make_switch(service_info, coordinator=None):
    """Instantiate OdioServiceSwitch with a mock coordinator."""
    if coordinator is None:
        coordinator = _make_coordinator([service_info])
    return OdioServiceSwitch(
        coordinator,
        api=MagicMock(),
        entry_id="test_entry_id",
        service_info=service_info,
        server_hostname="htpc",
    )


def _make_entry(service_coordinator):
    """Return a minimal mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.runtime_data.server_info = MOCK_SERVER_INFO
    entry.runtime_data.service_coordinator = service_coordinator
    entry.runtime_data.api = MagicMock()
    entry.runtime_data.device_connections = set()
    return entry


# ---------------------------------------------------------------------------
# Entity construction
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchConstruction:
    """Tests for OdioServiceSwitch identity and naming."""

    def test_unique_id(self):
        """unique_id encodes scope and service name."""
        svc = MOCK_SERVICES[0]  # mpd.service / user
        entity = _make_switch(svc)
        assert entity.unique_id == "test_entry_id_switch_user_mpd.service"

    def test_name_strips_service_suffix(self):
        """Name removes the '.service' suffix."""
        entity = _make_switch(MOCK_SERVICES[0])
        assert entity.name == "mpd"

    def test_name_without_service_suffix_unchanged(self):
        """A unit name without '.service' is kept as-is."""
        svc = {"name": "kodi", "scope": "user", "exists": True, "running": False}
        entity = _make_switch(svc)
        assert entity.name == "kodi"

    def test_has_entity_name(self):
        entity = _make_switch(MOCK_SERVICES[0])
        assert entity._attr_has_entity_name is True

    def test_device_info_uses_hostname(self):
        entity = _make_switch(MOCK_SERVICES[0])
        assert "htpc" in str(entity.device_info)


# ---------------------------------------------------------------------------
# is_on
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchIsOn:
    """Tests for the is_on property."""

    def test_is_on_when_running(self):
        """is_on is True when the service is running."""
        svc = MOCK_SERVICES[0]  # running=True
        entity = _make_switch(svc)
        assert entity.is_on is True

    def test_is_off_when_stopped(self):
        """is_on is False when the service is not running."""
        svc = MOCK_SERVICES[1]  # running=False
        entity = _make_switch(svc)
        assert entity.is_on is False

    def test_is_off_when_service_not_in_data(self):
        """is_on is False when the service name isn't present in coordinator data."""
        svc = {"name": "unknown.service", "scope": "user", "exists": True, "running": True}
        # coordinator holds mpd data, not unknown.service
        coord = _make_coordinator([MOCK_SERVICES[0]])
        entity = _make_switch(svc, coordinator=coord)
        assert entity.is_on is False

    def test_is_off_when_coordinator_data_is_none(self):
        """is_on is False when coordinator.data is None."""
        coord = _make_coordinator(services=None)
        entity = _make_switch(MOCK_SERVICES[0], coordinator=coord)
        assert entity.is_on is False

    def test_is_on_matches_scope(self):
        """is_on checks both name and scope to avoid false positives."""
        user_svc = {"name": "mpd.service", "scope": "user", "exists": True, "running": True}
        system_svc = {"name": "mpd.service", "scope": "system", "exists": True, "running": False}
        coord = _make_coordinator([system_svc])  # only system-scope in data
        entity = _make_switch(user_svc, coordinator=coord)
        assert entity.is_on is False


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchAvailable:
    """Tests for the available property."""

    def test_available_when_coordinator_ok(self):
        coord = _make_coordinator(MOCK_SERVICES, last_update_success=True)
        entity = _make_switch(MOCK_SERVICES[0], coordinator=coord)
        assert entity.available is True

    def test_unavailable_when_last_update_failed(self):
        coord = _make_coordinator(MOCK_SERVICES, last_update_success=False)
        entity = _make_switch(MOCK_SERVICES[0], coordinator=coord)
        assert entity.available is False

    def test_unavailable_when_data_is_none(self):
        coord = _make_coordinator(services=None, last_update_success=True)
        entity = _make_switch(MOCK_SERVICES[0], coordinator=coord)
        assert entity.available is False


# ---------------------------------------------------------------------------
# Turn on / turn off
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchActions:
    """Tests for async_turn_on and async_turn_off."""

    @pytest.mark.asyncio
    async def test_turn_on_calls_start(self):
        """async_turn_on issues a 'start' action for the correct scope/unit."""
        svc = MOCK_SERVICES[1]  # shairport-sync.service / user / stopped
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(coord, api, "test_entry_id", svc, "htpc")

        with patch("custom_components.odio_remote.switch.asyncio.sleep", new=AsyncMock()):
            await entity.async_turn_on()

        api.control_service.assert_awaited_once_with(
            "start", "user", "shairport-sync.service"
        )

    @pytest.mark.asyncio
    async def test_turn_on_requests_refresh(self):
        """async_turn_on triggers a coordinator refresh after the delay."""
        svc = MOCK_SERVICES[1]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(coord, api, "test_entry_id", svc, "htpc")

        with patch("custom_components.odio_remote.switch.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await entity.async_turn_on()

        mock_sleep.assert_awaited_once_with(2)
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_calls_stop(self):
        """async_turn_off issues a 'stop' action for the correct scope/unit."""
        svc = MOCK_SERVICES[0]  # mpd.service / user / running
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(coord, api, "test_entry_id", svc, "htpc")

        with patch("custom_components.odio_remote.switch.asyncio.sleep", new=AsyncMock()):
            await entity.async_turn_off()

        api.control_service.assert_awaited_once_with(
            "stop", "user", "mpd.service"
        )

    @pytest.mark.asyncio
    async def test_turn_off_requests_refresh(self):
        """async_turn_off triggers a coordinator refresh after the delay."""
        svc = MOCK_SERVICES[0]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(coord, api, "test_entry_id", svc, "htpc")

        with patch("custom_components.odio_remote.switch.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await entity.async_turn_off()

        mock_sleep.assert_awaited_once_with(2)
        coord.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestOdioSwitchSetupEntry:
    """Tests for the async_setup_entry platform entry point."""

    @pytest.mark.asyncio
    async def test_creates_user_scope_entities(self):
        """Only user-scope services become switch entities."""
        # MOCK_ALL_SERVICES has 1 system + 5 user services, all existing
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []

        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))

        assert len(added) == 5  # all user-scope ones
        for entity in added:
            assert entity._service_info["scope"] == "user"

    @pytest.mark.asyncio
    async def test_filters_system_scope(self):
        """System-scope services are excluded."""
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []

        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))

        names = [e._service_info["name"] for e in added]
        assert "bluetooth.service" not in names

    @pytest.mark.asyncio
    async def test_filters_non_existing_services(self):
        """Services with exists=False are excluded."""
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
        """No entities are created when service_coordinator is None."""
        entry = _make_entry(service_coordinator=None)
        add_entities = MagicMock()

        await async_setup_entry(MagicMock(), entry, add_entities)

        add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entities_when_coordinator_data_is_none(self):
        """No entities are created when coordinator.data is None."""
        coord = _make_coordinator(services=None)
        entry = _make_entry(coord)
        add_entities = MagicMock()

        await async_setup_entry(MagicMock(), entry, add_entities)

        add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_entity_names_strip_service_suffix(self):
        """Entities created by setup have names without '.service'."""
        coord = _make_coordinator(MOCK_SERVICES)
        entry = _make_entry(coord)
        added = []

        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))

        names = {e.name for e in added}
        assert names == {"mpd", "shairport-sync", "snapclient"}
