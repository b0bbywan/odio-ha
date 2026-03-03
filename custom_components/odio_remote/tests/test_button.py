"""Tests for Odio Remote button platform."""
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.button import ButtonDeviceClass

from custom_components.odio_remote.button import (
    OdioBluetoothPairingButton,
    OdioPowerOffButton,
    OdioRebootButton,
    async_setup_entry,
)
from custom_components.odio_remote.const import DOMAIN

from .conftest import MOCK_DEVICE_INFO

ENTRY_ID = "test_entry_id"


def _make_event_stream(sse_connected=True):
    stream = MagicMock()
    stream.sse_connected = sse_connected
    return stream


@dataclass
class MockPowerRuntimeData:
    api: object
    device_info: object
    power_capabilities: dict
    event_stream: object
    bluetooth_coordinator: object = None


class MockConfigEntry:
    def __init__(self, caps, api=None):
        self.entry_id = ENTRY_ID
        self.runtime_data = MockPowerRuntimeData(
            api=api or MagicMock(),
            device_info=MOCK_DEVICE_INFO,
            power_capabilities=caps,
            event_stream=_make_event_stream(),
        )


class TestButtonSetup:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_no_buttons_when_power_backend_disabled(self):
        entry = MockConfigEntry(caps={})
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert added == []

    @pytest.mark.asyncio
    async def test_power_off_button_created(self):
        entry = MockConfigEntry(caps={"power_off": True, "reboot": False})
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioPowerOffButton)

    @pytest.mark.asyncio
    async def test_reboot_button_created(self):
        entry = MockConfigEntry(caps={"reboot": True, "power_off": False})
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioRebootButton)

    @pytest.mark.asyncio
    async def test_both_buttons_created(self):
        entry = MockConfigEntry(caps={"power_off": True, "reboot": True})
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert len(added) == 2
        assert {type(e) for e in added} == {OdioPowerOffButton, OdioRebootButton}


class TestOdioPowerOffButton:
    """Tests for OdioPowerOffButton."""

    def _make_button(self, api=None, sse_connected=True):
        return OdioPowerOffButton(
            _make_event_stream(sse_connected), api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO
        )

    @pytest.mark.asyncio
    async def test_press_calls_api(self):
        api = MagicMock()
        api.power_off = AsyncMock()
        await self._make_button(api).async_press()
        api.power_off.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button().unique_id == f"{ENTRY_ID}_power_off"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button().device_info["identifiers"]

    def test_translation_key(self):
        assert self._make_button().translation_key == "power_off"

    def test_device_class_is_none(self):
        assert self._make_button().device_class is None

    def test_available_when_connectivity_up(self):
        assert self._make_button(sse_connected=True).available is True

    def test_unavailable_when_connectivity_down(self):
        assert self._make_button(sse_connected=False).available is False


class TestOdioRebootButton:
    """Tests for OdioRebootButton."""

    def _make_button(self, api=None, sse_connected=True):
        return OdioRebootButton(
            _make_event_stream(sse_connected), api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO
        )

    @pytest.mark.asyncio
    async def test_press_calls_api(self):
        api = MagicMock()
        api.reboot = AsyncMock()
        await self._make_button(api).async_press()
        api.reboot.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button().unique_id == f"{ENTRY_ID}_reboot"

    def test_device_info_matches_receiver(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button().device_info["identifiers"]

    def test_device_class_is_restart(self):
        assert self._make_button().device_class == ButtonDeviceClass.RESTART

    def test_translation_key(self):
        assert self._make_button().translation_key == "reboot"

    def test_available_when_connectivity_up(self):
        assert self._make_button(sse_connected=True).available is True

    def test_unavailable_when_connectivity_down(self):
        assert self._make_button(sse_connected=False).available is False


class TestOdioBluetoothPairingButton:
    """Tests for OdioBluetoothPairingButton."""

    def _make_button(self, api=None, sse_connected=True):
        return OdioBluetoothPairingButton(
            _make_event_stream(sse_connected), api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO
        )

    @pytest.mark.asyncio
    async def test_press_calls_pairing_mode(self):
        api = MagicMock()
        api.bluetooth_pairing_mode = AsyncMock()
        await self._make_button(api).async_press()
        api.bluetooth_pairing_mode.assert_awaited_once()

    def test_unique_id(self):
        assert self._make_button().unique_id == f"{ENTRY_ID}_bluetooth_pairing"

    def test_translation_key(self):
        assert self._make_button().translation_key == "bluetooth_pairing"

    def test_device_class_is_none(self):
        assert self._make_button().device_class is None

    def test_device_info_set(self):
        assert (DOMAIN, ENTRY_ID) in self._make_button().device_info["identifiers"]

    def test_available_when_connectivity_up(self):
        assert self._make_button(sse_connected=True).available is True

    def test_unavailable_when_connectivity_down(self):
        assert self._make_button(sse_connected=False).available is False


class TestButtonSetupWithBluetooth:
    """Tests async_setup_entry pairing button creation."""

    def _make_entry(self, caps, bt_coordinator=None):
        entry = MockConfigEntry(caps=caps)
        entry.runtime_data.bluetooth_coordinator = bt_coordinator
        return entry

    @pytest.mark.asyncio
    async def test_pairing_button_created_when_bt_coordinator_present(self):
        entry = self._make_entry(caps={}, bt_coordinator=MagicMock())
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioBluetoothPairingButton)

    @pytest.mark.asyncio
    async def test_no_pairing_button_when_bt_coordinator_absent(self):
        entry = self._make_entry(caps={}, bt_coordinator=None)
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothPairingButton) for e in added)

    @pytest.mark.asyncio
    async def test_all_three_buttons_with_full_caps_and_bt(self):
        entry = self._make_entry(caps={"power_off": True, "reboot": True}, bt_coordinator=MagicMock())
        added = []
        await async_setup_entry(None, entry, lambda entities: added.extend(entities))
        assert len(added) == 3
        assert {type(e) for e in added} == {OdioPowerOffButton, OdioRebootButton, OdioBluetoothPairingButton}
