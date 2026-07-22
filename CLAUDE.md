# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**odio-ha** is a Home Assistant custom integration that provides a full multimedia remote for the [go-odio-api](https://github.com/b0bbywan/go-odio-api) REST API, built on top of the [pyodio](https://github.com/b0bbywan/pyodio) library. It creates `media_player` entities for a main receiver, individual audio services (MPD, Snapcast, Shairport-Sync, Spotifyd, upmpdcli), remote audio clients, and MPRIS media players. Audio, service, MPRIS, Bluetooth, power, and upgrade backends are all **optional** — driven by `ServerInfo.backends`.

## Commands

```bash
# Install dev dependencies (pyodio comes from git; for local dev use the clone)
pip install --group dev
pip install -e ../pyodio

# Run all tests
pytest custom_components/odio_remote/tests/ -v

# Run a single test file
pytest custom_components/odio_remote/tests/test_config_flow.py -v

# Linting
ruff check custom_components/odio_remote/

# Type checking
mypy custom_components/odio_remote/
```

## Architecture

### Core Pattern: pyodio OdioHub (push, no coordinators)

All API communication and SSE state tracking is delegated to **pyodio's `OdioHub`** — a stateful client that snapshots the server on connect, then keeps live entity objects (`Player`, `AudioClient`, `AudioOutput`, `Service`, `BluetoothDevice`, upgrade status) in sync via the SSE stream, with automatic reconnection (backoff 1 s → 5 min) and a **full resync on every (re)connect**. There are no `DataUpdateCoordinator`s: HA entities read hub objects directly and subscribe to `namespace.on_change(cb)` callbacks (`cb(change, obj)`, returns an unsubscribe callable).

`async_setup_entry` (`__init__.py`):
1. `hub = OdioHub(api_url, async_get_clientsession(hass), keepalive=...)`, then `await hub.connect()`.
2. On `OdioError` (API down at boot): fall back to `StartupData.from_cache(entry.data)` and `await hub.start()` — the SSE loop connects in the background; entities come up from cached data and go live on first sync.
3. `StartupData` (`models.py`) wraps pyodio `ServerInfo` + `PowerCapabilities` and caches them in `entry.data` (plus `cached_services` for the switch platform).
4. `entry.runtime_data = OdioRemoteRuntimeData(hub, device_info, server_info, service_mappings, power_capabilities)`. Entities must read `runtime_data.server_info` (cache-safe), never `hub.server` (raises until first sync).

> **Backend re-detection on reconnect.** The backend set is read once at setup, so a software upgrade that adds a backend would go unnoticed. The hub resyncs (re-fetching `/server`) *before* reporting the connection, so the `hub.on_connection_change(True)` handler in `__init__.py` compares `hub.server.backends` to the setup snapshot and calls `async_schedule_reload` when they differ; otherwise it just re-caches `StartupData` (the hub already resynced all state itself).

`device_info.sw_version` tracks the upgrade detector's `current` version live via `hub.upgrade.on_change`.

### Entity base (`entity.py`)

`OdioEntity(hub, entry_id, device_info)` — unique_id `f"{entry_id}_{_unique_suffix}"`, availability `hub.connected and _has_data()`, subscribes to `hub.on_connection_change` plus whatever `_change_sources()` returns, filtered by `_relevant_change(change, obj)`. `OdioBluetoothEntity` binds to `hub.bluetooth`. Per-item entities (service switch, pulse client, MPRIS player) filter notifications by their own key to limit state writes on resync fan-out.

### Update Platform (`update.py`)

`OdioUpdateEntity` (only when `backends.upgrade`) reads `hub.upgrade` directly. `installed_version` is the detector `current` (fallback `server_info.api_version`); `latest_version` mirrors installed when no upgrade is available so HA reports "up to date". `supported_features` always includes `PROGRESS`, adds `INSTALL` only when `status.can_upgrade`. `async_install` → `hub.upgrade.start()`. Re-detection is intentionally **not** exposed (server-side systemd timer). The upgrade event semantics (the lifecycle `upgrade.info` `finished` event is the authoritative systemd job result; `upgrade.progress` drives `percent`/`step` only and never clears the run) live **in pyodio** and are tested there.

