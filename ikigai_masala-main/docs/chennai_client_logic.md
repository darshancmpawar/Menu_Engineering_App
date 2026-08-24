# Client Logics — Chennai

Per-client menu requirements for Chennai, mapped against what the tool enforces.
City-level rules live in `data/configs/city_rules/chennai.json`; Bangalore's
clients are in [`client_logics.md`](client_logics.md) and Pune's in
[`pune_client_logic.md`](pune_client_logic.md).

**Sources:** `data/raw/source_workbooks/chennai_menu_items_raw.xlsx` (361 raw items, normalised to
`data/raw/city_items/chennai.xlsx`; now 352 after `scripts/remove_generic_rows.py` dropped 9 rows
named for a category, not a dish) and `data/raw/source_workbooks/chennai_sample_menu.xlsx`, sheet
`Toasttab`. Scope is **lunch**.

**Implementation:** the `"ToastTab CHN"` entry in
`data/configs/client_rules.json`. Asserted end to end by
`tests/test_chennai_client_logic.py`; the city ruleset by
`tests/test_chennai_rules.py`.

---

## What kind of source this is

Pune arrived with a written rulebook — 70 numbered rules, of which 33 are
enforced. **Chennai did not.** What arrived is an item list plus one client's
*service history*: seven days of what was actually served. So every rule below
was **read off the grid**, not transcribed, and the city ruleset is deliberately
limited to the engine skeleton plus caps provable from the item list.

A Chennai rulebook is still outstanding. The regional questions it would settle —
which kuzhambu on which day, poriyal/kootu rotation, rasam cadence, whether
Friday is fixed — are not inferable from seven days.

---

## ToastTab CHN

One counter, five service days (`serve_weekends` is false — the sample skips
Sat 04 and Sun 05 Jul), `source_pools: []` (the whole Chennai list; every row is
tagged `common`).

### The sample week

Seven service days across two part-weeks, read as served.

| | Wed 01 | Thu 02 | Fri 03 | Mon 06 | Tue 07 | Wed 08 | Thu 09 |
|---|---|---|---|---|---|---|---|
| Starter | Kalan soup | Cucumber salad | Cucumber mint salad | Green salad | Boil black chenna | **Raitha** | Cabbage soup |
| Bread | Chappathi | Aloo paratha | Chappathi | Chapathi | Butter kulcha | Kothu paratha | Paratha |
| Veg gravy | Nilagiri kurma | Punjabi dal | Tomato thokku | Chenna masala | Mix veg curry | Brinjal masala | Pattani kurma |
| Kuzhambu / sambar / dal | Kara kuzhambu | Dal makhani | Sambar | Kadamba sambar | — | — | More curry |
| Veg dry | Vaazha thanda kootu | Veg jalfrize | Soya chukka | Perkangai kootu | — | Chilli baby corn | Yam kara poriyal |
| Rice | **White rice** | **Peas pulao** | **White rice** | **White rice** | **Ghee bisibellabath** | **Veg biryani** | **White rice** |
| Sour | Rasam / curd | Curd rice | Rasam / curd | Jeera rasam / curd | Rasam rice + curd rice | Curd rice | Rasam / curd |
| Non-veg | Egg kurma | Chicken do payasa | Fish kuzhambu | Chicken masala | Butter chicken masala | Chicken briyani | Egg thokku |
| Dessert | Dry sweet | Jelabi | Broken wheat kesari | Kalkhandu pongal | Gulab jamun | Dry sweet | Ladoo |
| Papad | Appalam | Appalam | Appalam | Appalam | Appalam | Appalam | **Potato chips** |

Every dish resolves to a real row in `chennai.xlsx` — nothing in the sample is
missing from the list. Matching needs the workbook's own `Mapping_Log` sheet plus
transliteration tolerance: `chappathi`→`chapati`, `jelabi`→`jalebi`,
`raitha`→`raita`, `chicken_briyani`→`chicken_biryani`, `perkangai_kootu`→
`peerkangai_kootu`, `ghee_bisibellabath`→`ghee_bisibelebath`, `ladoo`→`laddu`,
`chilli_baby_corn_sauce`→`chilli_baby_corn`, `boil_black_chenna`→
`boiled_black_chana`, `mixed_veg_kothu_paratha`→`veg_kothu_parotta`.

