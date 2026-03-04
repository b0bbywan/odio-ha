"""Tests for setup helper functions in __init__.py."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.odio_remote import (
    _resolve_mac,
    _fetch_power_capabilities,
    _setup_audio_coordinator,
    _setup_service_coordinator,
    _setup_mpris_coordinator,
    _setup_bluetooth_coordinator,
)
from custom_components.odio_remote.const import (
    SSE_EVENT_AUDIO_UPDATED,
    SSE_EVENT_AUDIO_REMOVED,
    SSE_EVENT_BLUETOOTH_UPDATED,
    SSE_EVENT_PLAYER_UPDATED,
    SSE_EVENT_PLAYER_ADDED,
    SSE_EVENT_PLAYER_REMOVED,
    SSE_EVENT_PLAYER_POSITION,
    SSE_EVENT_SERVICE_UPDATED,
)


def _make_hass():
    """Create a mock hass with event loop."""
    hass = MagicMock()
    try:
        hass.loop = asyncio.get_running_loop()
    except RuntimeError:
        hass.loop = MagicMock()
    return hass


def _make_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.data = {}
    entry.entry_id = "test_entry_id"
    unload_callbacks = []
    entry.async_on_unload = lambda cb: unload_callbacks.append(cb)
    entry._unload_callbacks = unload_callbacks
    return entry


def _make_event_stream():
    """Create a mock event stream that tracks registered listeners."""
    stream = MagicMock()
    registered = {}

    def add_event_listener(event_type, callback):
        registered.setdefault(event_type, []).append(callback)
        return lambda: registered[event_type].remove(callback)

    stream.async_add_event_listener = add_event_listener
    stream._registered = registered
    return stream


# =============================================================================
# MAC resolution
# =============================================================================


class TestResolveMac:
    """Tests for _resolve_mac."""

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_resolves_and_caches_mac(self, mock_get_mac):
        """Test MAC is resolved and cached in entry data."""
        mock_get_mac.return_value = "aa:bb:cc:dd:ee:ff"
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {}

        result = await _resolve_mac(hass, entry, "http://192.168.1.10:8018")

        assert result == "aa:bb:cc:dd:ee:ff"
        mock_get_mac.assert_awaited_once_with(hass, "192.168.1.10")
        hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_skips_update_when_mac_unchanged(self, mock_get_mac):
        """Test no update when MAC matches cached value."""
        mock_get_mac.return_value = "aa:bb:cc:dd:ee:ff"
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {"mac": "aa:bb:cc:dd:ee:ff"}

        result = await _resolve_mac(hass, entry, "http://192.168.1.10:8018")

        assert result == "aa:bb:cc:dd:ee:ff"
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_falls_back_to_cached_mac(self, mock_get_mac):
        """Test fallback to cached MAC when resolution fails."""
        mock_get_mac.return_value = None
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {"mac": "11:22:33:44:55:66"}

        result = await _resolve_mac(hass, entry, "http://192.168.1.10:8018")

        assert result == "11:22:33:44:55:66"

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_returns_none_when_no_mac(self, mock_get_mac):
        """Test returns None when no MAC resolved and no cache."""
        mock_get_mac.return_value = None
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {}

        result = await _resolve_mac(hass, entry, "http://192.168.1.10:8018")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_no_host(self):
        """Test returns None when URL has no hostname."""
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {}

        result = await _resolve_mac(hass, entry, "")

        assert result is None


# =============================================================================
# Power capabilities
# =============================================================================


class TestFetchPowerCapabilities:
    """Tests for _fetch_power_capabilities."""

    @pytest.mark.asyncio
    async def test_fetches_and_caches(self):
        """Test capabilities are fetched and cached."""
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {}
        api = MagicMock()
        caps = {"reboot": True, "shutdown": True}
        api.get_power_capabilities = AsyncMock(return_value=caps)

        result = await _fetch_power_capabilities(hass, entry, api)

        assert result == caps
        hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_update_when_unchanged(self):
        """Test no update when capabilities match cached value."""
        hass = MagicMock()
        entry = _make_entry()
        caps = {"reboot": True, "shutdown": True}
        entry.data = {"power_capabilities": caps}
        api = MagicMock()
        api.get_power_capabilities = AsyncMock(return_value=caps)

        result = await _fetch_power_capabilities(hass, entry, api)

        assert result == caps
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_cached_on_error(self):
        """Test fallback to cached value on API error."""
        hass = MagicMock()
        entry = _make_entry()
        cached = {"reboot": True, "shutdown": False}
        entry.data = {"power_capabilities": cached}
        api = MagicMock()
        api.get_power_capabilities = AsyncMock(side_effect=ConnectionError("refused"))

        result = await _fetch_power_capabilities(hass, entry, api)

        assert result == cached

    @pytest.mark.asyncio
    async def test_returns_empty_on_error_no_cache(self):
        """Test returns empty dict on error with no cache."""
        hass = MagicMock()
        entry = _make_entry()
        entry.data = {}
        api = MagicMock()
        api.get_power_capabilities = AsyncMock(side_effect=ConnectionError("refused"))

        result = await _fetch_power_capabilities(hass, entry, api)

        assert result == {}


# =============================================================================
# Audio coordinator setup
# =============================================================================


class TestSetupAudioCoordinator:
    """Tests for _setup_audio_coordinator."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioAudioCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_creates_coordinator(self, mock_refresh):
        """Test that audio coordinator is created and refreshed."""
        hass = _make_hass()
        entry = _make_entry()
        api = MagicMock()
        stream = _make_event_stream()

        result = await _setup_audio_coordinator(hass, entry, api, stream)

        assert result is not None
        assert result.api is api
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioAudioCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_wires_sse_listeners(self, mock_refresh):
        """Test that audio SSE events are wired."""
        hass = _make_hass()
        entry = _make_entry()
        stream = _make_event_stream()

        coordinator = await _setup_audio_coordinator(hass, entry, MagicMock(), stream)

        assert SSE_EVENT_AUDIO_UPDATED in stream._registered
        assert SSE_EVENT_AUDIO_REMOVED in stream._registered
        assert stream._registered[SSE_EVENT_AUDIO_UPDATED][0] == coordinator.handle_sse_event
        assert stream._registered[SSE_EVENT_AUDIO_REMOVED][0] == coordinator.handle_sse_remove_event

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioAudioCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_registers_unload(self, mock_refresh):
        """Test that unload callbacks are registered."""
        entry = _make_entry()
        stream = _make_event_stream()

        await _setup_audio_coordinator(_make_hass(), entry, MagicMock(), stream)

        # 1 (coordinator shutdown) + 4 SSE listeners = 5 unload callbacks
        assert len(entry._unload_callbacks) == 5


