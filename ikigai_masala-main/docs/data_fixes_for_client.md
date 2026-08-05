# Item data — what needs fixing, and why it matters

For the team that maintains the item workbooks. Every entry below was found by
generating real menus and reading them dish by dish, not by inspecting data.

**Why this list exists even though most of it is already "fixed."** The fixes are
applied to `data/raw/city_items/<city>.xlsx`, which is *derived*. The source
workbooks in `data/raw/source_workbooks/` still contain the original values, so
**re-importing a city through `scripts/normalize_city_ontology.py` throws every fix
away.** Correction scripts exist to re-apply them, and tests fail if you forget —
but the durable fix is in the source data, which is what this document asks for.

**The one thing to understand about `course_type`.** It decides which slot pool a
dish can be served from. Nothing in the engine knows what a dish *is* — only what
its columns say. So a dessert filed as a gravy is not a labelling nit: it will be
served as a gravy, on a real menu, and no rule can prevent it.

---

## A. Wrong category — the dish gets served in the wrong position

Fixed in our copy; **please fix at source.**

| City | Dish | Filed as | Should be | What the tool did |
|---|---|---|---|---|
| Chennai | `semiya_pal_payasam` | `veg_gravy / mixed_veg_curry` | `dessert / payasam_/_kheer` | Served a milk-and-vermicelli **dessert as one of Tuesday's two gravies** |
| Chennai | `millet_payasam` | `veg_gravy / mixed_veg_curry` | `dessert / payasam_/_kheer` | same |
| Chennai | `kalkandu_pongal` | `rice / south_one_pot_rice` | `dessert / sweet_pongal` | Sweet pongal available as the **rice of the day** |
| Chennai | `mapillai_samba_sweet_pongal` | `rice / south_one_pot_rice` | `dessert / sweet_pongal` | same |
| Bangalore | `moong_dal_dosa` | `dal / leafy_dal` | `bread / lentil-based_dosa_(adai/pesarattu)` | A **dosa served as the client's dal**. All 37 other dosas are `bread`; this was the only one that wasn't |
| Bangalore | `butter_milk` | `veg_gravy / mixed_veg_curry` | `welcome_drink / indian_regional_drink` | **A drink in the gravy slot** |
| Bangalore | `masala_butter_milk` | `veg_gravy / mixed_veg_curry` | `welcome_drink / indian_regional_drink` | same |
| Bangalore | `boondi_butter_milk` | `veg_gravy / mixed_veg_curry` | `welcome_drink / indian_regional_drink` | same |

**Each of these is inconsistent with the same workbook.** `semiya_payasam`,
`rice_kheer` and `moong_dal_thengai_kheer` were already correct desserts.
**Eight** other buttermilks were already `welcome_drink`. The rule is only broken
for a handful of rows, which is what makes it easy to miss.

**Deliberately NOT changed:** `majjige_huli`, `bendekai_majjige_huli`,
`sorekai_majjige_huli` stay `veg_gravy / kadhi`. Those genuinely are buttermilk
*curries*, not drinks.

---

## B. Unservable rows — the dish cannot appear on any menu at all

Worse than category A, and invisible: the dish simply never comes up, and nothing
reports it.

The rule: **a dish with a non-veg `primary_protein` can only be served from
`nonveg_main`.** Non-veg rows are dropped from every other slot so a veg slot can
never serve meat. So a non-veg protein on a row whose `course_type` is something
else leaves its own pool and joins nothing.

| City | Dish | Was | Fix applied | Why |
|---|---|---|---|---|
| Bangalore | `egg_fried_rice` | `course_type: rice` + `primary_protein: egg` | → `course_type: nonveg_main` | Dropped from the rice pool for being non-veg, never entered nonveg_main because its course said `rice`. **Unservable.** Every chicken biryani is `nonveg_main` for exactly this reason |
| Chennai | `urandai_kuzhambu` | `course_type: veg_gravy` + `primary_protein: egg` | → **protein cleared** | Same symptom, opposite cause. Urundai kuzhambu is a lentil-dumpling gravy — `is_egg_dish` is `0` on the row and all 11 sibling veg kuzhambus carry no protein. The *protein* was wrong |

Note the second one carefully: moving it to `nonveg_main` would have "fixed" the
error by **making a vegetarian gravy non-veg.** When these two columns disagree,
decide which one is telling the truth about the dish.

**Rule of thumb for new rows:** if `primary_protein` is chicken / egg / fish /
mutton / prawn, then `course_type` must be `nonveg_main`. If the dish is
vegetarian, leave `primary_protein` blank.

---

## C. Seafood — the taxonomy had no place for it

Chennai is the first city list with fish, and the master taxonomy had only chicken
and egg. All 8 fish dishes were filed under the nearest chicken bucket.

| Column | Was | Now |
|---|---|---|
| `sub_category` | `chicken_south_coastal`, `chicken_chinese_dry`, `chicken_spicy_fry` | `fish_south_coastal`, `fish_chinese_dry`, `fish_spicy_fry` |
| `key_ingredient` | `chicken` on all 8 | `fish` |
| flags | `fish_kuzhambu` carried `is_south_chicken_gravy` | cleared |
| new flags | — | `is_seafood`, `is_fish_dish` (added to all three city workbooks) |
| `cuisine_family` | `fish_65`, `fish_roast` = `north_indian` | `south_indian` |

