"""Tests for Odio Remote setup/teardown in __init__.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pyodio import OdioConnectionError, PowerCapabilities, ServerInfo

from custom_components.odio_remote import (
    OdioRemoteRuntimeData,
    PLATFORMS,
    _resolve_mac,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.odio_remote.const import (
    CONF_API_URL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_KEEPALIVE_INTERVAL,
)

from .conftest import (
    MOCK_SERVER_INFO,
    MOCK_SERVICES,
    TEST_API_URL,
    make_hub,
    push_event,
    set_connected,
)

ENTRY_ID = "test_entry_id"

UPGRADE_SERVER_INFO = {
    **MOCK_SERVER_INFO,
    "backends": {**MOCK_SERVER_INFO["backends"], "upgrade": True},
}


def _make_hass():
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    def _apply_update(entry, **kwargs):
        if "data" in kwargs:
            entry.data = kwargs["data"]

    hass.config_entries.async_update_entry = MagicMock(side_effect=_apply_update)
    return hass


def _make_entry(data=None, options=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {CONF_API_URL: TEST_API_URL, **(data or {})}
    entry.options = options or {}
    return entry


def _prepare_hub(hub, connect_error=None):
    hub.connect = (
        AsyncMock(side_effect=connect_error)
        if connect_error
        else AsyncMock(return_value=hub)
    )
    hub.start = AsyncMock()
    hub.close = AsyncMock()
    return hub


async def _setup(hass, entry, hub):
    """Run async_setup_entry with the hub class and MAC resolution patched."""
    session = MagicMock()
    with patch(
        "custom_components.odio_remote.OdioHub", return_value=hub
    ) as hub_cls, patch(
        "custom_components.odio_remote.async_get_clientsession", return_value=session
    ), patch(
        "custom_components.odio_remote.async_get_mac_from_ip",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await async_setup_entry(hass, entry)
    return result, hub_cls, session


# =============================================================================
# MAC resolution
# =============================================================================


class TestResolveMac:
    """Tests for _resolve_mac."""

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_resolves_and_caches_mac(self, mock_get_mac):
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
        mock_get_mac.return_value = None
        entry = _make_entry()
        entry.data = {"mac": "11:22:33:44:55:66"}

        result = await _resolve_mac(MagicMock(), entry, "http://192.168.1.10:8018")

        assert result == "11:22:33:44:55:66"

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.async_get_mac_from_ip", new_callable=AsyncMock)
    async def test_returns_none_when_no_mac(self, mock_get_mac):
        mock_get_mac.return_value = None
        entry = _make_entry()
        entry.data = {}

        result = await _resolve_mac(MagicMock(), entry, "http://192.168.1.10:8018")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_no_host(self):
        entry = _make_entry()
        entry.data = {}

        result = await _resolve_mac(MagicMock(), entry, "")

        assert result is None


# =============================================================================
# async_setup_entry — nominal path
# =============================================================================


class TestAsyncSetupEntry:

    @pytest.mark.asyncio
    async def test_nominal_setup(self):
        hass = _make_hass()
        entry = _make_entry(options={CONF_SERVICE_MAPPINGS: {"svc": "media_player.x"}})
        hub = _prepare_hub(make_hub(services=MOCK_SERVICES))

        result, hub_cls, session = await _setup(hass, entry, hub)

        assert result is True
        hub_cls.assert_called_once_with(
            TEST_API_URL, session, keepalive=DEFAULT_KEEPALIVE_INTERVAL
        )
        hub.connect.assert_awaited_once()
        hub.start.assert_not_awaited()
        rd = entry.runtime_data
        assert isinstance(rd, OdioRemoteRuntimeData)
        assert rd.hub is hub
        assert rd.server_info.hostname == "htpc"
        assert rd.service_mappings == {"svc": "media_player.x"}
        assert isinstance(rd.power_capabilities, PowerCapabilities)
        assert rd.device_info["name"] == "Odio Remote (htpc)"
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_startup_data_cached_in_entry(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = _prepare_hub(make_hub())

        await _setup(hass, entry, hub)

        assert entry.data["server_info"]["hostname"] == "htpc"
        assert "power_capabilities" in entry.data

    @pytest.mark.asyncio
    async def test_services_cached_when_systemd_enabled(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = _prepare_hub(make_hub(services=MOCK_SERVICES))

        await _setup(hass, entry, hub)

        cached = entry.data["cached_services"]
        assert {s["name"] for s in cached} == {s["name"] for s in MOCK_SERVICES}


# =============================================================================
# async_setup_entry — degraded path (API down at startup)
# =============================================================================


class TestDegradedStartup:

    @pytest.mark.asyncio
    async def test_falls_back_to_cache_and_starts_stream(self):
        hass = _make_hass()
        entry = _make_entry(data={"server_info": MOCK_SERVER_INFO})
        hub = _prepare_hub(make_hub(connected=False), connect_error=OdioConnectionError("down"))

        result, _, _ = await _setup(hass, entry, hub)

        assert result is True
        hub.start.assert_awaited_once()
        assert entry.runtime_data.server_info.hostname == "htpc"
        assert entry.runtime_data.server_info.backends.systemd is True
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_degraded_without_cache_uses_empty_defaults(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = _prepare_hub(make_hub(connected=False), connect_error=OdioConnectionError("down"))

        result, _, _ = await _setup(hass, entry, hub)

        assert result is True
        assert entry.runtime_data.server_info.backends.systemd is False


# =============================================================================
# Connection change — backend re-detection on SSE reconnect
# =============================================================================


class TestConnectionChange:

    async def _setup_connected(self, hass, entry):
        hub = _prepare_hub(make_hub(services=MOCK_SERVICES))
        await _setup(hass, entry, hub)
        return hub

    @pytest.mark.asyncio
    async def test_reload_when_backends_change_on_reconnect(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = await self._setup_connected(hass, entry)

        hub._server = ServerInfo.from_dict(UPGRADE_SERVER_INFO)
        set_connected(hub, False)
        set_connected(hub, True)

        hass.config_entries.async_schedule_reload.assert_called_once_with(ENTRY_ID)

    @pytest.mark.asyncio
    async def test_no_reload_when_backends_unchanged(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = await self._setup_connected(hass, entry)

        set_connected(hub, False)
        set_connected(hub, True)

        hass.config_entries.async_schedule_reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnect_recaches_startup_and_services(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = await self._setup_connected(hass, entry)

        # Fresh state on reconnect must be re-persisted.
        hub._server = ServerInfo.from_dict({**MOCK_SERVER_INFO, "hostname": "htpc2"})
        set_connected(hub, False)
        set_connected(hub, True)

        hass.config_entries.async_schedule_reload.assert_not_called()
        assert entry.data["server_info"]["hostname"] == "htpc2"

    @pytest.mark.asyncio
    async def test_disconnect_does_nothing(self):
        hass = _make_hass()
        entry = _make_entry()
        hub = await self._setup_connected(hass, entry)
        hass.config_entries.async_update_entry.reset_mock()

        set_connected(hub, False)

        hass.config_entries.async_schedule_reload.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()


# =============================================================================
# Device registry sw_version sync (upgrade backend)
# =============================================================================


class TestSwVersionSync:

    async def _setup_with_upgrade(self, hass, entry, current="1.0.0"):
        hub = _prepare_hub(
            make_hub(
                server_info=UPGRADE_SERVER_INFO,
                upgrade={"current": current, "upgrade_available": False},
            )
        )
        await _setup(hass, entry, hub)
        return hub

    def _registry(self, device):
        registry = MagicMock()
        registry.async_get_device.return_value = device
        return registry

    @pytest.mark.asyncio
    async def test_syncs_device_sw_version_on_new_current(self):
        hass = _make_hass()
        hub = await self._setup_with_upgrade(hass, _make_entry())
        device = MagicMock(id="dev1", sw_version="1.0.0")
        registry = self._registry(device)

        with patch("custom_components.odio_remote.dr.async_get", return_value=registry):
            push_event(hub, "upgrade.info", {"current": "2.0.0", "upgrade_available": False})

        registry.async_update_device.assert_called_once_with("dev1", sw_version="2.0.0")

    @pytest.mark.asyncio
    async def test_no_registry_write_when_current_unchanged(self):
        hass = _make_hass()
        hub = await self._setup_with_upgrade(hass, _make_entry())
        registry = self._registry(MagicMock(id="dev1", sw_version="1.0.0"))

        with patch("custom_components.odio_remote.dr.async_get", return_value=registry):
            push_event(hub, "upgrade.info", {"current": "1.0.0", "upgrade_available": False})

        registry.async_get_device.assert_not_called()
        registry.async_update_device.assert_not_called()

    @pytest.mark.asyncio
    async def test_repeated_current_hits_registry_once(self):
        hass = _make_hass()
        hub = await self._setup_with_upgrade(hass, _make_entry())
        registry = self._registry(MagicMock(id="dev1", sw_version="1.0.0"))

        with patch("custom_components.odio_remote.dr.async_get", return_value=registry):
            push_event(hub, "upgrade.info", {"current": "2.0.0", "upgrade_available": False})
            push_event(hub, "upgrade.info", {"current": "2.0.0", "upgrade_available": False})

        assert registry.async_get_device.call_count == 1

    @pytest.mark.asyncio
    async def test_device_info_uses_detector_current(self):
        hass = _make_hass()
        entry = _make_entry()
        await self._setup_with_upgrade(hass, entry, current="1.2.3")
        assert entry.runtime_data.device_info["sw_version"] == "1.2.3"


# =============================================================================
# async_unload_entry / async_remove_config_entry_device
# =============================================================================


class TestAsyncUnload:

    @pytest.mark.asyncio
    async def test_unload_closes_hub(self):
        hass = _make_hass()
        entry = MagicMock()
        entry.runtime_data.hub.close = AsyncMock()

        result = await async_unload_entry(hass, entry)

        assert result is True
        entry.runtime_data.hub.close.assert_awaited_once()
        hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_remove_device_returns_true(self):
        result = await async_remove_config_entry_device(
            MagicMock(), MagicMock(), MagicMock()
        )
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
