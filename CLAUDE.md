# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**odio-ha** is a Home Assistant custom integration that provides a full multimedia remote for the [go-odio-api](https://github.com/b0bbywan/go-odio-api) REST API. It creates `media_player` entities for a main receiver, individual audio services (MPD, Snapcast, Shairport-Sync, Spotifyd, upmpdcli), remote audio clients, and MPRIS media players. Audio, service, and MPRIS backends are all **optional** — driven by the backends reported by `GET /server`.

## Commands

```bash
# Install dev dependencies
pip install --group dev

# Run all tests
pytest custom_components/odio_remote/tests/ -v

# Run a single test file
pytest custom_components/odio_remote/tests/test_api_client.py -v

# Run a single test
pytest custom_components/odio_remote/tests/test_config_flow.py::TestConfigFlowUser::test_show_form_no_input -v

# Linting
ruff check custom_components/odio_remote/

# Type checking
mypy custom_components/odio_remote/
```

## Architecture

### Core Pattern

`GET /server` is called **once at setup** (not polled) and stored in `OdioRemoteRuntimeData.server_info`. The `backends` dict it returns controls which coordinators are created:

- `OdioAudioCoordinator` — SSE-driven, fetches audio clients. Created only if `backends["pulseaudio"]` is `True`.
- `OdioServiceCoordinator` — SSE-driven, fetches systemd services. Created only if `backends["systemd"]` is `True`.
- `OdioMPRISCoordinator` — SSE-driven, fetches MPRIS media players. Created only if `backends["mpris"]` is `True`.
- `OdioBluetoothCoordinator` — SSE-driven, fetches Bluetooth adapter/device state. Created only if `backends["bluetooth"]` is `True`.
- `OdioUpgradeCoordinator` — SSE-driven, tracks software-upgrade state. Created only if `backends["upgrade"]` is `True`. Seeded from `GET /upgrade`, then driven by two SSE events that merge three payload shapes (all routed to `handle_sse_event`, dispatched by `event.type` first, then by key within `upgrade.info`): `upgrade.info` carries detector status (`{current, latest, upgrade_available, can_upgrade, run?}` — `run` only during a run) and run lifecycle (`{state: "running"|"finished", success?}`, distinguished by the top-level `state` key); `upgrade.progress` carries script progress (`{event: "begin"|"progress"|"end", percent?, step?, …}`). The lifecycle `finished` event is the **systemd job result and is authoritative for completion** — `upgrade.progress` drives `percent`/`step` only and never clears `in_progress` (the script's `end` can precede the job result). `GET /upgrade`'s `run` object is likewise authoritative on refresh, so no in-flight state is preserved across reconnects.

All coordinators are grouped in the `OdioCoordinators` dataclass (each field `| None`) and accessed via `entry.runtime_data.coordinators`.

### Update Platform (`update.py`)

`OdioUpdateEntity` (`CoordinatorEntity` over `OdioUpgradeCoordinator`, only created when the upgrade coordinator exists) exposes the HA `update` entity. `installed_version` is the detector `current` (fallback `server_info.api_version`); `latest_version` mirrors the installed version when no upgrade is available so HA reports "up to date". `supported_features` always includes `PROGRESS`, and adds `INSTALL` only when the detector reports `can_upgrade: true` (gates `POST /upgrade/start`). `async_install` → `POST /upgrade/start`. Re-detection (`POST /upgrade/check`) is intentionally **not** exposed — detection is driven by the server-side detector (systemd timer).

### Entity Types (`media_player.py`)

1. **`OdioReceiverMediaPlayer`** — Extends `MediaPlayerEntity` directly (not `CoordinatorEntity`). Represents the Odio instance itself. Manually registers listeners on whichever coordinators exist via `async_added_to_hass`. Volume/mute only available when `backends["pulseaudio"]` is enabled. `extra_state_attributes` always includes `{"backends": {...}}`.
2. **`OdioServiceMediaPlayer`** — One per systemd service (only created when `service_coordinator` is not None). Uses `audio_coordinator or service_coordinator` as its base coordinator.
3. **`OdioPulseClientMediaPlayer`** — PulseAudio clients (host ≠ server hostname). Dynamically created when clients are detected (only when `audio_coordinator` is not None).
4. **`OdioMPRISMediaPlayer`** — One per D-Bus MPRIS player (only when `mpris_coordinator` is not None). Dynamically created via SSE `player.added` events. Uses native MPRIS capabilities (play/pause/seek/volume/shuffle/repeat) when available, with `MappedEntityMixin` delegation as fallback. Position data is in µs from the API and converted to seconds for HA. Removed players are marked `available: False` (not deleted) so entities go OFF instead of disappearing. `media_image_url` filters out `file://` URLs (only `http`/`https` passed to HA).

### Entity Delegation (`mixins.py`)

`MappedEntityMixin` allows service/client entities to wrap an existing `media_player` entity for extended functionality (play/pause/next/seek/source_select/metadata). Mappings are stored as `dict[str, str]` in `entry.runtime_data.service_mappings` and configured through the UI config flow.

### API Client (`api_client.py`)

Wraps aiohttp for async REST calls. Key detail: volume/mute endpoints use the **client name** (not ID), URL-encoded. 10s timeout default.

Endpoints used:
- `GET /server` — system info with backends dict (fetched once at setup)
- `GET /audio/server` — PulseAudio-specific info (used for mute/volume POSTs)
- `GET /audio/clients` — audio clients list (requires pulseaudio backend)
- `GET /services` — systemd services (requires systemd backend)
- `GET /players` — MPRIS media players (requires mpris backend); returns `x-cache-updated-at` header for position timestamping
- `GET /upgrade` — last upgrade detector status (requires upgrade backend); `null` when no detection has run yet. Body: `{current, latest, upgrade_available, can_upgrade, can_check, checked_at, extra, run?}` (`run` present only during a run; `can_check` is ignored — re-detection is not exposed)
- `POST /upgrade/start` — start the upgrade (202 Accepted; 409 if already running)
- `POST /audio/server/{mute,volume}` — server-level control
- `POST /audio/clients/{name}/{mute,volume}` — per-client control
- `POST /services/{scope}/{unit}/{enable,disable,restart}` — service control
- `POST /players/{player}/{play,pause,stop,next,previous,seek,position,volume,loop,shuffle}` — MPRIS player control (player name is URL-encoded)

### Config Flow (`config_flow.py`)

Three steps:
1. **User** — Validates API URL via `GET /server`; only fetches services if systemd backend is enabled.
2. **Options** — Configures poll intervals.
3. **Services** — Maps service entities to existing `media_player` entities (skipped if no services).

Options flow also includes a **Mappings** step for service and remote client associations (add/remove).

Schema building and mapping parsing are separated into `config_flow_helpers.py`.

### Constants (`const.py`)

- Domain: `odio_remote`
- `ENDPOINT_SYSTEM_SERVER = "/server"` — system info + backends
- `ENDPOINT_SERVER = "/audio/server"` — PulseAudio info
- Supported services: `mpd.service`, `shairport-sync.service`, `snapclient.service`, `spotifyd.service`, `upmpdcli.service`

## Testing

Tests live in `custom_components/odio_remote/tests/`. Shared fixtures (mock server info, services, clients) are in `conftest.py`. `MOCK_SERVER_INFO` matches the `/server` response shape (includes `backends`, `api_version`, `os_version`, `api_sw`).

- `test_api_client.py` — API request/response handling, endpoint methods, URL encoding
- `test_config_flow.py` — Full config flow step coverage including error paths and options reconfiguration
- `test_config_flow_helpers.py` — Schema builders and mapping parse/update logic
- `test_mixins.py` — Entity delegation, feature inheritance, state/attribute/service-call delegation
- `test_mpris.py` — MPRIS coordinator SSE handlers (update/added/removed/position) and entity properties/actions

CI runs on Python 3.14 via `.github/workflows/ci.yml` (Home Assistant 2026.3+ requires Python 3.14).
