"""Tests for Odio Remote sensor platform."""
from unittest.mock import MagicMock

from pyodio import PowerCapabilities, ServerInfo

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.sensor import (
    OdioBluetoothConnectedDeviceSensor,
    OdioDefaultOutputSensor,
    async_setup_entry,
)

from .conftest import (
    MOCK_BLUETOOTH_STATUS,
    MOCK_DEVICE_INFO,
    MOCK_OUTPUTS,
    MOCK_SERVER_INFO,
    make_hub,
)

ENTRY_ID = "test_entry_id"


def _make_output_sensor(outputs=None):
    audio = None if outputs is None else {"kind": "pipewire", "clients": [], "outputs": outputs}
    hub = make_hub(audio=audio)
    return OdioDefaultOutputSensor(hub, ENTRY_ID, MOCK_DEVICE_INFO)


def _make_bt_sensor(status=None):
    hub = make_hub(bluetooth=status)
    return OdioBluetoothConnectedDeviceSensor(hub, ENTRY_ID, MOCK_DEVICE_INFO)


def _make_entry(hub, *, pulseaudio=True, bluetooth=True):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {}
    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        server_info=ServerInfo.from_dict({
            **MOCK_SERVER_INFO,
            "backends": {**MOCK_SERVER_INFO["backends"], "pulseaudio": pulseaudio, "bluetooth": bluetooth},
        }),
        service_mappings={},
        power_capabilities=PowerCapabilities(power_off=True, reboot=True),
    )
    return entry


# ---------------------------------------------------------------------------
# OdioDefaultOutputSensor — construction
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
        # id=78 is the default output in MOCK_OUTPUTS
        assert _make_output_sensor(MOCK_OUTPUTS).native_value == "Audio interne Stéréo on pi@rasponkyold"

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "description": "Sink", "default": False}]
        assert _make_output_sensor(outputs).native_value is None

    def test_returns_none_when_outputs_empty(self):
        assert _make_output_sensor([]).native_value is None

    def test_returns_none_when_no_data(self):
        assert _make_output_sensor(None).native_value is None

    def test_falls_back_to_name_when_no_description(self):
        outputs = [{"id": 1, "name": "alsa_output.stereo", "default": True}]
        assert _make_output_sensor(outputs).native_value == "alsa_output.stereo"

    def test_returns_first_default_when_multiple(self):
        outputs = [
            {"id": 1, "name": "a", "description": "First Default", "default": True},
            {"id": 2, "name": "b", "description": "Second Default", "default": True},
        ]
        assert _make_output_sensor(outputs).native_value == "First Default"


# ---------------------------------------------------------------------------
# OdioDefaultOutputSensor — extra_state_attributes
# ---------------------------------------------------------------------------

class TestOdioDefaultOutputSensorAttributes:

    def test_returns_output_attributes(self):
        attrs = _make_output_sensor(MOCK_OUTPUTS).extra_state_attributes
        assert attrs["id"] == 78
        assert attrs["name"] == "tunnel.rasponkyold.local.alsa_output.platform-2000b840.mailbox.stereo-fallback"
        assert attrs["description"] == "Audio interne Stéréo on pi@rasponkyold"
        assert attrs["muted"] is False
        assert attrs["volume"] == 1
        assert attrs["state"] == "suspended"
        assert attrs["driver"] == "PipeWire"
        assert attrs["is_network"] is True

    def test_excludes_default_and_props(self):
        attrs = _make_output_sensor(MOCK_OUTPUTS).extra_state_attributes
        assert "default" not in attrs
        assert "props" not in attrs

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "default": False}]
        assert _make_output_sensor(outputs).extra_state_attributes is None

    def test_returns_none_when_no_data(self):
        assert _make_output_sensor(None).extra_state_attributes is None


# ---------------------------------------------------------------------------
# OdioBluetoothConnectedDeviceSensor — construction
# ---------------------------------------------------------------------------

class TestOdioBluetoothConnectedDeviceSensorConstruction:

    def test_unique_id(self):
        assert _make_bt_sensor().unique_id == f"{ENTRY_ID}_bluetooth_connected_device"

    def test_translation_key(self):
        assert _make_bt_sensor().translation_key == "bluetooth_connected_device"

    def test_has_entity_name(self):
        assert _make_bt_sensor()._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in _make_bt_sensor().device_info["identifiers"]


# ---------------------------------------------------------------------------
# OdioBluetoothConnectedDeviceSensor — native_value
# ---------------------------------------------------------------------------

class TestOdioBluetoothConnectedDeviceSensorValue:

    def test_returns_connected_device_name(self):
        assert _make_bt_sensor(MOCK_BLUETOOTH_STATUS).native_value == "Pixel 6a"

    def test_returns_none_when_no_connected_device(self):
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Old Device", "trusted": True, "connected": False}
        ]}
        assert _make_bt_sensor(status).native_value == "none"

    def test_returns_none_when_known_devices_empty(self):
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": []}
        assert _make_bt_sensor(status).native_value == "none"

    def test_returns_none_when_no_data(self):
        assert _make_bt_sensor(None).native_value == "none"

    def test_returns_first_connected_when_multiple(self):
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Device A", "trusted": True, "connected": False},
            {"address": "11:22:33:44:55:66", "name": "Device B", "trusted": True, "connected": True},
            {"address": "77:88:99:AA:BB:CC", "name": "Device C", "trusted": True, "connected": True},
        ]}
        assert _make_bt_sensor(status).native_value == "Device B"


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestSensorSetupEntry:

    async def test_bt_sensor_created_when_bt_backend_enabled(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS), pulseaudio=False)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothConnectedDeviceSensor) for e in added)

    async def test_output_sensor_created_when_pulseaudio_backend_enabled(self):
        entry = _make_entry(make_hub(), bluetooth=False)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioDefaultOutputSensor) for e in added)

    async def test_both_sensors_created_when_both_backends_enabled(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 2
        assert {type(e) for e in added} == {OdioDefaultOutputSensor, OdioBluetoothConnectedDeviceSensor}

    async def test_no_sensor_when_backends_disabled(self):
        entry = _make_entry(make_hub(), pulseaudio=False, bluetooth=False)
        add_entities = MagicMock()
        await async_setup_entry(MagicMock(), entry, add_entities)
        add_entities.assert_not_called()
