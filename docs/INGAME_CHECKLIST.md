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

## Now line and Monke pick

17. Log in with a quest super-tracked (click a quest in the tracker). A dark line sits just above
    the objective tracker, left edges lined up, as wide as the tracker, not covering the tracker,
    the minimap, the buffs or the zone text. Its text is a size larger than the tracker's lines.
    With the tracker empty or collapsed it still sits somewhere sensible.
18. Drag the line with the left mouse button: it follows the mouse, cannot leave the screen, and
    letting go does not also pick a quest. `/dump MonkeDoDB.nowPoint` then shows `point`,
    `relativePoint`, `x` and `y` (nil means the client left the frame anchored to something other
    than UIParent after the drag: report it). `/monke now reset` puts it back above the tracker.
19. Walk toward the quest: the distance drops about once a second, in steps of 10 yards, and
    agrees with Blizzard's arrow and the map. Under 30 yards it says "close" (plain: "nearby").
    On another continent or inside an instance there is no distance, and no error.
20. Kill or loot for the objective on the line: the count, e.g. `(4/10)`, updates within a moment,
    also mid-fight. After the last objective the line switches to the turn-in line.
21. Super-track a quest whose next step is in another zone or across water: a second, smaller line
    reads "Way: ..." (plain: "Next: ..."). The middle dot before the distance and the dash in the
    chat line of item 26 show as characters, not boxes.
22. Options > Keybindings > AddOns lists "Monke pick: which quest now?" under Monke Do. Bind a key and
    press it: Blizzard's arrow and map pin point at the picked quest (one ready to hand in first,
    else the nearest), with a short click. Press again: the next quest; after the last it wraps.
    `/monke pick` and a left-click on the line do the same, also in combat.
23. With nothing super-tracked the line reads "Now: nothing. Click, Monke pick." With an empty quest
    log, a pick says "No quest. Monke go find quest giver." for a few seconds.
24. Right-click the line out of combat: the map opens on the quest's details. In combat: nothing
    opens and the line says "Monke busy bonking. Map after fight." for a few seconds. Then fight
    again and use a quest item button in the tracker and an action button: no "action blocked" and
    no "Interface action failed because of an AddOn".
25. Hover the line: the tooltip shows the quest title, then the click, right-click and drag lines.
26. `/monke now off` hides the line; a pick then prints one chat line ("Monke pick: <quest> — <next
    step> · <distance>"). `/monke now on` and the "Now line" checkbox in the settings panel bring
    it back. `/monke voice plain` changes its words at once.
27. Resume cue: after a loading screen (hearthstone, boat, instance portal), a moment after it has
    faded, and when a fight ends, the line glows gold twice over about two seconds. The text stays
    readable through the glow. Nothing glows during a fight or when no quest is tracked.
28. Collapse a zone header in the quest log: Monke pick still finds the quests under it. It never
    picks a failed quest, a world quest or a bonus objective.
29. With BugSack open through all of the above: no Lua error, no taint warning, no "action blocked".
