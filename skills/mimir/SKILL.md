---
name: mimir
description: Answer Valheim questions (items, crafting recipes and costs, materials and where to find them, creatures, bosses, drops, building pieces, biomes, status effects, game mechanics, progression) from Mimir's Well, a reference built from the game's own data. Use for any question about the game Valheim.
---

# Mimir's Well

[Mimir's Well](https://mimir.slackworks.com/) is rebuilt from the Valheim dedicated server's data on every game
update (public branch, vanilla, no mods). Answer from it rather than from memory: numbers change between patches.

## Look things up with the script

`scripts/mimir.py` (Python 3, standard library) downloads the site's JSON and prints only what matches. Run it from
this skill's directory:

```
python3 scripts/mimir.py search frost resist        # names/ids with every word: name | id | kind | stage | page URL
python3 scripts/mimir.py show SwordIron             # the whole entry as JSON, and its page (names work too: "Iron Sword")
python3 scripts/mimir.py get Iron                   # every way to get it: craft, smelt, pick up, mine, drop, chest, trader, spawn
python3 scripts/mimir.py used-in Iron               # recipes, building pieces and smelters that take it, bait
python3 scripts/mimir.py tree SwordIron             # what it takes, back to the start of the game
python3 scripts/mimir.py list items --type Shield   # by kind: items (--type), creatures (--biome), pieces (--type = build tag), effects
python3 scripts/mimir.py --up-to Swamp list items --type Helmet   # only what is available up to a stage
```

Search first when you only have a name, then `show` the id for details. Ids are the game's prefab names.

## Reading the data

- `stage`: the first stage of the progression where a player can get it: Meadows, BlackForest, Swamp, Mountain,
  Plains, Mistlands, AshLands, DeepNorth, PostGame (after the last boss). Missing = not settled.
- `via`: the earliest way to get it: `how` (craft, process, build, source, drop, spawn, ...), `from` (recipe,
  station, source, creature or trader id) and `needs`. `tree` follows it.
- Empty, zero and false values are left out. Damage is per hit at quality 1; `...PerLevel` adds per quality level.
- `unobtainable`, `internal` (creature attacks) and `enemyOnly` entries exist in the game files but players can't
  get them.
- Chances in drops are 0–1 in `show` output (`chance: 0.5` = 50%); `get` prints percent.

## Spoilers

If the user mentions where they are in the game ("I just beat the Elder"), pass `--up-to` with their next stage
(the Elder opens the Swamp) and don't reveal later content unless asked.

## Mechanics

For how something works (damage, comfort, skills, raids, food, drops), read the site's mechanics pages: each is
verified against the decompiled game code. The list with one-line summaries is in
https://mimir.slackworks.com/llms.txt under "Mechanics"; fetch it with Python (`urllib.request`) or a web fetch.

## Linking

Give the page URL that `search` or `show` prints when it helps the user read more.

## If the download fails

The script needs network access to mimir.slackworks.com. In claude.ai, code execution needs network egress with
that domain allowed (Settings → Capabilities). If it is blocked, say so, and fall back to fetching the pages
(https://mimir.slackworks.com/items/<id>.html, creatures/, pieces/, effects/) with a web fetch.
