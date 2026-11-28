# ROM Game Page (Core design)

A ROM's Steam game page is Steam's own app-details page with The Collector's panel in place of Steam's overview panel.
User-facing behaviour is in [Managing Games](../user-guide/managing-games.md#the-game-detail-panel); this page is how
the page is put together and which rules it keeps.

## Layout

The Core page follows the Clean Gameview theme (v1.8 Lz, SuchMeme and Leozito, MIT) the way Core's restyle of Steam's
own game page will, so a ROM page and a Steam page look the same. It has two screens.

**Screen one** is a place to see the art: Steam's hero art fills the view (`object-fit: cover`, 60% brightness, Steam's
top gradient cleared), Steam's logo is locked bottom-left at most 120px tall (Steam draws the name as text when there is
no logo), and a transparent play bar sits along the bottom above the footer. Measures (`GAME_VIEW` in
`utils/corePageStyles.ts`): an 80px play bar over a 40px footer, so Steam's `TopCapsule` is `100vh - 120px` tall and the
play bar row is 120px with 40px of bottom padding. Nothing else is drawn over the art.

**Screen two**, one D-pad press down from the play bar, is black with the stars: the platform and The Collector chips,
the tab row and the active tab's content. Focus entering it from above scrolls it to the top (`scrollToScreenTwo`); Y
(`onOptionsButton`) scrolls back and puts focus on the play button (`scrollToScreenOne`).

### The play bar

Steam's own play-section classes (`PlaySection`, `ActionRow`, `ActionButtonAndStatusPanel`, `StatusAndStats`,
`GameStatsSection`, `AppButtons`, `appActionButtonClasses.PlayButtonContainer`, `GameStat` / `PlayBarLabel` /
`PlayBarDetailLabel`) are kept, so a Core rule for Steam's play bar reaches both pages. Left to right:

- Play (crimson, white 3px ring on focus) or the Download / progress / conflict states, then the disc, exe and version
  pickers when the game has them.
- Cells, label over value: SPACE REQUIRED (not installed), LAST PLAYED, PLAY TIME, EMULATOR (the active emulator or
  core), and the legacy-slot and missing-BIOS warnings.
- Square 48px black buttons (Clean Gameview's "cloud as a button" size): emulator or core (only with more than one),
  Mods (when Forge has not registered its tab), save sync (a cloud marked synced, waiting, conflict or off; opens the
  Saves tab on screen two), controller layout (`SteamClient.Apps.ShowControllerConfigurator`), and Options. The Start
  button opens Options from anywhere on the play bar.

The save-sync warnings (RetroArch writing saves beside the ROM, sync blocked) render after the play bar on Windows, at
the top of screen two.

## Structure

`patches/gameDetailPatch.tsx` finds Steam's `InnerContainer` and replaces the native `AppDetailsOverviewPanel` with
`rommPageWrapper`: a `div` carrying the native panel's class (so it takes part in Steam's flex layout and scrolling)
that holds `RomMPlaySection` and `RomMGameInfoPanel`. Steam keeps drawing the header (hero art and logo) above it.

| Part           | Module                                                  | Owns                                                                             |
| -------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Chips          | `components/RomPageChips.tsx`                           | Platform chip (family tone) and The Collector chip at the top of screen two      |
| Play bar       | `components/RomMPlaySection.tsx`, `CustomPlayButton`    | Play/Download states, pickers, meta cells, the square buttons                    |
| Tabs           | `components/PanelTabBar.tsx`                            | Overview, Achievements, extension tabs, Saves, Media, Details, BIOS              |
| Overview cards | `components/RomOverviewCards.tsx`, `GamePageExtensions` | RetroAchievements (order 10) and Save sync (30) among registered cards, by order |
| Panes          | `components/panelTabContent.tsx`                        | Overview summary, Details (`GameInfoTab`), Media (`RomMediaTab`), Saves          |
| Core styles    | `utils/corePageStyles.ts`                               | The one stylesheet for the Core page                                             |
| Family tones   | `theme/coreTokens.ts` (`consoleFamily`, `familyTones`)  | RomM platform slug to PlayStation / Nintendo / Sega / Xbox / retro               |

The two-screen layout, the chips and the play bar's square buttons render only under the Windows look (`nativeLook()`),
where the wrapper is also the Core page (`.romm-core-page`). The tabs, cards and panes are the same on every platform;
the Steam Deck keeps its older play row.

## The Core page's styles

`ensureCorePageStyles()` injects one stylesheet into Big Picture's document the first time a ROM page renders. Every
rule is scoped under `.romm-core-page`; the ones that reach Steam's header go through
`InnerContainer:has(>
.romm-core-page)`, so a Steam game page is never touched:

- `InnerContainer` is black; `TopCapsule` is screen one's height; `HeaderBackgroundImage` is `100vh`, so the art runs
  under the transparent play bar; `ImgSrc` is cover and dimmed; `TopGradient` is cleared; `BoxSizer` (the logo) is
  locked bottom-left.
- The wrapper is transparent for its first 120px (the play bar) and black below.
- Tabs carry one crimson underline (an inset shadow, so it never shifts the row); a focused tab is gunmetal.
- Cards are gunmetal with `var(--core-radius-float, 10px)`; focus is gunmetal raised plus a crimson outline, no glow.

A class map Steam renames leaves its rule out; the rest still applies.

### Stars

Core UI's design rule is that a black surface gets the Core Starfield. Core UI attaches its animated canvas only to the
surfaces in its own host list, which does not include this page yet. Until it does, the wrapper's first child
(`.romm-core-stars`, from the end of screen one down) paints a still, seeded field (`starfieldSvg`, no star above 24%
opacity, Core UI's ceiling) and shows only under `html[data-core-ui]`. Without Core UI the page is plain black. When
Core UI takes the page as a host it sets `data-core-ui-host="1"` on it, and the still field steps aside.

## Rules kept

- **ROM identity.** The play bar renders from the play section's `useGameDetail` state; the chips and the Overview cards
  render from the panel's state (`raId`, `achievements`, `saveSyncEnabled`, `saveStatus`, `conflicts`) and read nothing
  themselves. `achievements` is written only alongside `raId`, at the two identity writes (`loadData` and the version
  switch), so a switch re-renders the cards with the switched-to version's answers. Card and tab presses only set
  `activeTab`; no write crosses an `await`, so the `writerForRom` / `RomBinding` rule has no new site.
- **Every action stays reachable.** The Options menu holds what the separate RomM Actions and Steam Properties buttons
  held; the save sync button reaches the Saves tab; the cover is on Media, the description on the Overview; BIOS keeps
  its own tab.
- **Controller.** The play bar, tab row, card grid and panes are `Focusable` rows and columns; cards are
  `DialogButton`s, so A opens their tab.
