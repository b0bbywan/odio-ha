"""SSE event stream manager for the Odio Remote integration."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

import aiohttp

from .api_client import OdioApiClient, SseEvent
from .const import (
    SSE_EVENT_SERVER_INFO,
    SSE_KEEPALIVE_TIMEOUT,
    SSE_RECONNECT_MAX_INTERVAL,
    SSE_RECONNECT_MIN_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class OdioEventStreamManager:
    """Manage an SSE connection and dispatch events to registered listeners.

    Handles reconnection with exponential backoff and keepalive timeout
    detection. Events are dispatched to listeners registered via
    async_add_event_listener(). The manager has no knowledge of coordinators
    or any other HA-specific consumer.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: OdioApiClient,
        backends: list[str],
    ) -> None:
        """Initialize the event stream manager."""
        self._hass = hass
        self._api = api
        self._backends = backends
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._sse_connected = False
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: dict[str, list[Callable[[SseEvent], None]]] = {}

    @property
    def connected(self) -> bool:
        """Return True if the SSE stream task is running."""
        return self._task is not None and not self._task.done()

    @property
    def sse_connected(self) -> bool:
        """Return True if the SSE connection is currently established."""
        return self._sse_connected

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

    def async_add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a connectivity state listener. Returns an unsubscribe function."""
        self._listeners.append(callback)

        def remove() -> None:
            self._listeners.remove(callback)
        return remove

    def async_add_event_listener(
        self,
        event_type: str,
        callback: Callable[[SseEvent], None],
    ) -> Callable[[], None]:
        """Register a listener for a specific SSE event type.

        Returns an unsubscribe function.
        """
        self._event_listeners.setdefault(event_type, []).append(callback)

        def remove() -> None:
            self._event_listeners[event_type].remove(callback)
        return remove

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

    def _set_sse_connected(self, value: bool) -> None:
        if self._sse_connected != value:
            self._sse_connected = value
            for callback in self._listeners:
                callback()

    def _dispatch_event(self, event: SseEvent) -> None:
        for callback in self._event_listeners.get(event.type, []):
            callback(event)

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

            self._set_sse_connected(False)
            # Wait before reconnecting (interruptible by stop)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=backoff
                )
                return
            except asyncio.TimeoutError:
                pass

            backoff = min(backoff * 2, SSE_RECONNECT_MAX_INTERVAL)

    async def _consume_stream(self) -> None:
        """Open one SSE connection and process events until it ends."""
        if not self._backends:
            _LOGGER.debug("No backends to subscribe to, skipping SSE")
            await self._stop_event.wait()
            return

        async for event in self._api.listen_events(
            backends=self._backends,
            exclude=["player.position"],
            keepalive_timeout=SSE_KEEPALIVE_TIMEOUT,
        ):
            if event.type == SSE_EVENT_SERVER_INFO:
                self._handle_server_info(event)
            else:
                self._dispatch_event(event)

        _LOGGER.debug("SSE stream ended (at_eof)")

    def _handle_server_info(self, event: SseEvent) -> None:
        """Handle server.info control events (connected, love, bye)."""
        if event.data == "connected":
            _LOGGER.info("SSE stream connected")
            self._set_sse_connected(True)
        elif event.data == "love":
            _LOGGER.debug("SSE keepalive received")
        elif event.data == "bye":
            _LOGGER.info("SSE server sent bye")
        else:
            _LOGGER.debug("SSE server.info: %s", event.data)
