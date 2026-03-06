"""Tests for OdioReceiverMediaPlayer source (audio output) features."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import MediaPlayerEntityFeature

from custom_components.odio_remote.media_player import OdioReceiverMediaPlayer

from .conftest import MOCK_CLIENTS, MOCK_DEVICE_INFO, MOCK_OUTPUTS

ENTRY_ID = "test_entry_id"


def _make_audio_coordinator(data=None):
    coord = MagicMock()
    coord.data = data
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    coord.async_request_refresh = AsyncMock()
    coord.last_update_success = True
    return coord


def _make_ctx(audio_coordinator=None, backends=None):
    ctx = MagicMock()
    ctx.entry_id = ENTRY_ID
    ctx.device_info = MOCK_DEVICE_INFO
    ctx.audio_coordinator = audio_coordinator
    ctx.service_coordinator = None
    ctx.backends = backends or {}
    return ctx


def _make_receiver(audio_data=None, backends=None):
    if backends is None:
        backends = {"pulseaudio": True}
    coord = _make_audio_coordinator(audio_data) if audio_data is not None else None
    ctx = _make_ctx(audio_coordinator=coord, backends=backends)
    return OdioReceiverMediaPlayer(ctx)


# ---------------------------------------------------------------------------
# source_list
# ---------------------------------------------------------------------------

class TestReceiverSourceList:

    def test_returns_output_descriptions(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        receiver = _make_receiver(data)
        sources = receiver.source_list
        assert len(sources) == 5
        assert "Built-in Audio Analog Stereo" in sources
        assert "SnapAir" in sources
        assert "Audio interne Stéréo on pi@rasponkyold" in sources

    def test_returns_none_when_no_outputs(self):
        data = {"audio": MOCK_CLIENTS, "outputs": []}
        assert _make_receiver(data).source_list is None

    def test_returns_none_when_no_audio_coordinator(self):
        ctx = _make_ctx(audio_coordinator=None, backends={"pulseaudio": True})
        receiver = OdioReceiverMediaPlayer(ctx)
        assert receiver.source_list is None


# ---------------------------------------------------------------------------
# source (current)
# ---------------------------------------------------------------------------

class TestReceiverSource:

    def test_returns_default_output(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        assert _make_receiver(data).source == "Audio interne Stéréo on pi@rasponkyold"

    def test_returns_none_when_no_default(self):
        outputs = [{"id": 1, "name": "sink", "description": "Sink", "default": False}]
        data = {"audio": [], "outputs": outputs}
        assert _make_receiver(data).source is None

    def test_returns_none_when_no_coordinator(self):
        ctx = _make_ctx(audio_coordinator=None, backends={"pulseaudio": True})
        receiver = OdioReceiverMediaPlayer(ctx)
        assert receiver.source is None


# ---------------------------------------------------------------------------
# async_select_source
# ---------------------------------------------------------------------------

class TestReceiverSelectSource:

    @pytest.mark.asyncio
    async def test_calls_api_with_output_name(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        receiver = _make_receiver(data)
        receiver._api_client = MagicMock()
        receiver._api_client.set_output_default = AsyncMock()

        await receiver.async_select_source("SnapAir")

        receiver._api_client.set_output_default.assert_awaited_once_with(
            "raop_sink.nas-2.local.2a01:cb0c:796:200:3285:a9ff:fe40:f90f.5000"
        )

    @pytest.mark.asyncio
    async def test_unknown_source_does_nothing(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        receiver = _make_receiver(data)
        receiver._api_client = MagicMock()
        receiver._api_client.set_output_default = AsyncMock()

        await receiver.async_select_source("Nonexistent")

        receiver._api_client.set_output_default.assert_not_awaited()


# ---------------------------------------------------------------------------
# supported_features includes SELECT_SOURCE
# ---------------------------------------------------------------------------

class TestReceiverSupportedFeatures:

    def test_includes_select_source_with_pulseaudio(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        receiver = _make_receiver(data)
        assert receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE

    def test_includes_select_source_even_without_outputs(self):
        data = {"audio": MOCK_CLIENTS, "outputs": []}
        receiver = _make_receiver(data)
        assert receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE

    def test_no_select_source_when_no_pulseaudio(self):
        data = {"audio": MOCK_CLIENTS, "outputs": MOCK_OUTPUTS}
        receiver = _make_receiver(data, backends={})
        assert not (receiver.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE)
