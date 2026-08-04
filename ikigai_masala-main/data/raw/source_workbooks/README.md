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

Only Bangalore's sample history was committed before; Pune's and Chennai's raw
lists, the Pune rulebook and Chennai's sample menu existed only as chat
attachments and would have been lost.

| File | City | What it is | Used to produce |
|---|---|---|---|
| `bangalore_menu_samples_history.xlsx` | Bangalore | printed menus as served | `docs/client_logics.md` |
| `bangalore_menu_samples_1.xlsx` | Bangalore | earlier sample extract | `docs/client_logics.md` |
| `pune_menu_items_raw.xlsx` | Pune | raw item list before normalisation | `city_items/pune.xlsx` |
| `pune_menu_rulebook_101.xlsx` | Pune | **the 70-rule rulebook** | `docs/pune_rulebook.md`, `configs/city_rules/pune.json` |
| `chennai_menu_items_raw.xlsx` | Chennai | raw item list, incl. its own `Mapping_Log` sheet | `city_items/chennai.xlsx` |
| `chennai_sample_menu.xlsx` | Chennai | Toast Tab's 7-day service history (sheet `Toasttab`) | `docs/chennai_client_logic.md`, the `ToastTab CHN` client rules |
| `menu_implementation_tracker.xlsx` | — | cross-city delivery tracker | — |

## Adding a city

1. Drop the raw item list here as `<city>_menu_items_raw.xlsx`, plus any rulebook
   or sample menu.
2. `python scripts/normalize_city_ontology.py <city> data/raw/source_workbooks/<city>_menu_items_raw.xlsx --dry-run`
   then again without `--dry-run` to write `city_items/<city>.xlsx`.
3. Re-run the correction scripts — the normaliser rebuilds the workbook from the
   raw list and drops hand-applied fixes: `scripts/seafood_taxonomy.py`,
   `scripts/pune_flag_corrections.py`, `scripts/chennai_course_corrections.py`.
   Each is idempotent, and each has a test that fails if its corrections are
   missing.
4. Declare the city's categories in `city_items/ontology_categories.json`.
