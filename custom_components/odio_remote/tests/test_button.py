"""Tests for Odio Remote button platform."""
from unittest.mock import MagicMock

from homeassistant.components.button import ButtonDeviceClass
from pyodio import PowerCapabilities, ServerInfo

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.button import (
    OdioBluetoothPairingButton,
    OdioPowerOffButton,
    OdioRebootButton,
    async_setup_entry,
)
from custom_components.odio_remote.const import DOMAIN

from .conftest import MOCK_DEVICE_INFO, MOCK_SERVER_INFO, make_hub

ENTRY_ID = "test_entry_id"


def _make_entry(caps, *, bluetooth=False, hub=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = {}
    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub or make_hub(),
        device_info=MOCK_DEVICE_INFO,
        server_info=ServerInfo.from_dict(
            {**MOCK_SERVER_INFO, "backends": {**MOCK_SERVER_INFO["backends"], "bluetooth": bluetooth}}
        ),
        service_mappings={},
        power_capabilities=caps,
    )
    return entry


async def _setup(entry):
    added = []
    await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return added


class TestButtonSetup:
    """Tests for async_setup_entry."""

    async def test_no_buttons_when_power_backend_disabled(self):
        assert await _setup(_make_entry(PowerCapabilities())) == []

    async def test_power_off_button_created(self):
        added = await _setup(_make_entry(PowerCapabilities(power_off=True, reboot=False)))
        assert len(added) == 1
        assert isinstance(added[0], OdioPowerOffButton)

    async def test_reboot_button_created(self):
        added = await _setup(_make_entry(PowerCapabilities(reboot=True, power_off=False)))
        assert len(added) == 1
        assert isinstance(added[0], OdioRebootButton)

    async def test_both_buttons_created(self):
        added = await _setup(_make_entry(PowerCapabilities(power_off=True, reboot=True)))
        assert len(added) == 2
        assert {type(e) for e in added} == {OdioPowerOffButton, OdioRebootButton}


class TestOdioPowerOffButton:
    """Tests for OdioPowerOffButton."""

    def _make_button(self, connected=True):
        hub = make_hub(connected=connected)
        return OdioPowerOffButton(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub

    async def test_press_calls_power_off(self):
        button, hub = self._make_button()
        await button.async_press()
        hub.client.power_off.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button()[0].unique_id == f"{ENTRY_ID}_power_off"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button()[0].device_info["identifiers"]

    def test_translation_key(self):
        assert self._make_button()[0].translation_key == "power_off"

    def test_device_class_is_none(self):
        assert self._make_button()[0].device_class is None

    def test_available_when_connected(self):
        assert self._make_button(connected=True)[0].available is True

    def test_unavailable_when_disconnected(self):
        assert self._make_button(connected=False)[0].available is False


class TestOdioRebootButton:
    """Tests for OdioRebootButton."""

    def _make_button(self, connected=True):
        hub = make_hub(connected=connected)
        return OdioRebootButton(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub

    async def test_press_calls_reboot(self):
        button, hub = self._make_button()
        await button.async_press()
        hub.client.reboot.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button()[0].unique_id == f"{ENTRY_ID}_reboot"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button()[0].device_info["identifiers"]

    def test_device_class_is_restart(self):
        assert self._make_button()[0].device_class == ButtonDeviceClass.RESTART

    def test_translation_key(self):
        assert self._make_button()[0].translation_key == "reboot"

    def test_available_when_connected(self):
        assert self._make_button(connected=True)[0].available is True

    def test_unavailable_when_disconnected(self):
        assert self._make_button(connected=False)[0].available is False


class TestOdioBluetoothPairingButton:
    """Tests for OdioBluetoothPairingButton."""

    def _make_button(self, connected=True):
        hub = make_hub(connected=connected)
        return OdioBluetoothPairingButton(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub

    async def test_press_calls_pairing_mode(self):
        button, hub = self._make_button()
        await button.async_press()
        hub.client.bluetooth_pairing_mode.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button()[0].unique_id == f"{ENTRY_ID}_bluetooth_pairing"

    def test_translation_key(self):
        assert self._make_button()[0].translation_key == "bluetooth_pairing"

    def test_device_class_is_none(self):
        assert self._make_button()[0].device_class is None

    def test_device_info_set(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button()[0].device_info["identifiers"]

    def test_available_when_connected(self):
        assert self._make_button(connected=True)[0].available is True

    def test_unavailable_when_disconnected(self):
        assert self._make_button(connected=False)[0].available is False


class TestButtonSetupWithBluetooth:
    """Tests async_setup_entry pairing button creation."""

    async def test_pairing_button_created_when_bt_backend_enabled(self):
        added = await _setup(_make_entry(PowerCapabilities(), bluetooth=True))
        assert len(added) == 1
        assert isinstance(added[0], OdioBluetoothPairingButton)

    async def test_no_pairing_button_when_bt_backend_disabled(self):
        added = await _setup(_make_entry(PowerCapabilities(), bluetooth=False))
        assert not any(isinstance(e, OdioBluetoothPairingButton) for e in added)

    async def test_all_three_buttons_with_full_caps_and_bt(self):
        added = await _setup(_make_entry(PowerCapabilities(power_off=True, reboot=True), bluetooth=True))
        assert len(added) == 3
        assert {type(e) for e in added} == {OdioPowerOffButton, OdioRebootButton, OdioBluetoothPairingButton}
