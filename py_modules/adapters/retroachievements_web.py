"""RetroAchievements Web API adapter — every request The Collector makes to retroachievements.org.

The Web API key is the one the user stored in The Collector's own settings
(``ra_web_api_key``) for this purpose; an emulator's RetroAchievements login is
never read. The key is read here at request time, travels only as the ``y`` query
parameter of a request to ``https://retroachievements.org/API/``, and never appears
in a log line, an exception message or a return value. Redirects are refused, so
the query string carrying the key cannot be forwarded to another host.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Final

from lib.certifi_bundle import ca_bundle as _ca_bundle
from lib.errors import RaWebApiError

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from urllib.request import Request

API_BASE: Final = "https://retroachievements.org/API/"
SETTINGS_KEY: Final = "ra_web_api_key"
_TIMEOUT_SECONDS: Final = 20


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an error instead of following it with the key attached."""

    def redirect_request(
        self,
        req: Request,  # noqa: ARG002
        fp: Any,  # noqa: ARG002
        code: int,  # noqa: ARG002
        msg: str,  # noqa: ARG002
        headers: HTTPMessage,  # noqa: ARG002
        newurl: str,  # noqa: ARG002
    ) -> Request | None:
        return None


class RetroAchievementsWebAdapter:
    """Concrete RetroAchievements Web API client.

    Parameters
    ----------
    settings:
        Shared settings dict (held by reference). Source of the Web API key.
    user_agent:
        Outgoing ``User-Agent`` header value (``"romm-dock/<version>"``).
    """

    def __init__(self, *, settings: dict[str, Any], user_agent: str) -> None:
        self._settings = settings
        self._user_agent = user_agent
        context = ssl.create_default_context(cafile=_ca_bundle())
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            _RefuseRedirects(),
        )

    def _stored_key(self) -> str:
        key = self._settings.get(SETTINGS_KEY, "")
        if not isinstance(key, str) or not key:
            raise RaWebApiError(None, "No RetroAchievements Web API key is configured")
        return key

    def _get(self, endpoint: str, params: dict[str, str], api_key: str) -> Any:
        query = urllib.parse.urlencode({**params, "y": api_key})
        request = urllib.request.Request(f"{API_BASE}{endpoint}?{query}", method="GET")
        request.add_header("User-Agent", self._user_agent)
        request.add_header("Accept", "application/json")
        try:
            with self._opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                body = response.read()
        except urllib.error.HTTPError as e:
            raise RaWebApiError(e.code, f"RetroAchievements answered HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise RaWebApiError(None, "RetroAchievements could not be reached") from None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RaWebApiError(None, "RetroAchievements sent an answer that could not be read") from None

    def get_achievements_earned_between(self, username: str, from_epoch: int, to_epoch: int) -> Any:
        """The raw ``API_GetAchievementsEarnedBetween`` answer for *username* in the window."""
        return self._get(
            "API_GetAchievementsEarnedBetween.php",
            {"u": username, "f": str(int(from_epoch)), "t": str(int(to_epoch))},
            self._stored_key(),
        )

    def get_game_info_and_user_progress(self, username: str, game_id: int) -> Any:
        """The raw ``API_GetGameInfoAndUserProgress`` answer for *username* in *game_id*."""
        return self._get(
            "API_GetGameInfoAndUserProgress.php",
            {"u": username, "g": str(int(game_id))},
            self._stored_key(),
        )

    def verify_credentials(self, username: str, api_key: str) -> None:
        """Read *username*'s profile with *api_key*; raises ``RaWebApiError`` when that fails."""
        answer = self._get("API_GetUserProfile.php", {"u": username}, api_key)
        if not isinstance(answer, dict) or not answer:
            raise RaWebApiError(None, "RetroAchievements has no profile for that username")
