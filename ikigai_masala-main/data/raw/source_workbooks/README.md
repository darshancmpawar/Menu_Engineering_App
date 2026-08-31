# Source workbooks — the provenance of every derived rule

Every workbook that arrived from the client, in one place, one per city where the
city has one. **These are inputs, not runtime data.** Nothing in the app reads
this directory: the app reads `../city_items/<city>.xlsx`, which is what
`scripts/normalize_city_ontology.py` produces *from* the raw lists here.

They are committed because the derived artefacts cite them. `docs/pune_rulebook.md`
transcribes R1–R70 from `pune_menu_rulebook_101.xlsx`; every Toast Tab CHN rule was
read off the grid in `chennai_sample_menu.xlsx`. Without the sources in the repo,
the reasoning behind a rule is unverifiable — you can see *that* a cap is 3 but not
*why* — and re-deriving it means asking the client for the file again.

`bangalore_menu_samples_1.xlsx` was briefly here too and has been removed: all 14
of its sheets are byte-identical to sheets in `bangalore_menu_samples_history.xlsx`
(which has 32), so it was a strict subset and a second copy to keep in sync.

Only Bangalore's sample history was committed before; Pune's and Chennai's raw
lists, the Pune rulebook and Chennai's sample menu existed only as chat
attachments and would have been lost.

| File | City | What it is | Used to produce |
|---|---|---|---|
| `bangalore_menu_samples_history.xlsx` | Bangalore | printed menus as served | `docs/client_logics.md` |
| `pune_menu_items_raw.xlsx` | Pune | raw item list before normalisation | `city_items/pune.xlsx` |
| `pune_menu_rulebook_101.xlsx` | Pune | **the 70-rule rulebook** | `docs/pune_rulebook.md`, `configs/city_rules/pune.json` |
| `chennai_menu_items_raw.xlsx` | Chennai | raw item list, incl. its own `Mapping_Log` sheet | `city_items/chennai.xlsx` |
| `chennai_sample_menu.xlsx` | Chennai | Toast Tab's 7-day service history (sheet `Toasttab`) | `docs/chennai_client_logic.md`, the `ToastTab CHN` client rules |
| `bangalore_client_logics.xlsx` | Bangalore | **the Bangalore rulebook** — 158 logic statements across 32 clients, hard and soft mixed together, in one sheet named `Banglore`. This is the main regional ruleset; it is per-CLIENT logics rather than city-level rules | `docs/client_logics.md`, the Bangalore entries in `configs/client_rules.json` |
| `NCR_menu_items.xlsx` | NCR | pre-mapped item list (already in master schema) for 8 NCR clients, with its own `Mapping_Log` / `Review_Required` / `Data_Quality_Log` sheets. **Its `ACCEPT_REVIEW` fuzzy matches are the provenance for `scripts/ncr_fuzzy_unmerge.py`** — the reversal cites the exact merges it undoes | `city_items/ncr.xlsx`, `docs/ncr_client_logic.md` |
| `booking_menu_3_months.xlsx` | Bangalore | Booking.com's printed 3-month Lunch / Dinner / Breakfast grid. Only Lunch and Dinner are imported; it is where `infused_water` and `nonveg_soup` came from | `scripts/import_booking_menu.py` |
| `corning_chakan_pune_menu.xlsx` | Pune | Corning Chakan's nine weekly sheets, one column per day, identical row layout on every sheet. **The first client menu for a city other than Bangalore or Chennai**, and the first Maharashtrian list. Lunch and dinner only; the salad block is a salad BAR whose components are ingredients, and one sheet carries an unlabelled Independence Day menu below the grid that is read by dish name rather than position | `scripts/import_corning_pune_menu.py`, `scripts/marathi_ingredient_names.py` |
| `chennai_client_structure.xlsx` | Chennai | **four clients' rules in their own words**, on `Sheet1`, plus a sample week per client on its own sheet — a different kind of source from Toast Tab's service history, since these are stated rather than inferred. TCL, Gartner, World Bank and ICON Chn. RNTBCI is listed with nothing beside it and an empty sheet: on hold | `docs/chennai_client_logic.md`, `configs/clients/{tcl,gartner,world_bank,icon_chn}.json`, `scripts/chennai_client_pools.py` |
| `quest_hyderabad_menu_2026.xlsx` | Hyderabad | Quest's 41-day grid (31 Mar – 30 Jul 2026), one column per service day. **The source that created the Hyderabad city list.** Two layouts OFFSET from each other — Tue/Thu carry the full menu in rows 2-13, Wed is the biryani day in rows 5-13 with nothing above — so a column is read on the biryani map exactly when row 2 is blank; on the wrong map the Wednesday veg gravy files as a dal. The two non-veg rows are dry and gravy in that order and the biryani row is a third form, which is evidence no name heuristic has. "Chef Choice Desserts" is a placeholder and the fruit row holds serving counts, not dishes | `scripts/import_quest_hyderabad_menu.py`, `city_items/hyderabad.xlsx` |
| `stripe_menu_2026_06_29.xlsx`, `stripe_menu_2026_07_27.xlsx` | Bangalore | Stripe's two sample weeks, three sheets each. **Only the plated lunch and dinner blocks are imported** — the salad bar and the DIY sandwich station are components a diner assembles, not solver slots. The July file's salad-bar block lost a row, so its labels sit one row below their dishes; the importer detects and re-pairs that rather than assuming a layout | `scripts/import_stripe_menu.py` |

