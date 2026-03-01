"""SSE event stream manager for the Odio Remote integration."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp

from .api_client import OdioApiClient, SseEvent
from .const import (
    SSE_EVENT_AUDIO_UPDATED,
    SSE_EVENT_SERVER_INFO,
    SSE_EVENT_SERVICE_UPDATED,
    SSE_KEEPALIVE_TIMEOUT,
    SSE_RECONNECT_MAX_INTERVAL,
    SSE_RECONNECT_MIN_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import OdioAudioCoordinator, OdioServiceCoordinator

_LOGGER = logging.getLogger(__name__)


class OdioEventStreamManager:
    """Manage an SSE connection and route events to coordinators.

    Handles reconnection with exponential backoff and keepalive timeout
    detection. Events are dispatched to the appropriate coordinator:
      - audio.updated  → audio_coordinator.async_set_updated_data()
      - service.updated → merged into service_coordinator data
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: OdioApiClient,
        audio_coordinator: OdioAudioCoordinator | None,
        service_coordinator: OdioServiceCoordinator | None,
    ) -> None:
        """Initialize the event stream manager."""
        self._hass = hass
        self._api = api
        self._audio_coordinator = audio_coordinator
        self._service_coordinator = service_coordinator
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def connected(self) -> bool:
        """Return True if the SSE stream task is running."""
        return self._task is not None and not self._task.done()

    @property
    def is_api_reachable(self) -> bool:
        """Return True if the API is believed to be reachable.

        Returns True during startup (before the stream is started) so that
        coordinators can perform their initial fetch unconditionally.
        Once the stream has started, reflects the live connection state.
        """
        if self._task is None:
            return True
        return self.connected

    def start(self) -> None:
        """Start the event stream in a background task."""
        if self._task is not None and not self._task.done():
            _LOGGER.debug("Event stream already running")
            return
        self._stop_event.clear()
        self._task = self._hass.async_create_background_task(
            self._run_loop(),
            name="odio_remote_event_stream",
        )
        _LOGGER.info("Event stream started")

    async def stop(self) -> None:
        """Stop the event stream."""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        _LOGGER.info("Event stream stopped")

    async def _run_loop(self) -> None:
        """Run the SSE event loop with reconnection logic."""
        backoff = SSE_RECONNECT_MIN_INTERVAL

        while not self._stop_event.is_set():
            try:
                await self._consume_stream()
                # Stream ended cleanly (e.g. server sent "bye") — reconnect quickly
                backoff = SSE_RECONNECT_MIN_INTERVAL
                _LOGGER.info("SSE stream ended cleanly, reconnecting in %ds", backoff)
            except asyncio.CancelledError:
                _LOGGER.debug("Event stream cancelled")
                return
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "SSE keepalive timeout, reconnecting in %ds", backoff
                )
            except aiohttp.ClientError as err:
                _LOGGER.warning(
                    "SSE connection error: %s, reconnecting in %ds", err, backoff
                )
            except Exception:
                _LOGGER.exception(
                    "Unexpected SSE error, reconnecting in %ds", backoff
                )

            # Wait before reconnecting (interruptible by stop)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=backoff
                )
                # stop_event was set — exit
                return
            except asyncio.TimeoutError:
                # Backoff elapsed — reconnect
                pass

            backoff = min(backoff * 2, SSE_RECONNECT_MAX_INTERVAL)

    async def _consume_stream(self) -> None:
        """Open one SSE connection and process events until it ends."""
        backends = self._get_backends()
        if not backends:
            _LOGGER.debug("No backends to subscribe to, skipping SSE")
            # Wait until stopped to avoid busy-looping
            await self._stop_event.wait()
            return

        async for event in self._api.listen_events(
            backends=backends,
            exclude=["player.position"],
            keepalive_timeout=SSE_KEEPALIVE_TIMEOUT,
        ):
            if event.type == SSE_EVENT_SERVER_INFO:
                self._handle_server_info(event)
                continue

            if event.type == SSE_EVENT_AUDIO_UPDATED:
                self._handle_audio_updated(event)
            elif event.type == SSE_EVENT_SERVICE_UPDATED:
                self._handle_service_updated(event)
            else:
                _LOGGER.debug("Ignoring unhandled SSE event: %s", event.type)

        _LOGGER.debug("SSE stream ended (at_eof)")

    def _get_backends(self) -> list[str]:
        """Build the list of backends to subscribe to."""
        backends: list[str] = []
        if self._audio_coordinator is not None:
            backends.append("audio")
        if self._service_coordinator is not None:
            backends.append("systemd")
        return backends

    def _handle_server_info(self, event: SseEvent) -> None:
        """Handle server.info control events (connected, love, bye)."""
        if event.data == "connected":
            _LOGGER.info("SSE stream connected")
        elif event.data == "love":
            _LOGGER.debug("SSE keepalive received")
        elif event.data == "bye":
            _LOGGER.info("SSE server sent bye")
        else:
            _LOGGER.debug("SSE server.info: %s", event.data)

    def _handle_audio_updated(self, event: SseEvent) -> None:
        """Handle audio.updated: full client list replacement."""
        if self._audio_coordinator is None:
            return
        if not isinstance(event.data, list):
            _LOGGER.warning(
                "audio.updated: expected list, got %s", type(event.data).__name__
            )
            return
        _LOGGER.debug("SSE audio.updated: %d clients", len(event.data))
        self._audio_coordinator.async_set_updated_data({"audio": event.data})

    def _handle_service_updated(self, event: SseEvent) -> None:
        """Handle service.updated: merge single service into existing list."""
        if self._service_coordinator is None:
            return
        if not isinstance(event.data, dict):
            _LOGGER.warning(
                "service.updated: expected dict, got %s",
                type(event.data).__name__,
            )
            return

        svc_name = event.data.get("name")
        svc_scope = event.data.get("scope")
        if not svc_name or not svc_scope:
            _LOGGER.warning(
                "service.updated: missing name or scope in %s", event.data
            )
            return

        # Merge into existing services list
        current = self._service_coordinator.data or {"services": []}
        services = list(current.get("services", []))

        replaced = False
        for i, svc in enumerate(services):
            if svc.get("name") == svc_name and svc.get("scope") == svc_scope:
                services[i] = event.data
                replaced = True
                break
        if not replaced:
            services.append(event.data)

        _LOGGER.debug(
            "SSE service.updated: %s/%s (replaced=%s)", svc_scope, svc_name, replaced
        )
        self._service_coordinator.async_set_updated_data({"services": services})
