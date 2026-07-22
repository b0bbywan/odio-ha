"""Tests for OdioReceiverMediaPlayer source (audio output) features."""
from homeassistant.components.media_player import MediaPlayerEntityFeature
from pyodio import Backends

from custom_components.odio_remote.media_player import (
    OdioReceiverMediaPlayer,
    _MediaPlayerContext,
)

from .conftest import MOCK_CLIENTS, MOCK_DEVICE_INFO, MOCK_OUTPUTS, make_hub

ENTRY_ID = "test_entry_id"


def _make_receiver(outputs=None, backends=None, seed_audio=True):
    audio = None
    if seed_audio:
        audio = {"kind": "pipewire", "clients": MOCK_CLIENTS, "outputs": outputs or []}
    hub = make_hub(audio=audio)
    ctx = _MediaPlayerContext(
        entry_id=ENTRY_ID,
        hub=hub,
        device_info=MOCK_DEVICE_INFO,
        service_mappings={},
        backends=backends if backends is not None else hub.server.backends,
        server_hostname="htpc",
    )
    return OdioReceiverMediaPlayer(ctx), hub


# ---------------------------------------------------------------------------
# source_list
# ---------------------------------------------------------------------------

class TestReceiverSourceList:

    def test_returns_output_descriptions(self):
        receiver, _ = _make_receiver(outputs=MOCK_OUTPUTS)
        sources = receiver.source_list
        assert len(sources) == 5
        assert "Built-in Audio Analog Stereo" in sources
        assert "SnapAir" in sources
        assert "Audio interne Stéréo on pi@rasponkyold" in sources

    def test_returns_none_when_no_outputs(self):
        receiver, _ = _make_receiver(outputs=[])
        assert receiver.source_list is None

    def test_returns_none_when_no_audio_data(self):
        receiver, _ = _make_receiver(seed_audio=False)
        assert receiver.source_list is None


# ---------------------------------------------------------------------------
# source (current)
# ---------------------------------------------------------------------------

class TestReceiverSource:

    def test_returns_default_output(self):
        receiver, _ = _make_receiver(outputs=MOCK_OUTPUTS)
        assert receiver.source == "Audio interne Stéréo on pi@rasponkyold"

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "description": "Sink", "default": False}]
        receiver, _ = _make_receiver(outputs=outputs)
        assert receiver.source is None

    def test_returns_none_when_no_audio_data(self):
        receiver, _ = _make_receiver(seed_audio=False)
        assert receiver.source is None


# ---------------------------------------------------------------------------
# async_select_source
# ---------------------------------------------------------------------------

class TestReceiverSelectSource:

    async def test_calls_api_with_output_name(self):
        receiver, hub = _make_receiver(outputs=MOCK_OUTPUTS)

        await receiver.async_select_source("SnapAir")

        hub.client.set_default_output.assert_awaited_once_with(
            "raop_sink.nas-2.local.2a01:cb0c:796:200:3285:a9ff:fe40:f90f.5000"
        )

    async def test_unknown_source_does_nothing(self):
        receiver, hub = _make_receiver(outputs=MOCK_OUTPUTS)

        await receiver.async_select_source("Nonexistent")

        hub.client.set_default_output.assert_not_awaited()


# ---------------------------------------------------------------------------
# supported_features includes SELECT_SOURCE
# ---------------------------------------------------------------------------

class TestReceiverSupportedFeatures:

    def test_includes_select_source_with_pulseaudio(self):
        receiver, _ = _make_receiver(outputs=MOCK_OUTPUTS)
        assert receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE

    def test_includes_select_source_even_without_outputs(self):
        receiver, _ = _make_receiver(outputs=[])
        assert receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE

    def test_no_select_source_when_no_pulseaudio(self):
        receiver, _ = _make_receiver(outputs=MOCK_OUTPUTS, backends=Backends())
        assert not (receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE)
