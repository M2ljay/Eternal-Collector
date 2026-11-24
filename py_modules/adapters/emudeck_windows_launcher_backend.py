"""EmuDeck for Windows launcher backend — the ``LauncherBackend`` used under Decky on Windows.

EmuDeck for Windows (``EmuDeck/emudeck-we``) is laid out nothing like EmuDeck
on Linux, which the emu-atlas-backed :mod:`adapters.emudeck_launcher_backend`
understands: there is no ``settings.sh``, no AppImages or Flatpaks, and ES-DE
is optional (many installs launch everything through Steam ROM Manager
instead). Two files EmuDeck for Windows always maintains answer everything this
backend needs:

``%APPDATA%\\EmuDeck\\settings.ps1``
    PowerShell assignments (``$romsPath="C:\\Emulation\\roms"``) naming the
    ROM, BIOS, saves and tools roots. Its presence is the detection signal.

Steam ROM Manager's ``userConfigurations.json`` (under ``$toolsPath\\userData``)
    One parser per system and emulator — exactly what EmuDeck itself uses to
    put games in Steam. Each parser's ``romDirectory`` names the system folder
    (``${romsdirglobal}/snes``) and its ``executableArgs`` name the EmuDeck
    launcher script plus the emulator arguments, e.g.
    ``retroarch.ps1 -L 'cores\\snes9x_libretro.dll' '${filePath}'``. When this
    file is absent, EmuDeck's shipped parser templates
    (``backend\\configs\\steam-rom-manager\\userData\\parsers\\emudeck``) are read
    instead.

Each launcher script (``$toolsPath\\launchers\\<name>.ps1``) names its emulator
in a single ``$emulatorFile = "..."`` line. The backend resolves that path and
bakes a direct command — ``"<emulator.exe>" <args> "<rom>"`` — rather than going
through the PowerShell script, which on every launch runs ``git pull`` on
EmuDeck's backend and EmuDeck Cloud Sync. Skipping it makes launches start
immediately and keeps EmuDeck's cloud sync from contending with RomM's own save
sync. Per-emulator "launch fixes" EmuDeck may apply in that script are skipped
too; none is known to be needed for a normal game launch.

Quoting follows the Windows C runtime's command-line rules, since the baked
command reaches the emulator through ``bin\\rom-launcher.exe`` verbatim. A
Windows file name can never contain ``"``, so a quoted path is always a single
argument; trailing backslashes inside quotes are doubled per those rules.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.emulator_commands import EmulatorOption, option_to_invocation, select_default_option
from domain.launcher_backend import EMUDECK_BACKEND_ID, BackendValidation, DetectedInstallation
from domain.standalone_saves import DUCKSTATION, MELONDS, VITA3K
from lib.retrodeck_health import RetroDeckConfigHealth

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from domain.shortcut_data import EmulatorInvocation

_DISPLAY_NAME = "EmuDeck"
_SETTINGS_RELATIVE = os.path.join("EmuDeck", "settings.ps1")
_SRM_USER_CONFIG_RELATIVE = os.path.join("userData", "userConfigurations.json")
_SRM_TEMPLATE_DIR_RELATIVE = os.path.join(
    "EmuDeck", "backend", "configs", "steam-rom-manager", "userData", "parsers", "emudeck"
)

# `$name="value"` / `$name=value` lines in settings.ps1.
_PS1_ASSIGNMENT_RE = re.compile(r'^\s*\$(\w+)\s*=\s*"?(.*?)"?\s*$')
# The first `$emulatorFile = "..."` in a launcher script.
_EMULATOR_FILE_RE = re.compile(r'^\s*\$emulatorFile\s*=\s*"([^"]+)"', re.MULTILINE)
# `& ${{}C:\Emulation\tools\launchers\<name>.ps1 <args>${\}}` inside an SRM
# parser's executableArgs: the launcher script name and its argument text.
_LAUNCHER_CALL_RE = re.compile(r"[\\/]launchers[\\/]([\w.-]+)\.ps1\s*(.*?)\$\{\\\}\}", re.DOTALL)
_ROMS_DIR_TOKEN = "${romsdirglobal}"
_ROM_SENTINEL = "\x00ROM\x00"
_RETROARCH_EXE = "retroarch.exe"
_CORE_SUFFIX = "_libretro.dll"
_VITA3K_SCRIPT = "vita3k"
# Understood by bin\rom-launcher.exe: replace the trailing quoted ROM path with
# the title ID that file holds (see native/rom-launcher-win/rom-launcher.c).
_TITLE_ID_FLAG = "--title-id-file"
# EmuDeck for Windows links each emulator's per-game save folder to
# ``$savesPath\<folder>\saves``: melonDS's save directory, DuckStation's
# ``memcards`` and Vita3K's ``ux0\user\00\savedata``.
_STANDALONE_SAVE_FOLDERS = {MELONDS: "melonds", DUCKSTATION: "duckstation", VITA3K: "Vita3K"}


class _TemplateError(ValueError):
    """An SRM ``${...}`` variable this backend does not know how to resolve."""


@dataclass(frozen=True)
class _Catalogue:
    """Every parsed option, by system folder, plus whether any source was readable."""

    by_system: dict[str, list[EmulatorOption]]
    available: bool


# -- pure helpers --------------------------------------------------------------


def parse_ps1_settings(text: str) -> dict[str, str]:
    """Parse EmuDeck's ``settings.ps1`` assignments into ``{name: value}``."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _PS1_ASSIGNMENT_RE.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def resolve_srm_template(text: str) -> str:
    """Resolve the Steam ROM Manager variables EmuDeck's parsers use.

    ``${os:win|A|ELSE}`` picks ``A`` (nesting allowed), ``${/}`` is the
    Windows separator, and ``${filePath}`` becomes a sentinel the caller
    replaces with the ROM path at bake time. Anything else raises
    :class:`_TemplateError`, so an unfamiliar parser is refused rather than
    baked with a literal ``${...}`` in it.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("${", i):
            end = _matching_brace(text, i + 1)
            out.append(_resolve_variable(text[i + 2 : end]))
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for j in range(open_index, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    raise _TemplateError(f"unbalanced SRM variable in {text!r}")


def _resolve_variable(inner: str) -> str:
    if inner == "/":
        return "\\"
    if inner == "filePath":
        return _ROM_SENTINEL
    if inner.startswith("os:"):
        branches = _split_top_level(inner, "|")
        if branches[0] == "os:win" and len(branches) >= 2:
            return resolve_srm_template(branches[1])
        raise _TemplateError(f"no Windows branch in ${{{inner}}}")
    raise _TemplateError(f"unknown SRM variable ${{{inner}}}")


def _split_top_level(text: str, sep: str) -> list[str]:
    parts, depth, current = [], 0, []
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def split_powershell_args(text: str) -> list[str]:
    """Split a launcher call's argument text into tokens.

    EmuDeck's parsers single-quote every argument that may contain spaces
    (``-L 'cores\\x_libretro.dll' '${filePath}'``); bare words split on
    whitespace. ``''`` inside a single-quoted token is PowerShell's escaped
    quote.
    """
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        token: list[str] = []
        while i < n and not text[i].isspace():
            if text[i] == "'":
                i += 1
                while i < n:
                    if text[i] == "'" and i + 1 < n and text[i + 1] == "'":
                        token.append("'")
                        i += 2
                    elif text[i] == "'":
                        i += 1
                        break
                    else:
                        token.append(text[i])
                        i += 1
            else:
                token.append(text[i])
                i += 1
        tokens.append("".join(token))
    return tokens


def quote_windows_arg(arg: str, *, always: bool = False) -> str:
    """Quote one argument for a Windows command line (C runtime rules).

    Returns *arg* unchanged when it needs no quoting (and *always* is false).
    Backslashes are literal except before a ``"``, so only a run of trailing
    backslashes is doubled before the closing quote. Callers never pass a
    ``"`` (impossible in a Windows path, refused upstream otherwise).
    """
    if not always and arg and not any(c in arg for c in ' \t"'):
        return arg
    trailing = len(arg) - len(arg.rstrip("\\"))
    return '"' + arg + "\\" * trailing + '"'


def expand_launcher_path(raw: str, appdata: str, user_profile: str) -> str:
    """Expand ``$env:APPDATA`` / ``$env:USERPROFILE`` in a launcher's ``$emulatorFile``."""
    expanded = re.sub(r"\$env:APPDATA", lambda _m: appdata, raw, flags=re.IGNORECASE)
    expanded = re.sub(r"\$env:USERPROFILE", lambda _m: user_profile, expanded, flags=re.IGNORECASE)
    return os.path.normpath(expanded.replace("/", "\\") if os.sep == "\\" else expanded)