### The two readings the rest follows from

* **Exactly ONE rice per day, and the theme decides which.** White rice on all
  four South Indian days; a flavoured rice (peas pulao, ghee bisibelebath, veg
  biryani) on the north and biryani days. Never both, never neither — 7/7. This
  is the same structure Amadeus Pune has, arrived at independently.
* **The sour component follows the rice.** `RASAM / CURD` (one cell the source
  workbook auto-split into two servings) on the four white-rice days; `CURD RICE`
  on the three flavoured-rice days. With no plain rice to eat rasam with, the
  sour component moves — 7/7. The biryani day takes a **raita** rather than a
  rasam.

### Rule-by-rule

| # | Read from the sample | Status | How |
|---|---|---|---|
| 1 | White rice on South Indian days only | DONE | `toast_tab_chn_white_rice_south_days` — `slot_day_restriction`, `[mon, thu, fri]` |
| 2 | Flavoured rice on north and biryani days only | DONE | `toast_tab_chn_flavour_rice_north_biryani_days` — `[tue, wed]`, the complement of #1 |
| 3 | Rasam on the white-rice days | DONE | `toast_tab_chn_rasam_south_days` — `[mon, thu, fri]` |
| 4 | Curd beside the rasam; raita on the biryani day | DONE | `toast_tab_chn_curd_side_south_and_biryani_days` — `[mon, wed, thu, fri]` |
| 5 | Curd rice on the flavoured-rice days | DONE | `toast_tab_chn_curd_rice_north_biryani_days` — `[tue, wed]` |
| 6 | Bread is always a wheat flatbread, never dosai/idly | DONE | `toast_tab_chn_bread_is_a_wheat_flatbread` — one-slot `slot_composition` component on `any_flag: [is_plain_phulka_chapathi, is_paratha, is_maida_bread, is_tandoori_roti]` |
| 7 | Maida bread on most days, not one a week | DONE | `maida_bread_weekly` overridden to `max: 3` (see below) |
| 8 | Non-veg every day | DONE | falls out of configuring `nonveg_main: 1` with no day restriction |
| 9 | Bread / dessert / papad every day | DONE | same — no restriction needed |
| 10 | Two veg gravies + one veg dry a day | DONE | `slot_counts` — `veg_gravy: 2`, `veg_dry: 1` |
| 11 | Chicken biryani on the biryani day | DONE | city rule `nonveg_biryani_weekly` (max 1) plus the biryani theme |

### The one assumption

The sample spans two part-weeks whose weekday→theme mapping **conflicts**:

| | Wed | Thu |
|---|---|---|
| week of 01 Jul | south | north |
| week of 06 Jul | **biryani** | **south** |

So no stable weekday→theme map exists in the data. The map used is inferred from
the later, more complete run (06–09 Jul):

```
Mon south · Tue north · Wed biryani · Thu south · Fri south
```

That fits 5 of the 7 observed days and reproduces the sample's 4 south : 2 north
: 1 biryani ratio scaled to a 5-day week. **The weekday lists in rules 1–5 follow
from this map** — what the sample actually determines is the *theme* each slot
belongs to, so if the real map differs, those lists move with it.

### Two conflicts the pre-flight gate caught

Both were real, and both were reported as blocking errors before any solve ran —
worth recording because they are the gate doing its job on a new city.

* **`maida_bread_weekly` vs the bread composition.** Chennai's city rule caps
  refined-flour bread at one day a week. But only 5 of the 20 wheat flatbreads in
  the whole 29-dish pool are non-maida (and 3 of those are chapati variants),
  while the sample serves a maida bread on **4 of 7 days** — aloo paratha, butter
  kulcha, kothu parotta, paratha. Requiring a wheat flatbread daily therefore
  forces maida past a cap of 1. Resolved by overriding the cap to 3 for this
  client, not by disabling it: "unlimited refined flour" is not what the sample
  shows either.
