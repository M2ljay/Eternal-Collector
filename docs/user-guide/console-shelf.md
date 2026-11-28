# Console Pages

The Collector has a page for each console listing its games.

!!! note "The Home row is gone"

    Up to version win.35, The Collector also put a row of your console families on Steam's Big Picture Home, under
    **Recent games**, with a **Show The Collector on Home** setting. Core now draws Home itself: its **Consoles** tab
    shows your consoles from The Collector's per-console Steam collections, the family collections stay as Library tabs
    (see [Console family collections](configuration.md#console-family-collections)), and its **Achievements** tab shows
    your RetroAchievements alongside Steam achievements. The setting is gone, and the icon pack in
    `%APPDATA%\GamingMode\icons\colorgrade` is no longer read by The Collector.

## A console page

Opening a console shows its games drawn in that console's style — keep cases, jewel cases or cartridges, with the game's
cover from Steam when it has one. The page is titled with the console's name as RomM gives it, except the original
PlayStation, which is **PlayStation 1** (RomM calls it just "PlayStation", the family's name).

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
trophy earned tonight may only show up tomorrow. The console page (and Core's Achievements tab) asks RomM for the latest copy at most once an hour, and keeps the last copy for when the server is offline. Your RetroAchievements username must be set in
your RomM profile.

Nothing in The Collector itself opens a console page any more; Core or another plugin can link to it.
