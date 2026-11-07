"""Diagnostics for Odio Remote."""
from __future__ import annotations

import ipaddress
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pyodio import ServiceScope, UpgradeStatus

from . import OdioConfigEntry
from .const import CONF_API_URL, CONF_SERVICE_MAPPINGS

_SCOPES = {str(scope) for scope in ServiceScope}

# Values replaced by a pseudonym token wherever they appear.
_HOST_KEYS = {"hostname", "host"}
_USER_KEYS = {"user"}
# Free-form PipeWire properties: too open-ended to scrub reliably.
_DROP_KEYS = {"props"}
# Track metadata: keep the keys, hide what is being played.
_METADATA_KEYS = {"metadata"}

# odios image defaults (hostname, user, BT/AirPlay name): identify nothing.
_STOCK = {"odio"}

# Hostname-valid chars ("_" is not one, so entity ids are covered too).
_HOST_EDGE = r"A-Za-z0-9\-"
# "_" as in bluez_output.AA_BB_CC_DD_EE_FF.1 and BlueZ dev_AA_BB_... paths.
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}([:_-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}"
    r"(?![0-9A-Fa-f:])"
)
_IPV6_RE = re.compile(
    r"(?<![0-9A-Za-z:])(?:"
    # IPv4 tail first, else ::ffff:192.168.1.10 stops at ::ffff:192.
    r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){1,6}:(?:\d{1,3}\.){3}\d{1,3}"
    r"|[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}"
    r")(?![0-9A-Za-z:])"
)
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_LOCAL_RE = re.compile(rf"(?<![{_HOST_EDGE}])([A-Za-z0-9][A-Za-z0-9\-]*)\.local(?![{_HOST_EDGE}])")
_TOKEN_RE = re.compile(r"<\w+_\d+>")
_USER_AT_RE = re.compile(r"(?<![A-Za-z0-9_.\-])([A-Za-z0-9_.\-]+)@(<\w+>|[A-Za-z0-9][A-Za-z0-9\-]*)")


