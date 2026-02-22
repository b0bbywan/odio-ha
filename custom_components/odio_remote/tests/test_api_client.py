"""Tests for OdioApiClient using aioresponses."""
import asyncio

import aiohttp
import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses
from unittest.mock import MagicMock

from custom_components.odio_remote.api_client import OdioApiClient

from .conftest import (
    MOCK_SERVER_INFO,
    MOCK_AUDIO_SERVER_INFO,
    MOCK_CLIENTS,
    MOCK_ALL_SERVICES,
)


class TestOdioApiClient:
    """Tests for OdioApiClient HTTP methods."""

    @pytest.mark.asyncio
    async def test_get_success(self):
        """Test successful GET request."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/test", payload={"test": "data"})

                result = await api.get("/test")

                assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_get_empty_response(self):
        """Test GET request with empty response (204)."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/test", status=204)

                result = await api.get("/test")

                assert result is None

    @pytest.mark.asyncio
    async def test_post_success(self):
        """Test successful POST request."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post("http://test:8018/test", payload={"result": "ok"})

                result = await api.post("/test", {"key": "value"})

                assert result == {"result": "ok"}


class TestOdioApiClientErrors:
    """Tests for _request error handling branches."""

    @pytest.mark.asyncio
    async def test_request_timeout(self):
        """Test that TimeoutError is logged and re-raised."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/server", exception=asyncio.TimeoutError())

                with pytest.raises(asyncio.TimeoutError):
                    await api.get("/server")

    @pytest.mark.asyncio
    async def test_request_connector_error(self):
        """Test that ClientConnectorError is logged and re-raised."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get(
                    "http://test:8018/server",
                    exception=aiohttp.ClientConnectorError(MagicMock(), OSError()),
                )

                with pytest.raises(aiohttp.ClientConnectorError):
                    await api.get("/server")

    @pytest.mark.asyncio
    async def test_request_http_error(self):
        """Test that ClientResponseError (e.g. 500) is logged and re-raised."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/server", status=500)

                with pytest.raises(aiohttp.ClientResponseError):
                    await api.get("/server")


class TestOdioApiClientEndpoints:
    """Tests for specific API endpoints."""

    @pytest.mark.asyncio
    async def test_get_server_info(self):
        """Test get_server_info returns real-shaped response."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/server", payload=MOCK_SERVER_INFO)

                result = await api.get_server_info()

                assert result["hostname"] == "htpc"
                assert result["api_version"] == "v0.6.0-rc.1-main"
                assert result["backends"]["pulseaudio"] is True
                assert result["backends"]["zeroconf"] is True
                assert result["api_sw"] == "odio-api"

    @pytest.mark.asyncio
    async def test_get_server_info_invalid_response(self):
        """Test get_server_info with invalid response type."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/server", payload=["not", "a", "dict"])

                with pytest.raises(ValueError, match="Expected dict"):
                    await api.get_server_info()

    @pytest.mark.asyncio
    async def test_get_audio_server_info(self):
        """Test get_audio_server_info returns real-shaped PipeWire response."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/audio/server", payload=MOCK_AUDIO_SERVER_INFO)

                result = await api.get_audio_server_info()

                assert result["kind"] == "pipewire"
                assert result["name"] == "PulseAudio (on PipeWire 1.4.2)"
                assert result["hostname"] == "htpc"
                assert result["volume"] == pytest.approx(1.0000153)

    @pytest.mark.asyncio
    async def test_get_audio_server_info_invalid_response(self):
        """Test get_audio_server_info with invalid response type."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/audio/server", payload=["not", "a", "dict"])

                with pytest.raises(ValueError, match="Expected dict"):
                    await api.get_audio_server_info()

    @pytest.mark.asyncio
    async def test_get_clients(self):
        """Test get_clients returns real-shaped client list."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/audio/clients", payload=MOCK_CLIENTS)

                result = await api.get_clients()

                assert len(result) == 1
                assert result[0]["name"] == "Netflix"
                assert result[0]["backend"] == "pipewire"
                assert result[0]["host"] == "htpc"
                assert result[0]["corked"] is True

    @pytest.mark.asyncio
    async def test_get_clients_empty(self):
        """Test get_clients with empty response."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/audio/clients", body="")

                result = await api.get_clients()

                assert result == []

    @pytest.mark.asyncio
    async def test_get_clients_invalid_response(self):
        """Test get_clients with invalid response type."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/audio/clients", payload={"not": "a list"})

                with pytest.raises(ValueError, match="Expected list"):
                    await api.get_clients()

    @pytest.mark.asyncio
    async def test_get_services(self):
        """Test get_services returns real-shaped service list."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/services", payload=MOCK_ALL_SERVICES)

                result = await api.get_services()

                assert len(result) == 6
                assert result[0]["name"] == "bluetooth.service"
                assert result[0]["scope"] == "system"
                assert result[1]["name"] == "firefox-kiosk@netflix.com.service"
                assert result[1]["running"] is True
                assert result[5]["name"] == "pipewire-pulse.service"
                assert result[5]["description"] == "PipeWire PulseAudio"

    @pytest.mark.asyncio
    async def test_get_services_empty(self):
        """Test get_services with 204 (no content) response."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/services", status=204)

                result = await api.get_services()

                assert result == []

    @pytest.mark.asyncio
    async def test_get_services_invalid_response(self):
        """Test get_services with invalid response type."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.get("http://test:8018/services", payload={"not": "a list"})

                with pytest.raises(ValueError, match="Expected list"):
                    await api.get_services()


