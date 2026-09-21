# In-game checklist

CI cannot run the game. Everything below is what the stub tests cannot prove. Run it on the
Forever beta (or live) with BugSack and BugGrabber installed, after `/reload`.

## Display (every release)

1. Open a quest giver with a quest in `MonkeDB` (Red Silk Bandanas, 214, Scout Riell in Westfall).
   The description shows the lore, the objectives show bullets with a turn-in line, and the
   rewards line matches the reward panel below it.
2. Click the toggle on the quest frame header. Blizzard's text comes back exactly, including
   paragraph breaks. Click again: Monke Do text returns. `/monke lore` does the same.
3. Accept the quest, open the map quest details: same text, progress such as `(3/10)` on the
   item bullet, and it updates after looting one more.

## Display (first time on a new client build)

4. `/dump QuestInfo_Display ~= nil, QuestFrameProgressPanel ~= nil, QuestMapFrame.DetailsFrame ~= nil`
   prints `true, true, true`. If not, a hotfix renamed something: Display does nothing rather than
   error, and the hooks in `Display.Enable` need updating.
5. The toggle button sits in the quest frame header without covering the NPC name or the close
   button, and on the map quest details without covering the back button. Positions are the two
   `createToggle` calls in `Display.lua`.
6. A long quest (more than one screen of Blizzard text) scrolls correctly after the swap, with no
   empty scroll area left behind, on the detail, progress and reward pages.
7. A quest with no `MonkeDB` entry (any Forever-new quest) shows "Lore not yet translated.",
   Blizzard's text under it, and rule-based bullets.
8. Progress page with items still missing shows the "still need" list; with everything done it
   shows the ready line. Reward page shows the complete line and rewards.
9. A group quest (suggested players above 1, or an elite or dungeon quest) shows the red group
   line first. `/monke group off` removes it.

## Tracker

10. Tracked quests show "Grab 10 Red Silk Bandana (3/10)" style lines. No line overlaps the one
    below it. `/monke tracker off` restores Blizzard's lines after the next tracker update.
11. Use a quest item button in the tracker during combat: no "action blocked" taint error.

## Settings

12. `/monke` opens the settings panel; voice dropdown and three checkboxes change the open quest
    frame immediately. The addon compartment entry opens the same panel.
13. `/monke version` prints the addon version, quest count, game build and generation date.
14. Relog. Settings come back as defaults while the SavedVariables beta bug lasts; no error.

## 30-quest soak (before a tag)

15. Accept, progress and turn in 30 quests across two zones with BugSack open: zero Lua errors.
16. With Immersion or Storyline enabled: one chat line explains that only the log and tracker
    change, and nothing errors.
