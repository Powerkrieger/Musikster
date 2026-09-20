# 3D prints

Everything here is a PrusaSlicer project (`.3mf`), so it carries its print settings and colour
assignments along; open it in PrusaSlicer and slice. Both files are templates: they get
personalized by the scripts in `scripts/`, and the per-person result lands in
`people/<slug>/stl/`.

| File | What | Script | Print |
|---|---|---|---|
| `rock_on_coin.3mf` | Game token: a Ø25 × 2 mm disc, "rock on" hand on the underside | `uv run make_tokens.py <slug>` engraves the person's initial into the top | **32×** per person |
| `musikster_box.3mf` | Card box: tray and sliding lid with a recess that fits one of the coins | `uv run make_box.py <slug>` engraves "<Name>s / Musikster" on lid and bottom | 1× per person |

## Game token (`rock_on_coin.3mf`)

Origin: [Hitster coin (muntje)](https://www.printables.com/model/1446487-hitster-coin-muntje)
on Printables. The hand symbol on the underside is a colour modifier (extruder 1, the disc is
extruder 2) made from
["Hand With White Outline Forming A Rock On Symbol"](https://www.svgrepo.com/svg/171045/hand-with-white-outline-forming-a-rock-on-symbol)
from SVG Repo, embedded in the project as
`3D/hand-with-white-outline-forming-a-rock-on-symbol-svgrepo-com.svg`. Check both pages for
licence terms before redistributing prints.

Don't print the template as is — run `uv run make_tokens.py <slug>` in `scripts/` first. It
cuts the person's initial (`person.json` `"tokenLetter"`, default: first letter of `"name"`)
0.6 mm deep into the top face, so different people's tokens can be told apart when decks are
mixed. Then, in PrusaSlicer, add instances until you have **32** (select the object, press `+`
or set the count in the right-click menu) and slice. On a single-extruder printer either
delete the hand modifier for a plain disc, or add a colour change (M600) after the first
1 mm and swap filament by hand.

## Card box (`musikster_box.3mf`)

Origin: the lid and tray come from
[Parametric sliding lid box](https://www.printables.com/model/425966-parametric-sliding-lid-box)
on Printables (a replicad configurator; the exported body is `Shape(2).stl` in the project),
sized for the deck's cut cards. On top of that, by hand in PrusaSlicer: a built-in box shape
extending the tray, the coin above as a negative volume so one token sits flush in the lid,
and the label with PrusaSlicer's text tool in Z003 (the URW Zapf Chancery clone from
`fonts-urw-base35`) — which is why `make_box.py` needs that font installed.

Don't print the template as is — its label reads "Name / Musikster". Run
`uv run make_box.py <slug>` in `scripts/` and print `people/<slug>/stl/musikster_box.3mf`
(see the repo README, "Printing notes", for what the script does with long names).
