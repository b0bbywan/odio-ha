"""Config-entry migrations for Odio Remote.

Kept out of `__init__.py` so the setup/runtime path stays focused on
hot-path work; HA only calls into this module via `async_migrate_entry`
at upgrade time.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_SERVICE_MAPPINGS
from .helpers import extract_mpris_app_name

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v1 → v2: stabilize MPRIS unique_ids and service_mapping keys
# ---------------------------------------------------------------------------

_MPRIS_OLD_BUS_SAFE_PREFIX = "org_mpris_mediaplayer2_"
# Match `_instance` followed by at least one digit/underscore (the real D-Bus
# instance-suffix shapes: `instance123`, `instance_1_52`). Requiring [\d_]+
# avoids over-stripping legitimate app names that happen to contain or end
# with `_instance` (e.g. an app literally named `foo_instance`).
_MPRIS_INSTANCE_RE = re.compile(r"^(.+?)(?:_instance[\d_]+)?$")
_HA_SUFFIX_RE = re.compile(r"_(\d+)$")


def _pick_keeper(
    ents: list[er.RegistryEntry], new_uid: str
) -> er.RegistryEntry:
    """Pick which entry of a same-app group survives the migration.

    Priority:
      1. An entry already on the target uid — no rename runs, so no collision.
      2. The canonical entity_id of the group: the one that is a strict prefix
         (followed by `_<digits>`) of every other entry. Survives apps whose
         name itself ends in `_<digits>` (e.g. `vlc_3`).
      3. Fall back to the orphan with the lowest HA-added numeric suffix —
         sorted as integers so `_2` beats `_10`.
    """
    already_migrated = next((e for e in ents if e.unique_id == new_uid), None)
    if already_migrated is not None:
        return already_migrated

    def _is_canonical(candidate: er.RegistryEntry) -> bool:
        base = candidate.entity_id
        for other in ents:
            if other is candidate:
                continue
            if not re.fullmatch(rf"{re.escape(base)}_\d+", other.entity_id):
                return False
        return True

    canonical = next((e for e in ents if _is_canonical(e)), None)
    if canonical is not None:
        return canonical

    def _trailing_int(e: er.RegistryEntry) -> int:
        m = _HA_SUFFIX_RE.search(e.entity_id)
        return int(m.group(1)) if m else 0

    return min(ents, key=lambda e: (_trailing_int(e), e.entity_id))


def migrate_mpris_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Collapse per-instance MPRIS entries into one stable entry per app.

    Old unique_id encoded the full D-Bus bus_name (including the volatile
    `.instanceXXX` suffix), so every Firefox/Chrome restart leaked a new
    orphan entity. New format is `<entry_id>_mpris_<safe_app_name>`.

    Pre-existing new-format entries (e.g. from a beta or a partially-applied
    earlier migration pass) are folded into the same group so the rename
    cannot collide on `async_update_entity`.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_mpris_"

    by_app: dict[str, list[er.RegistryEntry]] = {}
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not ent.unique_id.startswith(prefix):
            continue
        suffix = ent.unique_id[len(prefix):]
        if suffix.startswith(_MPRIS_OLD_BUS_SAFE_PREFIX):
            tail = suffix[len(_MPRIS_OLD_BUS_SAFE_PREFIX):]
            match = _MPRIS_INSTANCE_RE.match(tail)
            if not match:
                continue
            app = match.group(1)
        else:
            # Already in the new `<entry>_mpris_<app>` format.
            app = suffix
        by_app.setdefault(app, []).append(ent)

    for app, ents in by_app.items():
        new_uid = f"{prefix}{app}"
        keeper = _pick_keeper(ents, new_uid)
        for orphan in ents:
            if orphan is keeper:
                continue
            _LOGGER.info(
                "Removing orphan MPRIS entity %s (unique_id=%s)",
                orphan.entity_id,
                orphan.unique_id,
            )
            registry.async_remove(orphan.entity_id)
        if keeper.unique_id != new_uid:
            _LOGGER.info(
                "Migrating MPRIS unique_id for %s: %s → %s",
                keeper.entity_id,
                keeper.unique_id,
                new_uid,
            )
            try:
                registry.async_update_entity(
                    keeper.entity_id, new_unique_id=new_uid
                )
            except ValueError:
                # Defensive: a stray entity outside this group also holds the
                # target uid. Drop the keeper rather than fail the whole entry
                # setup; the other entity wins.
                _LOGGER.warning(
                    "Cannot migrate %s to %s (uid already in use); removing",
                    keeper.entity_id,
                    new_uid,
                )
                registry.async_remove(keeper.entity_id)


def migrate_mpris_service_mappings(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Rewrite MPRIS keys in entry.options[CONF_SERVICE_MAPPINGS].

    Old keys encoded the full D-Bus bus_name (`mpris:org.mpris.MediaPlayer2.
    firefox.instance_1_52`); they broke on every browser restart. New keys
    use the extracted app name (`mpris:firefox`), matching the stable form
    now produced by `OdioMPRISMediaPlayer._mapping_key`.
    """
    options: dict[str, Any] = dict(entry.options or {})
    mappings = options.get(CONF_SERVICE_MAPPINGS) or {}
    if not mappings:
        return

    new_mappings: dict[str, str] = {}
    changed = False
    for key, target in mappings.items():
        if not key.startswith("mpris:"):
            new_mappings[key] = target
            continue
        bus_name = key[len("mpris:"):]
        new_key = f"mpris:{extract_mpris_app_name(bus_name)}"
        if new_key != key:
            changed = True
            _LOGGER.info("Migrating MPRIS mapping key: %s → %s", key, new_key)
        # Collisions (e.g. two firefox bus_names mapping to different targets)
        # resolve to the last write — the user can re-pick in the options flow.
        new_mappings[new_key] = target

    if changed:
        hass.config_entries.async_update_entry(
            entry, options={**options, CONF_SERVICE_MAPPINGS: new_mappings}
        )


