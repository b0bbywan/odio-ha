"""Tests for Odio Remote helpers."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.odio_remote.helpers import async_get_mac_from_ip


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
