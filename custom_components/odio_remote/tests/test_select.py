"""Tests for Odio Remote select platform."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.odio_remote.select import (
    OdioBluetoothPairSelect,
    async_setup_entry,
)

from .conftest import MOCK_BLUETOOTH_STATUS, MOCK_DEVICE_INFO


def _make_bt_coordinator(data=None, last_update_success=True):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = last_update_success
    coord.async_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_event_stream(sse_connected=True):
    es = MagicMock()
    es.sse_connected = sse_connected
    es.async_add_listener = MagicMock(return_value=lambda: None)
    return es


def _make_select(data=None, sse_connected=True, last_update_success=True, api=None):
    coord = _make_bt_coordinator(data, last_update_success)
    es = _make_event_stream(sse_connected)
    return OdioBluetoothPairSelect(coord, api or MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es)


# A status with one paired device (Pixel) + two discovered unpaired devices.
_DISCOVERED = {
    **MOCK_BLUETOOTH_STATUS,
    "scanning": True,
    "known_devices": [
        # paired device (Pixel) — excluded from the select, gets its own switch
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Pixel 6a", "paired": True, "bonded": True, "connected": True},
        {"address": "11:22:33:44:55:66", "name": "JBL Flip", "paired": False, "bonded": False},
        {"address": "77:88:99:AA:BB:CC", "paired": False, "bonded": False},
    ],
}


class TestOdioBluetoothPairSelectConstruction:

    def test_unique_id(self):
        assert _make_select().unique_id == "test_entry_id_bluetooth_pair"

    def test_translation_key(self):
        assert _make_select().translation_key == "bluetooth_pair"

    def test_current_option_is_none(self):
        assert _make_select(data=_DISCOVERED).current_option is None


class TestOdioBluetoothPairSelectOptions:

    def test_options_list_only_unpaired_discovered(self):
        options = _make_select(data=_DISCOVERED).options
        assert options == ["JBL Flip (11:22:33:44:55:66)", "77:88:99:AA:BB:CC"]

    def test_paired_devices_excluded(self):
        # The Pixel (paired/bonded) must not appear as a pairable option.
        options = _make_select(data=_DISCOVERED).options
        assert not any("Pixel" in o for o in options)

    def test_empty_when_no_discovered(self):
        assert _make_select(data=MOCK_BLUETOOTH_STATUS).options == []

    def test_empty_when_no_data(self):
        assert _make_select(data=None).options == []


class TestOdioBluetoothPairSelectAvailable:

    def test_available_when_discovered_present(self):
        assert _make_select(data=_DISCOVERED).available is True

    def test_unavailable_when_no_discovered(self):
        assert _make_select(data=MOCK_BLUETOOTH_STATUS).available is False

    def test_unavailable_when_sse_disconnected(self):
        assert _make_select(data=_DISCOVERED, sse_connected=False).available is False

    def test_unavailable_when_last_update_failed(self):
        assert _make_select(data=_DISCOVERED, last_update_success=False).available is False


class TestOdioBluetoothPairSelectActions:

    @pytest.mark.asyncio
    async def test_select_option_connects_named_device(self):
        api = MagicMock()
        api.bluetooth_connect = AsyncMock()
        coord = _make_bt_coordinator(_DISCOVERED)
        es = _make_event_stream()
        select = OdioBluetoothPairSelect(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)

        await select.async_select_option("JBL Flip (11:22:33:44:55:66)")

        api.bluetooth_connect.assert_awaited_once_with("11:22:33:44:55:66")
        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_select_option_connects_unnamed_device(self):
        api = MagicMock()
        api.bluetooth_connect = AsyncMock()
        coord = _make_bt_coordinator(_DISCOVERED)
        es = _make_event_stream()
        select = OdioBluetoothPairSelect(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)

        await select.async_select_option("77:88:99:AA:BB:CC")

        api.bluetooth_connect.assert_awaited_once_with("77:88:99:AA:BB:CC")

    @pytest.mark.asyncio
    async def test_select_matches_by_address_after_name_resolves(self):
        # Option rendered while the device was unnamed (label == bare address);
        # the name has since resolved, so label-matching would miss — matching
        # on the embedded address must still connect.
        api = MagicMock()
        api.bluetooth_connect = AsyncMock()
        coord = _make_bt_coordinator(_DISCOVERED)  # "11:22:..." is now "JBL Flip"
        es = _make_event_stream()
        select = OdioBluetoothPairSelect(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)

        await select.async_select_option("11:22:33:44:55:66")

        api.bluetooth_connect.assert_awaited_once_with("11:22:33:44:55:66")

    @pytest.mark.asyncio
    async def test_select_unknown_option_noop(self):
        api = MagicMock()
        api.bluetooth_connect = AsyncMock()
        coord = _make_bt_coordinator(_DISCOVERED)
        es = _make_event_stream()
        select = OdioBluetoothPairSelect(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)

        await select.async_select_option("gone (00:00:00:00:00:00)")

        api.bluetooth_connect.assert_not_called()


class TestOdioBluetoothPairSelectLifecycle:

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_sse(self):
        es = _make_event_stream()
        select = OdioBluetoothPairSelect(
            _make_bt_coordinator(_DISCOVERED), MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es
        )
        select.async_on_remove = MagicMock()
        with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
            await select.async_added_to_hass()
        es.async_add_listener.assert_called_with(select.async_write_ha_state)


def _make_entry(bt_coordinator):
    from custom_components.odio_remote import OdioCoordinators
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.runtime_data.coordinators = OdioCoordinators(bluetooth=bt_coordinator)
    entry.runtime_data.api = MagicMock()
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.event_stream = _make_event_stream()
    entry.async_on_unload = MagicMock()
    return entry


class TestSelectSetupEntry:

    @pytest.mark.asyncio
    async def test_creates_pair_select_when_bt_present(self):
        entry = _make_entry(_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioBluetoothPairSelect)

    @pytest.mark.asyncio
    async def test_no_select_when_bt_absent(self):
        entry = _make_entry(bt_coordinator=None)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []
