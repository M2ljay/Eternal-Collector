# Achievements: Goals, Notes and Timeline

The **Achievements** tab on a game's page shows its RetroAchievements set from RomM. On top of that list you can pin
achievements as **goals**, keep **notes** for the game, open an achievement's page on RetroAchievements, and see a
**timeline** of your unlocks across games.

## Goals

1. Open a game's page and select the **Achievements** tab.
2. Select an achievement and press **A**, then choose **Pin as goal**. The row gets a red **GOAL** tag.
3. Select **Goals** at the top of the tab to see this game's goals. A goal turns green with a tick once it is unlocked.

To remove a goal, press **A** on it (in **All** or **Goals**) and choose **Remove goal**.

Goals are shared by every version of a game (they belong to its RetroAchievements set), and they are kept if a game is
removed from your library: sync it again and they come back.

### Goals in the Quick Access menu

The Collector's main page in the Quick Access menu lists up to three open goals. **All goals and unlock timeline** (or
**Achievements** in the buttons at the bottom) opens the **Achievements** page with every goal. Press **A** on a goal
there to open its game, remove it, or open its RetroAchievements page.

A goal is ticked off as soon as The Collector sees the unlock: when you open the game's Achievements tab (RomM's data),
or, with a Web API key set up, from the timeline or **Check goals on RetroAchievements**. RomM's data is only as fresh
as RomM's own RetroAchievements sync.

## Notes

Select **Notes** at the top of the Achievements tab, then **Write notes** (or **Edit notes**). Steam's on-screen
keyboard opens; select **Save** when done. Saving an empty note clears it. Notes are limited to 4,000 characters.

The Notes view also links the game's page on RetroAchievements and, with a Web API key set up, the game's guide when
RetroAchievements lists one. Links open in Steam's browser.

## Guides for one achievement

Press **A** on any achievement and choose **Open guide on RetroAchievements**. Its page on RetroAchievements opens in
Steam's browser; players' tips and comments are there. The Collector only opens RetroAchievements' own pages and its
guides on GitHub, never other sites.

## Unlock timeline

The **Achievements** page in the Quick Access menu shows your unlocks, newest first: achievement, game and console,
points, date, and **HC** for hardcore. Choose the **Period** (last 30 days, 90 days or year) and narrow it by **Game**
or **Console**. **Refresh timeline** reads it again (otherwise it is kept for ten minutes).

The timeline needs a RetroAchievements Web API key. Without one, the page shows a line saying where to add it; goals and
notes work without it.

## Setting up the Web API key

1. On [retroachievements.org](https://retroachievements.org), sign in and open your settings page. Copy your **Web API
   Key**.
2. In The Collector, open **Settings**, go to **The Collector**, and select **Edit** next to **RetroAchievements Web
   API**.
3. Enter your RetroAchievements **username** and the **Web API key**, then **Save**. The key is checked with
   RetroAchievements before it is saved.

The key is stored in The Collector's settings and shown only as `••••`. It is sent only to retroachievements.org, never
to your RomM server or anywhere else, and it is not written to the logs. The Collector never reads the RetroAchievements
login stored in your emulators. **Remove** next to the setting deletes the username and key.

If the timeline says the key was refused, select **Edit** and enter it again; RetroAchievements gives you a new key if
you reset it on its site.
