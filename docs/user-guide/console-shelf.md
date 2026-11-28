# Console Shelf and Console Pages

The Collector adds a row of your console families to Steam's Big Picture Home, right under **Recent games**, and a page
for each console with its games.

## The Home row

The row is titled **The Collector**, with a cartridge glyph, and holds one wide tile per console family that has games
in your Steam library, always in this order: **PlayStation**, **Nintendo**, **Sega**, **Xbox** and **Retro**. Retro is
everything that isn't one of the four makers: arcade, Neo Geo and Neo Geo Pocket, SNK, TurboGrafx / PC Engine, Atari and
the home computers. Every Nintendo system (Game & Watch and Virtual Boy included) is under Nintendo, as in Core's
Library tabs.

Each tile shows the family's artwork and logo from your icon pack, the family's colour along the bottom edge, and
nothing else: no game art, no counts, no "last played".

With a controller: press down from Recent games to reach the row, left and right to move between families, and **A** to
open one. The selected tile lifts slightly with a crimson ring. **A** opens the family's collection in your Library, the
one The Collector keeps for it (see [Console family collections](configuration.md#console-family-collections)); with
that setting off, it opens the console page of the family's console you play most.

The row appears once the plugin has loaded and you have at least one synced game. It never contacts your RomM server
while Home is on screen; it updates after a sync, after you finish playing, and when a game's save status changes.

### The icon pack (Windows)

The artwork comes from the ColorGrade icon pack on your own PC, in
`%APPDATA%\GamingMode\icons\colorgrade\families\<family>\` (`hero.png`, `logo.png`, `icon.png`; the family folders are
`playstation`, `nintendo`, `sega`, `xbox` and `retro`). The plugin only reads these files; it doesn't ship or copy them.
When the folder or a file is missing, the tile is plain dark grey with the family's name in large letters. Art you add
later shows the next time the plugin loads.

## A console page

Opening a console shows its games drawn in that console's style — keep cases, jewel cases or cartridges, with the game's
cover from Steam when it has one.

- **Continue** comes first: the game from this console you played most recently.
- **All games** follows, alphabetically, in rows of six. Long lists load 100 games at a time; **Show more** at the
  bottom loads the next ones.
- Each game shows when you last played it, **Not downloaded** if it isn't on this device, and two kinds of chips:
  - **Save sync** (when [save sync](save-sync.md) is on): "Saves synced", "Not synced" or "No saves yet" — the status
    this device recorded at its last sync, which is what the game page shows before it checks the server. Open the game
    page for the live status.
  - **RetroAchievements**, from your RomM server: unlocked / total (for example "12 / 40"), **Hardcore** when every
    unlock so far was in hardcore mode, and **Mastered**, **Completed** or **Beaten** for your highest award. A game
    with achievements that you haven't started shows "No progress yet".

Press **A** on a game to open its game page (Play, downloads, saves). Press **B** to go back.

### Where the achievement numbers come from

The plugin reads RetroAchievements progress from your RomM server; it never asks for a RetroAchievements key of its own.
RomM refreshes that data during its own RetroAchievements sync (nightly, or when you sync from your RomM profile), so a
trophy earned tonight may only show up tomorrow. The console page asks RomM for the latest copy when it opens, at most
once an hour, and keeps the last copy for when the server is offline. Your RetroAchievements username must be set in
your RomM profile.

## Turning it off

**Show The Collector on Home**, in **The Collector** section of the settings page, hides the row (it is on by default).
Turning it off takes effect at once.

If the row doesn't appear, see
[The console shelf doesn't appear on Home](troubleshooting.md#the-console-shelf-doesnt-appear-on-home).
