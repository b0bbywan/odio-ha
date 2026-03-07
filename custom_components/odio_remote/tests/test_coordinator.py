"""Tests for Odio Remote coordinators."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.odio_remote.api_client import SseEvent
from custom_components.odio_remote.coordinator import (
    OdioAudioCoordinator,
    OdioBluetoothCoordinator,
    OdioServiceCoordinator,
)
from custom_components.odio_remote.exceptions import OdioConnectionError, OdioTimeoutError

from .conftest import MOCK_BLUETOOTH_STATUS, MOCK_CLIENTS, MOCK_OUTPUTS, MOCK_SERVICES


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


def _make_audio_coordinator(api):
    return OdioAudioCoordinator(_make_hass(), MagicMock(), api)


def _make_service_coordinator(api):
    return OdioServiceCoordinator(_make_hass(), MagicMock(), api)


def _make_bluetooth_coordinator(api):
    return OdioBluetoothCoordinator(_make_hass(), MagicMock(), api)


# ---------------------------------------------------------------------------
# OdioAudioCoordinator
# ---------------------------------------------------------------------------

class TestOdioAudioCoordinator:

    @pytest.mark.asyncio
    async def test_fetches_data_when_connectivity_up(self):
        """Returns client + output data when the API is reachable."""
        api = MagicMock()
        api.get_audio_data = AsyncMock(
            return_value={"clients": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        )
        coord = _make_audio_coordinator(api)

        result = await coord._async_update_data()

        assert result == {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        api.get_audio_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        """OdioConnectionError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_audio_data = AsyncMock(
            side_effect=OdioConnectionError("connection failed")
        )
        coord = _make_audio_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """OdioTimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_audio_data = AsyncMock(side_effect=OdioTimeoutError("timeout"))
        coord = _make_audio_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# OdioServiceCoordinator
# ---------------------------------------------------------------------------


class TestOdioServiceCoordinator:

    @pytest.mark.asyncio
    async def test_fetches_data_when_connectivity_up(self):
        """Returns service data when the API is reachable."""
        api = MagicMock()
        api.get_services = AsyncMock(return_value=MOCK_SERVICES)
        coord = _make_service_coordinator(api)

        result = await coord._async_update_data()

        assert result == {"services": MOCK_SERVICES}
        api.get_services.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        """OdioConnectionError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_services = AsyncMock(
            side_effect=OdioConnectionError("connection failed")
        )
        coord = _make_service_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """OdioTimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_services = AsyncMock(side_effect=OdioTimeoutError("timeout"))
        coord = _make_service_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# OdioAudioCoordinator.handle_sse_event
# ---------------------------------------------------------------------------


class TestAudioCoordinatorHandleSseEvent:

    def _make_coord_with_data(self, clients):
        coord = _make_audio_coordinator(MagicMock())
        coord.data = {"audio": clients}
        coord.async_set_updated_data = MagicMock()
        return coord

    def test_updates_existing_client_by_name(self):
        """Changed client is replaced in-place by name."""
        existing = {"id": 1, "name": "Spotify", "volume": 0.5}
        coord = self._make_coord_with_data([existing])

        updated = {"id": 1, "name": "Spotify", "volume": 0.8}
        coord.handle_sse_event(SseEvent(type="audio.updated", data=[updated]))

        coord.async_set_updated_data.assert_called_once_with({"audio": [updated]})

    def test_appends_new_client(self):
        """Unknown client name is appended to the list."""
        existing = {"id": 1, "name": "Spotify", "volume": 0.5}
        coord = self._make_coord_with_data([existing])

        new_client = {"id": 2, "name": "VLC", "volume": 1.0}
        coord.handle_sse_event(SseEvent(type="audio.updated", data=[new_client]))

        coord.async_set_updated_data.assert_called_once_with({"audio": [existing, new_client]})

    def test_unchanged_clients_preserved(self):
        """Clients not in the event are kept as-is."""
        a = {"id": 1, "name": "Spotify", "volume": 0.5}
        b = {"id": 2, "name": "VLC", "volume": 1.0}
        coord = self._make_coord_with_data([a, b])

        updated_b = {"id": 2, "name": "VLC", "volume": 0.7}
        coord.handle_sse_event(SseEvent(type="audio.updated", data=[updated_b]))

        coord.async_set_updated_data.assert_called_once_with({"audio": [a, updated_b]})

    def test_empty_event_preserves_existing(self):
        """Empty event data leaves current list untouched."""
        existing = [{"id": 1, "name": "Spotify", "volume": 0.5}]
        coord = self._make_coord_with_data(existing)

        coord.handle_sse_event(SseEvent(type="audio.updated", data=[]))

        coord.async_set_updated_data.assert_called_once_with({"audio": existing})

    def test_works_with_no_existing_data(self):
        """handle_sse_event handles coordinator.data being None."""
        coord = _make_audio_coordinator(MagicMock())
        coord.data = None
        coord.async_set_updated_data = MagicMock()

        client = {"id": 1, "name": "Spotify", "volume": 0.5}
        coord.handle_sse_event(SseEvent(type="audio.updated", data=[client]))

        coord.async_set_updated_data.assert_called_once_with({"audio": [client]})

    def test_non_list_data_ignored(self):
        """handle_sse_event does nothing when event data is not a list."""
        coord = _make_audio_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_event(SseEvent(type="audio.updated", data={"not": "a list"}))

        coord.async_set_updated_data.assert_not_called()


# ---------------------------------------------------------------------------
# OdioAudioCoordinator.handle_sse_remove_event
# ---------------------------------------------------------------------------


class TestAudioCoordinatorHandleSseRemoveEvent:

    def _make_coord_with_data(self, clients):
        coord = _make_audio_coordinator(MagicMock())
        coord.data = {"audio": clients}
        coord.async_set_updated_data = MagicMock()
        return coord

    def test_marks_removed_client_as_corked(self):
        """Removed client stays in list with corked=True → Idle state."""
        a = {"id": 1, "name": "Spotify", "volume": 0.5, "corked": False}
        b = {"id": 2, "name": "VLC", "volume": 1.0, "corked": False}
        coord = self._make_coord_with_data([a, b])

        coord.handle_sse_remove_event(SseEvent(type="audio.removed", data=[a]))

        result = coord.async_set_updated_data.call_args[0][0]["audio"]
        assert len(result) == 2
        assert result[0]["name"] == "Spotify"
        assert result[0]["corked"] is True
        assert result[1] == b

    def test_unknown_name_ignored(self):
        """Removing an unknown client does not alter the existing list."""
        existing = [{"id": 1, "name": "Spotify", "volume": 0.5, "corked": False}]
        coord = self._make_coord_with_data(existing)

        coord.handle_sse_remove_event(
            SseEvent(type="audio.removed", data=[{"id": 99, "name": "Ghost"}])
        )

        coord.async_set_updated_data.assert_called_once_with({"audio": existing})

    def test_non_list_data_ignored(self):
        """handle_sse_remove_event does nothing when event data is not a list."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_remove_event(SseEvent(type="audio.removed", data={"not": "a list"}))

        coord.async_set_updated_data.assert_not_called()

    def test_works_with_no_existing_data(self):
        """handle_sse_remove_event handles coordinator.data being None."""
        coord = _make_audio_coordinator(MagicMock())
        coord.data = None
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_remove_event(
            SseEvent(type="audio.removed", data=[{"id": 1, "name": "Spotify"}])
        )

        coord.async_set_updated_data.assert_called_once_with({"audio": []})


