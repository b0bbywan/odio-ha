"""Tests for Odio Remote binary_sensor platform."""
import pytest
from unittest.mock import MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.odio_remote.binary_sensor import (
    ConnectionStatusSensor,
    OdioBluetoothPairingActiveSensor,
    async_setup_entry,
)

from .conftest import MOCK_BLUETOOTH_STATUS, MOCK_DEVICE_INFO

ENTRY_ID = "test_entry_id"


def _make_event_stream(sse_connected=True):
    stream = MagicMock()
    stream.sse_connected = sse_connected
    stream.async_add_listener = MagicMock(return_value=lambda: None)
    return stream


def _make_bt_coordinator(data=None):
    coord = MagicMock()
    coord.data = data
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_entry(bt_coordinator=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data.event_stream = _make_event_stream()
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    from custom_components.odio_remote import OdioCoordinators
    entry.runtime_data.coordinators = OdioCoordinators(bluetooth=bt_coordinator)
    return entry


# ---------------------------------------------------------------------------
# ConnectionStatusSensor (existing, regression)
# ---------------------------------------------------------------------------

class TestConnectionStatusSensor:

    def test_is_on_when_sse_connected(self):
        sensor = ConnectionStatusSensor(_make_event_stream(True), ENTRY_ID, MOCK_DEVICE_INFO)
        assert sensor.is_on is True

    def test_is_off_when_sse_disconnected(self):
        sensor = ConnectionStatusSensor(_make_event_stream(False), ENTRY_ID, MOCK_DEVICE_INFO)
        assert sensor.is_on is False

    def test_unique_id(self):
        sensor = ConnectionStatusSensor(_make_event_stream(), ENTRY_ID, MOCK_DEVICE_INFO)
        assert sensor.unique_id == f"{ENTRY_ID}_connectivity"


# ---------------------------------------------------------------------------
# OdioBluetoothPairingActiveSensor — construction
# ---------------------------------------------------------------------------

class TestOdioBluetoothPairingActiveSensorConstruction:

    def _make_sensor(self, data=None):
        return OdioBluetoothPairingActiveSensor(
            _make_bt_coordinator(data), ENTRY_ID, MOCK_DEVICE_INFO
        )

    def test_unique_id(self):
        assert self._make_sensor().unique_id == f"{ENTRY_ID}_bluetooth_pairing_active"

    def test_translation_key(self):
        assert self._make_sensor().translation_key == "bluetooth_pairing_active"

    def test_entity_category_is_diagnostic(self):
        assert self._make_sensor().entity_category == EntityCategory.DIAGNOSTIC

    def test_has_entity_name(self):
        assert self._make_sensor()._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in self._make_sensor().device_info["identifiers"]


# ---------------------------------------------------------------------------
# OdioBluetoothPairingActiveSensor — is_on
# ---------------------------------------------------------------------------

class TestOdioBluetoothPairingActiveSensorIsOn:

    def _make_sensor(self, data):
        return OdioBluetoothPairingActiveSensor(
            _make_bt_coordinator(data), ENTRY_ID, MOCK_DEVICE_INFO
        )

    def test_is_off_when_not_pairing(self):
        assert self._make_sensor(MOCK_BLUETOOTH_STATUS).is_on is False

    def test_is_on_when_pairing_active(self):
        data = {**MOCK_BLUETOOTH_STATUS, "pairing_active": True}
        assert self._make_sensor(data).is_on is True

    def test_is_off_when_no_data(self):
        assert self._make_sensor(None).is_on is False


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestBinarySensorSetupEntry:

    @pytest.mark.asyncio
    async def test_connectivity_sensor_always_created(self):
        entry = _make_entry(bt_coordinator=None)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, ConnectionStatusSensor) for e in added)

    @pytest.mark.asyncio
    async def test_pairing_sensor_created_when_bt_coordinator_present(self):
        entry = _make_entry(bt_coordinator=_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothPairingActiveSensor) for e in added)

    @pytest.mark.asyncio
    async def test_no_pairing_sensor_when_bt_coordinator_absent(self):
        entry = _make_entry(bt_coordinator=None)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothPairingActiveSensor) for e in added)

    @pytest.mark.asyncio
    async def test_two_sensors_with_bt_coordinator(self):
        entry = _make_entry(bt_coordinator=_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 2
