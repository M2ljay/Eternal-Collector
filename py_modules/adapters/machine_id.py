"""Machine-id adapter — concrete ``MachineIdReader`` Protocol implementation.

Reads the operating system's stable machine identity so services can supply a
machine-derived device identity to RomM device registration without touching
the filesystem directly: ``/etc/machine-id`` on Linux, and the ``MachineGuid``
value Windows keeps under ``HKLM\\SOFTWARE\\Microsoft\\Cryptography`` on
Windows. There is one source per platform and no fallback chain, so an
unreadable or empty value degrades to ``None`` and the caller falls back to
no-fingerprint registration.
"""

from __future__ import annotations

import sys

_MACHINE_ID_PATH = "/etc/machine-id"
_WINDOWS_CRYPTOGRAPHY_KEY = r"SOFTWARE\Microsoft\Cryptography"


class MachineIdAdapter:
    """Real ``MachineIdReader`` backed by ``/etc/machine-id`` or the Windows ``MachineGuid``."""

    def get(self) -> str | None:
        """Return the stripped machine id, or ``None`` when unreadable.

        Returns ``None`` on a missing file or registry value, empty or
        whitespace-only content, or any ``OSError`` so registration can
        degrade to no-fingerprint behaviour rather than sending an empty or
        invalid identity.
        """
        if sys.platform == "win32":
            return _read_windows_machine_guid()
        try:
            with open(_MACHINE_ID_PATH, encoding="utf-8") as f:
                machine_id = f.read().strip()
        except OSError:
            return None
        return machine_id or None


def _read_windows_machine_guid() -> str | None:
    """Read ``MachineGuid`` from the 64-bit registry view.

    Decky's bundled Python is 64-bit, but ``KEY_WOW64_64KEY`` is passed
    explicitly so a 32-bit interpreter would read the same value rather than
    the redirected (and usually absent) WOW6432Node copy.
    """
    try:
        import winreg

        access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WINDOWS_CRYPTOGRAPHY_KEY, 0, access) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    # /etc/machine-id is 32 lowercase hex characters; normalize the GUID to the
    # same shape so the server sees one identity format from every client.
    machine_id = value.strip().replace("-", "").lower()
    return machine_id or None
