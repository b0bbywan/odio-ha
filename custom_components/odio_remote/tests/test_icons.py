"""icons.json stays in sync with the entities' translation keys."""
from __future__ import annotations

import json
import re
from pathlib import Path

_PKG = Path(__file__).parent.parent
_KEY_RE = re.compile(r'_attr_translation_key = "([a-z0-9_]+)"')


def _translation_keys(platform: str) -> set[str]:
    return set(_KEY_RE.findall((_PKG / f"{platform}.py").read_text()))


def test_every_icon_matches_a_translation_key():
    icons = json.loads((_PKG / "icons.json").read_text())["entity"]
    for platform, entries in icons.items():
        missing = set(entries) - _translation_keys(platform)
        assert not missing, f"{platform}: no entity uses {sorted(missing)}"
