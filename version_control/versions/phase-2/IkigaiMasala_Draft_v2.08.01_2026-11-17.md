# Version 2.08.01: Corrections after Rippling's first look

**Phase:** 2 Scaling  **Date:** 17 Nov 2026  **Status:** Draft — awaiting approval

## In one line

The veg / non-veg mark sits after the dish name, the Curd row serves plain
curd for every client, Rippling serves kootu as a veg dry instead of a lentil,
and three dish names in the Bangalore and Hyderabad lists are corrected.

## What changed

### 1. The veg / non-veg mark is after the dish name

On screen the mark now follows the dish name instead of coming before it. In
the Excel download each day has a narrow column after the dish column holding
the mark, and the date heading spans both. A picture cannot sit directly after
text inside one Excel cell, which is why it has its own column. Long typed
lists, such as Rippling's dressings, now wrap onto a second line instead of
being cut off.

### 2. The Curd row serves plain curd, for every client

The Curd row could serve any plain-curd dish: Mixed Curd in Bangalore, and
Mint Curd or Beetroot Curd in other cities. It now serves only "Curd", for
every client in every city. Those other curds stay in the dish list, and the
Raitha row is unchanged.

### 3. Rippling: kootu is a veg dry, not a lentil

- **Kootu never appears on the Lentils row** for Rippling.
- **It can appear on the South Veg Dry row** (kootu is a south dish, so it
  never lands on the North row).
- **At most once in 8 days.** Once in the week being planned, and not within 8
  days of a saved kootu.
- **A regional day is the exception.** On a day you mark as regional, both
  limits lift and kootu may come again.

Only Rippling changes. Every other client still gets kootu as a lentil.

### 4. Dish names corrected (Bangalore and Hyderabad)

- **"Corn Papad Masala Majjige" was two dishes in one row.** It is now
  "Masala Majjige", a welcome drink, and "Papad Corn Masala", a new starter.
- **"Cinnamon Pears" is now "Cinnamon Pears Drink".**

The Bangalore list goes from 5,323 to 5,324 dishes.

### 5. The four-week check follows the app's Generate button

The check that plans four saved weeks in a row for every client now does what
Generate does: it plans each client's own services, each counter avoids only its
own earlier dishes, shared dishes are pinned into the other counters, and each
plan gets the app's time allowance. The old version was stricter than the app,
so it reported failures the planner never meets. Rippling passes all four
weeks.

### 6. Breakfast is its own part of the dish list

Every city list has a new `session` column. Existing dishes say
"lunch,dinner"; the 402 breakfast dishes added to Bangalore say "breakfast".
A plan sees only its own session's dishes, so a breakfast plan is built from
breakfast dishes and lunch and dinner never see them. Nine breakfast
categories are new: Beverage, Breakfast Main, Side, Chutney (chosen daily,
unlike lunch's fixed chutney), Sandwich, Non-veg Sandwich, Snack, Fruit and
Condiment. In the configuration, a breakfast service offers only breakfast
categories. A snacks service shows "Snacks menu bank and solver in
development" instead of a plan.

### 7. Regional days work for clients with fixed dishes

Applying a regional day re-plans that day's dishes for the region. It asked
for every dish of the day, including fixed ones (Rippling's salad, dressing,
chapati, steamed rice), and the planner refuses to change a fixed dish, so the
apply failed for every client that has one. It now re-plans only the dishes
that are not fixed.

### 8. Add-on feature switches per client

A new "Add-on features" section in the configuration has six switches:
regional days, explain the menu, ask the chef, the banned-vegetables section,
the veg / non-veg marker and last served. They are saved with the client.
Turning the banned-vegetables switch off hides the section only; those
vegetables are still kept off every menu. The marker and last-served settings
moved here from Rippling's rules file. **Every switch starts off**, for every
client including Rippling, and is turned on per client as required (owner's
decision). Until then those sections are hidden.

### 9. One counter with different services stays one counter

When a site's services differ (Rippling's breakfast has its own rows), the
configuration saves the counter once per service. The planner counted every
copy for every service, so Rippling showed three counters and planned
breakfast three times, and it was treated as a multi-counter site, which also
changes how a week is saved to history. Counters are now counted within each
service.

