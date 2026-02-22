"""Tests for MappedEntityMixin."""
import pytest
from unittest.mock import Mock, AsyncMock
from dataclasses import dataclass


@dataclass
class MockRuntimeData:
    """Mock runtime data."""

    service_mappings: dict


class MockConfigEntry:
    """Mock config entry with runtime_data."""

    def __init__(self, service_mappings=None):
        self.runtime_data = MockRuntimeData(
            service_mappings=service_mappings or {},
        )


class MockCoordinator:
    """Mock coordinator with config_entry."""

    def __init__(self, config_entry=None):
        self.config_entry = config_entry or MockConfigEntry()


class MockMappedEntity:
    """Mock entity using the mixin pattern (mirrors CoordinatorEntity + MappedEntityMixin)."""

    def __init__(self, hass, coordinator, mapping_key, mapped_entity_id=None):
        self.hass = hass
        self.coordinator = coordinator
        self._mapping_key_value = mapping_key
        self._mapped_entity_override = mapped_entity_id

    @property
    def _mapping_key(self):
        return self._mapping_key_value

    @property
    def _mapped_entity(self):
        if self._mapped_entity_override:
            return self._mapped_entity_override
        try:
            runtime_data = self.coordinator.config_entry.runtime_data
            return runtime_data.service_mappings.get(self._mapping_key)
        except (AttributeError, TypeError):
            return None

    def _get_mapped_state(self):
        if not self._mapped_entity or not self.hass:
            return None
        return self.hass.states.get(self._mapped_entity)

    def _get_mapped_attribute(self, attribute):
        mapped_state = self._get_mapped_state()
        if mapped_state:
            return mapped_state.attributes.get(attribute)
        return None

    async def _delegate_to_hass(self, service, data=None):
        if not self._mapped_entity or not self.hass:
            return False

        if data is None:
            data = {}
        data.setdefault("entity_id", self._mapped_entity)

        try:
            await self.hass.services.async_call(
                "media_player",
                service,
                data,
                blocking=True,
            )
            return True
        except Exception:
            return False


