"""Tests for the Odio Remote update platform (pyodio-backed)."""
import pytest
from unittest.mock import MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.exceptions import HomeAssistantError
from pyodio import OdioApiError

from custom_components.odio_remote.const import DOMAIN
from custom_components.odio_remote.update import OdioUpdateEntity, async_setup_entry

from .conftest import MOCK_DEVICE_INFO, MOCK_SERVER_INFO, make_hub, push_event

ENTRY_ID = "test_entry_id"

UPGRADE_SERVER_INFO = {
    **MOCK_SERVER_INFO,
    "backends": {**MOCK_SERVER_INFO["backends"], "upgrade": True},
}

UPGRADE_AVAILABLE = {
    "current": "1.0.0",
    "latest": "1.1.0",
    "upgrade_available": True,
    "can_upgrade": True,
    "run": {"state": "idle"},
}

UPGRADE_RUNNING = {
    **UPGRADE_AVAILABLE,
    "run": {"state": "running", "percent": 42, "step": "mpd"},
}


def _make_entity(upgrade=None, fallback="api-v1"):
    hub = make_hub(server_info=UPGRADE_SERVER_INFO, upgrade=upgrade)
    return hub, OdioUpdateEntity(hub, ENTRY_ID, MOCK_DEVICE_INFO, fallback)


# ---------------------------------------------------------------------------
# OdioUpdateEntity — properties
# ---------------------------------------------------------------------------

class TestOdioUpdateEntity:

    def test_installed_version_from_detector(self):
        _, entity = _make_entity(UPGRADE_AVAILABLE)
        assert entity.installed_version == "1.0.0"

    def test_installed_version_fallback_when_no_status(self):
        _, entity = _make_entity(None, fallback="api-v1")
        assert entity.installed_version == "api-v1"

    def test_installed_version_fallback_when_detector_has_no_current(self):
        _, entity = _make_entity({"upgrade_available": False}, fallback="api-v1")
        assert entity.installed_version == "api-v1"

    def test_latest_version_when_available(self):
        _, entity = _make_entity(UPGRADE_AVAILABLE)
        assert entity.latest_version == "1.1.0"

    def test_latest_version_mirrors_installed_when_up_to_date(self):
        _, entity = _make_entity(
            {"current": "1.0.0", "latest": "2.0.0", "upgrade_available": False}
        )
        assert entity.latest_version == "1.0.0"

    def test_latest_version_unknown_when_available_without_target(self):
        """An available upgrade with no named target must not mirror installed."""
        _, entity = _make_entity({"current": "1.0.0", "upgrade_available": True})
        assert entity.latest_version is None

    def test_in_progress(self):
        assert _make_entity(UPGRADE_RUNNING)[1].in_progress is True
        assert _make_entity(UPGRADE_AVAILABLE)[1].in_progress is False

    def test_update_percentage(self):
        _, entity = _make_entity(UPGRADE_RUNNING)
        assert entity.update_percentage == 42

    def test_update_percentage_none_when_idle(self):
        _, entity = _make_entity(
            {**UPGRADE_AVAILABLE, "run": {"state": "idle", "percent": 42}}
        )
        assert entity.update_percentage is None

    def test_supported_features_install_when_can_upgrade(self):
        _, entity = _make_entity(UPGRADE_AVAILABLE)
        assert entity.supported_features & UpdateEntityFeature.INSTALL
        assert entity.supported_features & UpdateEntityFeature.PROGRESS

    def test_supported_features_no_install_when_cannot_upgrade(self):
        _, entity = _make_entity({**UPGRADE_AVAILABLE, "can_upgrade": False})
        assert not entity.supported_features & UpdateEntityFeature.INSTALL
        assert entity.supported_features & UpdateEntityFeature.PROGRESS

    def test_supported_features_no_install_without_status(self):
        _, entity = _make_entity(None)
        assert not entity.supported_features & UpdateEntityFeature.INSTALL

    def test_unique_id(self):
        assert _make_entity()[1].unique_id == f"{ENTRY_ID}_firmware_update"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in _make_entity()[1].device_info["identifiers"]

    def test_change_source_is_upgrade_namespace(self):
        hub, entity = _make_entity()
        assert entity._change_sources() == (hub.upgrade.on_change,)


