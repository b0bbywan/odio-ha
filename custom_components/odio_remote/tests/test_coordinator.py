"""Tests for Odio Remote coordinators."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.odio_remote.coordinator import (
    OdioAudioCoordinator,
    OdioConnectivityCoordinator,
    OdioServiceCoordinator,
)

from .conftest import MOCK_CLIENTS, MOCK_SERVER_INFO, MOCK_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.loop = asyncio.get_event_loop()
    return hass


def _make_connectivity(last_update_success=True):
    coord = MagicMock(spec=OdioConnectivityCoordinator)
    coord.last_update_success = last_update_success
    return coord


def _make_audio_coordinator(api, connectivity=None, scan_interval=5):
    return OdioAudioCoordinator(
        _make_hass(),
        MagicMock(),
        api,
        scan_interval,
        connectivity or _make_connectivity(),
    )


def _make_service_coordinator(api, connectivity=None, scan_interval=60):
    return OdioServiceCoordinator(
        _make_hass(),
        MagicMock(),
        api,
        scan_interval,
        connectivity or _make_connectivity(),
    )


def _make_connectivity_coordinator(api):
    return OdioConnectivityCoordinator(
        _make_hass(),
        MagicMock(),
        api,
        30,
    )


# ---------------------------------------------------------------------------
# OdioAudioCoordinator
# ---------------------------------------------------------------------------

class TestOdioAudioCoordinator:

    @pytest.mark.asyncio
    async def test_skips_update_when_connectivity_down(self):
        """No API call is made when the connectivity coordinator reports failure."""
        api = MagicMock()
        api.get_clients = AsyncMock()
        connectivity = _make_connectivity(last_update_success=False)
        coord = _make_audio_coordinator(api, connectivity)

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
        """No API call is made when the connectivity coordinator reports failure."""
        api = MagicMock()
        api.get_services = AsyncMock()
        connectivity = _make_connectivity(last_update_success=False)
        coord = _make_service_coordinator(api, connectivity)

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


# ---------------------------------------------------------------------------
# OdioConnectivityCoordinator
# ---------------------------------------------------------------------------

class TestOdioConnectivityCoordinator:

    @pytest.mark.asyncio
    async def test_returns_server_info_on_success(self):
        """Returns server info dict when the API responds."""
        api = MagicMock()
        api.get_server_info = AsyncMock(return_value=MOCK_SERVER_INFO)
        coord = _make_connectivity_coordinator(api)

        result = await coord._async_update_data()

        assert result == MOCK_SERVER_INFO

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_connection_error(self):
        """ClientConnectorError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_server_info = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError())
        )
        coord = _make_connectivity_coordinator(api)

        with pytest.raises(UpdateFailed, match="Cannot reach"):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_raises_update_failed_on_timeout(self):
        """TimeoutError is wrapped in UpdateFailed."""
        api = MagicMock()
        api.get_server_info = AsyncMock(side_effect=asyncio.TimeoutError())
        coord = _make_connectivity_coordinator(api)

        with pytest.raises(UpdateFailed, match="Cannot reach"):
            await coord._async_update_data()