* **The bread cuisine lock.** `theme_slot_filter` locks bread to the day's
  cuisine, which narrowed Chennai's bread pool to the 10 south-tagged rows on a
  South Indian day — the dosai/idly family. The sample serves *chappathi* on its
  south days, so the lock contradicts the client. `chennai.json` lists `bread` in
  `exempt_slots`; that required an engine fix, because the lock ran ahead of the
  exemption check and could not be switched off at all (see below).

### Data notes

Findings that are not bugs in this client's config but are worth knowing.

* **Fish now has a real place in the taxonomy** — it used to be filed under
  `chicken_*`. The master grew up around a chicken-and-egg non-veg list, so the
  import filed all 8 fish dishes under the nearest chicken bucket:
  `fish_kuzhambu` came through as `sub_category: chicken_south_coastal`,
  `key_ingredient: chicken`, carrying `is_south_chicken_gravy`. Only
  `primary_protein` was right. `scripts/seafood_taxonomy.py` adds `is_seafood` +
  `is_fish_dish` to every city workbook and repairs the rows — see the seafood
  section below.
* **26 of 28 desserts are tagged `cuisine_family: north_indian`**, only badusha
  and mysore_pak south. `payasam`, `semiya_payasam` and all three kesaris are
  South Indian and filed north. `dessert` is exempt from the theme filter, so
  this changes nothing today — but a south day would otherwise have had a
  two-dish dessert pool, which made any week with 3+ south days infeasible.
* **`kalkandu_pongal` is filed as `rice`**, and the sample serves it as Monday's
  dessert. Sweet pongal is a dessert; the row is in the rice pool.
* **`tomato_thokku` is filed as `accompaniment`** and the sample serves it in the
  veg-gravy position.
* **`kootu` is its own `sub_category`** (7 rows) but `course_type: veg_gravy`, so
  a south day's "veg dry" position is often a kootu the ontology counts as a
  gravy. `kootu_twice_weekly` targets the sub-category for exactly this reason.
* **11 items carry a provisional classification** (`brinjal`, `chutney`,
  `dry_sweet`, `sweet`, `milk_sweet`, `veg_gravy`, `toast_salad`, `local_salna`,
  `darbar_soup`, `chicken_chindamani`) — generic source names the workbook could
  not resolve to a known dish. `dry_sweet` and `sweet` appear in the sample, so
  they are real menu rows, just unspecific.

---

## The four clients that arrived with a stated rule set

`data/raw/source_workbooks/chennai_client_structure.xlsx` is a different kind of
source from ToastTab's history: **`Sheet1` states the rules in the client's own
words**, and each client's own sheet holds a sample week that verifies them. So
these four are transcribed rather than inferred, and where a stated rule and its
sample disagree the config follows the sentence and the disagreement is recorded.

A fifth client, **RNTBCI**, is listed on `Sheet1` with nothing beside it and its
own sheet is empty. It is on hold at the client's request; its six counters plan
from the city ruleset alone.

Full rule-by-rule tables are in [`client_rules_index.md`](client_rules_index.md).
What follows is what each client taught the tool.

### TCL — one counter, seven days

Thirteen stated rules, and the only Chennai site that serves Saturday and Sunday.
Both weekend days run a **reduced menu** — Saturday has no dal, sambar, rasam,
dessert, salad or non-veg and serves one rice instead of two; Sunday drops the
veg dry, dessert, curd rice and non-veg and serves white rice instead of a
flavoured one. Ten day restrictions carry that, and one of them needed a new
capability: `slot_day_restriction` could only stand down a whole slot family, so
"two rices on a weekday and one on Saturday" was inexpressible until
`slot_indices` was added.

Two of the thirteen are about which SLOT holds what rather than about the menu:
"in dal need to give only Kootu item" (see below) and "in salad need to give only
KUZHAMBU item". All 13 Chennai kuzhambus are `veg_gravy` — a tamarind gravy is
not a salad — so the client's kuzhambu row is a second gravy, and the DB change
is recorded rather than the ontology bent.

