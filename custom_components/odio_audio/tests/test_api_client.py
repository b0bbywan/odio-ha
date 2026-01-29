"""Tests for OdioApiClient using aioresponses."""
import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses


class TestOdioApiClient:
    """Tests for OdioApiClient HTTP methods."""

    @pytest.mark.asyncio
    async def test_get_success(self):
        """Test successful GET request."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get("http://test:8080/test", payload={"test": "data"})

                result = await api.get("/test")

                assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_get_empty_response(self):
        """Test GET request with empty response (204)."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get("http://test:8080/test", status=204)

                result = await api.get("/test")

                assert result is None

    @pytest.mark.asyncio
    async def test_post_success(self):
        """Test successful POST request."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/test", payload={"result": "ok"})

                result = await api.post("/test", {"key": "value"})

                assert result == {"result": "ok"}


class TestOdioApiClientEndpoints:
    """Tests for specific API endpoints."""

    @pytest.mark.asyncio
    async def test_get_server_info(self):
        """Test get_server_info endpoint."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get(
                    "http://test:8080/audio/server",
                    payload={
                        "name": "pulseaudio",
                        "hostname": "test-server",
                        "version": "15.0"
                    }
                )

                result = await api.get_server_info()

                assert result["name"] == "pulseaudio"
                assert result["hostname"] == "test-server"

    @pytest.mark.asyncio
    async def test_get_server_info_invalid_response(self):
        """Test get_server_info with invalid response type."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get("http://test:8080/audio/server", payload=["not", "a", "dict"])

                with pytest.raises(ValueError, match="Expected dict"):
                    await api.get_server_info()

    @pytest.mark.asyncio
    async def test_get_clients(self):
        """Test get_clients endpoint."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get(
                    "http://test:8080/audio/clients",
                    payload=[
                        {"id": 1, "name": "Client 1"},
                        {"id": 2, "name": "Client 2"}
                    ]
                )

                result = await api.get_clients()

                assert len(result) == 2
                assert result[0]["name"] == "Client 1"

    @pytest.mark.asyncio
    async def test_get_clients_empty(self):
        """Test get_clients with empty response."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                # Empty response (no body)
                m.get("http://test:8080/audio/clients", body="")

                result = await api.get_clients()

                assert result == []

    @pytest.mark.asyncio
    async def test_get_clients_invalid_response(self):
        """Test get_clients with invalid response type."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get("http://test:8080/audio/clients", payload={"not": "a list"})

                with pytest.raises(ValueError, match="Expected list"):
                    await api.get_clients()

    @pytest.mark.asyncio
    async def test_get_services(self):
        """Test get_services endpoint."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.get(
                    "http://test:8080/services",
                    payload=[
                        {"name": "mpd.service", "scope": "user", "enabled": True},
                        {"name": "snapclient.service", "scope": "user", "enabled": False}
                    ]
                )

                result = await api.get_services()

                assert len(result) == 2
                assert result[0]["name"] == "mpd.service"


class TestOdioApiClientVolumeControl:
    """Tests for volume control methods."""

    @pytest.mark.asyncio
    async def test_set_server_volume(self):
        """Test set_server_volume."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/audio/server/volume")

                await api.set_server_volume(0.75)

                # Verify request was made
                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_set_server_mute(self):
        """Test set_server_mute."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/audio/server/mute")

                await api.set_server_mute(True)

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_set_client_volume(self):
        """Test set_client_volume with URL encoding."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                # Match URL-encoded client name
                m.post("http://test:8080/audio/clients/Test%20Client/volume")

                await api.set_client_volume("Test Client", 0.5)

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_set_client_mute(self):
        """Test set_client_mute."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/audio/clients/Test%20Client/mute")

                await api.set_client_mute("Test Client", False)

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_set_client_volume_special_chars(self):
        """Test set_client_volume with special characters in name."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                # Match URL-encoded special chars
                m.post("http://test:8080/audio/clients/Client%2FWith%40Special%23Chars/volume")

                await api.set_client_volume("Client/With@Special#Chars", 0.8)

                assert len(m.requests) == 1


class TestOdioApiClientServiceControl:
    """Tests for service control methods."""

    @pytest.mark.asyncio
    async def test_control_service_enable(self):
        """Test control_service enable."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/services/user/mpd.service/enable")

                await api.control_service("enable", "user", "mpd.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_disable(self):
        """Test control_service disable."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/services/system/upmpdcli.service/disable")

                await api.control_service("disable", "system", "upmpdcli.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_restart(self):
        """Test control_service restart."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with aioresponses() as m:
                m.post("http://test:8080/services/user/snapclient.service/restart")

                await api.control_service("restart", "user", "snapclient.service")

                assert len(m.requests) == 1

    @pytest.mark.asyncio
    async def test_control_service_invalid_action(self):
        """Test control_service with invalid action."""
        from custom_components.odio_audio.api_client import OdioApiClient

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8080", session)

            with pytest.raises(ValueError, match="Unknown service action"):
                await api.control_service("invalid_action", "user", "mpd.service")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
