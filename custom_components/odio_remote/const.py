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

# API Endpoints
ENDPOINT_SYSTEM_SERVER: Final = "/server"       # System info + backends
ENDPOINT_SERVER: Final = "/audio/server"        # PulseAudio server (mute/volume only)
ENDPOINT_CLIENTS: Final = "/audio/clients"
ENDPOINT_SERVICES: Final = "/services"
ENDPOINT_SERVER_MUTE: Final = "/audio/server/mute"
ENDPOINT_SERVER_VOLUME: Final = "/audio/server/volume"
ENDPOINT_CLIENT_MUTE: Final = "/audio/clients/{name}/mute"  # Utilise le name, pas l'id
ENDPOINT_CLIENT_VOLUME: Final = "/audio/clients/{name}/volume"
ENDPOINT_SERVICE_ENABLE: Final = "/services/{scope}/{unit}/enable"
ENDPOINT_SERVICE_DISABLE: Final = "/services/{scope}/{unit}/disable"
ENDPOINT_SERVICE_RESTART: Final = "/services/{scope}/{unit}/restart"
ENDPOINT_POWER: Final = "/power"
ENDPOINT_POWER_OFF: Final = "/power/power_off"
ENDPOINT_POWER_REBOOT: Final = "/power/reboot"
ENDPOINT_SERVICE_START: Final = "/services/{scope}/{unit}/start"
ENDPOINT_SERVICE_STOP: Final = "/services/{scope}/{unit}/stop"
ENDPOINT_EVENTS: Final = "/events"

# SSE event types
SSE_EVENT_AUDIO_UPDATED: Final = "audio.updated"
SSE_EVENT_SERVICE_UPDATED: Final = "service.updated"
SSE_EVENT_SERVER_INFO: Final = "server.info"

# SSE reconnection
SSE_RECONNECT_MIN_INTERVAL: Final = 1  # seconds
SSE_RECONNECT_MAX_INTERVAL: Final = 300  # 5 minutes max backoff
SSE_KEEPALIVE_BUFFER: Final = 15  # seconds added to keepalive_interval for client timeout

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
