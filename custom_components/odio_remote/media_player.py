"""Media player platform for Odio Remote."""
from __future__ import annotations

import asyncio
import logging
import re

from dataclasses import dataclass
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioConfigEntry
from .api_client import OdioApiClient
from .const import (
    ATTR_CLIENT_ID,
    ATTR_APP,
    ATTR_BACKEND,
    ATTR_USER,
    ATTR_HOST,
    ATTR_CORKED,
    ATTR_SERVICE_SCOPE,
    ATTR_SERVICE_ENABLED,
    ATTR_SERVICE_ACTIVE,
)
from .coordinator import OdioAudioCoordinator, OdioConnectivityCoordinator, OdioServiceCoordinator
from .mixins import MappedEntityMixin

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Platform context
# =============================================================================


@dataclass
class _MediaPlayerContext:
    """Shared setup state for media player platform helpers.

    Bundles all objects that entity constructors and setup callbacks need,
    avoiding long parameter lists and keeping the live coordinator accessible
    for closures that must derive values (e.g. hostname) at call time rather
    than at setup time.
    """

    entry_id: str
    connectivity_coordinator: OdioConnectivityCoordinator
    audio_coordinator: OdioAudioCoordinator | None
    service_coordinator: OdioServiceCoordinator | None
    api: OdioApiClient
    device_info: DeviceInfo
    service_mappings: dict[str, str]


# =============================================================================
# Platform setup
# =============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OdioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Remote media player based on a config entry."""
    rd = config_entry.runtime_data
    ctx = _MediaPlayerContext(
        entry_id=config_entry.entry_id,
        connectivity_coordinator=rd.connectivity_coordinator,
        audio_coordinator=rd.audio_coordinator,
        service_coordinator=rd.service_coordinator,
        api=rd.api,
        device_info=rd.device_info,
        service_mappings=rd.service_mappings,
    )

    # Receiver is always present
    entities: list[MediaPlayerEntity] = [OdioReceiverMediaPlayer(ctx)]

    # Track which clients are handled by a service entity
    handled_client_patterns: set[str] = set()

    # Service entities (only when systemd backend enabled and data available)
    if ctx.service_coordinator is not None and ctx.service_coordinator.data:
        for service in ctx.service_coordinator.data.get("services", []):
            mapping_key = f"{service.get('scope', 'user')}/{service['name']}"
            if service.get("exists") and mapping_key in ctx.service_mappings:
                entities.append(OdioServiceMediaPlayer(ctx, service))
                handled_client_patterns.add(
                    service["name"].replace(".service", "").lower()
                )

    # Standalone remote client entities (only when pulseaudio backend enabled)
    if ctx.audio_coordinator is not None and ctx.audio_coordinator.data:
        _hostname = (
            ctx.connectivity_coordinator.data.get("hostname")
            if ctx.connectivity_coordinator.data
            else None
        )
        for client in ctx.audio_coordinator.data.get("audio", []):
            client_name = client.get("name", "")
            client_host = client.get("host", "")
            if (
                _hostname
                and client_host
                and client_host != _hostname
                and client_name
            ):
                entities.append(OdioPulseClientMediaPlayer(ctx, client))

    _LOGGER.info(
        "Creating %d media_player entities (1 receiver + %d services + %d standalone clients)",
        len(entities),
        len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioPulseClientMediaPlayer)]),
    )

    async_add_entities(entities)

    # -------------------------------------------------------------------------
    # Dynamic service entity creation
    # Fires when service_coordinator first gets data after an API-down startup.
    # -------------------------------------------------------------------------
    if ctx.service_coordinator is not None:
        service_coordinator = ctx.service_coordinator  # narrowed for closure
        known_service_keys = {
            f"{e._service_info['scope']}/{e._service_info['name']}"
            for e in entities
            if isinstance(e, OdioServiceMediaPlayer)
        }

        @callback
        def _async_check_new_services() -> None:
            if not service_coordinator.data:
                return
            new_entities: list[MediaPlayerEntity] = []
            for service in service_coordinator.data.get("services", []):
                mapping_key = f"{service.get('scope', 'user')}/{service['name']}"
                if (
                    service.get("exists")
                    and mapping_key in ctx.service_mappings
                    and mapping_key not in known_service_keys
                ):
                    new_entities.append(OdioServiceMediaPlayer(ctx, service))
                    known_service_keys.add(mapping_key)
                    handled_client_patterns.add(
                        service["name"].replace(".service", "").lower()
                    )
            if new_entities:
                _LOGGER.info(
                    "Dynamically adding %d service entities after late API connection",
                    len(new_entities),
                )
                async_add_entities(new_entities)

        config_entry.async_on_unload(
            service_coordinator.async_add_listener(_async_check_new_services)
        )

    # -------------------------------------------------------------------------
    # Dynamic remote client entity creation
    # Fires on every audio coordinator update; adds entities for newly seen
    # remote clients.
    # -------------------------------------------------------------------------
    if ctx.audio_coordinator is not None:
        audio_coordinator = ctx.audio_coordinator  # narrowed for closure
        known_remote_clients = {
            entity._client_name: entity
            for entity in entities
            if isinstance(entity, OdioPulseClientMediaPlayer)
        }

        @callback
        def _async_check_new_clients() -> None:
            # Derive hostname live so this works even when it was None at setup.
            _hostname = (
                ctx.connectivity_coordinator.data.get("hostname")
                if ctx.connectivity_coordinator.data
                else None
            )
            if not audio_coordinator.data or not _hostname:
                return

            new_entities: list[MediaPlayerEntity] = []
            for client in audio_coordinator.data.get("audio", []):
                client_name = client.get("name", "")
                client_host = client.get("host", "")
                app = client.get("app", "").lower()
                binary = client.get("binary", "").lower()

                if not (client_host and client_host != _hostname and client_name):
                    continue
                if client_name in known_remote_clients:
                    continue
                if any(
                    pattern in [client_name.lower(), app, binary]
                    for pattern in handled_client_patterns
                ):
                    continue

                entity = OdioPulseClientMediaPlayer(ctx, client)
                new_entities.append(entity)
                known_remote_clients[client_name] = entity

            if new_entities:
                _LOGGER.info(
                    "Adding %d new remote client entities", len(new_entities)
                )
                async_add_entities(new_entities)

        config_entry.async_on_unload(
            ctx.audio_coordinator.async_add_listener(_async_check_new_clients)
        )


