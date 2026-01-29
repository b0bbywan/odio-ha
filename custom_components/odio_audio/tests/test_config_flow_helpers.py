"""Tests for config_flow_helpers."""
import pytest
from custom_components.odio_audio.config_flow_helpers import (
    build_mapping_schema,
    parse_mappings_from_input,
    get_service_keys,
    get_client_keys,
)


class TestBuildMappingSchema:
    """Tests for build_mapping_schema."""

    def test_empty_entities(self):
        """Test with no entities."""
        schema = build_mapping_schema([], {}, get_service_keys)
        assert len(schema.schema) == 0

    def test_single_entity_no_mapping(self):
        """Test single entity without existing mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]

        schema = build_mapping_schema(services, {}, get_service_keys)

        # Should have 1 field (entity selector)
        assert len(schema.schema) == 1

        # Key should be Optional
        keys = list(schema.schema.keys())
        assert str(keys[0].schema) == "user_mpd.service"

    def test_single_entity_with_mapping(self):
        """Test single entity with existing mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        mappings = {
            "user/mpd.service": "media_player.mpd_test"
        }

        schema = build_mapping_schema(services, mappings, get_service_keys)

        # Should have 2 fields (entity selector + delete checkbox)
        assert len(schema.schema) == 2

    def test_multiple_entities_mixed(self):
        """Test multiple entities with mixed mappings."""
        services = [
            {"scope": "user", "name": "mpd.service"},
            {"scope": "user", "name": "snapclient.service"},
            {"scope": "system", "name": "upmpdcli.service"},
        ]
        mappings = {
            "user/mpd.service": "media_player.mpd_test",
            # snapclient not mapped
            "system/upmpdcli.service": "media_player.upnp_test",
        }

        schema = build_mapping_schema(services, mappings, get_service_keys)

        # mpd: 2 fields (selector + delete)
        # snapclient: 1 field (selector only)
        # upmpdcli: 2 fields (selector + delete)
        # Total: 5 fields
        assert len(schema.schema) == 5


class TestParseMappingsFromInput:
    """Tests for parse_mappings_from_input."""

    def test_empty_input(self):
        """Test with no user input."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]

        result = parse_mappings_from_input({}, services, {}, get_service_keys, False)

        assert result == {}

    def test_add_new_mapping(self):
        """Test adding a new mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        user_input = {
            "user_mpd.service": "media_player.mpd_test"
        }

        result = parse_mappings_from_input(
            user_input, services, {}, get_service_keys, False
        )

        assert result == {"user/mpd.service": "media_player.mpd_test"}

    def test_update_existing_mapping(self):
        """Test updating an existing mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.old_mpd"
        }
        user_input = {
            "user_mpd.service": "media_player.new_mpd"
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, False
        )

        assert result == {"user/mpd.service": "media_player.new_mpd"}

    def test_delete_mapping(self):
        """Test deleting a mapping via checkbox."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_test"
        }
        user_input = {
            "user_mpd.service": "media_player.mpd_test",
            "user_mpd.service_delete": True,  # Delete checkbox checked
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, False
        )

        # Mapping should be removed
        assert result == {}

    def test_preserve_others(self):
        """Test preserving mappings not in current entity list."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_test",
            "client:Remote Client": "media_player.remote_test",  # Different type
        }
        user_input = {
            "user_mpd.service": "media_player.mpd_updated"
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, preserve_others=True
        )

        # Should update MPD and preserve client mapping
        assert result == {
            "user/mpd.service": "media_player.mpd_updated",
            "client:Remote Client": "media_player.remote_test",
        }

    def test_no_preserve_others(self):
        """Test not preserving other mappings."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_test",
            "client:Remote Client": "media_player.remote_test",
        }
        user_input = {
            "user_mpd.service": "media_player.mpd_updated"
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, preserve_others=False
        )

        # Should only have MPD mapping
        assert result == {
            "user/mpd.service": "media_player.mpd_updated",
        }

    def test_empty_entity_value_removes_mapping(self):
        """Test that empty entity value removes the mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_test"
        }
        user_input = {
            "user_mpd.service": "",  # Empty value
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, False
        )

        # Empty value should not create mapping
        assert result == {}

    def test_none_entity_value_removes_mapping(self):
        """Test that None entity value removes the mapping."""
        services = [
            {"scope": "user", "name": "mpd.service"}
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_test"
        }
        user_input = {
            "user_mpd.service": None,  # None value
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, False
        )

        # None value should not create mapping
        assert result == {}

    def test_multiple_services_complex_scenario(self):
        """Test complex scenario with multiple services."""
        services = [
            {"scope": "user", "name": "mpd.service"},
            {"scope": "user", "name": "snapclient.service"},
            {"scope": "system", "name": "upmpdcli.service"},
        ]
        existing = {
            "user/mpd.service": "media_player.mpd_old",
            "user/snapclient.service": "media_player.snapcast_old",
            "client:Remote": "media_player.remote",  # Not in services list
        }
        user_input = {
            "user_mpd.service": "media_player.mpd_new",  # Update
            "user_snapclient.service": "media_player.snapcast_old",  # Keep
            "user_snapclient.service_delete": True,  # But delete!
            "system_upmpdcli.service": "media_player.upnp_new",  # Add new
        }

        result = parse_mappings_from_input(
            user_input, services, existing, get_service_keys, preserve_others=True
        )

        assert result == {
            "user/mpd.service": "media_player.mpd_new",
            # snapclient deleted
            "system/upmpdcli.service": "media_player.upnp_new",
            "client:Remote": "media_player.remote",  # Preserved
        }


class TestClientKeys:
    """Tests for client key generation with edge cases."""

    def test_client_with_spaces(self):
        """Test client name with spaces."""
        client = {"name": "My Audio Client"}
        form_key, mapping_key = get_client_keys(client)

        assert form_key == "client_my_audio_client"
        assert mapping_key == "client:My Audio Client"

    def test_client_with_unicode(self):
        """Test client name with unicode characters."""
        client = {"name": "Client-Été-2024"}
        form_key, mapping_key = get_client_keys(client)

        assert "client_" in form_key
        assert mapping_key == "client:Client-Été-2024"

    def test_client_with_consecutive_special_chars(self):
        """Test client name with consecutive special characters."""
        client = {"name": "Test!!!Client"}
        form_key, mapping_key = get_client_keys(client)

        # Consecutive special chars should be replaced with single underscore
        assert form_key == "client_test_client"
        assert mapping_key == "client:Test!!!Client"

    def test_client_leading_trailing_special(self):
        """Test client name with leading/trailing special characters."""
        client = {"name": "___Test___"}
        form_key, mapping_key = get_client_keys(client)

        # Leading/trailing underscores should be stripped
        assert form_key == "client_test"
        assert mapping_key == "client:___Test___"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
