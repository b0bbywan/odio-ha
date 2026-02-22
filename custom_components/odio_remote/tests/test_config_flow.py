"""Tests for Odio Remote config flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.data_entry_flow import FlowResultType

from custom_components.odio_remote.config_flow import (
    OdioConfigFlow,
    OdioOptionsFlow,
    CannotConnect,
    InvalidResponse,
)
from custom_components.odio_remote.const import (
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    CONF_SERVICE_MAPPINGS,
    CONF_SERVICE_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVICE_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import MOCK_SERVER_INFO, MOCK_SERVICES, MOCK_CLIENTS, MOCK_REMOTE_CLIENTS

# Valid API response for async_validate_api
MOCK_API_INFO = {
    "server_info": MOCK_SERVER_INFO,
    "services": MOCK_SERVICES,
}


def _create_config_flow():
    """Create a config flow instance with mocked internals."""
    flow = OdioConfigFlow()
    flow.hass = MagicMock()
    flow.flow_id = "test_flow"
    flow.handler = DOMAIN
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()
    # Mock context needed by some FlowHandler methods
    flow.context = {"source": "user"}
    return flow


def _create_options_flow(data=None, options=None):
    """Create an options flow instance with mocked config entry."""
    flow = OdioOptionsFlow()
    flow.flow_id = "test_options_flow"
    flow.handler = "test_entry_id"
    flow.context = {"source": "options"}

    # Mock config entry
    mock_entry = MagicMock()
    mock_entry.data = data or {CONF_API_URL: "http://test:8018"}
    mock_entry.options = options or {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_SERVICE_SCAN_INTERVAL: DEFAULT_SERVICE_SCAN_INTERVAL,
        CONF_SERVICE_MAPPINGS: {},
    }
    mock_entry.title = "Odio Remote"
    mock_entry.entry_id = "test_entry_id"

    # config_entry is a property that calls hass.config_entries.async_get_known_entry
    mock_hass = MagicMock()
    mock_hass.config_entries.async_get_known_entry.return_value = mock_entry
    flow.hass = mock_hass

    return flow


# =============================================================================
# Config Flow: async_step_user
# =============================================================================


class TestConfigFlowUser:
    """Tests for the user step of the config flow."""

    @pytest.mark.asyncio
    async def test_show_form_no_input(self):
        """Test that the user form is shown when no input is provided."""
        flow = _create_config_flow()

        result = await flow.async_step_user(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_success_transitions_to_options(self, mock_validate):
        """Test that valid API URL transitions to options step."""
        flow = _create_config_flow()

        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )

        # Should transition to options step (show form)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "options"
        assert flow._data[CONF_API_URL] == "http://test:8018"
        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        side_effect=CannotConnect,
    )
    async def test_cannot_connect_error(self, mock_validate):
        """Test error when API connection fails."""
        flow = _create_config_flow()

        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://bad-host:8018"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        side_effect=InvalidResponse("bad"),
    )
    async def test_invalid_response_error(self, mock_validate):
        """Test error when API returns invalid data."""
        flow = _create_config_flow()

        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "invalid_response"}

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        side_effect=RuntimeError("something unexpected"),
    )
    async def test_unknown_error(self, mock_validate):
        """Test error on unexpected exception."""
        flow = _create_config_flow()

        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "unknown"}

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_already_configured_aborts(self, mock_validate):
        """Test abort when API URL is already configured."""
        from homeassistant.data_entry_flow import AbortFlow

        flow = _create_config_flow()
        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=AbortFlow("already_configured")
        )

        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_user(
                user_input={CONF_API_URL: "http://test:8018"}
            )

        assert exc_info.value.reason == "already_configured"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_unique_id_set_to_api_url(self, mock_validate):
        """Test that unique ID is set to the API URL."""
        flow = _create_config_flow()

        await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )

        flow.async_set_unique_id.assert_called_once_with("http://test:8018")


# =============================================================================
# Config Flow: async_step_options
# =============================================================================


class TestConfigFlowOptions:
    """Tests for the options step of the config flow."""

    @pytest.mark.asyncio
    async def test_show_form_no_input(self):
        """Test that the options form is shown when no input is provided."""
        flow = _create_config_flow()

        result = await flow.async_step_options(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "options"

    @pytest.mark.asyncio
    async def test_transitions_to_services(self):
        """Test that providing options transitions to services step."""
        flow = _create_config_flow()
        flow._services = []  # No services available

        result = await flow.async_step_options(
            user_input={
                CONF_SCAN_INTERVAL: 10,
                CONF_SERVICE_SCAN_INTERVAL: 120,
            }
        )

        assert flow._options[CONF_SCAN_INTERVAL] == 10
        assert flow._options[CONF_SERVICE_SCAN_INTERVAL] == 120
        # Should create entry directly since no services
        assert result["type"] is FlowResultType.CREATE_ENTRY

    @pytest.mark.asyncio
    async def test_defaults_used_when_not_provided(self):
        """Test that defaults are used when values not in input."""
        flow = _create_config_flow()
        flow._services = []

        await flow.async_step_options(user_input={})

        assert flow._options[CONF_SCAN_INTERVAL] == DEFAULT_SCAN_INTERVAL
        assert flow._options[CONF_SERVICE_SCAN_INTERVAL] == DEFAULT_SERVICE_SCAN_INTERVAL


# =============================================================================
# Config Flow: async_step_services
# =============================================================================


class TestConfigFlowServices:
    """Tests for the services step of the config flow."""

    @pytest.mark.asyncio
    async def test_no_services_creates_entry(self):
        """Test that entry is created directly when no services available."""
        flow = _create_config_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SCAN_INTERVAL: 5, CONF_SERVICE_SCAN_INTERVAL: 60}
        flow._services = []

        result = await flow.async_step_services(user_input=None)

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {CONF_API_URL: "http://test:8018"}
        assert result["options"][CONF_SERVICE_MAPPINGS] == {}

    @pytest.mark.asyncio
    async def test_show_form_with_services(self):
        """Test that form is shown when services are available."""
        flow = _create_config_flow()
        flow._services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ]

        result = await flow.async_step_services(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "services"
        assert result["data_schema"] is not None

    @pytest.mark.asyncio
    async def test_creates_entry_with_mappings(self):
        """Test entry creation with service mappings."""
        flow = _create_config_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SCAN_INTERVAL: 5, CONF_SERVICE_SCAN_INTERVAL: 60}
        flow._services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ]

        result = await flow.async_step_services(
            user_input={"user_mpd.service": "media_player.mpd"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"][CONF_SERVICE_MAPPINGS] == {
            "user/mpd.service": "media_player.mpd"
        }

    @pytest.mark.asyncio
    async def test_creates_entry_empty_mappings(self):
        """Test entry creation when user skips all mappings."""
        flow = _create_config_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SCAN_INTERVAL: 5, CONF_SERVICE_SCAN_INTERVAL: 60}
        flow._services = [
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ]

        result = await flow.async_step_services(user_input={})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"][CONF_SERVICE_MAPPINGS] == {}


# =============================================================================
# Config Flow: Full flow
# =============================================================================


class TestConfigFlowFullPath:
    """Tests for the complete config flow path."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_full_flow_no_services(self, mock_validate):
        """Test the full flow when no services are available."""
        flow = _create_config_flow()

        # Step 1: User provides API URL (API returns no enabled services)
        mock_validate.return_value = {
            "server_info": MOCK_SERVER_INFO,
            "services": [],
        }

        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )
        assert result["step_id"] == "options"

        # Step 2: User provides scan intervals
        result = await flow.async_step_options(
            user_input={
                CONF_SCAN_INTERVAL: 10,
                CONF_SERVICE_SCAN_INTERVAL: 120,
            }
        )

        # No services → entry created directly
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Odio Remote"
        assert result["data"] == {CONF_API_URL: "http://test:8018"}
        assert result["options"][CONF_SCAN_INTERVAL] == 10
        assert result["options"][CONF_SERVICE_SCAN_INTERVAL] == 120
        assert result["options"][CONF_SERVICE_MAPPINGS] == {}

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_full_flow_with_services(self, mock_validate):
        """Test the full flow with services to map."""
        flow = _create_config_flow()

        # Step 1: User provides API URL
        result = await flow.async_step_user(
            user_input={CONF_API_URL: "http://test:8018"}
        )
        assert result["step_id"] == "options"

        # Step 2: User provides scan intervals
        result = await flow.async_step_options(
            user_input={
                CONF_SCAN_INTERVAL: 5,
                CONF_SERVICE_SCAN_INTERVAL: 60,
            }
        )

        # Services found → show services form
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "services"

        # Step 3: User maps a service
        result = await flow.async_step_services(
            user_input={"user_mpd.service": "media_player.mpd"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"][CONF_SERVICE_MAPPINGS] == {
            "user/mpd.service": "media_player.mpd"
        }


# =============================================================================
# Options Flow: async_step_init
# =============================================================================


class TestOptionsFlowInit:
    """Tests for the init step of the options flow."""

    @pytest.mark.asyncio
    async def test_show_menu(self):
        """Test that the options menu is shown."""
        flow = _create_options_flow()

        result = await flow.async_step_init(user_input=None)

        assert result["type"] is FlowResultType.MENU
        assert "intervals" in result["menu_options"]
        assert "mappings" in result["menu_options"]


# =============================================================================
# Options Flow: async_step_intervals
# =============================================================================


class TestOptionsFlowIntervals:
    """Tests for the intervals step of the options flow."""

    @pytest.mark.asyncio
    async def test_show_form_no_input(self):
        """Test that intervals form is shown."""
        flow = _create_options_flow()
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {},
        }

        result = await flow.async_step_intervals(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "intervals"

    @pytest.mark.asyncio
    async def test_update_intervals(self):
        """Test updating scan intervals."""
        flow = _create_options_flow()
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {},
        }

        result = await flow.async_step_intervals(
            user_input={
                CONF_SCAN_INTERVAL: 15,
                CONF_SERVICE_SCAN_INTERVAL: 180,
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_SCAN_INTERVAL] == 15
        assert result["data"][CONF_SERVICE_SCAN_INTERVAL] == 180
        # Existing mappings should be preserved
        assert result["data"][CONF_SERVICE_MAPPINGS] == {}


# =============================================================================
# Options Flow: async_step_mappings
# =============================================================================


class TestOptionsFlowMappings:
    """Tests for the mappings step of the options flow."""

    @pytest.mark.asyncio
    async def test_abort_no_api_url(self):
        """Test abort when no API URL is configured."""
        flow = _create_options_flow(data={})
        flow._data = {}

        result = await flow.async_step_mappings(user_input=None)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "no_api_url"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[],
    )
    async def test_abort_no_mappable_entities(self, mock_clients, mock_services):
        """Test abort when no services or clients are available."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SERVICE_MAPPINGS: {}}

        result = await flow.async_step_mappings(user_input=None)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "no_mappable_entities"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[],
    )
    async def test_show_form_with_services(self, mock_clients, mock_services):
        """Test that mappings form is shown when services exist."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SERVICE_MAPPINGS: {}}

        result = await flow.async_step_mappings(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mappings"
        assert result["data_schema"] is not None

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[
            {"name": "RemoteClient", "host": "remote-host"},
        ],
    )
    async def test_show_form_with_clients(self, mock_clients, mock_services):
        """Test that mappings form is shown when clients exist."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {CONF_SERVICE_MAPPINGS: {}}

        result = await flow.async_step_mappings(user_input=None)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "mappings"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[],
    )
    async def test_update_mappings(self, mock_clients, mock_services):
        """Test updating service mappings."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {},
        }

        result = await flow.async_step_mappings(
            user_input={"user_mpd.service": "media_player.mpd"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_SERVICE_MAPPINGS] == {
            "user/mpd.service": "media_player.mpd"
        }

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[],
    )
    async def test_delete_mapping(self, mock_clients, mock_services):
        """Test deleting an existing mapping via delete checkbox."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {
                "user/mpd.service": "media_player.mpd",
            },
        }

        result = await flow.async_step_mappings(
            user_input={
                "user_mpd.service": "media_player.mpd",
                "user_mpd.service_delete": True,
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "user/mpd.service" not in result["data"][CONF_SERVICE_MAPPINGS]

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[
            {"name": "RemoteClient", "host": "remote-host"},
        ],
    )
    async def test_mixed_services_and_clients(self, mock_clients, mock_services):
        """Test mapping both services and clients."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {},
        }

        result = await flow.async_step_mappings(
            user_input={
                "user_mpd.service": "media_player.mpd",
                "client_remoteclient": "media_player.remote",
            }
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        mappings = result["data"][CONF_SERVICE_MAPPINGS]
        assert mappings["user/mpd.service"] == "media_player.mpd"
        assert mappings["client:RemoteClient"] == "media_player.remote"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_available_services",
        return_value=[
            {"name": "mpd.service", "scope": "user", "exists": True, "enabled": True},
        ],
    )
    @patch(
        "custom_components.odio_remote.config_flow.async_fetch_remote_clients",
        return_value=[],
    )
    async def test_preserves_offline_client_mappings(self, mock_clients, mock_services):
        """Test that mappings for offline clients are preserved."""
        flow = _create_options_flow()
        flow._data = {CONF_API_URL: "http://test:8018"}
        flow._options = {
            CONF_SCAN_INTERVAL: 5,
            CONF_SERVICE_SCAN_INTERVAL: 60,
            CONF_SERVICE_MAPPINGS: {
                "client:OfflineClient": "media_player.offline",
            },
        }

        result = await flow.async_step_mappings(
            user_input={"user_mpd.service": "media_player.mpd"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        mappings = result["data"][CONF_SERVICE_MAPPINGS]
        # New mapping added
        assert mappings["user/mpd.service"] == "media_player.mpd"
        # Offline client mapping preserved
        assert mappings["client:OfflineClient"] == "media_player.offline"


# =============================================================================
# Config Flow: zeroconf discovery
# =============================================================================


def _create_zeroconf_info(
    host="192.168.1.100",
    port=8018,
    hostname="htpc.local.",
    addresses=None,
):
    """Create a mock ZeroconfServiceInfo."""
    info = MagicMock(spec=ZeroconfServiceInfo)
    info.host = host
    info.port = port
    info.hostname = hostname
    info.addresses = addresses if addresses is not None else [host]
    return info


class TestConfigFlowZeroconf:
    """Tests for the zeroconf discovery path of the config flow."""

    @pytest.mark.asyncio
    async def test_zeroconf_shows_confirm_form(self):
        """Discovery shows confirmation form."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info()

        result = await flow.async_step_zeroconf(discovery_info)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "zeroconf_confirm"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        return_value=MOCK_API_INFO,
    )
    async def test_zeroconf_confirm_proceeds_to_options(self, mock_validate):
        """Confirmation calls validate and transitions to options."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info()

        # Discover first
        await flow.async_step_zeroconf(discovery_info)

        # Then confirm
        result = await flow.async_step_zeroconf_confirm(user_input={})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "options"
        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_zeroconf_aborts_if_already_configured(self):
        """Already-configured URL causes abort."""
        from homeassistant.data_entry_flow import AbortFlow

        flow = _create_config_flow()
        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=AbortFlow("already_configured")
        )
        discovery_info = _create_zeroconf_info()

        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_zeroconf(discovery_info)

        assert exc_info.value.reason == "already_configured"

    @pytest.mark.asyncio
    @patch(
        "custom_components.odio_remote.config_flow.async_validate_api",
        side_effect=CannotConnect,
    )
    async def test_zeroconf_confirm_aborts_on_cannot_connect(self, mock_validate):
        """Validation failure at confirm step aborts with cannot_connect."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info()

        await flow.async_step_zeroconf(discovery_info)

        result = await flow.async_step_zeroconf_confirm(user_input={})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_zeroconf_hostname_display(self):
        """hostname .local. suffix is stripped for display."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info(hostname="htpc.local.")

        await flow.async_step_zeroconf(discovery_info)

        assert flow.context["title_placeholders"]["host"] == "htpc"

    @pytest.mark.asyncio
    async def test_zeroconf_sets_api_url(self):
        """Discovered host and port are combined into API URL."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info(host="10.0.0.5", port=9000)

        await flow.async_step_zeroconf(discovery_info)

        assert flow._data["api_url"] == "http://10.0.0.5:9000"
        flow.async_set_unique_id.assert_called_once_with("http://10.0.0.5:9000")

    @pytest.mark.asyncio
    async def test_zeroconf_prefers_ipv4_over_ipv6(self):
        """When both IPv6 and IPv4 addresses are advertised, IPv4 is used."""
        flow = _create_config_flow()
        discovery_info = _create_zeroconf_info(
            host="2a01:cb0c:796:200:922b:34ff:fe3a:a796",
            port=8018,
            addresses=["2a01:cb0c:796:200:922b:34ff:fe3a:a796", "192.168.1.100"],
        )

        await flow.async_step_zeroconf(discovery_info)

        assert flow._data["api_url"] == "http://192.168.1.100:8018"

    @pytest.mark.asyncio
    async def test_zeroconf_falls_back_to_host_when_only_ipv6(self):
        """When only IPv6 is advertised, fall back to discovery_info.host."""
        flow = _create_config_flow()
        ipv6 = "2a01:cb0c:796:200:922b:34ff:fe3a:a796"
        discovery_info = _create_zeroconf_info(
            host=ipv6,
            port=8018,
            addresses=[ipv6],
        )

        await flow.async_step_zeroconf(discovery_info)

        assert flow._data["api_url"] == f"http://{ipv6}:8018"


# =============================================================================
# Validation helpers
# =============================================================================


class TestValidationHelpers:
    """Tests for config flow validation helper functions."""

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.config_flow.async_get_clientsession")
    async def test_async_validate_api_success(self, mock_session):
        """Test successful API validation."""
        from custom_components.odio_remote.config_flow import async_validate_api

        mock_api_instance = MagicMock()
        mock_api_instance.get_server_info = AsyncMock(return_value=MOCK_SERVER_INFO)
        mock_api_instance.get_services = AsyncMock(return_value=MOCK_SERVICES)

        with patch(
            "custom_components.odio_remote.config_flow.OdioApiClient",
            return_value=mock_api_instance,
        ):
            result = await async_validate_api(MagicMock(), "http://test:8018")

        assert result["server_info"] == MOCK_SERVER_INFO
        assert result["services"] == MOCK_SERVICES

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.config_flow.async_get_clientsession")
    async def test_async_validate_api_connection_error(self, mock_session):
        """Test API validation with connection error."""
        from custom_components.odio_remote.config_flow import async_validate_api

        mock_api_instance = MagicMock()
        mock_api_instance.get_server_info = AsyncMock(
            side_effect=ConnectionError("refused")
        )

        with patch(
            "custom_components.odio_remote.config_flow.OdioApiClient",
            return_value=mock_api_instance,
        ):
            with pytest.raises(CannotConnect):
                await async_validate_api(MagicMock(), "http://bad:8018")

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.config_flow.async_get_clientsession")
    async def test_async_validate_api_invalid_response(self, mock_session):
        """Test API validation with invalid response types."""
        from custom_components.odio_remote.config_flow import async_validate_api

        mock_api_instance = MagicMock()
        # server_info returns a list instead of dict
        mock_api_instance.get_server_info = AsyncMock(return_value=["not", "a", "dict"])
        mock_api_instance.get_services = AsyncMock(return_value=MOCK_SERVICES)

        with patch(
            "custom_components.odio_remote.config_flow.OdioApiClient",
            return_value=mock_api_instance,
        ):
            with pytest.raises(InvalidResponse):
                await async_validate_api(MagicMock(), "http://test:8018")

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.config_flow.async_get_clientsession")
    async def test_async_fetch_remote_clients(self, mock_session):
        """Test fetching remote clients filters by hostname."""
        from custom_components.odio_remote.config_flow import async_fetch_remote_clients

        all_clients = MOCK_CLIENTS + MOCK_REMOTE_CLIENTS

        mock_api_instance = MagicMock()
        mock_api_instance.get_server_info = AsyncMock(return_value=MOCK_SERVER_INFO)
        mock_api_instance.get_clients = AsyncMock(return_value=all_clients)

        with patch(
            "custom_components.odio_remote.config_flow.OdioApiClient",
            return_value=mock_api_instance,
        ):
            result = await async_fetch_remote_clients(MagicMock(), "http://test:8018")

        # Only the remote client (not on "odio-server") should be returned
        assert len(result) == 1
        assert result[0]["name"] == "RemoteClient"

    @pytest.mark.asyncio
    @patch("custom_components.odio_remote.config_flow.async_get_clientsession")
    async def test_async_fetch_remote_clients_error(self, mock_session):
        """Test fetching remote clients returns empty on error."""
        from custom_components.odio_remote.config_flow import async_fetch_remote_clients

        mock_api_instance = MagicMock()
        mock_api_instance.get_server_info = AsyncMock(
            side_effect=ConnectionError("refused")
        )

        with patch(
            "custom_components.odio_remote.config_flow.OdioApiClient",
            return_value=mock_api_instance,
        ):
            result = await async_fetch_remote_clients(MagicMock(), "http://bad:8018")

        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
