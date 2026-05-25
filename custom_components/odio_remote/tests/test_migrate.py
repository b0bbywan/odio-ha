"""Tests for async_migrate_entry — MPRIS unique_id and service_mappings v1 → v2."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch


def _make_hass():
    """Create a mock hass with event loop."""
    hass = MagicMock()
    try:
        hass.loop = asyncio.get_running_loop()
    except RuntimeError:
        hass.loop = MagicMock()
    return hass


def _make_registry_entry(entity_id: str, unique_id: str):
    """Build a minimal stand-in for er.RegistryEntry."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.unique_id = unique_id
    return entry


# =============================================================================
# async_migrate_entry — MPRIS unique_id v1 → v2
# =============================================================================


class TestMigrateMprisUniqueIds:

    async def _run_migration(self, registry_entries):
        """Invoke async_migrate_entry with a mocked registry holding the given entries.

        Returns the result, registry mock, hass mock, and entry mock so the
        test can assert removes/updates and version bumps.
        """
        from custom_components.odio_remote import async_migrate_entry

        hass = _make_hass()
        entry = MagicMock()
        entry.entry_id = "abc123"
        entry.version = 1
        hass.config_entries.async_update_entry = MagicMock()

        registry = MagicMock()
        registry.async_remove = MagicMock()
        registry.async_update_entity = MagicMock()

        with patch(
            "custom_components.odio_remote.migrate.er.async_get", return_value=registry
        ), patch(
            "custom_components.odio_remote.migrate.er.async_entries_for_config_entry",
            return_value=registry_entries,
        ):
            result = await async_migrate_entry(hass, entry)

        return result, registry, hass, entry

    @pytest.mark.asyncio
    async def test_collapses_duplicates_keeping_canonical_entity_id(self):
        """Five chrome entries → keep the one without _N suffix, delete the rest, rename uid."""
        prefix = "abc123_mpris_"
        bus = "org_mpris_mediaplayer2_chrome"
        entries = [
            _make_registry_entry("media_player.odio_chrome", f"{prefix}{bus}_instance10"),
            _make_registry_entry("media_player.odio_chrome_2", f"{prefix}{bus}_instance20"),
            _make_registry_entry("media_player.odio_chrome_3", f"{prefix}{bus}_instance30"),
            _make_registry_entry("media_player.odio_chrome_4", f"{prefix}{bus}_instance40"),
            _make_registry_entry("media_player.odio_chrome_5", f"{prefix}{bus}_instance50"),
        ]

        result, registry, hass, entry = await self._run_migration(entries)

        assert result is True
        # The canonical entity_id (no numeric suffix) is kept and renamed.
        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_chrome", new_unique_id="abc123_mpris_chrome"
        )
        # The four orphans are removed.
        removed = {c.args[0] for c in registry.async_remove.call_args_list}
        assert removed == {
            "media_player.odio_chrome_2",
            "media_player.odio_chrome_3",
            "media_player.odio_chrome_4",
            "media_player.odio_chrome_5",
        }
        hass.config_entries.async_update_entry.assert_called_once_with(entry, version=2)

    @pytest.mark.asyncio
    async def test_handles_app_name_with_underscores(self):
        """firefox-esr (bus_name → firefox_esr_instance_X_Y) must regroup as firefox_esr."""
        prefix = "abc123_mpris_"
        bus = "org_mpris_mediaplayer2_firefox_esr"
        entries = [
            _make_registry_entry(
                "media_player.odio_firefox_esr", f"{prefix}{bus}_instance_1_52"
            ),
            _make_registry_entry(
                "media_player.odio_firefox_esr_2", f"{prefix}{bus}_instance_1_99"
            ),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_firefox_esr",
            new_unique_id="abc123_mpris_firefox_esr",
        )
        registry.async_remove.assert_called_once_with("media_player.odio_firefox_esr_2")

    @pytest.mark.asyncio
    async def test_no_instance_suffix_just_renames(self):
        """mpd has no .instanceXXX suffix; uid still gets shortened to the new format."""
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry(
                "media_player.odio_mpd", f"{prefix}org_mpris_mediaplayer2_mpd"
            ),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_mpd", new_unique_id="abc123_mpris_mpd"
        )
        registry.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_new_format_is_skipped(self):
        """Entries lacking the old bus prefix are ignored (already migrated)."""
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry("media_player.odio_chrome", f"{prefix}chrome"),
        ]

        _, registry, hass, entry = await self._run_migration(entries)

        registry.async_update_entity.assert_not_called()
        registry.async_remove.assert_not_called()
        # Version still bumped even when no entities needed migration.
        hass.config_entries.async_update_entry.assert_called_once_with(entry, version=2)

    @pytest.mark.asyncio
    async def test_non_mpris_entries_ignored(self):
        """Non-MPRIS unique_ids in the same config entry are left alone."""
        entries = [
            _make_registry_entry("switch.odio_receiver", "abc123_switch_receiver"),
            _make_registry_entry("media_player.odio_receiver", "abc123_receiver"),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        registry.async_update_entity.assert_not_called()
        registry.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_first_when_no_canonical_exists(self):
        """If only `_2`/`_3` survived (canonical was deleted manually), keep the first."""
        prefix = "abc123_mpris_"
        bus = "org_mpris_mediaplayer2_spotify"
        entries = [
            _make_registry_entry("media_player.odio_spotify_3", f"{prefix}{bus}_instance30"),
            _make_registry_entry("media_player.odio_spotify_2", f"{prefix}{bus}_instance20"),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        # _2 sorts before _3 alphabetically; both lack canonical, so _2 wins.
        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_spotify_2", new_unique_id="abc123_mpris_spotify"
        )
        registry.async_remove.assert_called_once_with("media_player.odio_spotify_3")

    @pytest.mark.asyncio
    async def test_fallback_sorts_numerically_not_lexically(self):
        """Without a canonical, `_2` must beat `_10` (numeric, not lex order)."""
        prefix = "abc123_mpris_"
        bus = "org_mpris_mediaplayer2_chrome"
        # 10 entries `_2` through `_11`, no canonical present.
        entries = [
            _make_registry_entry(
                f"media_player.odio_chrome_{n}",
                f"{prefix}{bus}_instance{n}0",
            )
            for n in range(2, 12)
        ]

        _, registry, _, _ = await self._run_migration(entries)

        # `_2` should be the keeper — lex sort would have picked `_10`.
        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_chrome_2", new_unique_id="abc123_mpris_chrome"
        )
        removed = {c.args[0] for c in registry.async_remove.call_args_list}
        assert "media_player.odio_chrome_2" not in removed
        assert len(removed) == 9

    @pytest.mark.asyncio
    async def test_app_name_with_trailing_digits_keeps_canonical(self):
        """For an app literally named `vlc_3`, the canonical entity_id (no HA suffix)
        must be detected even though it ends in `_<digits>` — the false-positive
        the old `_\\d+$` heuristic would trigger."""
        prefix = "abc123_mpris_"
        bus = "org_mpris_mediaplayer2_vlc_3"
        entries = [
            _make_registry_entry("media_player.odio_vlc_3", f"{prefix}{bus}_instance10"),
            _make_registry_entry("media_player.odio_vlc_3_2", f"{prefix}{bus}_instance20"),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        # vlc_3 (canonical) wins despite the trailing `_3` looking like a HA suffix.
        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_vlc_3", new_unique_id="abc123_mpris_vlc_3"
        )
        registry.async_remove.assert_called_once_with("media_player.odio_vlc_3_2")

    @pytest.mark.asyncio
    async def test_future_version_refused(self):
        """A config entry from a future schema version must not be downgraded."""
        from custom_components.odio_remote import async_migrate_entry

        hass = _make_hass()
        entry = MagicMock()
        entry.version = 99

        result = await async_migrate_entry(hass, entry)

        assert result is False

    @pytest.mark.asyncio
    async def test_existing_new_format_entry_wins_no_rename(self):
        """A pre-existing new-format entry is kept; old-format orphans are removed and no rename runs.

        This covers the partial-migration / beta-install scenario where calling
        async_update_entity on the keeper would otherwise collide.
        """
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry("media_player.odio_chrome", f"{prefix}chrome"),
            _make_registry_entry(
                "media_player.odio_chrome_2",
                f"{prefix}org_mpris_mediaplayer2_chrome_instance20",
            ),
            _make_registry_entry(
                "media_player.odio_chrome_3",
                f"{prefix}org_mpris_mediaplayer2_chrome_instance30",
            ),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        # The already-migrated entity is the keeper → no rename call.
        registry.async_update_entity.assert_not_called()
        removed = {c.args[0] for c in registry.async_remove.call_args_list}
        assert removed == {
            "media_player.odio_chrome_2",
            "media_player.odio_chrome_3",
        }

    @pytest.mark.asyncio
    async def test_app_name_ending_in_instance_is_not_over_stripped(self):
        """An app literally named `foo_instance` must NOT have `_instance` stripped.

        The live `extract_mpris_app_name` splits on `.` and returns `foo_instance`
        for bus_name `org.mpris.MediaPlayer2.foo_instance.instance10`, so the
        migration must produce the same key to avoid re-leaking an orphan.
        """
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry(
                "media_player.odio_foo_instance",
                f"{prefix}org_mpris_mediaplayer2_foo_instance_instance10",
            ),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_foo_instance",
            new_unique_id="abc123_mpris_foo_instance",
        )

    @pytest.mark.asyncio
    async def test_app_name_containing_instance_word_preserved(self):
        """An app name like `foo_instance_player` (no real instance suffix) is preserved."""
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry(
                "media_player.odio_foo",
                f"{prefix}org_mpris_mediaplayer2_foo_instance_player",
            ),
        ]

        _, registry, _, _ = await self._run_migration(entries)

        registry.async_update_entity.assert_called_once_with(
            "media_player.odio_foo",
            new_unique_id="abc123_mpris_foo_instance_player",
        )

    @pytest.mark.asyncio
    async def test_rename_collision_falls_back_to_remove(self):
        """If async_update_entity raises ValueError (uid taken by an entity outside
        the group), the keeper is removed instead of crashing async_migrate_entry."""
        prefix = "abc123_mpris_"
        entries = [
            _make_registry_entry(
                "media_player.odio_chrome",
                f"{prefix}org_mpris_mediaplayer2_chrome_instance10",
            ),
        ]

        from custom_components.odio_remote import async_migrate_entry

        hass = _make_hass()
        entry = MagicMock()
        entry.entry_id = "abc123"
        entry.version = 1
        hass.config_entries.async_update_entry = MagicMock()

        registry = MagicMock()
        registry.async_update_entity = MagicMock(side_effect=ValueError("uid taken"))
        registry.async_remove = MagicMock()

        with patch(
            "custom_components.odio_remote.migrate.er.async_get", return_value=registry
        ), patch(
            "custom_components.odio_remote.migrate.er.async_entries_for_config_entry",
            return_value=entries,
        ):
            result = await async_migrate_entry(hass, entry)

        assert result is True  # migration still completes
        registry.async_remove.assert_called_once_with("media_player.odio_chrome")
        # Version bump still applied.
        hass.config_entries.async_update_entry.assert_called_with(entry, version=2)


