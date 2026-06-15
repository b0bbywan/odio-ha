"""Tests for Odio Remote upgrade coordinator and update platform."""
import asyncio
from dataclasses import dataclass

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.odio_remote.api_client import SseEvent
from custom_components.odio_remote.const import DOMAIN
from custom_components.odio_remote.coordinator import OdioUpgradeCoordinator
from custom_components.odio_remote.exceptions import (
    OdioApiError,
    OdioConnectionError,
    OdioTimeoutError,
)
from custom_components.odio_remote.update import OdioUpdateEntity, async_setup_entry

from .conftest import MOCK_DEVICE_INFO

ENTRY_ID = "test_entry_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    try:
        hass.loop = asyncio.get_running_loop()
    except RuntimeError:
        hass.loop = MagicMock()
    return hass


def _make_coordinator(api=None, data=None):
    coord = OdioUpgradeCoordinator(_make_hass(), MagicMock(), api or MagicMock())
    if data is not None:
        coord.async_set_updated_data(data)
    return coord


# ---------------------------------------------------------------------------
# OdioUpgradeCoordinator._async_update_data
# ---------------------------------------------------------------------------

class TestUpgradeCoordinatorUpdate:

    @pytest.mark.asyncio
    async def test_fetches_detector_status(self):
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(
            return_value={"current": "1.0.0", "latest": "1.1.0", "upgrade_available": True}
        )
        coord = _make_coordinator(api)

        result = await coord._async_update_data()

        assert result["current"] == "1.0.0"
        assert result["latest"] == "1.1.0"
        assert result["upgrade_available"] is True
        assert result["in_progress"] is False

    @pytest.mark.asyncio
    async def test_handles_null_status(self):
        """API returns null when the detector has not produced a result yet."""
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(return_value=None)
        coord = _make_coordinator(api)

        result = await coord._async_update_data()

        assert result["current"] is None
        assert result["upgrade_available"] is False

    @pytest.mark.asyncio
    async def test_applies_active_run_from_get(self):
        """GET /upgrade reports the active run under "run" — it is authoritative."""
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(
            return_value={
                "current": "1.0.0",
                "latest": "1.1.0",
                "upgrade_available": True,
                "can_upgrade": True,
                "run": {"state": "running", "percent": 42, "step": "mpd"},
            }
        )
        coord = _make_coordinator(api)

        result = await coord._async_update_data()

        assert result["in_progress"] is True
        assert result["percent"] == 42
        assert result["step"] == "mpd"
        assert result["can_upgrade"] is True

    @pytest.mark.asyncio
    async def test_no_run_clears_stale_progress(self):
        """A GET without "run" means no active run, overriding stale state."""
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(
            return_value={"current": "1.0.0", "latest": "1.1.0", "upgrade_available": True}
        )
        coord = _make_coordinator(api)
        coord.data = {"in_progress": True, "percent": 42, "step": "mpd"}

        result = await coord._async_update_data()

        assert result["in_progress"] is False
        assert result["percent"] is None
        assert result["step"] is None
        assert result["can_upgrade"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("err", [OdioConnectionError("x"), OdioTimeoutError("x")])
    async def test_connection_errors_wrapped(self, err):
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(side_effect=err)
        coord = _make_coordinator(api)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_api_error_wrapped(self):
        api = MagicMock()
        api.get_upgrade_status = AsyncMock(side_effect=OdioApiError("boom"))
        coord = _make_coordinator(api)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# OdioUpgradeCoordinator.handle_sse_event
# ---------------------------------------------------------------------------

class TestUpgradeCoordinatorSse:

    def _evt(self, data):
        return SseEvent(type="upgrade.info", data=data)

    def _pevt(self, data):
        return SseEvent(type="upgrade.progress", data=data)

    def test_detector_status(self):
        coord = _make_coordinator(data={"in_progress": False})
        coord.handle_sse_event(
            self._evt({
                "current": "1.0.0",
                "latest": "2.0.0",
                "upgrade_available": True,
                "can_upgrade": True,
            })
        )
        assert coord.data["current"] == "1.0.0"
        assert coord.data["latest"] == "2.0.0"
        assert coord.data["upgrade_available"] is True
        assert coord.data["can_upgrade"] is True

    def test_detector_status_with_active_run(self):
        coord = _make_coordinator(data={"in_progress": False})
        coord.handle_sse_event(
            self._evt({
                "current": "1.0.0",
                "latest": "2.0.0",
                "upgrade_available": True,
                "run": {"state": "running", "percent": 30, "step": "mpd"},
            })
        )
        assert coord.data["in_progress"] is True
        assert coord.data["percent"] == 30
        assert coord.data["step"] == "mpd"

    def test_lifecycle_running(self):
        coord = _make_coordinator(data={"in_progress": False})
        coord.handle_sse_event(self._evt({"state": "running"}))
        assert coord.data["in_progress"] is True

    def test_lifecycle_finished_resets_progress(self):
        coord = _make_coordinator(
            data={"in_progress": True, "percent": 80, "step": "mpd"}
        )
        coord.handle_sse_event(self._evt({"state": "finished", "success": True}))
        assert coord.data["in_progress"] is False
        assert coord.data["percent"] is None
        assert coord.data["step"] is None

    def test_lifecycle_finished_success_clears_available(self):
        """A successful run clears upgrade_available without re-detection."""
        coord = _make_coordinator(
            data={"in_progress": True, "upgrade_available": True, "latest": "2.0.0"}
        )
        coord.handle_sse_event(self._evt({"state": "finished", "success": True}))
        assert coord.data["upgrade_available"] is False

    def test_lifecycle_finished_failure_keeps_available(self):
        """A failed run leaves the upgrade available to retry."""
        coord = _make_coordinator(
            data={"in_progress": True, "upgrade_available": True, "latest": "2.0.0"}
        )
        coord.handle_sse_event(self._evt({"state": "finished", "success": False}))
        assert coord.data["upgrade_available"] is True

    def test_progress_begin_sets_zero(self):
        coord = _make_coordinator(data={"in_progress": True})
        coord.handle_sse_event(self._pevt({"event": "begin", "total": 7}))
        assert coord.data["in_progress"] is True
        assert coord.data["percent"] == 0

    def test_progress_update(self):
        coord = _make_coordinator(data={"in_progress": True})
        coord.handle_sse_event(
            self._pevt({"event": "progress", "percent": 42, "current": 3, "step": "mpd"})
        )
        assert coord.data["percent"] == 42
        assert coord.data["step"] == "mpd"
        assert coord.data["in_progress"] is True

    def test_progress_end_keeps_in_progress(self):
        """The script's end precedes the systemd result, which owns completion."""
        coord = _make_coordinator(data={"in_progress": True, "percent": 99})
        coord.handle_sse_event(self._pevt({"event": "end", "success": True}))
        assert coord.data["in_progress"] is True
        assert coord.data["percent"] == 100

    def test_lifecycle_finished_after_progress_end_completes(self):
        """The authoritative finished event is what flips the entity to idle."""
        coord = _make_coordinator(data={"in_progress": True, "percent": 100})
        coord.handle_sse_event(self._evt({"state": "finished", "success": True}))
        assert coord.data["in_progress"] is False
        assert coord.data["percent"] is None

    def test_non_dict_ignored(self):
        coord = _make_coordinator(data={"in_progress": False})
        coord.handle_sse_event(self._evt(["not", "a", "dict"]))
        assert coord.data == {"in_progress": False}

    def test_unrecognized_payload_ignored(self):
        coord = _make_coordinator(data={"current": "1.0.0"})
        coord.handle_sse_event(self._evt({"foo": "bar"}))
        assert coord.data == {"current": "1.0.0"}

    def test_dispatch_by_event_type_not_keys(self):
        """An info detector payload that also carries an 'event' key isn't misrouted to progress."""
        coord = _make_coordinator(data={"percent": 50})
        coord.handle_sse_event(
            self._evt({"upgrade_available": True, "latest": "2.0.0", "event": "progress"})
        )
        assert coord.data["upgrade_available"] is True
        assert coord.data["latest"] == "2.0.0"
        assert coord.data["percent"] == 50


# ---------------------------------------------------------------------------
# OdioUpdateEntity
# ---------------------------------------------------------------------------

class TestOdioUpdateEntity:

    def _make_entity(self, data=None, api=None, fallback="api-v1"):
        coord = _make_coordinator(api=api, data=data)
        return OdioUpdateEntity(coord, api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO, fallback)

    def test_installed_version_from_detector(self):
        entity = self._make_entity({"current": "1.0.0", "upgrade_available": False})
        assert entity.installed_version == "1.0.0"

    def test_installed_version_fallback(self):
        entity = self._make_entity({"upgrade_available": False}, fallback="api-v1")
        assert entity.installed_version == "api-v1"

    def test_latest_version_when_available(self):
        entity = self._make_entity(
            {"current": "1.0.0", "latest": "2.0.0", "upgrade_available": True}
        )
        assert entity.latest_version == "2.0.0"

    def test_latest_version_mirrors_installed_when_up_to_date(self):
        entity = self._make_entity(
            {"current": "1.0.0", "latest": "2.0.0", "upgrade_available": False}
        )
        assert entity.latest_version == "1.0.0"

    def test_latest_version_unknown_when_available_without_target(self):
        """An available upgrade with no named target must not mirror installed.

        Mirroring would make latest == installed and HA report STATE_OFF,
        masking the update. We return None (HA shows "unknown") instead.
        """
        entity = self._make_entity(
            {"current": "1.0.0", "upgrade_available": True}
        )
        assert entity.latest_version is None

    def test_in_progress(self):
        assert self._make_entity({"in_progress": True}).in_progress is True
        assert self._make_entity({"in_progress": False}).in_progress is False

    def test_update_percentage(self):
        entity = self._make_entity({"in_progress": True, "percent": 42})
        assert entity.update_percentage == 42

    def test_update_percentage_none_when_idle(self):
        entity = self._make_entity({"in_progress": False, "percent": 42})
        assert entity.update_percentage is None

    @pytest.mark.asyncio
    async def test_install_calls_api(self):
        api = MagicMock()
        api.upgrade_start = AsyncMock()
        entity = self._make_entity({"upgrade_available": True}, api=api)
        await entity.async_install(version=None, backup=False)
        api.upgrade_start.assert_awaited_once()

    def test_supported_features_install_when_can_upgrade(self):
        entity = self._make_entity({"can_upgrade": True})
        assert entity.supported_features & UpdateEntityFeature.INSTALL
        assert entity.supported_features & UpdateEntityFeature.PROGRESS

    def test_supported_features_no_install_when_cannot_upgrade(self):
        entity = self._make_entity({"can_upgrade": False})
        assert not entity.supported_features & UpdateEntityFeature.INSTALL
        assert entity.supported_features & UpdateEntityFeature.PROGRESS

    def test_unique_id(self):
        assert self._make_entity({}).unique_id == f"{ENTRY_ID}_firmware_update"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in self._make_entity({}).device_info["identifiers"]


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

@dataclass
class _Coordinators:
    upgrade: object = None


@dataclass
class _RuntimeData:
    api: object
    device_info: object
    server_info: object
    coordinators: object


class _Entry:
    def __init__(self, upgrade_coord):
        self.entry_id = ENTRY_ID
        self.runtime_data = _RuntimeData(
            api=MagicMock(),
            device_info=MOCK_DEVICE_INFO,
            server_info=MagicMock(api_version="api-v1"),
            coordinators=_Coordinators(upgrade=upgrade_coord),
        )


class TestUpdateSetup:

    @pytest.mark.asyncio
    async def test_no_entity_when_backend_disabled(self):
        entry = _Entry(upgrade_coord=None)
        added = []
        await async_setup_entry(None, entry, lambda e: added.extend(e))
        assert added == []

    @pytest.mark.asyncio
    async def test_entity_created_when_backend_enabled(self):
        entry = _Entry(upgrade_coord=_make_coordinator(data={}))
        added = []
        await async_setup_entry(None, entry, lambda e: added.extend(e))
        assert len(added) == 1
        assert isinstance(added[0], OdioUpdateEntity)
