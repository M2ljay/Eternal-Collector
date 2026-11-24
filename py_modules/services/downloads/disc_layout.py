"""The on-disk shape an extracted multi-file ROM is left in before it is recorded.

Everything between "the archive is extracted" and "this is the launch file and
the ROM directory": quirk healing, playlist generation, launch-file choice and
the ES-DE collapse rename. Raw filesystem I/O flows through the
``DownloadFileStore`` Protocol; the decisions are the pure kernels in
``domain.rom_files``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.disc_formats import DISC_IMAGE_EXTENSIONS
from domain.rom_files import (
    build_m3u_content,
    detect_launch_file,
    es_de_collapse_rename,
    folder_boot_layout_root,
    needs_m3u,
)

if TYPE_CHECKING:
    import logging

    from services.protocols import DownloadFileStore, SystemM3uSupportFn


@dataclass(frozen=True)
class DiscLayoutArrangerConfig:
    """Frozen wiring bundle handed to ``DiscLayoutArranger.__init__``."""

    download_file_store: DownloadFileStore
    m3u_support: SystemM3uSupportFn
    logger: logging.Logger


class DiscLayoutArranger:
    """Owns the layout an extracted multi-file ROM directory is installed in."""

    def __init__(self, *, config: DiscLayoutArrangerConfig) -> None:
        self._download_file_store = config.download_file_store
        self._m3u_support = config.m3u_support
        self._logger = config.logger

    def do_arrange(self, extract_dir: str, rom_detail: dict[str, Any], system: str) -> tuple[str, str]:
        """Lay out *extract_dir* for its emulator and front-end; return ``(rom_dir, launch_file)``.

        Synchronous — runs on the download's executor worker. ``rom_dir`` is
        *extract_dir* unless the ES-DE collapse rename moved it.
        """
        # Heal a folder-boot disc dump whose PS3_DISC.SFB ships .txt-suffixed,
        # before launch detection reads the layout (ADR-0019 / #1212).
        self._maybe_heal_ps3_sfb_io(extract_dir)
        # Whether ES-DE lists .m3u for this system (gates both M3U generation and
        # launch-file selection so a RomM-bundled .m3u is ignored on Switch/Xbox).
        m3u_supported = self._m3u_support(system)
        self._maybe_generate_m3u_io(extract_dir, rom_detail, m3u_supported)
        launch_file = self._collect_and_detect_launch_file(extract_dir, m3u_supported)
        # ES-DE collapses a multi-file dir into one game entry only when the
        # dir is named after the launch file *including* the extension. The
        # launch file is only known after extraction (the M3U may be
        # auto-generated above), so the rename happens here, last of all the
        # filesystem work, so a later failure cleans up the renamed dir.
        return self._maybe_es_de_collapse_io(extract_dir, launch_file)

    def _maybe_heal_ps3_sfb_io(self, extract_dir: str) -> None:
        """Copy a folder-boot dump's ``PS3_DISC.SFB.txt`` back to ``PS3_DISC.SFB``.

        RPCS3 identifies a disc-dump folder by a ``PS3_DISC.SFB`` at the game
        root; some RomM dumps ship it renamed ``PS3_DISC.SFB.txt`` and never
        boot until it is restored (verified on-device, #1212). Only for a
        folder-boot layout (:func:`folder_boot_layout_root` locates the game
        root) and only the exact ``.txt`` → real-name case: when the ``.txt``
        exists and the real name does not, a copy is written (the original is
        kept). Any other shape — real SFB already present, no ``.txt``, no
        folder-boot layout — is left untouched. Scoped to this one known dump
        quirk, not a general renamer.
        """
        all_files = self._download_file_store.scan_files_with_sizes(extract_dir)
        root = folder_boot_layout_root([path for path, _size in all_files])
        if root is None:
            return
        sfb = os.path.join(root, "PS3_DISC.SFB")
        sfb_txt = os.path.join(root, "PS3_DISC.SFB.txt")
        if self._download_file_store.exists(sfb_txt) and not self._download_file_store.exists(sfb):
            self._download_file_store.copy_file(sfb_txt, sfb)
            self._logger.info("healed PS3_DISC.SFB from .txt-suffixed dump: %s", sfb)

    def _maybe_generate_m3u_io(self, extract_dir: str, rom_detail: dict[str, Any], m3u_supported: bool) -> None:
        """Auto-generate a game-named M3U playlist when one is warranted (see ``needs_m3u``).

        Writes ``<fs_name_no_ext>.m3u`` when the platform supports ``.m3u``, no
        M3U already exists, and the disc files warrant one: multi-disc ROMs (any
        of cue/chd/iso) for disc switching, or a single-disc bin/cue ROM so the
        extract dir collapses to a game-named entry in ES-DE. When the platform
        does not support ``.m3u`` (per ES-DE's ``es_systems.xml``), no playlist
        is generated.
        """
        if not m3u_supported:
            return

        all_files = self._download_file_store.scan_files_with_sizes(extract_dir)
        # A folder-boot dump (PS3 — …/PS3_GAME/USRDIR/EBOOT.BIN) launches the game
        # directory directly (ADR-0019), never a playlist — and its many payload
        # files must never be misread as "discs". Suppress the M3U outright even
        # though ES-DE lists .m3u for the platform. (#1212)
        if folder_boot_layout_root([path for path, _size in all_files]) is not None:
            return
        if any(path.lower().endswith(".m3u") for path, _size in all_files):
            return

        disc_suffixes = tuple(DISC_IMAGE_EXTENSIONS)
        disc_files = [
            os.path.relpath(path, extract_dir) for path, _size in all_files if path.lower().endswith(disc_suffixes)
        ]

        if not needs_m3u(disc_files, m3u_supported):
            return

        rom_name = rom_detail.get("fs_name_no_ext", rom_detail.get("name", "playlist"))
        m3u_path = os.path.join(extract_dir, f"{rom_name}.m3u")
        self._download_file_store.write_text_atomic(m3u_path, build_m3u_content(disc_files))
        self._logger.info(f"Auto-generated M3U playlist: {m3u_path}")

    def _collect_and_detect_launch_file(self, extract_dir: str, m3u_supported: bool) -> str:
        """Find the best launch file in an extracted multi-file ROM directory.

        *m3u_supported* gates whether a ``.m3u`` (including a RomM-bundled one)
        may be chosen as the launch file — see ``detect_launch_file``.
        """
        all_files = self._download_file_store.scan_files_with_sizes(extract_dir)
        result = detect_launch_file(all_files, m3u_supported)
        return result if result is not None else extract_dir

    def _maybe_es_de_collapse_io(self, extract_dir: str, launch_file: str) -> tuple[str, str]:
        """Rename *extract_dir* after the launch file so ES-DE collapses it to one entry.

        Returns ``(rom_dir, launch_file)`` — the renamed pair when the move
        applied, or the originals unchanged. Moves the *whole* directory
        (never just the launch file — ADR-0008). Skips the move when
        ``es_de_collapse_rename`` reports no rename is needed, and on
        collision: if the target already exists the staging dir is kept and a
        warning is logged rather than clobbering or merging an existing dir.
        """
        rename = es_de_collapse_rename(extract_dir, launch_file)
        if rename is None:
            return (extract_dir, launch_file)
        new_rom_dir, new_launch_file = rename
        if self._download_file_store.exists(new_rom_dir):
            self._logger.warning(
                "ES-DE collapse rename skipped: target '%s' already exists; keeping staging dir '%s'",
                new_rom_dir,
                extract_dir,
            )
            return (extract_dir, launch_file)
        self._download_file_store.move_dir(extract_dir, new_rom_dir)
        return (new_rom_dir, new_launch_file)