### Entity Types (`media_player.py`)

1. **`OdioReceiverMediaPlayer`** — the Odio instance itself. Always available; state OFF while disconnected. PLAYING when any audio client is uncorked or any MPRIS player plays. Volume read = mean of client volumes; write = `hub.audio.set_volume` (master). Mute via `hub.audio.set_muted(bool)` (pyodio compare+toggle — the server only toggles). Source select = default output via `AudioOutput.make_default()`.
2. **`OdioServiceMediaPlayer`** — one per mapped systemd service. ON/OFF wrapper (enable/disable via `hub.client`); media capabilities delegated through `MappedEntityMixin`.
3. **`OdioPulseClientMediaPlayer`** — remote PulseAudio clients (host ≠ server hostname), created dynamically via `hub.audio.on_change`. Client gone from the hub ⇒ state OFF.
4. **`OdioMPRISMediaPlayer`** — one per MPRIS app (deduped by app name; `helpers.extract_mpris_app_name` strips the `.instanceXXX` suffix pyodio's `app_name` keeps — it is load-bearing for unique_ids). Created dynamically via `hub.players.on_change` (ADDED); an app restart with a new bus_name **rebinds** the existing unavailable entity instead of creating one. `media_position` is the raw beacon (µs→s) + `media_position_updated_at` — HA extrapolates. `media_image_url` = `Player.cover_url` (server-side `/cover` proxy with cache-busting query) only when `art_url` is set.

### Entity Delegation (`mixins.py`)

`MappedEntityMixin` lets service/client/MPRIS entities wrap an existing `media_player` entity (play/pause/seek/metadata delegation). Mappings live in `entry.runtime_data.service_mappings` (`dict[str, str]`, keys `scope/name`, `client:<name>`, `mpris:<app>`); entities set `self._service_mappings` at init. Volume/mute fallback goes through the pyodio `AudioClient` live object.

### Config Flow (`config_flow.py`)

Uses the low-level `pyodio.OdioClient` (no hub — a validation call shouldn't open an SSE stream). `GET /services` returning 404 is tolerated (backend enabled but no units configured). Steps: user (validate URL) → sse (keepalive) → services (mappings). Options flow adds a **Mappings** step for services, remote clients, and MPRIS players. Schema building and mapping parsing are in `config_flow_helpers.py`, operating on pyodio dataclasses (`ServiceState`, `AudioClientState`, `PlayerState`).

### Errors

pyodio exceptions are used everywhere: `OdioError` → `OdioConnectionError` (⊃ `OdioTimeoutError`) and `OdioApiError(.status)`. The single HA boundary is the `helpers.api_command` decorator (`except OdioError` → `HomeAssistantError`).

### Constants (`const.py`)

Domain `odio_remote`, config keys, attribute names, `_MPRIS_BUS_PREFIX`. Endpoints and SSE event names now live in pyodio.

## Testing

Tests live in `custom_components/odio_remote/tests/`. `conftest.py` holds the dict fixtures (`MOCK_SERVER_INFO`, `MOCK_AUDIO_UNIFIED`, `MOCK_ALL_SERVICES`, `MOCK_BLUETOOTH_STATUS`, `MOCK_PLAYERS`, …) and the hub factory:

- `make_hub(...)` — a **real `OdioHub`** seeded from the dict fixtures through pyodio's own `from_dict` parsers, with `hub.client` replaced by `create_autospec(OdioClient)` (assert commands with `hub.client.<method>.assert_awaited_with(...)`; `player_cover_url` stays real).
- `push_event(hub, type, payload)` — feeds a raw SSE event through the hub's real dispatch/parsing path.
- `set_connected(hub, bool)` — flips SSE connectivity and notifies listeners.

Low-level REST/SSE parsing, reconnection, and upgrade-run semantics are tested **in the pyodio repo**, not here.

CI runs on Python 3.14 via `.github/workflows/ci.yml` (Home Assistant 2026.3+ requires Python 3.14). The dev dependency group pins pyodio from git; release builds will switch to a PyPI pin once pyodio has a stable release.
