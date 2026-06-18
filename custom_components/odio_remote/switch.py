"""Switch platform for Odio Remote — start/stop user-scope systemd services."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .coordinator import OdioBluetoothCoordinator, OdioServiceCoordinator
from .event_stream import OdioEventStreamManager
from .helpers import (
    api_command,
    is_persistent_bt_device,
    register_dynamic_entities,
)
from .mixins import OdioBluetoothEntity

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Platform context
# =============================================================================


@dataclass
class _SwitchContext:
    """Shared setup state for switch platform helpers."""

    entry_id: str
    service_coordinator: OdioServiceCoordinator
    api: OdioApiClient
    device_info: DeviceInfo
    event_stream: OdioEventStreamManager


# =============================================================================
# Platform setup
# =============================================================================


def _build_service_switches(
    entry: OdioConfigEntry,
    service_coordinator: OdioServiceCoordinator,
) -> tuple[_SwitchContext, list["OdioServiceSwitch"]]:
    """Build initial service switch entities from live or cached data."""
    rd = entry.runtime_data
    ctx = _SwitchContext(
        entry_id=entry.entry_id,
        service_coordinator=service_coordinator,
        api=rd.api,
        device_info=rd.device_info,
        event_stream=rd.event_stream,
    )

    live_services = service_coordinator.data.get("services", []) if service_coordinator.data else []
    cached_services = entry.data.get("cached_services", []) if not live_services else []
    services_source = live_services or cached_services

    entities = [
        OdioServiceSwitch(ctx, svc)
        for svc in services_source
        if svc.get("exists") and svc.get("scope") == "user"
    ]
    if live_services or cached_services:
        _LOGGER.debug(
            "Creating %d service switch entities (%s)",
            len(entities),
            "live" if live_services else "cached",
        )
    return ctx, entities


def _build_bluetooth_device_switches(
    entry: OdioConfigEntry,
    coordinator: OdioBluetoothCoordinator,
) -> list["OdioBluetoothDeviceSwitch"]:
    """Build connect/disconnect switches for known (paired/bonded) BT devices."""
    rd = entry.runtime_data
    devices = (coordinator.data or {}).get("known_devices", [])
    return [
        OdioBluetoothDeviceSwitch(
            coordinator,
            rd.api,
            entry.entry_id,
            rd.device_info,
            rd.event_stream,
            device["address"],
            device.get("name") or device["address"],
        )
        for device in devices
        if device.get("address") and is_persistent_bt_device(device)
    ]


def _register_dynamic_bluetooth_devices(
    entry: OdioConfigEntry,
    coordinator: OdioBluetoothCoordinator,
    async_add_entities: AddEntitiesCallback,
    initial_entities: list[SwitchEntity],
) -> None:
    """Add a switch when a newly paired/bonded BT device appears via SSE."""
    rd = entry.runtime_data

    def _select_key(device: dict[str, Any]) -> str | None:
        address = device.get("address")
        return address if address and is_persistent_bt_device(device) else None

    register_dynamic_entities(
        entry,
        coordinator,
        list_key="known_devices",
        select_key=_select_key,
        factory=lambda device: OdioBluetoothDeviceSwitch(
            coordinator,
            rd.api,
            entry.entry_id,
            rd.device_info,
            rd.event_stream,
            device["address"],
            device.get("name") or device["address"],
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
    entities: list[SwitchEntity] = []

    bluetooth_coordinator = rd.coordinators.bluetooth
    if bluetooth_coordinator is not None:
        entities.append(
            OdioBluetoothSwitch(
                bluetooth_coordinator,
                rd.api,
                entry.entry_id,
                rd.device_info,
                rd.event_stream,
            )
        )
        entities.append(
            OdioBluetoothScanSwitch(
                bluetooth_coordinator,
                rd.api,
                entry.entry_id,
                rd.device_info,
                rd.event_stream,
            )
        )
        entities += _build_bluetooth_device_switches(entry, bluetooth_coordinator)

    service_coordinator = rd.coordinators.service
    if service_coordinator is not None:
        ctx, service_switches = _build_service_switches(entry, service_coordinator)
        entities += service_switches

    async_add_entities(entities)

    if bluetooth_coordinator is not None:
        _register_dynamic_bluetooth_devices(
            entry, bluetooth_coordinator, async_add_entities, entities
        )

    if service_coordinator is None:
        return

    # Dynamic switch creation: fires when service_coordinator first gets data
    # after an API-down startup.
    def _select_switch_key(svc: dict[str, Any]) -> str | None:
        if not (svc.get("exists") and svc.get("scope") == "user"):
            return None
        return f"{svc.get('scope', 'user')}/{svc['name']}"

    register_dynamic_entities(
        entry,
        service_coordinator,
        list_key="services",
        select_key=_select_switch_key,
        factory=lambda svc: OdioServiceSwitch(ctx, svc),
        initial_keys={
            f"{e._service_info['scope']}/{e._service_info['name']}"
            for e in entities
            if isinstance(e, OdioServiceSwitch)
        },
        label="service switch(es)",
        async_add_entities=async_add_entities,
    )


# =============================================================================
# Entity
# =============================================================================


class OdioServiceSwitch(CoordinatorEntity[OdioServiceCoordinator], SwitchEntity):
    """Switch that starts/stops a user-scope systemd service."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _SwitchContext, service_info: dict[str, Any]) -> None:
        super().__init__(ctx.service_coordinator)
        self._api = ctx.api
        self._event_stream = ctx.event_stream
        self._service_info = service_info

        service_name: str = service_info["name"]
        scope: str = service_info["scope"]

        self._attr_unique_id = f"{ctx.entry_id}_switch_{scope}_{service_name}"
        self._attr_name = service_name.removesuffix(".service")
        self._attr_device_info = ctx.device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to SSE connectivity changes in addition to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._event_stream.async_add_listener(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        """Return True when the service is running."""
        if not self.coordinator.data:
            return False
        for svc in self.coordinator.data.get("services", []):
            if svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]:
                return svc.get("running", False)
        return False

    @property
    def available(self) -> bool:
        """Return False when SSE is disconnected or coordinator has no data."""
        return (
            self._event_stream.sse_connected
            and self.coordinator.last_update_success
            and bool(self.coordinator.data)
        )

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the service."""
        await self._api.control_service(
            "start", self._service_info["scope"], self._service_info["name"]
        )

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the service."""
        await self._api.control_service(
            "stop", self._service_info["scope"], self._service_info["name"]
        )


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
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("powered", False)

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on Bluetooth adapter."""
        await self._api.bluetooth_power_up()
        await self.coordinator.async_refresh()

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off Bluetooth adapter."""
        await self._api.bluetooth_power_down()
        await self.coordinator.async_refresh()


