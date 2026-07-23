"""Switch platform for Odio Remote — start/stop user-scope systemd services."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyodio import BluetoothDevice, BluetoothDeviceState, OdioHub, Service, ServiceState

from . import OdioConfigEntry
from .entity import OdioBluetoothEntity, OdioEntity
from .helpers import (
    api_command,
    is_persistent_bt_device,
    register_dynamic_entities,
)

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Platform setup
# =============================================================================


def _build_service_switches(entry: OdioConfigEntry) -> list["OdioServiceSwitch"]:
    """Build initial service switch entities from live or cached data."""
    rd = entry.runtime_data
    live = [service.state for service in rd.hub.services.values()]
    cached = (
        []
        if live
        else [ServiceState.from_dict(svc) for svc in entry.data.get("cached_services", [])]
    )
    source = live or cached
    entities = [
        OdioServiceSwitch(rd.hub, entry.entry_id, rd.device_info, state)
        for state in source
        if state.exists and state.scope == "user"
    ]
    if source:
        _LOGGER.debug(
            "Creating %d service switch entities (%s)",
            len(entities),
            "live" if live else "cached",
        )
    return entities


def _build_bluetooth_device_switches(entry: OdioConfigEntry) -> list["OdioBluetoothDeviceSwitch"]:
    """Build connect/disconnect switches for known (paired/bonded) BT devices."""
    rd = entry.runtime_data
    return [
        OdioBluetoothDeviceSwitch(
            rd.hub,
            entry.entry_id,
            rd.device_info,
            device.address,
            device.name or device.address,
        )
        for device in rd.hub.bluetooth.devices.values()
        if device.address and is_persistent_bt_device(device.state)
    ]


def _register_dynamic_bluetooth_devices(
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[SwitchEntity],
) -> None:
    """Add a switch when a newly paired/bonded BT device appears via SSE."""
    rd = entry.runtime_data

    def _select_key(obj: Any) -> str | None:
        if not isinstance(obj, BluetoothDevice):
            return None
        return obj.address if obj.address and is_persistent_bt_device(obj.state) else None

    register_dynamic_entities(
        entry,
        rd.hub.bluetooth.on_change,
        select_key=_select_key,
        factory=lambda device: OdioBluetoothDeviceSwitch(
            rd.hub,
            entry.entry_id,
            rd.device_info,
            device.address,
            device.name or device.address,
        ),
        initial_keys={
            e.address
            for e in initial_entities
            if isinstance(e, OdioBluetoothDeviceSwitch)
        },
        label="Bluetooth device switch(es)",
        async_add_entities=async_add_entities,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote switch entities."""
    rd = entry.runtime_data
    backends = rd.server_info.backends
    entities: list[SwitchEntity] = []

    if backends.bluetooth:
        entities.append(OdioBluetoothSwitch(rd.hub, entry.entry_id, rd.device_info))
        entities.append(OdioBluetoothScanSwitch(rd.hub, entry.entry_id, rd.device_info))
        entities += _build_bluetooth_device_switches(entry)

    if backends.systemd:
        entities += _build_service_switches(entry)

    async_add_entities(entities)

    if backends.bluetooth:
        _register_dynamic_bluetooth_devices(entry, async_add_entities, entities)

    if not backends.systemd:
        return

    # Dynamic switch creation: fires when the hub first syncs services after
    # an API-down startup, or when a new unit is configured server-side.
    def _select_switch_key(obj: Any) -> str | None:
        if not isinstance(obj, Service):
            return None
        if not (obj.state.exists and obj.scope == "user"):
            return None
        return obj.state.key

    register_dynamic_entities(
        entry,
        rd.hub.services.on_change,
        select_key=_select_switch_key,
        factory=lambda service: OdioServiceSwitch(
            rd.hub, entry.entry_id, rd.device_info, service.state
        ),
        initial_keys={
            e.service_key
            for e in entities
            if isinstance(e, OdioServiceSwitch)
        },
        label="service switch(es)",
        async_add_entities=async_add_entities,
    )


# =============================================================================
# Entities
# =============================================================================


