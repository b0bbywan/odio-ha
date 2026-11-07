"""Tests for Odio Remote diagnostics."""
import json
import re
from unittest.mock import MagicMock

import pytest
from homeassistant.components.diagnostics import REDACTED
from pyodio import PowerCapabilities, ServerInfo

from custom_components.odio_remote import OdioRemoteRuntimeData
from custom_components.odio_remote.diagnostics import (
    _Pseudonymizer,
    async_get_config_entry_diagnostics,
)

from .conftest import (
    MOCK_ALL_SERVICES,
    MOCK_AUDIO_UNIFIED,
    MOCK_BLUETOOTH_STATUS,
    MOCK_CLIENTS,
    MOCK_DEVICE_INFO,
    MOCK_PLAYERS,
    MOCK_REMOTE_CLIENTS,
    MOCK_SERVER_INFO,
    make_hub,
)

SECRETS = [
    "htpc", "rasponkyo", "nas-2", "2a01:cb0c", "AA:BB:CC:DD:EE:FF",
    "11:22:33:44:55:66", "192.168.1.42", "remote-host", "xbmc", "pi@",
]


def _make_entry(hub):
    entry = MagicMock()
    entry.title = "Odio Remote (htpc)"
    entry.options = {"keepalive_interval": 30}
    entry.data = {
        "api_url": "http://192.168.1.42:8018",
        "mac": "11:22:33:44:55:66",
        "server_info": MOCK_SERVER_INFO,
    }
    entry.runtime_data = OdioRemoteRuntimeData(
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        server_info=ServerInfo.from_dict(MOCK_SERVER_INFO),
        service_mappings={"client:RemoteClient": "media_player.remote"},
        power_capabilities=PowerCapabilities(power_off=True, reboot=True),
    )
    return entry


async def _full_dump():
    hub = make_hub(
        audio={**MOCK_AUDIO_UNIFIED, "clients": MOCK_CLIENTS + MOCK_REMOTE_CLIENTS},
        bluetooth=MOCK_BLUETOOTH_STATUS,
        players=MOCK_PLAYERS,
        services=MOCK_ALL_SERVICES,
    )
    return await async_get_config_entry_diagnostics(MagicMock(), _make_entry(hub))