class _Pseudonymizer:
    """Replace sensitive values with tokens that are stable within one dump."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: Counter[str] = Counter()
        self._known: dict[str, str] = {}
        self._known_re: re.Pattern[str] | None = None
        self._whole: dict[str, str] = {}
        self._verbatim: set[str] = set()

    def keep(self, value: str) -> None:
        """Never scrub value, nor learn hostnames from it."""
        self._verbatim.add(value)

    def token(self, kind: str, value: str) -> str:
        if _is_stock(value):
            return value
        if kind == "mac":
            value = re.sub("[_-]", ":", value)
        key = (kind, value if kind == "user" else value.lower())
        if key not in self._tokens:
            self._counts[kind] += 1
            self._tokens[key] = f"<{kind}_{self._counts[kind]}>"
        return self._tokens[key]

    def add_known(self, kind: str, value: str | None) -> None:
        if value and not _is_stock(value):
            self._known[value.lower()] = kind
            self._known_re = None

    def add_whole(self, kind: str, value: str | None) -> None:
        """Tokenize strings equal to value only: generic names ("TV") stay safe."""
        if value:
            self._whole[value.lower()] = kind

    def _host_token(self, value: str) -> str:
        return self.token(_ip_kind(value) or "host", value)

    def scrub(self, text: str) -> str:
        if text in self._verbatim:
            return text
        kind = self._whole.get(text.lower())
        if kind and text.lower() not in self._known:
            return self.token(kind, text)
        if self._known and self._known_re is None:
            alternatives = "|".join(
                re.escape(v) for v in sorted(self._known, key=len, reverse=True)
            )
            self._known_re = re.compile(
                rf"(?<![{_HOST_EDGE}])(?:{alternatives})(?![{_HOST_EDGE}])",
                re.IGNORECASE,
            )
        if self._known_re is not None:
            text = self._known_re.sub(
                lambda m: self.token(self._known[m[0].lower()], m[0]), text
            )
        text = _MAC_RE.sub(lambda m: self.token("mac", m[0]), text)
        text = _IPV6_RE.sub(
            lambda m: self.token("ipv6", m[0]) if _ip_kind(m[0]) == "ipv6" else m[0],
            text,
        )
        text = _IPV4_RE.sub(
            lambda m: self.token("ip", m[0]) if _ip_kind(m[0]) == "ip" else m[0],
            text,
        )
        text = _LOCAL_RE.sub(lambda m: f"{self.token('host', m[1])}.local", text)
        return _USER_AT_RE.sub(
            lambda m: f"{self.token('user', m[1])}@"
            f"{m[2] if m[2].startswith('<') else self.token('host', m[2])}",
            text,
        )

    def pseudonymize(self, data: Any) -> Any:
        """Learn LAN hostnames from every string, then scrub."""
        self._discover(data)
        return self.walk(data)

    def _discover(self, data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if key not in _DROP_KEYS and key not in _METADATA_KEYS:
                    self._discover(key)
                    self._discover(value)
        elif isinstance(data, (list, tuple)):
            for item in data:
                self._discover(item)
        elif isinstance(data, str) and data not in self._verbatim:
            hosts = [m[1] for m in _LOCAL_RE.finditer(data)]
            hosts += [m[2] for m in _USER_AT_RE.finditer(data)]
            for host in hosts:
                # Digits-only would be an IP fragment.
                if re.search(r"[A-Za-z]", host):
                    self.add_known("host", host)

    def walk(self, data: Any, scrub_keys: bool = False) -> Any:
        if isinstance(data, dict):
            out: dict[Any, Any] = {}
            for key, value in data.items():
                skey = self.scrub(key) if scrub_keys and isinstance(key, str) else key
                if key in _DROP_KEYS:
                    out[skey] = REDACTED
                elif key in _METADATA_KEYS and isinstance(value, dict):
                    out[skey] = dict.fromkeys(value, REDACTED)
                elif key in _HOST_KEYS and isinstance(value, str) and value:
                    out[skey] = self._host_token(value)
                elif key in _USER_KEYS and isinstance(value, str) and value:
                    out[skey] = self.token("user", value)
                else:
                    out[skey] = self.walk(value, key == CONF_SERVICE_MAPPINGS)
            return out
        if isinstance(data, (list, tuple)):
            return [self.walk(item) for item in data]
        if isinstance(data, str):
            return self.scrub(data)
        return data


def _is_stock(value: str) -> bool:
    return value.lower().removesuffix(".local") in _STOCK


def _ip_kind(value: str) -> str | None:
    try:
        return "ip" if ipaddress.ip_address(value).version == 4 else "ipv6"
    except ValueError:
        return None


def _mask_entities(pseudo: _Pseudonymizer, mappings: dict[str, Any]) -> dict[str, Any]:
    """Tokenize mapped entity ids: third-party names (users, MACs, old hosts)."""
    masked: dict[str, Any] = {}
    for key, entity_id in mappings.items():
        if isinstance(entity_id, str):
            domain, _, object_id = entity_id.rpartition(".")
            entity_id = f"{domain}.{pseudo.token('entity', object_id)}" if domain else (
                pseudo.token("entity", object_id)
            )
        masked[key] = entity_id
    return masked


def _unit_names(
    entry: OdioConfigEntry, upgrade: UpgradeStatus | None
) -> Iterator[str]:
    """systemd units: whitelisted or catalog names, kept verbatim for debugging."""
    services = [(s.state.scope, s.state.name) for s in entry.runtime_data.hub.services.values()]
    services += [
        (s.get("scope", ""), s.get("name", ""))
        for s in entry.data.get("cached_services") or []
        if isinstance(s, dict)
    ]
    for scope, name in services:
        yield name
        yield f"{scope}/{name}"
    mappings = entry.options.get(CONF_SERVICE_MAPPINGS) or {}
    for key in [*entry.runtime_data.service_mappings, *mappings]:
        scope, _, name = key.partition("/")
        if scope in _SCOPES and name:
            yield key
            yield name
    manifest = upgrade.extra.get("manifest") if upgrade else None
    catalog = manifest.get("catalog") if isinstance(manifest, dict) else None
    for role in catalog.values() if isinstance(catalog, dict) else []:
        if isinstance(role, dict) and isinstance(role.get("services"), list):
            yield from (s for s in role["services"] if isinstance(s, str))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> dict[str, Any]:
    """Return pseudonymized diagnostics for a config entry."""
    runtime = entry.runtime_data
    hub = runtime.hub
    audio = hub.audio
    bluetooth = hub.bluetooth
    upgrade = hub.upgrade.status

    pseudo = _Pseudonymizer()
    options = dict(entry.options)
    if isinstance(options.get(CONF_SERVICE_MAPPINGS), dict):
        options[CONF_SERVICE_MAPPINGS] = _mask_entities(pseudo, options[CONF_SERVICE_MAPPINGS])

    data = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": options,
        },
        "connected": hub.connected,
        "server_info": asdict(runtime.server_info),
        "power_capabilities": asdict(runtime.power_capabilities),
        "service_mappings": _mask_entities(pseudo, runtime.service_mappings),
        "audio": {
            "server": asdict(audio.server) if audio.server else None,
            "clients": [asdict(c.state) for c in audio.clients.values()],
            "outputs": [asdict(o.state) for o in audio.outputs.values()],
        },
        "players": [
            {
                **asdict(p.state),
                "available": p.available,
                "tracklist": asdict(p.tracklist) if p.tracklist else None,
            }
            for p in hub.players.values()
        ],
        "services": [asdict(s.state) for s in hub.services.values()],
        "bluetooth": {
            "state": asdict(bluetooth.state) if bluetooth.state else None,
            "devices": [asdict(d.state) for d in bluetooth.devices.values()],
        },
        "upgrade": asdict(upgrade) if upgrade else None,
    }

    for unit in _unit_names(entry, upgrade):
        pseudo.keep(unit)
    api_host = urlparse(entry.data.get(CONF_API_URL, "")).hostname
    if api_host:
        pseudo.add_known(_ip_kind(api_host) or "host", api_host)
    pseudo.add_known("host", runtime.server_info.hostname)
    pseudo.add_known("mac", entry.data.get("mac"))
    for client in audio.clients.values():
        pseudo.add_known("host", client.state.host)
    for device in bluetooth.devices.values():
        pseudo.add_known("mac", device.address)
        # Often owner-named; also the announced name of AirPlay sinks.
        pseudo.add_whole("bt", device.name)
    result: dict[str, Any] = pseudo.pseudonymize(data)
    # AirPlay sink descriptions are free-form announced names.
    for output in result["audio"]["outputs"]:
        desc = output.get("description")
        if output["name"].startswith("raop_sink.") and desc and not _TOKEN_RE.fullmatch(desc):
            output["description"] = pseudo.token("airplay", desc)
    return result
