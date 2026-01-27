# custom_components/odio_audio/api_client.py

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)


class OdioApiClient:
    """Client for Odio Audio API."""

    def __init__(self, api_url: str, session: aiohttp.ClientSession):
        """Initialize the API client."""
        self._api_url = api_url
        self._session = session

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """Make HTTP request to API."""
        url = f"{self._api_url}{endpoint}"
        _LOGGER.debug("%s request to %s", method.upper(), url)

        try:
            async with asyncio.timeout(timeout):
                async with self._session.request(
                    method, url, json=json_data
                ) as response:
                    response.raise_for_status()

                    # Handle empty responses
                    if response.status == 204 or not response.content_length:
                        return None

                    return await response.json()

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout on %s %s", method, url)
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("Error on %s %s: %s", method, url, err)
            raise

    async def get(self, endpoint: str, timeout: int = 10) -> Any:
        """Make GET request."""
        return await self._request("GET", endpoint, timeout=timeout)

    async def post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> Any:
        """Make POST request."""
        return await self._request("POST", endpoint, json_data=data, timeout=timeout)

    # Server endpoints
    async def get_server_info(self) -> dict[str, Any]:
        """Get server information."""
        from .const import ENDPOINT_SERVER
        result = await self.get(ENDPOINT_SERVER)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from server endpoint, got {type(result)}")
        return result

    async def get_clients(self) -> list[dict[str, Any]]:
        """Get audio clients."""
        from .const import ENDPOINT_CLIENTS
        result = await self.get(ENDPOINT_CLIENTS)
        if not isinstance(result, list):
            raise ValueError(f"Expected list from clients endpoint, got {type(result)}")
        return result

    async def get_services(self) -> list[dict[str, Any]]:
        """Get systemd services."""
        from .const import ENDPOINT_SERVICES
        result = await self.get(ENDPOINT_SERVICES, timeout=15)
        if not isinstance(result, list):
            raise ValueError(f"Expected list from services endpoint, got {type(result)}")
        return result

    # Volume control
    async def set_server_volume(self, volume: float) -> None:
        """Set server volume."""
        from .const import ENDPOINT_SERVER_VOLUME
        await self.post(ENDPOINT_SERVER_VOLUME, {"volume": volume})

    async def set_server_mute(self, muted: bool) -> None:
        """Set server mute state."""
        from .const import ENDPOINT_SERVER_MUTE
        await self.post(ENDPOINT_SERVER_MUTE, {"muted": muted})

    async def set_client_volume(self, client_name: str, volume: float) -> None:
        """Set client volume."""
        from .const import ENDPOINT_CLIENT_VOLUME
        encoded_name = quote(client_name, safe='')
        endpoint = ENDPOINT_CLIENT_VOLUME.format(name=encoded_name)
        await self.post(endpoint, {"volume": volume})

    async def set_client_mute(self, client_name: str, muted: bool) -> None:
        """Set client mute state."""
        from .const import ENDPOINT_CLIENT_MUTE
        encoded_name = quote(client_name, safe='')
        endpoint = ENDPOINT_CLIENT_MUTE.format(name=encoded_name)
        await self.post(endpoint, {"muted": muted})

    # Service control
    async def control_service(
        self,
        action: str,
        scope: str,
        unit: str,
    ) -> None:
        """Control systemd service (enable/disable/restart)."""
        from .const import (
            ENDPOINT_SERVICE_ENABLE,
            ENDPOINT_SERVICE_DISABLE,
            ENDPOINT_SERVICE_RESTART,
        )

        endpoint_map = {
            "enable": ENDPOINT_SERVICE_ENABLE,
            "disable": ENDPOINT_SERVICE_DISABLE,
            "restart": ENDPOINT_SERVICE_RESTART,
        }

        endpoint_template = endpoint_map.get(action)
        if not endpoint_template:
            raise ValueError(f"Unknown service action: {action}")

        endpoint = endpoint_template.format(scope=scope, unit=unit)
        await self.post(endpoint)
