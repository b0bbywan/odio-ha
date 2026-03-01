# Odio Remote - Home Assistant Integration

Control your Linux multimedia setup remotely from Home Assistant.

This integration connects to a Linux machine running the [go-odio-api server](https://github.com/b0bbywan/go-odio-api) and turns it into a discoverable and controllable media hub. Backends (audio, power, services, etc.) are configured and exposed **directly on the server side**. HA discovers them automatically via the API.

## Features

### Core basics
- Zeroconf (mDNS) auto-discovery: your Linux machine appears automatically (no manual IP/port in most cases)
- One single "Odio Remote (hostname)" device grouping everything
- Automatic detection of exposed backends from server config:
  - audio: PulseAudio/PipeWire sink + per-sink-input volume/mute
  - power: shutdown & reboot buttons
  - services: user-scope systemd services start/stop
  - (mpris, bluetooth, sse planned but not available yet)
- Always-visible connectivity binary_sensor (diagnostic category)
- MAC address resolved via ARP and added to DeviceInfo.connections (“Connected via” in UI)
- Clean state logic: `playing` / `idle` / `unavailable`
- Real-time updates via SSE (Server-Sent Events) — no polling needed
  - Automatic reconnection with exponential backoff
  - Configurable keepalive interval (server-side heartbeat detection)

### Mapping to existing media players
You can map Odio entities (services or remote clients) to any existing HA media_player entity via the configuration or reconfiguration flow.

Examples:
- Map a service like `mpd.service` to `media_player.music_player_daemon`
- Map an audio client like a PipeWire tunnel to `media_player.kodi_htpc`

When mapped, the Odio entity combines:
- Start/stop control via systemd (for services only)
- Independent volume and mute control via PulseAudio/PipeWire (global or per-client)
- All native features of the mapped entity: play/pause/stop/next/previous/seek/shuffle/repeat/select_source/media_title/media_artist/media_album_name/entity_picture (album art)/media_position/media_duration/shuffle/repeat/source/source_list/etc.

Without mapping, the Odio entity only provides basic volume/mute and playback state (playing/idle).

This way, Odio augments your existing players with Linux-level audio control and service management, without replacing their core playback features.

### Screenshots

**With poweroff and reboot enabled**

<img width="1644" height="921" alt="With poweroff and reboot enabled" src="https://github.com/user-attachments/assets/ef8c19a7-1bd3-40a5-98af-d7884375275e" />

  
**Without poweroff and reboot enabled**. Default on [go-odio-api](https://github.com/b0bbywan/go-odio-api)
  
<img width="1644" height="921" alt="Without poweroff and reboot enabled" src="https://github.com/user-attachments/assets/f9f5b949-87c3-4d3d-824c-22e1a3229653" />
  
**With MPD mapped**
  
<img width="1644" height="921" alt="With MPD mapped" src="https://github.com/user-attachments/assets/dc73cd84-1428-4d3f-8ce4-2d95a3657be2" />
  
## Installation

### Via HACS (recommended)

Add odio-ha integration via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=b0bbywan&repository=odio-ha&category=integration)


### Manual installation

1. Download the latest release
2. Copy `custom_components/odio_remote` into your `config/custom_components/` folder
3. Restart Home Assistant

## Setup

Add your device via the Integration menu

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=odio_remote)

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Odio Remote**
3. It should auto-discover via Zeroconf (shows your Linux hostname)
   - If not, enter the API URL manually (`http://ip:port`)
4. No backend toggles in HA — everything depends on what your go-odio-api server exposes (see its config)

Required: [go-odio-api](https://github.com/b0bbywan/go-odio-api) running on your Linux machine. Check its README for setup, endpoints, and how to enable specific backends.


## Entities Created

Grouped under one device: “Odio Remote (hostname)”.

- `media_player.odio_remote_[hostname]`
  Main hub.
  - State: `playing` (any active playback), `idle` (no playback), `unavailable` (API down or audio not exposed)
  - Controls: global volume/mute (audio backend only)

- `media_player.odio_remote_[hostname]_sink_input_[app]`
  Per-sink-input (e.g. Firefox, VLC).
  - Volume/mute per-client
  - State follows corked/uncorked

- `media_player.odio_remote_[hostname]_[service_name]` (e.g. mpd.service)
  For each detected user systemd service (if services backend exposed).
  - Start/stop via switch-like actions
  - Volume/mute via Pulse/PipeWire
  - If mapped: full inherited playback controls & metadata

- `media_player.odio_remote_[hostname]_tunnel_[client_name]`
  For remote clients (different host, no local service).
  - Volume/mute
  - If mapped: inherits full player features (e.g. Kodi metadata)

- `button.odio_remote_[hostname]_power_off` / `button.odio_remote_[hostname]_reboot`
  Shutdown/reboot (power backend only)

- `switch.odio_remote_[hostname]_service_[unit]`
  Start/stop for services (redundant with media_player if mapped, but direct toggle)

- `binary_sensor.odio_remote_[hostname]_connection_status`
  API reachable (connectivity device_class, diagnostic)

## Roadmap

- MPRIS player entities
- Embed Bluetooth speaker support (pairing, enable/disable)
- Audio outputs handling
- More Sensors: Tell me what you need for your setup !
- Improved error reporting & options flow

**Note on backends**: Enabling/disabling features (audio, power, services…) is handled **exclusively on the go-odio-api server** for security reasons (exposing config via API would introduce risks). HA only reflects what the server makes available.

## Troubleshooting

Enable debug logs:

`configuration.yaml`
```yaml
logger:
  default: warning
  logs:
    custom_components.odio_remote: debug
    custom_components.odio_remote.config_flow: debug
    custom_components.odio_remote.media_player: debug
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

For issues and questions: [GitHub repository](https://github.com/b0bbywan/odio-ha)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
