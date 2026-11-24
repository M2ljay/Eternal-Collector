"""Game-process adapter for Windows — ``GameProcessControl`` over the Win32 API.

The Windows counterpart of ``adapters.game_process``. On Windows every RomM
shortcut runs ``bin\\rom-launcher.exe``, which starts the emulator as its child
and waits for it, so a game "instance" is one ``rom-launcher.exe`` process and
the tree beneath it. The launcher itself is never a signal target: it holds the
Job Object that force-closes the emulator when the launcher ends, so stopping
it first would kill the emulator mid-save. It exits on its own once the
emulator has.

What "ask to exit" means here: Windows has no SIGTERM. The polite request is a
``WM_CLOSE`` posted to the process's visible top-level windows — exactly what
clicking the window's close button sends, and what RetroArch, Dolphin, PCSX2,
DuckStation and the rest handle by saving and quitting. A process with no such
window is reported as "not requested" (False) so the ladder never force-kills
something it never asked to close.

ctypes only, against kernel32, user32, ntdll and shell32; every call is guarded
and fail-soft. Process identity is checked against creation time when walking
parent links, because Windows reuses pids and a parent pid can outlive its
parent.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from domain.game_instance import GameInstance

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_WM_CLOSE = 0x0010
_GW_OWNER = 4
_PROCESS_COMMAND_LINE_INFORMATION = 60
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_DEPTH = 16


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class _Win32:
    """The handful of Win32 entry points this adapter uses, with signatures set."""

    def __init__(self) -> None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        n = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
        s = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined]
        h, b, d = wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD

        def sig(fn, res, *args):
            fn.restype, fn.argtypes = res, list(args)
            return fn

        self.CreateToolhelp32Snapshot = sig(k.CreateToolhelp32Snapshot, h, d, d)
        self.Process32FirstW = sig(k.Process32FirstW, b, h, ctypes.POINTER(_PROCESSENTRY32W))
        self.Process32NextW = sig(k.Process32NextW, b, h, ctypes.POINTER(_PROCESSENTRY32W))
        self.OpenProcess = sig(k.OpenProcess, h, d, b, d)
        self.CloseHandle = sig(k.CloseHandle, b, h)
        self.TerminateProcess = sig(k.TerminateProcess, b, h, ctypes.c_uint)
        self.WaitForSingleObject = sig(k.WaitForSingleObject, d, h, d)
        self.GetProcessTimes = sig(
            k.GetProcessTimes,
            b,
            h,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        self.LocalFree = sig(k.LocalFree, ctypes.c_void_p, ctypes.c_void_p)
        self.NtQueryInformationProcess = sig(
            n.NtQueryInformationProcess,
            ctypes.c_ulong,
            h,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        )
        self.CommandLineToArgvW = sig(
            s.CommandLineToArgvW, ctypes.POINTER(ctypes.c_wchar_p), wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)
        )
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(b, wintypes.HWND, wintypes.LPARAM)  # type: ignore[attr-defined]
        self.EnumWindows = sig(u.EnumWindows, b, self.WNDENUMPROC, wintypes.LPARAM)
        self.GetWindowThreadProcessId = sig(u.GetWindowThreadProcessId, d, wintypes.HWND, ctypes.POINTER(d))
        self.IsWindowVisible = sig(u.IsWindowVisible, b, wintypes.HWND)
        self.GetWindow = sig(u.GetWindow, wintypes.HWND, wintypes.HWND, ctypes.c_uint)
        self.PostMessageW = sig(u.PostMessageW, b, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)


class WindowsGameProcessAdapter:
    """Real ``GameProcessControl`` for Windows: rom-launcher.exe trees, WM_CLOSE, TerminateProcess.

    ``find_game_instances`` takes the launcher's exe name (``rom-launcher.exe``)
    where the Linux adapter takes a flatpak app id; the service passes whichever
    the platform's wiring configured.
    """

    def __init__(self, win32: _Win32 | None = None) -> None:
        self._win32 = win32

    @property
    def _w(self) -> _Win32:
        # Bound on first use, not at plugin startup: a Win32 lookup failure
        # then fails one Stop Game press instead of the whole plugin load.
        if self._win32 is None:
            self._win32 = _Win32()
        return self._win32

    # ── GameProcessControl ────────────────────────────────────────────────

    def find_game_instances(self, flatpak_app_id: str) -> list[GameInstance]:
        launcher_name = flatpak_app_id.lower()
        table = self._process_table()
        children: dict[int, list[int]] = {}
        for pid, (parent, _name) in table.items():
            children.setdefault(parent, []).append(pid)

        instances: list[GameInstance] = []
        for pid, (_parent, name) in table.items():
            if name.lower() != launcher_name:
                continue
            pids = self._descendants(pid, children)
            if not pids:
                continue
            argv = [t for p in (pid, *pids) for t in self._cmdline_tokens(p)]
            instances.append(GameInstance(pids=tuple(pids), argv=tuple(argv)))
        return instances

    def request_stop(self, pid: int) -> bool:
        """Post one WM_CLOSE to each visible top-level window *pid* owns.

        True when at least one window received it. False when the process has
        no such window — nothing was asked, so the ladder must not force it.
        """
        targets: list[int] = []
        w = self._w

        def collect(hwnd, _lparam):
            owner = wintypes.DWORD(0)
            w.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and w.IsWindowVisible(hwnd) and not w.GetWindow(hwnd, _GW_OWNER):
                targets.append(hwnd)
            return True

        try:
            w.EnumWindows(w.WNDENUMPROC(collect), 0)
        except OSError:
            return False
        return sum(1 for hwnd in targets if w.PostMessageW(hwnd, _WM_CLOSE, 0, 0)) > 0

    def force_kill(self, pid: int) -> bool:
        handle = self._w.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(self._w.TerminateProcess(handle, 1))
        finally:
            self._w.CloseHandle(handle)

    def is_alive(self, pid: int) -> bool:
        handle = self._w.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            return self._w.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            self._w.CloseHandle(handle)

    def running_executable_names(self) -> frozenset[str] | None:
        """Lower-cased executable names of every running process, or ``None`` when the table cannot be read."""
        try:
            table = self._process_table()
        except (OSError, AttributeError):
            return None
        return frozenset(name.lower() for _parent, name in table.values()) if table else None

    # ── process table ─────────────────────────────────────────────────────

    def _process_table(self) -> dict[int, tuple[int, str]]:
        """Return ``{pid: (parent_pid, exe_name)}`` for every process, or {} on failure."""
        w = self._w
        snap = w.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snap or snap == _INVALID_HANDLE_VALUE:
            return {}
        table: dict[int, tuple[int, str]] = {}
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = w.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
                ok = w.Process32NextW(snap, ctypes.byref(entry))
        finally:
            w.CloseHandle(snap)
        return table

    def _descendants(self, root: int, children: dict[int, list[int]]) -> list[int]:
        """*root*'s subtree, deepest level first, root excluded.

        A child is accepted only when it was created after its parent — a pid
        whose recorded parent pid has since been reused by an unrelated, newer
        process is not that process's child.
        """
        levels: list[list[int]] = []
        seen = {root}
        frontier = [root]
        for _ in range(_MAX_DEPTH):
            next_frontier: list[int] = []
            for parent in frontier:
                parent_born = self._creation_time(parent)
                for child in children.get(parent, []):
                    if child in seen:
                        continue
                    born = self._creation_time(child)
                    if parent_born is None or born is None or born < parent_born:
                        continue
                    seen.add(child)
                    next_frontier.append(child)
            if not next_frontier:
                break
            levels.append(next_frontier)
            frontier = next_frontier
        return [pid for level in reversed(levels) for pid in level]

    def _creation_time(self, pid: int) -> int | None:
        handle = self._w.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not self._w.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return None
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            self._w.CloseHandle(handle)

    def _cmdline_tokens(self, pid: int) -> list[str]:
        """*pid*'s argv as Windows parses it; [] when it cannot be read."""
        w = self._w
        handle = w.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return []
        try:
            needed = ctypes.c_ulong(0)
            status = w.NtQueryInformationProcess(
                handle, _PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(needed)
            )
            if status != _STATUS_INFO_LENGTH_MISMATCH or not needed.value:
                return []
            buf = ctypes.create_string_buffer(needed.value)
            status = w.NtQueryInformationProcess(
                handle, _PROCESS_COMMAND_LINE_INFORMATION, buf, needed.value, ctypes.byref(needed)
            )
            if status != 0:
                return []
            us = _UNICODE_STRING.from_buffer(buf)
            if not us.Buffer or not us.Length:
                return []
            cmdline = ctypes.wstring_at(us.Buffer, us.Length // 2)
        finally:
            w.CloseHandle(handle)
        return self._split(cmdline)

    def _split(self, cmdline: str) -> list[str]:
        argc = ctypes.c_int(0)
        argv = self._w.CommandLineToArgvW(cmdline, ctypes.byref(argc))
        if not argv:
            return []
        try:
            return [argv[i] for i in range(argc.value) if argv[i]]
        finally:
            self._w.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def is_supported() -> bool:
    """True on Windows, where this adapter can load."""
    return os.name == "nt"
