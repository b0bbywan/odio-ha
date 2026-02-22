"""Media player platform for Odio Audio."""
from __future__ import annotations

import asyncio
import logging
import re

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OdioAudioConfigEntry
from .api_client import OdioApiClient
from .const import (
    DOMAIN,
    ATTR_CLIENT_ID,
    ATTR_APP,
    ATTR_BACKEND,
    ATTR_USER,
    ATTR_HOST,
    ATTR_CORKED,
    ATTR_SERVICE_SCOPE,
    ATTR_SERVICE_ENABLED,
    ATTR_SERVICE_ACTIVE,
    SUPPORTED_SERVICES,
)
from .coordinator import OdioAudioCoordinator, OdioServiceCoordinator
from .mixins import MappedEntityMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OdioAudioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Odio Audio media player based on a config entry."""
    runtime_data = config_entry.runtime_data
    audio_coordinator = runtime_data.audio_coordinator
    service_coordinator = runtime_data.service_coordinator
    api_client = runtime_data.api

    # Get server hostname to identify remote clients
    server_hostname = None
    if service_coordinator.data:
        server_info = service_coordinator.data.get("server", {})
        server_hostname = server_info.get("hostname")

    _LOGGER.debug("Server hostname: %s", server_hostname)

    # Create main receiver entity
    entities: list[MediaPlayerEntity] = [
        OdioReceiverMediaPlayer(
            audio_coordinator,
            service_coordinator,
            api_client,
            config_entry.entry_id,
        )
    ]

    # Track which clients are handled by services
    handled_client_patterns = set()

    # Create service entities
    if service_coordinator.data:
        services = service_coordinator.data.get("services", [])
        for service in services:
            if (
                service.get("exists") and service.get("enabled") and service["name"]
                in SUPPORTED_SERVICES
            ):
                serviceEntity = OdioServiceMediaPlayer(
                    audio_coordinator,
                    service_coordinator,
                    api_client,
                    config_entry.entry_id,
                    service,
                )
                entities.append(serviceEntity)

                # Track this service's client pattern
                service_name = service["name"].replace(".service", "").lower()
                handled_client_patterns.add(service_name)

    # Create entities for standalone clients
    if audio_coordinator.data:
        audio = audio_coordinator.data.get("audio", [])
        for client in audio:
            client_name = client.get("name", "")
            client_host = client.get("host", "")

            # Only create standalone entity for remote clients
            is_remote = server_hostname and client_host and client_host != server_hostname

            if not is_remote or not client_name:
                continue

            audioEntity = OdioStandaloneClientMediaPlayer(
                audio_coordinator,
                api_client,
                config_entry.entry_id,
                client,
                server_hostname,
            )
            entities.append(audioEntity)

    _LOGGER.info(
        "Creating %d media_player entities (1 receiver + %d services + %d standalone clients)",
        len(entities),
        len([e for e in entities if isinstance(e, OdioServiceMediaPlayer)]),
        len([e for e in entities if isinstance(e, OdioStandaloneClientMediaPlayer)]),
    )

    async_add_entities(entities)

    # Track known standalone clients
    known_remote_clients = {
        entity._client_name: entity
        for entity in entities
        if isinstance(entity, OdioStandaloneClientMediaPlayer)
    }

    # Set up listener to detect new remote clients
    @callback
    def _async_check_new_clients():
        """Check for new remote clients and create entities."""
        if not audio_coordinator.data or not server_hostname:
            return

        new_entities = []

        for client in audio_coordinator.data.get("audio", []):
            client_name = client.get("name", "")
            client_host = client.get("host", "")
            app = client.get("app", "").lower()
            binary = client.get("binary", "").lower()

            # Only process remote clients
            is_remote = client_host and client_host != server_hostname
            if not is_remote or not client_name:
                continue

            # Skip if we already have an entity
            if client_name in known_remote_clients:
                continue

            # Skip if handled by a service
            is_handled = any(
                pattern in [client_name.lower(), app, binary]
                for pattern in handled_client_patterns
            )
            if is_handled:
                continue

            # Create new entity
            _LOGGER.info("Detected new remote client: '%s' from host '%s'", client_name, client_host)

            entity = OdioStandaloneClientMediaPlayer(
                audio_coordinator,
                api_client,
                config_entry.entry_id,
                client,
                server_hostname,
            )
            new_entities.append(entity)
            known_remote_clients[client_name] = entity

        if new_entities:
            _LOGGER.info("Adding %d new remote client entities", len(new_entities))
            async_add_entities(new_entities)

    # Listen for coordinator updates
    config_entry.async_on_unload(
        audio_coordinator.async_add_listener(_async_check_new_clients)
    )


class OdioReceiverMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of the main Odio Audio receiver."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        audio_coordinator: OdioAudioCoordinator,
        service_coordinator: OdioServiceCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
    ) -> None:
        """Initialize the receiver."""
        super().__init__(audio_coordinator)
        self._service_coordinator = service_coordinator
        self._api_client = api_client
        self._attr_unique_id = f"{entry_id}_receiver"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "PulseAudio Receiver",
        }

        if service_coordinator.data:
            server = service_coordinator.data.get("server", {})
            if server:
                self._attr_device_info["sw_version"] = server.get("version")
                self._attr_device_info["configuration_url"] = api_client._api_url

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        if not self.coordinator.data:
            return MediaPlayerState.OFF

        clients = self.coordinator.data.get("audio", [])
        # Check if any client is playing
        for client in clients:
            if not client.get("corked", True):
                return MediaPlayerState.PLAYING

        # Check if any clients exist
        if self.coordinator.data:
            return MediaPlayerState.IDLE

        return MediaPlayerState.OFF

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        return MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        if not self.coordinator.data:
            return None

        clients = self.coordinator.data.get("audio", [])
        volumes = [client.get("volume", 0) for client in clients]
        if volumes:
            return sum(volumes) / len(volumes)
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        if not self.coordinator.data:
            return False

        clients = self.coordinator.data.get("audio", [])
        return any(client.get("muted", False) for client in clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        if self.coordinator.data:
            clients = self.coordinator.data.get("audio", [])
            attrs["active_clients"] = len(clients)
            attrs["playing_clients"] = len([
                client for client in clients
                if not client.get("corked", True)
            ])

        if self._service_coordinator.data:
            server = self._service_coordinator.data.get("server", {})
            if server:
                attrs["server_name"] = server.get("name")
                attrs["server_hostname"] = server.get("hostname")
                attrs["default_sink"] = server.get("default_sink")

        return attrs

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._api_client.set_server_volume(volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._api_client.set_server_mute(mute)


class OdioServiceMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of an Odio Audio service using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(
        self,
        audio_coordinator: OdioAudioCoordinator,
        service_coordinator: OdioServiceCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
        service_info: dict[str, Any],
    ) -> None:
        """Initialize the service."""
        super().__init__(audio_coordinator)
        self._service_coordinator = service_coordinator
        self._api_client = api_client
        self._service_info = service_info

        service_name = service_info["name"]
        scope = service_info["scope"]

        self._attr_unique_id = f"{entry_id}_service_{scope}_{service_name}"
        self._attr_name = f"{service_name} ({scope})"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "PulseAudio Receiver",
        }

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
        # Try to map from mapped entity if available
        mapped_state = self._map_state_from_entity(self._is_service_running)
        if mapped_state is not None:
            return mapped_state

        # Fallback to original logic
        if not self._is_service_running():
            return MediaPlayerState.OFF

        # Check if service has an active audio client
        if self.coordinator.data:
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
            services = self._service_coordinator.data.get("services", [])
            for svc in services:
                if (
                    svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]
                ):
                    return svc.get("running", False)
        return False

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        base_features = (
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF | MediaPlayerEntityFeature.VOLUME_MUTE
        )

        # Add volume control if client is found
        if self._get_client():
            base_features |= MediaPlayerEntityFeature.VOLUME_SET

        # Add features from mapped entity if available
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Prefer mapped entity volume if available
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume

        # Fallback to client volume
        client = self._get_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        # Prefer mapped entity mute state if available
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted

        # Fallback to client mute
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
            services = self._service_coordinator.data.get("services", [])
            for svc in services:
                if (
                    svc["name"] == self._service_info["name"] and svc["scope"] == self._service_info["scope"]
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
        if not self.coordinator.data:
            return None

        service_name = self._service_info["name"].replace(".service", "")
        clients = self.coordinator.data.get("audio", [])
        for client in clients:
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
        await asyncio.sleep(0.5)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Try to delegate to mapped entity first
        if await self._delegate_to_hass("volume_set", {"volume_level": volume}):
            return

        # Fallback to PulseAudio client volume
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
        # Try mapped entity first
        if await self._delegate_to_hass("volume_mute", {"is_volume_muted": mute}):
            return

        # Fallback to PulseAudio client mute
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


class OdioStandaloneClientMediaPlayer(MappedEntityMixin, CoordinatorEntity, MediaPlayerEntity):
    """Representation of a standalone audio client using MappedEntityMixin."""

    _attr_has_entity_name = True

    def __init__(
        self,
        audio_coordinator: OdioAudioCoordinator,
        api_client: OdioApiClient,
        entry_id: str,
        initial_client: dict[str, Any],
        server_hostname: str | None = None,
    ) -> None:
        """Initialize the standalone client."""
        super().__init__(audio_coordinator)
        self._api_client = api_client
        self._server_hostname = server_hostname

        # Use client NAME as stable identifier
        self._client_name = initial_client.get("name", "")
        self._client_host = initial_client.get("host", "")

        # Generate a stable unique_id
        safe_name = re.sub(r"[^a-z0-9_]+", "_", self._client_name.lower()).strip("_")
        self._attr_unique_id = f"{entry_id}_remote_{safe_name}"
        self._attr_name = self._client_name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Odio Audio Receiver",
            "manufacturer": "Odio",
            "model": "Media Hub",
        }

        _LOGGER.debug(
            "Created standalone client entity for '%s' from host '%s' with unique_id '%s'",
            self._client_name,
            self._client_host,
            self._attr_unique_id,
        )

    @property
    def _mapping_key(self) -> str:
        """Return the key used in service_mappings."""
        return f"client:{self._client_name}"

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the device."""
        # Try to map from mapped entity if available
        mapped_state = self._map_state_from_entity(self._get_current_client)
        if mapped_state is not None:
            return mapped_state

        # Fallback to original logic
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

        # Add features from mapped entity if available
        mapped_features = self._get_mapped_attribute("supported_features")
        return self._get_supported_features(base_features, mapped_features)

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Prefer mapped entity volume if available
        volume = self._get_mapped_attribute("volume_level")
        if volume is not None:
            return volume

        # Fallback to client volume
        client = self._get_current_client()
        if client:
            return client.get("volume")
        return None

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        # Prefer mapped entity mute state if available
        muted = self._get_mapped_attribute("is_volume_muted")
        if muted is not None:
            return muted

        # Fallback to client mute
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

        # Add interesting props if available
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

        clients = self.coordinator.data.get("audio", [])
        for client in clients:
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