## Adding a city

1. Drop the raw item list here as `<city>_menu_items_raw.xlsx`, plus any rulebook
   or sample menu.
2. `python scripts/normalize_city_ontology.py <city> data/raw/source_workbooks/<city>_menu_items_raw.xlsx --dry-run`
   then again without `--dry-run` to write `city_items/<city>.xlsx`.
3. Re-run the correction scripts — the normaliser rebuilds the workbook from the
   raw list and drops hand-applied fixes: `scripts/seafood_taxonomy.py`,
   `scripts/pune_flag_corrections.py`, `scripts/course_type_corrections.py`,
   `scripts/remove_generic_rows.py`, `scripts/dessert_cuisine_corrections.py`,
   `scripts/expand_side_pools.py` (adds 7 dishes to the small
   healthy_rice/dessert/bread/starter pools in every city),
   and (NCR only) `scripts/ncr_cuisine_corrections.py`,
   `scripts/ncr_fuzzy_unmerge.py`, `scripts/add_ncr_sambar.py`,
   `scripts/ncr_bread_misfiles.py` (curries the mapper filed as bread),
   `scripts/add_ncr_north_rice.py` (16 north rices outside the weekly-capped
   mixed-veg pulao family) + `scripts/ncr_south_bread.py` (a real south bread
   pool for counters with a south-themed weekday). Each is
   idempotent, and each has a test that fails if its corrections are missing.

   **Order matters in two places**: run `scripts/merge_duplicate_curd.py` BEFORE
   `scripts/expand_side_pools.py`. The merge removes a `curd_side` row
   (`plain_curd`), so running it afterwards drops that category back below its
   share target and leaves the pool one dish short. And run
   `scripts/canonical_dish_spellings.py` BEFORE any client menu import
   (`import_booking_menu.py`, `import_stripe_menu.py`): the importer rewrites an
   incoming `channa` to `chana`, so while both spellings are alive in the
   workbook the fold reads the pair as two real words and the import adds a
   second row for a dish that is already there.

   Also pan-city: `scripts/misspelled_protein_names.py` (meat-named dishes the
   mapping pipeline left sitting in veg pools) and
   `scripts/canonical_dish_spellings.py` (one dish, one spelling).

   **Run the chain as a WHOLE, not piecemeal.** Several scripts repair what an
   earlier one removes, and running one on its own leaves the workbook between
   two consistent states: folding `raitha` into `raita` took Chennai's
   `curd_side` from 13 dishes to 11, and it is `expand_side_pools.py` — six
   steps earlier in the list — that tops such a pool back up to its floor of 12.
   The chain converges (a second full pass changes nothing), so re-running it
   costs only time.
4. Re-run `scripts/build_pool_token_map.py` so `city_items/pool_tokens.json`
   picks up the new city (keeps `/editor-metadata` fast).
5. Declare the city's categories in `city_items/ontology_categories.json` — **only if the
   city does not cover every mandatory slot.** An undeclared city is held to the FULL
   check, which is the stricter one; declaring a complete list only lowers the bar.
   Hyderabad is deliberately absent for that reason.
6. If the city's rows carry pool tokens that mean nothing there, add it to
   `src.constants.FULL_POOL_CITIES`. Hyderabad had to: it was SEEDED from Bangalore
   (`scripts/import_quest_hyderabad_menu.py` — a 191-dish standalone list starves under
   the cooldown, see `tests/cities/test_hyderabad_ontology.py`), so ~5,300 of its rows are
   tagged to Bangalore sites and `common` alone is 960 rows holding none of the city's own
   dishes. Seeding also doubles the corpus the all-cities scripts learn from, which is why
   `complete_ontology.py` and `fill_item_colours.py` weigh evidence per DISH, not per row.
