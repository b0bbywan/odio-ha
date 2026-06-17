"""Tests for Odio Remote switch platform."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.odio_remote.switch import (
    OdioBluetoothDeviceSwitch,
    OdioBluetoothScanSwitch,
    OdioBluetoothSwitch,
    OdioServiceSwitch,
    _SwitchContext,
    async_setup_entry,
)

from .conftest import MOCK_ALL_SERVICES, MOCK_BLUETOOTH_STATUS, MOCK_DEVICE_INFO, MOCK_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(services=None, last_update_success=True):
    coord = MagicMock()
    coord.data = {"services": services} if services is not None else None
    coord.last_update_success = last_update_success
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_event_stream(sse_connected=True):
    es = MagicMock()
    es.sse_connected = sse_connected
    es.async_add_listener = MagicMock(return_value=lambda: None)
    return es


def _make_ctx(coordinator=None, service_info=None, event_stream=None, api=None):
    if coordinator is None:
        coordinator = _make_coordinator([service_info] if service_info else [])
    return _SwitchContext(
        entry_id="test_entry_id",
        service_coordinator=coordinator,
        api=api or MagicMock(),
        device_info=MOCK_DEVICE_INFO,
        event_stream=event_stream or _make_event_stream(),
    )


def _make_switch(service_info, coordinator=None):
    if coordinator is None:
        coordinator = _make_coordinator([service_info])
    return OdioServiceSwitch(_make_ctx(coordinator), service_info)


def _make_entry(service_coordinator):
    from custom_components.odio_remote import OdioCoordinators
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.runtime_data.coordinators = OdioCoordinators(service=service_coordinator)
    entry.runtime_data.api = MagicMock()
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.event_stream = _make_event_stream()
    entry.async_on_unload = MagicMock()
    return entry


# ---------------------------------------------------------------------------
# Entity construction
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchConstruction:

    def test_unique_id(self):
        entity = _make_switch(MOCK_SERVICES[0])
        assert entity.unique_id == "test_entry_id_switch_user_mpd.service"

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
# is_on
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchIsOn:

    def test_is_on_when_running(self):
        assert _make_switch(MOCK_SERVICES[0]).is_on is True

    def test_is_off_when_stopped(self):
        assert _make_switch(MOCK_SERVICES[1]).is_on is False

    def test_is_off_when_service_not_in_data(self):
        svc = {"name": "unknown.service", "scope": "user", "exists": True, "running": True}
        entity = _make_switch(svc, coordinator=_make_coordinator([MOCK_SERVICES[0]]))
        assert entity.is_on is False

    def test_is_off_when_coordinator_data_is_none(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(services=None))
        assert entity.is_on is False

    def test_is_on_matches_scope(self):
        user_svc = {"name": "mpd.service", "scope": "user", "exists": True, "running": True}
        system_svc = {"name": "mpd.service", "scope": "system", "exists": True, "running": False}
        entity = _make_switch(user_svc, coordinator=_make_coordinator([system_svc]))
        assert entity.is_on is False


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchLifecycle:

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_sse(self):
        es = _make_event_stream()
        ctx = _make_ctx(coordinator=_make_coordinator(MOCK_SERVICES), event_stream=es)
        entity = OdioServiceSwitch(ctx, MOCK_SERVICES[0])
        entity.async_on_remove = MagicMock()
        with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
            await entity.async_added_to_hass()
        es.async_add_listener.assert_called_with(entity.async_write_ha_state)


class TestOdioServiceSwitchAvailable:

    def test_available_when_coordinator_ok(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(MOCK_SERVICES, last_update_success=True))
        assert entity.available is True

    def test_unavailable_when_last_update_failed(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(MOCK_SERVICES, last_update_success=False))
        assert entity.available is False

    def test_unavailable_when_data_is_none(self):
        entity = _make_switch(MOCK_SERVICES[0], coordinator=_make_coordinator(services=None))
        assert entity.available is False

    def test_unavailable_when_sse_disconnected(self):
        es = _make_event_stream(sse_connected=False)
        ctx = _make_ctx(coordinator=_make_coordinator(MOCK_SERVICES), event_stream=es)
        entity = OdioServiceSwitch(ctx, MOCK_SERVICES[0])
        assert entity.available is False


# ---------------------------------------------------------------------------
# Turn on / turn off
# ---------------------------------------------------------------------------

class TestOdioServiceSwitchActions:

    @pytest.mark.asyncio
    async def test_turn_on_calls_start(self):
        svc = MOCK_SERVICES[1]
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_make_ctx(coordinator=_make_coordinator(MOCK_SERVICES), api=api), svc)

        await entity.async_turn_on()

        api.control_service.assert_awaited_once_with("start", "user", "shairport-sync.service")

    @pytest.mark.asyncio
    async def test_turn_on_does_not_poll(self):
        """State update is driven by SSE — no manual refresh after action."""
        svc = MOCK_SERVICES[1]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_make_ctx(coordinator=coord, api=api), svc)

        await entity.async_turn_on()

        coord.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_calls_stop(self):
        svc = MOCK_SERVICES[0]
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_make_ctx(coordinator=_make_coordinator(MOCK_SERVICES), api=api), svc)

        await entity.async_turn_off()

        api.control_service.assert_awaited_once_with("stop", "user", "mpd.service")

    @pytest.mark.asyncio
    async def test_turn_off_does_not_poll(self):
        """State update is driven by SSE — no manual refresh after action."""
        svc = MOCK_SERVICES[0]
        coord = _make_coordinator(MOCK_SERVICES)
        api = MagicMock()
        api.control_service = AsyncMock()
        entity = OdioServiceSwitch(_make_ctx(coordinator=coord, api=api), svc)

        await entity.async_turn_off()

        coord.async_request_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestOdioSwitchSetupEntry:

    @pytest.mark.asyncio
    async def test_creates_user_scope_entities(self):
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 5
        for entity in added:
            assert entity._service_info["scope"] == "user"

    @pytest.mark.asyncio
    async def test_filters_system_scope(self):
        coord = _make_coordinator(MOCK_ALL_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert "bluetooth.service" not in [e._service_info["name"] for e in added]

    @pytest.mark.asyncio
    async def test_filters_non_existing_services(self):
        services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "running": False},
            {"name": "ghost.service", "scope": "user", "exists": False, "running": False},
        ]
        coord = _make_coordinator(services)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert len(added) == 1
        assert added[0]._service_info["name"] == "mpd.service"

    @pytest.mark.asyncio
    async def test_dynamic_listener_adds_new_services(self):
        """Callback fires when coordinator gets data after an API-down startup."""
        coord = _make_coordinator(services=None)
        captured_listeners = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured_listeners.append(cb) or (lambda: None)
        )
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []

        coord.data = {"services": MOCK_SERVICES}
        for listener in captured_listeners:
            listener()
        assert len(added) == len([s for s in MOCK_SERVICES if s.get("exists") and s.get("scope") == "user"])

    @pytest.mark.asyncio
    async def test_dynamic_listener_skips_already_known_keys(self):
        """Callback does not re-add services already created at setup."""
        coord = _make_coordinator(MOCK_SERVICES)
        captured_listeners = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured_listeners.append(cb) or (lambda: None)
        )
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        initial_count = len(added)

        for listener in captured_listeners:
            listener()
        assert len(added) == initial_count  # no duplicates

    @pytest.mark.asyncio
    async def test_dynamic_listener_noop_when_data_is_none(self):
        """Callback does nothing if coordinator data is still None."""
        coord = _make_coordinator(services=None)
        captured_listeners = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured_listeners.append(cb) or (lambda: None)
        )
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        for listener in captured_listeners:
            listener()
        assert added == []

    @pytest.mark.asyncio
    async def test_dynamic_listener_skips_non_user_or_missing_services(self):
        """select_key returns None for non-user-scope or non-existing services."""
        coord = _make_coordinator(services=None)
        captured_listeners = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured_listeners.append(cb) or (lambda: None)
        )
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))

        coord.data = {"services": [
            {"name": "system.service", "scope": "system", "exists": True},
            {"name": "ghost.service", "scope": "user", "exists": False},
        ]}
        for listener in captured_listeners:
            listener()
        assert added == []

    @pytest.mark.asyncio
    async def test_no_entities_when_no_coordinator(self):
        entry = _make_entry(service_coordinator=None)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []

    @pytest.mark.asyncio
    async def test_no_entities_when_coordinator_data_is_none(self):
        coord = _make_coordinator(services=None)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert added == []

    @pytest.mark.asyncio
    async def test_entity_names_strip_service_suffix(self):
        coord = _make_coordinator(MOCK_SERVICES)
        entry = _make_entry(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert {e.name for e in added} == {"mpd", "shairport-sync", "snapclient"}


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch helpers
# ---------------------------------------------------------------------------

def _make_bt_coordinator(data=None, last_update_success=True):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = last_update_success
    coord.async_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _make_bt_switch(data=None, sse_connected=True, last_update_success=True, api=None):
    coord = _make_bt_coordinator(data, last_update_success)
    es = _make_event_stream(sse_connected)
    return OdioBluetoothSwitch(coord, api or MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es)


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch — construction
# ---------------------------------------------------------------------------

class TestOdioBluetoothSwitchLifecycle:

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_sse(self):
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothSwitch(coord, MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es)
        switch.async_on_remove = MagicMock()
        with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
            await switch.async_added_to_hass()
        es.async_add_listener.assert_called_with(switch.async_write_ha_state)


class TestOdioBluetoothSwitchConstruction:

    def test_unique_id(self):
        assert _make_bt_switch().unique_id == "test_entry_id_bluetooth_power"

    def test_translation_key(self):
        assert _make_bt_switch().translation_key == "bluetooth_power"

    def test_has_entity_name(self):
        assert _make_bt_switch()._attr_has_entity_name is True

    def test_device_info_set(self):
        from custom_components.odio_remote.const import DOMAIN
        assert (DOMAIN, "test_entry_id") in _make_bt_switch().device_info["identifiers"]


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch — is_on
# ---------------------------------------------------------------------------

class TestOdioBluetoothSwitchIcon:

    def test_icon_when_on(self):
        assert _make_bt_switch(data=MOCK_BLUETOOTH_STATUS).icon == "mdi:bluetooth"

    def test_icon_when_off(self):
        data = {**MOCK_BLUETOOTH_STATUS, "powered": False}
        assert _make_bt_switch(data=data).icon == "mdi:bluetooth-off"


class TestOdioBluetoothSwitchIsOn:

    def test_is_on_when_powered(self):
        assert _make_bt_switch(data=MOCK_BLUETOOTH_STATUS).is_on is True

    def test_is_off_when_not_powered(self):
        data = {**MOCK_BLUETOOTH_STATUS, "powered": False}
        assert _make_bt_switch(data=data).is_on is False

    def test_is_off_when_no_data(self):
        assert _make_bt_switch(data=None).is_on is False


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch — available
# ---------------------------------------------------------------------------

class TestOdioBluetoothSwitchAvailable:

    def test_available_when_all_ok(self):
        assert _make_bt_switch(data=MOCK_BLUETOOTH_STATUS).available is True

    def test_unavailable_when_sse_disconnected(self):
        assert _make_bt_switch(data=MOCK_BLUETOOTH_STATUS, sse_connected=False).available is False

    def test_unavailable_when_last_update_failed(self):
        assert _make_bt_switch(data=MOCK_BLUETOOTH_STATUS, last_update_success=False).available is False

    def test_unavailable_when_no_data(self):
        assert _make_bt_switch(data=None).available is False


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch — actions
# ---------------------------------------------------------------------------

class TestOdioBluetoothSwitchActions:

    @pytest.mark.asyncio
    async def test_turn_on_calls_power_up(self):
        api = MagicMock()
        api.bluetooth_power_up = AsyncMock()
        switch = _make_bt_switch(data=MOCK_BLUETOOTH_STATUS, api=api)
        await switch.async_turn_on()
        api.bluetooth_power_up.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_on_refreshes_coordinator(self):
        api = MagicMock()
        api.bluetooth_power_up = AsyncMock()
        coord = _make_bt_coordinator(data=MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)
        await switch.async_turn_on()
        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_calls_power_down(self):
        api = MagicMock()
        api.bluetooth_power_down = AsyncMock()
        switch = _make_bt_switch(data=MOCK_BLUETOOTH_STATUS, api=api)
        await switch.async_turn_off()
        api.bluetooth_power_down.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_refreshes_coordinator(self):
        api = MagicMock()
        api.bluetooth_power_down = AsyncMock()
        coord = _make_bt_coordinator(data=MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)
        await switch.async_turn_off()
        coord.async_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# OdioBluetoothSwitch — async_setup_entry
# ---------------------------------------------------------------------------

def _make_entry_with_bt(bt_coordinator, service_coordinator=None):
    from custom_components.odio_remote import OdioCoordinators
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.runtime_data.coordinators = OdioCoordinators(service=service_coordinator, bluetooth=bt_coordinator)
    entry.runtime_data.api = MagicMock()
    entry.runtime_data.device_info = MOCK_DEVICE_INFO
    entry.runtime_data.event_stream = _make_event_stream()
    entry.async_on_unload = MagicMock()
    return entry


class TestOdioBluetoothSwitchSetupEntry:

    @pytest.mark.asyncio
    async def test_creates_bt_switch_when_coordinator_present(self):
        entry = _make_entry_with_bt(_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothSwitch) for e in added)

    @pytest.mark.asyncio
    async def test_no_bt_switch_when_coordinator_absent(self):
        entry = _make_entry_with_bt(bt_coordinator=None)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothSwitch) for e in added)


# ---------------------------------------------------------------------------
# OdioBluetoothScanSwitch
# ---------------------------------------------------------------------------

def _make_scan_switch(data=None, sse_connected=True, last_update_success=True, api=None):
    coord = _make_bt_coordinator(data, last_update_success)
    es = _make_event_stream(sse_connected)
    return OdioBluetoothScanSwitch(coord, api or MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es)


class TestOdioBluetoothScanSwitch:

    def test_unique_id(self):
        assert _make_scan_switch().unique_id == "test_entry_id_bluetooth_scan"

    def test_translation_key(self):
        assert _make_scan_switch().translation_key == "bluetooth_scan"

    def test_is_off_when_not_scanning(self):
        assert _make_scan_switch(data=MOCK_BLUETOOTH_STATUS).is_on is False

    def test_is_on_when_scanning(self):
        data = {**MOCK_BLUETOOTH_STATUS, "scanning": True}
        assert _make_scan_switch(data=data).is_on is True

    def test_is_off_when_no_data(self):
        assert _make_scan_switch(data=None).is_on is False

    def test_available_when_all_ok(self):
        assert _make_scan_switch(data=MOCK_BLUETOOTH_STATUS).available is True

    def test_unavailable_when_sse_disconnected(self):
        assert _make_scan_switch(data=MOCK_BLUETOOTH_STATUS, sse_connected=False).available is False

    @pytest.mark.asyncio
    async def test_turn_on_starts_scan(self):
        api = MagicMock()
        api.bluetooth_scan = AsyncMock()
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothScanSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)
        await switch.async_turn_on()
        api.bluetooth_scan.assert_awaited_once()
        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_stops_scan(self):
        api = MagicMock()
        api.bluetooth_scan_stop = AsyncMock()
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothScanSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es)
        await switch.async_turn_off()
        api.bluetooth_scan_stop.assert_awaited_once()
        coord.async_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# OdioBluetoothDeviceSwitch
# ---------------------------------------------------------------------------

_BT_ADDR = "AA:BB:CC:DD:EE:FF"


def _make_device_switch(data=None, sse_connected=True, last_update_success=True, api=None,
                        address=_BT_ADDR, name="Pixel 6a"):
    coord = _make_bt_coordinator(data, last_update_success)
    es = _make_event_stream(sse_connected)
    return OdioBluetoothDeviceSwitch(
        coord, api or MagicMock(), "test_entry_id", MOCK_DEVICE_INFO, es, address, name
    )


class TestOdioBluetoothDeviceSwitch:

    def test_unique_id_includes_address(self):
        assert _make_device_switch().unique_id == f"test_entry_id_bluetooth_device_{_BT_ADDR}"

    def test_name_is_device_name(self):
        assert _make_device_switch().name == "Pixel 6a"

    def test_name_falls_back_to_constructor_when_device_gone(self):
        # Device left known_devices — keep the last known label, not crash.
        assert _make_device_switch(data=None, name="Pixel 6a").name == "Pixel 6a"

    def test_name_resolves_live_when_blue_z_populates_it(self):
        # Paired while name was still "" (constructed with address); name later
        # resolves via bluetooth.updated and must override the address fallback.
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "name": "JBL Go 3"}
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        switch = _make_device_switch(data=data, name=_BT_ADDR)
        assert switch.name == "JBL Go 3"

    def test_is_on_when_connected(self):
        assert _make_device_switch(data=MOCK_BLUETOOTH_STATUS).is_on is True

    def test_is_off_when_disconnected(self):
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "connected": False}
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        assert _make_device_switch(data=data).is_on is False

    def test_icon_reflects_connection(self):
        assert _make_device_switch(data=MOCK_BLUETOOTH_STATUS).icon == "mdi:bluetooth-audio"
        device = {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "connected": False}
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        assert _make_device_switch(data=data).icon == "mdi:bluetooth-off"

    def test_unavailable_when_device_gone(self):
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": []}
        assert _make_device_switch(data=data).available is False

    def test_available_when_present(self):
        assert _make_device_switch(data=MOCK_BLUETOOTH_STATUS).available is True

    def test_unavailable_when_sse_disconnected(self):
        assert _make_device_switch(data=MOCK_BLUETOOTH_STATUS, sse_connected=False).available is False

    @pytest.mark.asyncio
    async def test_turn_on_connects(self):
        api = MagicMock()
        api.bluetooth_connect = AsyncMock()
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothDeviceSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es, _BT_ADDR, "Pixel 6a")
        await switch.async_turn_on()
        api.bluetooth_connect.assert_awaited_once_with(_BT_ADDR)
        coord.async_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off_disconnects(self):
        api = MagicMock()
        api.bluetooth_disconnect = AsyncMock()
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        es = _make_event_stream()
        switch = OdioBluetoothDeviceSwitch(coord, api, "test_entry_id", MOCK_DEVICE_INFO, es, _BT_ADDR, "Pixel 6a")
        await switch.async_turn_off()
        api.bluetooth_disconnect.assert_awaited_once_with(_BT_ADDR)
        coord.async_refresh.assert_awaited_once()


class TestBluetoothDeviceSwitchSetup:

    @pytest.mark.asyncio
    async def test_creates_scan_and_device_switches(self):
        entry = _make_entry_with_bt(_make_bt_coordinator(MOCK_BLUETOOTH_STATUS))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert any(isinstance(e, OdioBluetoothScanSwitch) for e in added)
        device_switches = [e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]
        assert len(device_switches) == 1
        assert device_switches[0].address == _BT_ADDR

    @pytest.mark.asyncio
    async def test_skips_unpaired_devices(self):
        device = {"address": "11:22:33:44:55:66", "name": "Speaker", "paired": False, "bonded": False}
        data = {**MOCK_BLUETOOTH_STATUS, "known_devices": [device]}
        entry = _make_entry_with_bt(_make_bt_coordinator(data))
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothDeviceSwitch) for e in added)

    @pytest.mark.asyncio
    async def test_dynamic_listener_adds_newly_paired_device(self):
        coord = _make_bt_coordinator({**MOCK_BLUETOOTH_STATUS, "known_devices": []})
        captured = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured.append(cb) or (lambda: None)
        )
        entry = _make_entry_with_bt(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        assert not any(isinstance(e, OdioBluetoothDeviceSwitch) for e in added)

        coord.data = MOCK_BLUETOOTH_STATUS
        for cb in captured:
            cb()
        device_switches = [e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]
        assert len(device_switches) == 1

    @pytest.mark.asyncio
    async def test_dynamic_listener_skips_known_device(self):
        coord = _make_bt_coordinator(MOCK_BLUETOOTH_STATUS)
        captured = []
        coord.async_add_listener = MagicMock(
            side_effect=lambda cb: captured.append(cb) or (lambda: None)
        )
        entry = _make_entry_with_bt(coord)
        added = []
        await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
        count = len([e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)])
        for cb in captured:
            cb()
        assert len([e for e in added if isinstance(e, OdioBluetoothDeviceSwitch)]) == count
