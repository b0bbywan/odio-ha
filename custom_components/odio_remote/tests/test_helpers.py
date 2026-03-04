"""Tests for Odio Remote helpers."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.odio_remote.exceptions import (
    OdioApiError,
    OdioConnectionError,
    OdioTimeoutError,
)
from custom_components.odio_remote.helpers import api_command, async_get_mac_from_ip


def _make_hass(gethostbyname_result, dt_states=None):
    """Return a mock hass configured for device_tracker-only MAC resolution."""
    hass = MagicMock()
    if isinstance(gethostbyname_result, Exception):
        hass.async_add_executor_job = AsyncMock(side_effect=gethostbyname_result)
    else:
        hass.async_add_executor_job = AsyncMock(return_value=gethostbyname_result)
    hass.states.async_all.return_value = dt_states or []
    return hass


def _make_dt_state(entity_id, ip, mac=None):
    """Return a mock device_tracker state."""
    state = MagicMock()
    state.entity_id = entity_id
    state.attributes = {"ip": ip}
    if mac is not None:
        state.attributes["mac"] = mac
    return state


class TestAsyncGetMacFromIp:
    """Tests for async_get_mac_from_ip."""

    @pytest.mark.asyncio
    async def test_returns_mac_from_device_tracker(self):
        """Returns MAC from matching device_tracker entity."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", "aa:bb:cc:dd:ee:ff")
        hass = _make_hass("192.168.1.100", dt_states=[dt])

        result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "aa:bb:cc:dd:ee:ff"

    @pytest.mark.asyncio
    async def test_hostname_resolved_before_device_tracker_lookup(self):
        """Hostname is resolved to IP before searching device_tracker entities."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.50", "bb:cc:dd:ee:ff:00")
        hass = _make_hass("192.168.1.50", dt_states=[dt])

        result = await async_get_mac_from_ip(hass, "mydevice.local")

        assert result == "bb:cc:dd:ee:ff:00"
        hass.async_add_executor_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_device_tracker_matches(self):
        """Returns None when no device_tracker entity has the target IP."""
        dt = _make_dt_state("device_tracker.other", "192.168.1.200", "11:22:33:44:55:66")
        hass = _make_hass("192.168.1.100", dt_states=[dt])

        result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_device_trackers(self):
        """Returns None when no device_tracker entities exist."""
        hass = _make_hass("192.168.1.100")

        result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_device_tracker_without_mac_attribute(self):
        """Skips device_tracker entity that matches IP but has no mac attribute."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", mac=None)
        hass = _make_hass("192.168.1.100", dt_states=[dt])

        result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_gethostbyname_fails(self):
        """Returns None immediately when DNS resolution fails."""
        hass = _make_hass(OSError("Name or service not known"))

        result = await async_get_mac_from_ip(hass, "unknown.host")

        assert result is None
        hass.states.async_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_matching_device_tracker_wins(self):
        """Returns MAC from first device_tracker that matches."""
        dt1 = _make_dt_state("device_tracker.first", "192.168.1.100", "aa:aa:aa:aa:aa:aa")
        dt2 = _make_dt_state("device_tracker.second", "192.168.1.100", "bb:bb:bb:bb:bb:bb")
        hass = _make_hass("192.168.1.100", dt_states=[dt1, dt2])

        result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "aa:aa:aa:aa:aa:aa"

    @pytest.mark.asyncio
    async def test_queries_device_tracker_domain(self):
        """device_tracker domain is searched for matching entity."""
        hass = _make_hass("192.168.1.100")

        await async_get_mac_from_ip(hass, "192.168.1.100")

        hass.states.async_all.assert_called_once_with("device_tracker")


class TestApiCommand:
    """Tests for the api_command decorator."""

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        """Successful calls return the function result unchanged."""
        @api_command
        async def action():
            return "ok"

        assert await action() == "ok"

    @pytest.mark.asyncio
    async def test_reraises_homeassistant_error(self):
        """Existing HomeAssistantError passes through unchanged."""
        @api_command
        async def action():
            raise HomeAssistantError("already ha")

        with pytest.raises(HomeAssistantError, match="already ha"):
            await action()

    @pytest.mark.asyncio
    async def test_converts_odio_connection_error(self):
        """OdioConnectionError is re-raised as HomeAssistantError."""
        @api_command
        async def action():
            raise OdioConnectionError("unreachable")

        with pytest.raises(HomeAssistantError, match="unreachable"):
            await action()

    @pytest.mark.asyncio
    async def test_converts_odio_timeout_error(self):
        """OdioTimeoutError is re-raised as HomeAssistantError."""
        @api_command
        async def action():
            raise OdioTimeoutError("timed out")

        with pytest.raises(HomeAssistantError, match="timed out"):
            await action()

    @pytest.mark.asyncio
    async def test_converts_odio_api_error(self):
        """OdioApiError is re-raised as HomeAssistantError."""
        @api_command
        async def action():
            raise OdioApiError("bad response", status=500)

        with pytest.raises(HomeAssistantError, match="bad response"):
            await action()

    @pytest.mark.asyncio
    async def test_lets_programming_errors_bubble(self):
        """TypeError and other bugs are not caught — they bubble naturally."""
        @api_command
        async def action():
            raise TypeError("this is a bug")

        with pytest.raises(TypeError, match="this is a bug"):
            await action()
