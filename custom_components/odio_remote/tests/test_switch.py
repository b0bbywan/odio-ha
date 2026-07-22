"""Tests for Odio Remote switch platform."""
from unittest.mock import MagicMock

from pyodio import PowerCapabilities, ServerInfo, ServiceState

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.switch import (
    OdioBluetoothDeviceSwitch,
    OdioBluetoothScanSwitch,
    OdioBluetoothSwitch,
    OdioServiceSwitch,
    async_setup_entry,
)

from .conftest import (
    MOCK_ALL_SERVICES,
    MOCK_BLUETOOTH_STATUS,
    MOCK_DEVICE_INFO,
    MOCK_SERVER_INFO,
    MOCK_SERVICES,
    make_hub,
    push_event,
    set_connected,
)

ENTRY_ID = "test_entry_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backends(**overrides):
    return {**MOCK_SERVER_INFO, "backends": {**MOCK_SERVER_INFO["backends"], **overrides}}


def _make_entry(hub, *, server_info=None, data=None):
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = data or {}
    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        server_info=ServerInfo.from_dict(server_info or MOCK_SERVER_INFO),
        service_mappings={},
        power_capabilities=PowerCapabilities(power_off=True, reboot=True),
    )
    return entry


def _make_switch(svc_dict, hub=None):
    if hub is None:
        hub = make_hub(services=MOCK_SERVICES)
    return OdioServiceSwitch(hub, ENTRY_ID, MOCK_DEVICE_INFO, ServiceState.from_dict(svc_dict))


async def _setup(entry):
    added = []
    await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return added


# ---------------------------------------------------------------------------
# OdioServiceSwitch — construction
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchConstruction:

    def test_unique_id(self):
        assert _make_switch(MOCK_SERVICES[0]).unique_id == "test_entry_id_switch_user_mpd.service"

    def test_name_strips_service_suffix(self):
        assert _make_switch(MOCK_SERVICES[0]).name == "mpd"

    def test_name_without_service_suffix_unchanged(self):
        svc = {"name": "kodi", "scope": "user", "exists": True, "running": False}
        assert _make_switch(svc).name == "kodi"

    def test_has_entity_name(self):
        assert _make_switch(MOCK_SERVICES[0])._attr_has_entity_name is True

    def test_device_info_uses_hostname(self):
        assert "htpc" in str(_make_switch(MOCK_SERVICES[0]).device_info)


# ---------------------------------------------------------------------------
# OdioServiceSwitch — is_on
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchIsOn:

    def test_is_on_when_running(self):
        assert _make_switch(MOCK_SERVICES[0]).is_on is True

    def test_is_off_when_stopped(self):
        assert _make_switch(MOCK_SERVICES[1]).is_on is False

    def test_is_off_when_service_not_in_hub(self):
        svc = {"name": "unknown.service", "scope": "user", "exists": True, "running": True}
        assert _make_switch(svc).is_on is False

    def test_is_off_when_hub_has_no_services(self):
        entity = _make_switch(MOCK_SERVICES[0], hub=make_hub(services=None))
        assert entity.is_on is False

    def test_is_on_matches_scope(self):
        user_svc = {"name": "mpd.service", "scope": "user", "exists": True, "running": True}
        system_svc = {"name": "mpd.service", "scope": "system", "exists": True, "running": False}
        entity = _make_switch(user_svc, hub=make_hub(services=[system_svc]))
        assert entity.is_on is False


# ---------------------------------------------------------------------------
# OdioServiceSwitch — lifecycle
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchLifecycle:

    async def test_relevant_service_event_writes_state(self):
        hub = make_hub(services=MOCK_SERVICES)
        entity = _make_switch(MOCK_SERVICES[0], hub=hub)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()

        push_event(hub, "service.updated", {**MOCK_SERVICES[0], "running": False})

        entity.async_write_ha_state.assert_called_once()
        assert entity.is_on is False

    async def test_unrelated_service_event_ignored(self):
        hub = make_hub(services=MOCK_SERVICES)
        entity = _make_switch(MOCK_SERVICES[0], hub=hub)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()

        push_event(hub, "service.updated", MOCK_SERVICES[1])

        entity.async_write_ha_state.assert_not_called()

    async def test_connection_change_writes_state(self):
        hub = make_hub(services=MOCK_SERVICES)
        entity = _make_switch(MOCK_SERVICES[0], hub=hub)
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()

        set_connected(hub, False)

        entity.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# OdioServiceSwitch — available
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchAvailable:

    def test_available_when_connected_and_known(self):
        assert _make_switch(MOCK_SERVICES[0]).available is True

    def test_unavailable_when_disconnected(self):
        hub = make_hub(services=MOCK_SERVICES, connected=False)
        assert _make_switch(MOCK_SERVICES[0], hub=hub).available is False

    def test_unavailable_when_service_missing_from_hub(self):
        assert _make_switch(MOCK_SERVICES[0], hub=make_hub(services=None)).available is False


