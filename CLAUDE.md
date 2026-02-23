# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**odio-ha** is a Home Assistant custom integration that provides a full multimedia remote for the [go-odio-api](https://github.com/b0bbywan/go-odio-api) REST API. It creates `media_player` entities for a main receiver, individual audio services (MPD, Snapcast, Shairport-Sync, Spotifyd, upmpdcli), and remote audio clients. Both audio and service backends are **optional** — driven by the backends reported by `GET /server`.

## Commands

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest custom_components/odio_remote/tests/ -v

# Run a single test file
pytest custom_components/odio_remote/tests/test_api_client.py -v

# Run a single test
pytest custom_components/odio_remote/tests/test_config_flow.py::TestConfigFlowUser::test_show_form_no_input -v

# Linting
flake8 custom_components/odio_remote/

# Type checking
mypy custom_components/odio_remote/
```

## Architecture

### Core Pattern

`GET /server` is called **once at setup** (not polled) and stored in `OdioRemoteRuntimeData.server_info`. The `backends` dict it returns controls which coordinators are created:

- `OdioAudioCoordinator` — 5s interval, fetches audio clients. Created only if `backends["pulseaudio"]` is `True`.
- `OdioServiceCoordinator` — 60s interval, fetches systemd services. Created only if `backends["systemd"]` is `True`.

Both coordinators are `| None` in `OdioRemoteRuntimeData` (defined in `__init__.py`). All state is accessed via `entry.runtime_data`.

### Entity Types (`media_player.py`)

1. **`OdioReceiverMediaPlayer`** — Extends `MediaPlayerEntity` directly (not `CoordinatorEntity`). Represents the Odio instance itself. Manually registers listeners on whichever coordinators exist via `async_added_to_hass`. Volume/mute only available when `backends["pulseaudio"]` is enabled. `extra_state_attributes` always includes `{"backends": {...}}`.
2. **`OdioServiceMediaPlayer`** — One per systemd service (only created when `service_coordinator` is not None). Uses `audio_coordinator or service_coordinator` as its base coordinator.
3. **`OdioPulseClientMediaPlayer`** — PulseAudio clients (host ≠ server hostname). Dynamically created when clients are detected (only when `audio_coordinator` is not None).

### Entity Delegation (`mixins.py`)

`MappedEntityMixin` allows service/client entities to wrap an existing `media_player` entity for extended functionality (play/pause/next/seek/source_select/metadata). Mappings are stored as `dict[str, str]` in `entry.runtime_data.service_mappings` and configured through the UI config flow.

### API Client (`api_client.py`)

Wraps aiohttp for async REST calls. Key detail: volume/mute endpoints use the **client name** (not ID), URL-encoded. 10s timeout default.

Endpoints used:
- `GET /server` — system info with backends dict (fetched once at setup)
- `GET /audio/server` — PulseAudio-specific info (used for mute/volume POSTs)
- `GET /audio/clients` — audio clients list (requires pulseaudio backend)
- `GET /services` — systemd services (requires systemd backend)
- `POST /audio/server/{mute,volume}` — server-level control
- `POST /audio/clients/{name}/{mute,volume}` — per-client control
- `POST /services/{scope}/{unit}/{enable,disable,restart}` — service control

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

CI runs on Python 3.13 and 3.14 via `.github/workflows/ci.yml`.