class TestConfigEntryDiagnostics:

    @pytest.mark.asyncio
    async def test_no_sensitive_value_leaks(self):
        dumped = json.dumps(await _full_dump(), default=str)
        for secret in SECRETS:
            assert secret.lower() not in dumped.lower(), secret

    @pytest.mark.asyncio
    async def test_tokens_are_consistent_across_fields(self):
        diag = await _full_dump()
        server_host = diag["server_info"]["hostname"]
        assert re.fullmatch(r"<host_\d+>", server_host)
        assert diag["entry"]["title"] == f"Odio Remote ({server_host})"
        assert diag["entry"]["data"]["server_info"]["hostname"] == server_host
        local, remote = diag["audio"]["clients"]
        assert local["host"] == server_host
        assert remote["host"] != server_host
        assert diag["bluetooth"]["state"]["known_devices"][0]["address"] == (
            diag["bluetooth"]["devices"][0]["address"]
        )

    @pytest.mark.asyncio
    async def test_free_form_strings_keep_their_shape(self):
        diag = await _full_dump()
        names = [o["name"] for o in diag["audio"]["outputs"]]
        descriptions = [o["description"] for o in diag["audio"]["outputs"]]
        assert "alsa_output.pci-0000_00_1f.3.analog-stereo" in names
        assert any(
            re.fullmatch(r"raop_sink\.<host_\d+>\.local\.<ipv6_\d+>\.5000", n) for n in names
        )
        assert any(
            re.fullmatch(r"Built-in Audio Stereo on <user_\d+>@<host_\d+>", d)
            for d in descriptions
        )
        assert diag["entry"]["data"]["api_url"] == "http://<ip_1>:8018"
        assert diag["entry"]["data"]["mac"] == "<mac_1>"

    @pytest.mark.asyncio
    async def test_airplay_names_tokenized(self):
        hub = make_hub(audio={**MOCK_AUDIO_UNIFIED, "outputs": [
            {"name": "raop_sink.a.local.10.0.0.1.5000", "description": "SnapAir"},
            {"name": "raop_sink.b.local.10.0.0.2.5000", "description": "SnapAir"},
            {"name": "raop_sink.kodi.local.10.0.0.3.5000", "description": "kodi"},
            {"name": "tunnel.c.local.sink", "description": "Stereo on pi@c"},
        ]})
        diag = await async_get_config_entry_diagnostics(MagicMock(), _make_entry(hub))
        descriptions = [o["description"] for o in diag["audio"]["outputs"]]
        assert descriptions[0] == descriptions[1] == "<airplay_1>"
        assert re.fullmatch(r"<host_\d+>", descriptions[2])
        assert re.fullmatch(r"Stereo on <user_\d+>@<host_\d+>", descriptions[3])

    @pytest.mark.asyncio
    async def test_airplay_sink_named_after_bluetooth_device_shares_token(self):
        bluetooth = {**MOCK_BLUETOOTH_STATUS, "known_devices": [
            {**MOCK_BLUETOOTH_STATUS["known_devices"][0], "name": "SnapAir"},
        ]}
        hub = make_hub(audio=MOCK_AUDIO_UNIFIED, bluetooth=bluetooth)
        diag = await async_get_config_entry_diagnostics(MagicMock(), _make_entry(hub))
        raop = next(o for o in diag["audio"]["outputs"] if o["name"].startswith("raop_sink."))
        assert raop["description"] == diag["bluetooth"]["devices"][0]["name"] == "<bt_1>"

    @pytest.mark.asyncio
    async def test_bluez_sink_shares_device_tokens(self):
        hub = make_hub(
            audio={**MOCK_AUDIO_UNIFIED, "outputs": [
                {"name": "bluez_output.AA_BB_CC_DD_EE_FF.1", "description": "Pixel 6a"},
            ]},
            bluetooth=MOCK_BLUETOOTH_STATUS,
        )
        diag = await async_get_config_entry_diagnostics(MagicMock(), _make_entry(hub))
        device = diag["bluetooth"]["devices"][0]
        assert diag["audio"]["outputs"][0]["name"] == f"bluez_output.{device['address']}.1"
        assert diag["audio"]["outputs"][0]["description"] == device["name"]

    @pytest.mark.asyncio
    async def test_props_dropped_and_metadata_values_hidden(self):
        diag = await _full_dump()
        assert all(c["props"] == REDACTED for c in diag["audio"]["clients"])
        metadata = diag["players"][0]["metadata"]
        assert "xesam:title" in metadata
        assert set(metadata.values()) == {REDACTED}

    @pytest.mark.asyncio
    async def test_non_sensitive_values_untouched(self):
        diag = await _full_dump()
        assert diag["connected"] is True
        assert diag["server_info"]["os_version"] == MOCK_SERVER_INFO["os_version"]
        assert diag["server_info"]["api_sw"] == "odio-api"
        assert diag["players"][0]["bus_name"] == MOCK_PLAYERS[0]["bus_name"]
        assert diag["service_mappings"] == {"client:RemoteClient": "media_player.<entity_1>"}
        units = [s["name"] for s in diag["services"]]
        assert "firefox-kiosk@netflix.com.service" in units

    @pytest.mark.asyncio
    async def test_unit_names_kept_when_instance_is_hostname(self):
        unit = "snapclient@htpc.service"
        hub = make_hub(services=[{"name": unit, "scope": "user", "exists": True}])
        entry = _make_entry(hub)
        entry.runtime_data.service_mappings = {f"user/{unit}": "media_player.htpc_snap"}
        entry.data["cached_services"] = [{"name": unit, "scope": "user"}]
        diag = await async_get_config_entry_diagnostics(MagicMock(), entry)
        assert diag["services"][0]["name"] == unit
        assert diag["entry"]["data"]["cached_services"][0]["name"] == unit
        assert diag["service_mappings"] == {f"user/{unit}": "media_player.<entity_1>"}

    @pytest.mark.asyncio
    async def test_missing_hub_state_is_none(self):
        hub = make_hub(connected=False)
        diag = await async_get_config_entry_diagnostics(MagicMock(), _make_entry(hub))
        assert diag["connected"] is False
        assert diag["audio"] == {"server": None, "clients": [], "outputs": []}
        assert diag["bluetooth"] == {"state": None, "devices": []}
        assert diag["upgrade"] is None
        assert diag["players"] == []


