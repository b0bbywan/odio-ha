"""Config flow for Odio Remote integration"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
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
    CONF_KEEPALIVE_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_NAME,
    DOMAIN,
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

    Calls GET /server to check connectivity and discover enabled backends.
    If the systemd backend is enabled, also fetches services.

    Raises:
        CannotConnect: If connection fails.
        InvalidResponse: If API returns invalid data.
    """
    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    try:
        server_info = await api.get_server_info()
    except Exception as err:
        raise CannotConnect from err

    if not isinstance(server_info, dict):
        raise InvalidResponse("Invalid API response")

    backends = server_info.get("backends", {})
    services: list[dict[str, Any]] = []

    if backends.get("systemd"):
        try:
            services = await api.get_services()
        except Exception as err:
            raise CannotConnect from err
        if not isinstance(services, list):
            raise InvalidResponse("Invalid services response")

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
            if svc.get("exists")
        ]
    except OdioConfigError:
        return []


async def async_fetch_remote_clients(
    hass: HomeAssistant, api_url: str
) -> list[dict[str, Any]]:
    """Fetch remote clients (not on server host).

    Only fetches audio clients if the pulseaudio backend is enabled.
    """
    session = async_get_clientsession(hass)
    api = OdioApiClient(api_url, session)

    try:
        server_info = await api.get_server_info()
    except Exception:
        return []

    if not server_info.get("backends", {}).get("pulseaudio"):
        return []

    try:
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
        vol.Required(CONF_API_URL, default="http://localhost:8018"): str,
    }
)


# =============================================================================
# Config Flow
# =============================================================================


class OdioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Odio Remote."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._services: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OdioOptionsFlow:
        """Get the options flow for this handler."""
        return OdioOptionsFlow()

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
                if svc.get("exists")
            ]
            _LOGGER.info("Found %d existing services", len(self._services))

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
                return await self.async_step_sse()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        _LOGGER.debug(
            "Zeroconf discovery: host=%s addresses=%s port=%s hostname=%s",
            discovery_info.host,
            discovery_info.addresses,
            discovery_info.port,
            discovery_info.hostname,
        )
        # Prefer IPv4 — API only supports IPv4; IPv6 addresses contain ":"
        host = next(
            (addr for addr in discovery_info.addresses if ":" not in addr),
            discovery_info.host,
        )
        if host != discovery_info.host:
            _LOGGER.debug(
                "Zeroconf: picked IPv4 %s over host %s", host, discovery_info.host
            )
        port = discovery_info.port
        api_url = f"http://{host}:{port}"

        await self.async_set_unique_id(api_url)
        self._abort_if_unique_id_configured()

        self._data[CONF_API_URL] = api_url

        # Strip .local. suffix for human-readable display
        hostname = discovery_info.hostname.rstrip(".").removesuffix(".local")
        self.context["title_placeholders"] = {"host": hostname or host}

        _LOGGER.debug("Zeroconf: will configure api_url=%s", api_url)
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered Odio instance."""
        if user_input is not None:
            errors = await self._async_validate_api_url(self._data[CONF_API_URL])
            if errors:
                return self.async_abort(reason="cannot_connect")
            return await self.async_step_sse()

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "host": self.context["title_placeholders"]["host"],
                "api_url": self._data[CONF_API_URL],
            },
        )

    async def async_step_sse(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure SSE keepalive interval."""
        if user_input is not None:
            self._options[CONF_KEEPALIVE_INTERVAL] = user_input.get(
                CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL
            )
            return await self.async_step_services()

        schema = vol.Schema(
            {
                vol.Optional(CONF_KEEPALIVE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=120)
                ),
            }
        )

        return self.async_show_form(
            step_id="sse",
            data_schema=add_suggested_values_to_schema(
                schema, {CONF_KEEPALIVE_INTERVAL: DEFAULT_KEEPALIVE_INTERVAL}
            ),
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


class OdioOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Odio Remote."""

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
            menu_options=["sse", "mappings"],
            description_placeholders={
                "name": self.config_entry.title,
            },
        )

    async def async_step_sse(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure SSE keepalive interval."""
        if user_input is not None:
            new_options = dict(self._options)
            new_options[CONF_KEEPALIVE_INTERVAL] = user_input[CONF_KEEPALIVE_INTERVAL]

            _LOGGER.info(
                "Updating SSE keepalive interval: %s",
                new_options[CONF_KEEPALIVE_INTERVAL],
            )

            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Optional(CONF_KEEPALIVE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=120)
                ),
            }
        )

        suggested = {
            CONF_KEEPALIVE_INTERVAL: self._options.get(
                CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL
            ),
        }

        return self.async_show_form(
            step_id="sse",
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
