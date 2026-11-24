"""Make a downloaded PS Vita game visible to Vita3K without copying it.

Vita3K only runs apps under its own ``<pref-path>/ux0/app/<TITLE_ID>``. A Vita
game stored in RomM as the folder of an installed app is downloaded and
extracted like any multi-file ROM; this adapter then points
``ux0/app/<TITLE_ID>`` at the extracted folder (a directory junction on
Windows, which needs no admin rights; a symlink elsewhere), copies any ``.rif``
licence it carries into ``ux0/license/<TITLE_ID>``, and writes a
``<TITLE_ID>.psvita`` file for ``rom-launcher.exe --title-id-file``. The game
data lives only in the ROM folder, so uninstalling the ROM removes it; the link
left behind is pruned on the next Vita install.

An ``ux0/app/<TITLE_ID>`` that is a real folder (a game installed into Vita3K
directly) is never touched.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from typing import TYPE_CHECKING

from domain.vita_app import find_app_roots, is_title_id, parse_sfo_title_id

if TYPE_CHECKING:
    import logging

_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _config_candidates() -> list[str]:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return [
            os.path.join(appdata, "EmuDeck", "Emulators", "vita3k", "config.yml"),
            os.path.join(appdata, "Vita3K", "Vita3K", "config.yml"),
        ]
    home = os.path.expanduser("~")
    return [
        os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")), "Vita3K", "config.yml"),
        os.path.join(home, ".var", "app", "org.vita3k.Vita3K", "config", "Vita3K", "config.yml"),
    ]


def _is_link(path: str) -> bool:
    """True for a symlink or a Windows directory junction (never for a real folder)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def _remove_link(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)  # a junction is removed as an empty directory; its target is untouched


def _make_link(target: str, link: str) -> None:
    if sys.platform == "win32":
        import _winapi  # noqa: PLC0415 — Windows-only stdlib module

        _winapi.CreateJunction(target, link)
    else:
        os.symlink(target, link, target_is_directory=True)


class Vita3kAppLinker:
    """Implements ``VitaAppLinker`` against the local Vita3K install."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def pref_path(self) -> str | None:
        """Vita3K's ``pref-path`` from the first config file found, or ``None``."""
        for candidate in _config_candidates():
            try:
                with open(candidate, encoding="utf-8") as f:
                    for line in f:
                        key, sep, value = line.partition(":")
                        if sep and key.strip() == "pref-path":
                            value = value.strip().strip("'\"")
                            if value:
                                return os.path.normpath(value)
            except OSError:
                continue
        return None

    def prepare(self, rom_dir: str) -> str | None:
        """Link the app inside *rom_dir* into Vita3K; return the ``.psvita`` launch file.

        ``None`` (with a warning logged) when *rom_dir* holds no Vita app or
        Vita3K's storage folder cannot be found — the caller keeps its own
        launch-file choice and the launch fails with that warning to go on.
        """
        rel_files = []
        for dirpath, _dirs, files in os.walk(rom_dir):
            for name in files:
                rel_files.append(os.path.relpath(os.path.join(dirpath, name), rom_dir))
        roots = find_app_roots(rel_files)
        if not roots:
            self._logger.warning("vita3k: no sce_sys/param.sfo under %s; not a Vita app folder", rom_dir)
            return None
        app_root = os.path.join(rom_dir, *roots[0].split("/")) if roots[0] else rom_dir
        title_id = self._title_id(app_root)
        if title_id is None:
            self._logger.warning("vita3k: no title ID in %s", app_root)
            return None
        pref = self.pref_path()
        if pref is None:
            self._logger.warning("vita3k: Vita3K config.yml with a pref-path not found; %s not linked", title_id)
            return None

        app_parent = os.path.join(pref, "ux0", "app")
        os.makedirs(app_parent, exist_ok=True)
        self._prune_dangling(app_parent)
        link = os.path.join(app_parent, title_id)
        if _is_link(link):
            _remove_link(link)
        if os.path.isdir(link) and not os.path.isfile(os.path.join(link, "sce_sys", "param.sfo")):
            self._set_aside_incomplete(link)
        if os.path.exists(link):
            self._logger.info("vita3k: %s is installed in Vita3K directly; using that copy", title_id)
        else:
            _make_link(os.path.abspath(app_root), link)
            self._logger.info("vita3k: linked %s -> %s", link, app_root)

        self._install_licences(rom_dir, rel_files, os.path.join(pref, "ux0", "license", title_id))

        launch_file = os.path.join(rom_dir, f"{title_id}.psvita")
        with open(launch_file, "w", encoding="ascii", newline="") as f:
            f.write(title_id)
        return launch_file

    @staticmethod
    def _title_id(app_root: str) -> str | None:
        try:
            with open(os.path.join(app_root, "sce_sys", "param.sfo"), "rb") as f:
                title_id = parse_sfo_title_id(f.read())
        except OSError:
            title_id = None
        if title_id is None:
            name = os.path.basename(os.path.normpath(app_root))
            title_id = name if is_title_id(name) else None
        return title_id

    def _set_aside_incomplete(self, folder: str) -> None:
        """Clear a real ``ux0/app/<ID>`` folder that holds no runnable app.

        Such a folder (no ``sce_sys/param.sfo``) is a leftover — an interrupted
        copy, or the empty skeleton a failed card backup leaves — and Vita3K
        would try to boot it instead of the downloaded game. A folder with no
        files at all is removed; one with some files is renamed aside so
        nothing that might matter is deleted.
        """
        has_files = any(files for _dirpath, _dirs, files in os.walk(folder))
        if not has_files:
            shutil.rmtree(folder)
            self._logger.info("vita3k: removed empty leftover folder %s", folder)
            return
        aside = f"{folder}.incomplete"
        n = 1
        while os.path.exists(aside):
            n += 1
            aside = f"{folder}.incomplete{n}"
        os.rename(folder, aside)
        self._logger.info("vita3k: moved incomplete folder %s aside to %s", folder, aside)

    def _install_licences(self, rom_dir: str, rel_files: list[str], dest_dir: str) -> None:
        for rel in rel_files:
            if not rel.lower().endswith(".rif"):
                continue
            dest = os.path.join(dest_dir, os.path.basename(rel))
            if os.path.exists(dest):
                continue
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copyfile(os.path.join(rom_dir, rel), dest)
            self._logger.info("vita3k: installed licence %s", dest)

    def _prune_dangling(self, app_parent: str) -> None:
        """Remove links left in ``ux0/app`` by Vita games whose ROM folder was uninstalled."""
        try:
            names = os.listdir(app_parent)
        except OSError:
            return
        for name in names:
            path = os.path.join(app_parent, name)
            if _is_link(path) and not os.path.exists(os.path.join(path, "sce_sys")):
                try:
                    _remove_link(path)
                    self._logger.info("vita3k: removed link to an uninstalled game: %s", path)
                except OSError as e:
                    self._logger.warning("vita3k: could not remove stale link %s: %s", path, e)