class TestPseudonymizer:

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("fe80::1", "<ipv6_1>"),
            ("[2001:db8::42]:8018", "[<ipv6_1>]:8018"),
            ("::ffff:10.0.0.7", "<ipv6_1>"),
            ("http://[::ffff:10.0.0.7]:8018", "http://[<ipv6_1>]:8018"),
            ("10.0.0.7", "<ip_1>"),
            ("aa-bb-cc-dd-ee-ff", "<mac_1>"),
            ("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF", "/org/bluez/hci0/dev_<mac_1>"),
            ("aa_bb_cc_dd_ee_ff AA:BB:CC:DD:EE:FF", "<mac_1> <mac_1>"),
            ("kodi.local", "<host_1>.local"),
            ("bob@laptop", "<user_1>@<host_1>"),
        ],
    )
    def test_patterns(self, text, expected):
        assert _Pseudonymizer().scrub(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "19:06:00", "PipeWire 1.4.2", "999.1.1.1", "v0.6.0-rc.1-main",
            "alsa_output.pci-0000_00_1f.3", "aa:bb_cc:dd_ee:ff",
        ],
    )
    def test_lookalikes_untouched(self, text):
        assert _Pseudonymizer().scrub(text) == text

    def test_known_host_matches_whole_labels_only(self):
        pseudo = _Pseudonymizer()
        pseudo.add_known("host", "htpc")
        assert pseudo.scrub("htpc-api on HTPC") == "htpc-api on <host_1>"

    def test_stock_odio_name_never_tokenized(self):
        pseudo = _Pseudonymizer()
        pseudo.add_known("host", "odio")
        pseudo.add_known("host", "odio.local")
        assert [pseudo.scrub(s) for s in (
            "Tunnel for odio@odio", "http://odio.local:8018", "pi@odio-2",
        )] == ["Tunnel for odio@odio", "http://odio.local:8018", "<user_1>@<host_1>"]

    def test_whole_values_match_entire_strings_only(self):
        pseudo = _Pseudonymizer()
        pseudo.add_whole("bt", "TV")
        assert [pseudo.scrub(s) for s in ("tv", "arte.tv", "TV Speaker")] == [
            "<bt_1>", "arte.tv", "TV Speaker",
        ]

    def test_known_host_wins_over_whole_value(self):
        pseudo = _Pseudonymizer()
        pseudo.add_whole("bt", "raspodio")
        pseudo.add_known("host", "raspodio")
        assert pseudo.scrub("raspodio") == "<host_1>"

    def test_only_mapping_keys_scrubbed(self):
        pseudo = _Pseudonymizer()
        pseudo.add_known("host", "audio")
        data = {"audio": {"service_mappings": {"client:Tunnel for pi@audio": "x"}}}
        assert pseudo.pseudonymize(data) == {
            "audio": {"service_mappings": {"client:Tunnel for <user_1>@<host_1>": "x"}},
        }

    def test_same_value_same_token(self):
        pseudo = _Pseudonymizer()
        assert pseudo.scrub("10.0.0.7 10.0.0.8 10.0.0.7") == "<ip_1> <ip_2> <ip_1>"

    def test_ipv4_between_dots(self):
        assert _Pseudonymizer().scrub("raop_sink.x.local.192.168.1.21.5000") == (
            "raop_sink.<host_1>.local.<ip_1>.5000"
        )

    def test_discovered_hosts_scrubbed_everywhere(self):
        data = {
            "name": "raop_sink.raspodio.local.fe80::1.5000",
            "description": "raspodio",
            "client": "Tunnel for pi@rasponkyo",
            "other": "rasponkyo",
            "entity": "media_player.raspodio_music_player_daemon",
        }
        assert _Pseudonymizer().pseudonymize(data) == {
            "name": "raop_sink.<host_1>.local.<ipv6_1>.5000",
            "description": "<host_1>",
            "client": "Tunnel for <user_1>@<host_2>",
            "other": "<host_2>",
            "entity": "media_player.<host_1>_music_player_daemon",
        }

    def test_kept_values_neither_scrubbed_nor_learned_from(self):
        pseudo = _Pseudonymizer()
        pseudo.add_known("host", "htpc")
        pseudo.keep("kiosk@htpc.service")
        pseudo.keep("user/firefox-kiosk@netflix.service")
        data = {
            "user/firefox-kiosk@netflix.service": "kiosk@htpc.service",
            "description": "netflix on htpc",
        }
        assert pseudo.pseudonymize(data) == {
            "user/firefox-kiosk@netflix.service": "kiosk@htpc.service",
            "description": "netflix on <host_1>",
        }
