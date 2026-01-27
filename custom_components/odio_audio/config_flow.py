"""Config flow for Odio Audio integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
    DEFAULT_NAME,
    ENDPOINT_SERVER,
    ENDPOINT_SERVICES,
    SUPPORTED_SERVICES,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api(hass: HomeAssistant, api_url: str) -> dict[str, Any]:
    """Validate the API connection."""
    _LOGGER.debug("Starting API validation for URL: %s", api_url)

    session = async_get_clientsession(hass)

    try:
        # Test server endpoint
        server_url = f"{api_url}{ENDPOINT_SERVER}"
        _LOGGER.debug("Testing server endpoint: %s", server_url)

        async with session.get(
            server_url,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            _LOGGER.debug("Server endpoint status: %s", response.status)

            if response.status != 200:
                error_text = await response.text()
                _LOGGER.error("Server endpoint returned %s: %s", response.status, error_text)
                raise ValueError(f"Server returned status {response.status}")

            server_info = await response.json()
            _LOGGER.debug("Server info received: %s", server_info)

        # Test services endpoint
        services_url = f"{api_url}{ENDPOINT_SERVICES}"
        _LOGGER.debug("Testing services endpoint: %s", services_url)

        async with session.get(
            services_url,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            _LOGGER.debug("Services endpoint status: %s", response.status)
            _LOGGER.debug("Services endpoint content-type: %s", response.content_type)

            if response.status != 200:
                error_text = await response.text()
                _LOGGER.error("Services endpoint returned %s: %s", response.status, error_text)
                raise ValueError(f"Services returned status {response.status}")

            # Handle both application/json and text/plain
            text = await response.text()
            try:
                import json
                services = json.loads(text)
                _LOGGER.debug("Services received: %d services found", len(services))
            except json.JSONDecodeError as err:
                _LOGGER.error("Failed to parse services response as JSON: %s", text[:200])
                raise ValueError(f"Invalid JSON response: {err}") from err

        _LOGGER.info("API validation successful")
        return {
            "server_info": server_info,
            "services": services,
        }

    except aiohttp.ClientConnectorError as err:
        _LOGGER.error("Connection error - cannot reach API at %s: %s", api_url, err)
        raise ValueError(f"Cannot connect to {api_url}") from err

    except aiohttp.ClientError as err:
        _LOGGER.error("HTTP client error: %s", err)
        raise ValueError(f"HTTP error: {err}") from err

    except Exception as err:
        _LOGGER.exception("Unexpected error during API validation")
        raise ValueError(f"Unexpected error: {err}") from err


class OdioAudioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Odio Audio."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._api_url: str | None = None
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._service_scan_interval: int = DEFAULT_SERVICE_SCAN_INTERVAL
        self._services: list[dict[str, Any]] = []
        self._entities: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            _LOGGER.debug("Processing user input: %s", {k: v for k, v in user_input.items() if k != CONF_API_URL})

            try:
                # Validate API
                info = await validate_api(self.hass, user_input[CONF_API_URL])

                self._api_url = user_input[CONF_API_URL]
                self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                self._service_scan_interval = user_input.get(
                    CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
                )

                # Filter enabled services
                self._services = [
                    svc for svc in info["services"]
                    if svc.get("exists") and svc.get("enabled")
                    and svc["name"] in SUPPORTED_SERVICES
                ]

                _LOGGER.info("Found %d enabled services", len(self._services))

                # Get all media_player entities for mapping
                self._entities = [
                    entity_id
                    for entity_id in self.hass.states.async_entity_ids("media_player")
                ]

                _LOGGER.debug("Found %d existing media_player entities", len(self._entities))

                return await self.async_step_services()

            except ValueError as err:
                _LOGGER.error("Validation error: %s", err)
                errors["base"] = "cannot_connect"

            except Exception as err:
                _LOGGER.exception("Unexpected exception during setup")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_URL, default="http://localhost:8080"): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                    vol.Optional(
                        CONF_SERVICE_SCAN_INTERVAL, default=DEFAULT_SERVICE_SCAN_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                }
            ),
            errors=errors,
        )

    async def async_step_services(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle service mapping step."""
        if user_input is not None:
            _LOGGER.debug("Processing service mappings")

            # Build service mappings from user input
            mappings = {}
            for service in self._services:
                key = f"{service['scope']}_{service['name']}"
                if key in user_input and user_input[key]:
                    mappings[f"{service['scope']}/{service['name']}"] = user_input[key]
                    _LOGGER.debug("Mapped %s/%s to %s", service['scope'], service['name'], user_input[key])

            _LOGGER.info("Creating config entry with %d service mappings", len(mappings))

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_API_URL: self._api_url,
                    CONF_SERVICE_MAPPINGS: mappings,
                },
                options={
                    CONF_SCAN_INTERVAL: self._scan_interval,
                    CONF_SERVICE_SCAN_INTERVAL: self._service_scan_interval,
                },
            )

        # Build schema for service mappings
        schema = {}
        for service in self._services:
            key = f"{service['scope']}_{service['name']}"
            description = service.get("description", service["name"])
            schema[vol.Optional(key)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    multiple=False,
                )
            )

        if not schema:
            # No services to map, create entry directly
            _LOGGER.info("No services to map, creating entry directly")

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_API_URL: self._api_url,
                    CONF_SERVICE_MAPPINGS: {},
                },
                options={
                    CONF_SCAN_INTERVAL: self._scan_interval,
                    CONF_SERVICE_SCAN_INTERVAL: self._service_scan_interval,
                },
            )

        return self.async_show_form(
            step_id="services",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "services_info": "Associez vos services audio à des entités existantes dans Home Assistant (optionnel)"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OdioAudioOptionsFlow:
        """Get the options flow for this handler."""
        return OdioAudioOptionsFlow(config_entry)


class OdioAudioOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Odio Audio."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._step = "init"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - main menu."""
        if user_input is not None:
            if user_input.get("next_step") == "intervals":
                return await self.async_step_intervals()
            elif user_input.get("next_step") == "mappings":
                return await self.async_step_mappings()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("next_step", default="intervals"): vol.In({
                    "intervals": "Modifier les intervalles de scan",
                    "mappings": "Gérer les associations d'entités",
                }),
            }),
        )

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure scan intervals."""
        if user_input is not None:
            _LOGGER.info("Updating intervals: scan_interval=%s, service_scan_interval=%s",
                        user_input.get(CONF_SCAN_INTERVAL),
                        user_input.get(CONF_SERVICE_SCAN_INTERVAL))

            # Keep existing mappings, only update intervals
            new_options = dict(self._config_entry.options)
            new_options[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            new_options[CONF_SERVICE_SCAN_INTERVAL] = user_input[CONF_SERVICE_SCAN_INTERVAL]

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="intervals",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                    vol.Optional(
                        CONF_SERVICE_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                }
            ),
        )

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure entity mappings for services and standalone clients."""
        if user_input is not None:
            _LOGGER.debug("Processing mapping updates")

            # Build new service mappings from user input
            service_mappings = dict(self._config_entry.data.get(CONF_SERVICE_MAPPINGS, {}))

            # Get current data from coordinator to find all mappable entities
            coordinator_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
            if coordinator_data:
                service_coordinator = coordinator_data["service_coordinator"]
                audio_coordinator = coordinator_data["audio_coordinator"]

                # Update service mappings
                if service_coordinator.data:
                    services = service_coordinator.data.get("services", [])
                    for service in services:
                        if service.get("exists") and service.get("enabled") and service["name"] in SUPPORTED_SERVICES:
                            key = f"{service['scope']}_{service['name']}"
                            service_key = f"{service['scope']}/{service['name']}"
                            if key in user_input and user_input[key]:
                                service_mappings[service_key] = user_input[key]
                            elif service_key in service_mappings and not user_input.get(key):
                                # Remove mapping if cleared
                                del service_mappings[service_key]

                # Handle standalone client mappings
                # We'll store these separately with a "client:" prefix to distinguish them
                if audio_coordinator.data:
                    server_hostname = None
                    if service_coordinator.data:
                        server_hostname = service_coordinator.data.get("server", {}).get("hostname")

                    for client in audio_coordinator.data:
                        client_name = client.get("name", "")
                        client_host = client.get("host", "")

                        # Only process remote clients
                        is_remote = server_hostname and client_host and client_host != server_hostname
                        if not is_remote or not client_name:
                            continue

                        import re
                        safe_name = re.sub(r'[^a-z0-9_]+', '_', client_name.lower()).strip('_')
                        key = f"client_{safe_name}"
                        client_mapping_key = f"client:{client_name}"

                        if key in user_input and user_input[key]:
                            service_mappings[client_mapping_key] = user_input[key]
                        elif client_mapping_key in service_mappings and not user_input.get(key):
                            # Remove mapping if cleared
                            del service_mappings[client_mapping_key]

            _LOGGER.info("Updating mappings: %d total mappings", len(service_mappings))

            # Update config entry data (not options, as mappings are in data)
            new_data = dict(self._config_entry.data)
            new_data[CONF_SERVICE_MAPPINGS] = service_mappings

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data,
            )

            # Keep existing options unchanged
            return self.async_create_entry(title="", data=dict(self._config_entry.options))

        # Build schema for all mappable entities (services + standalone clients)
        schema = {}

        coordinator_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if not coordinator_data:
            return self.async_abort(reason="not_loaded")

        service_coordinator = coordinator_data["service_coordinator"]
        audio_coordinator = coordinator_data["audio_coordinator"]
        current_mappings = self._config_entry.data.get(CONF_SERVICE_MAPPINGS, {})

        # Add services
        if service_coordinator.data:
            services = service_coordinator.data.get("services", [])
            for service in services:
                if service.get("exists") and service.get("enabled") and service["name"] in SUPPORTED_SERVICES:
                    key = f"{service['scope']}_{service['name']}"
                    service_key = f"{service['scope']}/{service['name']}"
                    description = service.get("description", service["name"])
                    default_value = current_mappings.get(service_key)

                    schema[vol.Optional(key, default=default_value)] = selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="media_player",
                            multiple=False,
                        )
                    )

        # Add standalone clients
        if audio_coordinator.data:
            server_hostname = None
            if service_coordinator.data:
                server_hostname = service_coordinator.data.get("server", {}).get("hostname")

            for client in audio_coordinator.data:
                client_name = client.get("name", "")
                client_host = client.get("host", "")

                # Only show remote clients
                is_remote = server_hostname and client_host and client_host != server_hostname
                if not is_remote or not client_name:
                    continue

                import re
                safe_name = re.sub(r'[^a-z0-9_]+', '_', client_name.lower()).strip('_')
                key = f"client_{safe_name}"
                client_mapping_key = f"client:{client_name}"
                default_value = current_mappings.get(client_mapping_key)

                schema[vol.Optional(key, description={"suggested_value": default_value} if default_value else None)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="media_player",
                        multiple=False,
                    )
                )

        if not schema:
            return self.async_abort(reason="no_mappable_entities")

        return self.async_show_form(
            step_id="mappings",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "info": "Associez vos services et clients distants à des entités media_player existantes. Laissez vide pour supprimer l'association."
            },
        )
