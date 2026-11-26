# The Collector: Home console shelf and console pages

The Collector adds two things to Steam's Big Picture mode: a row of consoles on Home, under Steam's own Recent games
row, and a page per console listing its games. This page owns how both are built, how the Home row is attached to
Steam's tree, and what keeps a failure from ever breaking Home. The user-facing description is
[Console Shelf and Console Pages](../user-guide/console-shelf.md).

## What is drawn

- **Home row** — "The Collector": one tile per console that has games in Steam, drawn as a CSS stack of its media (DVD
  keep cases spine-out for PS2, GameCube boxes, jewel cases for CD consoles, SNES and N64 cartridges, small carts for
  handhelds, a generic keep case for anything else; `src/utils/consoleMedia.ts`). Each tile shows the console name, the
  game count and when it was last played. No logos, no artwork, no individual games. The focused tile is gunmetal
  `#1A1D21` with a crimson `#D7263D` ring, lifted 6 px; the palette is black `#000000`, gunmetal, crimson and steel
  `#C9D1D9`.
- **Console page** — route `/the-collector/console/:slug`. The console's games in its media style, "Continue" (the most
  recently played game of that console) first, then every other game by name in rows of six, paged 100 at a time with a
  "Show more" button. Each game shows when it was last played, whether it is downloaded, its save-sync chip and its
  RetroAchievements chip. A on a game opens `/library/app/<appId>`, the game page the plugin already owns, so the
  console page never launches anything itself.

## Most played

Consoles are ordered by **recency-weighted play time**: every game's play time counts half as much for each 90 days
since it was last played (`domain/console_shelf.py`, `HALF_LIFE_DAYS`). A console binged two years ago sinks below one
played this week. Ties go to the newest last-played instant, then the larger console, then the name; consoles with no
dated play time come last, by game count. Play time without a last-played instant weighs nothing.

The inputs are the plugin's own `rom_playtime` rows, already reconciled with RomM's play sessions. Steam's playtime
fields on the shortcuts are written from the same rows, so they are not read. Play time recorded under an unbound
version of a game (a version switch rebinds the shortcut within the sibling group) is folded into the version that is in
Steam.

## Data flow

Everything the Home row and the console page show is read from this device's own records:

| Shown                 | Source                                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Consoles, game counts | bound ROMs (`roms.shortcut_app_id IS NOT NULL`) grouped by `platform_slug`; names from the `platform_names` cache                             |
| Last played, ranking  | `rom_playtime`                                                                                                                                |
| Save-sync chip        | `rom_save_sync_states` through `compute_save_sync_display`, the same cached display the game page shows before its live check                 |
| Downloaded            | `rom_installs`                                                                                                                                |
| Achievements chip     | the achievement snapshot (`rom_achievement_progress`), see below                                                                              |
| Cover art             | Steam's own `/customimages/<appId>p.png` (then `.jpg`), which the plugin's artwork fills; the title is printed on the case when neither loads |

`ConsoleShelfService` (`services/console_shelf.py`) builds both payloads in one short read unit of work each and is
declared read-only in `scripts/check_read_only_module.py`. The callables `get_console_shelf` and
`get_console_games(platform_slug, offset, limit)` run it off the event loop.

The Home row never calls the backend while it renders. It reads `src/utils/consoleShelfStore.ts`, which is filled by one
`get_console_shelf` at plugin load and re-read (debounced 1.5 s) when what it shows can have changed: a `sync_progress`
frame with `running: false`, a `save_status_updated` event, and the frontend's `romm_playtime_changed` signal after a
session. Each read takes a sequence number, and an answer older than the last one applied is dropped.

### Achievement snapshot

RetroAchievements progress comes from RomM only: `GET /api/users/me` returns `ra_progression.results[]`, one entry per
game the user has progress in, with `max_possible`, `num_awarded`, `num_awarded_hardcore` and `highest_award_kind`.
`AchievementsService.do_store_progress_snapshot` maps those entries to ROMs through `roms.ra_id` (versions sharing a set
share the record) and replaces the whole `rom_achievement_progress` table in one write unit of work, stamping
`kv_config.achievement_snapshot_fetched_at`. It runs from two places, neither of which costs an extra request:

- `refresh_console_achievements`, which the console page calls when it opens, the snapshot is missing or older than an
  hour, and at least one of its games has a set. One refresh per console per page visit.
- every `/api/users/me` answer the game page's per-ROM progress read already makes (including the post-session refresh).

A failed refresh keeps the previous snapshot and answers with the canonical failure shape. A game with a set and no
recorded progress shows "No progress yet"; its total is not known until the user starts it. The chip marks **Hardcore**
when every unlock so far was earned in hardcore mode, and **Mastered**, **Completed** or **Beaten** from the highest
award.

