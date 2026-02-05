"""Constants for the Odio Audio integration."""
from typing import Final

DOMAIN: Final = "odio_audio"

# Config Flow
CONF_API_URL: Final = "api_url"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SERVICE_SCAN_INTERVAL: Final = "service_scan_interval"
CONF_SERVICE_MAPPINGS: Final = "service_mappings"

# Defaults
DEFAULT_SCAN_INTERVAL: Final = 5  # secondes pour audio
DEFAULT_SERVICE_SCAN_INTERVAL: Final = 60  # secondes pour services
DEFAULT_NAME: Final = "Odio Audio"

# API Endpoints
ENDPOINT_SERVER: Final = "/audio/server"
ENDPOINT_CLIENTS: Final = "/audio/clients"
ENDPOINT_SERVICES: Final = "/services"
ENDPOINT_SERVER_MUTE: Final = "/audio/server/mute"
ENDPOINT_SERVER_VOLUME: Final = "/audio/server/volume"
ENDPOINT_CLIENT_MUTE: Final = "/audio/clients/{name}/mute"  # Utilise le name, pas l'id
ENDPOINT_CLIENT_VOLUME: Final = "/audio/clients/{name}/volume"
ENDPOINT_SERVICE_ENABLE: Final = "/services/{scope}/{unit}/enable"
ENDPOINT_SERVICE_DISABLE: Final = "/services/{scope}/{unit}/disable"
ENDPOINT_SERVICE_RESTART: Final = "/services/{scope}/{unit}/restart"
ENDPOINT_SERVICE_START: Final = "/services/{scope}/{unit}/start"
ENDPOINT_SERVICE_STOP: Final = "/services/{scope}/{unit}/stop"

# MPRIS Player Endpoints
ENDPOINT_PLAYERS: Final = "/players"
ENDPOINT_PLAYER_PLAY: Final = "/players/{player}/play"
ENDPOINT_PLAYER_PAUSE: Final = "/players/{player}/pause"
ENDPOINT_PLAYER_PLAY_PAUSE: Final = "/players/{player}/play_pause"
ENDPOINT_PLAYER_STOP: Final = "/players/{player}/stop"
ENDPOINT_PLAYER_NEXT: Final = "/players/{player}/next"
ENDPOINT_PLAYER_PREVIOUS: Final = "/players/{player}/previous"
ENDPOINT_PLAYER_SEEK: Final = "/players/{player}/seek"
ENDPOINT_PLAYER_POSITION: Final = "/players/{player}/position"
ENDPOINT_PLAYER_VOLUME: Final = "/players/{player}/volume"
ENDPOINT_PLAYER_LOOP: Final = "/players/{player}/loop"
ENDPOINT_PLAYER_SHUFFLE: Final = "/players/{player}/shuffle"

# Service types we care about
SUPPORTED_SERVICES: Final = [
    "mpd.service",
    # "mpd-discplayer.service",  # Ne fait que relayer vers MPD, pas besoin d'entité séparée
    # "pipewire-pulse.service",  # Serveur audio, pas un lecteur - représenté par le receiver principal
    # "pulseaudio.service",      # Serveur audio, pas un lecteur - représenté par le receiver principal
    "shairport-sync.service",
    "snapclient.service",
    "spotifyd.service",
    "upmpdcli.service",
]

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
