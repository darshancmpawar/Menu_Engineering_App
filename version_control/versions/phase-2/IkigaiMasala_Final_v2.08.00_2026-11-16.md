# Version 2.08.00: A client's own menu, a style for every dish, and a cleaner Bangalore list

**Phase:** 2 Scaling  **Date:** 16 Nov 2026  **Status:** Final — approved by Darshan, 16 Nov 2026

## In one line

Rippling's menu now comes out the way their requirement sheet describes it —
their rows, their names, a fixed salad bar for each day, a veg / non-veg mark on
every dish and when each dish was last served — and the Bangalore dish list has
lost 395 duplicate entries and 72 misspellings.

## What changed

### 1. Rippling, set up from their requirement sheet

Rippling serves lunch and dinner. Everything below is in their own client
file, so no other site's menu changes.

- **Two veg dry dishes a day, north first and south second, whatever the
  day's theme.** Each row is now held to its own kind. Before, the planner only
  made sure one of each appeared somewhere in the two rows, so "North Veg Dry"
  could hold a south dish, and on a North-themed day (Rippling's Friday) the
  south row had only north dishes to choose from.
- **Chicken every day, and an egg dish as well on Wednesday.** The row named
  "NonVeg Main (Egg)" is empty on the other four days.
- **Curd and raita are two separate rows.** The Curd row is plain curd and the
  Raitha row is always a raita. The editor used to refuse to save a counter with
  both; that check is gone.
- **Two Indian breads.** The first is plain chapati every day; the second
  changes.
- **Sambar / Rasam is one row.** Rasam on three days and sambar on two, and the
  biryani day is always rasam. That holds even on a two-week plan. Before, the
  second Monday of a fortnight would have been given sambar.
- **No cut fruit, and no fruit served on its own as dessert.** Eleven dishes are
  affected. Fruit custard, fruit kesari and banana halwa are still allowed.
- **The make-your-own salad and the dressings are fixed for each weekday**, the
  same every week, with different lists for lunch and dinner. They print exactly
  as the client wrote them. Rippling runs one counter with two sessions, so a
  client's fixed items can now differ by session on the same counter.

### 2. Rippling's menu looks the way they asked

- **Their rows, in their order, under their names.** The rows run Welcome
  Drink, Make Your Own Salad, Dressing, Soup, Indian Bread, Flavoured Rice,
  Steamed Rice, North Veg Dry, South Veg Dry, Vegetable Gravy, Lentils,
  Sambar / Rasam, Curd, Raitha, NonVeg Main (Chicken), NonVeg Main (Egg) and
  Dessert.
- **A veg or non-veg mark in front of every dish**, on screen and in the Excel
  download. A green square with a leaf means veg; a red square with a drumstick
  means non-veg. They follow the picture the client sent. They were redrawn
  rather than copied, because the picture was a watermarked stock-photo preview.
- **When each dish was last served.** Under every dish it says, for example,
  "Last served 18 Nov (21 days ago)", or "New" if it has not been served in the
  past year. The count runs back from that dish's own day, and both lunch and
  dinner count. Steamed rice and anything fixed by the client's settings show
  nothing.

Only Rippling has these switched on. Any other client can have them by adding
the same settings to their file.

### 3. A salad bar with chicken in it is no longer shown as veg

A fixed line typed into a client's settings, such as "…, boiled peanuts,
millets, pesto chicken" in the salad row, used to be shown as vegetarian. The
planner only knew a dish was non-veg if it came from the dish list or sat in the
non-veg row.

It now reads such typed lines, and marks them non-veg when they name chicken,
egg, fish, mutton or similar. Dishes from the list are never read this way. 43
vegetarian dishes have one of those words in their names, such as soya keema
pulao and an eggless red-velvet pastry, and they stay veg.

This applies to every client, because it corrects a dietary error.

### 4. Every Bangalore dish has a style

The Bangalore list has a new column, `item_style`, filled in by hand for all
5,323 dishes. Two dishes share a style when a guest who saw both in one week
would say "that again". For example, clear soup and clear veg soup share one
style, and so do the two carrot soups.

This is the groundwork for the variety complaint: "Clear Soup, Veg Clear Soup
and Veg Soup in the same week". The rule that will use the column (at most one
dish of each style a week) is **not** switched on yet.

