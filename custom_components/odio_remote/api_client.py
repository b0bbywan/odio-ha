# custom_components/odio_remote/api_client.py

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class SseEvent:
    """A parsed Server-Sent Event."""

    type: str
    data: Any  # JSON-decoded payload


class OdioApiClient:
    """Client for Odio Remote API."""

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

                    # Handle empty responses (204 No Content, 202 Accepted with no body, etc.)
                    if response.content_length == 0 or response.status in (202, 204):
                        return None

                    return await response.json()

        except asyncio.TimeoutError:
            # Timeout is expected when device is slow or unreachable - log as warning
            _LOGGER.warning("Timeout connecting to %s", url)
            raise
        except aiohttp.ClientConnectorError as err:
            # Connection errors are expected when device is offline - log as warning
            _LOGGER.warning("Unable to connect to %s: %s", url, err)
            raise
        except aiohttp.ClientError as err:
            # Other client errors (e.g., HTTP errors) are unexpected - log as error
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
        """Get system-wide server info (hostname, backends, api_version, etc.)."""
        from .const import ENDPOINT_SYSTEM_SERVER
        result = await self.get(ENDPOINT_SYSTEM_SERVER)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from server endpoint, got {type(result)}")
        return result

    async def get_audio_server_info(self) -> dict[str, Any]:
        """Get PulseAudio/PipeWire server info (requires pulseaudio backend)."""
        from .const import ENDPOINT_SERVER
        result = await self.get(ENDPOINT_SERVER)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from audio server endpoint, got {type(result)}")
        return result

    async def get_clients(self) -> list[dict[str, Any]]:
        """Get audio clients.

        Tries unified GET /audio first, falls back to GET /audio/clients on 404.
        TODO: Remove fallback when /audio/clients is dropped from go-odio-api.
        """
        from .const import ENDPOINT_AUDIO

        try:
            result = await self.get(ENDPOINT_AUDIO)
        except aiohttp.ClientResponseError as err:
            if err.status == 404:
                _LOGGER.debug("GET /audio returned 404 — falling back to /audio/clients")
                return await self._get_clients_legacy()
            raise

        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from /audio endpoint, got {type(result)}")
        clients = result.get("clients")
        if clients is None:
            return []
        if not isinstance(clients, list):
            raise ValueError(f"Expected list for 'clients' key, got {type(clients)}")
        return clients

    async def _get_clients_legacy(self) -> list[dict[str, Any]]:
        """Fetch clients from old GET /audio/clients endpoint.

        TODO: Remove this method when /audio/clients is dropped from go-odio-api.
        """
        from .const import ENDPOINT_CLIENTS

        result = await self.get(ENDPOINT_CLIENTS)
        if result is None:
            return []
        if not isinstance(result, list):
            raise ValueError(f"Expected list from clients endpoint, got {type(result)}")
        return result

    async def get_services(self) -> list[dict[str, Any]]:
        """Get systemd services."""
        from .const import ENDPOINT_SERVICES
        result = await self.get(ENDPOINT_SERVICES, timeout=15)
        if result is None:
            return []
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

    # Power control
    async def get_power_capabilities(self) -> dict[str, bool]:
        """Get power capabilities (reboot/power_off flags)."""
        from .const import ENDPOINT_POWER
        result = await self.get(ENDPOINT_POWER)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from power endpoint, got {type(result)}")
        return result

    async def power_off(self) -> None:
        """Trigger power off."""
        from .const import ENDPOINT_POWER_OFF
        await self.post(ENDPOINT_POWER_OFF)

    async def reboot(self) -> None:
        """Trigger reboot."""
        from .const import ENDPOINT_POWER_REBOOT
        await self.post(ENDPOINT_POWER_REBOOT)

    # Bluetooth control
    async def get_bluetooth_status(self) -> dict[str, Any]:
        """Get Bluetooth adapter and device status."""
        from .const import ENDPOINT_BLUETOOTH
        result = await self.get(ENDPOINT_BLUETOOTH)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from bluetooth endpoint, got {type(result)}")
        return result

    async def bluetooth_power_up(self) -> None:
        """Power on Bluetooth adapter."""
        from .const import ENDPOINT_BLUETOOTH_POWER_UP
        await self.post(ENDPOINT_BLUETOOTH_POWER_UP)

    async def bluetooth_power_down(self) -> None:
        """Power off Bluetooth adapter."""
        from .const import ENDPOINT_BLUETOOTH_POWER_DOWN
        await self.post(ENDPOINT_BLUETOOTH_POWER_DOWN)

    async def bluetooth_pairing_mode(self) -> None:
        """Enable Bluetooth pairing mode (60s timeout server-side)."""
        from .const import ENDPOINT_BLUETOOTH_PAIRING_MODE
        await self.post(ENDPOINT_BLUETOOTH_PAIRING_MODE)

    # MPRIS Player control
    async def get_players(self) -> tuple[list[dict[str, Any]], str | None]:
        """Get MPRIS media players and cache timestamp from x-cache-updated-at header."""
        from .const import ENDPOINT_PLAYERS
        url = f"{self._api_url}{ENDPOINT_PLAYERS}"
        try:
            async with asyncio.timeout(10):
                async with self._session.get(url) as response:
                    response.raise_for_status()
                    result = await response.json()
                    if not isinstance(result, list):
                        raise ValueError(f"Expected list from players endpoint, got {type(result)}")
                    cache_ts = response.headers.get("x-cache-updated-at")
                    return result, cache_ts
        except aiohttp.ClientResponseError as err:
            if err.status == 404:
                _LOGGER.debug("Players endpoint not available (404) - server may not support MPRIS yet")
                return [], None
            raise

    async def player_play(self, player: str) -> None:
        """Send play command to MPRIS player."""
        from .const import ENDPOINT_PLAYER_PLAY
        endpoint = ENDPOINT_PLAYER_PLAY.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_pause(self, player: str) -> None:
        """Send pause command to MPRIS player."""
        from .const import ENDPOINT_PLAYER_PAUSE
        endpoint = ENDPOINT_PLAYER_PAUSE.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_play_pause(self, player: str) -> None:
        """Toggle play/pause on MPRIS player."""
        from .const import ENDPOINT_PLAYER_PLAY_PAUSE
        endpoint = ENDPOINT_PLAYER_PLAY_PAUSE.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_stop(self, player: str) -> None:
        """Send stop command to MPRIS player."""
        from .const import ENDPOINT_PLAYER_STOP
        endpoint = ENDPOINT_PLAYER_STOP.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_next(self, player: str) -> None:
        """Send next track command to MPRIS player."""
        from .const import ENDPOINT_PLAYER_NEXT
        endpoint = ENDPOINT_PLAYER_NEXT.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_previous(self, player: str) -> None:
        """Send previous track command to MPRIS player."""
        from .const import ENDPOINT_PLAYER_PREVIOUS
        endpoint = ENDPOINT_PLAYER_PREVIOUS.format(player=quote(player, safe=''))
        await self.post(endpoint)

    async def player_seek(self, player: str, offset: int) -> None:
        """Seek relative to current position (microseconds).

        Args:
            player: MPRIS player name
            offset: Offset in microseconds (can be negative)
        """
        from .const import ENDPOINT_PLAYER_SEEK
        endpoint = ENDPOINT_PLAYER_SEEK.format(player=quote(player, safe=''))
        await self.post(endpoint, {"offset": offset})

    async def player_set_position(
        self, player: str, track_id: str, position: int
    ) -> None:
        """Set absolute position in track (microseconds).

        Args:
            player: MPRIS player name
            track_id: Track ID from MPRIS metadata
            position: Position in microseconds
        """
        from .const import ENDPOINT_PLAYER_POSITION
        endpoint = ENDPOINT_PLAYER_POSITION.format(player=quote(player, safe=''))
        await self.post(endpoint, {"track_id": track_id, "position": position})

    async def player_set_volume(self, player: str, volume: float) -> None:
        """Set MPRIS player volume (0.0 to 1.0)."""
        from .const import ENDPOINT_PLAYER_VOLUME
        endpoint = ENDPOINT_PLAYER_VOLUME.format(player=quote(player, safe=''))
        await self.post(endpoint, {"volume": volume})

    async def player_set_loop(self, player: str, loop: str) -> None:
        """Set MPRIS loop status.

        Args:
            player: MPRIS player name
            loop: "None", "Track", or "Playlist"
        """
        from .const import ENDPOINT_PLAYER_LOOP
        endpoint = ENDPOINT_PLAYER_LOOP.format(player=quote(player, safe=''))
        await self.post(endpoint, {"loop": loop})

    async def player_set_shuffle(self, player: str, shuffle: bool) -> None:
        """Set MPRIS shuffle state."""
        from .const import ENDPOINT_PLAYER_SHUFFLE
        endpoint = ENDPOINT_PLAYER_SHUFFLE.format(player=quote(player, safe=''))
        await self.post(endpoint, {"shuffle": shuffle})

    # SSE event stream
    async def listen_events(
        self,
        backends: list[str] | None = None,
        exclude: list[str] | None = None,
        keepalive_interval: int | None = None,
        keepalive_timeout: float | None = None,
    ) -> AsyncGenerator[SseEvent]:
        """Open an SSE connection to /events and yield parsed events.

        This is a low-level generator that handles SSE wire-format parsing.
        It does NOT handle reconnection — the caller is responsible for that.

        Yields SseEvent instances for every received event including
        server.info control events (connected, love, bye).

        Raises on connection errors or when the stream ends.
        """
        from .const import ENDPOINT_EVENTS

        params: dict[str, str] = {}
        if backends:
            params["backend"] = ",".join(backends)
        if exclude:
            params["exclude"] = ",".join(exclude)
        if keepalive_interval is not None:
            params["keepalive"] = str(keepalive_interval)

        url = f"{self._api_url}{ENDPOINT_EVENTS}"
        _LOGGER.debug("Opening SSE connection to %s (params=%s)", url, params)

        async with self._session.get(
            url,
            params=params,
            headers={"Accept": "text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
        ) as response:
            response.raise_for_status()

            event_type = ""
            data_buf = ""

            while not response.content.at_eof():
                raw_line = await asyncio.wait_for(
                    response.content.readline(), timeout=keepalive_timeout
                )
                if not raw_line:
                    break
                line = raw_line.decode("utf-8").rstrip("\r\n")

                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_buf += line[len("data:"):].strip()
                elif line == "":
                    # Blank line marks end of an event
                    if event_type and data_buf:
                        try:
                            parsed_data = json.loads(data_buf)
                        except json.JSONDecodeError:
                            _LOGGER.warning(
                                "Failed to parse SSE data for event %s: %s",
                                event_type,
                                data_buf,
                            )
                            event_type = ""
                            data_buf = ""
                            continue
                        yield SseEvent(type=event_type, data=parsed_data)
                    event_type = ""
                    data_buf = ""

    # Service control
    async def control_service(
        self,
        action: str,
        scope: str,
        unit: str,
    ) -> None:
        """Control systemd service (enable/disable/restart/start/stop)."""
        from .const import (
            ENDPOINT_SERVICE_DISABLE,
            ENDPOINT_SERVICE_ENABLE,
            ENDPOINT_SERVICE_RESTART,
            ENDPOINT_SERVICE_START,
            ENDPOINT_SERVICE_STOP,
        )

        endpoint_map = {
            "enable": ENDPOINT_SERVICE_ENABLE,
            "disable": ENDPOINT_SERVICE_DISABLE,
            "restart": ENDPOINT_SERVICE_RESTART,
            "start": ENDPOINT_SERVICE_START,
            "stop": ENDPOINT_SERVICE_STOP,
        }

        endpoint_template = endpoint_map.get(action)
        if not endpoint_template:
            raise ValueError(f"Unknown service action: {action}")

        endpoint = endpoint_template.format(scope=scope, unit=unit)
        await self.post(endpoint)
