"""Tests for OdioEventStreamManager."""
import asyncio
import json

import pytest
from aiohttp import ClientSession
from unittest.mock import MagicMock, patch

from custom_components.odio_remote.api_client import OdioApiClient, SseEvent
from custom_components.odio_remote.event_stream import OdioEventStreamManager


def _make_sse_bytes(*events: tuple[str, object]) -> bytes:
    """Build raw SSE byte stream from (event_type, data) tuples."""
    lines = []
    for event_type, data in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")  # blank line terminates the event
    return "\n".join(lines).encode("utf-8") + b"\n"


def _make_manager(backends=None, hass=None):
    """Create an OdioEventStreamManager with sensible defaults."""
    return OdioEventStreamManager(
        hass=hass or MagicMock(),
        api=MagicMock(),
        backends=backends or [],
    )


class TestListenEvents:
    """Tests for OdioApiClient.listen_events() SSE parser."""

    @pytest.mark.asyncio
    async def test_parse_single_event(self):
        """Test parsing a single SSE event."""
        raw = _make_sse_bytes(("audio.updated", [{"id": 1, "name": "Spotify"}]))

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(raw),
            ):
                events = [e async for e in api.listen_events()]

        assert len(events) == 1
        assert events[0].type == "audio.updated"
        assert events[0].data == [{"id": 1, "name": "Spotify"}]

    @pytest.mark.asyncio
    async def test_parse_multiple_events(self):
        """Test parsing multiple consecutive SSE events."""
        raw = _make_sse_bytes(
            ("server.info", "connected"),
            ("audio.updated", [{"id": 1}]),
            ("service.updated", {"name": "mpd.service", "scope": "user"}),
            ("server.info", "love"),
        )

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(raw),
            ):
                events = [e async for e in api.listen_events()]

        assert len(events) == 4
        assert events[0].type == "server.info"
        assert events[0].data == "connected"
        assert events[1].type == "audio.updated"
        assert events[2].type == "service.updated"
        assert events[3].data == "love"

    @pytest.mark.asyncio
    async def test_parse_skips_invalid_json(self):
        """Test that events with invalid JSON data are skipped."""
        raw = (
            b"event: audio.updated\n"
            b"data: {not valid json\n"
            b"\n"
            b"event: server.info\n"
            b"data: \"love\"\n"
            b"\n"
        )

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(raw),
            ):
                events = [e async for e in api.listen_events()]

        assert len(events) == 1
        assert events[0].type == "server.info"

    @pytest.mark.asyncio
    async def test_backend_and_exclude_params(self):
        """Test that backend and exclude params are passed correctly."""
        raw = _make_sse_bytes(("server.info", "connected"))

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(raw),
            ) as mock_get:
                _ = [
                    e
                    async for e in api.listen_events(
                        backends=["audio", "systemd"],
                        exclude=["player.position"],
                    )
                ]

            call_kwargs = mock_get.call_args
            assert call_kwargs.kwargs["params"] == {
                "backend": "audio,systemd",
                "exclude": "player.position",
            }

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        """Test that an empty stream yields nothing."""
        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(b""),
            ):
                events = [e async for e in api.listen_events()]

        assert events == []

    @pytest.mark.asyncio
    async def test_event_without_data_ignored(self):
        """Test that an event type line followed by blank line (no data) is ignored."""
        raw = b"event: audio.updated\n\n"

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(
                session,
                "get",
                return_value=_mock_sse_response(raw),
            ):
                events = [e async for e in api.listen_events()]

        assert events == []

    @pytest.mark.asyncio
    async def test_keepalive_timeout_raises(self):
        """Test that a stalled stream raises TimeoutError after keepalive_timeout."""
        import asyncio

        class _StalledStreamReader:
            def at_eof(self):
                return False

            async def readline(self):
                await asyncio.sleep(3600)

        class _StalledResponse:
            content = _StalledStreamReader()
            status = 200

            def raise_for_status(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        async with ClientSession() as session:
            api = OdioApiClient("http://test:8018", session)

            with patch.object(session, "get", return_value=_StalledResponse()):
                with pytest.raises(asyncio.TimeoutError):
                    async for _ in api.listen_events(keepalive_timeout=0.05):
                        pass


class TestEventStreamManagerDispatch:
    """Tests for async_add_event_listener and event dispatch."""

    def test_dispatch_calls_registered_listener(self):
        """Registered listener is called when a matching event is dispatched."""
        manager = _make_manager()
        received = []
        manager.async_add_event_listener("audio.updated", received.append)

        event = SseEvent(type="audio.updated", data=[{"id": 1}])
        manager._dispatch_event(event)

        assert received == [event]

    def test_dispatch_ignores_unregistered_type(self):
        """No error when dispatching an event with no registered listener."""
        manager = _make_manager()
        received = []
        manager.async_add_event_listener("audio.updated", received.append)

        manager._dispatch_event(SseEvent(type="service.updated", data={}))

        assert received == []

    def test_unsubscribe_stops_delivery(self):
        """Calling the returned unsubscribe function stops event delivery."""
        manager = _make_manager()
        received = []
        unsub = manager.async_add_event_listener("audio.updated", received.append)

        unsub()
        manager._dispatch_event(SseEvent(type="audio.updated", data=[]))

        assert received == []

    def test_multiple_listeners_same_type(self):
        """Multiple listeners for the same event type are all called."""
        manager = _make_manager()
        a, b = [], []
        manager.async_add_event_listener("audio.updated", a.append)
        manager.async_add_event_listener("audio.updated", b.append)

        event = SseEvent(type="audio.updated", data=[])
        manager._dispatch_event(event)

        assert a == [event]
        assert b == [event]

    def test_dispatch_survives_callback_exception(self):
        """A callback that raises does not prevent other listeners from firing."""
        manager = _make_manager()
        received = []

        def bad_callback(event):
            raise RuntimeError("boom")

        manager.async_add_event_listener("audio.updated", bad_callback)
        manager.async_add_event_listener("audio.updated", received.append)

        event = SseEvent(type="audio.updated", data=[])
        manager._dispatch_event(event)

        assert received == [event]

    def test_unsubscribe_during_dispatch_safe(self):
        """Removing a listener during dispatch does not crash."""
        manager = _make_manager()
        received = []
        unsub = manager.async_add_event_listener("audio.updated", lambda e: unsub())
        manager.async_add_event_listener("audio.updated", received.append)

        event = SseEvent(type="audio.updated", data=[])
        manager._dispatch_event(event)

        assert received == [event]

    def test_connectivity_listener_survives_exception(self):
        """A connectivity listener that raises does not prevent others from firing."""
        manager = _make_manager()
        called = []

        def bad_listener():
            raise RuntimeError("boom")

        manager.async_add_listener(bad_listener)
        manager.async_add_listener(lambda: called.append(True))

        manager._set_sse_connected(True)

        assert called == [True]


class TestEventStreamManagerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_creates_task(self):
        """Test that start creates a background task."""
        hass = MagicMock()
        task = MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        def _fake_create_task(coro, **kwargs):
            coro.close()
            return task

        hass.async_create_background_task = MagicMock(side_effect=_fake_create_task)
        manager = _make_manager(backends=["audio"], hass=hass)

        manager.start()

        hass.async_create_background_task.assert_called_once()
        assert manager.connected

    def test_start_idempotent(self):
        """Test that calling start twice doesn't create a second task."""
        hass = MagicMock()
        task = MagicMock(spec=asyncio.Task)
        task.done.return_value = False

        def _fake_create_task(coro, **kwargs):
            coro.close()
            return task

        hass.async_create_background_task = MagicMock(side_effect=_fake_create_task)
        manager = _make_manager(backends=["audio"], hass=hass)

        manager.start()
        manager.start()

        assert hass.async_create_background_task.call_count == 1

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Test that stop cancels the task."""
        hass = MagicMock()

        async def _forever():
            await asyncio.sleep(3600)

        real_task = asyncio.create_task(_forever())

        def _fake_create_task(coro, **kwargs):
            coro.close()
            return real_task

        hass.async_create_background_task = MagicMock(side_effect=_fake_create_task)
        manager = _make_manager(backends=["audio"], hass=hass)

        manager.start()
        assert manager.connected

        await manager.stop()

        assert real_task.cancelled()
        assert not manager.connected

    def test_connected_false_when_no_task(self):
        """Test connected is False before start."""
        assert not _make_manager().connected


# ── Helpers ──────────────────────────────────────────────────────


class _MockStreamReader:
    """Mock aiohttp StreamReader that yields lines from raw bytes."""

    def __init__(self, raw: bytes) -> None:
        self._lines = raw.split(b"\n")
        self._index = 0

    def at_eof(self) -> bool:
        return self._index >= len(self._lines)

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index] + b"\n"
        self._index += 1
        return line


class _MockResponse:
    """Mock aiohttp response for SSE streams."""

    def __init__(self, raw: bytes) -> None:
        self.content = _MockStreamReader(raw)
        self.status = 200

    def raise_for_status(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _mock_sse_response(raw: bytes):
    """Create a mock context manager returning a mock SSE response."""
    return _MockResponse(raw)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
