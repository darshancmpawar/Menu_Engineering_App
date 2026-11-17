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

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.08.01 | 17 Nov | Darshan + Claude Code | Veg / non-veg mark after the dish (screen and Excel); Curd row is plain curd for every client; Rippling kootu moved from Lentils to South Veg Dry, at most once in 8 days, regional days exempt (new `slot_pool_moves`, `except_regional_days`); Corn Papad Masala Majjige split, Cinnamon Pears renamed (Bangalore and Hyderabad); four-week check mirrors Generate; `session` column in every city list, 402 breakfast dishes and nine breakfast categories, a solve sees its own session; regional-day apply skips fixed dishes (all clients); six add-on feature switches per client in `clients.features`. |

**Previous:** [v2.08.00](IkigaiMasala_Final_v2.08.00_2026-11-16.md)  **Next:** —
