"""Shared test fixtures for Odio Audio tests."""
# Standard mock server info response
MOCK_SERVER_INFO = {
    "name": "pulseaudio",
    "hostname": "odio-server",
    "version": "15.0",
    "default_sink": "alsa_output.pci-0000_00_1b.0.analog-stereo",
}

# Standard mock services response
MOCK_SERVICES = [
    {
        "name": "mpd.service",
        "scope": "user",
        "exists": True,
        "enabled": True,
        "running": True,
        "active_state": "active",
    },
    {
        "name": "shairport-sync.service",
        "scope": "user",
        "exists": True,
        "enabled": True,
        "running": False,
        "active_state": "inactive",
    },
    {
        "name": "snapclient.service",
        "scope": "user",
        "exists": True,
        "enabled": False,
        "running": False,
        "active_state": "inactive",
    },
]

# Standard mock audio clients response
MOCK_CLIENTS = [
    {
        "id": 1,
        "name": "mpd",
        "app": "mpd",
        "binary": "mpd",
        "host": "odio-server",
        "backend": "PulseAudio",
        "user": "odio",
        "volume": 0.75,
        "muted": False,
        "corked": False,
    },
    {
        "id": 2,
        "name": "snapclient",
        "app": "snapclient",
        "binary": "snapclient",
        "host": "odio-server",
        "backend": "PulseAudio",
        "user": "odio",
        "volume": 0.5,
        "muted": True,
        "corked": True,
    },
]

MOCK_REMOTE_CLIENTS = [
    {
        "id": 3,
        "name": "RemoteClient",
        "app": "firefox",
        "binary": "firefox",
        "host": "remote-host",
        "backend": "PulseAudio",
        "user": "user",
        "volume": 0.8,
        "muted": False,
        "corked": False,
    },
]