# =============================================================================
# async_migrate_entry — MPRIS service_mappings v1 → v2
# =============================================================================


class TestMigrateMprisServiceMappings:

    async def _run_migration(self, options):
        """Invoke async_migrate_entry with mocked registry (empty) and given options.

        Returns (update_calls, hass, entry) so the test can assert option updates.
        """
        from custom_components.odio_remote import async_migrate_entry

        hass = _make_hass()
        entry = MagicMock()
        entry.entry_id = "abc123"
        entry.version = 1
        entry.options = options

        update_calls: list[dict] = []

        def fake_update(e, **kwargs):
            update_calls.append(kwargs)
            # Persist the new options on the mock so a subsequent call sees them.
            if "options" in kwargs:
                e.options = kwargs["options"]

        hass.config_entries.async_update_entry = MagicMock(side_effect=fake_update)
        registry = MagicMock()

        with patch(
            "custom_components.odio_remote.migrate.er.async_get", return_value=registry
        ), patch(
            "custom_components.odio_remote.migrate.er.async_entries_for_config_entry",
            return_value=[],
        ):
            await async_migrate_entry(hass, entry)

        return update_calls, hass, entry

    @pytest.mark.asyncio
    async def test_rewrites_mpris_keys_to_app_names(self):
        """mpris:<bus_name> entries become mpris:<app_name>; non-MPRIS keys untouched."""
        from custom_components.odio_remote.const import CONF_SERVICE_MAPPINGS

        options = {
            CONF_SERVICE_MAPPINGS: {
                "mpris:org.mpris.MediaPlayer2.firefox.instance_1_52": "media_player.living_room",
                "mpris:org.mpris.MediaPlayer2.spotify": "media_player.kitchen",
                "user/mpd.service": "media_player.bedroom",
                "client:laptop": "media_player.office",
            }
        }

        update_calls, _, _ = await self._run_migration(options)

        options_updates = [c for c in update_calls if "options" in c]
        assert len(options_updates) == 1
        new = options_updates[0]["options"][CONF_SERVICE_MAPPINGS]
        assert new["mpris:firefox"] == "media_player.living_room"
        assert new["mpris:spotify"] == "media_player.kitchen"
        assert new["user/mpd.service"] == "media_player.bedroom"
        assert new["client:laptop"] == "media_player.office"
        # Old volatile keys must be gone.
        assert "mpris:org.mpris.MediaPlayer2.firefox.instance_1_52" not in new

    @pytest.mark.asyncio
    async def test_no_change_when_already_app_keyed(self):
        """If keys are already in the new format, options aren't rewritten."""
        from custom_components.odio_remote.const import CONF_SERVICE_MAPPINGS

        options = {
            CONF_SERVICE_MAPPINGS: {"mpris:firefox": "media_player.living_room"},
        }

        update_calls, _, _ = await self._run_migration(options)

        # Only the version bump should touch the entry — no options update.
        assert all("options" not in c for c in update_calls)

    @pytest.mark.asyncio
    async def test_empty_mappings_no_crash(self):
        """No mappings configured → migration is a no-op for the mapping side."""
        update_calls, _, _ = await self._run_migration({})
        assert all("options" not in c for c in update_calls)

    @pytest.mark.asyncio
    async def test_collisions_resolve_to_last_write(self):
        """Two firefox bus_names collapse to one mpris:firefox key (last value wins)."""
        from custom_components.odio_remote.const import CONF_SERVICE_MAPPINGS

        options = {
            CONF_SERVICE_MAPPINGS: {
                "mpris:org.mpris.MediaPlayer2.firefox.instance_1_52": "media_player.a",
                "mpris:org.mpris.MediaPlayer2.firefox.instance_1_99": "media_player.b",
            }
        }

        update_calls, _, _ = await self._run_migration(options)

        new = next(c for c in update_calls if "options" in c)["options"][CONF_SERVICE_MAPPINGS]
        # Iteration order is insertion order in 3.7+; the second wins.
        assert new == {"mpris:firefox": "media_player.b"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