class OdioServiceSwitch(OdioEntity, SwitchEntity):
    """Switch that starts/stops a user-scope systemd service."""

    def __init__(
        self,
        hub: OdioHub,
        entry_id: str,
        device_info: DeviceInfo,
        state: ServiceState,
    ) -> None:
        self._key = state.key
        self._scope = state.scope
        self._service_name = state.name
        self._unique_suffix = f"switch_{state.scope}_{state.name}"
        super().__init__(hub, entry_id, device_info)
        self._attr_name = state.name.removesuffix(".service")

    @property
    def service_key(self) -> str:
        """Return the ``scope/name`` key of the backing service."""
        return self._key

    def _change_sources(self) -> tuple:
        return (self._hub.services.on_change,)

    def _relevant_change(self, change: str, obj: Any) -> bool:
        return isinstance(obj, Service) and obj.state.key == self._key

    def _has_data(self) -> bool:
        return self._key in self._hub.services

    @property
    def is_on(self) -> bool:
        """Return True when the service is running."""
        service = self._hub.services.get(self._key)
        return bool(service and service.running)

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the service."""
        await self._hub.client.service_start(self._scope, self._service_name)

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the service."""
        await self._hub.client.service_stop(self._scope, self._service_name)


class OdioBluetoothSwitch(OdioBluetoothEntity, SwitchEntity):
    """Switch that powers the Bluetooth adapter on or off."""

    _attr_translation_key = "bluetooth_power"
    _unique_suffix = "bluetooth_power"

    @property
    def icon(self) -> str:
        """Return icon based on power state."""
        return "mdi:bluetooth" if self.is_on else "mdi:bluetooth-off"

    @property
    def is_on(self) -> bool:
        """Return True when Bluetooth is powered on."""
        return self._hub.bluetooth.powered

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on Bluetooth adapter."""
        await self._hub.bluetooth.power_up()

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off Bluetooth adapter."""
        await self._hub.bluetooth.power_down()


class OdioBluetoothScanSwitch(OdioBluetoothEntity, SwitchEntity):
    """Switch that starts/stops Bluetooth discovery of nearby audio devices."""

    _attr_translation_key = "bluetooth_scan"
    _attr_icon = "mdi:bluetooth-settings"
    _unique_suffix = "bluetooth_scan"

    @property
    def is_on(self) -> bool:
        """Return True while a scan is in progress."""
        return self._hub.bluetooth.scanning

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start scanning for Bluetooth devices."""
        await self._hub.bluetooth.scan()

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the active Bluetooth scan."""
        await self._hub.bluetooth.scan_stop()


class OdioBluetoothDeviceSwitch(OdioBluetoothEntity, SwitchEntity):
    """Switch that connects/disconnects a known Bluetooth audio device.

    Once connected, the device becomes a PulseAudio/PipeWire sink and is
    selectable as the default output on the receiver media_player.
    """

    def __init__(
        self,
        hub: OdioHub,
        entry_id: str,
        device_info: DeviceInfo,
        address: str,
        name: str,
    ) -> None:
        self._address = address
        self._fallback_name = name
        self._unique_suffix = f"bluetooth_device_{address}"
        super().__init__(hub, entry_id, device_info)

    @property
    def address(self) -> str:
        """Return the device MAC address."""
        return self._address

    @property
    def name(self) -> str:
        """Friendly name, refreshed live as BlueZ resolves it."""
        device = self._device_state()
        if device is not None and device.name:
            return device.name
        return self._fallback_name

    def _has_data(self) -> bool:
        """Available only while the device is present in known_devices."""
        return self._device_state() is not None

    def _device_state(self) -> BluetoothDeviceState | None:
        """Return this device's entry in known_devices, or None if gone."""
        state = self._hub.bluetooth.state
        if state is None:
            return None
        for device in state.known_devices:
            if device.address == self._address:
                return device
        return None

    @property
    def icon(self) -> str:
        """Return icon based on connection state."""
        return "mdi:bluetooth-audio" if self.is_on else "mdi:bluetooth-off"

    @property
    def is_on(self) -> bool:
        """Return True when the device is connected."""
        device = self._device_state()
        return bool(device and device.connected)

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Connect the device."""
        await self._hub.bluetooth.connect(self._address)

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disconnect the device."""
        await self._hub.bluetooth.disconnect(self._address)
