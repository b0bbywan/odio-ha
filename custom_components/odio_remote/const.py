"""Constants for the Odio Remote integration."""
from typing import Final

DOMAIN: Final = "odio_remote"

# Config Flow
CONF_API_URL: Final = "api_url"
CONF_KEEPALIVE_INTERVAL: Final = "keepalive_interval"
CONF_SERVICE_MAPPINGS: Final = "service_mappings"

# Defaults
DEFAULT_KEEPALIVE_INTERVAL: Final = 30  # seconds, server-side SSE keepalive (range 10-120)
DEFAULT_NAME: Final = "Odio Remote"

# Attributes
ATTR_CLIENT_ID: Final = "client_id"
ATTR_APP: Final = "app"
ATTR_BACKEND: Final = "backend"
ATTR_USER: Final = "user"
ATTR_HOST: Final = "host"
ATTR_CORKED: Final = "corked"
ATTR_SERVICE_SCOPE: Final = "scope"
ATTR_SERVICE_ENABLED: Final = "enabled"
ATTR_SERVICE_ACTIVE: Final = "active_state"

_MPRIS_BUS_PREFIX = "org.mpris.MediaPlayer2."
