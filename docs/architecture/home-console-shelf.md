# The Collector: Home console shelf and console pages

The Collector adds two things to Steam's Big Picture mode: a row of consoles on Home, under Steam's own Recent games
row, and a page per console listing its games. This page owns how both are built, how the Home row is attached to
Steam's tree, and what keeps a failure from ever breaking Home. The user-facing description is
[Console Shelf and Console Pages](../user-guide/console-shelf.md).

## What is drawn

- **Home row** — "The Collector": one portrait capsule per console that has games in Steam, on the lines of Steam's own
  Recent games row (see [Lining up with Recent games](#lining-up-with-recent-games)). A capsule shows the Steam capsule
  art of the console's **cover game** — its "Continue" game, else its first game by name (`cover_app_id`) — over a CSS
  stack of the console's media (DVD keep cases spine-out for PS2, GameCube boxes, jewel cases for CD consoles, SNES and
  N64 cartridges, small carts for handhelds, a generic keep case for anything else; `src/utils/consoleMedia.ts`), which
  is what remains visible when the game has no art. A capsule carries no text of its own: the console's name fades in
  along the bottom only while the capsule has focus, and Home shows **no game count and no "last played" time or date**
  anywhere (the console page, a separate route, still shows them per game). The focused capsule scales up 5 % with a
  crimson ring. Colours come from the Core palette in `src/theme/coreTokens.ts` (black, gunmetal, crimson, steel),
  shared with the QAM panel and the game detail page.
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

| Shown                 | Source                                                                                                                              |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Consoles, game counts | bound ROMs (`roms.shortcut_app_id IS NOT NULL`) grouped by `platform_slug`; names from the `platform_names` cache                   |
| Last played, ranking  | `rom_playtime`                                                                                                                      |
| Save-sync chip        | `rom_save_sync_states` through `compute_save_sync_display`, the same cached display the game page shows before its live check       |
| Downloaded            | `rom_installs`                                                                                                                      |
| Achievements chip     | the achievement snapshot (`rom_achievement_progress`), see below                                                                    |
| Home capsule game     | `cover_app_id`: the shortcut of the console's first game in console-page order                                                      |
| Cover art             | Steam's own capsule URLs for the shortcut (`src/utils/steamCapsuleArt.ts`, below); the title is printed on the case when none loads |

### Cover art

The Home capsules and the console page's cases load exactly what Steam's library shows for the shortcut, from Steam's
`appStore`, tried in order (`capsuleArtSources`):

1. `appStore.GetCustomVerticalCapsuleURLs(overview)` — the custom grid art with the `?v=<rt_custom_image_mtime>`
   cache-buster Steam's own capsules carry. The plugin's cover lands there through `SetCustomArtworkForApp`.
2. `/customimages/<appId>p.png`, then `.jpg`, with the same cache-buster — the grid files themselves. The backend writes
   the cached RomM cover to `<appId>p.png` as well, so this is the plugin's already-cached cover, reached without a
   backend call.
3. `appStore.GetVerticalCapsuleURLForApp(overview)` — anything else Steam would draw.

Under the Game case cover style this is the ROM's case art, which the plugin puts on the same portrait capsule
([Game case covers](steam-non-steam-shortcuts.md#game-case-covers)); the shelf itself never fetches or chooses art. Each
source that fails to load moves to the next. The lookup is synchronous and local, so it is safe on the Home render path;
nothing fetches a cover from RomM there.

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

### Lining up with Recent games

The row takes its geometry from Steam's own Recent games row as Steam rendered it (`src/utils/steamRowGeometry.ts`).
Because the patch inserts the shelf as that row's next sibling, the row's element is the shelf's
`previousElementSibling`. After mount, on window resize, when the row resizes and twice more while Steam's capsules
load, the shelf measures it:

- **left inset** — the left edge of the row's first image, from the row's own left edge;
- **capsule height and gap** — the median height of the row's portrait images (ratio 1.2 to 1.8) and the smallest gap
  between them; the shelf's capsules take that height at a 2:3 ratio;
- **vertical rhythm** — the space above the row's title (or its capsules), between title and capsules, and under the
  capsules;
- **title type** — font family, size, weight, line height, letter spacing and case of the row's title, which is the
  first short text before its first image; when Recent games has no title, the same is read from the next rows on Home.

The numbers go into CSS variables on the shelf's own section (`--tc-inset`, `--tc-capsule-h`, …). Measuring reads
bounding boxes and computed styles only and writes nothing to Steam's elements. When nothing can be measured (no
portrait image found, or an exception) the shelf uses its own fallback geometry, a 240 px 2:3 capsule with a 24 px
inset, and `data-geometry="fallback"` on the section says so. Copying Steam's classes was not taken: they are hashed per
build, and Steam's carousel sizes its tiles in JavaScript, so a class carries neither a stable name nor the size. The
shelf no longer relies on a CSS Loader theme for its spacing.

Focus follows Steam's: the capsules sit in a `Focusable` with `flow-children="row"`, so the D-pad moves down from Recent
games into the row and on to the next row. A focused capsule scrolls to the nearest edge, kept clear of the inset by
`scroll-padding-inline`, and the scrolling row carries 16 px of padding (given back by a negative margin) so the focus
ring and scale are not clipped.

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
   themselves. Steam's row geometry is read from its rendered boxes, never by writing to them.

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
| `src/utils/steamCapsuleArt.ts`                  | The capsule art URLs Steam's library uses for a shortcut       |
| `src/utils/steamRowGeometry.ts`                 | Measures Steam's Recent games row for the shelf's geometry     |
| `src/components/collector/`                     | Row, tile, media stacks, console page, game cases, stylesheet  |