One stated rule contradicts its own sample: "welcome drink will be buttermilk
twice a week", against a week whose five drinks are all buttermilks (BUTTERMILK /
SAMBARAM / INJI MOORU / BUTTERMILK / NEER MOORU — `sambaram` and `tadka_neer_mor`
both carry `is_buttermilk`). Configured as stated.

### Gartner — one counter, four rules, all about rice

"On chinese day we will not serve indian bread we will serve white rice and
flavoured rice", "when there is white rice no flavour rice (except chinese day)",
"white rice will be served weekly twice excluding chinese day". Three sentences
describing one weekly shape, and the sample settles it 5/5 — so they are encoded
as three complementary day restrictions (bread Mon-Thu, white rice Wed-Fri,
flavoured rice Mon/Tue/Fri) rather than as frequency caps the solver would then
have to be steered inside. The fourth, "fish dish to be served on wednesaday",
makes `chennai.json`'s one-seafood-day-a-week cap land on a named day.

### World Bank — two counters

Its non-veg station serves **four dishes every day** — a chicken gravy, chicken
biryani, boiled egg and bone salna. Three are the same dish daily, so they are
`constant_items` pins and the fourth is a composition. Two of the four dishes did
not exist in any city list and are now real rows; pinning a real dish narrows its
cell rather than stamping text, so `boiled_egg` and `bone_salna` are visible to
the colour and variety rules like anything else.

That is also what surfaced the pin/uniqueness contradiction: a pin narrows a cell
to one dish, and `unique_items` then saw that dish on all five days. Each pin
alone made the counter INFEASIBLE with no rule named. A dish the config pins into
the same slot every day is a staple by declaration, which is now what the solver
reads it as.

Its dessert is pinned to the client's own wording, **"Sweet/Fruit"** — no such
dish exists, so it is stamped verbatim and the slot serves no rotating sweet.
Deliberate, and flagged in `pending_config_changes.md` in case they want the
rotation instead.

### ICON Chn — four counters

The most structurally demanding of the four. "In Premium Lunch and Economy Lunch
counter we have give dal and veg dry alternative days not both on same day": both
run as mandatory daily slots, so alternation can only be said by standing each
down on the other's days — kootu Tuesday and Thursday, poriyal Monday, Wednesday
and Friday, which is exactly what the sample's single "Kootu or Poriyal" row does.

Two of its rules are about cross-counter sharing and only one could be
implemented. "Rice combo counter is not linked to the shared items list" is now
expressible: `shared_categories_excluded_counters` in the client's rules file
takes a counter out of the sync. "Same nonveg main is served in Economy Lunch
counter and Roti Combo Counter" is not: the sync pins from the **primary**
counter, and ICON's primary serves a different lineup entirely. Both counters are
given the same weekday structure instead — an egg gravy Monday and Wednesday, a
chicken gravy otherwise — so they serve the same kind of dish on the same day
without being guaranteed the identical one.

"2 egg gravy on Monday and Wednesday" is where `all_of` came from: "an egg
GRAVY" is `is_egg_dish` AND `is_nonveg_gravy`, and the flag alone returned a
boiled egg.

### What all three of them agreed about: the kootu is the dal

TCL, World Bank and ICON Chn state **"in dal need to give only Kootu item"** in
the same words. Every Chennai kootu was `course_type = veg_gravy`, so the dal
pool held none of them and the rule was unsatisfiable as written.

The four sample weeks settle it: the kootu is always its own row, next to the
gravies and never one of them. World Bank prints "Veg Gravy", "Kara kuzhambhu"
and "Kootu" as three separate rows; ICON's is labelled "Kootu or Poriyal",
pairing it with the dry rather than the gravy. A kootu is a vegetable simmered
with moong or toor dal, so `dal` is the position it occupies on a Tamil plate.

`scripts/chennai_client_pools.py` re-files the eight and imports eight more, and
`sub_category = kootu` is preserved so the city's `kootu_twice_weekly` cap still
selects them. This is a **deliberate per-city divergence**: Bangalore files 43
kootus as `veg_gravy` and two as `dal`, and stays as it is.