7. Nothing to do for the correction scripts themselves: they read
   `scripts/city_list.py`, which is derived from the workbooks on disk.
   `tests/data/test_city_coverage.py` fails if one goes back to a hard-coded list.

## Correction scripts, in the order they must run

1. `scripts/normalize_city_ontology.py` — raw list → `city_items/<city>.xlsx`
2. `scripts/misspelled_protein_names.py` — meat-named rows left in veg pools
3. `scripts/canonical_dish_spellings.py` — one dish, one spelling
4. `scripts/merge_duplicate_curd.py` — before `expand_side_pools.py`
5. the per-city corrections (`seafood_taxonomy`, `course_type_corrections`,
   `remove_generic_rows`, `dessert_cuisine_corrections`, the `ncr_*` set)
6. `scripts/expand_side_pools.py`
7. the client menu imports (`import_booking_menu.py`, `import_stripe_menu.py`,
   `import_stryker_menu.py`, `import_moengage_menu.py`, `import_citrix_menu.py`,
   `import_chennai_menu_bank.py`, `import_corning_pune_menu.py`,
   `import_quest_hyderabad_menu.py` — which also SEEDS `city_items/hyderabad.xlsx`
   from Bangalore's list on a fresh checkout, so it must run before anything
   that expects the file to exist)
8. `scripts/nonveg_structural_flags.py` — **after** the imports, because they
   are what adds new non-veg rows with no form flag
8b. `scripts/bread_form_flags.py` — same slot, same reason, for
   `is_plain_phulka_chapathi`: an importer writes only what a dish name supports
   and leaves the column blank, so every `chapati`-spelled row an import added
   arrived unflagged. It derives the flag from the NAME in both directions, so it
   must run **after** step 3 has settled on one spelling.
9. `scripts/seafood_taxonomy.py` again if an import added a fish dish
10. `scripts/marathi_ingredient_names.py` — a dictionary, so it runs BEFORE
    `complete_ontology.py`: the `key_ingredient` values it writes are what that
    pass then implies a sub_category and flags from.
10b. `scripts/fill_cuisine_family.py` — after the re-files (it reads
    `course_type` and `sub_category`) and before `complete_ontology.py`, whose
    attribute implication learns from the column this fills. Only NCR has
    blanks; the other four are complete.
11. `scripts/fill_item_colours.py` — the same argument as the dictionary, for
    `item_color`, and it must come BEFORE `complete_ontology.py`. It reads only
    dish names and the colours already present, so nothing that pass fills can
    help it — while `is_rule_ready` is derived FROM `item_color`, so running it
    afterwards leaves a row that a re-run then finds newly complete, and the
    chain stops converging.
12. `scripts/complete_ontology.py` — **last of the writers**, because it learns
    every rule it applies from the rows already classified, so it needs the
    imports, the re-files, the flag corrections, the ingredient dictionary and
    the colours to have happened first. It runs to a fixed point internally; a
    second invocation is a no-op.
13. `scripts/definitional_flags.py` — **after** `complete_ontology.py`, and the
    only thing in the chain that CLEARS a flag rather than filling one. That
    pass's token vote is what put `is_liquid_dessert` on 55 NCR pethas, laddus
    and cakes; both flags it owns are in that script's `OWNED_ELSEWHERE`, so the
    chain converges whichever order the two actually run in — the ordering here
    is for readability, not correctness.
14. `scripts/drop_dead_columns.py` — schema only, so order does not matter
15. `scripts/build_pool_token_map.py`

`scripts/chennai_client_pools.py` and `scripts/chennai_cuisine_corrections.py`
sit with the per-city corrections (step 5).
It re-files Chennai's kootus into `dal` and imports the drinks, biryanis and
sweets four clients' stated rules asked more of than the list held.

Steps 3, 7, 8, 8b, 10, 11 and 13 are order-sensitive for the reasons their
docstrings give.

The whole chain is **convergent**: run it twice and the second pass reports
"already correct" everywhere. That is the check worth doing after any re-import,
because it catches two scripts disagreeing — `expand_side_pools.py` maintains a
floor of 12 rasam per city, so moving a dish out of `rasam` makes it share two
back in, and that is the system working rather than a fault.