# =============================================================================
# Entities
# =============================================================================


class OdioReceiverMediaPlayer(MediaPlayerEntity):
    """Representation of the main Odio Remote receiver (the Odio instance)."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, ctx: _MediaPlayerContext) -> None:
        """Initialize the receiver."""
        self._connectivity = ctx.connectivity_coordinator
        self._audio_coordinator = ctx.audio_coordinator
        self._service_coordinator = ctx.service_coordinator
        self._api_client = ctx.api
        self._attr_unique_id = f"{ctx.entry_id}_receiver"
        self._attr_device_info = ctx.device_info

    async def async_added_to_hass(self) -> None:
        """Register listeners on available coordinators."""
        await super().async_added_to_hass()
        # Always listen to connectivity so backends/state update when the API
        # reconnects — even when no audio or service coordinator was created.
        self.async_on_remove(
            self._connectivity.async_add_listener(self._handle_coordinator_update)
        )
        if self._audio_coordinator is not None:
            self.async_on_remove(
                self._audio_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )
        if self._service_coordinator is not None:
            self.async_on_remove(
                self._service_coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinators."""
        self.async_write_ha_state()

    def _get_backends(self) -> dict[str, bool]:
        """Return backends dict from the live connectivity coordinator."""
        return (self._connectivity.data or {}).get("backends", {})

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if self._audio_coordinator is None:
            return MediaPlayerState.OFF

        if not self._audio_coordinator.last_update_success:
            return MediaPlayerState.OFF

        backends = self._get_backends()
        if "pulseaudio" not in backends or self._audio_coordinator is None:
            return MediaPlayerState.OFF

        audio_data = self._audio_coordinator.data
        if audio_data is None:
            return MediaPlayerState.OFF

        clients = audio_data.get("audio", [])
        has_active_client = any(not c.get("corked", True) for c in clients)
        return MediaPlayerState.PLAYING if has_active_client else MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        if self._get_backends().get("pulseaudio"):
            return MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE
        return MediaPlayerEntityFeature(0)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        if self._audio_coordinator is None or not self._audio_coordinator.data:
            return None
        clients = self._audio_coordinator.data.get("audio", [])
        volumes = [client.get("volume", 0) for client in clients]
        if volumes:
            return sum(volumes) / len(volumes)
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        if self._audio_coordinator is None or not self._audio_coordinator.data:
            return False
        clients = self._audio_coordinator.data.get("audio", [])
        return any(client.get("muted", False) for client in clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "backends": self._get_backends(),
        }
        if self._audio_coordinator is not None and self._audio_coordinator.data:
            clients = self._audio_coordinator.data.get("audio", [])
            attrs["active_clients"] = len(clients)
            attrs["playing_clients"] = len([
                c for c in clients if not c.get("corked", True)
            ])
        return attrs

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._api_client.set_server_volume(volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._api_client.set_server_mute(mute)


class OdioServiceMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Odio Remote service using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _MediaPlayerContext, service_info: dict[str, Any]) -> None:
        """Initialize the service."""
        assert ctx.service_coordinator is not None
        # Use audio_coordinator as primary (fast updates) when available,
        # fall back to service_coordinator so CoordinatorEntity always has one.
        coordinator = ctx.audio_coordinator or ctx.service_coordinator
        super().__init__(coordinator)
        self._service_coordinator: OdioServiceCoordinator = ctx.service_coordinator
        self._api_client = ctx.api
        self._service_info = service_info

        service_name = service_info["name"]
        scope = service_info["scope"]

        self._attr_unique_id = f"{ctx.entry_id}_service_{scope}_{service_name}"
        self._attr_name = f"{service_name} ({scope})"
        self._attr_device_info = ctx.device_info

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"{self._service_info['scope']}/{self._service_info['name']}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()
        self.async_on_remove(
            self._service_coordinator.async_add_listener(
                self._handle_service_coordinator_update
            )
        )

    @callback
    def _handle_service_coordinator_update(self) -> None:
        """Handle updated data from the service coordinator."""
        self.async_write_ha_state()

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._is_service_running)
        if mapped_state is not None:
            return mapped_state

        if not self._is_service_running():
            return MediaPlayerState.OFF

        if self.coordinator is not None and self.coordinator.data:
            service_name = self._service_info["name"].replace(".service", "")
            clients = self.coordinator.data.get("audio", [])
            for client in clients:
                client_name = client.get("name", "").lower()
                app = client.get("app", "").lower()
                binary = client.get("binary", "").lower()
                if service_name in [client_name, app, binary]:
                    if not client.get("corked", True):
                        return MediaPlayerState.PLAYING
                    return MediaPlayerState.IDLE

        return MediaPlayerState.IDLE

    def _is_service_running(self) -> bool:
        """Check if the service is running."""
        if self._service_coordinator.data:
            for svc in self._service_coordinator.data.get("services", []):
                if (
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
                ):
                    return svc.get("running", False)
        return False

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )
        if self._get_client():
            base_features |= MediaPlayerEntityFeature.VOLUME_SET
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume
        client = self._get_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted
        client = self._get_client()
        if client:
            return client.get("muted", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            ATTR_SERVICE_SCOPE: self._service_info["scope"],
            ATTR_SERVICE_ENABLED: self._service_info.get("enabled", False),
        }
        if self._service_coordinator.data:
            for svc in self._service_coordinator.data.get("services", []):
                if (
                    svc["name"] == self._service_info["name"]
                    and svc["scope"] == self._service_info["scope"]
                ):
                    attrs[ATTR_SERVICE_ACTIVE] = svc.get("active_state")
                    attrs["running"] = svc.get("running", False)
                    break
        client = self._get_client()
        if client:
            attrs[ATTR_CLIENT_ID] = client.get("id")
            attrs[ATTR_APP] = client.get("app")
            attrs[ATTR_BACKEND] = client.get("backend")
            attrs[ATTR_USER] = client.get("user")
            attrs[ATTR_HOST] = client.get("host")
            attrs[ATTR_CORKED] = client.get("corked")
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        return attrs

    def _get_client(self) -> dict[str, Any] | None:
        """Get the audio client for this service."""
        if self.coordinator is None or not self.coordinator.data:
            return None
        service_name = self._service_info["name"].replace(".service", "")
        for client in self.coordinator.data.get("audio", []):
            client_name = client.get("name", "").lower()
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()
            if service_name in [client_name, app, binary]:
                return client
        return None

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning on service %s/%s", scope, unit)
        await self._api_client.control_service("enable", scope, unit)
        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        if self.coordinator is not None:
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        scope = self._service_info["scope"]
        unit = self._service_info["name"]
        _LOGGER.debug("Turning off service %s/%s", scope, unit)
        await self._api_client.control_service("disable", scope, unit)
        await asyncio.sleep(1)
        await self._service_coordinator.async_request_refresh()
        if self.coordinator is not None:
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        if await self._delegate_to_hass("volume_set", {"volume_level": volume}):
            return
        client = self._get_client()
        if not client:
            _LOGGER.warning(
                "No client found for service %s/%s, cannot set volume",
                self._service_info["scope"],
                self._service_info["name"],
            )
            return
        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return
        await self._api_client.set_client_volume(client_name, volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        if await self._delegate_to_hass("volume_mute", {"is_volume_muted": mute}):
            return
        client = self._get_client()
        if not client:
            _LOGGER.warning(
                "No client found for service %s/%s, cannot mute",
                self._service_info["scope"],
                self._service_info["name"],
            )
            return
        client_name = client.get("name")
        if not client_name:
            _LOGGER.error("Client has no name: %s", client)
            return
        await self._api_client.set_client_mute(client_name, mute)


class OdioPulseClientMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of a standalone audio client using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(self, ctx: _MediaPlayerContext, initial_client: dict[str, Any]) -> None:
        """Initialize the standalone client."""
        assert ctx.audio_coordinator is not None
        super().__init__(ctx.audio_coordinator)
        self._api_client = ctx.api
        self._connectivity = ctx.connectivity_coordinator

        self._client_name = initial_client.get("name", "")
        self._client_host = initial_client.get("host", "")

        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._client_name.lower()).strip("_")
        self._attr_unique_id = f"{ctx.entry_id}_remote_{safe_name}"
        self._attr_name = self._client_name
        self._attr_device_info = ctx.device_info

        _LOGGER.debug(
            "Created standalone client entity for '%s' from host '%s' with unique_id '%s'",
            self._client_name,
            self._client_host,
            self._attr_unique_id,
        )

    @property
    def _server_hostname(self) -> str | None:
        """Return the live server hostname from the connectivity coordinator."""
        return (
            self._connectivity.data.get("hostname")
            if self._connectivity.data
            else None
        )

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"client:{self._client_name}"

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        mapped_state = self._map_state_from_entity(self._get_current_client)
        if mapped_state is not None:
            return mapped_state
        client = self._get_current_client()
        if not client:
            return MediaPlayerState.OFF
        if not client.get("corked", True):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.VOLUME_SET
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume
        client = self._get_current_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted
        client = self._get_current_client()
        if client:
            return client.get("muted", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        client = self._get_current_client()
        attrs = {
            "client_name": self._client_name,
            "remote_host": self._client_host,
            "server_hostname": self._server_hostname,
        }
        if self._mapped_entity:
            attrs["mapped_entity"] = self._mapped_entity
        if not client:
            attrs["status"] = "disconnected"
            return attrs
        attrs["status"] = "connected"
        attrs[ATTR_CLIENT_ID] = client.get("id")
        attrs[ATTR_APP] = client.get("app")
        attrs[ATTR_BACKEND] = client.get("backend")
        attrs[ATTR_USER] = client.get("user")
        attrs[ATTR_HOST] = client.get("host")
        attrs[ATTR_CORKED] = client.get("corked")
        props = client.get("props", {})
        if "native-protocol.peer" in props:
            attrs["connection"] = props["native-protocol.peer"]
        if "application.process.host" in props:
            attrs["remote_host"] = props["application.process.host"]
        if "application.version" in props:
            attrs["app_version"] = props["application.version"]
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True

    def _get_current_client(self) -> dict[str, Any] | None:
        """Get the current client data from coordinator by NAME."""
        if not self.coordinator.data:
            return None
        for client in self.coordinator.data.get("audio", []):
            if client.get("name") == self._client_name:
                return client
        return None

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._set_volume_with_fallback(volume, get_client_name, self._api_client)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        def get_client_name():
            client = self._get_current_client()
            return client.get("name") if client else None

        await self._mute_with_fallback(mute, get_client_name, self._api_client)