_GLOB_FOLDERS_RE = re.compile(r"^(?:@\(([^)]+)\)|\{([^}]+)\}|([\w-]+))/")


def systems_from_glob(glob: str) -> list[str]:
    """Leading system folders of a parser glob rooted at the ROMs folder.

    ``@(segacd|megacd)/**/...`` → ``["segacd", "megacd"]``;
    ``{genesis/**/!(homebrew),genesis,megadrive/**}/...`` → ``["genesis", "megadrive"]``.
    """
    match = _GLOB_FOLDERS_RE.match(glob)
    if match is None:
        return []
    raw = match.group(1) or match.group(2) or match.group(3) or ""
    systems: list[str] = []
    for alternative in re.split(r"[|,]", raw):
        folder = re.split(r"[\\/]", alternative.strip())[0].lower()
        if folder and re.fullmatch(r"[\w-]+", folder) and folder not in systems:
            systems.append(folder)
    return systems


def system_from_rom_directory(rom_directory: str) -> tuple[str, bool] | None:
    """Return ``(system folder, is_subfolder)`` for a parser's ``romDirectory``.

    ``${romsdirglobal}/snes`` → ``("snes", False)``;
    ``${romsdirglobal}/ps4/shortcuts`` → ``("ps4", True)``. ``None`` when the
    parser does not read from the ROMs root at all (EmuDeck's "Emulators"
    parser, which lists the launcher scripts themselves).
    """
    if not rom_directory.startswith(_ROMS_DIR_TOKEN):
        return None
    # SRM's ${/} is its path-separator variable (the psvita parser uses it).
    tail = rom_directory[len(_ROMS_DIR_TOKEN) :].replace("${/}", "/")
    parts = [p for p in re.split(r"[\\/]+", tail) if p]
    if not parts:
        return None
    return parts[0].lower(), len(parts) > 1


