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
   - With the letter-by-letter fade on (`/console instantQuestText 0`, the classic look; Blizzard
     added it after build 1.60.1.69913): the Monke text fades in, then the task list and rewards fade
     in and Accept lights up. After it finishes, click the toggle: all of Blizzard's text shows at
     once, none of it cut off after the first line or two. Click again: all of the Monke text.
     Then open a long quest in the map quest details: all of its text shows. Repeat with
     `/console instantQuestText 1`: no fade, everything as before.
3. Accept the quest, open the map quest details (and the quest log popup, if the client has
   one): the task list comes first, starting with a "Monke do:" line in the same colour as
   Blizzard's "Description" header, with progress such as `(3/10)` on the item bullet that
   updates after looting one more. The lore sits under
   "Description". There is no "Monke get:" line (the map's own rewards panel is below) and none
   of Blizzard's own objective lines.
   - No big empty gap between the task list and "Description" (or the group size line) once
     Blizzard's objective lines are emptied. Blizzard's own offsets remain, so expect roughly
     10-16 px more than with no list at all; a gap of several text lines is a bug. Compare with
     the toggle on: Blizzard's lines come back with "(Complete)" where due.
   - A finished objective shows grey. The header, the grey lines, the grey "Long story?" line
     and the red group warning are all easy to read on the parchment page, and again after
     turning on Quest Text Contrast (Options > Accessibility): Monke Do reads the page's own
     colours after each redraw, so it should switch with Blizzard's text.
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

## Now line and Monke pick

17. Log in with a quest super-tracked (click the round map-pin button next to the quest in the
    tracker, or right-click the quest > Focus; a left-click on the title opens the map instead).
    A small dark strip with the monke icon sits at the bottom middle of the screen: under your
    own and your target's frames, over the action bars and the cast bar, as wide as its words, and
    covering nothing else. It stays centred as its text gets longer or shorter. Check it in Edit
    Mode's other layouts too (Classic moves the unit frames to the top left; the gamepad layout
    brings them closer to the middle), while casting, and on a quest with a long step: the line
    is cut with "..." and hover shows it whole.
18. Drag the line with the left mouse button: it follows the mouse, cannot leave the screen, and
    letting go does not also pick a quest. `/dump MonkeDoDB.nowPoint` then shows `point` CENTER,
    `relativePoint` BOTTOM, `x` and `y` (nil: report it), and a longer step afterwards grows both
    ways from where it was left. `/monke now reset` puts it back at the bottom middle. While the
    beta does not load saved settings, a relog also puts it back there.
19. Walk toward the quest: the distance drops about once a second, in steps of 10 yards, and
    agrees with Blizzard's arrow and the map. Under 30 yards it says "close" (plain: "nearby").
    On another continent or inside an instance there is no distance, and no error.
20. Kill or loot for the objective on the line: it counts down ("Grab 7 more ...", "Grab 6 more
    ...") within a moment, also mid-fight. Before the first one it says the whole amount ("Grab
    10 ..."), with no "more". After the last objective the line switches to the turn-in line.
21. Super-track a quest whose next step is in another zone or across water: the tooltip has a
    "Way: ..." line (plain: "Next: ..."); the strip stays one line. The middle dot before the
    distance and the dash in the chat line of item 26 show as characters, not boxes.
22. Options > Keybindings > AddOns lists "Monke Do: which quest now?" (there is no separate
    "Monke Do" heading: the game draws headings there as blank rows). Bind a key and press it:
    Blizzard's arrow and map pin point at the picked quest (one ready to hand in first, else the
    nearest), with a short click. Press again: the next quest; after the last it wraps.
    `/monke pick` and a left-click on the line do the same, also in combat. A picked quest you
    are not watching stays off Blizzard's tracker (Monke Do does not add watches, to keep the
    tracker untainted); the strip still shows it.
23. With nothing super-tracked the line reads "Nothing now. Click: Monke pick." With an empty quest
    log, a pick says "No quest. Monke go find quest giver." for a few seconds.
24. Right-click the line: nothing happens (by design: opening Blizzard's map from addon code taints
    the map and the tracker, and Blizzard's next map refresh in combat gets blocked). Press M: the
    map shows the picked quest. Then, with the map still open, fight a quest mob, loot it, and use
    a quest item button in the tracker and an action button: no "action blocked" and no
    "Interface action failed because of an AddOn".
25. Hover the line: the tooltip shows the quest title, the whole step with its distance, the
    "Way:" route when there is one, then the click and drag lines.
26. `/monke now off` hides the line; a pick then prints one chat line ("Monke pick: <quest> — <next
    step> · <distance>"). `/monke now on` and the "Now line" checkbox in the settings panel bring
    it back. `/monke voice plain` changes its words at once.
27. Fights: when one starts the line fades to about a third, still readable, and hovering it
    shows it whole. Resume cue: after a loading screen (hearthstone, boat, instance portal), a
    moment after it has faded, and when a fight ends, the line comes back and glows gold twice
    over about two seconds. The text stays readable through the glow. Nothing glows during a
    fight or when no quest is tracked.
28. Collapse a zone header in the quest log: Monke pick still finds the quests under it. It never
    picks a failed quest, a world quest or a bonus objective.
29. With BugSack open through all of the above: no Lua error, no taint warning, no "action blocked".

## The pointer

30. Follow a quest in the open world: the monke icon at the start of the Now line becomes a
    pointing monke finger. Turn on the spot in a full circle: the finger turns the other way and
    keeps pointing at the quest, the same way as the gold arrow on the edge of the minimap (and
    toward the quest's area with the map open). Walk the way it points: the distance on the line
    goes down. The finger reads at a glance, hangs only a little over the strip and does not
    touch the words. `/monke pointer arrow` (or the "Gold arrow" checkbox) swaps in a gold arrow
    that points the same way; `/monke pointer finger` brings the finger back.
31. Within about 30 yards of the spot the pointer turns back into the monke icon. Once the quest is
    ready, it points at whoever takes it in.
32. A quest in the next zone over: the pointer points toward it. One that needs a boat or a portal:
    it points at the boat or portal first (the tooltip's "Way:" line). One on another continent:
    the monke icon, no arrow.
33. Inside a dungeon: the monke icon, no pointer, no error. A quest with no map marker (some new
    Forever quests): the monke icon.
34. A few minutes of questing with the pointer turning: no frame-rate drop. It turns 25 times a
    second, and only while the line shows a quest.