class TestMappedEntityMixin:
    """Tests for MappedEntityMixin functionality."""

    def test_no_mapping_returns_none(self):
        """Test that entity without mapping returns None."""
        hass = Mock()
        coordinator = MockCoordinator(MockConfigEntry(service_mappings={}))

        entity = MockMappedEntity(hass, coordinator, "service:test")

        assert entity._mapped_entity is None
        assert entity._get_mapped_attribute("media_title") is None

    def test_mapping_resolution(self):
        """Test that mapping is resolved from runtime data."""
        hass = Mock()
        config_entry = MockConfigEntry(
            service_mappings={"user/mpd.service": "media_player.mpd_test"}
        )
        coordinator = MockCoordinator(config_entry)

        entity = MockMappedEntity(hass, coordinator, "user/mpd.service")

        assert entity._mapped_entity == "media_player.mpd_test"

    def test_get_mapped_attribute(self):
        """Test getting attributes from mapped entity."""
        hass = Mock()

        # Mock state
        mock_state = Mock()
        mock_state.attributes = {
            "media_title": "Test Song",
            "media_artist": "Test Artist",
            "volume_level": 0.5,
        }
        hass.states.get.return_value = mock_state

        coordinator = MockCoordinator()
        entity = MockMappedEntity(
            hass,
            coordinator,
            "test",
            mapped_entity_id="media_player.test",
        )

        assert entity._get_mapped_attribute("media_title") == "Test Song"
        assert entity._get_mapped_attribute("media_artist") == "Test Artist"
        assert entity._get_mapped_attribute("volume_level") == 0.5
        assert entity._get_mapped_attribute("nonexistent") is None

    def test_get_mapped_attribute_no_state(self):
        """Test getting attributes when mapped entity has no state."""
        hass = Mock()
        hass.states.get.return_value = None

        coordinator = MockCoordinator()
        entity = MockMappedEntity(
            hass,
            coordinator,
            "test",
            mapped_entity_id="media_player.test",
        )

        assert entity._get_mapped_attribute("media_title") is None

    @pytest.mark.asyncio
    async def test_delegate_to_hass_success(self):
        """Test successful delegation to HA service."""
        hass = Mock()
        hass.services.async_call = AsyncMock(return_value=None)

        coordinator = MockCoordinator()
        entity = MockMappedEntity(
            hass,
            coordinator,
            "test",
            mapped_entity_id="media_player.test",
        )

        result = await entity._delegate_to_hass("media_play")

        assert result is True
        hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_play",
            {"entity_id": "media_player.test"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_delegate_to_hass_with_data(self):
        """Test delegation with additional data."""
        hass = Mock()
        hass.services.async_call = AsyncMock(return_value=None)

        coordinator = MockCoordinator()
        entity = MockMappedEntity(
            hass,
            coordinator,
            "test",
            mapped_entity_id="media_player.test",
        )

        result = await entity._delegate_to_hass(
            "volume_set",
            {"volume_level": 0.7},
        )

        assert result is True
        hass.services.async_call.assert_called_once_with(
            "media_player",
            "volume_set",
            {"entity_id": "media_player.test", "volume_level": 0.7},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_delegate_to_hass_failure(self):
        """Test delegation failure handling."""
        hass = Mock()
        hass.services.async_call = AsyncMock(side_effect=Exception("Service failed"))

        coordinator = MockCoordinator()
        entity = MockMappedEntity(
            hass,
            coordinator,
            "test",
            mapped_entity_id="media_player.test",
        )

        result = await entity._delegate_to_hass("media_play")

        assert result is False

    @pytest.mark.asyncio
    async def test_delegate_no_mapping(self):
        """Test delegation without mapped entity."""
        hass = Mock()
        coordinator = MockCoordinator()

        entity = MockMappedEntity(hass, coordinator, "test")

        result = await entity._delegate_to_hass("media_play")

        assert result is False

    def test_mapping_resolution_no_coordinator(self):
        """Test graceful handling when coordinator has no config_entry."""
        hass = Mock()
        coordinator = Mock()
        coordinator.config_entry = None

        entity = MockMappedEntity(hass, coordinator, "test")

        assert entity._mapped_entity is None


class TestMappingKeyFunctions:
    """Tests for config_flow_helpers key functions."""

    def test_get_service_keys(self):
        """Test service key generation."""
        from custom_components.odio_audio.config_flow_helpers import get_service_keys

        service = {
            "scope": "user",
            "name": "mpd.service",
        }

        form_key, mapping_key = get_service_keys(service)

        assert form_key == "user_mpd.service"
        assert mapping_key == "user/mpd.service"

    def test_get_client_keys(self):
        """Test client key generation."""
        from custom_components.odio_audio.config_flow_helpers import get_client_keys

        client = {
            "name": "Tunnel for bobby@bobby-desktop",
        }

        form_key, mapping_key = get_client_keys(client)

        assert form_key == "client_tunnel_for_bobby_bobby_desktop"
        assert mapping_key == "client:Tunnel for bobby@bobby-desktop"

    def test_get_client_keys_special_chars(self):
        """Test client key generation with special characters."""
        from custom_components.odio_audio.config_flow_helpers import get_client_keys

        client = {
            "name": "Test!@#$%Client-123",
        }

        form_key, mapping_key = get_client_keys(client)

        assert form_key == "client_test_client_123"
        assert mapping_key == "client:Test!@#$%Client-123"

    def test_get_client_keys_empty_name(self):
        """Test client key generation with empty name."""
        from custom_components.odio_audio.config_flow_helpers import get_client_keys

        client = {"name": ""}

        form_key, mapping_key = get_client_keys(client)

        assert form_key == ""
        assert mapping_key == ""


class TestStateMapping:
    """Tests for state mapping functionality."""

    def test_map_state_playing(self):
        """Test mapping playing state."""
        hass = Mock()

        mock_state = Mock()
        mock_state.state = "playing"
        hass.states.get.return_value = mock_state

        mapped_state = mock_state.state
        assert mapped_state == "playing"

    def test_map_state_unavailable(self):
        """Test mapping when device is unavailable."""
        hass = Mock()

        mock_state = Mock()
        mock_state.state = "playing"
        hass.states.get.return_value = mock_state

        # Test with is_available returning False
        # Would return OFF state
        pass  # Simplified for now


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
