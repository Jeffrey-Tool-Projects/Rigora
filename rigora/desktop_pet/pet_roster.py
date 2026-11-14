"""Several desktop characters: add, remove, enable, copy settings, layouts (R5.1).

Qt-free. Each character is a settings slot in :mod:`settings` (the primary
``default`` slot plus extras). This module adds what the slots lack: a
display name and an ``enabled`` flag per character, copying chosen settings
between characters, and named layouts that remember which characters were
running and where they stood.

Removing a character deletes only its own slot; the others are not touched.
The primary character cannot be removed (it can be disabled).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from rigora.desktop_pet import settings as pet_settings
from rigora.system.settings import user_setting_dict

LAYOUTS_KEY = "desktop_pet_layouts"
MAX_CHARACTERS = 8
MAX_LAYOUTS = 20
# Settings that describe one character's look and behaviour, as opposed to
# where it stands on screen.
COPYABLE = ("size_preset", "opacity", "click_through", "anchor_locked", "always_on_bottom",
            "hide_on_fullscreen", "snap_threshold", "drivers", "speech_enabled", "script_path",
            "llm_enabled", "llm_base_url", "llm_model", "llm_persona", "click_sfx_enabled",
            "click_sfx_volume", "click_sfx_paths", "pet_shadow_enabled", "pet_shadow_opacity",
            "pet_shadow_scale")
PLACEMENT = ("position", "screen_name", "relative_position")


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    enabled: bool
    rig_path: str
    script_path: str
    primary: bool


def characters() -> list[Character]:
    out = []
    for pet_id in pet_settings.list_pet_ids():
        data = pet_settings.load(pet_id)
        out.append(Character(
            id=pet_id, name=str(data.get("display_name") or _default_name(pet_id)),
            enabled=bool(data.get("enabled", pet_id == pet_settings.DEFAULT_PET_ID)),
            rig_path=str(data.get("last_rig_path") or ""),
            script_path=str(data.get("script_path") or ""),
            primary=pet_id == pet_settings.DEFAULT_PET_ID))
    return out


def _default_name(pet_id: str) -> str:
    return "Main character" if pet_id == pet_settings.DEFAULT_PET_ID else pet_id


def _new_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "pet"
    taken = set(pet_settings.list_pet_ids())
    candidate, index = base, 2
    while candidate in taken or candidate == pet_settings.DEFAULT_PET_ID:
        candidate, index = f"{base}-{index}", index + 1
    return candidate


def add_character(name: str, *, copy_from: str | None = None) -> str:
    """Create a character and return its id. ``copy_from`` copies that
    character's look and behaviour settings (not its position)."""
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("a character needs a name")
    if len(pet_settings.list_pet_ids()) >= MAX_CHARACTERS:
        raise ValueError(f"at most {MAX_CHARACTERS} characters")
    pet_id = _new_id(name)
    pet_settings.add_pet(pet_id)
    pet_settings.update(pet_id, display_name=name, enabled=False)
    if copy_from is not None:
        copy_settings(copy_from, pet_id, include_rig=True)
    return pet_id


def remove_character(pet_id: str) -> bool:
    """Delete one character's settings; the primary cannot be removed."""
    removed = pet_settings.remove_pet(pet_id)
    if removed:
        layouts = _layouts()
        for layout in layouts.values():
            layout.get("characters", {}).pop(pet_id, None)
        user_setting_dict[LAYOUTS_KEY] = layouts
    return removed


def rename(pet_id: str, name: str) -> None:
    _require(pet_id)
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("a character needs a name")
    pet_settings.update(pet_id, display_name=name)


def set_enabled(pet_id: str, enabled: bool) -> None:
    _require(pet_id)
    pet_settings.update(pet_id, enabled=bool(enabled))


def copy_settings(source: str, target: str, keys=COPYABLE, *,
                  include_rig: bool = False) -> list[str]:
    """Copy ``keys`` from ``source`` to ``target``; returns the keys copied."""
    _require(source)
    _require(target)
    if source == target:
        return []
    data = pet_settings.load(source)
    wanted = list(keys) + (["last_rig_path"] if include_rig else [])
    fields = {key: copy.deepcopy(data[key]) for key in wanted if key in data}
    pet_settings.update(target, **fields)
    return sorted(fields)


def _require(pet_id: str) -> None:
    if pet_id not in pet_settings.list_pet_ids():
        raise KeyError(f"no character {pet_id!r}")


# ---- layouts ------------------------------------------------------------------


def _layouts() -> dict:
    raw = user_setting_dict.get(LAYOUTS_KEY)
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def layout_names() -> list[str]:
    return sorted(_layouts())


def save_layout(name: str) -> dict:
    """Remember which characters run and where they stand."""
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("a layout needs a name")
    layouts = _layouts()
    if name not in layouts and len(layouts) >= MAX_LAYOUTS:
        raise ValueError(f"at most {MAX_LAYOUTS} layouts")
    entry = {"characters": {}}
    for character in characters():
        data = pet_settings.load(character.id)
        entry["characters"][character.id] = {
            "enabled": character.enabled,
            **{key: copy.deepcopy(data.get(key)) for key in PLACEMENT if key in data}}
    layouts[name] = entry
    user_setting_dict[LAYOUTS_KEY] = layouts
    return entry


def restore_layout(name: str) -> list[str]:
    """Apply a saved layout; returns the ids that should be running.
    Characters removed since the layout was saved are skipped, and
    characters added since are left disabled."""
    layouts = _layouts()
    if name not in layouts:
        raise KeyError(f"no layout {name!r}")
    saved = layouts[name].get("characters", {})
    running = []
    for character in characters():
        entry = saved.get(character.id)
        if entry is None:
            if not character.primary:
                set_enabled(character.id, False)
            continue
        fields = {key: entry[key] for key in PLACEMENT if key in entry}
        fields["enabled"] = bool(entry.get("enabled"))
        pet_settings.update(character.id, **fields)
        if fields["enabled"]:
            running.append(character.id)
    return running


def delete_layout(name: str) -> bool:
    layouts = _layouts()
    if name not in layouts:
        return False
    del layouts[name]
    user_setting_dict[LAYOUTS_KEY] = layouts
    return True
