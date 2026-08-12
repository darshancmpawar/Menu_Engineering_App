# NCR — ontology integration

NCR (Delhi National Capital Region) is a North Indian city list with non-veg and
welcome drinks. This documents how its ontology was integrated, what data
corrections it needed, and the **one decision still open** (per-client pools).

## The list

`data/raw/city_items/ncr.xlsx` — **1,544 items**, derived by
`scripts/normalize_city_ontology.py` from `source_workbooks/NCR_menu_items.xlsx`.
Unlike Pune/Chennai, the raw file arrived already in the master 135-column schema
(a mapping pipeline had run — it carries `Mapping_Log`, `Review_Required` and
`Data_Quality_Log` sheets), so normalisation was a light pass (`--client-pool
keep` to preserve the embedded client tags; no flags needed coercing).

Declared categories (`ontology_categories.json`): welcome_drink, soup, salad,
bread, rice, veg_dry, veg_gravy, starter, dal, dessert, healthy_rice, curd_side,
nonveg_main. No rasam/sambar — see corrections below.

Ruleset: `configs/city_rules/ncr.json` `extends` Bangalore (no NCR-specific rules
yet). A real solve produces a coherent North Indian menu from the list with
non-veg tagged and zero blocking diagnostics (`tests/test_ncr_plan.py`).

## Data corrections applied

Every correction is an idempotent script with a test, run in this order after the
normaliser (which rebuilds from the raw list and drops hand fixes):

1. **`seafood_taxonomy.py`** — NCR has 2 fish rows (`fish_curry`, `goan_fish_curry`);
   set `is_seafood`/`is_fish_dish` and moved them off the chicken buckets the
   import filed them under.
2. **`course_type_corrections.py`** (`ncr` block) — 31 misfiles the auditor
   caught, e.g. `kulfi`/`mathura_peda`/`rava_kesari` sitting in `veg_gravy` (a
   dessert served as a gravy), `kokum`/`mint_mojito`/`jaljeera` as gravies (they
   are welcome drinks), 4 soups filed as gravies, and **5 unservable** non-veg
   rows filed outside `nonveg_main` (`chicken_fried_rice`, `dhaba_chicken_curry`,
   `egg_curry_masala`, `kolhapuri_chicken`) plus `soya_keema` whose protein was
   wrongly `mutton` (it is minced soya).
3. **`remove_generic_rows.py`** (`ncr` block) — 10 rows named for a *category*,
   not a dish (`dal`, `rice`, `salad`, `sambar`, `rasam`, `chutney`, …). The only
   `rasam` and `sambar` rows were these bare labels, so NCR carries no
   rasam/sambar station — correct for a North list. `curd`, `papad` and `pickle`
   are KEPT: single fixed thali condiments/staples printed as-is.
4. **`dessert_cuisine_corrections.py`** — retagged 35 desserts by region
   (payasam/kesari families → south, western bakery → continental).
5. **`ncr_cuisine_corrections.py`** — 24 savoury dishes the pipeline mislabeled
   `cuisine_family = continental` (17 North Indian chicken curries in
   nonveg_main — each already `sub_category = chicken_north_*`, so the row
   contradicted itself — and 7 Indian chaat/pakora starters) → `north_indian`.
   They were silently **unservable**: ThemeSlotFilterRule hides a continental
   dish on every non-continental day, and no NCR client runs a continental day.
   Genuinely-continental veg_dry/soup rows are left alone.
6. **`ncr_fuzzy_unmerge.py`** — see next.

## The fuzzy-merge reversal (client-requested)

The raw file fuzzy-matched each source dish name to the master at 0.82 string
similarity and, on a match, **overwrote the source name with the master name**
(`Mapping_Log` decision `ACCEPT_REVIEW`, 190 of them). Most are harmless spelling
variants — `kadhai`→`kadai`, `chola`→`chole`, `laddoo`→`laddu`, `ajwain`→`ajawin`
— and stay merged. But string similarity is blind to meaning, and **13 collapsed
genuinely different dishes**. The client confirmed only spelling variants may
merge; these were restored:

| Lost dish | Wrongly became | Fix |
|---|---|---|
| aloo_matar (peas) | aloo_tamatar (tomato) | split — a real aloo_tamatar existed too |
| aloo_matar_dry / _gravy, soya_matar | aloo/soya_tamatar\* | rename back |
| paneer_butter | paneer_mutter (peas) | rename back |
| matar_mushroom | malai_mushroom (cream) | rename back |
| lauki_kofta (gourd) | malai_kofta (cream) | rename back |
| kala_chana (black) | kabul_chana (white) | rename back |
| bhuna_chicken (N. Indian) | hunan_chicken (Chinese) | rename + refile off the Chinese bucket |
| paneer_achari | paneer_chingari | rename + restore paneer identity |
| paneer_adraki (ginger) | paneer_kadai (wok) | split — a real kadai paneer existed too |
| punjabi_kadhi, veg_kadhi (yogurt curry) | punjabi/veg_kadai (wok) | rename back |

Tellingly, the merged rows kept the *source* dish's attributes (the merged
`aloo_tamatar` row was key_ingredient `potato`, `malai_kofta` was `bottle_gourd`),
so the corruption was in the name — which is why most fixes are a rename. Two are
COLLISIONS (a real dish *and* a spelling variant both merged into the same row):
those are split, the existing row kept as the real dish and a fresh row added for
the restored one. The other ~177 merges are left as-is (`Review_Required` still
lists them for the client to eyeball).

## Pools: full-list fallback (no `common`)

