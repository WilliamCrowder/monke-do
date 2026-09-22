# In-game checklist

CI cannot run the game. Everything below is what the stub tests cannot prove. Run it on the
Forever beta (or live) with BugSack and BugGrabber installed, after `/reload`.

## Display (every release)

1. Open a quest giver with a quest in `MonkeDB` (Red Silk Bandanas, 214, Scout Riell in Westfall).
   The description shows the lore, the "Quest Objectives" header reads "Monke do:" ("To do:" in
   plain voice), the objectives show bullets with a turn-in line, and the rewards line matches
   the reward panel below it.
2. Click the toggle on the quest frame header. Blizzard's text comes back exactly, including
   paragraph breaks, and the header reads "Quest Objectives" again. Click again: Monke Do text
   and "Monke do:" return. `/monke lore` does the same.
   - Toggle to the original while the map quest details are open, then open a quest giver: the
     header says "Quest Objectives", never "Monke do:".
3. Accept the quest, open the map quest details (and the quest log popup, if the client has
   one): the task list comes first, starting with a gold "Monke do:" line, with progress such as
   `(3/10)` on the item bullet that updates after looting one more. The lore sits under
   "Description". There is no "Monke get:" line (the map's own rewards panel is below) and none
   of Blizzard's own objective lines.
   - No empty gap between the task list and "Description" (or the group size line) once
     Blizzard's objective lines are emptied. Compare with the toggle on: Blizzard's lines come
     back with "(Complete)" where due, and the spacing matches.
   - A finished objective shows grey. The gold header and the grey lines are readable on the
     parchment background, and with Quest Text Contrast (Accessibility settings) turned on.
   - A quest whose route goes through a boat, tram or portal (Blizzard shows a waypoint line at
     the top of its list) shows a "Way: ..." bullet first ("Next: ..." in plain voice) with the
     same place as Blizzard's line when toggled.

## Display (first time on a new client build)

4. `/dump QuestInfo_Display ~= nil, QuestFrameProgressPanel ~= nil, QuestMapFrame.DetailsFrame ~= nil`
   prints `true, true, true`. If not, a hotfix renamed something: Display does nothing rather than
   error, and the hooks in `Display.Enable` need updating.
5. The toggle button sits in the quest frame header without covering the NPC name or the close
   button, and on the map quest details without covering the back button. Positions are the two
   `createToggle` calls in `Display.lua`.
6. A long quest (more than one screen of Blizzard text) scrolls correctly after the swap, with no
   empty scroll area left behind, on the detail, progress and reward pages and in the map quest
   details.
7. A quest with no `MonkeDB` entry (any Forever-new quest) shows Blizzard's short objectives
   sentence where the lore goes, a grey "Long story? Poke Wrinkle." line under it ("Full text:
   press Original." in plain voice), and rule-based bullets; never the full description, on the
   quest giver page and in the map details. The toggle brings the full description back.
   - A talk-only quest with no objectives sentence shows the first sentence or two of its
     description (at most about 160 characters, a word boundary and "…" when no sentence ends in
     time) instead.
   - Change a setting (`/monke group off`) with such a quest open: the sentence stays put and is
     never replaced by the bullet list.
8. Progress page with items still missing shows the "still need" list, with any finished
   objective in grey; with everything done it shows the ready line. Reward page shows the
   complete line and rewards.
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