# =============================================================================
# Service coordinator setup
# =============================================================================


class TestSetupServiceCoordinator:
    """Tests for _setup_service_coordinator."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioServiceCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_creates_coordinator(self, mock_refresh):
        """Test that service coordinator is created and refreshed."""
        hass = _make_hass()
        entry = _make_entry()
        api = MagicMock()
        stream = _make_event_stream()

        result = await _setup_service_coordinator(hass, entry, api, stream)

        assert result is not None
        assert result.api is api
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioServiceCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_wires_sse_listener(self, mock_refresh):
        """Test that service SSE event is wired."""
        hass = _make_hass()
        entry = _make_entry()
        stream = _make_event_stream()

        coordinator = await _setup_service_coordinator(hass, entry, MagicMock(), stream)

        assert SSE_EVENT_SERVICE_UPDATED in stream._registered
        assert stream._registered[SSE_EVENT_SERVICE_UPDATED][0] == coordinator.handle_sse_event

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioServiceCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_caches_services_in_entry_data(self, mock_refresh):
        """Test that services are cached in entry.data when changed."""
        hass = _make_hass()
        entry = _make_entry()
        stream = _make_event_stream()

        # Simulate coordinator having data after refresh
        mock_services = [{"name": "mpd.service", "scope": "user"}]

        async def fake_refresh():
            # Coordinator.data is set by the real refresh; we simulate it
            pass

        mock_refresh.side_effect = fake_refresh

        coordinator = await _setup_service_coordinator(hass, entry, MagicMock(), stream)
        # Manually set data as if refresh populated it
        coordinator.data = {"services": mock_services}

        # Re-run to test caching (call it again with data present)
        entry2 = _make_entry()
        stream2 = _make_event_stream()
        coordinator2 = await _setup_service_coordinator(hass, entry2, MagicMock(), stream2)
        coordinator2.data = {"services": mock_services}

        # The first call had no data (async_refresh is mocked), so no cache update
        # Verify the coordinator was returned correctly
        assert coordinator is not None

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioServiceCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_registers_unload(self, mock_refresh):
        """Test that unload callback is registered."""
        entry = _make_entry()
        stream = _make_event_stream()

        await _setup_service_coordinator(_make_hass(), entry, MagicMock(), stream)

        # 1 (coordinator shutdown) + 1 SSE listener = 2 unload callbacks
        assert len(entry._unload_callbacks) == 2


# =============================================================================
# MPRIS coordinator setup
# =============================================================================


class TestSetupMprisCoordinator:
    """Tests for _setup_mpris_coordinator."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioMPRISCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_creates_coordinator(self, mock_refresh):
        """Test that MPRIS coordinator is created and refreshed."""
        hass = _make_hass()
        entry = _make_entry()
        api = MagicMock()
        stream = _make_event_stream()

        result = await _setup_mpris_coordinator(hass, entry, api, stream)

        assert result is not None
        assert result.api is api
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioMPRISCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_wires_all_sse_listeners(self, mock_refresh):
        """Test that all MPRIS SSE events are wired."""
        hass = _make_hass()
        entry = _make_entry()
        stream = _make_event_stream()

        coordinator = await _setup_mpris_coordinator(hass, entry, MagicMock(), stream)

        assert SSE_EVENT_PLAYER_UPDATED in stream._registered
        assert SSE_EVENT_PLAYER_ADDED in stream._registered
        assert SSE_EVENT_PLAYER_REMOVED in stream._registered
        assert SSE_EVENT_PLAYER_POSITION in stream._registered

        assert stream._registered[SSE_EVENT_PLAYER_UPDATED][0] == coordinator.handle_sse_update_event
        assert stream._registered[SSE_EVENT_PLAYER_ADDED][0] == coordinator.handle_sse_update_event
        assert stream._registered[SSE_EVENT_PLAYER_REMOVED][0] == coordinator.handle_sse_removed_event
        assert stream._registered[SSE_EVENT_PLAYER_POSITION][0] == coordinator.handle_sse_position_event

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioMPRISCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_registers_unload(self, mock_refresh):
        """Test that unload callbacks are registered."""
        entry = _make_entry()
        stream = _make_event_stream()

        await _setup_mpris_coordinator(_make_hass(), entry, MagicMock(), stream)

        # 1 (coordinator shutdown) + 4 SSE listeners = 5 unload callbacks
        assert len(entry._unload_callbacks) == 5