# ---------------------------------------------------------------------------
# OdioServiceSwitch — actions
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchActions:

    async def test_turn_on_calls_start(self):
        hub = make_hub(services=MOCK_SERVICES)
        entity = _make_switch(MOCK_SERVICES[1], hub=hub)
        await entity.async_turn_on()
        hub.client.service_start.assert_awaited_once_with("user", "shairport-sync.service")

    async def test_turn_off_calls_stop(self):
        hub = make_hub(services=MOCK_SERVICES)
        entity = _make_switch(MOCK_SERVICES[0], hub=hub)
        await entity.async_turn_off()
        hub.client.service_stop.assert_awaited_once_with("user", "mpd.service")


# ---------------------------------------------------------------------------
# async_setup_entry — service switches
# ---------------------------------------------------------------------------

class TestOdioSwitchSetupEntry:

    async def test_creates_user_scope_entities(self):
        entry = _make_entry(make_hub(services=MOCK_ALL_SERVICES), server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        assert len(added) == 5
        assert all(isinstance(e, OdioServiceSwitch) for e in added)

    async def test_filters_system_scope(self):
        entry = _make_entry(make_hub(services=MOCK_ALL_SERVICES), server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        assert not any("bluetooth.service" in e.service_key for e in added)

    async def test_filters_non_existing_services(self):
        services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "running": False},
            {"name": "ghost.service", "scope": "user", "exists": False, "running": False},
        ]
        entry = _make_entry(make_hub(services=services), server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        assert [e.service_key for e in added] == ["user/mpd.service"]

    async def test_cached_services_fallback_when_hub_empty(self):
        entry = _make_entry(
            make_hub(services=None),
            server_info=_backends(bluetooth=False),
            data={"cached_services": MOCK_SERVICES},
        )
        added = await _setup(entry)
        assert len(added) == len(MOCK_SERVICES)

    async def test_no_service_switches_without_systemd_backend(self):
        entry = _make_entry(make_hub(services=MOCK_SERVICES), server_info=_backends(systemd=False, bluetooth=False))
        assert await _setup(entry) == []

    async def test_dynamic_adds_new_services(self):
        """New services pushed after an API-down startup create switches."""
        hub = make_hub(services=None)
        entry = _make_entry(hub, server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        assert added == []

        push_event(hub, "service.updated", MOCK_SERVICES)

        assert len(added) == len([s for s in MOCK_SERVICES if s["exists"] and s["scope"] == "user"])

    async def test_dynamic_skips_already_known_keys(self):
        hub = make_hub(services=MOCK_SERVICES)
        entry = _make_entry(hub, server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        initial_count = len(added)

        push_event(hub, "service.updated", MOCK_SERVICES[0])

        assert len(added) == initial_count  # no duplicates

    async def test_dynamic_skips_non_user_or_missing_services(self):
        hub = make_hub(services=None)
        entry = _make_entry(hub, server_info=_backends(bluetooth=False))
        added = await _setup(entry)

        push_event(hub, "service.updated", [
            {"name": "system.service", "scope": "system", "exists": True},
            {"name": "ghost.service", "scope": "user", "exists": False},
        ])

        assert added == []

    async def test_entity_names_strip_service_suffix(self):
        entry = _make_entry(make_hub(services=MOCK_SERVICES), server_info=_backends(bluetooth=False))
        added = await _setup(entry)
        assert {e.name for e in added} == {"mpd", "shairport-sync", "snapclient"}


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch
# ---------------------------------------------------------------------------

def _make_bt_switch(status=MOCK_BLUETOOTH_STATUS, connected=True, hub=None):
    if hub is None:
        hub = make_hub(bluetooth=status, connected=connected)
    return OdioBluetoothSwitch(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub


class TestOdioBluetoothSwitchConstruction:

    def test_unique_id(self):
        assert _make_bt_switch()[0].unique_id == "test_entry_id_bluetooth_power"

    def test_translation_key(self):
        assert _make_bt_switch()[0].translation_key == "bluetooth_power"

    def test_has_entity_name(self):
        assert _make_bt_switch()[0]._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, ENTRY_ID) in _make_bt_switch()[0].device_info["identifiers"]


class TestOdioBluetoothSwitchIcon:

    def test_icon_when_on(self):
        assert _make_bt_switch()[0].icon == "mdi:bluetooth"

    def test_icon_when_off(self):
        switch, _ = _make_bt_switch({**MOCK_BLUETOOTH_STATUS, "powered": False})
        assert switch.icon == "mdi:bluetooth-off"


class TestOdioBluetoothSwitchIsOn:

    def test_is_on_when_powered(self):
        assert _make_bt_switch()[0].is_on is True

    def test_is_off_when_not_powered(self):
        switch, _ = _make_bt_switch({**MOCK_BLUETOOTH_STATUS, "powered": False})
        assert switch.is_on is False

    def test_is_off_when_no_state(self):
        assert _make_bt_switch(status=None)[0].is_on is False


class TestOdioBluetoothSwitchAvailable:

    def test_available_when_all_ok(self):
        assert _make_bt_switch()[0].available is True

    def test_unavailable_when_disconnected(self):
        assert _make_bt_switch(connected=False)[0].available is False

    def test_unavailable_when_no_state(self):
        assert _make_bt_switch(status=None)[0].available is False


class TestOdioBluetoothSwitchActions:

    async def test_turn_on_calls_power_up(self):
        switch, hub = _make_bt_switch()
        await switch.async_turn_on()
        hub.client.bluetooth_power_up.assert_awaited_once()

    async def test_turn_off_calls_power_down(self):
        switch, hub = _make_bt_switch()
        await switch.async_turn_off()
        hub.client.bluetooth_power_down.assert_awaited_once()


class TestOdioBluetoothSwitchLifecycle:

    async def test_bluetooth_event_writes_state(self):
        switch, hub = _make_bt_switch()
        switch.hass = MagicMock()
        switch.async_on_remove = MagicMock()
        switch.async_write_ha_state = MagicMock()
        await switch.async_added_to_hass()

        push_event(hub, "bluetooth.updated", {**MOCK_BLUETOOTH_STATUS, "powered": False})

        switch.async_write_ha_state.assert_called()
        assert switch.is_on is False


class TestOdioBluetoothSwitchSetupEntry:

    async def test_creates_bt_switch_when_backend_enabled(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS), server_info=_backends(systemd=False))
        added = await _setup(entry)
        assert any(isinstance(e, OdioBluetoothSwitch) for e in added)

    async def test_no_bt_switch_when_backend_disabled(self):
        entry = _make_entry(make_hub(), server_info=_backends(bluetooth=False, systemd=False))
        added = await _setup(entry)
        assert not any(isinstance(e, OdioBluetoothSwitch) for e in added)


# ---------------------------------------------------------------------------
# OdioBluetoothScanSwitch
# ---------------------------------------------------------------------------

def _make_scan_switch(status=MOCK_BLUETOOTH_STATUS, connected=True):
    hub = make_hub(bluetooth=status, connected=connected)
    return OdioBluetoothScanSwitch(hub, ENTRY_ID, MOCK_DEVICE_INFO), hub


class TestOdioBluetoothScanSwitch:

    def test_unique_id(self):
        assert _make_scan_switch()[0].unique_id == "test_entry_id_bluetooth_scan"

    def test_translation_key(self):
        assert _make_scan_switch()[0].translation_key == "bluetooth_scan"

    def test_is_off_when_not_scanning(self):
        assert _make_scan_switch()[0].is_on is False

    def test_is_on_when_scanning(self):
        switch, _ = _make_scan_switch({**MOCK_BLUETOOTH_STATUS, "scanning": True})
        assert switch.is_on is True

    def test_is_off_when_no_state(self):
        assert _make_scan_switch(status=None)[0].is_on is False

    def test_available_when_all_ok(self):
        assert _make_scan_switch()[0].available is True

    def test_unavailable_when_disconnected(self):
        assert _make_scan_switch(connected=False)[0].available is False

    async def test_turn_on_starts_scan(self):
        switch, hub = _make_scan_switch()
        await switch.async_turn_on()
        hub.client.bluetooth_scan.assert_awaited_once()

    async def test_turn_off_stops_scan(self):
        switch, hub = _make_scan_switch()
        await switch.async_turn_off()
        hub.client.bluetooth_scan_stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# OdioBluetoothDeviceSwitch
# ---------------------------------------------------------------------------

_BT_ADDR = "AA:BB:CC:DD:EE:FF"


def _make_device_switch(status=MOCK_BLUETOOTH_STATUS, connected=True,
                        address=_BT_ADDR, name="Pixel 6a"):
    hub = make_hub(bluetooth=status, connected=connected)
    return OdioBluetoothDeviceSwitch(hub, ENTRY_ID, MOCK_DEVICE_INFO, address, name), hub


class TestOdioBluetoothDeviceSwitch:

    def test_unique_id_includes_address(self):
        assert _make_device_switch()[0].unique_id == f"test_entry_id_bluetooth_device_{_BT_ADDR}"

    def test_name_is_device_name(self):
        assert _make_device_switch()[0].name == "Pixel 6a"

    def test_name_falls_back_to_constructor_when_device_gone(self):
        # Device left known_devices — keep the last known label, not crash.
        switch, _ = _make_device_switch(status=None, name="Pixel 6a")
        assert switch.name == "Pixel 6a"

    def test_name_resolves_live_when_blue_z_populates_it(self):
        # Constructed with address fallback; name resolves later via SSE.
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "name": "JBL Go 3"}
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        switch, _ = _make_device_switch(status=status, name=_BT_ADDR)
        assert switch.name == "JBL Go 3"

    def test_is_on_when_connected(self):
        assert _make_device_switch()[0].is_on is True

    def test_is_off_when_disconnected(self):
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "connected": False}
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        assert _make_device_switch(status=status)[0].is_on is False

    def test_icon_reflects_connection(self):
        assert _make_device_switch()[0].icon == "mdi:bluetooth-audio"
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "connected": False}
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        assert _make_device_switch(status=status)[0].icon == "mdi:bluetooth-off"

    def test_unavailable_when_device_gone(self):
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": []}
        assert _make_device_switch(status=status)[0].available is False

    def test_available_when_present(self):
        assert _make_device_switch()[0].available is True

    def test_unavailable_when_sse_disconnected(self):
        assert _make_device_switch(connected=False)[0].available is False

    async def test_turn_on_connects(self):
        switch, hub = _make_device_switch()
        await switch.async_turn_on()
        hub.client.bluetooth_connect.assert_awaited_once_with(_BT_ADDR)

    async def test_turn_off_disconnects(self):
        switch, hub = _make_device_switch()
        await switch.async_turn_off()
        hub.client.bluetooth_disconnect.assert_awaited_once_with(_BT_ADDR)


