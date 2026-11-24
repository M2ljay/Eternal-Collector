"""HTTPS client for the plugin's own release channel (``PluginReleaseSource``)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import ssl
import urllib.error
import urllib.request

from lib.certifi_bundle import ca_bundle as _ca_bundle
from lib.errors import PluginReleaseFetchError

_TIMEOUT_SECONDS = 30
_CHUNK = 64 * 1024


class PluginReleaseHttpAdapter:
    """Real ``PluginReleaseSource`` over ``urllib`` with the plugin's User-Agent.

    Parameters
    ----------
    user_agent:
        Outgoing ``User-Agent`` (``romm-dock/<version>``), as every HTTP-talking
        adapter sends.
    """

    def __init__(self, *, user_agent: str) -> None:
        self._user_agent = user_agent

    def _open(self, url: str):
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", self._user_agent)
        req.add_header("Cache-Control", "no-cache")
        ctx = ssl.create_default_context(cafile=_ca_bundle())
        try:
            return urllib.request.urlopen(req, context=ctx, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as e:
            raise PluginReleaseFetchError(f"HTTP {e.code} from the release channel") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise PluginReleaseFetchError(f"Could not reach the release channel: {e}") from e

    def fetch_manifest(self, url: str, max_bytes: int) -> bytes:
        with self._open(url) as resp:
            try:
                body = resp.read(max_bytes + 1)
            except OSError as e:
                raise PluginReleaseFetchError(f"Reading the release channel failed: {e}") from e
        if len(body) > max_bytes:
            raise PluginReleaseFetchError("The release channel answered with an oversized update.json")
        return body

    def download(self, url: str, dest_path: str, max_bytes: int) -> tuple[int, str]:
        tmp_path = dest_path + ".part"
        digest = hashlib.sha256()
        written = 0
        try:
            with self._open(url) as resp, open(tmp_path, "wb") as f:
                while written <= max_bytes:
                    chunk = resp.read(min(_CHUNK, max_bytes + 1 - written))
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
            os.replace(tmp_path, dest_path)
        except PluginReleaseFetchError:
            self._discard(tmp_path)
            raise
        except OSError as e:
            self._discard(tmp_path)
            raise PluginReleaseFetchError(f"Downloading the update failed: {e}") from e
        return written, digest.hexdigest()

    @staticmethod
    def _discard(path: str) -> None:
        with contextlib.suppress(OSError):
            os.remove(path)