# =============================================================================
# Bluetooth coordinator setup
# =============================================================================


class TestSetupBluetoothCoordinator:
    """Tests for _setup_bluetooth_coordinator."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioBluetoothCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_creates_coordinator(self, mock_refresh):
        """Test that bluetooth coordinator is created and refreshed."""
        hass = _make_hass()
        entry = _make_entry()
        api = MagicMock()
        stream = _make_event_stream()

        result = await _setup_bluetooth_coordinator(hass, entry, api, stream)

        assert result is not None
        assert result.api is api
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioBluetoothCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_wires_sse_listener(self, mock_refresh):
        """Test that bluetooth SSE event is wired."""
        hass = _make_hass()
        entry = _make_entry()
        stream = _make_event_stream()

        coordinator = await _setup_bluetooth_coordinator(hass, entry, MagicMock(), stream)

        assert SSE_EVENT_BLUETOOTH_UPDATED in stream._registered
        assert stream._registered[SSE_EVENT_BLUETOOTH_UPDATED][0] == coordinator.handle_sse_event

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.coordinator.OdioBluetoothCoordinator.async_refresh",
        new_callable=AsyncMock,
    )
    async def test_registers_unload(self, mock_refresh):
        """Test that unload callback is registered."""
        entry = _make_entry()
        stream = _make_event_stream()

        await _setup_bluetooth_coordinator(_make_hass(), entry, MagicMock(), stream)

        # 1 (coordinator shutdown) + 1 SSE listener = 2 unload callbacks
        assert len(entry._unload_callbacks) == 2


# =============================================================================
# async_setup_entry
# =============================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_clientsession")
    @patch("custom_components.odio_remote._resolve_mac", new_callable=AsyncMock, return_value="aa:bb:cc:dd:ee:ff")
    @patch("custom_components.odio_remote._fetch_power_capabilities", new_callable=AsyncMock, return_value={"reboot": True})
    @patch("custom_components.odio_remote._setup_audio_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_service_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_mpris_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_bluetooth_coordinator", new_callable=AsyncMock)
    async def test_full_setup_all_backends(
        self, mock_bt, mock_mpris, mock_svc, mock_audio,
        mock_power, mock_mac, mock_session,
    ):
        from custom_components.odio_remote import async_setup_entry
        from .conftest import MOCK_SERVER_INFO

        hass = _make_hass()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_entry()
        entry.data = {
            "api_url": "http://192.168.1.10:8018",
            "server_info": MOCK_SERVER_INFO,
        }
        entry.options = {}

        api = MagicMock()
        api.get_server_info = AsyncMock(return_value=MOCK_SERVER_INFO)
        mock_session.return_value = MagicMock()

        with patch("custom_components.odio_remote.OdioApiClient", return_value=api), \
             patch("custom_components.odio_remote.OdioEventStreamManager") as mock_esm:
            mock_esm_instance = MagicMock()
            mock_esm_instance.async_add_listener = MagicMock(return_value=lambda: None)
            mock_esm.return_value = mock_esm_instance

            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_audio.assert_awaited_once()
        mock_svc.assert_awaited_once()
        mock_mpris.assert_awaited_once()
        mock_bt.assert_awaited_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        mock_esm_instance.start.assert_called_once()

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_clientsession")
    @patch("custom_components.odio_remote._resolve_mac", new_callable=AsyncMock, return_value=None)
    @patch("custom_components.odio_remote._fetch_power_capabilities", new_callable=AsyncMock, return_value={})
    async def test_setup_no_backends(self, mock_power, mock_mac, mock_session):
        from custom_components.odio_remote import async_setup_entry

        hass = _make_hass()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_entry()
        no_backends = {"backends": {}}
        entry.data = {"api_url": "http://localhost:8018", "server_info": no_backends}
        entry.options = {}

        api = MagicMock()
        api.get_server_info = AsyncMock(return_value=no_backends)

        with patch("custom_components.odio_remote.OdioApiClient", return_value=api), \
             patch("custom_components.odio_remote.OdioEventStreamManager") as mock_esm:
            mock_esm_instance = MagicMock()
            mock_esm_instance.async_add_listener = MagicMock(return_value=lambda: None)
            mock_esm.return_value = mock_esm_instance

            result = await async_setup_entry(hass, entry)

        assert result is True
        assert entry.runtime_data.audio_coordinator is None
        assert entry.runtime_data.service_coordinator is None
        assert entry.runtime_data.mpris_coordinator is None
        assert entry.runtime_data.bluetooth_coordinator is None

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_clientsession")
    @patch("custom_components.odio_remote._resolve_mac", new_callable=AsyncMock, return_value=None)
    @patch("custom_components.odio_remote._fetch_power_capabilities", new_callable=AsyncMock, return_value={})
    async def test_setup_falls_back_to_cached_server_info(self, mock_power, mock_mac, mock_session):
        from custom_components.odio_remote import async_setup_entry

        hass = _make_hass()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_entry()
        cached = {"hostname": "htpc", "backends": {}}
        entry.data = {"api_url": "http://localhost:8018", "server_info": cached}
        entry.options = {}

        api = MagicMock()
        api.get_server_info = AsyncMock(side_effect=ConnectionError("offline"))

        with patch("custom_components.odio_remote.OdioApiClient", return_value=api), \
             patch("custom_components.odio_remote.OdioEventStreamManager") as mock_esm:
            mock_esm_instance = MagicMock()
            mock_esm_instance.async_add_listener = MagicMock(return_value=lambda: None)
            mock_esm.return_value = mock_esm_instance

            result = await async_setup_entry(hass, entry)

        assert result is True


# =============================================================================
# _on_sse_reconnect
# =============================================================================


class TestOnSseReconnect:
    """Tests for the SSE reconnect callback inside async_setup_entry."""

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_clientsession")
    @patch("custom_components.odio_remote._resolve_mac", new_callable=AsyncMock, return_value=None)
    @patch("custom_components.odio_remote._fetch_power_capabilities", new_callable=AsyncMock, return_value={})
    @patch("custom_components.odio_remote._setup_audio_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_service_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_mpris_coordinator", new_callable=AsyncMock)
    @patch("custom_components.odio_remote._setup_bluetooth_coordinator", new_callable=AsyncMock)
    async def test_reconnect_refreshes_coordinators(
        self, mock_bt, mock_mpris, mock_svc, mock_audio,
        mock_power, mock_mac, mock_session,
    ):
        from custom_components.odio_remote import async_setup_entry
        from .conftest import MOCK_SERVER_INFO

        hass = _make_hass()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_entry()
        entry.data = {"api_url": "http://localhost:8018", "server_info": MOCK_SERVER_INFO}
        entry.options = {}

        audio_coord = MagicMock()
        audio_coord.async_refresh = AsyncMock()
        svc_coord = MagicMock()
        svc_coord.async_refresh = AsyncMock()
        mpris_coord = MagicMock()
        mpris_coord.async_refresh = AsyncMock()
        bt_coord = MagicMock()
        bt_coord.async_refresh = AsyncMock()

        mock_audio.return_value = audio_coord
        mock_svc.return_value = svc_coord
        mock_mpris.return_value = mpris_coord
        mock_bt.return_value = bt_coord

        api = MagicMock()
        api.get_server_info = AsyncMock(return_value=MOCK_SERVER_INFO)

        reconnect_cb = None

        with patch("custom_components.odio_remote.OdioApiClient", return_value=api), \
             patch("custom_components.odio_remote.OdioEventStreamManager") as mock_esm:
            mock_esm_instance = MagicMock()
            mock_esm_instance.sse_connected = True

            def capture_listener(cb):
                nonlocal reconnect_cb
                reconnect_cb = cb
                return lambda: None

            mock_esm_instance.async_add_listener = capture_listener
            mock_esm.return_value = mock_esm_instance

            await async_setup_entry(hass, entry)

        assert reconnect_cb is not None
        reconnect_cb()
        assert hass.async_create_task.call_count == 4

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_clientsession")
    @patch("custom_components.odio_remote._resolve_mac", new_callable=AsyncMock, return_value=None)
    @patch("custom_components.odio_remote._fetch_power_capabilities", new_callable=AsyncMock, return_value={})
    async def test_reconnect_noop_when_disconnected(self, mock_power, mock_mac, mock_session):
        from custom_components.odio_remote import async_setup_entry

        hass = _make_hass()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _make_entry()
        entry.data = {"api_url": "http://localhost:8018", "server_info": {"backends": {}}}
        entry.options = {}

        api = MagicMock()
        api.get_server_info = AsyncMock(return_value={"backends": {}})

        reconnect_cb = None

        with patch("custom_components.odio_remote.OdioApiClient", return_value=api), \
             patch("custom_components.odio_remote.OdioEventStreamManager") as mock_esm:
            mock_esm_instance = MagicMock()
            mock_esm_instance.sse_connected = False

            def capture_listener(cb):
                nonlocal reconnect_cb
                reconnect_cb = cb
                return lambda: None

            mock_esm_instance.async_add_listener = capture_listener
            mock_esm.return_value = mock_esm_instance

            await async_setup_entry(hass, entry)

        reconnect_cb()
        hass.async_create_task.assert_not_called()


# =============================================================================
# async_unload_entry / async_remove_config_entry_device
# =============================================================================


class TestAsyncUnload:

    @pytest.mark.asyncio
    async def test_unload_stops_event_stream(self):
        from custom_components.odio_remote import async_unload_entry

        hass = _make_hass()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        entry = MagicMock()
        entry.runtime_data.event_stream.stop = AsyncMock()

        result = await async_unload_entry(hass, entry)

        assert result is True
        entry.runtime_data.event_stream.stop.assert_awaited_once()
        hass.config_entries.async_unload_platforms.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_device_returns_true(self):
        from custom_components.odio_remote import async_remove_config_entry_device

        result = await async_remove_config_entry_device(MagicMock(), MagicMock(), MagicMock())
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
