"""Tests for Odio Remote binary_sensor platform."""
from unittest.mock import MagicMock

from homeassistant.helpers.entity import EntityCategory
from pyodio import PowerCapabilities, ServerInfo

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.binary_sensor import (
    ConnectionStatusSensor,
    OdioBluetoothPairingActiveSensor,
    async_setup_entry,
)

from .conftest import (
    MOCK_BLUETOOTH_STATUS,
    MOCK_DEVICE_INFO,
    MOCK_SERVER_INFO,
    make_hub,
    push_event,
    set_connected,
)

ENTRY_ID = "test_entry_id"


def _make_entry(hub, *, bluetooth=True):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {}
    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        server_info=ServerInfo.from_dict(
            {**MOCK_SERVER_INFO, "backends": {**MOCK_SERVER_INFO["backends"], "bluetooth": bluetooth}}
        ),
        service_mappings={},
        power_capabilities=PowerCapabilities(power_off=True, reboot=True),
    )
    return entry


# ---------------------------------------------------------------------------
# ConnectionStatusSensor
# ---------------------------------------------------------------------------

class TestConnectionStatusSensor:

    def _make_sensor(self, connected=True):
        hub = make_hub(connected=connected)
        return ConnectionStatusSensor(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub

    def test_unique_id(self):
        assert self._make_sensor()[0].unique_id == f"{ENTRY_ID}_connectivity"

    def test_is_on_when_connected(self):
        assert self._make_sensor(connected=True)[0].is_on is True

    def test_is_off_when_disconnected(self):
        assert self._make_sensor(connected=False)[0].is_on is False

    def test_always_available_even_disconnected(self):
        assert self._make_sensor(connected=False)[0].available is True

    def test_entity_category_is_diagnostic(self):
        assert self._make_sensor()[0].entity_category == EntityCategory.DIAGNOSTIC

    async def test_connection_change_writes_state(self):
        sensor, hub = self._make_sensor()
        sensor.hass = MagicMock()
        sensor.async_on_remove = MagicMock()
        sensor.async_write_ha_state = MagicMock()
        await sensor.async_added_to_hass()

        set_connected(hub, False)

        sensor.async_write_ha_state.assert_called_once()
        assert sensor.is_on is False

    async def test_added_to_hass_registers_unsubscribe(self):
        sensor, _ = self._make_sensor()
        sensor.hass = MagicMock()
        sensor.async_on_remove = MagicMock()
        await sensor.async_added_to_hass()
        sensor.async_on_remove.assert_called()


# ---------------------------------------------------------------------------
# OdioBluetoothPairingActiveSensor — construction
# ---------------------------------------------------------------------------

def _make_pairing_sensor(status=None, connected=True):
    hub = make_hub(bluetooth=status, connected=connected)
    return OdioBluetoothPairingActiveSensor(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub


class TestOdioBluetoothPairingActiveSensorConstruction:

    def test_unique_id(self):
        assert _make_pairing_sensor()[0].unique_id == f"{ENTRY_ID}_bluetooth_pairing_active"

    def test_translation_key(self):
        assert _make_pairing_sensor()[0].translation_key == "bluetooth_pairing_active"

    def test_entity_category_is_diagnostic(self):
        assert _make_pairing_sensor()[0].entity_category == EntityCategory.DIAGNOSTIC

    def test_has_entity_name(self):
        assert _make_pairing_sensor()[0]._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in _make_pairing_sensor()[0].device_info["identifiers"]


# ---------------------------------------------------------------------------
# OdioBluetoothPairingActiveSensor — is_on
# ---------------------------------------------------------------------------

class TestOdioBluetoothPairingActiveSensorIsOn:

    def test_is_off_when_not_pairing(self):
        assert _make_pairing_sensor(MOCK_BLUETOOTH_STATUS)[0].is_on is False

    def test_is_on_when_pairing_active(self):
        status = {**MOCK_BLUETOOTH_STATUS, "pairing_active": True}
        assert _make_pairing_sensor(status)[0].is_on is True

    def test_is_off_when_no_data(self):
        assert _make_pairing_sensor(None)[0].is_on is False

    def test_unavailable_when_no_data(self):
        assert _make_pairing_sensor(None)[0].available is False

    async def test_bluetooth_event_writes_state(self):
        sensor, hub = _make_pairing_sensor(MOCK_BLUETOOTH_STATUS)
        sensor.hass = MagicMock()
        sensor.async_on_remove = MagicMock()
        sensor.async_write_ha_state = MagicMock()
        await sensor.async_added_to_hass()

        push_event(hub, "bluetooth.updated", {**MOCK_BLUETOOTH_STATUS, "pairing_active": True})

        sensor.async_write_ha_state.assert_called()
        assert sensor.is_on is True


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestBinarySensorSetupEntry:

    async def test_connectivity_sensor_always_created(self):
        entry = _make_entry(make_hub(), bluetooth=False)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, ConnectionStatusSensor) for e in added)

    async def test_pairing_sensor_created_when_bt_backend_enabled(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothPairingActiveSensor) for e in added)

    async def test_no_pairing_sensor_when_bt_backend_disabled(self):
        entry = _make_entry(make_hub(), bluetooth=False)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothPairingActiveSensor) for e in added)

    async def test_two_sensors_with_bt_backend(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 2
