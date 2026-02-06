"""Config flow for Odio Audio integration"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import OdioApiClient
from .const import (
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    CONF_SERVICE_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
    DOMAIN,
    SUPPORTED_SERVICES,
)
from .config_flow_helpers import (
    build_mapping_schema,
    parse_mappings_from_input,
    get_service_keys,
    get_client_keys,
)

_LOGGER = logging.getLogger(__name__)

# =============================================================================
# Exceptions
# =============================================================================


class OdioConfigError(Exception):
    """Base exception for Odio config errors."""


class CannotConnect(OdioConfigError):
    """Error to indicate we cannot connect."""


class InvalidResponse(OdioConfigError):
    """Error to indicate invalid API response."""


# =============================================================================
# Validation
# =============================================================================


async def async_validate_api(hass: HomeAssistant, api_url: str) -> dict[str, Any]:
    """Validate the API connection and return server info and services.

    Raises:
        CannotConnect: If connection fails.
        InvalidResponse: If API returns invalid data.
    """
    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    try:
        server_info = await api.get_server_capabilities()
        services = await api.get_services()
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
        raise CannotConnect(str(err)) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during API validation")
        raise CannotConnect(str(err)) from err

    if not isinstance(services, list):
        raise InvalidResponse("Invalid API response")

    _LOGGER.info("API validation successful")
    return {
        "server_info": server_info,
        "services": services,
    }


async def async_fetch_available_services(
    hass: HomeAssistant, api_url: str
) -> list[dict[str, Any]]:
    """Fetch available services from API.

    Returns list of enabled, supported services.
    """
    try:
        info = await async_validate_api(hass, api_url)
        return [
            svc
            for svc in info.get("services", [])
            if svc.get("exists") and svc.get("enabled") and svc.get("name")
            in SUPPORTED_SERVICES
        ]
    except OdioConfigError:
        return []


async def async_fetch_remote_clients(
    hass: HomeAssistant, api_url: str
) -> list[dict[str, Any]]:
    """Fetch remote clients (not on server host)."""
    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    try:
        server_info = await api.get_server_info()
        clients = await api.get_clients()
    except Exception:
        return []

    server_hostname = server_info.get("hostname")

    return [
        client
        for client in clients
        if client.get("host") and client.get("host") != server_hostname
    ]


# =============================================================================
# Schema helpers
# =============================================================================


def add_suggested_values_to_schema(
    data_schema: vol.Schema, suggested_values: dict[str, Any]
) -> vol.Schema:
    """Make a copy of the schema, populated with suggested values."""
    schema: dict[Any, Any] = {}
    for key, val in data_schema.schema.items():
        new_key = key
        if isinstance(key, vol.Marker):
            key_str = str(key.schema) if hasattr(key, "schema") else str(key)
            if key_str in suggested_values:
                new_key = deepcopy(key)
                new_key.description = {"suggested_value": suggested_values[key_str]}
        schema[new_key] = val
    return vol.Schema(schema)


# =============================================================================
# Schemas
# =============================================================================

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_URL, default="http://localhost:8080"): str,
    }
)

STEP_OPTIONS_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
        vol.Optional(
            CONF_SERVICE_SCAN_INTERVAL, default=DEFAULT_SERVICE_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
    }
)


# =============================================================================
# Config Flow
# =============================================================================


class OdioAudioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Odio Audio."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._services: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OdioAudioOptionsFlow:
        """Get the options flow for this handler."""
        return OdioAudioOptionsFlow()

    async def _async_validate_api_url(self, api_url: str) -> dict[str, str]:
        """Validate API URL and populate services.

        Returns dict of errors (empty if valid).
        """
        errors: dict[str, str] = {}

        try:
            info = await async_validate_api(self.hass, api_url)
            self._services = [
                svc
                for svc in info.get("services", [])
                if svc.get("exists") and svc.get("enabled") and svc.get("name")
                in SUPPORTED_SERVICES
            ]
            _LOGGER.info("Found %d enabled services", len(self._services))

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidResponse:
            errors["base"] = "invalid_response"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during API validation")
            errors["base"] = "unknown"

        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - API URL configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_url = user_input[CONF_API_URL]

            # Check if already configured
            await self.async_set_unique_id(api_url)
            self._abort_if_unique_id_configured()

            # Validate API
            errors = await self._async_validate_api_url(api_url)

            if not errors:
                self._data[CONF_API_URL] = api_url
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle scan interval options."""
        if user_input is not None:
            self._options[CONF_SCAN_INTERVAL] = user_input.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )
            self._options[CONF_SERVICE_SCAN_INTERVAL] = user_input.get(
                CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
            )
            return await self.async_step_services()

        return self.async_show_form(
            step_id="options",
            data_schema=STEP_OPTIONS_DATA_SCHEMA,
        )

    async def async_step_services(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle service mapping step."""
        if user_input is not None:
            # Parse mappings using generic helper
            mappings = parse_mappings_from_input(
                user_input,
                self._services,
                None,
                get_service_keys,
                preserve_others=False,
            )
            self._options[CONF_SERVICE_MAPPINGS] = mappings

            return self._create_entry()

        # No services to map - create entry directly
        if not self._services:
            self._options[CONF_SERVICE_MAPPINGS] = {}
            return self._create_entry()

        # Build schema using generic helper
        schema = build_mapping_schema(self._services, None, get_service_keys)

        return self.async_show_form(
            step_id="services",
            data_schema=schema,
            description_placeholders={
                "services_info": (
                    "Associez vos services audio à des entités media_player "
                    "existantes dans Home Assistant (optionnel)."
                )
            },
        )

    def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=DEFAULT_NAME,
            data=self._data,
            options=self._options,
        )


# =============================================================================
# Options Flow
# =============================================================================


class OdioAudioOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Odio Audio."""

    def __init__(self) -> None:
        """Initialize options flow."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._services: list[dict[str, Any]] = []
        self._clients: list[dict[str, Any]] = []

    async def _async_fetch_mappable_entities(self, api_url: str) -> None:
        """Fetch services and clients that can be mapped."""
        self._services = await async_fetch_available_services(self.hass, api_url)
        self._clients = await async_fetch_remote_clients(self.hass, api_url)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options - show menu."""
        # Initialize from current config
        self._data = dict(self.config_entry.data)
        self._options = dict(self.config_entry.options)

        return self.async_show_menu(
            step_id="init",
            menu_options=["intervals", "mappings"],
            description_placeholders={
                "name": self.config_entry.title,
            },
        )

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure scan intervals."""
        if user_input is not None:
            new_options = dict(self._options)
            new_options[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            new_options[CONF_SERVICE_SCAN_INTERVAL] = user_input[
                CONF_SERVICE_SCAN_INTERVAL
            ]

            _LOGGER.info(
                "Updating intervals: scan=%s, service_scan=%s",
                new_options[CONF_SCAN_INTERVAL],
                new_options[CONF_SERVICE_SCAN_INTERVAL],
            )

            return self.async_create_entry(title="", data=new_options)

        # Build schema with current values as suggested
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                ),
                vol.Optional(CONF_SERVICE_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=600)
                ),
            }
        )

        suggested = {
            CONF_SCAN_INTERVAL: self._options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
            CONF_SERVICE_SCAN_INTERVAL: self._options.get(
                CONF_SERVICE_SCAN_INTERVAL, DEFAULT_SERVICE_SCAN_INTERVAL
            ),
        }

        return self.async_show_form(
            step_id="intervals",
            data_schema=add_suggested_values_to_schema(schema, suggested),
        )

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure entity mappings for services and clients."""
        api_url = self._data.get(CONF_API_URL)

        if not api_url:
            return self.async_abort(reason="no_api_url")

        # Fetch current mappable entities from API
        await self._async_fetch_mappable_entities(api_url)

        current_mappings = self._options.get(CONF_SERVICE_MAPPINGS, {})

        if user_input is not None:
            _LOGGER.debug("user_input received: %s", user_input)
            _LOGGER.debug("current_mappings before parse: %s", current_mappings)

            # Parse service mappings using generic helper
            new_mappings = parse_mappings_from_input(
                user_input,
                self._services,
                current_mappings,
                get_service_keys,
                preserve_others=True,  # Preserve client mappings
            )
            _LOGGER.debug("after service parse: %s", new_mappings)

            # Parse client mappings using generic helper
            new_mappings = parse_mappings_from_input(
                user_input,
                self._clients,
                new_mappings,
                get_client_keys,
                preserve_others=True,  # Preserve offline client mappings
            )
            _LOGGER.debug("after client parse: %s", new_mappings)

            _LOGGER.info("Updating mappings: %d total", len(new_mappings))

            new_options = dict(self._options)
            new_options[CONF_SERVICE_MAPPINGS] = new_mappings
            _LOGGER.debug("new_options to save: %s", new_options)

            return self.async_create_entry(title="", data=new_options)

        # Build combined schema for services and clients
        if not self._services and not self._clients:
            return self.async_abort(reason="no_mappable_entities")

        schema_dict: dict[Any, Any] = {}

        # Add service selectors using generic helper
        if self._services:
            service_schema = build_mapping_schema(
                self._services, current_mappings, get_service_keys
            )
            schema_dict.update(service_schema.schema)

        # Add client selectors using generic helper
        if self._clients:
            client_schema = build_mapping_schema(
                self._clients, current_mappings, get_client_keys
            )
            schema_dict.update(client_schema.schema)

        return self.async_show_form(
            step_id="mappings",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "info": (
                    "Associez vos services et clients distants à des entités "
                    "media_player existantes. Laissez vide pour supprimer l'association."
                )
            },
        )