### 10. Rippling's breakfast

Breakfast follows the client's sheet as far as the planner can today: Eggs
fixed per weekday ("Boiled Egg, Omelette" Mon/Tue/Thu, "Boiled Eggs" Wed/Fri),
the condiments line fixed daily, the non-veg sandwich on Thursday only and the
veg sandwich on every other day, and the sheet's row names. Plain chapati is
now fixed for lunch and dinner only; set for every session, it was printed at
breakfast too. Non-veg main on Wednesday, three fruits a day, combos and
accompaniments that follow the main come in 2.09.00.

### 11. The 21-day no-repeat looks both ways

A dish saved for a date now keeps it off the 21 days before it as well as
after, at lunch or dinner. Rippling had saved the week's dinners first and
planned lunch afterwards, and lunch reprinted welcome drinks that dinner
served two and six days later. Pinned and fixed items stay outside the rule,
as before.

### 12. Rippling: bread and veg dry

- **Bread row 2 is never plain chapati** (owner, 17 Nov). Only plain chapati
  itself may repeat; before, the whole chapati/phulka family could, so row 2
  repeated ragi phulka within three days.
- **Veg dry stays North and South on Chinese Thursdays.** The Chinese-day
  filter ignored Rippling's exemption and cut the veg dry list to 64 dishes,
  one of them South, so from the second week the South Veg Dry row was
  quietly given a Chinese dish every Thursday.
- **The Curd row no longer warns on North days.** Plain curd has no regional
  cuisine to match.

Checked over 25 days of lunch and dinner (five weeks, each saved before the
next): every week planned, no rule loosened, every Rippling rule held on every
day, and nothing repeated within 21 days.

### 13. Regional days are for lunch and dinner

A regional day changes the lunch and dinner menus only (owner, 18 Nov).
Breakfast and snacks ignore it, both the day's pick and the weekly default.

### 14. Applying a regional day to Rippling failed

On 18 Nov, applying Karnataka, Punjab and Maharashtra to Rippling's week of
23 Nov failed for lunch and dinner with "No feasible plan found". Applying a
region re-plans only the regional days and keeps the rest of the week as it
is. Two things made that impossible:

