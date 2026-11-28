# The Collector: console pages (and the retired Home shelf)

The Collector adds a page per console to Steam's Big Picture mode, listing its games. This page owns how it is built and
where its data comes from. Until win.36 it also added a row of console families to Steam's Home; that shelf is retired
(see [Retired: the Home shelf](#retired-the-home-shelf)). The user-facing description is
[Console Pages](../user-guide/console-shelf.md).

## What is drawn

- **Console page** — route `/the-collector/console/:slug`. The console's games in its media style, "Continue" (the most
  recently played game of that console) first, then every other game by name in rows of six, paged 100 at a time with a
  "Show more" button. Each game shows when it was last played, whether it is downloaded, its save-sync chip and its
  RetroAchievements chip. A on a game opens `/library/app/<appId>`, the game page the plugin already owns, so the
  console page never launches anything itself. Colours come from the Core palette in `src/theme/coreTokens.ts`.

**Reaching it.** The route stays registered (`src/index.tsx`), but nothing in The Collector links to it since the Home
shelf, its only entry point, was retired. Another plugin can open it with
`Navigation.Navigate("/the-collector/console/<slug>")` (`consolePagePath` in `src/utils/consoleMedia.ts` builds the
path).

## Data flow

Everything the console page shows is read from this device's own records:

| Shown             | Source                                                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Games, names      | bound ROMs (`roms.shortcut_app_id IS NOT NULL`) of the console; its name from the `platform_names` cache, overridden                |
| Last played       | `rom_playtime`; play time under an unbound version of a game is folded into the version in Steam                                    |
| Save-sync chip    | `rom_save_sync_states` through `compute_save_sync_display`, the same cached display the game page shows before its live check       |
| Downloaded        | `rom_installs`                                                                                                                      |
| Achievements chip | the achievement snapshot (`rom_achievement_progress`), see below                                                                    |
| Cover art         | Steam's own capsule URLs for the shortcut (`src/utils/steamCapsuleArt.ts`, below); the title is printed on the case when none loads |

### Cover art

The console page's cases load exactly what Steam's library shows for the shortcut, from Steam's `appStore`, tried in
order (`capsuleArtSources`):

1. `appStore.GetCustomVerticalCapsuleURLs(overview)` — the custom grid art with the `?v=<rt_custom_image_mtime>`
   cache-buster Steam's own capsules carry. The plugin's cover lands there through `SetCustomArtworkForApp`.
2. `/customimages/<appId>p.png`, then `.jpg`, with the same cache-buster — the grid files themselves. The backend writes
   the cached RomM cover to `<appId>p.png` as well, so this is the plugin's already-cached cover, reached without a
   backend call.
3. `appStore.GetVerticalCapsuleURLForApp(overview)` — anything else Steam would draw.

Under the Game case cover style this is the ROM's case art, which the plugin puts on the same portrait capsule
([Game case covers](steam-non-steam-shortcuts.md#game-case-covers)); the console page itself never fetches or chooses art. Each
source that fails to load moves to the next. The lookup is synchronous and local; nothing
fetches a cover from RomM there.

`ConsoleShelfService` (`services/console_shelf.py`) builds the page in one short read unit of work and is declared
read-only in `scripts/check_read_only_module.py`. The callable `get_console_games(platform_slug, offset, limit)` runs it
off the event loop.

### Achievement snapshot

RetroAchievements progress comes from RomM only: `GET /api/users/me` returns `ra_progression.results[]`, one entry per
game the user has progress in, with `max_possible`, `num_awarded`, `num_awarded_hardcore` and `highest_award_kind`.
`AchievementsService.do_store_progress_snapshot` maps those entries to ROMs through `roms.ra_id` (versions sharing a set
share the record) and replaces the whole `rom_achievement_progress` table in one write unit of work, stamping
`kv_config.achievement_snapshot_fetched_at`. It runs from three places:

- `refresh_console_achievements`, which the console page calls when it opens, the snapshot is missing or older than an
  hour, and at least one of its games has a set. One refresh per console per page visit.
- the same callable from the achievements bridge's `getClosestToComplete`, when the snapshot is missing or older than an
  hour, at most one attempt an hour
  ([Achievements bridge](achievement-journal.md#achievements-bridge)).
- every `/api/users/me` answer the game page's per-ROM progress read already makes (including the post-session refresh),
  which costs no extra request.

A failed refresh keeps the previous snapshot and answers with the canonical failure shape. A game with a set and no
recorded progress shows "No progress yet"; its total is not known until the user starts it. The chip marks **Hardcore**
when every unlock so far was earned in hardcore mode, and **Mastered**, **Completed** or **Beaten** from the highest
award.

RomM only updates `ra_progression` when its own RetroAchievements sync runs (nightly, or from the RomM profile). Its
refresh endpoint needs the `me.write` scope, which the plugin does not request, so the plugin cannot make the data
fresher than RomM's last sync.

## Retired: the Home shelf

Until win.36 a `/library/home` route patch (`src/patches/homeShelfPatch.tsx`) inserted a row of console-family tiles
under Steam's Recent games, with art from the user's ColorGrade icon pack and a **Show The Collector on Home** setting.
Core now owns Big Picture Home: it draws its own Consoles tab from the per-console Steam collections, keeps the
console-family collections as Library tabs ([The console family collections](steam-non-steam-shortcuts.md#the-console-family-collections)),
and shows RetroAchievements in its Achievements tab through the
[achievements bridge](achievement-journal.md#achievements-bridge). So The Collector no longer touches Home at all, and
the invariant register says so.

Removed with it: the route patch and its watchdog, the shelf store, the row and family tiles, the Recent-games geometry
reader, the family navigation, the `get_console_shelf`, `get_family_art` and `save_collector_home_shelf` callables, the
`collector_home_shelf` setting (a value left in an existing `settings.json` is ignored), the recency-weighted "most
played" ranking, and the icon pack reader (`domain/icon_pack.py`, `adapters/icon_pack_files.py`), which had no other
user. The pack itself is still never copied into the repository, a release or a test.

What the shelf taught, in case Home is ever patched again: insert by recognising Steam's own row **by its props** (the
Recent games section takes `showBackground` and `autoFocus`) and add a sibling by copying elements, never mutating them;
wrap every hook in `try`/`catch` returning Steam's output unchanged, put the inserted row in an error boundary, and
switch the patch off after repeated failures. A separate React root or portal with `FocusNavController` patches, and
hook replacement through React internals, were rejected as too fragile across Steam betas. The full design is in this
page's history (win.35).

## Key files

| File                                            | Role                                                           |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `py_modules/domain/console_shelf.py`            | "Continue", page order, achievement chip rules                 |
| `py_modules/domain/rom_achievement_progress.py` | The snapshot aggregate and its construction from RomM's answer |
| `py_modules/services/console_shelf.py`          | The read model behind the console page (read-only)             |
| `py_modules/services/achievements.py`           | Writes the achievement snapshot                                |
| `src/utils/steamCapsuleArt.ts`                  | The capsule art URLs Steam's library uses for a shortcut       |
| `src/utils/consoleMedia.ts`                     | The page route, its path, and each console's media style       |
| `src/components/collector/`                     | Console page, game cases, stylesheet                           |
