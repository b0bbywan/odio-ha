"""Tests for Odio Remote helpers."""
import functools
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.odio_remote.helpers import async_get_mac_from_ip


def _mock_getmac(mac_return_value):
    """Patch sys.modules so the lazy `from getmac import …` inside the helper resolves."""
    mock_module = MagicMock()
    mock_module.get_mac_address.return_value = mac_return_value
    return patch.dict(sys.modules, {"getmac": mock_module})


def _make_hass(gethostbyname_result, getmac_result):
    """Return a mock hass where executor calls return gethostbyname then getmac values."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        side_effect=[gethostbyname_result, getmac_result]
    )
    return hass


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
        """Returns None when getmac finds no ARP entry."""
        hass = _make_hass("192.168.1.100", None)

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_returns_empty_string(self):
        """Returns None when getmac returns an empty string (no ARP entry)."""
        hass = _make_hass("192.168.1.100", "")

        with _mock_getmac(""):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_gethostbyname_fails(self):
        """Returns None when DNS resolution fails (unknown host)."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=OSError("Name or service not known")
        )

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "unknown.host")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_raises(self):
        """Returns None when the getmac executor job raises."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(
            side_effect=["192.168.1.100", OSError("ARP failed")]
        )

        with _mock_getmac(None):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_getmac_not_installed(self):
        """Returns None gracefully when getmac is not importable."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock()

        with patch.dict(sys.modules, {"getmac": None}):
            result = await async_get_mac_from_ip(hass, "192.168.1.100")

        assert result is None
        # Import fails before any executor job is dispatched
        hass.async_add_executor_job.assert_not_awaited()
