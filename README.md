<p align="center">                                    
  <a href="https://odio.love"><img src="https://odio.love/logo.png" alt="odio" width="160" /></a>   
  </p>
  <h1 align="center">odio-ha</h1>
  <p align="center"><em>Native Home Assistant integration for odio, every node exposed as HA entities.</em></p>
  <p align="center">
  <a href="https://github.com/b0bbywan/odio-ha/releases"><img src="https://img.shields.io/github/v/release/b0bbywan/odio-ha?include_prereleases" alt="Release" /></a>
  <a href="https://developers.home-assistant.io/docs/core/integration-quality-scale/#silver"><img src="https://img.shields.io/badge/HA%20integration-Silver-A8A8A8?logo=homeassistant&logoColor=white" alt="Home    
  Assistant Silver integration" /></a>
  <a href="https://github.com/b0bbywan/odio-ha/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License" /></a>
  <a href="https://github.com/b0bbywan/odio-ha/actions/workflows/ci.yml"><img src="https://github.com/b0bbywan/odio-ha/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/sponsors/b0bbywan"><img src="https://img.shields.io/github/sponsors/b0bbywan?label=Sponsor&logo=GitHub" alt="GitHub Sponsors" /></a>   
  </p>
  <p align="center"> 
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=b0bbywan&repository=odio-ha&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Add to HACS" 
  /></a>
  <a href="https://docs.odio.love/guides/home-assistant/#media-players"><img src="https://img.shields.io/badge/Media%20players-1DB954" alt="Media players" /></a>
  <a href="https://docs.odio.love/guides/home-assistant/#real-time-updates"><img src="https://img.shields.io/badge/Real--time%20SSE-F97316" alt="Real-time SSE" /></a>
  <a href="https://docs.odio.love/api/zeroconf/"><img src="https://img.shields.io/badge/Zeroconf%20discovery-6B21A8" alt="Zeroconf discovery" /></a>   
  </p>
  <p align="center">   
  Part of the <a href="https://odio.love">odio</a> project — <a href="https://docs.odio.love/guides/home-assistant/">full documentation</a>.
  </p>
  <p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python" /></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-18BCF2?logo=homeassistant&logoColor=white" alt="Home Assistant" /></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-03A9F4" alt="HACS" /></a>
  <a href="https://github.com/features/actions"><img src="https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white" alt="GitHub Actions" /></a>
  </p>
  
  # Odio Remote - Home Assistant Integration

Control your Linux multimedia setup remotely from Home Assistant.

This integration connects to a Linux machine running the [go-odio-api server](https://github.com/b0bbywan/go-odio-api) and turns it into a discoverable and controllable media hub. Backends (audio, power, services, etc.) are configured and exposed **directly on the server side**. HA discovers them automatically via the API.

## Features

### Core
- Zeroconf (mDNS) auto-discovery
- One single “Odio Remote (`hostname`)” device grouping all entities
- Backends detected automatically from server config — no toggles in HA
- Always-visible connectivity sensor (diagnostic)
- MAC address resolved via Device Tracker

### Real-time updates (SSE)
All state is pushed by the server via **Server-Sent Events** — no polling after initial fetch.
- Coordinators refresh once at startup, then stay in sync via SSE
- Automatic reconnection with exponential backoff (1s → 5min)
- Configurable server-side keepalive interval (default 30s, range 10–120s)

### Audio (PulseAudio / PipeWire backend)
- Main receiver `media_player` with global volume/mute
- **Audio output selection** via source list on the receiver. Unlike traditional media players, Odio has no exclusive source concept: all sources can be active simultaneously. The source list is used to select the **default audio output**, not to switch between inputs.
- Default output sensor with full output attributes
- Remote audio client entities (PipeWire tunnels from other machines)
- No local clients for now due to name collision risks

### Services (systemd backend)
- `media_player` entity per detected user-scope systemd service
- Start/stop switch per service
- Optional mapping to an existing HA media player → inherits full playback controls & metadata

### MPRIS (media player backend)
- `media_player` entity per active D-Bus MPRIS player (Spotify, Firefox, Chromium, mpd, etc.)
- Full transport controls: play/pause/stop/next/previous/seek (when the player supports them)
- Volume control, shuffle, and repeat mode
- Rich metadata: title, artist, album, album art (remote URLs only)
- Live position tracking via SSE
- Players appear/disappear dynamically as they start and stop
- Optional mapping to an existing HA media player for fallback controls

### Bluetooth
Control your Bluetooth adapter directly from Home Assistant:
- **Power** switch — turn the adapter on or off
- **Pairing mode** button — make the device discoverable for 60 seconds
- **Pairing active** sensor — know when pairing is in progress (diagnostic)
- **Connected device** sensor — name of the currently connected device

### Power (power backend)
- Shutdown and reboot buttons

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

All grouped under one device: **”Odio Remote (hostname)”**.

### Always present
| Entity | Description |
|--------|-------------|
| `media_player.odio_remote_[hostname]` | Main hub — state: `playing` / `idle` / `unavailable`. Global volume/mute and audio output selection when audio backend enabled. |
| `binary_sensor.odio_remote_[hostname]_connection_status` | SSE stream connected (diagnostic) |

### Audio backend (PulseAudio / PipeWire)
| Entity | Description |
|--------|-------------|
| `sensor.odio_remote_[hostname]_default_output` | Current default audio output with full attributes (name, volume, muted, state, driver, etc.) |
| `media_player.odio_remote_[hostname]_[client]` | Remote audio client (PulseAudio/PipeWire tunnel) — volume/mute, optional mapping |

### Services backend (systemd)
| Entity | Description |
|--------|-------------|
| `media_player.odio_remote_[hostname]_[service]` | One per user-scope service — start/stop, volume/mute, optional mapping for full playback |
| `switch.odio_remote_[hostname]_[service]` | Direct start/stop toggle per service |

### MPRIS backend
| Entity | Description |
|--------|-------------|
| `media_player.odio_remote_[hostname]_[player]` | One per MPRIS player (e.g. Spotify, Firefox) — transport controls, volume, metadata, position tracking |

### Bluetooth backend
| Entity | Description |
|--------|-------------|
| `switch.odio_remote_[hostname]_bluetooth_power` | Power the Bluetooth adapter on/off |
| `button.odio_remote_[hostname]_bluetooth_pairing` | Trigger pairing mode (60s server-side timeout) |
| `binary_sensor.odio_remote_[hostname]_bluetooth_pairing_active` | Pairing mode currently active (diagnostic) |
| `sensor.odio_remote_[hostname]_bluetooth_connected_device` | Name of the connected device, empty when none |

### Power backend
| Entity | Description |
|--------|-------------|
| `button.odio_remote_[hostname]_power_off` | Shut down the machine |
| `button.odio_remote_[hostname]_reboot` | Reboot the machine |

## Roadmap

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