class TestBluetoothDeviceSwitchSetup:

    async def test_creates_scan_and_device_switches(self):
        entry = _make_entry(make_hub(bluetooth=MOCK_BLUETOOTH_STATUS), server_info=_backends(systemd=False))
        added = await _setup(entry)
        assert any(isinstance(e, OdioBluetoothScanSwitch) for e in added)
        device_switches = [e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]
        assert len(device_switches) == 1
        assert device_switches[0].address == _BT_ADDR

    async def test_skips_unpaired_devices(self):
        device = {"address": "11:22:33:44:55:66", "name": "Speaker", "paired": False, "bonded": False}
        status = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        entry = _make_entry(make_hub(bluetooth=status), server_info=_backends(systemd=False))
        added = await _setup(entry)
        assert not any(isinstance(e, OdioBluetoothDeviceSwitch) for e in added)

    async def test_dynamic_adds_newly_paired_device(self):
        hub = make_hub(bluetooth={**MOCK_BLUETOOTH_STATUS, "known_devices": []})
        entry = _make_entry(hub, server_info=_backends(systemd=False))
        added = await _setup(entry)
        assert not any(isinstance(e, OdioBluetoothDeviceSwitch) for e in added)

        push_event(hub, "bluetooth.updated", MOCK_BLUETOOTH_STATUS)

        device_switches = [e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]
        assert len(device_switches) == 1

    async def test_dynamic_skips_known_device(self):
        hub = make_hub(bluetooth=MOCK_BLUETOOTH_STATUS)
        entry = _make_entry(hub, server_info=_backends(systemd=False))
        added = await _setup(entry)
        count = len([e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)])

        push_event(hub, "bluetooth.updated", MOCK_BLUETOOTH_STATUS)

        assert len([e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]) == count
