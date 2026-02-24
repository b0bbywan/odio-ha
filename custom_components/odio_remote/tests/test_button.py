"""Tests for Odio Remote button platform."""
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.button import ButtonDeviceClass

from custom_components.odio_remote.button import (
    OdioPowerOffButton,
    OdioRebootButton,
    async_setup_entry,
)
from custom_components.odio_remote.const import DOMAIN

from .conftest import MOCK_DEVICE_INFO

ENTRY_ID = "test_entry_id"


def _make_connectivity_coordinator(last_update_success=True):
    coord = MagicMock()
    coord.last_update_success = last_update_success
    return coord


@dataclass
class MockPowerRuntimeData:
    api: object
    device_info: object
    power_capabilities: dict
    connectivity_coordinator: object


class MockConfigEntry:
    def __init__(self, caps, api=None):
        self.entry_id = ENTRY_ID
        self.runtime_data = MockPowerRuntimeData(
            api=api or MagicMock(),
            device_info=MOCK_DEVICE_INFO,
            power_capabilities=caps,
            connectivity_coordinator=_make_connectivity_coordinator(),
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

    def _make_button(self, api=None):
        return OdioPowerOffButton(
            _make_connectivity_coordinator(), api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO
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
        btn = OdioPowerOffButton(
            _make_connectivity_coordinator(last_update_success=True),
            MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO,
        )
        assert btn.available is True

    def test_unavailable_when_connectivity_down(self):
        btn = OdioPowerOffButton(
            _make_connectivity_coordinator(last_update_success=False),
            MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO,
        )
        assert btn.available is False


class TestOdioRebootButton:
    """Tests for OdioRebootButton."""

    def _make_button(self, api=None):
        return OdioRebootButton(
            _make_connectivity_coordinator(), api or MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO
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
        btn = OdioRebootButton(
            _make_connectivity_coordinator(last_update_success=True),
            MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO,
        )
        assert btn.available is True

    def test_unavailable_when_connectivity_down(self):
        btn = OdioRebootButton(
            _make_connectivity_coordinator(last_update_success=False),
            MagicMock(), ENTRY_ID, MOCK_DEVICE_INFO,
        )
        assert btn.available is False
