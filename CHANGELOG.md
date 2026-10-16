# Monke Do

## v0.9.0-beta1

The first test build, for the WoW: Forever beta.

- **Quest text for smooth brains.** The quest window, the quest log and the map's quest details
  show one or two sentences of lore and a short task list instead of the wall of text. One click
  on the Wrinkle button (or `/monke lore`) brings back Blizzard's exact text.
- **Two voices.** Monke, or Plain English for the same information without the joke
  (`/monke voice plain`).
- **5,214 quests**: all 4,244 original quests and 970 that are new to Forever. A quest the
  database does not have yet still gets a task list, and shows the game's own one-line summary
  instead of the wall of text.
- **The Now line.** The one next thing to do, and how far away it is, at the bottom middle of the
  screen. A monke finger points the way and turns as you turn (`/monke pointer arrow` for a gold
  arrow). It fades during a fight and glows when you get back to it. Drag it anywhere.
- **Monke pick.** "Which quest now?" in one key (Options > Keybindings > AddOns), a click on the
  Now line, or `/monke pick`. It picks a quest you can hand in, otherwise the nearest one.
- **The Monke Do list** (`/monke list on`). Every quest's next step, nearest first. Click a line
  to follow that quest.
- **Voice lines.** "OK, monke do!" and "Monkey don't." when you switch texts or take a quest
  (`/monke sounds off` to mute them).
- The objective tracker uses the same short wording, and a minimap button switches the text
  (right-click for the settings).

Known limits:

- No pointer inside dungeons: the game does not tell addons where you are there.
- Some new Forever quests have no lore line yet and show Blizzard's one-line objective.
- Monke Do's own text is English only.
