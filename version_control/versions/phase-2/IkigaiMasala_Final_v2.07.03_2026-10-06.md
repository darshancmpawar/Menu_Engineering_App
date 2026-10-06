# Version 2.07.03: Cadences that are floors too, a season, and dinner that copies lunch

**Phase:** 2 Scaling  **Date:** 6 Oct 2026  **Status:** Final

## In one line

"Once in fifteen days" now also means "at least once", mango is served only in
its season, Corning Chakan's dinner repeats the lunch dessert, soup and bread,
and the last references to the deleted correction chain are gone.

## What changed

### 1. A cadence is a floor as well as a ceiling

"Khichdi once in fifteen days" was shipped as a ceiling only — no second
khichdi inside the window — and a ceiling is satisfied by serving **none**.
The dish could have disappeared for months with the rule reading as enforced.

That is the same defect v2.07.01 found at this site, where sprouts gravy was
written as "no more than twice" for a guideline asking for "at least twice". A
cap written where a floor was asked for is worse than a missing rule, because
nobody goes looking for it.

Cadence rules can now carry both halves. Once the dish family has not been
served for its window, the next menu must serve one. Measured end to end:

| Khichdi last served | This week's menu |
|---|---|
| never | khichdi served |
| 5 days ago | none — the ceiling holds |
| 14 days ago | none — the ceiling holds |
| 15 days ago | khichdi served — the floor fires |
| 40 days ago | khichdi served |

It is **opt-in**, and that matters: there are fourteen such cadences across
the fleet — biryani, kadhi, kofta, mutton, fish, special sambar, oil-based
bread — and every one of them is still a ceiling only. If any of those also
means "and it must actually appear", say which and it is a one-line change
each.

**Khichdi itself moved from three weeks to fifteen days** at the same time, on
the site's correction.

### 2. Mango is served from March to June and not otherwise

A new kind of rule: one scoped to the **months of the year**. Rules could
already be scoped to a cuisine day or to named weekdays, and neither can say
"only in season". Applies to every city.

The dish list is read by **ingredient**, not by the English word, and that is
what makes it work: the rule catches `mavinakayi_chitranna`, `mavinakayi_rasam`
and `mavinakayi_saru` (Kannada), `masala_mangai_sadam` (Tamil), `aam_panna`,
`aam_ras` and `aam_ki_sabzi` — eight dishes in the Bangalore list alone that
searching for "mango" would never find.

**And it deliberately does not catch a mangodi**, which is a dried moong-dal
dumpling and not a fruit. NCR carries five of them; a careless match would have
taken all five off the menu for eight months of the year.

Measured before switching on: mango is 0.6%–1.5% of each city's list, and at
worst 9.3% of a single category (NCR's welcome drinks). Nothing runs short, and
on a day where a category would have nothing else the dish stays and the
explanation says so.

### 3. Corning Chakan's dinner repeats the lunch dessert, soup and bread

The planner's rule until now was the opposite: every lunch dish is kept off
dinner, on every day of the week, so the three categories this site wants
identical were the three it worked hardest to keep apart.

Those three now carry over — the same dessert, the same soup, the same bread,
on the same day — while everything else still varies. Verified on a real
seven-day pair of menus: every dessert, soup and bread matched, and every rice
and vegetable gravy differed.

It is a per-client setting, off for everyone else.

### 4. The deleted correction chain's last 89 references

The chain that used to rebuild the city workbooks was deleted when the owner's
cleaned lists became the source. Eighty-nine mentions of it survived across
thirty files, each naming a script nobody can open — and **three of them were
instructions**:

- a document told the reader to run nine of those scripts over the city
  workbooks. That is now the one thing the project forbids, because the
  chain's job was injecting dishes and every one would be an unrequested
  change to the owner's data. Replaced with what is true now: the workbooks
  are the source, nothing writes to them, and a thin list is a normal state;
- the operations guide told you to run the normaliser over a new city's list.
  A new city now arrives as a finished workbook, and if it is not in that
  shape that is a conversation with whoever owns it;
- a test's failure message told you to run a script that does not exist, at
  exactly the moment a reader needs it to.

Two committed files — the pool-token map and the client test fixtures — were
produced by that chain and now have no generator. Each says so at its own top,
because "GENERATED, do not hand-edit" above a file with no generator is worse
than no note at all: the fixtures fell five clients behind the live table last
time they drifted, and nothing will catch that now except somebody reading
both.

## What this means for day-to-day use

Nothing to switch on. Khichdi comes round at Corning Chakan instead of merely
not coming round twice; mango appears only from March to June; and that site's
dinner prints the same dessert, soup and bread as its lunch.

## Known limits

**"Once in fifteen days" guarantees twenty-one.** The floor says "somewhere in
this plan", not "on this date", so a dish that falls due on a Monday may be
served on the Sunday. Pinning the date would buy six days and fix khichdi to
one weekday for ever.

**The other thirteen cadences are still ceilings only** — see above.

**Corning Chakan still serves steamed rice and a flavoured rice on the same
day.** Unchanged from v2.07.02 and still the one open item from that round: it
needs either the days named, or a change to how the planner fills a slot.

**Six sites cannot plan a third consecutive saved week.** Found while measuring
something else and worth saying plainly: Corning NCR, Junglee Games, Sinch NCR,
Stryker NCR, TCL and ToastTab CHN all fail on week three once weeks one and two
are saved, and they fail at the old twenty-day window as well as the new
twenty-one, so this is not new and not caused by that change. It is a pool-depth
problem and wants a pass of its own.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.07.03 | 6 Oct | Darshan + Claude Code | Cadence rules gain an opt-in FLOOR (`at_least_once_per_window`) — a ceiling alone is satisfied by serving none, the sprouts-gravy defect of 2.07.01 in a second place; khichdi retuned 21 → 15 days. New month axis (`allowed_months`) and a universal mango rule led by `key_ingredient`, which catches the Kannada, Tamil and Hindi names and excludes `mangodi`. Per-client `meal_shared_categories`: Corning Chakan's dinner repeats the lunch dessert, soup and bread while everything else still varies. 89 dangling references to the deleted correction chain removed, including three live instructions to run scripts that no longer exist |

**Previous:** [v2.07.02](IkigaiMasala_Final_v2.07.02_2026-10-06.md)  **Next:** —
