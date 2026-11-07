"""Diagnostics for Odio Remote."""
from __future__ import annotations

import ipaddress
import re
from collections import Counter
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from . import OdioConfigEntry
from .const import CONF_API_URL

# Values replaced by a pseudonym token wherever they appear.
_HOST_KEYS = {"hostname", "host"}
_USER_KEYS = {"user"}
# Free-form PipeWire properties: too open-ended to scrub reliably.
_DROP_KEYS = {"props"}
# Track metadata: keep the keys, hide what is being played.
_METADATA_KEYS = {"metadata"}

# Hostname-valid chars ("_" is not one, so entity ids are covered too).
_HOST_EDGE = r"A-Za-z0-9\-"
_MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])"
)
_IPV6_RE = re.compile(
    r"(?<![0-9A-Za-z:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![0-9A-Za-z:])"
)
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_LOCAL_RE = re.compile(rf"(?<![{_HOST_EDGE}])([A-Za-z0-9][A-Za-z0-9\-]*)\.local(?![{_HOST_EDGE}])")
# systemd template units (unit@instance.service) are not user@host.
_UNIT_RE = re.compile(r"(?:\w+/)?[\w:.\-]+@[\w:.\-]*\.(?:service|socket|timer|target|path|mount)")
_TOKEN_RE = re.compile(r"<\w+_\d+>")
_USER_AT_RE = re.compile(r"(?<![A-Za-z0-9_.\-])([A-Za-z0-9_.\-]+)@(<\w+>|[A-Za-z0-9][A-Za-z0-9\-]*)")


class _Pseudonymizer:
    """Replace sensitive values with tokens that are stable within one dump."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: Counter[str] = Counter()
        self._known: dict[str, str] = {}
        self._known_re: re.Pattern[str] | None = None

    def token(self, kind: str, value: str) -> str:
        key = (kind, value if kind == "user" else value.lower())
        if key not in self._tokens:
            self._counts[kind] += 1
            self._tokens[key] = f"<{kind}_{self._counts[kind]}>"
        return self._tokens[key]

    def add_known(self, kind: str, value: str | None) -> None:
        if value:
            self._known[value.lower()] = kind
            self._known_re = None

    def _host_token(self, value: str) -> str:
        return self.token(_ip_kind(value) or "host", value)

    def scrub(self, text: str) -> str:
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
        if _UNIT_RE.fullmatch(text):
            return text
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
        elif isinstance(data, str):
            hosts = [m[1] for m in _LOCAL_RE.finditer(data)]
            if not _UNIT_RE.fullmatch(data):
                hosts += [m[2] for m in _USER_AT_RE.finditer(data)]
            for host in hosts:
                # Digits-only would be an IP fragment.
                if re.search(r"[A-Za-z]", host):
                    self.add_known("host", host)

    def walk(self, data: Any) -> Any:
        if isinstance(data, dict):
            out: dict[Any, Any] = {}
            for key, value in data.items():
                skey = self.scrub(key) if isinstance(key, str) else key
                if key in _DROP_KEYS:
                    out[skey] = REDACTED
                elif key in _METADATA_KEYS and isinstance(value, dict):
                    out[skey] = dict.fromkeys(value, REDACTED)
                elif key in _HOST_KEYS and isinstance(value, str) and value:
                    out[skey] = self._host_token(value)
                elif key in _USER_KEYS and isinstance(value, str) and value:
                    out[skey] = self.token("user", value)
                else:
                    out[skey] = self.walk(value)
            return out
        if isinstance(data, (list, tuple)):
            return [self.walk(item) for item in data]
        if isinstance(data, str):
            return self.scrub(data)
        return data


def _ip_kind(value: str) -> str | None:
    try:
        return "ip" if ipaddress.ip_address(value).version == 4 else "ipv6"
    except ValueError:
        return None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OdioConfigEntry
) -> dict[str, Any]:
    """Return pseudonymized diagnostics for a config entry."""
    runtime = entry.runtime_data
    hub = runtime.hub
    audio = hub.audio
    bluetooth = hub.bluetooth
    upgrade = hub.upgrade.status

    data = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "connected": hub.connected,
        "server_info": asdict(runtime.server_info),
        "power_capabilities": asdict(runtime.power_capabilities),
        "service_mappings": runtime.service_mappings,
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

    pseudo = _Pseudonymizer()
    api_host = urlparse(entry.data.get(CONF_API_URL, "")).hostname
    if api_host:
        pseudo.add_known(_ip_kind(api_host) or "host", api_host)
    pseudo.add_known("host", runtime.server_info.hostname)
    pseudo.add_known("mac", entry.data.get("mac"))
    for client in audio.clients.values():
        pseudo.add_known("host", client.state.host)
    for device in bluetooth.devices.values():
        pseudo.add_known("mac", device.address)
    result: dict[str, Any] = pseudo.pseudonymize(data)
    # AirPlay sink descriptions are free-form announced names.
    for output in result["audio"]["outputs"]:
        desc = output.get("description")
        if output["name"].startswith("raop_sink.") and desc and not _TOKEN_RE.fullmatch(desc):
            output["description"] = pseudo.token("airplay", desc)
    return result
