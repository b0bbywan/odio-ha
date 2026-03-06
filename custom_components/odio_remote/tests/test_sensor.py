"""Tests for Odio Remote sensor platform."""
import pytest
from unittest.mock import MagicMock

from custom_components.odio_remote.sensor import (
    OdioBluetoothConnectedDeviceSensor,
    OdioDefaultOutputSensor,
    async_setup_entry,
)

from .conftest import MOCK_BLUETOOTH_STATUS, MOCK_DEVICE_INFO, MOCK_OUTPUTS

ENTRY_ID = "test_entry_id"


def _make_coordinator(data=None):
    coord = MagicMock()
    coord.data = data
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_bt_coordinator(data=None):
    return _make_coordinator(data)


def _make_sensor(data=None):
    return OdioBluetoothConnectedDeviceSensor(
        _make_bt_coordinator(data), ENTRY_ID, MOCK_DEVICE_INFO
    )


def _make_output_sensor(data=None):
    return OdioDefaultOutputSensor(
        _make_coordinator(data), ENTRY_ID, MOCK_DEVICE_INFO
    )


def _make_entry(bt_coordinator=None, audio_coordinator=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.bluetooth_coordinator = bt_coordinator
    entry.runtime_data.audio_coordinator = audio_coordinator
    return entry


# ---------------------------------------------------------------------------
# OdioDefaultOutputSensor — Construction
# ---------------------------------------------------------------------------

class TestOdioDefaultOutputSensorConstruction:

    def test_unique_id(self):
        assert _make_output_sensor().unique_id == f"{ENTRY_ID}_default_output"

    def test_translation_key(self):
        assert _make_output_sensor().translation_key == "default_output"

    def test_has_entity_name(self):
        assert _make_output_sensor()._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in _make_output_sensor().device_info["identifiers"]


# ---------------------------------------------------------------------------
# OdioDefaultOutputSensor — native_value
# ---------------------------------------------------------------------------

class TestOdioDefaultOutputSensorValue:

    def test_returns_default_output_description(self):
        data = {"audio": [], "outputs": MOCK_OUTPUTS}
        assert _make_output_sensor(data).native_value == "Audio interne Stéréo on pi@rasponkyold"  # id=78, default=True

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "description": "Sink", "default": False}]
        data = {"audio": [], "outputs": outputs}
        assert _make_output_sensor(data).native_value is None

    def test_returns_none_when_outputs_empty(self):
        data = {"audio": [], "outputs": []}
        assert _make_output_sensor(data).native_value is None

    def test_returns_none_when_no_data(self):
        assert _make_output_sensor(None).native_value is None

    def test_falls_back_to_name_when_no_description(self):
        outputs = [{"id": 1, "name": "alsa_output.stereo", "default": True}]
        data = {"audio": [], "outputs": outputs}
        assert _make_output_sensor(data).native_value == "alsa_output.stereo"

    def test_returns_first_default_when_multiple(self):
        outputs = [
            {"id": 1, "name": "a", "description": "First Default", "default": True},
            {"id": 2, "name": "b", "description": "Second Default", "default": True},
        ]
        data = {"audio": [], "outputs": outputs}
        assert _make_output_sensor(data).native_value == "First Default"


# ---------------------------------------------------------------------------
# OdioDefaultOutputSensor — extra_state_attributes
# ---------------------------------------------------------------------------

class TestOdioDefaultOutputSensorAttributes:

    def test_returns_output_attributes(self):
        data = {"audio": [], "outputs": MOCK_OUTPUTS}
        attrs = _make_output_sensor(data).extra_state_attributes
        assert attrs["id"] == 78
        assert attrs["name"] == "tunnel.rasponkyold.local.alsa_output.platform-2000b840.mailbox.stereo-fallback"
        assert attrs["description"] == "Audio interne Stéréo on pi@rasponkyold"
        assert attrs["muted"] is False
        assert attrs["volume"] == 1
        assert attrs["state"] == "suspended"
        assert attrs["driver"] == "PipeWire"
        assert attrs["is_network"] is True

    def test_excludes_default_and_props(self):
        data = {"audio": [], "outputs": MOCK_OUTPUTS}
        attrs = _make_output_sensor(data).extra_state_attributes
        assert "default" not in attrs
        assert "props" not in attrs

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "default": False}]
        data = {"audio": [], "outputs": outputs}
        assert _make_output_sensor(data).extra_state_attributes is None

    def test_returns_none_when_no_data(self):
        assert _make_output_sensor(None).extra_state_attributes is None


# ---------------------------------------------------------------------------
# OdioBluetoothConnectedDeviceSensor — Construction
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
    async def test_bt_sensor_created_when_bt_coordinator_present(self):
        entry = _make_entry(bt_coordinator=_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothConnectedDeviceSensor) for e in added)

    @pytest.mark.asyncio
    async def test_output_sensor_created_when_audio_coordinator_present(self):
        entry = _make_entry(audio_coordinator=_make_coordinator({"audio": [], "outputs": MOCK_OUTPUTS}))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioDefaultOutputSensor) for e in added)

    @pytest.mark.asyncio
    async def test_both_sensors_created_when_both_coordinators_present(self):
        entry = _make_entry(
            bt_coordinator=_make_bt_coordinator(MOCK_BLUETOOTH_STATUS),
            audio_coordinator=_make_coordinator({"audio": [], "outputs": MOCK_OUTPUTS}),
        )
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 2
        types = {type(e) for e in added}
        assert OdioDefaultOutputSensor in types
        assert OdioBluetoothConnectedDeviceSensor in types

    @pytest.mark.asyncio
    async def test_no_sensor_when_no_coordinator(self):
        entry = _make_entry(bt_coordinator=None, audio_coordinator=None)
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_not_called()