The consequence is that "kootu daily" and "kootu at most twice a week" are a
direct contradiction, which TCL and World Bank resolve by disabling the city
rule. That conflict was also invisible — `kootu_twice_weekly` has no `base_slot`,
and the composition cross-check only looked at compositions on the rule's own
slot, so `/diagnose` reported a clean bill of health for a counter that could not
solve.

---

## Seafood: a missing branch of the taxonomy

Chennai is the first city list with fish, and the master ontology had only
chicken and egg — `is_egg_dish` for the protein, `chicken_*` sub-categories for
everything else. The import therefore filed all 8 fish dishes under the nearest
chicken bucket. Only `primary_protein` was correct, which is why the dishes still
rendered red and `NONVEG_PROTEINS` already matched them.

`scripts/seafood_taxonomy.py` (idempotent, re-run after any re-import) fixes it:

| What | Before | After |
|---|---|---|
| Flag columns | none | `is_seafood` + `is_fish_dish`, added after `is_egg_dish` in **every** city workbook |
| `sub_category` | `chicken_south_coastal`, `chicken_chinese_dry`, `chicken_spicy_fry` | `fish_south_coastal`, `fish_chinese_dry`, `fish_spicy_fry` |
| `key_ingredient` | `chicken` on all 8 | `fish` |
| Chicken-only flags | `fish_kuzhambu` held `is_south_chicken_gravy` | cleared |
| `cuisine_family` | `fish_65`, `fish_roast` north_indian | `south_indian` |

Three of those are more than tidiness:

* **`key_ingredient` was a live bug.** `ingredient_ban_rule` matches on
  `key_ingredient` **and** `primary_protein`, so while the fish rows read
  `key_ingredient: chicken`, a client banning chicken silently lost the fish too,
  and a client banning fish caught them only via the second column.
* **`is_south_chicken_gravy` on a fish** put `fish_kuzhambu` inside
  `avoid_consecutive_south_chicken` — a rule about chicken — and inside
  `_augment_nonveg_pair`'s "keep the regional chicken gravy" exemption. That
  rule's comment now reads 10 rows rather than 11.
* **`cuisine_family` decides availability.** The theme filter narrows
  `nonveg_main` by cuisine, so a fish tagged north_indian cannot appear on a
  south day — and south is three of Toast Tab's five. The master files
  `chicken_65` as south_indian, so `fish_65` sitting in north contradicted the
  taxonomy's own convention. `fish_tawa_fry` was deliberately left north: tawa
  fry is a north/street preparation and the master keeps a bucket for it.

Both new columns exist because they answer different questions: `is_fish_dish` is
the fish-only subset, `is_seafood` the umbrella, so a future prawn or crab row is
covered without editing any rule. The columns go into `bangalore.xlsx` (0 rows)
and `pune.xlsx` (0 rows) as well as Chennai, because `normalize_city_ontology.py`
forces a new city's column set to match the reference list — a column absent from
the reference cannot exist in any city.

`chennai.json` gains one rule that reads the new flag, `seafood_weekly`
(`max: 2`). It is **not** from a rulebook: the sample serves fish once in seven
days, and 2 leaves a five-day week room to serve it without being forced to.
Widen or drop it when a real Chennai rulebook arrives.

---

## Engine change this city required

`ThemeSlotFilterRule`'s bread cuisine lock ran **before** the `exempt_slots`
check in all three of its code paths — `pre_filter_pool`, `diagnose` (which read
`if base in self.exempt_slots and base != 'bread'`) and
`_project_filter_size`. Listing `bread` in `exempt_slots` was therefore silently
ignored: a documented config knob that did nothing for one slot.

The lock now honours the exemption. No other city lists `bread`, so Bangalore
(bread narrows 252 → 66 on a south day) and Pune (a 2-chapati pool with nothing
to narrow) are unaffected, and `tests/test_chennai_rules.py` pins both halves —
that Chennai's bread is not narrowed on any theme, and that Bangalore's still is.
