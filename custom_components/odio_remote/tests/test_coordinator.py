"""Tests for Odio Remote coordinators."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from homeassistant.helpers.update_coordinator import UpdateFailed

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


def _make_event_stream(is_api_reachable=True):
    stream = MagicMock()
    stream.is_api_reachable = is_api_reachable
    return stream


def _make_audio_coordinator(api, event_stream=None, scan_interval=5):
    return OdioAudioCoordinator(
        _make_hass(),
        MagicMock(),
        api,
        scan_interval,
        event_stream or _make_event_stream(),
    )


def _make_service_coordinator(api, event_stream=None, scan_interval=60):
    return OdioServiceCoordinator(
        _make_hass(),
        MagicMock(),
        api,
        scan_interval,
        event_stream or _make_event_stream(),
    )


# ---------------------------------------------------------------------------
# OdioAudioCoordinator
# ---------------------------------------------------------------------------

class TestOdioAudioCoordinator:

    @pytest.mark.asyncio
    async def test_skips_update_when_connectivity_down(self):
        """No API call is made when the event stream reports API unreachable."""
        api = MagicMock()
        api.get_clients = AsyncMock()
        coord = _make_audio_coordinator(api, _make_event_stream(is_api_reachable=False))

        with pytest.raises(UpdateFailed, match="unreachable"):
            await coord._async_update_data()

        api.get_clients.assert_not_awaited()

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

    @pytest.mark.asyncio
    async def test_failure_count_increments_on_error(self):
        """_failure_count increases with each connection failure."""
        api = MagicMock()
        api.get_clients = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
        )
        coord = _make_audio_coordinator(api)
        assert coord._failure_count == 0

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert coord._failure_count == 1

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert coord._failure_count == 2

    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(self):
        """_failure_count resets to 0 after a successful fetch."""
        api = MagicMock()
        api.get_clients = AsyncMock(
            side_effect=[
                aiohttp.ClientConnectorError(MagicMock(), OSError()),
                MOCK_CLIENTS,
            ]
        )
        coord = _make_audio_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert coord._failure_count == 1

        await coord._async_update_data()
        assert coord._failure_count == 0


# ---------------------------------------------------------------------------
# OdioServiceCoordinator
# ---------------------------------------------------------------------------

class TestOdioServiceCoordinator:

    @pytest.mark.asyncio
    async def test_skips_update_when_connectivity_down(self):
        """No API call is made when the event stream reports API unreachable."""
        api = MagicMock()
        api.get_services = AsyncMock()
        coord = _make_service_coordinator(api, _make_event_stream(is_api_reachable=False))

        with pytest.raises(UpdateFailed, match="unreachable"):
            await coord._async_update_data()

        api.get_services.assert_not_awaited()

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

    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(self):
        """_failure_count resets to 0 after a successful fetch."""
        api = MagicMock()
        api.get_services = AsyncMock(
            side_effect=[
                aiohttp.ClientConnectorError(MagicMock(), OSError()),
                MOCK_SERVICES,
            ]
        )
        coord = _make_service_coordinator(api)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert coord._failure_count == 1

        await coord._async_update_data()
        assert coord._failure_count == 0
