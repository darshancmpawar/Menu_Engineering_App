# Pune rulebook → implementation map

Source: `data/raw/source_workbooks/pune_menu_rulebook_101.xlsx` (sheet `Rulebook`, R1–R70) plus its
annexure. Implementation: `data/configs/city_rules/pune.json`.

Per-client requirements are in [`pune_client_logic.md`](pune_client_logic.md);
where a client answers a question this rulebook leaves open, that document wins
(R59's daily buttermilk and R54's weekend shape are both settled there for
Amadeus Pune).

Pune's ruleset is **standalone** — it does not `extends: bangalore`. The two
rulebooks genuinely disagree (Bangalore mandates exactly one premium gravy a
week, Pune caps it at one; Bangalore schedules theme days, Pune does not), and
inheriting would have quietly imported Bangalore's non-veg station, deep-fried
coupling family and sambar rules into a city that serves none of them.

Scope is **lunch** only, per the standing decision to focus there; the
rulebook's breakfast/snack rules are listed below as out of scope rather than
dropped silently.

## Data

| | |
|---|---|
| Item list | `data/raw/city_items/pune.xlsx` — 272 items, 133 columns (the reference format). Was 274 before `scripts/remove_generic_rows.py` dropped `salad` and `sweet` (rows named for a category, not a dish) |
| Selected by | `clients.city = 'Pune'` → `api.config.city_excel_path()` |
| Categories covered | welcome_drink, salad, bread, rice, veg_dry, veg_gravy, dal, dessert, healthy_rice, curd_side (declared in `data/raw/city_items/ontology_categories.json`) |
| Not covered | soup, starter, sambar, rasam, nonveg_main — the list is fully vegetarian and carries no south-Indian tiffin/sambar section |
| Pool tokens | none — every row is `common`, i.e. the file is the whole Pune universe (see "The `client` column" below) |

### The `client` column

The raw workbook tagged all 274 rows `Amadeus Pune`. That carries no per-client
information, and the live `Amadeus Pune` row has `source_pools = []` (common
only), which would have made **zero** items eligible. The normaliser therefore
sets `client = common`. When Pune has several clients drawing from different
subsets, put real tokens in that column and set each client's `source_pools`;
nothing else has to change.

## Status legend

| | |
|---|---|
| **DONE** | encoded in `pune.json` and enforced |
| **N/A** | the dish or category the rule governs does not exist in the Pune list, so the rule is configured but has nothing to act on |
| **CLIENT** | a per-client/per-site decision — belongs in `client_rules.json`, not the city ruleset |
| **OPS** | a kitchen/procurement/food-safety instruction with nothing for the solver to decide |
| **GAP** | wants a capability the engine does not have; listed under "Open gaps" |

## R1–R70

