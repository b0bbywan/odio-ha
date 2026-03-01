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


class TestEventStreamManagerHandlers:
    """Tests for OdioEventStreamManager event routing."""

    def test_handle_audio_updated(self):
        """Test audio.updated replaces coordinator data."""
        audio_coord = MagicMock()
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=audio_coord,
            service_coordinator=None,
        )

        clients = [{"id": 1, "name": "Spotify", "volume": 0.75}]
        event = SseEvent(type="audio.updated", data=clients)
        manager._handle_audio_updated(event)

        audio_coord.async_set_updated_data.assert_called_once_with(
            {"audio": clients}
        )

    def test_handle_audio_updated_no_coordinator(self):
        """Test audio.updated is a no-op when audio_coordinator is None."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=None,
        )

        event = SseEvent(type="audio.updated", data=[{"id": 1}])
        # Should not raise
        manager._handle_audio_updated(event)

    def test_handle_audio_updated_invalid_data(self):
        """Test audio.updated with non-list data is ignored."""
        audio_coord = MagicMock()
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=audio_coord,
            service_coordinator=None,
        )

        event = SseEvent(type="audio.updated", data={"not": "a list"})
        manager._handle_audio_updated(event)

        audio_coord.async_set_updated_data.assert_not_called()

    def test_handle_service_updated_replace(self):
        """Test service.updated replaces matching service in list."""
        service_coord = MagicMock()
        service_coord.data = {
            "services": [
                {"name": "mpd.service", "scope": "user", "running": True},
                {"name": "snapclient.service", "scope": "user", "running": False},
            ]
        }
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        updated = {"name": "mpd.service", "scope": "user", "running": False}
        event = SseEvent(type="service.updated", data=updated)
        manager._handle_service_updated(event)

        call_args = service_coord.async_set_updated_data.call_args[0][0]
        services = call_args["services"]
        assert len(services) == 2
        assert services[0] == updated
        assert services[1]["name"] == "snapclient.service"

    def test_handle_service_updated_append(self):
        """Test service.updated appends new service to list."""
        service_coord = MagicMock()
        service_coord.data = {
            "services": [
                {"name": "mpd.service", "scope": "user", "running": True},
            ]
        }
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        new_svc = {"name": "kodi.service", "scope": "user", "running": True}
        event = SseEvent(type="service.updated", data=new_svc)
        manager._handle_service_updated(event)

        call_args = service_coord.async_set_updated_data.call_args[0][0]
        services = call_args["services"]
        assert len(services) == 2
        assert services[1] == new_svc

    def test_handle_service_updated_no_coordinator(self):
        """Test service.updated is a no-op when service_coordinator is None."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=None,
        )

        event = SseEvent(type="service.updated", data={"name": "mpd.service", "scope": "user"})
        # Should not raise
        manager._handle_service_updated(event)

    def test_handle_service_updated_invalid_data(self):
        """Test service.updated with non-dict data is ignored."""
        service_coord = MagicMock()
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        event = SseEvent(type="service.updated", data=["not", "a", "dict"])
        manager._handle_service_updated(event)

        service_coord.async_set_updated_data.assert_not_called()

    def test_handle_service_updated_missing_key(self):
        """Test service.updated with missing name or scope is ignored."""
        service_coord = MagicMock()
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        event = SseEvent(type="service.updated", data={"name": "mpd.service"})
        manager._handle_service_updated(event)

        service_coord.async_set_updated_data.assert_not_called()

    def test_handle_service_updated_empty_coordinator_data(self):
        """Test service.updated when coordinator has no prior data."""
        service_coord = MagicMock()
        service_coord.data = None
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        svc = {"name": "mpd.service", "scope": "user", "running": True}
        event = SseEvent(type="service.updated", data=svc)
        manager._handle_service_updated(event)

        call_args = service_coord.async_set_updated_data.call_args[0][0]
        assert call_args == {"services": [svc]}

    def test_get_backends_both(self):
        """Test _get_backends returns both when both coordinators exist."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=MagicMock(),
            service_coordinator=MagicMock(),
        )
        assert manager._get_backends() == ["audio", "systemd"]

    def test_get_backends_audio_only(self):
        """Test _get_backends returns audio only."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=MagicMock(),
            service_coordinator=None,
        )
        assert manager._get_backends() == ["audio"]

    def test_get_backends_none(self):
        """Test _get_backends returns empty list when no coordinators."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=None,
        )
        assert manager._get_backends() == []

    def test_handle_service_updated_scope_matters(self):
        """Test that name+scope together identify the service."""
        service_coord = MagicMock()
        service_coord.data = {
            "services": [
                {"name": "bluetooth.service", "scope": "system", "running": True},
                {"name": "bluetooth.service", "scope": "user", "running": False},
            ]
        }
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=service_coord,
        )

        # Update the user-scoped bluetooth only
        updated = {"name": "bluetooth.service", "scope": "user", "running": True}
        event = SseEvent(type="service.updated", data=updated)
        manager._handle_service_updated(event)

        call_args = service_coord.async_set_updated_data.call_args[0][0]
        services = call_args["services"]
        assert len(services) == 2
        # system scope unchanged
        assert services[0] == {"name": "bluetooth.service", "scope": "system", "running": True}
        # user scope updated
        assert services[1] == updated


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
        manager = OdioEventStreamManager(
            hass=hass,
            api=MagicMock(),
            audio_coordinator=MagicMock(),
            service_coordinator=None,
        )

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
        manager = OdioEventStreamManager(
            hass=hass,
            api=MagicMock(),
            audio_coordinator=MagicMock(),
            service_coordinator=None,
        )

        manager.start()
        manager.start()

        assert hass.async_create_background_task.call_count == 1

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Test that stop sets the task to None."""
        hass = MagicMock()

        async def _forever():
            await asyncio.sleep(3600)

        real_task = asyncio.create_task(_forever())

        def _fake_create_task(coro, **kwargs):
            coro.close()
            return real_task

        hass.async_create_background_task = MagicMock(side_effect=_fake_create_task)

        manager = OdioEventStreamManager(
            hass=hass,
            api=MagicMock(),
            audio_coordinator=MagicMock(),
            service_coordinator=None,
        )
        manager.start()
        assert manager.connected

        await manager.stop()

        assert real_task.cancelled()
        assert not manager.connected

    def test_connected_false_when_no_task(self):
        """Test connected is False before start."""
        manager = OdioEventStreamManager(
            hass=MagicMock(),
            api=MagicMock(),
            audio_coordinator=None,
            service_coordinator=None,
        )
        assert not manager.connected


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
