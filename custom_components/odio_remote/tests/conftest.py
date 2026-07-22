"""Shared test fixtures for Odio Remote tests."""
from typing import Any
from unittest.mock import MagicMock, create_autospec

from homeassistant.helpers.entity import DeviceInfo
from pyodio import (
    AudioServerState,
    AudioSnapshot,
    BluetoothState,
    OdioClient,
    OdioEvent,
    OdioHub,
    PlayerState,
    ServerInfo,
    ServiceState,
    UpgradeStatus,
)

from custom_components.odio_remote.const import DOMAIN

TEST_API_URL = "http://localhost:8018"

# Standard mock server info response (from GET /server)
MOCK_SERVER_INFO: dict[str, Any] = {
    "hostname": "htpc",
    "os_platform": "linux/amd64",
    "os_version": "Debian GNU/Linux 13 (trixie)",
    "api_sw": "odio-api",
    "api_version": "v0.6.0-rc.1-main",
    "backends": {
        "bluetooth": True,
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

# Mock audio outputs (from GET /audio "outputs" key)
MOCK_OUTPUTS = [
    {
        "id": 52,
        "name": "alsa_output.pci-0000_00_1f.3.analog-stereo",
        "description": "Built-in Audio Analog Stereo",
        "nick": "ALC887-VD Analog",
        "muted": False,
        "volume": 1,
        "state": "suspended",
        "default": False,
        "driver": "PipeWire",
        "active_port": "analog-output-lineout",
        "props": {},
    },
    {
        "id": 68,
        "name": "raop_sink.nas-2.local.2a01:cb0c:796:200:3285:a9ff:fe40:f90f.5000",
        "description": "SnapAir",
        "muted": False,
        "volume": 0,
        "state": "suspended",
        "default": False,
        "driver": "PipeWire",
        "is_network": True,
        "props": {},
    },
    {
        "id": 73,
        "name": "tunnel.rasponkyo.local.alsa_output.platform-soc_sound.stereo-fallback",
        "description": "Built-in Audio Stereo on pi@rasponkyo",
        "muted": False,
        "volume": 1,
        "state": "suspended",
        "default": False,
        "driver": "PipeWire",
        "is_network": True,
        "props": {},
    },
    {
        "id": 78,
        "name": "tunnel.rasponkyold.local.alsa_output.platform-2000b840.mailbox.stereo-fallback",
        "description": "Audio interne Stéréo on pi@rasponkyold",
        "muted": False,
        "volume": 1,
        "state": "suspended",
        "default": True,
        "driver": "PipeWire",
        "is_network": True,
        "props": {},
    },
    {
        "id": 85,
        "name": "alsa_output.pci-0000_01_00.1.hdmi-stereo",
        "description": "GP104 High Definition Audio Controller Digital Stereo (HDMI)",
        "nick": "24G2W1G4",
        "muted": False,
        "volume": 1,
        "state": "suspended",
        "default": False,
        "driver": "PipeWire",
        "active_port": "hdmi-output-0",
        "props": {},
    },
]

# Mock unified /audio response (new API)
MOCK_AUDIO_UNIFIED = {
    "clients": [
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
    ],
    "kind": "pipewire",
    "outputs": MOCK_OUTPUTS,
}

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

MOCK_BLUETOOTH_STATUS = {
    "powered": True,
    "discoverable": False,
    "pairable": False,
    "pairing_active": False,
    "scanning": False,
    "known_devices": [
        {
            "address": "AA:BB:CC:DD:EE:FF",
            "name": "Pixel 6a",
            "paired": True,
            "bonded": True,
            "trusted": True,
            "connected": True,
        }
    ],
}

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

# ---------------------------------------------------------------------------
# Hub factory — a real pyodio OdioHub with a mocked REST client, seeded from
# the dict fixtures above through the library's own from_dict parsers.
# ---------------------------------------------------------------------------


def make_hub(
    *,
    server_info: dict[str, Any] | None = MOCK_SERVER_INFO,
    services: list[dict[str, Any]] | None = None,
    audio: dict[str, Any] | None = None,
    audio_server: dict[str, Any] | None = None,
    bluetooth: dict[str, Any] | None = None,
    players: list[dict[str, Any]] | None = None,
    upgrade: dict[str, Any] | None = None,
    connected: bool = True,
) -> OdioHub:
    """Build a real OdioHub seeded from dict fixtures, with the client mocked."""
    hub = OdioHub(TEST_API_URL, MagicMock())
    real_client = hub.client
    hub.client = create_autospec(OdioClient, instance=True)
    hub.client.base_url = TEST_API_URL
    # Keep the real URL builder so cover URLs stay meaningful in tests.
    hub.client.player_cover_url.side_effect = real_client.player_cover_url

    if server_info is not None:
        hub._server = ServerInfo.from_dict(server_info)
    if services is not None:
        hub.services._set_snapshot([ServiceState.from_dict(s) for s in services])
    if audio is not None:
        hub.audio._set_snapshot(
            AudioSnapshot.from_dict(audio),
            AudioServerState.from_dict(audio_server) if audio_server else None,
        )
    if bluetooth is not None:
        hub.bluetooth._set_state(BluetoothState.from_dict(bluetooth))
    if players is not None:
        hub.players._set_snapshot([PlayerState.from_dict(p) for p in players])
    if upgrade is not None:
        hub.upgrade._set_status(UpgradeStatus.from_dict(upgrade))
    set_connected(hub, connected)
    return hub


def set_connected(hub: OdioHub, connected: bool) -> None:
    """Flip the hub's SSE connectivity, notifying connection listeners."""
    hub._stream._set_connected(connected)


def push_event(hub: OdioHub, event_type: str, data: Any) -> None:
    """Feed a raw SSE event through the hub's real dispatch/parsing path."""
    hub._handle_event(OdioEvent(event_type, data))


MOCK_PLAYERS = [
    {
        "bus_name": "org.mpris.MediaPlayer2.spotify",
        "identity": "Spotify",
        "playback_status": "Playing",
        "loop_status": "None",
        "shuffle": True,
        "volume": 0.8,
        "position": 28962000,
        "position_updated_at": "2026-03-04T19:06:00Z",
        "rate": 1,
        "metadata": {
            "mpris:artUrl": "https://i.scdn.co/image/abc123",
            "mpris:length": "223840000",
            "mpris:trackid": "/com/spotify/track/abc",
            "xesam:album": "Etoiles du sol",
            "xesam:artist": ["Dooz Kawa"],
            "xesam:title": "Narcozik",
        },
        "capabilities": {
            "can_play": True,
            "can_pause": True,
            "can_go_next": True,
            "can_go_previous": True,
            "can_seek": True,
            "can_control": True,
        },
    },
    {
        "bus_name": "org.mpris.MediaPlayer2.chromium.instance1",
        "identity": "Chrome",
        "playback_status": "Paused",
        "volume": 1.0,
        "position": 987200000,
        "position_updated_at": "2026-03-04T19:06:00Z",
        "metadata": {
            "mpris:artUrl": "file:///tmp/.com.google.Chrome.abc",
            "mpris:length": "987200000",
            "mpris:trackid": "/org/chromium/MediaPlayer2/TrackList/Track1",
            "xesam:artist": "Some Artist",
            "xesam:title": "Some Title",
        },
        "capabilities": {
            "can_play": False,
            "can_pause": False,
            "can_go_next": False,
            "can_go_previous": False,
            "can_seek": False,
            "can_control": True,
        },
    },
]