Every NCR row is tagged to one or more of the **8 real NCR clients** (Stryker,
Carelon, Junglee Games, Airtel Noida, Sinch, Siemens, SAEL, Corning) and there is
**no `common` pool**. In the live DB every NCR client has `source_pools = []`.
Under the old F5 rule that resolved to common-only → an empty menu.

Resolved in `OntologyRepository.filtered_menu_data` (see note 15 / the F5
section): a client whose eligible subset comes out **empty** falls back to the
full city list, so all 8 NCR clients plan from the whole NCR ontology today,
differentiated by their per-client rules (below) rather than by dish pools. The
per-client `client` tags remain available: assign `source_pools = ['stryker']`
and that client narrows to its own dishes, and the required-slot check is no
longer applied to the subset (a slot the client doesn't serve is simply absent).

## Client-specific logics

The client's `Site_Specific_Menu_items_logic` workbook carries per-site rules for
five NCR sites. Sheet → client-name mapping (they differ): `Stryker Sector 59` →
**Stryker NCR**, `Seimens` → **Siemens**, `Airtel Plot 5` → **Airtel Noida**,
`Sinch` → **Sinch NCR**, `Junglee` → **Junglee Games**. Encoded in
`data/configs/client_rules.json`, tested in `tests/test_ncr_client_logic.py`:

| Client | Encoded (lunch) | Deferred / out of scope |
|---|---|---|
| Stryker NCR | salad 1 = green salad daily (salad 2 varies); bread 1 = tawa roti daily (bread 2 varies); rice split — flavour rice Mon/Wed/Thu/Fri, white rice Tue only; 2 paneer gravies + 1 kofta gravy/wk; egg gravy 1×/wk; fish ≤1/wk | fish/biryani/sambar **once per 15 days** (rolling window a weekly plan can't see — history-checked at generation); 'biryani not the same week as fish' (week-level co-occurrence); **10 sambar were imported into NCR** (`scripts/add_ncr_sambar.py`) — serving them still needs a sambar/dal_sambar slot on the counter plus the 15-day cadence rule; 'Thursday special' (undefined); cut fruit (breakfast) |
| Siemens | salad = green salad daily; bread = plain chapati daily; non-veg pair — Tue one egg + one chicken, other days two chicken; 1 paneer + 1 soya/wk; kofta ≤1/wk | kofta 'once per 2 weeks' (capped to ≤1/wk; fortnightly is history-checked); tetrapack juice (snacks); brown bread / cut fruit / boiled egg (breakfast) |
| Airtel Noida | paneer 2×/wk; non-veg Wed & Fri only; potato ≤2×/wk | fish / paratha monthly (long-horizon); 'no repeat in 15 days' (already covered by cooldown 20); Wed 'regional theme' (needs the cuisine named) |
| Sinch NCR | bread = tawa roti daily; flavour rice Mon/Wed, white rice Tue/Thu/Fri; raita Mon/Fri only; welcome drink Tue/Thu only; **starter Wednesday only + chaats only**; chicken Mon/Wed/Fri, egg curry Tue/Thu; paneer 1×/wk | the starter rules are **inert until a starter category (count 1) is added** to this counter in the editor — then they activate (verified in the tests); only 3 chaat starters exist today (dhokla/kachori/samosa_chaat), add more for a 4th consecutive week |
| Junglee Games | chicken 4×/wk; egg curry 1×/wk; paneer 1×/wk | one chaat item 1×/wk (no starter/salad slot on this counter — add one to serve it) |

Selectors: `primary_protein` = paneer/chicken/soya, `is_egg_dish`,
`is_fish_dish`, `is_veg_kofta_gravy`, `key_ingredient` = potato, `item` =
green_salad / tawa_roti (staple pins). "N times a week" is `exact`/`min`/`max`
day-count (`selector_frequency`, auto-capped so it never forces INFEASIBLE);
day-specific placement uses `slot_composition.components_by_weekday`; "non-veg
only Wed/Fri" and the rice/raita/welcome-drink weekday windows use
`slot_day_restriction`; a same-dish-daily staple pinned into one expansion of a
multi-slot (Stryker salad 1 / bread 1) also carries a `repeatable_items`
declaration so `unique_items` allows the daily repeat.

**Two operator notes:**
- **Stryker bread must be slot_count 2** for the second (varying) bread the
  sample shows — the live counter has bread 1. At count 1 the pin still holds
  (tawa roti daily) with no second bread; set it to 2 in the editor to get the
  variety bread.
- **Stryker and Siemens disable `deep_fried_coupling`** (the Bangalore rice-bread /
  deep-fried-family rule). It links bread to the deep-fried rice/veg-dry family
  and cannot be satisfied once bread is pinned to plain chapati / tawa roti on
  these simple North-Indian counters; it is irrelevant to the NCR menu.

The **15-day / fortnightly cadences** (Stryker fish/biryani/sambar, Siemens
kofta) exceed a weekly horizon, so they are enforced across plans by the
`selector_history_window` rule type (CLAUDE.md note 23): it reads saved
`menu_history` and bans the whole family on dates within the window of a prior
occurrence, paired with a within-plan `max` cap. So "fish once per 15 days" is
now automatic — a fish served last week holds the family off until the 15 days
clear — not a manual check. Stryker's sambar window is inert until the counter
serves sambar (switch `dal` → `dal_sambar`); Stryker's biryani window enforces
the *cap* half only (the positive "serve a biryani day once/15 days" and "not
the same week as fish" are not expressible and stay deferred). The remaining
**deferred** rows are the ones the next round of client input / a sample menu
should pin down.
