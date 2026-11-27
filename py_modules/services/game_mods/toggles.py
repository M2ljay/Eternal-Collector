"""ToggleEditor — reading a built-in-toggle target's entries and planning the edit that switches one.

Each format is read the way its emulator reads it (``domain.mod_toggles``,
``domain.rpcs3_patches``, ``domain.xenia_patches``, ``domain.cemu_packs``); a
plan changes only the lines (or, for RPCS3's YAML, the keys) carrying one
entry's state in the one file the target names. Writing the plan — the backup,
the unchanged-since-read check, the refusal while the emulator runs — is the
façade's, so every format takes the same write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.cemu_packs import PackInfo, cemu_packs, cemu_set_pack, pack_info
from domain.game_mods import ToggleSource, join_path
from domain.mod_targets import (
    TOGGLE_AZAHAR_CHEATS,
    TOGGLE_CEMU_PACKS,
    TOGGLE_DOLPHIN_ACTION_REPLAY,
    TOGGLE_DOLPHIN_GECKO,
    TOGGLE_PCSX2_PATCHES,
    TOGGLE_RPCS3_PATCHES,
    TOGGLE_XENIA_PATCHES,
    pcsx2_pnach_matches,
)
from domain.mod_toggles import (
    DOLPHIN_ACTION_REPLAY,
    DOLPHIN_GECKO,
    ORIGIN_BUILTIN,
    PCSX2_CHEATS,
    PCSX2_PATCHES,
    ToggleEntry,
    ToggleList,
    azahar_cheats,
    azahar_set_cheat,
    dolphin_codes,
    dolphin_set_code,
    pcsx2_enabled,
    pcsx2_entries,
    pcsx2_set_enabled,
    pnach_groups,
)
from domain.rpcs3_patches import (
    config_for_dump,
    config_is_tree,
    patch_list_subset,
    rpcs3_patches,
    rpcs3_set,
    rpcs3_target,
)
from domain.xenia_patches import xenia_patches, xenia_set_patch

if TYPE_CHECKING:
    from services.protocols import GameModStore, YamlCodec

_SCAN_LIMIT = 2000
_PACKS_FOLDER = "graphicPacks"


@dataclass(frozen=True)
class ToggleState:
    """A target's entries, plus what a switch of one needs that the list does not show.

    ``defaults`` maps an entry to whether it is on when nothing switches it
    (Dolphin's shipped default, a Cemu pack's ``default``); ``docs`` are the
    RPCS3 patch lists as read; ``written`` is the edited file's text as read
    (``None`` when it does not exist).
    """

    listing: ToggleList
    written: str | None
    defaults: dict[str, bool]
    docs: tuple[tuple[str, dict[str, Any]], ...] = ()
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToggleEditorConfig:
    """Frozen wiring for ``ToggleEditor``: the mod-folder filesystem seam and the YAML codec (RPCS3)."""

    mod_store: GameModStore | None
    yaml: YamlCodec


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


class ToggleEditor:
    """Reads built-in toggle entries and plans single-entry edits; writes nothing itself."""

    def __init__(self, *, config: ToggleEditorConfig) -> None:
        self._store = config.mod_store
        self._yaml = config.yaml

    @property
    def _fs(self) -> GameModStore:
        if self._store is None:
            raise RuntimeError("ToggleEditor used without a mod store")
        return self._store

    def _read(self, path: str) -> tuple[bool, str | None]:
        """``(exists, text)``: a file that exists but cannot be read as text answers ``(True, None)``."""
        return (True, self._fs.load_text(path)) if self._fs.is_file(path) else (False, None)

    def state(self, source: ToggleSource) -> ToggleState:
        """The entries of *source* with everything a switch needs."""
        exists, written = self._read(source.write_file)
        if exists and written is None:
            return ToggleState(ToggleList((), False, f"{source.write_file} could not be read as text."), None, {})
        fmt = source.format
        if fmt in (TOGGLE_DOLPHIN_GECKO, TOGGLE_DOLPHIN_ACTION_REPLAY):
            section = DOLPHIN_GECKO if fmt == TOGGLE_DOLPHIN_GECKO else DOLPHIN_ACTION_REPLAY
            shipped = [self._read(p)[1] for p in source.read_files]
            user = [(_base(p), self._read(p)[1]) for p in source.user_files]
            listing = dolphin_codes(section, shipped, user, _base(source.write_file))
            defaults = {e.entry_id: e.enabled for e in dolphin_codes(section, shipped, [], "").entries}
            return ToggleState(listing, written, defaults)
        if fmt == TOGGLE_AZAHAR_CHEATS:
            return ToggleState(azahar_cheats(written, _base(source.write_file)), written, {})
        if fmt == TOGGLE_RPCS3_PATCHES:
            return self._rpcs3_state(source, written)
        if fmt == TOGGLE_XENIA_PATCHES:
            listing = xenia_patches(written, _base(source.write_file))
            if len(source.read_files) > 1:
                reason = f"This game's patches are split over {len(source.read_files)} files; switch them in Xenia."
                listing = ToggleList(
                    tuple(
                        ToggleEntry(e.entry_id, e.name, e.description, e.enabled, False, e.origin, e.notes)
                        for e in listing.entries
                    ),
                    False,
                    reason,
                )
            return ToggleState(listing, written, {})
        if fmt == TOGGLE_CEMU_PACKS:
            return self._cemu_state(source, written)
        return self._pcsx2_state(source, written)

    def _pcsx2_state(self, source: ToggleSource, written: str | None) -> ToggleState:
        section = PCSX2_PATCHES if source.format == TOGGLE_PCSX2_PATCHES else PCSX2_CHEATS
        files: list[tuple[str, str]] = []
        if source.scan_dir is not None:
            names = pcsx2_pnach_matches(self._fs.list_file_names(source.scan_dir, _SCAN_LIMIT), source.scan_prefixes)
            files = [(n, t) for n in names if (t := self._read(join_path(source.scan_dir, n))[1]) is not None]
        if source.zip_file is not None and not any(pnach_groups(text)[1] for _n, text in files):
            for member in source.zip_members:
                text = self._fs.read_zip_text(source.zip_file, member)
                if text is not None:
                    files.append((ORIGIN_BUILTIN, text))
                    break
        enabled = pcsx2_enabled(written, section)
        if enabled is None:
            reason = f"{source.write_file} has a line PCSX2's settings reader would not take; edit it in PCSX2."
            return ToggleState(pcsx2_entries(files, set(), editable=False, reason=reason), written, {})
        return ToggleState(pcsx2_entries(files, enabled, editable=True), written, {})

    def _rpcs3_state(self, source: ToggleSource, written: str | None) -> ToggleState:
        serial, version = source.game[0], (source.game[1] or None)
        docs: list[tuple[str, dict[str, Any]]] = []
        for path in source.read_files:
            text = self._read(path)[1]
            if text is None:
                continue
            try:
                doc = self._yaml.load(patch_list_subset(text, serial))
            except ValueError:
                listing = ToggleList((), False, f"RPCS3's {_base(path)} could not be read as YAML.")
                return ToggleState(listing, written, {})
            if isinstance(doc, dict):
                docs.append((_base(path), doc))
        try:
            config = self._yaml.load(written) if written else {}
        except ValueError:
            config = None
        if not config_is_tree(config):
            config = None
        if config is None:
            reason = f"{source.write_file} could not be read as RPCS3 writes it; switch patches in RPCS3."
            listing = rpcs3_patches(docs, {}, serial, version, editable=False, reason=reason)
            return ToggleState(listing, written, {}, tuple(docs), None)
        tree = config if isinstance(config, dict) else {}
        return ToggleState(rpcs3_patches(docs, tree, serial, version), written, {}, tuple(docs), tree)

    def _cemu_state(self, source: ToggleSource, written: str | None) -> ToggleState:
        title_id = source.game[0]
        packs: list[tuple[str, PackInfo]] = []
        if source.scan_dir is not None:
            for rel in self._fs.find_files(source.scan_dir, "rules.txt", _SCAN_LIMIT):
                text = self._read(join_path(source.scan_dir, *rel.split("\\")))[1]
                info = pack_info(text) if text is not None else None
                if info is not None:
                    packs.append((f"{_PACKS_FOLDER}\\{rel}", info))
        listing = cemu_packs(packs, written, title_id, settings_file=source.write_file)
        defaults = {rel: info.default_enabled for rel, info in packs}
        return ToggleState(listing, written, defaults)

    def switched_text(self, source: ToggleSource, state: ToggleState, entry_id: str, enabled: bool) -> str | None:
        """The edited file's new text with *entry_id* switched, or ``None`` when that cannot be done safely."""
        fmt, text = source.format, state.written
        if fmt == TOGGLE_DOLPHIN_GECKO:
            return dolphin_set_code(text, DOLPHIN_GECKO, entry_id, enabled, state.defaults.get(entry_id, False))
        if fmt == TOGGLE_DOLPHIN_ACTION_REPLAY:
            return dolphin_set_code(text, DOLPHIN_ACTION_REPLAY, entry_id, enabled, state.defaults.get(entry_id, False))
        if fmt == TOGGLE_AZAHAR_CHEATS:
            return azahar_set_cheat(text, entry_id, enabled) if text is not None else None
        if fmt == TOGGLE_XENIA_PATCHES:
            return xenia_set_patch(text, entry_id, enabled) if text is not None else None
        if fmt == TOGGLE_CEMU_PACKS:
            if text is None:
                return None
            return cemu_set_pack(text, entry_id, enabled, state.defaults.get(entry_id, False))
        if fmt == TOGGLE_RPCS3_PATCHES:
            if state.config is None:
                return None
            serial, version = source.game[0], (source.game[1] or None)
            where = rpcs3_target(list(state.docs), entry_id, serial, version)
            if where is None:
                return None
            hash_key, description, title, app_version = where
            changed = rpcs3_set(state.config, (hash_key, description, title, serial, app_version), enabled)
            return self._yaml.dump(config_for_dump(changed))
        section = PCSX2_PATCHES if fmt == TOGGLE_PCSX2_PATCHES else PCSX2_CHEATS
        return pcsx2_set_enabled(text, section, entry_id, enabled)
