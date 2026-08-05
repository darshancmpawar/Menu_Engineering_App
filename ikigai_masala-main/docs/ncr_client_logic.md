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
5. **`ncr_fuzzy_unmerge.py`** — see next.

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

## Open decision: per-client pools

Every NCR row is tagged to one or more of the **8 real NCR clients** (Stryker,
Carelon, Junglee Games, Airtel Noida, Sinch, Siemens, SAEL, Corning). **There is
no `common` pool.** This breaks the F5 assumption that `common` backfills every
mandatory slot:

* A client with no `source_pools` resolves to common-only → **empty** for NCR.
* A single client's pool does not cover every declared slot (Sinch has no
  curd_side, SAEL no nonveg_main, three clients no starter, several no soup).

So per-client narrowing (`source_pools = ['Stryker']`) is not yet usable; the
list plans correctly only from the full ontology (all 8 pools). The right fix —
synthesise a `common` pool from shared dishes, or relax the city-required-slot
check on filtered pools — **depends on the client config data**, so it is
deliberately left open. `tests/test_ncr_plan.py` validates the ontology and
ruleset from all 8 pools, independent of this decision.