- **Thursday's veg dry.** Without the fix in section 12, the plan had no South
  dish to put in the South Veg Dry row on Thursday, so it served two North
  dishes there. The re-plan kept Thursday as it was but asked for a South dish
  again. With section 12, a fresh week takes the regional days for lunch and
  for dinner (checked against Rippling's saved history).
- **Weeks saved before 2.08.01.** The dinner week of 23 Nov was saved on
  17 Nov and holds dishes the new rules remove: Mixed Curd in the Curd row
  and a kootu in Lentils on Friday. No re-plan can keep those days. The error
  now names such cells and says to generate the week again.

### 15. One drink base a week

Each drink base (`item_style`) is served at most once a week. Rippling had
served Orange Cooler on Wednesday and Orange Punch on Thursday, both
orange-based. Buttermilk is exempt, because it already has its own rule
(two days a week). This is a Bangalore rule, so Hyderabad and NCR, which
follow Bangalore's rules, get it too.

### 16. Detox and infused waters are Infused Water, not Welcome Drink

Owner, 18 Nov. Ten waters in Bangalore and Hyderabad (Lime Ginger Infused
Water, Detox Water and others) and NCR's Cucumber Detox Water moved from the
Welcome Drink category to Infused Water. Nothing else about them changed.
Welcome drinks: Bangalore 180 to 170, Hyderabad 194 to 184, NCR 43 to 42.

### 17. Papad is chosen by the planner

Owner, 18 Nov. The Papad row used to print the word "Papad" every day. It
now picks a papad from the city's Papad category: a different one each day of
the week, and after that the one served longest ago first. It is not tied to
the day's theme, and Regenerate can change it. A new client still starts
without the row. Chennai has four papads, so a five-day week there repeats
one.

The Papad lists were cleaned first (owner):

- Removed Papad Pickle and Papad Pickle Curd (Bangalore and Hyderabad).
- Removed Veg Raita Masala Papad: it was two dishes, and both are listed
  already (Mixed Veg Raita, Masala Papad).
- Hyderabad: one name per papad. Akki Papad is Akki Happala; Urad Papad and
  Regular Uddina Happala are Urad Dal Papad.

Papads now: Bangalore 11, Hyderabad 14, NCR 6, Pune 6, Chennai 4.

### 18. Rippling's menus for 2-13 November

Owner, 18 Nov. Rippling's lunch and dinner for 2-6 and 9-13 November, served
before the planner, are matched to the dish list so the planner does not
repeat them. `scripts/backfill_rippling_2026-11-02_to_13.sql` saves the 20
days (it can be run twice safely). Each sheet dish is saved as a dish in the
list; for a "main + side" the main only (owner). Infused Water and Papad are
saved too; the owner adds those two rows to Rippling.

59 dishes were not in the Bangalore list and are added, including the
undated event menu's (Goli Soda, Khandvi, Ghewar...). Every field and flag
of each one is set by hand, following how the list files similar dishes.
Jeera Peas Pulao is its own dish, not Green Peas Pulao (owner). New dishes are
named the way the menu writes them, since the list's names are what a menu
prints. A new colour, pink, is added for the guava and rose drinks. With the
saved days in place, the planner's 23 Nov week (lunch and dinner) repeats
nothing served in the 21 days before it.

### 19. Saved weeks open from history for lunch and dinner

Owner, 18 Nov: Rippling's 2-13 November menus were in the database, but
opening 9 November generated a new plan. The planner only reopened a saved
week for clients that plan lunch alone. It now reopens it whenever every
service being planned has that week saved; if one is missing, it generates
all of them, so a saved menu never sits beside a new one. A reopened week
also shows the day themes of the service it belongs to, and the regional
day each date had (Karnataka, Tamil Nadu ...), with its regional dishes
marked, as when it was planned. Saving now keeps each date's regional day;
Rippling's 2-13 November days are filled in from the menu sheet
(`scripts/backfill_rippling_regions_2026-11.sql`: Karnataka on 2 Nov, Italian
on 5 Nov, Tamil Nadu on 9 Nov, Indo-Chinese on 12 Nov).

### 20. Rippling's breads

Owner, 18 Nov:

- **Bread 1 is a chapati, plain or flavoured.** It is no longer fixed to plain
  chapati. Plain chapati may come back within the week, on 2 days at most;
  a flavoured chapati follows the 21-day rule like any dish.
- **Bread 2 is any other bread**: paratha, naan, kulcha, dosa, idli and so on.
- **A dosa every 10 days.** Not within 10 days of the last one, and once 10
  days have passed the week must have one, so the gap is 10 to 14 days. It
  counts lunch and dinner together.
- Bangalore keeps dosas and other South breads to South days, and limits
  Chinese-day bread to chapatis. Rippling has no South day and serves
  parathas on its Chinese day, so for Rippling bread is not tied to the
  day's cuisine, and South breads are allowed on mix and biryani days (not
  the North Friday or the Chinese Thursday).

Checked against the live data of 18 November: both saved weeks reopen for
lunch and dinner with the right themes; the week of 23 November plans for
lunch and dinner with no rule loosened, one dosa each, nothing repeated
within 21 days of the saved menus, and a Karnataka day and breakfast both
plan.

### 21. Rippling's menus for 16-20 November

