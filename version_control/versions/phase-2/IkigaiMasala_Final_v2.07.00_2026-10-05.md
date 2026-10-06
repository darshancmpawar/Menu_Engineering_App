# Version 2.07.00: Seasonal high-risk vegetables

**Phase:** 2 Scaling  **Date:** 5 Oct 2026  **Status:** Final

## In one line

The vegetables a city should not be serving this month are taken out of the
menu before the planner sees them, and the kitchen is told what to do about
the ones that stay.

## Why this version was needed

Every year a list goes round naming the vegetables that are risky in each
region each month — the monsoon bhindi that arrives full of worms, the
cauliflower nobody can clean in August, the lettuce that will not survive the
journey in October. Until now that list lived in a spreadsheet and in the head
of whoever remembered to look at it. The planner knew nothing about it, so a
menu could be generated, approved and cooked with a vegetable on it that the
company had already decided not to buy that month.

Catching it afterwards is the expensive way: by the time anyone notices, the
menu has been circulated and the purchase order is out.

## What's new

### 1. The month's red list is removed before the solver sees it

Each city maps to a region — Bangalore to Karnataka, Chennai to Tamilnadu,
Hyderabad to AP & Telangana, Pune to Maharashtra, NCR to North — and each
month's red list for that region is taken out of the candidate dishes, the
same way a banned ingredient already was. Nothing downstream has to know; the
dishes are simply not offered.

The list is resolved **per date**, not per plan, so a week running from 28
October to 3 November uses October's list for the first four days and
November's for the rest.

### 2. It is a floor the dish list can actually take

Measured across all five cities, twelve months and every food category: the
red list removes between 1.6% and 8.7% of a city's dishes in a month, and
**never empties a category**. It leaves one category thin, once — Pune's
infused water in June, down to one dish, because cucumber is red that month.

A category that would run empty or thin is reported in the pre-flight check
before anyone presses Generate, naming the month, the list and the count.

### 3. The yellow list bends instead of banning

A second list per month is "avoid where possible". Those dishes stay
available, but the solver is penalised for choosing one, so it steers away and
still has them when a category would otherwise run short. A hard ban on both
lists would have emptied categories that the measurement shows are already
thin.

### 4. A pinned dish stays, and the kitchen is told

If a client has pinned a dish that contains a red vegetable — Amadeus pins a
green salad, and lettuce is red in Karnataka in October — the dish is **not**
removed. Removing it would silently drop a pin the client asked for. Instead
it stays on the menu and the seasonal panel names it, because the kitchen
makes that salad without the lettuce.

The same reasoning covers mixed-vegetable dishes: their contents are not
listed anywhere, so they are never matched, and the panel says plainly that
the kitchen leaves the red-list vegetables out of them.

### 5. A panel on the planner, with notes written for this week

A closed panel at the top of the planner shows the month's red list (with how
many dishes each vegetable costs), the yellow list, the sheet's own advice
("replace Indian cucumber with English cucumber"), the suggested alternatives,
and any pinned dish that clashes.

Opened after a menu exists, it also has a model write kitchen notes against
**this week's actual dishes** — which day, which dish, what to do. Every note
is checked against the month's list and the week's menu before it is shown; if
the model is off, unreachable, or cannot produce something that passes, the
panel falls back to the sheet's own notes and says so.

The panel is closed by default and does nothing until opened, so a planner who
never opens it pays nothing.

### 6. The sheet is the source, and the script is the only way in

`scripts/build_seasonal_bans.py` turns the workbook into the reviewed JSON the
system reads. It prints a report of everything a human should look at before
the result is committed, and the generated file says plainly not to hand-edit
it. A vocabulary of 50 vegetables maps each one to the dish-name words and
ingredient values that identify it, in the local names a dish list actually
uses — gobi, baingan, vankaya, bendakaya, dosakai — and carefully: "patta
gobi" is cabbage, not cauliflower.

## What this means for day-to-day use

Nothing to switch on. Generate a menu as usual and the month's red-list
vegetables are already absent. Open the panel at the top of the planner to see
which vegetables those were, what to use instead, and which pinned dishes need
a word with the kitchen.

If a category is going to struggle in a particular month, the pre-flight check
says so before you generate, not after.

## Known limits

**The sheet's own conflicts are kept as bans.** In 26 month-and-region cells
the source sheet lists a vegetable as both in season and high risk. The build
script keeps those as red, which is the safe direction — a banned vegetable
costs variety, a served one costs a complaint — but it is a judgement the
sheet should settle. The report naming all 26 is produced by the build script
and should be reviewed with whoever owns the list.

**A dish is matched by its name and its main ingredient, nothing else.** A dish
whose name does not say the vegetable and whose recorded main ingredient is
something else will not be caught. The month's notes and the mixed-vegetable
line exist to cover exactly that gap at the stove rather than in the data.

**One sheet, one year.** When a new year's sheet is late, the previous year's
list for the same month is used rather than banning nothing, and the panel
names the sheet it is reading.

**Kitchen notes need a model key.** Without one the panel shows the sheet's
own notes, which is the same thing it shows before a menu exists.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.07.00 | 5 Oct | Darshan + Claude Code | **Seasonal high-risk vegetables.** (1) Per-date red list removed before the solver, per-city region mapping, yellow list as a soft penalty. (2) Client pins and mixed-vegetable dishes deliberately kept, and named in the panel. (3) Planner panel with the month's lists, counts, alternatives and model-written kitchen notes checked against the week's menu. (4) Reviewed JSON built from the sheet by a script that reports what a human must check |

**Previous:** [v2.06.00](IkigaiMasala_Final_v2.06.00_2026-10-05.md)  **Next:** [v2.07.01](IkigaiMasala_Final_v2.07.01_2026-10-06.md)
