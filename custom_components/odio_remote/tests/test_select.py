"""Tests for Odio Remote select platform."""
from unittest.mock import MagicMock

from pyodio import PowerCapabilities, ServerInfo

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.select import (
    OdioBluetoothPairSelect,
    async_setup_entry,
)

from .conftest import (
    MOCK_BLUETOOTH_STATUS,
    MOCK_DEVICE_INFO,
    MOCK_SERVER_INFO,
    make_hub,
    push_event,
)

ENTRY_ID = "test_entry_id"


def _make_select(status=MOCK_BLUETOOTH_STATUS, connected=True):
    hub = make_hub(bluetooth=status, connected=connected)
    return OdioBluetoothPairSelect(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub


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
        assert _make_select()[0].unique_id == "test_entry_id_bluetooth_pair"

    def test_translation_key(self):
        assert _make_select()[0].translation_key == "bluetooth_pair"

    def test_current_option_is_none(self):
        assert _make_select(status=_DISCOVERED)[0].current_option is None


class TestOdioBluetoothPairSelectOptions:

    def test_options_list_only_unpaired_discovered(self):
        options = _make_select(status=_DISCOVERED)[0].options
        assert options == ["JBL Flip (11:22:33:44:55:66)", "77:88:99:AA:BB:CC"]

    def test_paired_devices_excluded(self):
        # The Pixel (paired/bonded) must not appear as a pairable option.
        options = _make_select(status=_DISCOVERED)[0].options
        assert not any("Pixel" in o for o in options)

    def test_empty_when_no_discovered(self):
        assert _make_select()[0].options == []

    def test_empty_when_no_state(self):
        assert _make_select(status=None)[0].options == []


class TestOdioBluetoothPairSelectAvailable:

    def test_available_when_discovered_present(self):
        assert _make_select(status=_DISCOVERED)[0].available is True

    def test_unavailable_when_no_discovered(self):
        assert _make_select()[0].available is False

    def test_unavailable_when_disconnected(self):
        assert _make_select(status=_DISCOVERED, connected=False)[0].available is False


class TestOdioBluetoothPairSelectActions:

    async def test_select_option_connects_named_device(self):
        select, hub = _make_select(status=_DISCOVERED)
        await select.async_select_option("JBL Flip (11:22:33:44:55:66)")
        hub.client.bluetooth_connect.assert_awaited_once_with("11:22:33:44:55:66")

    async def test_select_option_connects_unnamed_device(self):
        select, hub = _make_select(status=_DISCOVERED)
        await select.async_select_option("77:88:99:AA:BB:CC")
        hub.client.bluetooth_connect.assert_awaited_once_with("77:88:99:AA:BB:CC")

    async def test_select_matches_by_address_after_name_resolves(self):
        # Option rendered while the device was unnamed (label == bare address);
        # matching on the embedded address must still connect.
        select, hub = _make_select(status=_DISCOVERED)  # "11:22:..." is now "JBL Flip"
        await select.async_select_option("11:22:33:44:55:66")
        hub.client.bluetooth_connect.assert_awaited_once_with("11:22:33:44:55:66")

    async def test_select_unknown_option_noop(self):
        select, hub = _make_select(status=_DISCOVERED)
        await select.async_select_option("gone (00:00:00:00:00:00)")
        hub.client.bluetooth_connect.assert_not_called()


class TestOdioBluetoothPairSelectLifecycle:

    async def test_bluetooth_event_writes_state(self):
        select, hub = _make_select()
        select.hass = MagicMock()
        select.async_on_remove = MagicMock()
        select.async_write_ha_state = MagicMock()
        await select.async_added_to_hass()

        push_event(hub, "bluetooth.updated", _DISCOVERED)

        select.async_write_ha_state.assert_called()
        assert len(select.options) == 2


class TestSelectSetupEntry:

    async def test_creates_pair_select_when_bt_backend_enabled(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert isinstance(added[0], OdioBluetoothPairSelect)

    async def test_no_select_when_bt_backend_disabled(self):
        entry = _make_entry(make_hub(), bluetooth=False)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []
