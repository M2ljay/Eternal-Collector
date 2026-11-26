# Console Shelf and Console Pages

The Collector adds a row of your consoles to Steam's Big Picture Home, right under **Recent games**, and a page for each
console with its games.

## The Home row

The row is titled **The Collector** and holds one tile per console that has games in your Steam library. Each tile is a
little stack of that console's media — PS2 cases on their spines, GameCube boxes, PS1 jewel cases, SNES and N64
cartridges, and a plain case for any other console — with the console's name, how many games it has, and when you last
played it ("Played tonight", "Played last week", …).

The consoles are ordered by how much you play them **lately**: play time counts half as much for every 90 days since you
last played, so a console you binged years ago drops behind one you picked up this week. Consoles you have never played
come last.

With a controller: press down from Recent games to reach the row, left and right to move between consoles, and **A** to
open one. The selected tile lifts slightly with a red ring.

The row appears once the plugin has loaded and you have at least one synced game. It never contacts your RomM server
while Home is on screen; it updates after a sync, after you finish playing, and when a game's save status changes.

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
Turning it off takes effect at once. The row is the way into the console pages, so they are not reachable while it is
off.

If the row doesn't appear, see
[The console shelf doesn't appear on Home](troubleshooting.md#the-console-shelf-doesnt-appear-on-home).
