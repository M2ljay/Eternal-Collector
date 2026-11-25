"""The plugin must import under Decky's frozen Windows Python.

Decky Loader's Windows build is a PyInstaller bundle that carries only the
standard-library modules Decky itself uses; ``decky_frozen_stdlib.txt`` lists
them (see its header for where the list comes from). A plugin module that
imports anything else at module level fails to load on Windows, and nothing on
Linux would notice. This test runs ``main.py`` in a fresh interpreter in which
every standard-library module missing from that list is hidden (as absent, so
``importlib.util.find_spec`` answers ``None`` the way the frozen runtime does), while the
plugin's own fallbacks (``_vendor/stdlib_compat``, found outside the stdlib
folders) still resolve, then imports every Windows-only module the plugin loads
lazily so their module-level imports are held to the same list.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LISTING = os.path.join(HERE, "decky_frozen_stdlib.txt")

# Imported by the plugin only on Windows (behind ``sys.platform == "win32"`` or a
# lazy import), so a plain ``import main`` on Linux never reaches them.
WINDOWS_ONLY_MODULES = (
    "adapters.game_process_windows",
    "adapters.descriptor_paths_windows",
    "adapters.emudeck_windows_launcher_backend",
    "adapters.install_files",
    "domain.install_manifest",
    "services.install_integrity",
    "core_bootstrap",
)

# POSIX-only extension modules. The Windows list cannot contain them, and the
# plugin imports them only on its non-Windows branches, so on the Linux machine
# this test runs on they must stay importable for main.py to get that far.
POSIX_ONLY = ("fcntl", "termios", "pwd", "grp", "resource", "_posixsubprocess", "posix", "_posixshmem")

CHILD = textwrap.dedent(r'''
    import importlib.machinery, os, sys, sysconfig, types
    root, listing, posix_only, extra = sys.argv[1], sys.argv[2], sys.argv[3].split(","), sys.argv[4].split(",")
    with open(listing, encoding="utf-8") as f:
        have = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    # Registered at import time rather than shipped as files (collections
    # aliases _collections_abc into sys.modules).
    have |= {"collections.abc"} | set(posix_only)
    std = set(sys.stdlib_module_names)
    stdlib_dirs = tuple(os.path.realpath(sysconfig.get_path(k)) + os.sep for k in ("stdlib", "platstdlib"))

    def hidden(name):
        return (name.split(".")[0] in std and name not in have and name not in sys.builtin_module_names
                and not name.startswith("encodings"))

    def in_stdlib(entry):
        real = os.path.realpath(entry) + os.sep
        return real.startswith(stdlib_dirs) and os.sep + "site-packages" + os.sep not in real

    def imported_by_stdlib():
        # Which modules the stdlib itself imports differs between the 3.14 the
        # list was read from and the interpreter running this test (3.13's lzma
        # imports _compression, 3.14's compression._common), so only an import
        # made by code outside the stdlib is held to the list.
        frame = sys._getframe(2)
        while frame is not None and frame.f_code.co_filename.startswith("<frozen"):
            frame = frame.f_back
        return frame is not None and in_stdlib(frame.f_code.co_filename)

    class FrozenPathFinder:
        """sys.meta_path's PathFinder, minus the stdlib folders for every module Decky lacks.

        Replacing the PathFinder (rather than raising from a finder ahead of it)
        keeps ``importlib.util.find_spec`` answering ``None`` for a missing
        module, which is what main.py's fallback guard asks.
        """
        def find_spec(self, name, path=None, target=None):
            if hidden(name) and not imported_by_stdlib():
                path = [p for p in (sys.path if path is None else path) if not in_stdlib(p)]
            return importlib.machinery.PathFinder.find_spec(name, path, target)

        def invalidate_caches(self):
            importlib.machinery.PathFinder.invalidate_caches()

    for name in list(sys.modules):
        if hidden(name):
            sys.modules.pop(name, None)
    sys.meta_path[:] = [FrozenPathFinder() if f is importlib.machinery.PathFinder else f for f in sys.meta_path]

    decky = types.ModuleType("decky")
    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None
    decky.logger = _Log()
    for attr in ("DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR", "DECKY_PLUGIN_DIR",
                 "DECKY_HOME", "DECKY_USER_HOME", "DECKY_PLUGIN_NAME", "DECKY_PLUGIN_VERSION", "DECKY_USER"):
        setattr(decky, attr, os.path.join(root, ".frozen-sim", attr))
    async def emit(*a, **k):
        return None
    decky.emit = emit
    sys.modules["decky"] = decky
    sys.modules["decky_plugin"] = decky

    import importlib.util
    spec = importlib.util.spec_from_file_location("frozen_main", os.path.join(root, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.CORE_IMPORT_ERROR is None, mod.CORE_IMPORT_ERROR
    assert mod.FULL_IMPORT_ERROR is None, mod.FULL_IMPORT_ERROR
    for name in extra:
        importlib.import_module(name)
    # The modules main.py's fallback path exists for must have come from the plugin, not the stdlib.
    import tomllib
    assert os.sep + "stdlib_compat" + os.sep in tomllib.__file__, tomllib.__file__
    print("frozen import OK")
''')


# Runs the script passed as argv[5] with the fixture plugin's py_modules importable.
_BOOT_FROM_ARGV = "import sys; sys.path.insert(0, sys.argv[1] + '/py_modules'); exec(sys.argv.pop(5))"


def _run_child(root: str, extra: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", CHILD, root, LISTING, ",".join(POSIX_ONLY), ",".join(extra)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_listing_is_readable_and_names_the_modules_main_py_checks():
    with open(LISTING, encoding="utf-8") as f:
        names = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    assert len(names) > 500
    # main.py's fallback guard asks for these two; the list is what says which is missing.
    assert "glob" in names
    assert "tomllib" not in names


def test_main_imports_with_only_deckys_stdlib():
    result = _run_child(ROOT, WINDOWS_ONLY_MODULES)
    assert result.returncode == 0, result.stderr[-4000:]
    assert "frozen import OK" in result.stdout


def test_a_module_outside_the_list_is_reported(tmp_path):
    """Non-vacuous: a plugin module importing a stdlib module Decky lacks makes the child fail."""
    plugin = tmp_path / "plugin"
    (plugin / "py_modules").mkdir(parents=True)
    (plugin / "main.py").write_text("CORE_IMPORT_ERROR = FULL_IMPORT_ERROR = None\n", encoding="utf-8")
    (plugin / "py_modules" / "needs_tkinter.py").write_text("import tkinter\n", encoding="utf-8")
    script = CHILD.replace("import tomllib\n", "").replace(
        'assert os.sep + "stdlib_compat" + os.sep in tomllib.__file__, tomllib.__file__\n', ""
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _BOOT_FROM_ARGV,
            str(plugin),
            LISTING,
            ",".join(POSIX_ONLY),
            "needs_tkinter",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "No module named 'tkinter'" in result.stderr
