# Source workbooks — the provenance of every derived rule

Every workbook that arrived from the client, in one place, one per city where the
city has one. **These are inputs, not runtime data.** Nothing in the app reads
this directory: the app reads `../city_items/<city>.xlsx`, which is what
`Chain rules/normalize_city_ontology.py` produces *from* the raw lists here.

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
| `NCR_menu_items.xlsx` | NCR | pre-mapped item list (already in master schema) for 8 NCR clients, with its own `Mapping_Log` / `Review_Required` / `Data_Quality_Log` sheets. **Its `ACCEPT_REVIEW` fuzzy matches are the provenance for `Chain rules/ncr_fuzzy_unmerge.py`** — the reversal cites the exact merges it undoes | `city_items/ncr.xlsx`, `docs/ncr_client_logic.md` |
| `booking_menu_3_months.xlsx` | Bangalore | Booking.com's printed 3-month Lunch / Dinner / Breakfast grid. Only Lunch and Dinner are imported; it is where `infused_water` and `nonveg_soup` came from | `Chain rules/import_booking_menu.py` |
| `corning_chakan_pune_menu.xlsx` | Pune | Corning Chakan's nine weekly sheets, one column per day, identical row layout on every sheet. **The first client menu for a city other than Bangalore or Chennai**, and the first Maharashtrian list. Lunch and dinner only; the salad block is a salad BAR whose components are ingredients, and one sheet carries an unlabelled Independence Day menu below the grid that is read by dish name rather than position | `Chain rules/import_corning_pune_menu.py`, `Chain rules/marathi_ingredient_names.py` |
| `chennai_client_structure.xlsx` | Chennai | **four clients' rules in their own words**, on `Sheet1`, plus a sample week per client on its own sheet — a different kind of source from Toast Tab's service history, since these are stated rather than inferred. TCL, Gartner, World Bank and ICON Chn. RNTBCI is listed with nothing beside it and an empty sheet: on hold | `docs/chennai_client_logic.md`, `customisation/client rules/{tcl,gartner,world_bank,icon_chn}.json`, `Chain rules/chennai_client_pools.py` |
| `quest_hyderabad_menu_2026.xlsx` | Hyderabad | Quest's 41-day grid (31 Mar – 30 Jul 2026), one column per service day. **The source that created the Hyderabad city list.** Two layouts OFFSET from each other — Tue/Thu carry the full menu in rows 2-13, Wed is the biryani day in rows 5-13 with nothing above — so a column is read on the biryani map exactly when row 2 is blank; on the wrong map the Wednesday veg gravy files as a dal. The two non-veg rows are dry and gravy in that order and the biryani row is a third form, which is evidence no name heuristic has. "Chef Choice Desserts" is a placeholder and the fruit row holds serving counts, not dishes | `Chain rules/import_quest_hyderabad_menu.py`, `city_items/hyderabad.xlsx` |
| `stripe_menu_2026_06_29.xlsx`, `stripe_menu_2026_07_27.xlsx` | Bangalore | Stripe's two sample weeks, three sheets each. **Only the plated lunch and dinner blocks are imported** — the salad bar and the DIY sandwich station are components a diner assembles, not solver slots. The July file's salad-bar block lost a row, so its labels sit one row below their dishes; the importer detects and re-pairs that rather than assuming a layout | `Chain rules/import_stripe_menu.py` |

## Adding a city

**The five workbooks in `../city_items/` are now the SOURCE, not an artefact.**
The owner supplies one cleaned list per city; the normaliser and the chain of
correction scripts that used to rebuild and re-patch them have been deleted.
Nothing in the repo writes to a city list any more, and nothing should.

1. Drop the raw item list here as `<city>_menu_items_raw.xlsx`, plus any
   rulebook or sample menu, so the derived rules stay citable.
2. Put the cleaned list at `../city_items/<city>.xlsx`, in the same 142-column
   schema the five existing ones use. It is used verbatim.
3. Declare the city's categories in `city_items/ontology_categories.json` —
   **only if the city does not cover every mandatory slot.** An undeclared city
   is held to the FULL check, which is the stricter one; declaring a complete
   list only lowers the bar. Hyderabad is deliberately absent for that reason.
4. If the city's rows carry pool tokens that mean nothing there, add it to
   `src.constants.FULL_POOL_CITIES`. Hyderabad had to: it was seeded from
   Bangalore, so ~5,300 of its rows are tagged to Bangalore sites and `common`
   alone is 960 rows holding none of the city's own dishes.
5. Run `tests/data/test_dataset_guards.py`. It reads the workbooks and nothing
   else, and it is what the deleted corrections existed to guarantee: no
   meat-named dish sitting in a veg pool, no misspelled protein word, no
   `nonveg_main` row without a form flag. A failure there is a question for
   the owner, not a workbook to edit.

## A thin pool is a normal state

The chain's job was to top pools up — ten sambars copied into NCR from
Bangalore, sixteen north rices, seven side dishes per city. Without it a city
carries exactly what its owner put in it, and some pools are genuinely small:
NCR has one `sambar` row and three `rasam`.

So code that narrows a pool must degrade rather than fail, and must say so on
the relaxation channel. `_combo_variant_cells` in `src/solver/menu_solver.py`
is the worked example — a combination slot used to pin itself to a component
with fewer dishes than it had days, which was INFEASIBLE with no diagnostic.
A rule that cannot bite on a city's real list is a fact to report, not a gap
to fill.
