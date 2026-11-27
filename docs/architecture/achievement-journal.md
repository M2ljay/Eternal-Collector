# Achievement Journal: Goals, Notes and the Unlock Timeline

The achievement journal is the user's own layer on top of RetroAchievements: achievements pinned as **goals**, free-text
**notes** per game, link-outs to RetroAchievements' achievement and guide pages, and an **unlock timeline** across
games. The user-facing side is in [Achievements: goals, notes and timeline](../user-guide/achievements.md).

## What is stored, and where

Goals and notes are the `RaGameJournal` aggregate (`domain/ra_game_journal.py`), persisted by migration `029` in two
tables ([Database Design](database-design.md#the-aggregate-set)): `ra_game_journals` (title, notes) and
`ra_achievement_goals` (one row per pinned achievement). `SqliteRaGameJournalRepository` saves a journal whole: it
UPSERTs the parent row and replaces the goal rows in the same transaction.

**Keyed by the RetroAchievements game id, not by a ROM.** Every version of a game shares one achievement set, so the
journal is shared by all of them (`roms.ra_id`). And the journal is writing that exists nowhere else: keying it on a
`rom_id` with the usual `ON DELETE CASCADE` would let a deliberate purge of a ROM row
([Removed-game cleanup](removed-game-cleanup.md)) delete it. So `ra_game_journals` has no foreign key onto `roms`; a
journal outlives every ROM that points at its game, and comes back when the game is synced again. A journal with no
notes and no goals is deleted rather than kept empty.

A goal keeps the achievement's title, description and points as they were when pinned, so the cross-game list on the QAM
reads without a network request. An unlock only moves forward: once a goal is unlocked it stays unlocked, and a softcore
unlock can later be upgraded to hardcore, never the other way.

Limits: notes up to 4,000 characters (refused whole, never cut), 100 goals per game.

## Where unlocks come from

A goal is ticked off from whichever of these sees the unlock first:

1. **RomM's progress data** (no Web API key needed). The achievements tab already reads the game's list and the user's
   earned achievements from RomM (`get_achievements`, `get_achievement_progress`). RomM reports an earned achievement by
   its badge id; the list carries both the badge id and the achievement id, so the tab maps one to the other
   (`src/utils/achievementJournal.ts`), shows goals ticked at once, and relays the unlocks the journal has not recorded
   yet with `record_achievement_goal_unlocks`. That is how the QAM list learns about them without the Web API.
2. **The unlock timeline** (Web API). Every timeline fetch ticks off any pinned goal it contains.
3. **Check goals** (Web API). `refresh_achievement_goals` asks `API_GetGameInfoAndUserProgress` for each game with an
   open goal, at most ten games per press, so one press never turns into a burst of requests. A refused key stops the
   whole check; other per-game failures are counted and skipped.

## The RetroAchievements Web API key

The timeline, the goal check and the game guide link use RetroAchievements' Web API
(`https://retroachievements.org/API/`), which needs a Web API key. The key is the one the user copies from their own
RetroAchievements settings page into The Collector's settings (**Settings → The Collector → RetroAchievements Web
API**), together with their RetroAchievements username. It is never an emulator's RetroAchievements login: nothing in
the journal holds a `RetroAchievementsConfigReader`, and the emulator credential rule in the invariant register is
unchanged.

How the key is handled:

- **Stored** in `settings.json` (`ra_web_username`, `ra_web_api_key`) through `SettingsPersister`, the settings owner.
  `AchievementJournalService.save_web_api` validates the shape first (username `[A-Za-z0-9_.-]{2,40}`, key
  `[A-Za-z0-9]{16,64}`); the mask `"••••"` means "keep the stored key". **Verify** (`verify_ra_web_api`) reads the
  user's profile with the candidate key before the settings page saves it.
- **Reported masked.** `get_settings` returns `ra_web_api_key_masked` (`"••••"` or `""`), never the key. The service
  itself only tests the key for presence.
- **Read and sent in one place.** `adapters/retroachievements_web.py` reads the key from settings at request time and
  sends it only as the `y` query parameter of a request to `https://retroachievements.org/API/`. Redirects are refused
  (a redirect would forward the query string, key included, to wherever it points). Every failure becomes a
  `RaWebApiError` whose message never carries the URL, and the original exception is not chained, so a traceback cannot
  leak it either. Nothing logs the key.

Failures map to the canonical failure shape (`domain/ra_web.web_api_failure`): 401/403 `auth_failed`, 404 `not_found`
(unknown username), 429 `rate_limited`, anything else `server_unreachable`. Without a key, the timeline and the goal
check answer `no_web_api_key` and the UI shows one line saying where to add it.

## The unlock timeline

`get_unlock_timeline(days, force)` reads `API_GetAchievementsEarnedBetween` for the last 30, 90 or 365 days and reduces
it (`domain/ra_web.parse_timeline`) to entries with the date (UTC, as RetroAchievements reports it), game, console,
achievement, points and hardcore flag, newest first. An achievement unlocked both ways appears once, as its hardcore
unlock. Badge images point at `media.retroachievements.org`, never at the RomM server. Answers are cached for ten
minutes per window; **Refresh** forces a new read, and saving or removing the key drops the cache. Filtering by game and
console happens in the QAM page over the fetched window.

## Links and guides

Each achievement's menu opens its public page (`https://retroachievements.org/achievement/<id>`), where players' tips
live. The Notes view links the game's page and, with the Web API, the guide RetroAchievements lists for the game
(`GuideURL`). A link opens in Steam's browser (`Navigation.NavigateToExternalWeb`) only when it is https on
RetroAchievements' own sites or in the RetroAchievements organisation on GitHub, checked both in the backend
(`domain/ra_web.safe_guide_url`) and before opening (`isRetroAchievementsUrl`). Nothing is fetched or scraped from a
guide site.

## UI

- **Achievements tab** (game page): a view bar — **All** (the list; A on a row opens Pin as goal / Remove goal / Open
  guide on RetroAchievements, and pinned rows carry a crimson GOAL chip), **Goals** (done/total, ticked rows in green)
  and **Notes** (edited in a modal with Steam's on-screen keyboard). The journal loads even when RomM is offline.
- **QAM main page**: up to three open goals and a button to the **Achievements** page, plus an Achievements entry in the
  navigation buttons. The section reads only the local journal.
- **QAM Achievements page**: every goal (open first), **Check goals on RetroAchievements**, and the unlock timeline with
  Period, Game and Console dropdowns.

All of it uses the Core palette (`src/theme/coreTokens.ts`) and plain `@decky/ui` components (DialogButton, Field,
DropdownItem, showContextMenu, ConfirmModal), so it needs nothing from the Decky 3/4 class-module lookups.

## Credits

The feature set takes ideas from two BSD-3-licensed Decky plugins, CheevoDeck and Achievement Companion. No code was
copied from either.

## Key files

| File                                                    | Role                                                     |
| ------------------------------------------------------- | -------------------------------------------------------- |
| `py_modules/domain/ra_game_journal.py`                  | The `RaGameJournal` aggregate and `AchievementGoal`      |
| `py_modules/domain/ra_web.py`                           | Links, guide allow-list, dates, Web API answer shapes    |
| `py_modules/adapters/retroachievements_web.py`          | The only reader and sender of the Web API key            |
| `py_modules/adapters/repositories/ra_game_journal.py`   | SQLite repository                                        |
| `py_modules/db/migrations/029_add_ra_game_journals.sql` | The two tables                                           |
| `py_modules/services/achievement_journal.py`            | `AchievementJournalService`: callables, caches, settings |
| `src/components/AchievementsTab.tsx`, `achievements/`   | Game-page views, menus, notes modal, QAM goals section   |
| `src/components/AchievementsPage.tsx`                   | QAM goals list and unlock timeline                       |
| `src/components/settings/RaWebApiModal.tsx`             | Username and key entry, verified before saving           |
| `src/utils/achievementJournal.ts`                       | Badge-to-achievement mapping, filters, link-out          |