Owner, 18 Nov. The week's menus as served replace what the planner had
saved for 16, 18, 19 and 20 November, lunch and dinner
(`scripts/backfill_rippling_2026-11-16_to_20.sql`). 17 November is not in the
sheet, so the planner's own saved day stays. Thursday 19 November was a
Malvani day, saved as Maharashtra, the planner's region for it. 28 dishes
were not in the Bangalore list and are added, every field set by hand
(Malvani Masale Bhat, Tandlachi Bhakri, Malvani Vade, Kulith Saar, Chicken
Pandhra Rassa, Shrikhand ...).

Regional days saved with a week always use the planner's own region names:
the 2-13 November sheet's "Italian" day is saved as Continental.

### 22. Rippling: 17 November and 23-27 November left blank

Owner, 18 Nov. The planner's saved 17 November was not what was served, and
23-27 November was saved before the new bread rules: 17 November lunch and
dinner and all of 23-27 November are deleted; 17 November breakfast is real
and stays (`scripts/blank_rippling_2026-11-17_and_23_to_27.sql`, which also
rebuilds the 16 November week records without 17 November). A saved week with
a PAST day nobody saved now opens from history with that day blank (all
clients); a missing day from today on still means a fresh plan.

## What this does not do

- **The switches need one database change.** Until `features` is added to the
  clients table (`scripts/setup_all.sql`), every switch reads as off and
  saving one does not stick.
- **Breakfast dishes have no `item_style` yet.**
- **Breakfast sambar has four dishes,** so a Sambar row every breakfast cannot
  fill a five-day week. To be decided with the owner.
- **Two breakfast sandwiches** (grill veggies, hummus veggies) are filed as veg
  with protein "egg", so they are treated as non-veg.
- **The swap list on screen still shows kootu under Lentils for Rippling.** A
  planner can still pick one by hand there. The planner itself never puts one
  there.
- **Saved history keeps the old names** ("Corn Papad Masala Majjige", "Cinnamon
  Pears"), as decided for 2.08.00. Those dishes count as new for one cycle.
- **Masala Majjige and the existing Masala Buttermilk are the same drink under
  two names.** They are kept apart, as written.
- **Rippling's weeks saved before 2.08.01 cannot take a regional day** until
  they are generated again (on hold, owner).
- **The moved waters keep their client tags** (Cloudera, MOengage,
  Booking.com; Junglee Games in NCR).
- **Saved menus show "Papad"** for the weeks before this change.

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.08.01 | 17 Nov | Darshan + Claude Code | Veg / non-veg mark after the dish (screen and Excel); Curd row is plain curd for every client; Rippling kootu moved from Lentils to South Veg Dry, at most once in 8 days, regional days exempt (new `slot_pool_moves`, `except_regional_days`); Corn Papad Masala Majjige split, Cinnamon Pears renamed (Bangalore and Hyderabad); four-week check mirrors Generate; `session` column in every city list, 402 breakfast dishes and nine breakfast categories, a solve sees its own session; regional-day apply skips fixed dishes (all clients); six add-on feature switches per client in `clients.features`; counters counted per service; Rippling breakfast rows; 21-day no-repeat looks both ways; Rippling bread row 2 never plain chapati and veg dry North/South on Chinese days; plain curd not theme-filtered; regional days for lunch and dinner only; a re-plan that cannot keep a saved dish names it; one drink base a week, buttermilk aside (Bangalore); detox and infused waters moved to Infused Water; Papad chosen by the planner, Papad lists cleaned; Rippling's 2-13 Nov menus saved, 59 dishes added; pink item colour; saved weeks reopen for every service, with their regional days; Rippling bread 1 a chapati, bread 2 any other bread, a dosa every 10 days; Rippling's 16-20 Nov menus saved, 28 dishes added; Rippling 17 Nov and 23-27 Nov left blank, a past day nobody saved opens blank. |

**Previous:** [v2.08.00](IkigaiMasala_Final_v2.08.00_2026-11-16.md)  **Next:** —