| R | Rule | Status | Where |
|---|---|---|---|
| R1 | ≥3 distinct colours/day across key slots | DONE | `colour_three_distinct_max_two_alike` (`min_distinct_per_day: 3`) |
| R2 | Max two items may look alike | DONE | same rule (`max_same_color_per_day: 2`, `max_colors_at_reach: 0`) |
| R3 | Flavoured rice ≠ veg gravy colour (except chinese day) | DONE | same rule (`ignore_rice_gravy_color_diff_on_chinese_day`) + built-in solver constraint |
| R4 | Indian starter ⇒ chutney mandatory | N/A | no `starter` items in the Pune list |
| R5 | Premium-ingredient items max once/week | DONE | `baby_corn_weekly` + `veg_kofta_gravy_weekly` (annexure names baby corn and kofta) |
| R6 | Malai kofta ⇒ no other premium gravy that week | DONE (implied) | `premium_gravy_weekly` caps premium gravies at one, so a kofta week excludes another |
| R7 | South-Indian starters served with chutney | N/A | no `starter` items |
| R8 | Veg gravy and flavoured rice complement (spicy ↔ mellow) | GAP | no cross-slot flavour-pairing rule type; `is_spicy`/`is_mellow` are set on 5/7 items, mostly not gravies |
| R9 | Match veg and non-veg biryani region | N/A | no non-veg |
| R10 | North rice ⇒ prefer north gravy | GAP | no cross-slot same-attribute preference mode |
| R11 | South rice ⇒ prefer south gravy | GAP | as R10 |
| R12 | Aloo gravies max twice/week | DONE | `aloo_gravy_twice_weekly` |
| R13 | Max 1 premium veg item per day | DONE | `premium_veg_daily_max_1` (+ `premiums_different_days` soft) |
| R14 | Black chana gravies max once/week | DONE | `black_chana_gravy_weekly`. `is_black_chana_gravy` was 0 for all 274 rows; `scripts/pune_flag_corrections.py` sets it on `black_chana_malwani` |
| R15 | Deep-fried veg dry once per 7 days | DONE | `deep_fried_veg_dry_weekly` |
| R16 | Kabuli chana gravies max once/week | DONE | `kabuli_chana_gravy_weekly` |
| R17 | Maida breads max once/week | N/A (no such dish) | `maida_bread_weekly` is configured but the Pune bread pool is chapati + phulka, so it has nothing to cap |
| R18 | Malai kofta max once/week | DONE | covered by `veg_kofta_gravy_weekly` |
| R19 | Mixed veg pulao/biryani max once/week | DONE | `mixedveg_pulao_biryani_weekly` |
| R20 | Mixed-veg / kurma / kofta gravies max once/week | DONE | `mixed_veg_gravy_weekly`, `veg_kurma_gravy_weekly`, `veg_kofta_gravy_weekly` (read as each once, matching R12/R14/R16's phrasing) |
| R21 | Pappu dal once/week | DONE | `pappu_dal_weekly` |
| R22 | Premium-ingredient gravies max once/week | DONE | `premium_gravy_weekly` |
| R23 | Premium-ingredient veg dry max once/week | DONE | `premium_veg_dry_weekly` |
| R24 | Puri only once a month | N/A (no such dish) | no puri / `is_fried_bread` item in the Pune list. A month is longer than any horizon, so the monthly window would project to one-per-horizon plus the 20-day item cooldown |
| R25 | Remaining dal days mostly yellow dal (~1 in 3) | DONE | `yellow_dal_at_least_twice` (a floor of 2 over a 5-day week — see "Judgement calls") |
| R26 | Special sambar max once/week | N/A | no sambar |
| R27 | A week's combination must not repeat within a month | DONE | `no_repeat_weeks` (`week_signature_cooldown`, 30 days) |
| R28 | Dessert form must not repeat on consecutive days | DONE | `dessert_form_non_consecutive` |
| R29 | Curd is exempt from repeat bans | DONE | built in: `curd` is in `REPEATABLE_SLOTS`, exempt from `unique_items` and the cooldown |
| R30 | Kadhi-style dal once in 15 days | DONE (projected) | `kadhi_weekly` — once per horizon; the 20-day item cooldown carries the rest of the window for the same dish |
| R31 | Leafy veg dry once in 15 days | DONE | `leafy_veg_dry_weekly`. `is_leafy_based_dish` covered no veg dry at all; `scripts/pune_flag_corrections.py` adds the palak / methi / hariyali dishes |
| R32 | Kofta needs a 7-day gap, not on consecutive weeks | DONE / partial | the 7-day gap is `veg_kofta_gravy_weekly`; "not on consecutive weeks" needs cross-horizon state the weekly signature does not model |
| R33 | Dal colour must not repeat on consecutive days | DONE | `dal_colour_non_consecutive` |
| R34 | Multigrain breads not on consecutive days | N/A (no such dish) | `multigrain_bread_non_consecutive` is configured; no multigrain bread in the list |
| R35 | North flavoured rice not on consecutive days | DONE (soft) | `avoid_consecutive_north_rice`, high priority — see "Judgement calls" |
| R36 | Plain atta phulka/chapathi may run on consecutive days | DONE | `plain_chapati_may_repeat` (`repeatable_items`) — needed a new rule type |
| R37 | Same sambar key ingredient not within 15 days | N/A | no sambar |
| R38 | South flavoured rice not on consecutive days | DONE (soft) | `avoid_consecutive_south_rice` |
| R39 | No aloo inside mixed-veg gravies | OPS | a recipe composition instruction; the ontology has one row per dish, not per ingredient list |
| R40 | Avoid paneer-based fried items | N/A (satisfied by data) | `is_paneer_fry` is 0 for all 274 rows |
| R41 | Avoid paneer-based veg dry | N/A (satisfied by data) | one veg dry (`potato_chilli`) has paneer as key ingredient; no paneer veg-dry family to avoid |
| R42 | Indian bread default is tawa-based regular bread | DONE (by data) | the Pune bread pool is chapati + phulka only |
| R43 | Only one leafy dish per menu | DONE | `leafy_daily_max_1` |
| R44 | Bakery desserts primarily for premium clients | CLIENT | `is_bakery_dessert` is 0 in the Pune list; gate per client when it lands |
| R45 | Fruit welcome drinks are for premium clients | CLIENT | 3 of Pune's 4 welcome drinks are `is_fruit_drink`; a city-wide ban would leave only buttermilk. Needs a per-client premium flag |
| R46 | Mocktails for events only | N/A | no mocktail items |
| R47 | Oil-based breads monthly, for premium | N/A (no such dish) + CLIENT | `oil_based_bread_weekly` caps them per horizon; none in the list, and "for premium" is per client |
| R48 | Omelette/egg curry only at enabled sites | N/A | no egg items |
| R49 | Sites with selling price ≥150 may relax premium gravy frequency | CLIENT | a per-client `disable: ["premium_gravy_weekly"]` in `client_rules.json` |
| R50 | All slots mandatory each day | DONE | how the solver works: every active slot gets a cell per day |
| R51 | White rice every day | DONE | `white_rice` is a constant slot stamped `steamed rice` daily |
| R52 | No fried items in breakfast/snacks | OPS (out of scope) | lunch only |
| R53 | No maida items in breakfast | OPS (out of scope) | lunch only |
| R54 | Limited menu on Sat/Sun | CLIENT | `serve_weekends` covers *whether* weekends are planned; a smaller weekend slot set is a per-counter config |
| R55 | Saturday breakfast prefers sabudana khichdi | OPS (out of scope) | breakfast |
| R56 | No live counters at breakfast/snacks | OPS (out of scope) | breakfast/snacks |
| R57 | Bread items not repeated across breakfast and snacks | OPS (out of scope) | needs meal periods |
| R58 | Exclude high-risk vegetables | OPS | no risk classification in the ontology; an `ingredient_ban` per client can express a concrete list |
| R59 | Buttermilk and cut fruits daily | GAP / CLIENT | see "Open questions" — encoding it as the welcome drink would end drink variety |
| R60 | Use seasonal vegetables | OPS | no seasonality data |
| R61 | Verify market availability | OPS | outside the tool |
| R62 | No laccha onion salad in the rainy season | OPS | no seasonality data; an `ingredient_ban` can do it for a fixed period |
| R63 | Bhajiya etc. may be added in the rainy season | OPS | as R62 |
| R64 | Balance cereals, pulses, vegetables, dairy | DONE (partial) | the slot structure supplies the balance; `veg_gravy_key_ingredient_variety` and `veg_dry_key_ingredient_variety` keep the week from collapsing onto one ingredient |
| R65 | Balance nutrition, taste, variety, presentation | DONE (partial) | as R64, plus the colour rules |
| R66 | Avoid excessively spicy/oily/heavy food | OPS | `richness_score` exists (14 items at 1) but there is no stated threshold to enforce |
| R67 | Consider food preference trends | OPS | outside the tool |
| R68 | Avoid items that travel badly | OPS | no transport-risk classification |
| R69 | Comply with FSSAI and hygiene standards | OPS | outside the tool |
| R70 | Consider vendor inventory and capacity | OPS | outside the tool |

Totals over all 70 rules, by the leading status word: **33 DONE** (of which 4
are qualified — 2 soft, 1 projected onto the horizon, 1 partial), 16 OPS
(5 of those out of scope while the tool is lunch-only), 13 N/A, 4 CLIENT, 4 GAP.

So 33 of 70 are enforced today; 29 (OPS + N/A) have nothing for the solver to
decide, either because they are kitchen instructions or because Pune serves no
such dish; and 8 are genuinely open — 4 on a per-client premium tier, 4 on engine
capabilities.

## Judgement calls

Each of these is a place the rulebook is open to more than one reading. They are
listed so a reviewer can overrule them rather than discover them.

1. **R35/R38 are soft, not hard.** `Amadeus Pune` is themed north every weekday.
   A hard "north rice not on consecutive days" is unsatisfiable when every day's
   rice is north by construction — the plan would 422 with a config
   contradiction. Encoded as `soft_preference` at `high` priority, which the
   solver honours whenever it can (the shipped plans alternate
   north/south/north/south/north) without turning a preference into an
   impossibility. Ordinary rules are never relaxed to produce a menu; this is the
   narrower case where a hard reading is *provably* force-violated.

2. **`rice` is exempt from cuisine narrowing.** Pune's regional character lives
   in the rice slot: `masala_bhat` and `phodnicha_bhat` are Maharashtrian, and the
   lemon/jeera/ghee rice baths are tagged `south_indian`. Holding a north-themed
   counter to the 10 north rices would delete them — and 8 of those 10 carry
   `is_mixedveg_pulao`/`is_mixedveg_biryani`, which R19 caps at one, leaving five
   rice days to be filled from two dishes. Chinese and continental mains are still
   excluded on a non-matching day (the theme filter's cuisine exclusivity applies
   regardless of the exemption), so no fried rice lands on a north day.

3. **R25's "mostly yellow dal, roughly one every 3 days" is a floor of 2.** The
   two phrasings pull in different directions ("mostly" suggests a majority, "one
   every 3 days" suggests 1–2 of a 5-day week). Two is the reading both support.
   The engine caps a `min` to what is placeable, so a shorter horizon lowers it
   rather than failing.

4. **15-day and monthly windows are projected onto the horizon.** R30, R31, R24
   and R47 name windows longer than a plan. Each becomes at most one per horizon;
   the 20-day item cooldown extends it for the *same dish*, but a different dish
   of the same family may legitimately return in the next week. A true rolling
   class-level window would need history-aware selector counting.

5. **R20 caps each family separately.** "Mixed-veg, veg kurma and veg kofta
   gravies: max once/week" is read as three caps of one, matching the phrasing of
   R12/R14/R16 which each cap a single family. If it means one gravy from the
   whole group per week, change the three rules to one with an `any_flag`
   selector.

## Bangalore rules deliberately NOT carried over

Not in the Pune rulebook, so not in Pune's ruleset. Each is a one-line addition
if Pune wants it:

- `theme_day`, `theme_starter_preference`, `theme_fallback_penalty` — Pune
  schedules no theme days. (`theme_slot_filter` **is** included, for cuisine
  hygiene rather than theme rotation; see judgement call 2.)
- `coupling` (deep-fried rice/bread/veg-dry family) and `ricebread_gap` —
  Bangalore rulebook 34–42.
- `welcome_drink_color` (no same drink colour on consecutive days) and
  `buttermilk_twice_weekly` — Bangalore's welcome-drink rules. Pune's R59 asks
  for buttermilk *daily*, which is a different rule (see open questions).
- `curd_side` (biryani ⇒ raita, else curd), `liquid_desserts_twice_nonconsecutive`,
  `icecream_custard_weekly`, `sugar_syrup_nonconsecutive`, `lassi_weekly`,
  `soda_weekly`, `milkshake_heavy_milk_weekly`, `potato_veg_gravy_weekly`,
  `potato_veg_dry_weekly`, `lentil_daily_max_3`, `whole_legume_daily_max_1`,
  `rajma_gravy_weekly`, `black_dal_weekly`, `veg_dry_north_south_pair`.
  Note `veg_dry_north_south_pair` would be close to unsatisfiable anyway: the
  Pune list has 54 north veg dries and 2 south.

## Open gaps (need engine work)

| Gap | Rules | What is missing |
|---|---|---|
| Cross-slot attribute agreement | R8, R10, R11 | a `soft_preference` mode that rewards two slots sharing (or complementing) an attribute on the same day |
| Rolling class-level windows | R24, R30, R31, R32, R37, R47 | history-aware selector counting, so "this *family* once in 15 days" spans horizons instead of being projected onto one |
| Per-client premium tier | R44, R45, R47, R49 | a client attribute (price tier / premium flag) that rules can gate on |
| Meal periods | R52, R53, R55, R56, R57 | breakfast/snack menus; out of scope while the tool is lunch-only |

## Open questions for the client

1. **R59, "buttermilk and cut fruits daily".** Is the buttermilk the *welcome
   drink* (in which case it is a `fixed_daily_item` on `welcome_drink`, and the
   other three drinks never appear), or a separate accompaniment served alongside
   it (in which case Pune needs a new always-on slot)? Left unencoded pending an
   answer — the welcome drink currently rotates across all four items. Same
   question for cut fruits: the Pune list has a `fresh_fruit` category whose items
   sit under `dessert`.

2. **R45, "fruit welcome drinks are for premium clients".** Three of Pune's four
   welcome drinks are fruit drinks (`aam_panna`, `kokum_sharbath`,
   `lemon_sherbat`), so a non-premium Pune site would be left with buttermilk
   alone. Which Pune sites are premium?

3. **R54, "a limited menu on Saturdays and Sundays".** `Amadeus Pune` has
   `serve_weekends` set, so weekends are planned with the full slot set today.
   Which slots should a weekend day drop?

4. **R20** — three caps of one, or one cap across the group? (judgement call 5)

## Data corrections applied

`scripts/pune_flag_corrections.py` sets nine flags the raw workbook left at 0.
Both affected rules were silently inert without them, and re-importing a fresh
workbook drops the corrections again — so the script is committed and
`tests/test_pune_rules.py::test_flag_corrections_are_applied` fails if they are
missing.

| Item | Flag | Rule it unblocks |
|---|---|---|
| `black_chana_malwani` | `is_black_chana_gravy` | R14 |
| `palak_paneer` | `is_leafy_based_dish` | R43 |
| `palak_peas_curry` | `is_leafy_based_dish` | R43 |
| `lasooni_aloo_palak_dry` | `is_leafy_based_dish` | R31, R43 |
| `moong_methi_dry` | `is_leafy_based_dish` | R31, R43 |
| `mix_veg_hariyali` | `is_leafy_based_dish` | R31, R43 |
| `dal_methi` | `is_leafy_based_dish` | R43 |
| `dal_coriander` | `is_leafy_based_dish` | R43 |
| `mint_rice` | `is_leafy_based_dish` | R43 |

The line drawn for "leafy" is the one already in the data: the defining ingredient
is a leafy green (palak, methi, coriander, mint, hariyali). Cucumber
(`khamang_kakadi`) and cabbage are out, matching how `coriander_rice`, `dal_palak`,
`green_salad` and `methi_mutter_masala` were originally flagged.

## Remaining thin spots in the Pune item list

None of these blocks generation, and none currently bites for Amadeus Pune —
listed so a second Pune client is not surprised.

1. `welcome_drink` has 4 items. Amadeus Pune serves buttermilk daily so it does
   not matter there; a client rotating drinks over a 7-day week would repeat one.
2. `bread` has 2 items (chapati, phulka), handled as staples per R36.
3. `healthy_rice` has 1 item (`birista_pulao`) — any client selecting it serves the
   same dish daily.
4. `curd_side` has 2 items (`raita`, `boondi_raita`).
5. The `dal_rasam` and `dal_sambar` combo slots resolve to their dal component
   only (the list has no rasam or sambar), so selecting either silently collapses
   to an all-dal week. Both are off by default.
6. No maida bread, multigrain bread, oil-based bread, puri, bakery dessert,
   paneer fry, sambar, rasam, soup, starter or non-veg — see the N/A rows above.
7. `mix_kathol` is filed as a `veg_dry` while the client's sample serves it in the
   Gravy Veg row, and `potato_chilli` carries `key_ingredient: paneer` while being
   a potato dish. Both look like classification slips; neither is changed here
   because one printed row is thin evidence for editing an item's taxonomy.