The other four cities have the column with a rough value for rice and soup
only.

### 5. The Bangalore dish list was cleaned

At the owner's request:

- 72 misspelt names were corrected.
- 395 entries that were the same dish under a second name (for example clear soup
  and clear veg soup, or seven spellings of chole masala) were merged into one.
- `redc_rice` (a misspelling of red rice) was removed at the owner's request.
- "Plain curd and mix veg raita" was removed: it is two dishes in one row, and
  both already exist on their own (curd, and mixed veg raita).
- A dish named just "flavoured rice" was removed: that is the name of the row,
  not a dish, so the menu told the kitchen nothing.
- **Plain rice can no longer be served as Flavoured Rice.** Flavoured Rice is
  every rice except plain rice, which belongs in the Steamed Rice row. Boiled
  rice, white boiled rice, plain basmati and jasmine rice were filed among the
  flavoured rices and could have been picked; they are now kept out, like
  steamed rice already was.
  The correct name was already taken by a healthy-rice dish.
- The list went from 5,721 dishes to 5,323. Nothing else in the list was
  changed.
- Each change is recorded with its reason, and a copy of the list as it was is
  kept.
- 167 entries the cleanup was not sure about were left untouched and listed for
  the owner to decide on.
- Rippling serves eggless mayo, so a dressing with mayo is correctly marked veg.

### 6. Smaller fixes, and a four-week check for every client

- **"Pick a dish" failed on Windows**, with a misleading "unknown client"
  error. The messages formatted their dates in a way only Linux accepts. They
  now work everywhere.
- **"Pick a dish" judged the plate with the picked dish blank.** The plate
  checks looked dishes up by name with the colour tag still attached (for
  example "paneer tikka masala (R)"). So the new dish counted as having no
  colour, texture or protein. Swapping one red dish for another could warn
  "only 3 colours on the plate". Dishes are now looked up without the tag.
- **The theme editor kept its own list of weekdays**, against the rule that
  every part of the planner reads the one shared list. It now reads the shared
  list.
- **A Corning Chakan test expected the dinner to fail** under Pune's
  one-Chinese-dish-a-week limit. The dinner now plans, so the expectation was
  out of date, and it was removed.
- **A new check plans four saved weeks in a row for every client**: lunch for
  every counter, then dinner without lunch's dishes, saved each week, so each
  week sees the history of the weeks before. One week with an empty history,
  which is all the existing checks plan, cannot show a site that runs out of
  dishes in week three.

## What this does not do

- **Saved menus keep the old names, by decision.** The owner chose to count
  history from the new list onward rather than rewrite past menus. A saved
  dish whose name was corrected or merged no longer matches anything, so for
  one three-week cycle it can come back sooner, and "last served" treats it as
  new. 20 saved names are affected, 11 of them Rippling's.
- **The one-style-a-week rule is not on.** The column exists; nothing uses it
  yet.
- **"Last served" covers one year.** A dish last served longer ago shows as
  "New".

## Change tracking

| Version | Date | Author(s) | Principal changes / reason |
|---|---|---|---|
| 2.08.00 | 13–16 Nov | Darshan + Claude Code | Rippling configured from the client's requirement sheet; per-client menu layout with veg / non-veg markers and last-served dates; combination half pinned by theme; free-text non-veg reading; fixed items per session on one counter; `item_style` column; Bangalore list cleaned (5,721 → 5,323). |

**Previous:** [v2.07.04](IkigaiMasala_Final_v2.07.04_2026-10-14.md)  **Next:** [v2.08.01](IkigaiMasala_Draft_v2.08.01_2026-11-17.md)