class TestOdioApiClientVolumeControl:
    """Tests for volume control methods."""

    @pytest.mark.asyncio
    async def test_set_server_volume(self):
        """Test set_server_volume sends correct body."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post("http://test:8018/audio/server/volume", status=204)

                await api.set_server_volume(0.75)

                request = list(m.requests.values())[0][0]
                assert request.kwargs["json"] == {"volume": 0.75}

    @pytest.mark.asyncio
    async def test_set_server_mute(self):
        """Test set_server_mute sends correct body."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post("http://test:8018/audio/server/mute", status=204)

                await api.set_server_mute(True)

                request = list(m.requests.values())[0][0]
                assert request.kwargs["json"] == {"muted": True}

    @pytest.mark.asyncio
    async def test_set_client_volume(self):
        """Test set_client_volume URL-encodes name and sends correct body."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post("http://test:8018/audio/clients/Netflix/volume", status=204)

                await api.set_client_volume("Netflix", 1.0)

                request = list(m.requests.values())[0][0]
                assert request.kwargs["json"] == {"volume": 1.0}

    @pytest.mark.asyncio
    async def test_set_client_volume_special_chars(self):
        """Test set_client_volume with special characters in name."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post(
                    "http://test:8018/audio/clients/Client%2FWith%40Special%23Chars/volume",
                    status=204,
                )

                await api.set_client_volume("Client/With@Special#Chars", 0.8)

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_set_client_mute(self):
        """Test set_client_mute URL-encodes name and sends correct body."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post("http://test:8018/audio/clients/Netflix/mute", status=204)

                await api.set_client_mute("Netflix", False)

                request = list(m.requests.values())[0][0]
                assert request.kwargs["json"] == {"muted": False}


class TestOdioApiClientServiceControl:
    """Tests for service control methods."""

    @pytest.mark.asyncio
    async def test_control_service_enable(self):
        """Test control_service enable."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post(
                    "http://test:8018/services/user/pipewire-pulse.service/enable",
                    status=204,
                )

                await api.control_service("enable", "user", "pipewire-pulse.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_disable(self):
        """Test control_service disable."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post(
                    "http://test:8018/services/system/bluetooth.service/disable",
                    status=204,
                )

                await api.control_service("disable", "system", "bluetooth.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_restart(self):
        """Test control_service restart."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with aioresponses() as m:
                m.post(
                    "http://test:8018/services/user/kodi.service/restart",
                    status=204,
                )

                await api.control_service("restart", "user", "kodi.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_invalid_action(self):
        """Test control_service with invalid action raises ValueError."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with pytest.raises(ValueError, match="Unknown service action"):
                await api.control_service("invalid_action", "user", "kodi.service")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
