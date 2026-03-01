"""Tests for Odio Remote coordinators."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.odio_remote.api_client import SseEvent
from custom_components.odio_remote.coordinator import (
    OdioAudioCoordinator,
    OdioServiceCoordinator,
)

from .conftest import MOCK_CLIENTS, MOCK_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.loop = asyncio.get_event_loop()
    return hass


def _make_audio_coordinator(api):
    return OdioAudioCoordinator(_make_hass(), MagicMock(), api)


def _make_service_coordinator(api):
    return OdioServiceCoordinator(_make_hass(), MagicMock(), api)


# ---------------------------------------------------------------------------
# OdioAudioCoordinator
# ---------------------------------------------------------------------------

class TestOdioAudioCoordinator:

    @pytest.mark.asyncio
    async def test_fetches_data_when_connectivity_up(self):
        """Returns client data when the API is reachable."""
        api = MagicMock()
        api.get_clients = AsyncMock(return_value=MOCK_CLIENTS)
        coord = _make_audio_coordinator(api)

        result = await coord._async_update_data()

        assert result == {"audio": MOCK_CLIENTS}
        api.get_clients.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        """ClientConnectorError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_clients = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
        )
        coord = _make_audio_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """TimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_clients = AsyncMock(side_effect=asyncio.TimeoutError())
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
        """ClientConnectorError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_services = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
        )
        coord = _make_service_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """TimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_services = AsyncMock(side_effect=asyncio.TimeoutError())
        coord = _make_service_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# OdioAudioCoordinator.handle_sse_event
# ---------------------------------------------------------------------------


class TestAudioCoordinatorHandleSseEvent:

    @pytest.mark.asyncio
    async def test_valid_list_updates_data(self):
        """handle_sse_event sets coordinator data when event data is a list."""
        coord = _make_audio_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        event = SseEvent(type="audio.updated", data=[{"id": 1}])
        coord.handle_sse_event(event)

        coord.async_set_updated_data.assert_called_once_with({"audio": [{"id": 1}]})

    @pytest.mark.asyncio
    async def test_non_list_data_ignored(self):
        """handle_sse_event does nothing when event data is not a list."""
        coord = _make_audio_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_event(SseEvent(type="audio.updated", data={"not": "a list"}))

        coord.async_set_updated_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_list_updates_data(self):
        """handle_sse_event accepts an empty list."""
        coord = _make_audio_coordinator(MagicMock())
        coord.async_set_updated_data = MagicMock()

        coord.handle_sse_event(SseEvent(type="audio.updated", data=[]))

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

    @pytest.mark.asyncio
    async def test_replaces_existing_service(self):
        """handle_sse_event replaces a service matched by name+scope."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        updated = {"name": "mpd.service", "scope": "user", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=updated))

        coord.async_set_updated_data.assert_called_once_with({"services": [updated]})

    @pytest.mark.asyncio
    async def test_appends_unknown_service(self):
        """handle_sse_event appends a service not in the current list."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        new_svc = {"name": "snapclient.service", "scope": "user", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=new_svc))

        coord.async_set_updated_data.assert_called_once_with(
            {"services": [existing, new_svc]}
        )

    @pytest.mark.asyncio
    async def test_non_dict_data_ignored(self):
        """handle_sse_event does nothing when event data is not a dict."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data=["not", "a", "dict"]))

        coord.async_set_updated_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_name_ignored(self):
        """handle_sse_event does nothing when event data has no 'name' key."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data={"scope": "user"}))

        coord.async_set_updated_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_scope_ignored(self):
        """handle_sse_event does nothing when event data has no 'scope' key."""
        coord = self._make_coord_with_data([])

        coord.handle_sse_event(SseEvent(type="service.updated", data={"name": "mpd.service"}))

        coord.async_set_updated_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_must_match_for_replace(self):
        """A service with same name but different scope is appended, not replaced."""
        existing = {"name": "mpd.service", "scope": "user", "running": True}
        coord = self._make_coord_with_data([existing])

        system_svc = {"name": "mpd.service", "scope": "system", "running": False}
        coord.handle_sse_event(SseEvent(type="service.updated", data=system_svc))

        coord.async_set_updated_data.assert_called_once_with(
            {"services": [existing, system_svc]}
        )

    @pytest.mark.asyncio
    async def test_works_with_no_existing_data(self):
        """handle_sse_event handles coordinator.data being None."""
        coord = _make_service_coordinator(MagicMock())
        coord.data = None
        coord.async_set_updated_data = MagicMock()

        svc = {"name": "mpd.service", "scope": "user", "running": True}
        coord.handle_sse_event(SseEvent(type="service.updated", data=svc))

        coord.async_set_updated_data.assert_called_once_with({"services": [svc]})
