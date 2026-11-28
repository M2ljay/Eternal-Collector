"""Tests for ``domain.ra_web`` — RetroAchievements links, dates and Web API answer shapes."""

from __future__ import annotations

import pytest

from domain.ra_web import (
    achievement_page_url,
    game_page_url,
    normalize_ra_date,
    parse_game_progress,
    parse_timeline,
    public_badge_url,
    safe_guide_url,
    web_api_failure,
)


class TestLinks:
    def test_page_urls(self):
        assert achievement_page_url(175333) == "https://retroachievements.org/achievement/175333"
        assert game_page_url(3164) == "https://retroachievements.org/game/3164"

    @pytest.mark.parametrize(
        "url",
        [
            "https://retroachievements.org/game/1/guide",
            "https://docs.retroachievements.org/guidelines/",
            "https://github.com/RetroAchievements/guides/wiki/Sonic-the-Hedgehog",
        ],
    )
    def test_accepts_retroachievements_guides(self, url):
        assert safe_guide_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            42,
            "http://retroachievements.org/game/1",
            "https://gamefaqs.gamespot.com/guide",
            "https://github.com/someone/guides",
            "https://retroachievements.org.evil.example/x",
            "https://user:pw@retroachievements.org/x",
            "https://retroachievements.org:8443/x",
            "https://retroachievements.org:notaport/x",
            "javascript:alert(1)",
        ],
    )
    def test_refuses_anything_else(self, url):
        assert safe_guide_url(url) is None


class TestDates:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2022-01-01 22:41:48", "2022-01-01T22:41:48Z"),
            ("2022-01-01T22:41:48Z", "2022-01-01T22:41:48Z"),
            ("2024-04-23T21:28:49+00:00", "2024-04-23T21:28:49Z"),
            ("2024-04-23T23:28:49+02:00", "2024-04-23T21:28:49Z"),
        ],
    )
    def test_normalizes_to_utc(self, raw, expected):
        assert normalize_ra_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "  ", "yesterday", 1641054603, "2022-13-01 00:00:00"])
    def test_rejects_garbage(self, raw):
        assert normalize_ra_date(raw) is None


def _entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "Date": "2022-01-01 22:41:48",
        "HardcoreMode": 1,
        "AchievementID": 175333,
        "Title": "Solo Adventurer",
        "Description": "Solo defeat Golden Beetles",
        "Points": 10,
        "GameTitle": "Persona 3 Portable",
        "GameID": 3164,
        "ConsoleName": "PlayStation Portable",
        "BadgeURL": "/Badge/228985.png",
    }
    entry.update(overrides)
    return entry


class TestTimeline:
    def test_parses_pascal_case(self):
        [entry] = parse_timeline([_entry()])
        assert entry.to_wire() == {
            "unlocked_at": "2022-01-01T22:41:48Z",
            "achievement_id": 175333,
            "title": "Solo Adventurer",
            "description": "Solo defeat Golden Beetles",
            "points": 10,
            "hardcore": True,
            "game_id": 3164,
            "game_title": "Persona 3 Portable",
            "console_name": "PlayStation Portable",
            "badge_url": "https://media.retroachievements.org/Badge/228985.png",
        }

    def test_parses_camel_case(self):
        [entry] = parse_timeline(
            [
                {
                    "date": "2022-01-01 22:41:48",
                    "hardcoreMode": False,
                    "achievementId": 5,
                    "title": "A",
                    "gameId": 9,
                    "gameTitle": "G",
                    "consoleName": "C",
                    "points": 3,
                }
            ]
        )
        assert (entry.achievement_id, entry.game_id, entry.hardcore, entry.points) == (5, 9, False, 3)
        assert entry.badge_url == ""

    def test_newest_first_and_drops_incomplete_entries(self):
        entries = parse_timeline(
            [
                _entry(AchievementID=1, Date="2022-01-01 10:00:00"),
                _entry(AchievementID=2, Date="2022-01-03 10:00:00"),
                _entry(AchievementID=3, Date=None),
                _entry(AchievementID=None),
                _entry(AchievementID=4, GameID=0),
                _entry(AchievementID=5, Title=""),
                "not a dict",
            ]
        )
        assert [e.achievement_id for e in entries] == [2, 1]

    def test_one_entry_per_achievement_preferring_hardcore(self):
        entries = parse_timeline(
            [
                _entry(HardcoreMode=0, Date="2022-01-01 10:00:00"),
                _entry(HardcoreMode=1, Date="2022-01-02 10:00:00"),
            ]
        )
        assert len(entries) == 1
        assert entries[0].hardcore is True

    def test_off_site_badge_paths_are_dropped(self):
        [entry] = parse_timeline([_entry(BadgeURL="//evil.example/x.png")])
        assert entry.badge_url == ""

    @pytest.mark.parametrize("payload", [None, {}, "x", 5])
    def test_non_list_is_empty(self, payload):
        assert parse_timeline(payload) == []


class TestGameProgress:
    def test_prefers_hardcore_and_skips_locked(self):
        progress = parse_game_progress(
            {
                "GuideURL": "https://github.com/RetroAchievements/guides/wiki/Sonic",
                "Achievements": {
                    "2": {"ID": 2, "DateEarned": "2022-01-01 10:00:00"},
                    "1": {
                        "ID": 1,
                        "DateEarned": "2022-01-01 09:00:00",
                        "DateEarnedHardcore": "2022-01-01 09:00:00",
                    },
                    "3": {"ID": 3},
                    "x": "bad",
                },
            }
        )
        assert [(u.achievement_id, u.hardcore) for u in progress.unlocks] == [(1, True), (2, False)]
        assert progress.guide_url == "https://github.com/RetroAchievements/guides/wiki/Sonic"

    def test_unsafe_guide_and_bad_payload(self):
        assert parse_game_progress({"GuideURL": "https://example.com/g", "Achievements": []}).guide_url is None
        assert parse_game_progress(None).unlocks == ()


class TestFailure:
    @pytest.mark.parametrize(
        ("status", "reason"),
        [
            (401, "auth_failed"),
            (403, "auth_failed"),
            (404, "not_found"),
            (429, "rate_limited"),
            (500, "server_unreachable"),
            (None, "server_unreachable"),
        ],
    )
    def test_maps_status(self, status, reason):
        assert web_api_failure(status)[0] == reason


class TestPublicBadgeUrl:
    def test_accepts_a_plain_media_url(self):
        url = "https://media.retroachievements.org/Badge/250336.png"
        assert public_badge_url(url) == url

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            None,
            42,
            "http://media.retroachievements.org/Badge/1.png",
            "https://retroachievements.org/Badge/1.png",
            "https://media.retroachievements.org.evil.example/Badge/1.png",
            "https://media.retroachievements.org/Badge/1.png?y=AbCdEf0123456789",
            "https://media.retroachievements.org/Badge/1.png#frag",
            "https://user:pw@media.retroachievements.org/Badge/1.png",
            "https://media.retroachievements.org:8443/Badge/1.png",
            "https://[bad/Badge/1.png",
        ],
    )
    def test_refuses_anything_else(self, raw):
        assert public_badge_url(raw) is None