Two of those were doing real damage:

* **`key_ingredient: chicken` on a fish** — the ingredient-ban rule matches on
  `key_ingredient` **and** `primary_protein`, so **a client banning chicken was
  silently losing the fish too.**
* **`cuisine_family` decides availability** — the theme filter narrows non-veg by
  cuisine, so a fish tagged `north_indian` **cannot appear on a South Indian day**,
  and south is three of Toast Tab's five days. The master files `chicken_65` as
  `south_indian`, so `fish_65` sitting in north contradicted its own convention.

`fish_tawa_fry` was deliberately left `north_indian` — tawa fry is a north/street
preparation.

**Please use `fish_*` sub-categories and `is_seafood` for any new coastal dish.**
Bangalore's list currently has **zero** fish or prawn rows — if Bangalore sites
actually serve seafood, those dishes are missing entirely.

---

## D. Resolved by your decision — applied in our copy

You reviewed D1-D3 and gave a decision on each; all three are now applied to
`data/raw/city_items/*.xlsx`. As with sections A-C, **please also fix them at
source** so a re-import stops undoing them.

### D1. Desserts now carry their real region (all cities) — DONE

`cuisine_family` on desserts was almost all `north_indian` (221/249 Bangalore,
28/32 Chennai, 43/45 Pune). We researched the dish families and retagged:

* **South Indian** — every *payasam* / *payasa*, rava *kesari*, *mysore pak*,
  *holige* / *obbattu*, sweet *pongal*, *badusha*, *adhirasam*, *ada pradhaman*,
  and the Kannada/Tamil/Telugu names (ellu-bella, karjikai, sunnundalu, …).
* **Continental** — western bakery: cake, brownie, muffin, cupcake, custard,
  pudding, tiramisu, ice cream. `milk_cake` / `ajmeri_milk_cake` were kept Indian
  (they are *mawa* sweets, not bakery).

East Indian (Bengali — rasgulla, rasmalai, sandesh) and West Indian (modak,
shrikhand, soan papdi) sweets were **left `north_indian` on purpose**: the
`cuisine_family` field has only north / south / continental / chinese / other, with
no East or West value, so those are the closest usable bucket. If you want a true
East/West split, we would need to add those values to the vocabulary first — tell us
if that matters to you.

### D2. `tomato_thokku` is now a gravy — DONE

You confirmed it is a gravy, so it moved from `accompaniment` to `veg_gravy`
(sub-category `mixed_veg_curry`, matching `tomato_gojju` / `tomato_masala`) in both
Bangalore and Chennai. ToastTab's Friday tomato-thokku-in-veg-gravy is now
reproducible.

### D3. The 11 generic-named rows were removed — DONE

Chennai: `brinjal`, `chutney`, `darbar_soup`, `dry_sweet`, `local_salna`,
`milk_sweet`, `sweet`, `toast_salad`, `veg_gravy`
Pune: `salad`, `sweet`

You chose removal over renaming, so these rows are deleted. **One consequence to
be aware of:** `dry_sweet` and `sweet` appear on ToastTab's real sample menu, so
those two sample rows are now **unreproducible** — a generated plan can no longer
put a dish called "Sweet" in the dessert slot, because no such dish exists. If you
later supply the real names for what "Sweet" and "Dry Sweet" actually were on those
days, we will add them back as proper dishes.

## E. Still open — one item needs more data from you

### D4. Five Chennai stations are too small for a five-day week

| Station | Distinct dishes |
|---|---|
| `curd` | 1 |
| `curd_rice` | 2 |
| `healthy_rice` | 2 |
| `rasam` | 2 |
| `curd_side` | 4 |

These must repeat within a single week — arithmetic, not a tool limitation. We treat
them as staples so the plan still generates, but if you want variety in the rasam or
the curd rice, **the list needs more dishes.** Two rasams cannot fill three rasam
days without one appearing twice.

---

## F. Item IDs are not globally unique

`MENU004360` is `ajwain_pulao` in Chennai and `aam_ras` in Pune. **151 IDs mean two
different dishes** across those two lists, because both were allocated from
`MENU004360` upward independently.

**Nothing is broken today** — every use of `item_id` is scoped to one city's list,
and menu history stores dish *names*. But if you intend `item_id` to be a global
key — for a cross-city report, a shared price list, anything that joins two cities —
these 151 must be re-issued first. Current high-water across all three lists is
`MENU0004558`.

---

## Summary of what we need from you

| Priority | Ask |
|---|---|
| **1** | Fix sections **A**, **B**, **C** and **D1-D3** in the *source* workbooks, so a re-import stops undoing them |
| **2** | **D3** — real names for `dry_sweet` and `sweet` if you want those two live-menu rows reproducible (they are removed for now) |
| **3** | **D4** — more dishes for `rasam`, `curd_rice`, `curd`, `healthy_rice` if you want weekly variety |
| **4** | **D1** — tell us if you need a true East/West dessert split (would require new `cuisine_family` values) |
| **5** | **F** — only if `item_id` is meant to be globally unique |

Everything in A, B, C and D1-D3 is already live in our copy, so plans generated
today are correct. The ask is to stop the next re-import from reintroducing them.
Only **D4** still blocks nothing but limits variety.