# ---------------------------------------------------------------------------
# OdioServiceCoordinator.handle_sse_event
# ---------------------------------------------------------------------------

class TestServiceCoordinatorHandleSseEvent:

    def _make_coord_with_data(self, services):
        coord = _make_service_coordinator(MagicMock())
        coord.data = {"services": services}
        coord.async_set_updated_data = MagicMock()
        return coord

    def test_replaces_existing_service(self):
        """handle_sse_event replaces a service matched by name+scope."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        updated = {"name": "mpd.service", "scope": "user", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=updated))

        coord.async_set_updated_data.assert_called_once_with({"services": [updated]})

    def test_appends_unknown_service(self):
        """handle_sse_event appends a service not in the current list."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        new_svc = {"name": "snapclient.service", "scope": "user", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=new_svc))

        coord.async_set_updated_data.assert_called_once_with(
            {"services": [existing, new_svc]}
        )

    def test_non_dict_data_ignored(self):
        """handle_sse_event does nothing when event data is not a dict."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data=["not", "a", "dict"]))

        coord.async_set_updated_data.assert_not_called()

    def test_missing_name_ignored(self):
        """handle_sse_event does nothing when event data has no 'name' key."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data={"scope": "user"}))

        coord.async_set_updated_data.assert_not_called()

    def test_missing_scope_ignored(self):
        """handle_sse_event does nothing when event data has no 'scope' key."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data={"name": "mpd.service"}))

        coord.async_set_updated_data.assert_not_called()

    def test_scope_must_match_for_replace(self):
        """A service with same name but different scope is appended, not replaced."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        system_svc = {"name": "mpd.service", "scope": "system", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=system_svc))

        coord.async_set_updated_data.assert_called_once_with(
            {"services": [existing, system_svc]}
        )

    def test_works_with_no_existing_data(self):
        """handle_sse_event handles coordinator.data being None."""
        coord = _make_service_coordinator(MagicMock())
        coord.data = None
        coord.async_set_updated_data = MagicMock()

        svc = {"name": "mpd.service", "scope": "user", "running": True}
        coord.handle_sse_event(SseEvent(type="service.updated", data=svc))

        coord.async_set_updated_data.assert_called_once_with({"services": [svc]})