def option_label(config_title: str) -> str:
    """``"Nintendo SNES (Super Nintendo) - RetroArch Snes9x"`` → ``"RetroArch Snes9x"``."""
    _, sep, tail = config_title.rpartition(" - ")
    return tail.strip() if sep and tail.strip() else config_title.strip()


# -- the backend -----------------------------------------------------------------


class EmuDeckWindowsLauncherBackend:
    """EmuDeck for Windows bound to one detected installation. Implements ``LauncherBackend``."""

    backend_id = EMUDECK_BACKEND_ID

    def __init__(
        self,
        *,
        installation_id: str,
        settings: dict[str, str],
        appdata: str,
        user_profile: str,
        resolve_system: Callable[[str, str | None], str],
        logger: logging.Logger,
        path_exists: Callable[[str], bool] = os.path.exists,
    ) -> None:
        self.installation_id = installation_id
        self._settings = settings
        self._appdata = appdata
        self._user_profile = user_profile
        self._resolve_system = resolve_system
        self._logger = logger
        self._exists = path_exists
        self._cache: tuple[tuple[float, ...], _Catalogue] | None = None

    # -- LauncherBackend: paths ------------------------------------------------

    def roms_path(self) -> str:
        return self._settings.get("romsPath", "")

    def bios_path(self) -> str:
        return self._settings.get("biosPath", "")

    def saves_path(self) -> str:
        """RetroArch's save folder — the tree save sync manages.

        EmuDeck keeps saves per emulator under ``savesPath`` and links
        RetroArch's own ``saves`` folder to ``savesPath\\retroarch\\saves``,
        which is where ``savefile_directory`` (``:\\saves``) lands.
        """
        saves = self._settings.get("savesPath", "")
        return os.path.join(saves, "retroarch", "saves") if saves else ""

    def states_path(self) -> str:
        saves = self._settings.get("savesPath", "")
        return os.path.join(saves, "retroarch", "states") if saves else ""

    def standalone_saves_path(self, emulator_id: str) -> str:
        """``$savesPath\\<emulator folder>\\saves`` for a supported standalone emulator, else ``""``."""
        saves = self._settings.get("savesPath", "")
        folder = _STANDALONE_SAVE_FOLDERS.get(emulator_id)
        return os.path.join(saves, folder, "saves") if saves and folder else ""

    def validate(self) -> BackendValidation:
        roms = self.roms_path()
        if not roms or not os.path.isdir(roms):
            return BackendValidation(ok=False, reason="roms_missing", message=f"EmuDeck ROMs folder not found: {roms!r}")
        if not self._catalogue().available:
            return BackendValidation(
                ok=False,
                reason="catalogue_missing",
                message="No Steam ROM Manager parsers found for EmuDeck; run EmuDeck once to set it up.",
            )
        return BackendValidation(ok=True)

    # -- LauncherBackend: rendering --------------------------------------------

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str:
        """The baked command prefix (``"<exe>" <args>``) for *rom*'s system, or ``""``."""
        system = self._resolve_system(rom.get("platform_slug", ""), rom.get("platform_fs_slug"))
        options = self.get_emulator_options(system)["options"]
        chosen = None
        if emulator is not None and emulator.label:
            chosen = next((o for o in options if o.label == emulator.label and o.status == "bakeable"), None)
        if chosen is None:
            chosen = select_default_option(options)
        if chosen is None:
            self._logger.warning(
                "emudeck_windows: no launchable emulator for system %r (%s)",
                system,
                "; ".join(f"{o.label}={o.status}/{o.reason}" for o in options) or "no parsers",
            )
            return ""
        return chosen.command

    def build_launch_options(self, invocation: str, path: str) -> str:
        """``<invocation> "<rom path>"``, or ``""`` when there is nothing to launch."""
        if not invocation or not path:
            return ""
        if '"' in path:
            self._logger.warning("emudeck_windows: refusing a ROM path containing a quote: %r", path)
            return ""
        return f"{invocation} {quote_windows_arg(path.rstrip(chr(92) + '/'), always=True)}"

    # -- CoreInfoProvider ------------------------------------------------------

    def get_emulator_options(self, system_name: str) -> dict[str, Any]:
        catalogue = self._catalogue()
        return {"available": catalogue.available, "options": list(catalogue.by_system.get(system_name.lower(), []))}

    def get_default_emulator(self, system_name: str) -> EmulatorInvocation | None:
        return option_to_invocation(select_default_option(self.get_emulator_options(system_name)["options"]))

    def get_active_core(self, system_name: str) -> tuple[str | None, str | None]:
        for option in self.get_emulator_options(system_name)["options"]:
            if option.kind == "libretro" and option.core_so:
                return (option.core_so, option.label)
        return (None, None)

    def resolve_sandbox_launcher(self, command: str) -> str | None:
        del command  # no sandbox on Windows; the bake is already a direct command
        return None

    def reset_cache(self) -> None:
        self._cache = None

    # -- catalogue -------------------------------------------------------------

    def _launchers_dir(self) -> str:
        return os.path.join(self._settings.get("toolsPath", ""), "launchers")

    def _sources(self) -> list[str]:
        """The parser files to read, best first: the user's live SRM config, else EmuDeck's templates."""
        user_config = os.path.join(self._settings.get("toolsPath", ""), _SRM_USER_CONFIG_RELATIVE)
        if os.path.isfile(user_config):
            return [user_config]
        template_dir = os.path.join(self._appdata, _SRM_TEMPLATE_DIR_RELATIVE)
        try:
            names = sorted(n for n in os.listdir(template_dir) if n.lower().endswith(".json"))
        except OSError:
            return []
        return [os.path.join(template_dir, n) for n in names]

    def _catalogue(self) -> _Catalogue:
        sources = self._sources()
        stamp = tuple(_mtime(p) for p in [*sources, self._launchers_dir()])
        if self._cache is not None and self._cache[0] == stamp:
            return self._cache[1]
        parsers: list[dict[str, Any]] = []
        for source in sources:
            parsers.extend(_load_parsers(source, self._logger))
        catalogue = self._build_catalogue(parsers, available=bool(parsers))
        self._cache = (stamp, catalogue)
        return catalogue

    def _build_catalogue(self, parsers: list[dict[str, Any]], *, available: bool) -> _Catalogue:
        by_system: dict[str, list[EmulatorOption]] = {}
        exe_by_script: dict[str, str | None] = {}
        for parser in parsers:
            if parser.get("disabled") is True:
                continue
            rom_directory = str(parser.get("romDirectory", ""))
            placements: list[tuple[str, bool]]
            if rom_directory.rstrip("\\/") == _ROMS_DIR_TOKEN:
                glob = str((parser.get("parserInputs") or {}).get("glob", ""))
                placements = [(system, False) for system in systems_from_glob(glob)]
            else:
                placement = system_from_rom_directory(rom_directory)
                placements = [placement] if placement is not None else []
            for system, in_subfolder in placements:
                option = self._option_for(parser, in_subfolder, exe_by_script)
                existing = by_system.setdefault(system, [])
                if option is not None and all(o.label != option.label for o in existing):
                    existing.append(option)
        return _Catalogue(by_system=by_system, available=available)

    def _option_for(
        self, parser: dict[str, Any], in_subfolder: bool, exe_by_script: dict[str, str | None]
    ) -> EmulatorOption | None:
        label = option_label(str(parser.get("configTitle", "")))
        if not label:
            return None
        args_text = str(parser.get("executableArgs", ""))
        call = _LAUNCHER_CALL_RE.search(args_text)
        if call is None:
            return _unbakeable(label, "shortcut_script")
        script = call.group(1)
        if in_subfolder:
            # e.g. "ps4/shortcuts" (.lnk files) or "xbox360/xbla": a layout the
            # plugin's one-folder-per-system downloads never produce.
            return _unbakeable(label, "shortcut_script")
        if script.lower() == _VITA3K_SCRIPT:
            return self._vita3k_option(label, exe_by_script)
        try:
            tokens = split_powershell_args(resolve_srm_template(call.group(2)))
        except _TemplateError as exc:
            self._logger.debug("emudeck_windows: %r: %s", label, exc)
            return _unbakeable(label, "unknown_placeholder")
        if not tokens or tokens[-1] != _ROM_SENTINEL or any(_ROM_SENTINEL in t for t in tokens[:-1]):
            return _unbakeable(label, "no_rom_target")
        if any('"' in t for t in tokens):
            return _unbakeable(label, "quoting")

        if script not in exe_by_script:
            exe_by_script[script] = self._emulator_for_script(script)
        exe = exe_by_script[script]
        if exe is None:
            # EmuDeck only writes a launcher script for an emulator it installed.
            return EmulatorOption(
                label=label, kind="standalone", core_so=None, command="", status="needs_setup", reason="not_installed"
            )

        args = tokens[:-1]
        core_so = None
        if os.path.basename(exe).lower() == _RETROARCH_EXE and "-L" in args[:-1]:
            core_index = args.index("-L") + 1
            core_path = args[core_index].replace("\\", os.sep).replace("/", os.sep)
            if not os.path.isabs(core_path):
                core_path = os.path.join(os.path.dirname(exe), core_path)
            args[core_index] = os.path.normpath(core_path)
            base = os.path.basename(core_path)
            if base.lower().endswith(_CORE_SUFFIX):
                core_so = base[: -len(".dll")]
        kind = "libretro" if core_so else "standalone"
        command = " ".join([quote_windows_arg(exe, always=True), *(quote_windows_arg(a) for a in args)])

        installed = self._exists(exe) and (core_so is None or self._exists(args[args.index("-L") + 1]))
        return EmulatorOption(
            label=label,
            kind=kind,
            core_so=core_so,
            command=command,
            status="bakeable" if installed else "needs_setup",
            reason=None if installed else "not_installed",
        )

    def _vita3k_option(self, label: str, exe_by_script: dict[str, str | None]) -> EmulatorOption:
        """Vita3K runs an installed title by ID (``-r PCSE00000``), not by file.

        EmuDeck's own parser points at the installed ``eboot.bin`` folders; the
        library instead holds ES-DE-style ``.psvita`` files whose only content
        is the title ID. ``rom-launcher.exe`` reads that ID at launch when the
        command starts with ``--title-id-file`` and the ROM path comes last.
        """
        if _VITA3K_SCRIPT not in exe_by_script:
            exe_by_script[_VITA3K_SCRIPT] = self._emulator_for_script(_VITA3K_SCRIPT)
        exe = exe_by_script[_VITA3K_SCRIPT]
        if exe is None or not self._exists(exe):
            return EmulatorOption(
                label=label, kind="standalone", core_so=None, command="", status="needs_setup", reason="not_installed"
            )
        command = f"{_TITLE_ID_FLAG} {quote_windows_arg(exe, always=True)} -F -r"
        return EmulatorOption(label=label, kind="standalone", core_so=None, command=command, status="bakeable", reason=None)

    def _emulator_for_script(self, script: str) -> str | None:
        """The ``$emulatorFile`` a launcher script names, expanded, or ``None``."""
        # EmuDeck's parsers and file names disagree on case (`cemu.ps1` vs
        # `Cemu.ps1`); Windows does not care, but match explicitly so the
        # lookup behaves the same everywhere.
        wanted = f"{script}.ps1".lower()
        try:
            name = next((n for n in os.listdir(self._launchers_dir()) if n.lower() == wanted), f"{script}.ps1")
        except OSError:
            name = f"{script}.ps1"
        path = os.path.join(self._launchers_dir(), name)
        try:
            with open(path, encoding="utf-8-sig") as f:
                match = _EMULATOR_FILE_RE.search(f.read())
        except OSError:
            return None
        if match is None:
            return None
        return expand_launcher_path(match.group(1), self._appdata, self._user_profile)