# ---------------------------------------------------------------------------
# OdioUpdateEntity — actions
# ---------------------------------------------------------------------------

class TestOdioUpdateEntityInstall:

    @pytest.mark.asyncio
    async def test_install_calls_api(self):
        hub, entity = _make_entity(UPGRADE_AVAILABLE)
        await entity.async_install(version=None, backup=False)
        hub.client.upgrade_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_install_conflict_raises_homeassistant_error(self):
        """A 409 (already running) surfaces as HomeAssistantError."""
        hub, entity = _make_entity(UPGRADE_AVAILABLE)
        hub.client.upgrade_start.side_effect = OdioApiError(409, "already running")
        with pytest.raises(HomeAssistantError, match="already running"):
            await entity.async_install(version=None, backup=False)


# ---------------------------------------------------------------------------
# End-to-end SSE semantics through the entity (parsing lives in pyodio)
# ---------------------------------------------------------------------------

class TestUpgradeSseSemantics:

    def test_progress_event_updates_percentage(self):
        hub, entity = _make_entity(UPGRADE_RUNNING)
        push_event(hub, "upgrade.progress", {"event": "progress", "percent": 60})
        assert entity.update_percentage == 60

    def test_progress_end_does_not_complete(self):
        """The script's end precedes the systemd result, which owns completion."""
        hub, entity = _make_entity(UPGRADE_RUNNING)
        push_event(hub, "upgrade.progress", {"event": "end", "success": True})
        assert entity.in_progress is True
        assert entity.update_percentage == 100

    def test_lifecycle_finished_completes(self):
        """The authoritative lifecycle verdict flips the entity to idle."""
        hub, entity = _make_entity(UPGRADE_RUNNING)
        push_event(hub, "upgrade.progress", {"event": "end", "success": True})
        push_event(hub, "upgrade.info", {"state": "idle", "origin": "systemd",
                                         "finished_at": "2026-07-11T09:05:00Z"})
        assert entity.in_progress is False
        assert entity.update_percentage is None

    def test_lifecycle_finished_success_reports_up_to_date(self):
        """Terminal 'idle' after a running run means the install succeeded."""
        hub, entity = _make_entity(UPGRADE_RUNNING)
        push_event(hub, "upgrade.info", {"state": "idle", "origin": "systemd",
                                         "finished_at": "2026-07-11T09:05:00Z"})
        assert entity.installed_version == "1.1.0"
        assert entity.latest_version == entity.installed_version

    def test_lifecycle_finished_failure_keeps_update_available(self):
        hub, entity = _make_entity(UPGRADE_RUNNING)
        push_event(hub, "upgrade.info", {"state": "failed", "origin": "systemd",
                                         "finished_at": "2026-07-11T09:05:00Z"})
        assert entity.in_progress is False
        assert entity.installed_version == "1.0.0"
        assert entity.latest_version == "1.1.0"

    def test_detector_info_event_updates_versions(self):
        hub, entity = _make_entity(
            {"current": "1.0.0", "upgrade_available": False, "run": {"state": "idle"}}
        )
        push_event(
            hub,
            "upgrade.info",
            {
                "current": "1.0.0",
                "latest": "2.0.0",
                "upgrade_available": True,
                "can_upgrade": True,
            },
        )
        assert entity.latest_version == "2.0.0"
        assert entity.supported_features & UpdateEntityFeature.INSTALL


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

def _make_entry(hub):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data.hub = hub
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.server_info = hub.server
    return entry


class TestUpdateSetup:

    @pytest.mark.asyncio
    async def test_no_entity_when_backend_disabled(self):
        entry = _make_entry(make_hub(server_info=MOCK_SERVER_INFO))
        added = []
        await async_setup_entry(None, entry, lambda e: added.extend(e))
        assert added == []

    @pytest.mark.asyncio
    async def test_entity_created_when_backend_enabled(self):
        entry = _make_entry(
            make_hub(server_info=UPGRADE_SERVER_INFO, upgrade=UPGRADE_AVAILABLE)
        )
        added = []
        await async_setup_entry(None, entry, lambda e: added.extend(e))
        assert len(added) == 1
        assert isinstance(added[0], OdioUpdateEntity)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