# ---------------------------------------------------------------------------
# OdioBluetoothCoordinator
# ---------------------------------------------------------------------------


class TestOdioBluetoothCoordinator:

    @pytest.mark.asyncio
    async def test_fetches_status(self):
        """Returns raw bluetooth status dict from API."""
        api = MagicMock()
        api.get_bluetooth_status = AsyncMock(return_value=MOCK_BLUETOOTH_STATUS)
        coord = _make_bluetooth_coordinator(api)

        result = await coord._async_update_data()

        assert result == MOCK_BLUETOOTH_STATUS
        api.get_bluetooth_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        """OdioConnectionError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_bluetooth_status = AsyncMock(
            side_effect=OdioConnectionError("connection failed")
        )
        coord = _make_bluetooth_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """OdioTimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_bluetooth_status = AsyncMock(side_effect=OdioTimeoutError("timeout"))
        coord = _make_bluetooth_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# OdioBluetoothCoordinator.handle_sse_event
# ---------------------------------------------------------------------------


class TestBluetoothCoordinatorHandleSseEvent:

    def test_valid_dict_updates_data(self):
        """handle_sse_event sets coordinator data when event data is a dict."""
        coord = _make_bluetooth_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_event(SseEvent(type="bluetooth.updated", data=MOCK_BLUETOOTH_STATUS))

        coord.async_set_updated_data.assert_called_once_with(MOCK_BLUETOOTH_STATUS)

    def test_non_dict_data_ignored(self):
        """handle_sse_event does nothing when event data is not a dict."""
        coord = _make_bluetooth_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_event(SseEvent(type="bluetooth.updated", data=["not", "a", "dict"]))

        coord.async_set_updated_data.assert_not_called()

    def test_powered_off_updates_data(self):
        """handle_sse_event handles powered=False state."""
        coord = _make_bluetooth_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        data = {"powered": False, "discoverable": False, "pairable": False,
                "pairing_active": False, "known_devices": []}
        coord.handle_sse_event(SseEvent(type="bluetooth.updated", data=data))

        coord.async_set_updated_data.assert_called_once_with(data)

    def test_pairing_active_updates_data(self):
        """handle_sse_event handles pairing_active=True state."""
        coord = _make_bluetooth_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        data = {**MOCK_BLUETOOTH_STATUS, "pairing_active": True}
        coord.handle_sse_event(SseEvent(type="bluetooth.updated", data=data))

        coord.async_set_updated_data.assert_called_once_with(data)
