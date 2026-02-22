"""Helpers for config flow schema building and parsing."""
import re
from typing import Any, Callable

import voluptuous as vol
from homeassistant.helpers import selector


def build_mapping_schema(
    entities: list[dict[str, Any]],
    current_mappings: dict[str, str] | None,
    get_key_func: Callable[[dict[str, Any]], tuple[str, str]],
) -> vol.Schema:
    """Build a generic mapping schema for services or clients.

    Args:
        entities: List of entities to map (services or clients)
        current_mappings: Current mapping dict
        get_key_func: Function that returns (form_key, mapping_key) tuple for an entity

    Returns:
        Schema with entity selectors and optional delete checkboxes
    """
    current_mappings = current_mappings or {}
    schema: dict[Any, Any] = {}

    for entity in entities:
        form_key, mapping_key = get_key_func(entity)
        current_value = current_mappings.get(mapping_key)

        # Entity selector (with suggested value if exists)
        if current_value:
            schema[
                vol.Optional(form_key, description={"suggested_value": current_value})
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    multiple=False,
                )
            )
            # Add delete checkbox for existing mappings
            schema[vol.Optional(f"{form_key}_delete", default=False)] = (
                selector.BooleanSelector()
            )
        else:
            schema[vol.Optional(form_key)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    multiple=False,
                )
            )

    return vol.Schema(schema)


def parse_mappings_from_input(
    user_input: dict[str, Any],
    entities: list[dict[str, Any]],
    existing_mappings: dict[str, str] | None,
    get_key_func: Callable[[dict[str, Any]], tuple[str, str]],
    preserve_others: bool = True,
) -> dict[str, str]:
    """Parse mappings from user input generically.

    Args:
        user_input: Form input data
        entities: List of entities being mapped
        existing_mappings: Current mappings
        get_key_func: Function that returns (form_key, mapping_key) tuple
        preserve_others: If True, preserve mappings not in entities list

    Returns:
        Updated mappings dict
    """
    mappings: dict[str, str] = {}

    # Build set of mapping keys we're currently managing
    managed_keys: set[str] = set()
    for entity in entities:
        _, mapping_key = get_key_func(entity)
        managed_keys.add(mapping_key)

    # Preserve existing mappings that we're NOT managing
    if preserve_others and existing_mappings:
        for key, value in existing_mappings.items():
            if key not in managed_keys:
                mappings[key] = value

    # Process entities from user_input
    for entity in entities:
        form_key, mapping_key = get_key_func(entity)
        delete_key = f"{form_key}_delete"

        # Check if user wants to delete this mapping
        if user_input.get(delete_key, False):
            continue

        # Add mapping if entity is selected
        entity_value = user_input.get(form_key)
        if entity_value:
            mappings[mapping_key] = entity_value

    return mappings


# Key functions for services and clients
def get_service_keys(service: dict[str, Any]) -> tuple[str, str]:
    """Get form_key and mapping_key for a service.

    Returns:
        (form_key, mapping_key) tuple
    """
    form_key = f"{service['scope']}_{service['name']}"
    mapping_key = f"{service['scope']}/{service['name']}"
    return form_key, mapping_key


def get_client_keys(client: dict[str, Any]) -> tuple[str, str]:
    """Get form_key and mapping_key for a client.

    Returns:
        (form_key, mapping_key) tuple
    """
    client_name = client.get("name", "")
    if not client_name:
        return "", ""

    safe_name = re.sub(r"[^a-z0-9_]+", "_", client_name.lower()).strip("_")
    form_key = f"client_{safe_name}"
    mapping_key = f"client:{client_name}"
    return form_key, mapping_key
