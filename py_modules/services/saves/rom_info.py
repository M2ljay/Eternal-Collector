"""Per-ROM save path resolution and local save-file discovery.

Resolves the on-disk save directory for an installed ROM (honouring
RetroArch's ``sort_savefiles_*`` settings and the optional per-core
subdirectory, or — when the ROM launches with a standalone emulator whose
saves the active launcher backend locates — that emulator's own save set)
and enumerates the matching local save files. Pure
filesystem + path-algebra responsibility — no RomM I/O, no state
mutation. Shared by SlotsService, SyncEngine, and StatusService; reads
about whether a save-sort migration is pending live here too because
they share ``_get_rom_save_info``'s decision to honour the previous
layout while a migration is in flight.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain import save_sync_blockers as blockers
from domain.disc_ids import GAMECUBE
from domain.emulator_tag import build_emulator_tag
from domain.save_extensions import get_save_extensions
from domain.save_layout import InSaveDir
from domain.save_path import resolve_save_dir
from domain.save_sync_blockers import SaveSyncBlocker
from domain.standalone_saves import (
    DISC_FAMILIES,
    PCSX2,
    PCSX2_CARDS_ELSEWHERE,
    STANDALONE_EMULATOR_TAGS,
    VITA3K,
    StandaloneSaveSet,
    disc_save_set,
    emulator_executable,
    identify_standalone_emulator,
    pcsx2_slot1,
    standalone_save_set,
)

# kv_config keys for the cross-run save-sort markers MigrationService writes
# (ADR-0003 Bucket 2): the last-seen observation and the pending pre-change
# snapshot. RomInfoService reads them to honour the previous save layout while
# a save-sort migration is in flight (#238).
_KV_SAVE_SORT = "save_sort_settings"
_KV_SAVE_SORT_PREVIOUS = "save_sort_settings_previous"

if TYPE_CHECKING:
    import logging

    from models.state import SaveSortSettings

    from services.protocols import (
        ActiveCoreReader,
        CoreNameProviderFn,
        DiscCodeReader,
        LauncherPaths,
        SaveFileStore,
        UnitOfWorkFactory,
    )


@dataclass(frozen=True)
class RomInfoServiceConfig:
    """Frozen wiring bundle handed to ``RomInfoService.__init__``.

    Holds the Unit-of-Work factory (the ``rom_installs`` aggregate is the
    source of truth for installed-ROM file records — WS3 — and ``kv_config``
    holds the save-sort markers), the Protocol-typed filesystem adapter, the
    active launcher backend's runtime-path accessor, the per-ROM active-core
    resolver, the RetroArch core-name provider, the disc-image identifier
    reader (for emulators that file saves under a disc's code), and the
    standard-library logger.
    """

    uow_factory: UnitOfWorkFactory
    save_file_store: SaveFileStore
    launcher_paths: LauncherPaths
    active_core: ActiveCoreReader
    get_core_name: CoreNameProviderFn
    disc_codes: DiscCodeReader
    logger: logging.Logger


class RomInfoService:
    """Resolves per-ROM save paths and discovers local save files on disk."""

    def __init__(self, *, config: RomInfoServiceConfig) -> None:
        self._config = config
        self._uow_factory = config.uow_factory
        self._save_file_store = config.save_file_store
        self._launcher_paths = config.launcher_paths
        self._active_core = config.active_core
        self._get_core_name = config.get_core_name
        self._disc_codes = config.disc_codes
        self._logger = config.logger

    def get_rom_save_info(self, rom_id: int) -> dict[str, Any] | None:
        """Get save-related info for an installed ROM.

        Returns dict with keys: system, rom_name, saves_dir, platform_slug,
        file_path, save_set, save_sync_blocker — or None if not installed.
        ``save_set`` is the :class:`StandaloneSaveSet` when the ROM launches
        with a standalone emulator whose saves the active backend locates;
        ``saves_dir`` is then that emulator's save folder. Otherwise
        ``save_set`` is ``None`` and ``saves_dir`` is the RetroArch save
        directory. ``save_sync_blocker`` is the :class:`SaveSyncBlocker` when
        the ROM launches with such an emulator but its exact save set cannot be
        derived — its saves are then not synced, and the user is told why.
        """
        info = self._retroarch_save_info(rom_id)
        if info is None:
            return None
        info["save_sync_blocker"] = None
        resolved = self._standalone_save_set(int(rom_id), info["rom_name"], info["file_path"])
        if isinstance(resolved, SaveSyncBlocker):
            info["save_sync_blocker"] = resolved
            self._logger.info("Save sync for rom %s is blocked: %s", rom_id, resolved.reason)
        elif resolved is not None:
            info["save_set"], info["saves_dir"] = resolved
        return info

    def save_sync_blocker(self, rom_id: int) -> SaveSyncBlocker | None:
        """Why this ROM's saves cannot be synced, or ``None`` when they can (or it is not installed)."""
        info = self.get_rom_save_info(rom_id)
        return info.get("save_sync_blocker") if info else None

    def _standalone_save_set(
        self, rom_id: int, rom_name: str, file_path: str
    ) -> tuple[StandaloneSaveSet, str] | SaveSyncBlocker | None:
        """The ROM's standalone save set and its folder, a blocker, or ``None`` for RetroArch handling.

        ``None`` when the active backend offers no standalone save folder at
        all (checked first, so a backend without one never pays for the
        emulator resolution) or the ROM does not launch with a standalone
        emulator. Past that, the ROM's saves live with the emulator, so every
        reason its exact save set cannot be derived is a
        :class:`SaveSyncBlocker`: an emulator this plugin does not know, a save
        folder the backend does not locate, or a save set the ROM does not
        yield — for an emulator that files saves under the disc's code, the
        installed image must be read exactly.
        """
        if not any(_nonempty_str(self._launcher_paths.standalone_saves_path(e)) for e in STANDALONE_EMULATOR_TAGS):
            return None
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        if emulator is None or emulator.kind != "standalone":
            return None
        emulator_id = identify_standalone_emulator(emulator.command)
        if emulator_id is None:
            exe = emulator_executable(emulator.command)
            return blockers.unknown_emulator(os.path.basename(exe.replace("\\", "/")) if exe else None)
        root = self._launcher_paths.standalone_saves_path(emulator_id)
        if not _nonempty_str(root):
            return blockers.emulator_folder_unknown(emulator_id)
        if emulator_id in DISC_FAMILIES:
            resolved = self._disc_save_set(emulator_id, emulator.command, file_path, root)
            if isinstance(resolved, SaveSyncBlocker):
                return resolved
            return resolved, root
        save_set = standalone_save_set(emulator_id, rom_name)
        if save_set is None:
            return blockers.vita_no_title_id() if emulator_id == VITA3K else blockers.unknown_emulator(None)
        return save_set, root

    def _disc_save_set(
        self, emulator_id: str, command: str | None, file_path: str, root: str
    ) -> StandaloneSaveSet | SaveSyncBlocker:
        family = DISC_FAMILIES[emulator_id]
        disc = self._disc_codes.read_disc_code(file_path, family)
        if disc is None:
            problem = self._disc_codes.disc_code_problem(file_path, family)
            kind, detail = problem if problem is not None else (None, None)
            return blockers.disc_problem(emulator_id, kind, detail, os.path.splitext(file_path)[1].lower())
        card: str | None = None
        if emulator_id == PCSX2:
            found = self._pcsx2_folder_card(command, root)
            if isinstance(found, SaveSyncBlocker):
                return found
            card = found
        save_set = disc_save_set(emulator_id, disc, card)
        if save_set is not None:
            return save_set
        if disc.platform == GAMECUBE:
            return blockers.disc_region_unknown(emulator_id)
        return blockers.disc_problem(emulator_id, "no_disc_id", None, "")

    def _pcsx2_folder_card(self, command: str | None, root: str) -> str | SaveSyncBlocker:
        """PCSX2's slot-1 card when it is a folder card in the EmuDeck-linked ``memcards`` folder, else why not.

        Read from ``inis/PCSX2.ini`` beside the executable (PCSX2's portable
        layout, which EmuDeck for Windows installs). An unreadable ini, a
        disabled slot, a file card, or a card elsewhere all mean no PCSX2 save
        is synced: which card the game writes to cannot be known exactly.
        """
        exe = emulator_executable(command)
        if not exe:
            return blockers.pcsx2_settings_unreadable()
        ini = os.path.join(os.path.dirname(exe), "inis", "PCSX2.ini")
        if not self._save_file_store.is_file(ini):
            return blockers.pcsx2_settings_unreadable()
        try:
            text = self._save_file_store.read_bytes(ini).decode("utf-8", errors="replace")
        except OSError:
            return blockers.pcsx2_settings_unreadable()
        card, problem = pcsx2_slot1(text)
        if card is None:
            return blockers.pcsx2_cards_elsewhere() if problem == PCSX2_CARDS_ELSEWHERE else blockers.pcsx2_slot_empty()
        card_dir = os.path.join(root, "saves", card)
        if self._save_file_store.is_file(card_dir):
            return blockers.pcsx2_file_card()
        if not self._save_file_store.is_dir(card_dir) or not self._save_file_store.is_file(
            os.path.join(card_dir, "_pcsx2_superblock")
        ):
            return blockers.pcsx2_card_missing(card)
        return card

    def upload_emulator_tag(self, rom_id: int, core_so: str | None) -> str:
        """The RomM ``emulator`` tag an upload of this ROM's save carries.

        The standalone emulator's own id for a standalone save set, so saves of
        two emulators never share a server folder or a local file; otherwise the
        ``retroarch-<core>`` tag of *core_so*.
        """
        info = self.get_rom_save_info(rom_id)
        save_set = info.get("save_set") if info else None
        return save_set.emulator_tag if save_set is not None else build_emulator_tag(core_so)

    def _retroarch_save_info(self, rom_id: int) -> dict[str, Any] | None:
        """The ROM's save info under RetroArch's layout, ignoring any standalone emulator."""
        with self._uow_factory() as uow:
            installed = uow.rom_installs.get(int(rom_id))
        if not installed:
            return None
        system = installed.system
        file_path = installed.file_path
        platform_slug = installed.platform_slug
        if not system or not file_path:
            return None
        rom_name = os.path.splitext(os.path.basename(file_path))[0]

        saves_base = self._launcher_paths.saves_path()
        roms_base = self._launcher_paths.roms_path()
        sorting = self.current_save_sorting()
        sort_by_content = sorting.sort_by_content
        sort_by_core = sorting.sort_by_core

        # When sort-by-core is active, RetroArch writes per-core subdirs named
        # by the .info ``corename`` field. Resolve it via the dedicated parser.
        # See docs: Config-Source-Parsers wiki page ("one parser per source").
        # Decision: warn-and-fallback (not fail-loud like MigrationService).
        # SaveService is the critical-path sync flow — every game launch
        # depends on it. Fail-loud would take down save sync entirely on any
        # .info hiccup. MigrationService can afford strictness (one-shot),
        # SaveService cannot (continuous). See issue #232 for history.
        core_name: str | None = None
        if sort_by_core:
            rom_filename = os.path.basename(file_path)
            core_name, core_so = self.resolve_retroarch_corename(int(rom_id))
            if core_name is None:
                self._logger.warning(
                    "SaveService: unable to resolve RetroArch corename for "
                    "%s/%s (core_so=%s) while sort_by_core is enabled. "
                    "Falling back to the parent save directory, which will "
                    "not match what RetroArch reads at runtime. Check that "
                    "the core's .info file is readable under the RetroDECK "
                    "Flatpak cores directory.",
                    system,
                    rom_filename,
                    core_so if core_so else "unresolved",
                )

        saves_dir = resolve_save_dir(
            file_path,
            saves_base,
            system,
            roms_base=roms_base,
            sort_by_content=sort_by_content,
            sort_by_core=sort_by_core,
            core_name=core_name,
        )

        return {
            "system": system,
            "rom_name": rom_name,
            "saves_dir": saves_dir,
            "platform_slug": platform_slug,
            "file_path": file_path,
            "save_set": None,
            "save_sync_blocker": None,
        }

    def current_save_sorting(self) -> InSaveDir:
        """The subdirectory sorting savefile paths are resolved with right now.

        The single answer to "which savefile layout is current", so every caller
        that has to address a save on disk addresses the same directory. It comes
        from the markers MigrationService records, never from the live
        ``retroarch.cfg``: while a save-sort migration is pending the *previous*
        layout wins, because RetroArch caches its runtime save-path at game-load
        time and the session that just ended still wrote to the old directory.
        Reading the live config here would point every caller at a directory the
        files have not reached yet (#238).

        Falls back to the RetroDECK defaults when nothing has been observed yet.
        Answers only the **sorting**: whether savefiles live under the saves root
        at all is ``savefiles_in_content_dir``, which is a live-config fact with
        no recorded counterpart — MigrationService never writes these markers for
        a ``ContentDir`` machine.
        """
        recorded = self.pending_sort_settings() or self._read_current_sort_settings()
        if not recorded:
            return InSaveDir(sort_by_content=True, sort_by_core=False)
        return InSaveDir(
            sort_by_content=recorded.get("sort_by_content", True),
            sort_by_core=recorded.get("sort_by_core", False),
        )

    def resolve_retroarch_corename(self, rom_id: int) -> tuple[str | None, str | None]:
        """Resolve the RetroArch ``corename`` for a ROM by ``rom_id``.

        Asks the per-ROM ``ActiveCoreReader`` **which** core is active for
        this ROM (the per-game ``emulator_override`` pin folded over the
        system default), then asks the RetroArch ``.info`` parser (via
        ``get_core_name``) **what** RetroArch calls that core in its own
        subsystem — which is the authoritative name used for per-core save
        subdirectories when ``sort_savefiles_enable`` is active.

        One parser per source: the ES-DE label (second element of the
        resolver tuple) is NOT a valid substitute for the RetroArch
        corename. See the Config-Source-Parsers wiki page and the reference
        implementation in ``MigrationService``.

        Returns ``(corename, core_so)``. Either element may be ``None``
        when resolution fails at that step: ``core_so`` is ``None`` when
        the resolver cannot determine the active core, ``corename`` is
        ``None`` when ``.info`` parsing returns nothing. Returning the tuple —
        rather than just ``corename`` — lets callers include ``core_so``
        in diagnostic logs so users can identify which ``.info`` file
        is at fault. Callers choose their own fallback strategy (e.g.
        warn and fall back for critical-path SaveService flows; skip
        and warn for one-shot migrations).
        """
        core_so, _label = self._active_core.active_core_for_rom(rom_id)
        if not core_so:
            return (None, None)
        corename = self._get_core_name(core_so)
        return (corename or None, core_so)

    def find_save_files(self, rom_id: int) -> list[dict[str, str]]:
        """Find local save files for a ROM.

        Returns list of ``{"path": str, "filename": str}``. For a standalone
        save set only the set's exact names are probed; a bundled save (a
        folder, or the entries a member layout owns) that exists is (re)packed
        into its zip here, so every consumer of the returned path sees the
        save's current content as one file.
        """
        info = self.get_rom_save_info(rom_id)
        if not info:
            return []
        rom_name = info["rom_name"]
        saves_dir = info["saves_dir"]
        system = info["system"]
        if not self._save_file_store.is_dir(saves_dir):
            return []
        save_set: StandaloneSaveSet | None = info.get("save_set")
        if save_set is not None:
            return self._find_standalone_files(saves_dir, save_set)
        results = []
        for ext in get_save_extensions(system):
            save_path = os.path.join(saves_dir, rom_name + ext)
            if self._save_file_store.is_file(save_path):
                results.append({"path": save_path, "filename": rom_name + ext})
        return results

    def _find_standalone_files(self, saves_dir: str, save_set: StandaloneSaveSet) -> list[dict[str, str]]:
        results = []
        for entry in save_set.entries:
            path = os.path.join(saves_dir, entry.filename)
            layout = entry.layout
            if layout is not None and layout.folder is not None:
                folder = os.path.join(saves_dir, *layout.folder.split("/"))
                if not self._save_file_store.is_dir(folder) or self._save_file_store.is_symlink(folder):
                    continue
                self._save_file_store.pack_save_folder(folder, path)
            elif layout is not None:
                if not self._save_file_store.pack_member_bundle(saves_dir, layout, path):
                    continue
            elif not self._save_file_store.is_file(path):
                continue
            results.append({"path": path, "filename": entry.filename})
        return results

    def expected_save_files(self, rom_id: int) -> list[dict[str, str]]:
        """Project exact RetroArch save paths for one installed ROM without broad scanning.

        Always the RetroArch projection, even for a ROM whose saves sync from a
        standalone emulator: the removed-game cleanup that consumes this never
        reaches a standalone emulator's save folder.
        """
        info = self._retroarch_save_info(rom_id)
        if not info:
            return []
        return [
            {
                "path": os.path.join(info["saves_dir"], info["rom_name"] + ext),
                "filename": info["rom_name"] + ext,
                "saves_dir": info["saves_dir"],
            }
            for ext in get_save_extensions(info["system"])
        ]

    def pending_sort_settings(self) -> SaveSortSettings | None:
        """Return previous save-sort settings if a migration is pending, else None.

        Rejects empty dicts to avoid the half-state where ``get_rom_save_info``'s
        ``or`` fallback would treat ``{}`` as "no pending migration" (and read
        current settings) while ``is_save_sort_changed`` would treat the same
        ``{}`` as "pending" (and gate sync). Both call sites must agree on
        what counts as pending — see #238 review finding 3.
        """
        with self._uow_factory() as uow:
            raw = uow.kv_config.get(_KV_SAVE_SORT_PREVIOUS)
        prev: SaveSortSettings | None = json.loads(raw) if raw is not None else None
        return prev if prev else None

    def _read_current_sort_settings(self) -> SaveSortSettings | None:
        """Return the last-seen RetroArch save-sort observation, ``None`` when unobserved."""
        with self._uow_factory() as uow:
            raw = uow.kv_config.get(_KV_SAVE_SORT)
        return json.loads(raw) if raw is not None else None

    def is_save_sort_changed(self) -> bool:
        """Check if a save sort migration is pending (detected by MigrationService)."""
        return self.pending_sort_settings() is not None


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)
