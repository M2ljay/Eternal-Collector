"""Tests for ``RetroAchievementsWebAdapter`` — where the Web API key goes, and where it never goes."""

from __future__ import annotations

import io
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from adapters.retroachievements_web import API_BASE, RetroAchievementsWebAdapter, _RefuseRedirects
from lib.errors import RaWebApiError

KEY = "AbCdEf0123456789AbCdEf0123456789"


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _FakeOpener:
    def __init__(self, body: bytes = b"[]", error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> _Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return _Response(self.body)


def _adapter(opener: _FakeOpener, key: str = KEY) -> RetroAchievementsWebAdapter:
    adapter = RetroAchievementsWebAdapter(settings={"ra_web_api_key": key}, user_agent="romm-dock/1.2.3")
    adapter._opener = opener  # type: ignore[assignment]
    return adapter


def _query(request: urllib.request.Request) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


class TestRequests:
    def test_earned_between_goes_to_retroachievements_with_the_stored_key(self):
        opener = _FakeOpener(body=json.dumps([{"AchievementID": 1}]).encode())
        answer = _adapter(opener).get_achievements_earned_between("Jamiras", 100, 200)

        assert answer == [{"AchievementID": 1}]
        [request] = opener.requests
        parts = urllib.parse.urlsplit(request.full_url)
        assert (parts.scheme, parts.hostname) == ("https", "retroachievements.org")
        assert request.full_url.startswith(API_BASE + "API_GetAchievementsEarnedBetween.php?")
        assert _query(request) == {"u": ["Jamiras"], "f": ["100"], "t": ["200"], "y": [KEY]}
        assert request.get_header("User-agent") == "romm-dock/1.2.3"

    def test_game_progress(self):
        opener = _FakeOpener(body=b'{"ID": 3}')
        assert _adapter(opener).get_game_info_and_user_progress("Jamiras", 3) == {"ID": 3}
        assert _query(opener.requests[0])["g"] == ["3"]

    def test_verify_uses_the_candidate_key_not_the_stored_one(self):
        opener = _FakeOpener(body=b'{"User": "Jamiras"}')
        _adapter(opener, key="StoredKey0123456789").verify_credentials("Jamiras", KEY)
        assert _query(opener.requests[0])["y"] == [KEY]

    def test_verify_refuses_an_empty_profile(self):
        with pytest.raises(RaWebApiError):
            _adapter(_FakeOpener(body=b"{}")).verify_credentials("Jamiras", KEY)

    def test_no_stored_key_sends_nothing(self):
        opener = _FakeOpener()
        with pytest.raises(RaWebApiError):
            _adapter(opener, key="").get_achievements_earned_between("Jamiras", 1, 2)
        assert opener.requests == []


class TestFailuresNeverCarryTheKey:
    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (urllib.error.HTTPError(f"{API_BASE}x?y={KEY}", 401, "Unauthorized", None, None), 401),  # type: ignore[arg-type]
            (urllib.error.URLError(f"failed for y={KEY}"), None),
            (TimeoutError(f"timed out y={KEY}"), None),
        ],
    )
    def test_transport_errors(self, error, status, caplog):
        caplog.set_level(logging.DEBUG)
        with pytest.raises(RaWebApiError) as info:
            _adapter(_FakeOpener(error=error)).get_achievements_earned_between("Jamiras", 1, 2)
        assert info.value.status_code == status
        assert KEY not in str(info.value)
        assert info.value.__cause__ is None
        assert KEY not in caplog.text

    def test_unreadable_answer(self):
        with pytest.raises(RaWebApiError) as info:
            _adapter(_FakeOpener(body=b"<html>")).get_achievements_earned_between("Jamiras", 1, 2)
        assert info.value.status_code is None


class _Redirecting(BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).hits.append(self.path)
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def test_redirects_are_refused_not_followed():
    server = HTTPServer(("127.0.0.1", 0), _Redirecting)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = urllib.request.build_opener(_RefuseRedirects())
        url = f"http://127.0.0.1:{server.server_address[1]}/API/x?y={KEY}"
        with pytest.raises(urllib.error.HTTPError) as info:
            opener.open(url, timeout=5)
        assert info.value.code == 302
        assert _Redirecting.hits == [f"/API/x?y={KEY}"]
    finally:
        server.shutdown()
        server.server_close()
