"""Tests for Odio Remote helpers."""
import functools
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.odio_remote.helpers import (
    _mac_from_device_trackers,
    async_get_mac_from_ip,
)


def _mock_getmac(mac_return_value):
    """Patch sys.modules so the lazy `from getmac import …` inside the helper resolves."""
    mock_module = MagicMock()
    mock_module.get_mac_address.return_value = mac_return_value
    return patch.dict(sys.modules, {"getmac": mock_module})


def _make_hass(gethostbyname_result, getmac_result, dt_states=None):
    """Return a mock hass where executor calls return gethostbyname then getmac values."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        side_effect=[gethostbyname_result, getmac_result]
    )
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
    async def test_returns_mac_on_success(self):
        """Returns the MAC string when getmac resolves it."""
        hass = _make_hass("192.168.1.100", "aa:bb:cc:dd:ee:ff")

        with _mock_getmac("aa:bb:cc:dd:ee:ff"):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "aa:bb:cc:dd:ee:ff"
        assert hass.async_add_executor_job.await_count == 2

    @pytest.mark.asyncio
    async def test_hostname_resolved_to_ip_before_mac_lookup(self):
        """Hostname is resolved to IP via gethostbyname before calling getmac."""
        hass = MagicMock()
        hass.states.async_all.return_value = []
        calls = []

        async def capture(*args):
            calls.append(args)
            return "192.168.1.50" if len(calls) == 1 else "bb:cc:dd:ee:ff:00"

        hass.async_add_executor_job = capture

        with _mock_getmac("bb:cc:dd:ee:ff:00"):
            result = await async_get_mac_from_ip(hass, "rasponkyo")

        assert result == "bb:cc:dd:ee:ff:00"
        # First call: gethostbyname("rasponkyo")
        assert calls[0] == (pytest.approx, "rasponkyo") or calls[0][1] == "rasponkyo"
        # Second call: partial(get_mac_address, ip="192.168.1.50")
        mac_fn = calls[1][0]
        assert isinstance(mac_fn, functools.partial)
        assert mac_fn.keywords.get("ip") == "192.168.1.50"

    @pytest.mark.asyncio
    async def test_resolved_ip_passed_to_getmac(self):
        """get_mac_address receives the resolved IP, not the original hostname."""
        hass = MagicMock()
        hass.states.async_all.return_value = []
        calls = []

        async def capture(*args):
            calls.append(args)
            return "10.0.0.42" if len(calls) == 1 else "cc:dd:ee:ff:00:11"

        hass.async_add_executor_job = capture

        with _mock_getmac("cc:dd:ee:ff:00:11"):
            await async_get_mac_from_ip(hass, "mydevice.local")

        mac_partial = calls[1][0]
        assert isinstance(mac_partial, functools.partial)
        assert mac_partial.keywords["ip"] == "10.0.0.42"

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_returns_none(self):
        """Falls back to device trackers when getmac finds no ARP entry."""
        hass = _make_hass("192.168.1.100", None)

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_returns_empty_string(self):
        """Falls back to device trackers when getmac returns an empty string."""
        hass = _make_hass("192.168.1.100", "")

        with _mock_getmac(""):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_gethostbyname_fails(self):
        """Returns None immediately when DNS resolution fails."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=OSError("Name or service not known")
        )
        hass.states.async_all.return_value = []

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "unknown.host")

        assert result is None
        # DNS failure short-circuits before device tracker fallback
        hass.states.async_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_raises(self):
        """Falls back to device trackers when the getmac executor job raises."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=["192.168.1.100", OSError("ARP failed")]
        )
        hass.states.async_all.return_value = []

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_not_installed(self):
        """Falls back to device trackers when getmac is not importable."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value="192.168.1.100")
        hass.states.async_all.return_value = []

        with patch.dict(sys.modules, {"getmac": None}):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None
        # gethostbyname is still called before the import attempt
        hass.async_add_executor_job.assert_awaited_once()


class TestDeviceTrackerFallback:
    """Tests for device_tracker fallback in async_get_mac_from_ip."""

    @pytest.mark.asyncio
    async def test_returns_mac_from_device_tracker_when_arp_fails(self):
        """Returns MAC from device_tracker when ARP returns None."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", "de:ad:be:ef:00:01")
        hass = _make_hass("192.168.1.100", None, dt_states=[dt])

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "de:ad:be:ef:00:01"

    @pytest.mark.asyncio
    async def test_returns_mac_from_device_tracker_when_arp_empty(self):
        """Returns MAC from device_tracker when ARP returns empty string."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", "de:ad:be:ef:00:02")
        hass = _make_hass("192.168.1.100", "", dt_states=[dt])

        with _mock_getmac(""):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "de:ad:be:ef:00:02"

    @pytest.mark.asyncio
    async def test_arp_takes_precedence_over_device_tracker(self):
        """ARP result is returned without consulting device trackers."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", "ff:ff:ff:ff:ff:ff")
        hass = _make_hass("192.168.1.100", "aa:bb:cc:dd:ee:ff", dt_states=[dt])

        with _mock_getmac("aa:bb:cc:dd:ee:ff"):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result == "aa:bb:cc:dd:ee:ff"
        hass.states.async_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_device_tracker_has_no_match(self):
        """Returns None when no device_tracker entity has the target IP."""
        dt = _make_dt_state("device_tracker.other", "192.168.1.200", "11:22:33:44:55:66")
        hass = _make_hass("192.168.1.100", None, dt_states=[dt])

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_device_tracker_skips_entity_without_mac_attr(self):
        """Skips device_tracker entity that matches IP but has no mac attribute."""
        dt = _make_dt_state("device_tracker.odio", "192.168.1.100", mac=None)
        hass = _make_hass("192.168.1.100", None, dt_states=[dt])

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None


class TestMacFromDeviceTrackers:
    """Unit tests for _mac_from_device_trackers."""

    def test_returns_mac_for_matching_ip(self):
        hass = MagicMock()
        hass.states.async_all.return_value = [
            _make_dt_state("device_tracker.odio", "192.168.1.100", "aa:bb:cc:dd:ee:ff"),
        ]
        assert _mac_from_device_trackers(hass, "192.168.1.100") == "aa:bb:cc:dd:ee:ff"

    def test_returns_none_when_no_entity_matches(self):
        hass = MagicMock()
        hass.states.async_all.return_value = [
            _make_dt_state("device_tracker.other", "10.0.0.1", "11:22:33:44:55:66"),
        ]
        assert _mac_from_device_trackers(hass, "192.168.1.100") is None

    def test_returns_none_when_no_entities(self):
        hass = MagicMock()
        hass.states.async_all.return_value = []
        assert _mac_from_device_trackers(hass, "192.168.1.100") is None

    def test_skips_entity_without_mac(self):
        hass = MagicMock()
        hass.states.async_all.return_value = [
            _make_dt_state("device_tracker.odio", "192.168.1.100", mac=None),
        ]
        assert _mac_from_device_trackers(hass, "192.168.1.100") is None

    def test_queries_device_tracker_domain(self):
        hass = MagicMock()
        hass.states.async_all.return_value = []
        _mac_from_device_trackers(hass, "192.168.1.100")
        hass.states.async_all.assert_called_once_with("device_tracker")
