"""Shared test fixtures for Odio Remote tests."""
from homeassistant.helpers.entity import DeviceInfo
from custom_components.odio_remote.const import DOMAIN

# Standard mock server info response (from GET /server)
MOCK_SERVER_INFO = {
    "hostname": "htpc",
    "os_platform": "linux/amd64",
    "os_version": "Debian GNU/Linux 13 (trixie)",
    "api_sw": "odio-api",
    "api_version": "v0.6.0-rc.1-main",
    "backends": {
        "power": True,
        "mpris": True,
        "pulseaudio": True,
        "systemd": True,
        "zeroconf": True,
    },
}

# Mock audio server info response (from GET /audio/server)
MOCK_AUDIO_SERVER_INFO = {
    "kind": "pipewire",
    "name": "PulseAudio (on PipeWire 1.4.2)",
    "version": "15.0.0",
    "user": "xbmc",
    "hostname": "htpc",
    "default_sink": "@DEFAULT_SINK@",
    "volume": 1.0000153,
}

# Standard mock services response (supported services for config_flow tests)
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

# Real services response (from GET /services)
MOCK_ALL_SERVICES = [
    {
        "name": "bluetooth.service",
        "scope": "system",
        "active_state": "inactive",
        "running": False,
        "enabled": True,
        "exists": True,
        "description": "Bluetooth service",
    },
    {
        "name": "firefox-kiosk@netflix.com.service",
        "scope": "user",
        "active_state": "active",
        "running": True,
        "enabled": False,
        "exists": True,
        "description": "netflix.com",
    },
    {
        "name": "firefox-kiosk@youtube.com.service",
        "scope": "user",
        "active_state": "inactive",
        "running": False,
        "enabled": False,
        "exists": True,
        "description": "youtube.com",
    },
    {
        "name": "firefox-kiosk@tv.orange.fr.service",
        "scope": "user",
        "active_state": "inactive",
        "running": False,
        "enabled": False,
        "exists": True,
        "description": "tv.orange.fr",
    },
    {
        "name": "kodi.service",
        "scope": "user",
        "active_state": "inactive",
        "running": False,
        "enabled": False,
        "exists": True,
        "description": "Kodi",
    },
    {
        "name": "pipewire-pulse.service",
        "scope": "user",
        "active_state": "active",
        "running": True,
        "enabled": True,
        "exists": True,
        "description": "PipeWire PulseAudio",
    },
]

# Standard mock audio clients response (local clients, host == server hostname)
MOCK_CLIENTS = [
    {
        "id": 161,
        "name": "Netflix",
        "app": "Firefox",
        "muted": False,
        "volume": 1,
        "corked": True,
        "backend": "pipewire",
        "binary": "firefox-esr",
        "user": "xbmc",
        "host": "htpc",
        "props": {
            "application.name": "Firefox",
            "media.name": "Netflix",
            "application.process.binary": "firefox-esr",
            "media.class": "Stream/Output/Audio",
        },
    },
]

MOCK_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "test_entry_id")},
    name="Odio Remote (htpc)",
    manufacturer="Odio",
    sw_version="v0.6.0-rc.1-main",
    hw_version="Debian GNU/Linux 13 (trixie)",
    configuration_url="http://localhost:8018/ui",
)

MOCK_REMOTE_CLIENTS = [
    {
        "id": 3,
        "name": "RemoteClient",
        "app": "firefox",
        "binary": "firefox",
        "host": "remote-host",
        "backend": "pipewire",
        "user": "user",
        "volume": 0.8,
        "muted": False,
        "corked": False,
    },
]
