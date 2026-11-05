"""Diagnostics replayed from real dumps (fixtures/diagnostics).

Each fixture is a real dump plus made-up plaintext for its tokens: the hub is
rebuilt from the dump with tokens swapped back, then must dump identically.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.json import json_bytes
from pyodio import PowerCapabilities, ServerInfo, TracklistState

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.diagnostics import (
    _Pseudonymizer,
    async_get_config_entry_diagnostics,
)

from .conftest import MOCK_DEVICE_INFO, make_hub

FIXTURES = Path(__file__).parent / "fixtures" / "diagnostics"
DUMPS = sorted(p.stem for p in FIXTURES.glob("*.json"))
_TOKEN = re.compile(r"<(?:host|ip|ipv6|mac|user|airplay|bt|entity)_\d+>")
_REDACTED = "**REDACTED**"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _detokenize(data: Any, values: dict[str, str]) -> Any:
    if isinstance(data, dict):
        return {
            _detokenize(k, values): (
                {} if v == _REDACTED and k == "props"
                else {mk: "x" for mk in v} if k == "metadata"
                else _detokenize(v, values)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_detokenize(v, values) for v in data]
    if isinstance(data, str):
        return _TOKEN.sub(lambda m: values[m[0]], data)
    return data


async def _replay(name: str, **values: str) -> dict[str, Any]:
    """Dump the fixture's installation, with token values optionally overridden."""
    fixture = _load(name)
    raw = _detokenize(fixture["dump"], {**fixture["values"], **values})
    audio = raw["audio"]
    hub = make_hub(
        server_info=raw["server_info"],
        services=raw["services"],
        audio=(
            {"kind": audio["server"]["kind"], "clients": audio["clients"],
             "outputs": audio["outputs"]}
            if audio["server"] else None
        ),
        audio_server=audio["server"],
        bluetooth=raw["bluetooth"]["state"],
        players=[
            {k: v for k, v in p.items() if k not in ("available", "tracklist")}
            for p in raw["players"]
        ],
        upgrade=raw["upgrade"],
        connected=raw["connected"],
    )
    for p in raw["players"]:
        if p["tracklist"]:
            hub.players[p["bus_name"]].tracklist = TracklistState.from_dict(p["tracklist"])
    entry: Any = SimpleNamespace(
        title=raw["entry"]["title"],
        data=raw["entry"]["data"],
        options=raw["entry"]["options"],
        runtime_data=OdioRemoteRuntimeData(
            hub=hub,
            device_info=MOCK_DEVICE_INFO,
            server_info=ServerInfo.from_dict(raw["server_info"]),
            service_mappings=raw["service_mappings"],
            power_capabilities=PowerCapabilities.from_dict(raw["power_capabilities"]),
        ),
    )
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)
    # Through HA's own serializer, as the download does.
    return json.loads(json_bytes(result))


def _key_paths(data: Any, path: tuple = ()) -> set[tuple]:
    if isinstance(data, dict):
        return {path + (k,) for k in data} | {
            p for k, v in data.items() for p in _key_paths(v, path + (k,))
        }
    if isinstance(data, list):
        return {p for i, v in enumerate(data) for p in _key_paths(v, path + (i,))}
    return set()


@pytest.mark.parametrize("name", DUMPS)
async def test_real_dump_reproduced(name):
    """Baseline: the harness reproduces every real dump byte for byte."""
    assert await _replay(name) == _load(name)["dump"]


# --- Hostname colliding with a dump key ------------------------------------


@pytest.mark.parametrize("hostname", ["audio", "name", "bluetooth", "mpd"])
async def test_hostname_never_renames_dump_keys(hostname):
    expected = _key_paths(_load("rpi4_upgrade_available")["dump"])
    diag = await _replay("rpi4_upgrade_available", **{"<host_1>": hostname})
    assert _key_paths(diag) == expected


# --- Stock odios image: hostname "odio", kiosk unit odio-kiosk@odio.service --


@pytest.mark.parametrize("name", ["rpi4_upgrade_available", "rpi_bluetooth_mappings"])
async def test_stock_hostname_keeps_template_unit(name):
    diag = await _replay(name, **{"<host_1>": "odio"})
    catalog = diag["upgrade"]["extra"]["manifest"]["catalog"]
    assert catalog["display"]["services"] == ["odio-kiosk@odio.service"]


async def test_stock_hostname_keeps_odio_strings():
    diag = await _replay("rpi4_upgrade_available", **{"<host_1>": "odio"})
    catalog = diag["upgrade"]["extra"]["manifest"]["catalog"]
    assert diag["entry"]["title"] == "Odio Remote"
    assert catalog["branding"]["description"] == "odio login banner"
    assert catalog["upgrade"]["description"] == "Keeps odio up to date"


async def test_stock_hostname_and_user_stay_plain():
    diag = await _replay(
        "rpi_tunnel_client", **{"<host_1>": "odio", "<user_1>": "odio"}
    )
    assert diag["server_info"]["hostname"] == "odio"
    assert diag["audio"]["clients"][0]["user"] == "odio"
    assert diag["audio"]["clients"][0]["name"] == "Tunnel for odio@<host_1>"


async def test_stock_hostname_keeps_cached_service_descriptions():
    diag = await _replay("x86_offline", **{"<host_1>": "odio"})
    descriptions = [s["description"] for s in diag["entry"]["data"]["cached_services"]]
    assert "Odio Dashboard UI" in descriptions


# --- Common-word hostname ---------------------------------------------------


@pytest.mark.parametrize(
    ("name", "hostname", "os_version"),
    [
        ("rpi4_upgrade_available", "debian", "Debian GNU/Linux 13 (trixie)"),
        ("fedora_network_sinks", "fedora", "Fedora Linux 44 (Workstation Edition)"),
    ],
)
async def test_distro_default_hostname_keeps_os_version(name, hostname, os_version):
    diag = await _replay(name, **{"<host_1>": hostname})
    assert diag["server_info"]["hostname"] == "<host_1>"
    assert diag["server_info"]["os_version"] == os_version
    assert diag["entry"]["data"]["server_info"]["os_version"] == os_version


# --- Leaks seen in rpi_bluetooth_mappings (dumped by the current code) -----


async def test_bluetooth_device_names_pseudonymized():
    diag = await _replay("rpi_bluetooth_mappings")
    names = [d["name"] for d in diag["bluetooth"]["devices"]]
    names += [d["name"] for d in diag["bluetooth"]["state"]["known_devices"]]
    assert names and all(_TOKEN.fullmatch(n) for n in names), names


@pytest.mark.parametrize(
    "plaintext",
    [
        "oldpi",         # machine name in third-party entity ids
        "carol",         # Spotify username: media_player.spotify_<user>
        "b827eb000007",  # server MAC inside the upmpdcli OpenHome UUID
    ],
)
async def test_mapped_entity_ids_do_not_leak(plaintext):
    diag = await _replay("rpi_bluetooth_mappings")
    assert plaintext not in json.dumps(diag)


# --- Pattern edge cases (not seen in the dumps) -----------------------------


def test_ipv4_mapped_ipv6_fully_scrubbed():
    assert _Pseudonymizer().scrub("raop_sink.x.local.::ffff:192.168.1.10.5000") == (
        "raop_sink.<host_1>.local.<ipv6_1>.5000"
    )