RomM only updates `ra_progression` when its own RetroAchievements sync runs (nightly, or from the RomM profile). Its
refresh endpoint needs the `me.write` scope, which the plugin does not request, so the plugin cannot make the data
fresher than RomM's last sync.

## Attaching the row to Home

`src/patches/homeShelfPatch.tsx` registers `routerHook.addPatch("/library/home")`. The route element renders a Home
component that renders the component holding the rows. The patch wraps those two component layers (`HOME_DESCENT_STEPS`)
so their rendered output can be read, recognises the Recent games row in that output **by its props**, and inserts the
shelf as the row's next sibling, copying every element on the way rather than mutating it. Wrapper types are cached per
original, so React sees one stable type and Home is not remounted on a re-render.

The row is recognised by props contracts, tried in order (`RECENTS_ROW_MATCHERS`):

1. `recents-section` — an element whose props include `showBackground` and `autoFocus`. The same contract identifies the
   row in two independent codebases (the Core plugin's `storeInstallRecents.tsx` and Deck Shelves'
   `recentsRowPatch.ts`).
2. `recents-carousel` — the row's tile list: `games[]`, a function `onItemFocus` and `showFeaturedItem`. The shelf then
   lands right after the tile list.

The shelf is a real child of Steam's Home tree, so Steam's gamepad focus reaches it like any native row: down from
Recent games, left and right along the tiles, down to the next row. The tiles sit in a `Focusable` with
`flow-children="row"`, and a focused tile scrolls itself into view.

### Roads not taken

- **A DOM mount with its own React root or a portal, and patching `FocusNavController`** (Deck Shelves' main shelves).
  Its own documentation calls the focus patches the most fragile part of that codebase, and its changelog records a
  string of 2026 Steam betas that broke it: a separate root is not in Steam's focus tree, React DOM 19 removed the
  global `createRoot`, focus classes and events disappeared, rows hid on the Big Art layout.
- **Replacing hooks through React internals** (TabMaster on the Library route). It depends on private React internals
  and hook order, already had to grow a React 19 branch, and is not needed to add a sibling.
- **Steam's own `Carousel` for the tiles.** It is found by searching Steam's modules and its render contract is
  internal; a plain `Focusable` row behaves the same under the gamepad and has nothing to look up.

## Never breaking Home

1. The route patch and each output hook run inside `try`/`catch` and return Steam's output unchanged on any error, on an
   unrecognised tree, or when the setting is off.
2. The shelf is wrapped in an error boundary that renders nothing on a render error.
3. Every failure counts; after three (`MAX_FAILURES`) the patch switches itself off for the session and Home is rendered
   untouched until the plugin loads again.
4. Matching is by props on every render, never by position or a remembered element, so other Home patchers (Core's news
   row and install-recents rewrite) can wrap or reorder rows around it. If something hides the Recent games row, the
   shelf is simply not inserted.
5. "Show The Collector on Home" (`collector_home_shelf` in `settings.json`, on by default) is read by the patch at
   render time and by the row itself, so switching it off takes effect at once.
6. `onDismount` removes the route patch, the console page route and the store's listeners; a plugin reload or uninstall
   restores Steam's Home.
7. No Steam class names are used: the stylesheet is the plugin's own, `tc-` prefixed, rendered by the row and the page
   themselves.

### Diagnostics

When the row is found, one info line names the matcher that hit
(`The Collector: Recent games row found on Home (matcher "recents-section")`). When it has not been found 8 s after Home
first rendered, one warning says so and an outline of the last output that was searched (element types, keys and prop
names, at most 60 lines) goes to the debug log, prefixed `The Collector home tree:`. Failures are logged as
`The Collector: Home shelf <route|patch|render> failed (n/3)`. If a Steam update changes Home, those lines are what the
matchers and the descent depth are adjusted from.

## Key files

| File                                            | Role                                                           |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `py_modules/domain/console_shelf.py`            | Ranking, "Continue", page order, achievement chip rules        |
| `py_modules/domain/rom_achievement_progress.py` | The snapshot aggregate and its construction from RomM's answer |
| `py_modules/services/console_shelf.py`          | The read model behind both callables (read-only)               |
| `py_modules/services/achievements.py`           | Writes the achievement snapshot                                |
| `src/patches/homeShelfPatch.tsx`                | The Home route patch, matchers, watchdog, diagnostics          |
| `src/utils/consoleShelfStore.ts`                | The Home row's store and its refresh triggers                  |
| `src/components/collector/`                     | Row, tile, media stacks, console page, game cases, stylesheet  |