class OdioBluetoothScanSwitch(OdioBluetoothEntity, SwitchEntity):
    """Switch that starts/stops Bluetooth discovery of nearby audio devices."""

    _attr_translation_key = "bluetooth_scan"
    _attr_icon = "mdi:bluetooth-settings"
    _unique_suffix = "bluetooth_scan"

    @property
    def is_on(self) -> bool:
        """Return True while a scan is in progress."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("scanning", False)

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start scanning for Bluetooth devices."""
        await self._api.bluetooth_scan()
        await self.coordinator.async_refresh()

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the active Bluetooth scan."""
        await self._api.bluetooth_scan_stop()
        await self.coordinator.async_refresh()


class OdioBluetoothDeviceSwitch(OdioBluetoothEntity, SwitchEntity):
    """Switch that connects/disconnects a known Bluetooth audio device.

    Once connected, the device becomes a PulseAudio/PipeWire sink and is
    selectable as the default output on the receiver media_player.
    """

    def __init__(
        self,
        coordinator: OdioBluetoothCoordinator,
        api: OdioApiClient,
        entry_id: str,
        device_info: DeviceInfo,
        event_stream: OdioEventStreamManager,
        address: str,
        name: str,
    ) -> None:
        self._address = address
        self._fallback_name = name
        self._unique_suffix = f"bluetooth_device_{address}"
        super().__init__(coordinator, api, entry_id, device_info, event_stream)

    @property
    def address(self) -> str:
        """Return the device MAC address."""
        return self._address

    @property
    def name(self) -> str:
        """Friendly name, refreshed live as BlueZ resolves it."""
        device = self._device()
        if device and device.get("name"):
            return device["name"]
        return self._fallback_name

    def _has_data(self) -> bool:
        """Available only while the device is present in known_devices."""
        return self._device() is not None

    def _device(self) -> dict[str, Any] | None:
        """Return this device's entry in known_devices, or None if gone."""
        if not self.coordinator.data:
            return None
        for device in self.coordinator.data.get("known_devices", []):
            if device.get("address") == self._address:
                return device
        return None

    @property
    def icon(self) -> str:
        """Return icon based on connection state."""
        return "mdi:bluetooth-audio" if self.is_on else "mdi:bluetooth-off"

    @property
    def is_on(self) -> bool:
        """Return True when the device is connected."""
        device = self._device()
        return bool(device and device.get("connected"))

    @api_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Connect the device."""
        await self._api.bluetooth_connect(self._address)
        await self.coordinator.async_refresh()

    @api_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disconnect the device."""
        await self._api.bluetooth_disconnect(self._address)
        await self.coordinator.async_refresh()