def _unbakeable(label: str, reason: str) -> EmulatorOption:
    return EmulatorOption(label=label, kind="standalone", core_so=None, command="", status="unbakeable", reason=reason)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return -1.0


def _load_parsers(path: str, logger: logging.Logger) -> list[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("emudeck_windows: cannot read SRM parsers from %s: %s", path, exc)
        return []
    items = data if isinstance(data, list) else [data]
    return [item for item in items if isinstance(item, dict)]


class EmuDeckWindowsLauncherBackendFactory:
    """Detects EmuDeck for Windows from ``%APPDATA%\\EmuDeck\\settings.ps1`` and binds it."""

    backend_id = EMUDECK_BACKEND_ID
    display_name = _DISPLAY_NAME

    def __init__(
        self,
        *,
        user_home: str,
        resolve_system: Callable[[str, str | None], str],
        logger: logging.Logger,
        appdata: str | None = None,
    ) -> None:
        self._user_home = user_home
        self._appdata = appdata or os.environ.get("APPDATA") or os.path.join(user_home, "AppData", "Roaming")
        self._resolve_system = resolve_system
        self._logger = logger

    def _settings_path(self) -> str:
        return os.path.join(self._appdata, _SETTINGS_RELATIVE)

    def _installation_id(self) -> str:
        return f"{EMUDECK_BACKEND_ID}:{os.path.dirname(self._settings_path())}"

    def _read_settings(self) -> dict[str, str] | None:
        try:
            with open(self._settings_path(), encoding="utf-8-sig") as f:
                return parse_ps1_settings(f.read())
        except OSError:
            return None

    def detect_installations(self) -> list[DetectedInstallation]:
        settings = self._read_settings()
        if settings is None:
            return []
        backend = self._backend(settings)
        validation = backend.validate()
        return [
            DetectedInstallation(
                installation_id=self._installation_id(),
                display_name=_DISPLAY_NAME,
                home=settings.get("emulationPath", ""),
                healthy=validation.ok,
                detail="ok" if validation.ok else (validation.message or validation.reason or "unhealthy"),
            )
        ]

    def bind(self, installation_id: str) -> EmuDeckWindowsLauncherBackend | None:
        if installation_id != self._installation_id():
            return None
        settings = self._read_settings()
        return self._backend(settings) if settings is not None else None

    def _backend(self, settings: dict[str, str]) -> EmuDeckWindowsLauncherBackend:
        return EmuDeckWindowsLauncherBackend(
            installation_id=self._installation_id(),
            settings=settings,
            appdata=self._appdata,
            user_profile=os.environ.get("USERPROFILE") or self._user_home,
            resolve_system=self._resolve_system,
            logger=self._logger,
        )


class EmuDeckWindowsPathsAdapter:
    """``RetroDeckPaths`` for Windows, answered from EmuDeck's ``settings.ps1``.

    On Windows there is no RetroDECK, but several services still ask the
    RetroDECK-paths seam where BIOS, ROMs and saves live (firmware placement,
    the installed-ROM prune, the home-path migration check). Answering from
    EmuDeck keeps them pointed at ``C:\\Emulation\\...`` instead of a
    ``%USERPROFILE%\\retrodeck`` folder that never exists. Reads the file at
    most every 30 seconds; never raises.
    """

    _TTL_SECONDS = 30.0

    def __init__(self, *, user_home: str, logger: logging.Logger, appdata: str | None = None) -> None:
        self._user_home = user_home
        self._logger = logger
        self._appdata = appdata or os.environ.get("APPDATA") or os.path.join(user_home, "AppData", "Roaming")
        self._cached: dict[str, str] | None = None
        self._cached_at = 0.0
        self._readable = False

    def config_path(self) -> str:
        return os.path.join(self._appdata, _SETTINGS_RELATIVE)

    def _settings(self) -> dict[str, str]:
        now = time.monotonic()
        if self._cached is None or now - self._cached_at > self._TTL_SECONDS:
            try:
                with open(self.config_path(), encoding="utf-8-sig") as f:
                    self._cached = parse_ps1_settings(f.read())
                self._readable = True
            except OSError:
                self._cached = {}
                self._readable = False
            self._cached_at = now
        return self._cached

    def _get(self, key: str, fallback_subdir: str) -> str:
        value = self._settings().get(key, "")
        if value:
            return value
        home = self.retrodeck_home()
        return os.path.join(home, fallback_subdir) if home else ""

    def retrodeck_home(self) -> str:
        return self._settings().get("emulationPath", "")

    def roms_path(self) -> str:
        return self._get("romsPath", "roms")

    def bios_path(self) -> str:
        return self._get("biosPath", "bios")

    def saves_path(self) -> str:
        """RetroArch's save folder under EmuDeck's ``savesPath`` (see the launcher backend)."""
        base = self._get("savesPath", "saves")
        return os.path.join(base, "retroarch", "saves") if base else ""

    def states_path(self) -> str:
        base = self._get("savesPath", "saves")
        return os.path.join(base, "retroarch", "states") if base else ""

    def config_health(self) -> RetroDeckConfigHealth:
        self._settings()
        if not os.path.exists(self.config_path()):
            return RetroDeckConfigHealth.ABSENT
        if not self._readable:
            return RetroDeckConfigHealth.UNREADABLE
        if not os.path.isdir(self.retrodeck_home()):
            return RetroDeckConfigHealth.ROOT_MISSING
        return RetroDeckConfigHealth.OK
