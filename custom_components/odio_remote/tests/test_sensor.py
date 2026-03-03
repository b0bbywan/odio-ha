"""Tests for Odio Remote sensor platform."""
import pytest
from unittest.mock import MagicMock

from custom_components.odio_remote.sensor import (
    OdioBluetoothConnectedDeviceSensor,
    async_setup_entry,
)

from .conftest import MOCK_BLUETOOTH_STATUS, MOCK_DEVICE_INFO

ENTRY_ID = "test_entry_id"


def _make_bt_coordinator(data=None):
    coord = MagicMock()
    coord.data = data
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_sensor(data=None):
    return OdioBluetoothConnectedDeviceSensor(
        _make_bt_coordinator(data), ENTRY_ID, MOCK_DEVICE_INFO
    )


def _make_entry(bt_coordinator=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.bluetooth_coordinator = bt_coordinator
    return entry


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestOdioBluetoothConnectedDeviceSensorConstruction:

    def test_unique_id(self):
        assert _make_sensor().unique_id == f"{ENTRY_ID}_bluetooth_connected_device"

    def test_translation_key(self):
        assert _make_sensor().translation_key == "bluetooth_connected_device"

    def test_has_entity_name(self):
        assert _make_sensor()._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in _make_sensor().device_info["identifiers"]


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------

class TestOdioBluetoothConnectedDeviceSensorValue:

    def test_returns_connected_device_name(self):
        assert _make_sensor(MOCK_BLUETOOTH_STATUS).native_value == "Pixel 6a"

    def test_returns_none_when_no_connected_device(self):
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Old Device", "trusted": True, "connected": False}
        ]}
        assert _make_sensor(data).native_value == "none"

    def test_returns_none_when_known_devices_empty(self):
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": []}
        assert _make_sensor(data).native_value == "none"

    def test_returns_none_when_no_data(self):
        assert _make_sensor(None).native_value == "none"

    def test_returns_first_connected_when_multiple(self):
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Device A", "trusted": True, "connected": False},
            {"address": "11:22:33:44:55:66", "name": "Device B", "trusted": True, "connected": True},
            {"address": "77:88:99:AA:BB:CC", "name": "Device C", "trusted": True, "connected": True},
        ]}
        assert _make_sensor(data).native_value == "Device B"


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestSensorSetupEntry:

    @pytest.mark.asyncio
    async def test_sensor_created_when_bt_coordinator_present(self):
        entry = _make_entry(bt_coordinator=_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioBluetoothConnectedDeviceSensor)

    @pytest.mark.asyncio
    async def test_no_sensor_when_bt_coordinator_absent(self):
        entry = _make_entry(bt_coordinator=None)
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_not_called()
