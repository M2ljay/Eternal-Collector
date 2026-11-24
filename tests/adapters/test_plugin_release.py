"""Tests for ``PluginReleaseHttpAdapter`` — the release channel's HTTPS client."""

from __future__ import annotations

import hashlib
import io
import urllib.error
from email.message import Message
from unittest.mock import patch

import pytest

from adapters.plugin_release import PluginReleaseHttpAdapter
from lib.errors import PluginReleaseFetchError


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def adapter():
    return PluginReleaseHttpAdapter(user_agent="romm-dock/0.33.0-win.17")


class TestFetchManifest:
    def test_sends_the_plugin_user_agent(self, adapter):
        with patch("urllib.request.urlopen", return_value=_Resp(b"{}")) as mock_open:
            assert adapter.fetch_manifest("https://example.invalid/update.json", 100) == b"{}"
        req = mock_open.call_args[0][0]
        assert req.get_header("User-agent") == "romm-dock/0.33.0-win.17"

    def test_oversized_body_is_an_error(self, adapter):
        with patch("urllib.request.urlopen", return_value=_Resp(b"x" * 11)), pytest.raises(PluginReleaseFetchError):
            adapter.fetch_manifest("https://example.invalid/update.json", 10)

    def test_http_error_is_wrapped(self, adapter):
        err = urllib.error.HTTPError("u", 404, "Not Found", Message(), None)
        with patch("urllib.request.urlopen", side_effect=err), pytest.raises(PluginReleaseFetchError, match="HTTP 404"):
            adapter.fetch_manifest("https://example.invalid/update.json", 100)

    def test_connection_error_is_wrapped(self, adapter):
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
            pytest.raises(PluginReleaseFetchError, match="Could not reach"),
        ):
            adapter.fetch_manifest("https://example.invalid/update.json", 100)


class TestDownload:
    def test_writes_and_hashes(self, adapter, tmp_path):
        body = b"zip bytes" * 1000
        dest = tmp_path / "r.zip"
        with patch("urllib.request.urlopen", return_value=_Resp(body)):
            size, sha = adapter.download("https://example.invalid/r.zip", str(dest), len(body))
        assert (size, sha) == (len(body), hashlib.sha256(body).hexdigest())
        assert dest.read_bytes() == body
        assert not (tmp_path / "r.zip.part").exists()

    def test_stops_one_byte_past_the_limit(self, adapter, tmp_path):
        dest = tmp_path / "r.zip"
        with patch("urllib.request.urlopen", return_value=_Resp(b"y" * 500)):
            size, _ = adapter.download("https://example.invalid/r.zip", str(dest), 100)
        assert size == 101

    def test_failure_leaves_no_partial_file(self, adapter, tmp_path):
        dest = tmp_path / "r.zip"
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("reset")),
            pytest.raises(PluginReleaseFetchError),
        ):
            adapter.download("https://example.invalid/r.zip", str(dest), 100)
        assert list(tmp_path.iterdir()) == []
