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

from .conftest import MOCK_SERVER_INFO

ENTRY_ID = "test_entry_id"


@dataclass
class MockPowerRuntimeData:
    api: object
    server_info: dict
    power_capabilities: dict


class MockConfigEntry:
    def __init__(self, caps, api=None):
        self.entry_id = ENTRY_ID
        self.runtime_data = MockPowerRuntimeData(
            api=api or MagicMock(),
            server_info=MOCK_SERVER_INFO,
            power_capabilities=caps,
        )


class TestButtonSetup:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_no_buttons_when_power_backend_disabled(self):
        """No entities created when power_capabilities is empty."""
        entry = MockConfigEntry(caps={})
        added = []

        await async_setup_entry(None, entry, lambda entities: added.extend(entities))

        assert added == []

    @pytest.mark.asyncio
    async def test_power_off_button_created(self):
        """Only power-off button created when power_off cap is True."""
        entry = MockConfigEntry(caps={"power_off": True, "reboot": False})
        added = []

        await async_setup_entry(None, entry, lambda entities: added.extend(entities))

        assert len(added) == 1
        assert isinstance(added[0], OdioPowerOffButton)

    @pytest.mark.asyncio
    async def test_reboot_button_created(self):
        """Only reboot button created when reboot cap is True."""
        entry = MockConfigEntry(caps={"reboot": True, "power_off": False})
        added = []

        await async_setup_entry(None, entry, lambda entities: added.extend(entities))

        assert len(added) == 1
        assert isinstance(added[0], OdioRebootButton)

    @pytest.mark.asyncio
    async def test_both_buttons_created(self):
        """Both buttons created when both caps are True."""
        entry = MockConfigEntry(caps={"power_off": True, "reboot": True})
        added = []

        await async_setup_entry(None, entry, lambda entities: added.extend(entities))

        assert len(added) == 2
        types = {type(e) for e in added}
        assert types == {OdioPowerOffButton, OdioRebootButton}


class TestOdioPowerOffButton:
    """Tests for OdioPowerOffButton."""

    def _make_button(self, api=None):
        return OdioPowerOffButton(api or MagicMock(), ENTRY_ID, MOCK_SERVER_INFO)

    @pytest.mark.asyncio
    async def test_press_calls_api(self):
        """async_press calls api.power_off()."""
        api = MagicMock()
        api.power_off = AsyncMock()
        btn = self._make_button(api)

        await btn.async_press()

        api.power_off.assert_awaited_once()

    def test_unique_id(self):
        """unique_id is {entry_id}_power_off."""
        btn = self._make_button()
        assert btn.unique_id == f"{ENTRY_ID}_power_off"

    def test_device_info_matches_receiver(self):
        """device_info identifiers match the receiver device."""
        btn = self._make_button()
        assert (DOMAIN, ENTRY_ID) in btn.device_info["identifiers"]

    def test_translation_key(self):
        btn = self._make_button()
        assert btn.translation_key == "power_off"

    def test_device_class_is_none(self):
        btn = self._make_button()
        assert btn.device_class is None


class TestOdioRebootButton:
    """Tests for OdioRebootButton."""

    def _make_button(self, api=None):
        return OdioRebootButton(api or MagicMock(), ENTRY_ID, MOCK_SERVER_INFO)

    @pytest.mark.asyncio
    async def test_press_calls_api(self):
        """async_press calls api.reboot()."""
        api = MagicMock()
        api.reboot = AsyncMock()
        btn = self._make_button(api)

        await btn.async_press()

        api.reboot.assert_awaited_once()

    def test_unique_id(self):
        """unique_id is {entry_id}_reboot."""
        btn = self._make_button()
        assert btn.unique_id == f"{ENTRY_ID}_reboot"

    def test_device_info_matches_receiver(self):
        """device_info identifiers match the receiver device."""
        btn = self._make_button()
        assert (DOMAIN, ENTRY_ID) in btn.device_info["identifiers"]

    def test_device_class_is_restart(self):
        btn = self._make_button()
        assert btn.device_class == ButtonDeviceClass.RESTART

    def test_translation_key(self):
        btn = self._make_button()
        assert btn.translation_key == "reboot"
